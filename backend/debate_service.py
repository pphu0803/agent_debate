"""思想孵化机 - 辩论编排服务"""
import json
import asyncio
import logging
from datetime import datetime
from typing import AsyncGenerator, Optional
from bson import ObjectId

from config import config
from models import AgentRole, CreateDebateRequest
from agents import AGENTS, AGENT_ORDER, AGENT_NAMES, AGENT_COLORS, AGENT_ICONS
from llm_service import llm_service

logger = logging.getLogger(__name__)

# SSE轮询间隔（秒）
POLL_INTERVAL = 2


class DebateService:
    """辩论编排服务：管理辩论生命周期、Agent轮转、上下文压缩、评分判定

    架构说明：
    - 辩论逻辑在后台asyncio任务中运行（_execute_debate），不依赖SSE连接
    - 所有事件存入MongoDB的events数组，带序号seq
    - SSE端点（stream_debate）回放历史事件后轮询新事件
    - 客户端断开重连时自动恢复，不丢失任何事件
    """

    def __init__(self):
        self.db = None
        self._active_debates: dict = {}   # debate_id -> bool (是否正在运行)
        self._debate_tasks: dict = {}      # debate_id -> asyncio.Task
        self._paused_debates: dict = {}     # debate_id -> bool (暂停标志)
        self._event_locks: dict = {}        # debate_id -> asyncio.Lock (事件写入锁)

    def init_db(self, db):
        self.db = db

    # ==================== 辩论CRUD ====================

    async def create_debate(self, request: CreateDebateRequest) -> dict:
        """创建新辩论"""
        debate = {
            "topic": request.topic,
            "status": "pending",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "current_round": 0,
            "messages": [],
            "events": [],
            "scores": {
                AgentRole.INNOVATOR.value: 0,
                AgentRole.CRITIC.value: 0,
                AgentRole.SCHOLAR.value: 0,
            },
            "final_summary": None,
            "config": {
                "max_rounds": request.max_rounds or config.MAX_ROUNDS,
                "score_threshold": request.score_threshold or config.SCORE_THRESHOLD,
            },
        }
        result = await self.db.debates.insert_one(debate)
        debate_id = str(result.inserted_id)
        logger.info(f"创建辩论: id={debate_id}, topic={request.topic[:50]}")
        return {"debate_id": debate_id, "topic": request.topic}

    async def get_debate(self, debate_id: str) -> Optional[dict]:
        """获取辩论详情"""
        if not ObjectId.is_valid(debate_id):
            return None
        debate = await self.db.debates.find_one({"_id": ObjectId(debate_id)})
        if debate:
            debate["id"] = str(debate["_id"])
            del debate["_id"]
            return debate
        return None

    async def list_debates(self, limit: int = 50) -> list:
        """获取辩论列表"""
        debates = []
        async for d in self.db.debates.find().sort("created_at", -1).limit(limit):
            status = d.get("status", "unknown")
            debates.append({
                "id": str(d["_id"]),
                "topic": d["topic"],
                "status": status,
                "created_at": d["created_at"].isoformat() if isinstance(d.get("created_at"), datetime) else str(d.get("created_at", "")),
                "current_round": d.get("current_round", 0),
                "message_count": len(d.get("messages", [])),
                "final_summary": d.get("final_summary"),
                "is_resumable": status in ("ongoing", "paused"),
            })
        return debates

    async def stop_debate(self, debate_id: str) -> bool:
        """终止辩论"""
        if not ObjectId.is_valid(debate_id):
            return False
        self._active_debates[debate_id] = False
        self._paused_debates[debate_id] = False
        result = await self.db.debates.update_one(
            {"_id": ObjectId(debate_id)},
            {"$set": {"status": "terminated", "updated_at": datetime.now()}}
        )
        return result.modified_count > 0

    async def pause_debate(self, debate_id: str) -> bool:
        """暂停辩论（不终止，可恢复）"""
        if not ObjectId.is_valid(debate_id):
            return False
        debate = await self.get_debate(debate_id)
        if not debate or debate["status"] != "ongoing":
            return False
        self._paused_debates[debate_id] = True
        await self.db.debates.update_one(
            {"_id": ObjectId(debate_id)},
            {"$set": {"status": "paused", "updated_at": datetime.now()}}
        )
        await self._save_event(debate_id, {"type": "paused"})
        logger.info(f"辩论 {debate_id} 已暂停")
        return True

    async def resume_debate(self, debate_id: str) -> bool:
        """恢复暂停的辩论"""
        if not ObjectId.is_valid(debate_id):
            return False
        debate = await self.get_debate(debate_id)
        if not debate or debate["status"] != "paused":
            return False
        self._paused_debates[debate_id] = False
        await self.db.debates.update_one(
            {"_id": ObjectId(debate_id)},
            {"$set": {"status": "ongoing", "updated_at": datetime.now()}}
        )
        await self._save_event(debate_id, {"type": "resumed"})
        logger.info(f"辩论 {debate_id} 已恢复")
        return True

    async def inject_message(self, debate_id: str, content: str) -> Optional[dict]:
        """注入用户消息到messages数组"""
        if not ObjectId.is_valid(debate_id):
            return None
        debate = await self.get_debate(debate_id)
        if not debate:
            return None
        if debate["status"] not in ("ongoing", "paused"):
            return None

        current_round = debate.get("current_round", 0)
        msg = {
            "agent": "user",
            "role": "user",
            "round": current_round,
            "content": content,
            "score": None,
            "score_reason": None,
            "timestamp": datetime.now().isoformat(),
            "is_summary": False,
            "is_user": True,
        }
        await self._save_message(debate_id, msg)
        await self._save_event(debate_id, {
            "type": "user_message",
            "content": content,
            "round": current_round,
        })
        logger.info(f"用户消息已注入辩论 {debate_id}")
        return {"status": "injected", "message": msg}

    async def _wait_if_paused(self, debate_id: str) -> bool:
        """等待暂停结束，返回False表示被终止"""
        while self._paused_debates.get(debate_id, False):
            if not self._active_debates.get(debate_id, True):
                return False
            await asyncio.sleep(0.5)
        return True

    def _get_event_lock(self, debate_id: str) -> asyncio.Lock:
        """获取辩论的事件写入锁"""
        if debate_id not in self._event_locks:
            self._event_locks[debate_id] = asyncio.Lock()
        return self._event_locks[debate_id]

    # ==================== SSE流式接口 ====================

    async def stream_debate(self, debate_id: str) -> AsyncGenerator[dict, None]:
        """SSE端点：回放历史事件 + 轮询新事件

        这个方法不执行辩论逻辑，只负责把事件推送给客户端。
        辩论逻辑在后台asyncio任务中运行。
        """
        debate = await self.get_debate(debate_id)
        if not debate:
            yield {"data": json.dumps({"type": "error", "message": "辩论不存在"}, ensure_ascii=False)}
            return

        # 如果辩论还没开始，或服务重启后需要恢复，启动后台任务
        if debate["status"] == "pending" and not self._active_debates.get(debate_id, False):
            self._start_debate_background(debate_id)
            await asyncio.sleep(0.5)
        elif debate["status"] in ("ongoing", "paused") and not self._active_debates.get(debate_id, False):
            # 服务重启后恢复：debate状态为ongoing/paused但后台任务不存在
            self._resume_debate_background(debate_id)
            await asyncio.sleep(0.5)

        # 发送reset事件，让前端清空旧消息（处理重连场景）
        yield {"data": json.dumps({
            "type": "reset",
            "debate_id": debate_id,
            "topic": debate["topic"],
            "status": debate.get("status", "unknown"),
            "current_round": debate.get("current_round", 0),
            "scores": debate.get("scores", {}),
            "final_summary": debate.get("final_summary"),
            "is_paused": self._paused_debates.get(debate_id, False),
        }, ensure_ascii=False)}

        # 回放已有事件
        last_seq = -1
        events = debate.get("events", [])
        for event in events:
            last_seq = event["seq"]
            yield {"data": json.dumps(event, ensure_ascii=False)}

        # 如果辩论已结束，发完历史事件后直接返回
        if debate["status"] in ("completed", "terminated"):
            return

        # 轮询新事件
        while True:
            await asyncio.sleep(POLL_INTERVAL)

            # 检查是否被手动终止
            if not self._active_debates.get(debate_id, True):
                # 可能已被终止，再查一次DB确认
                debate = await self.get_debate(debate_id)
                if debate and debate["status"] in ("completed", "terminated"):
                    # 发送终止事件
                    yield {"data": json.dumps({
                        "type": "stopped",
                        "message": "辩论已被手动终止",
                    }, ensure_ascii=False)}
                    return

            debate = await self.get_debate(debate_id)
            if not debate:
                yield {"data": json.dumps({"type": "error", "message": "辩论数据丢失"}, ensure_ascii=False)}
                return

            # 发送新事件
            new_events = [e for e in debate.get("events", []) if e["seq"] > last_seq]
            for event in new_events:
                last_seq = event["seq"]
                yield {"data": json.dumps(event, ensure_ascii=False)}

            # 检查是否结束
            if debate["status"] in ("completed", "terminated"):
                return

    # ==================== 后台辩论执行 ====================

    def _start_debate_background(self, debate_id: str):
        """启动后台辩论任务"""
        if self._active_debates.get(debate_id, False):
            logger.warning(f"辩论 {debate_id} 已在运行中，跳过重复启动")
            return
        self._active_debates[debate_id] = True
        task = asyncio.create_task(self._execute_debate(debate_id))
        self._debate_tasks[debate_id] = task
        logger.info(f"后台辩论任务已启动: {debate_id}")

    def _resume_debate_background(self, debate_id: str):
        """恢复中断的辩论（服务重启后）"""
        if self._active_debates.get(debate_id, False):
            logger.warning(f"辩论 {debate_id} 已在运行中，跳过恢复")
            return
        self._active_debates[debate_id] = True
        task = asyncio.create_task(self._resume_debate_task(debate_id))
        self._debate_tasks[debate_id] = task
        logger.info(f"后台辩论任务已恢复: {debate_id}")

    async def _resume_debate_task(self, debate_id: str):
        """恢复执行中断的辩论"""
        try:
            debate = await self.get_debate(debate_id)
            if not debate:
                return

            topic = debate["topic"]
            max_rounds = debate.get("config", {}).get("max_rounds", config.MAX_ROUNDS)
            score_threshold = debate.get("config", {}).get("score_threshold", config.SCORE_THRESHOLD)
            current_round = debate.get("current_round", 0)
            messages = debate.get("messages", [])

            # 分析当前轮次已完成哪些Agent的发言
            agents_done_in_round = set()
            for msg in messages:
                if msg.get("round") == current_round and not msg.get("is_summary") and not msg.get("is_user"):
                    agents_done_in_round.add(msg.get("agent"))

            # 计算剩余需要发言的Agent
            remaining_agents = [a for a in AGENT_ORDER if a.value not in agents_done_in_round]

            # 如果当前轮次所有Agent都已发言，从下一轮开始
            if not remaining_agents:
                start_round = current_round + 1
                remaining_agents = list(AGENT_ORDER)
            else:
                start_round = current_round

            logger.info(f"恢复辩论 {debate_id}: 从第{start_round}轮开始, "
                        f"剩余Agent: {[a.value for a in remaining_agents]}")

            # 如果之前是暂停状态，保持暂停
            if debate["status"] == "paused":
                self._paused_debates[debate_id] = True
            else:
                # 更新状态为进行中
                await self.db.debates.update_one(
                    {"_id": ObjectId(debate_id)},
                    {"$set": {"status": "ongoing", "updated_at": datetime.now()}}
                )

            await self._save_event(debate_id, {
                "type": "resumed_from_interruption",
                "resume_round": start_round,
            })

            await self._continue_debate_loop(
                debate_id, topic, start_round, max_rounds,
                score_threshold, remaining_agents
            )

        except Exception as e:
            logger.error(f"恢复辩论异常: {e}", exc_info=True)
            self._active_debates[debate_id] = False
            await self.db.debates.update_one(
                {"_id": ObjectId(debate_id)},
                {"$set": {"status": "terminated", "updated_at": datetime.now()}}
            )
            await self._save_event(debate_id, {
                "type": "error",
                "message": f"恢复失败: {str(e)}",
            })

    async def _continue_debate_loop(self, debate_id: str, topic: str,
                                    start_round: int, max_rounds: int,
                                    score_threshold: int,
                                    first_round_agents: list):
        """从指定轮次继续辩论循环

        first_round_agents: 第一轮（恢复轮）中还需要发言的Agent列表
        后续轮次使用完整的AGENT_ORDER
        """
        for round_num in range(start_round, max_rounds + 1):
            # 终止检查
            if not self._active_debates.get(debate_id, False):
                await self._save_event(debate_id, {
                    "type": "stopped", "message": "辩论已被手动终止",
                })
                return

            # 暂停检查
            if not await self._wait_if_paused(debate_id):
                await self._save_event(debate_id, {
                    "type": "stopped", "message": "辩论已被手动终止",
                })
                return

            # 更新当前轮次
            await self.db.debates.update_one(
                {"_id": ObjectId(debate_id)},
                {"$set": {"current_round": round_num, "updated_at": datetime.now()}}
            )

            await self._save_event(debate_id, {
                "type": "round_start", "round": round_num,
            })

            # 获取当前消息历史
            current_debate = await self.get_debate(debate_id)
            messages = current_debate.get("messages", [])

            # 上下文压缩检查
            if self._estimate_tokens(messages) > config.MAX_CONTEXT_TOKENS and len(messages) > 6:
                old_messages = messages[:-4]
                recent_messages = messages[-4:]
                summary = await self._compress_history(old_messages)
                summary_msg = {
                    "agent": "system", "role": "system",
                    "round": round_num - 1, "content": summary,
                    "timestamp": datetime.now().isoformat(), "is_summary": True,
                }
                await self._save_message(debate_id, summary_msg)
                messages = [summary_msg] + recent_messages
                await self._save_event(debate_id, {
                    "type": "context_compressed", "summary": summary, "round": round_num,
                })

            # 第一轮用传入的剩余Agent，后续轮用完整顺序
            agents_this_round = first_round_agents if round_num == start_round else list(AGENT_ORDER)

            for agent_role in agents_this_round:
                if not self._active_debates.get(debate_id, False):
                    await self._save_event(debate_id, {
                        "type": "stopped", "message": "辩论已被手动终止",
                    })
                    return

                if not await self._wait_if_paused(debate_id):
                    await self._save_event(debate_id, {
                        "type": "stopped", "message": "辩论已被手动终止",
                    })
                    return

                agent = AGENTS[agent_role]
                await self._save_event(debate_id, {
                    "type": "agent_thinking", "agent": agent_role.value,
                    "agent_name": agent.name, "agent_icon": AGENT_ICONS[agent_role],
                    "round": round_num,
                })

                try:
                    content, score, score_reason, is_skip = await agent.respond(topic, messages, round_num)
                    msg = {
                        "agent": agent_role.value, "role": agent_role.value,
                        "round": round_num, "content": content,
                        "score": score, "score_reason": score_reason,
                        "timestamp": datetime.now().isoformat(),
                        "is_summary": False, "is_skip": is_skip,
                    }
                    await self._save_message(debate_id, msg)
                    messages.append(msg)

                    if is_skip:
                        await self._save_event(debate_id, {
                            "type": "agent_skip", "agent": agent_role.value,
                            "agent_name": agent.name, "agent_icon": AGENT_ICONS[agent_role],
                            "round": round_num, "score": score, "score_reason": score_reason,
                            "timestamp": msg["timestamp"],
                        })
                    else:
                        await self._save_event(debate_id, {
                            "type": "agent_message", "agent": agent_role.value,
                            "agent_name": agent.name, "agent_icon": AGENT_ICONS[agent_role],
                            "round": round_num, "content": content,
                            "score": score, "score_reason": score_reason,
                            "timestamp": msg["timestamp"],
                        })
                except Exception as e:
                    logger.error(f"Agent {agent.name} 发言失败: {e}")
                    await self._save_event(debate_id, {
                        "type": "error", "message": f"{agent.name} 发言失败: {str(e)}",
                    })
                    await self.db.debates.update_one(
                        {"_id": ObjectId(debate_id)},
                        {"$set": {"status": "terminated", "updated_at": datetime.now()}}
                    )
                    self._active_debates[debate_id] = False
                    return

            # 暂停检查
            if not await self._wait_if_paused(debate_id):
                return

            # 辩论组织者复盘
            moderator_status = await self._run_moderator(debate_id, topic, round_num, messages)
            if moderator_status == "DEAD_END":
                await self._save_event(debate_id, {
                    "type": "generating_report", "reason": "dead_end",
                })
                report = await self._generate_report(debate_id, topic)
                await self.db.debates.update_one(
                    {"_id": ObjectId(debate_id)},
                    {"$set": {"status": "completed", "final_summary": report, "updated_at": datetime.now()}}
                )
                current_debate = await self.get_debate(debate_id)
                scores = current_debate.get("scores", {})
                await self._save_event(debate_id, {
                    "type": "complete", "report": report, "scores": scores,
                    "total_rounds": round_num, "consensus": False,
                    "end_reason": "讨论已达到需要实验/实证验证的瓶颈",
                })
                self._active_debates[debate_id] = False
                return

            # 检查共识
            current_debate = await self.get_debate(debate_id)
            scores = current_debate.get("scores", {})
            await self._save_event(debate_id, {
                "type": "round_complete", "round": round_num,
                "scores": scores, "score_threshold": score_threshold,
            })

            score_values = [v for v in scores.values() if v > 0]
            if len(score_values) == 3 and all(s >= score_threshold for s in score_values):
                await self._save_event(debate_id, {"type": "generating_report"})
                report = await self._generate_report(debate_id, topic)
                await self.db.debates.update_one(
                    {"_id": ObjectId(debate_id)},
                    {"$set": {"status": "completed", "final_summary": report, "updated_at": datetime.now()}}
                )
                await self._save_event(debate_id, {
                    "type": "complete", "report": report, "scores": scores,
                    "total_rounds": round_num, "consensus": True,
                })
                self._active_debates[debate_id] = False
                return

        # 达到最大轮次
        await self._save_event(debate_id, {"type": "generating_report"})
        report = await self._generate_report(debate_id, topic)
        await self.db.debates.update_one(
            {"_id": ObjectId(debate_id)},
            {"$set": {"status": "completed", "final_summary": report, "updated_at": datetime.now()}}
        )
        current_debate = await self.get_debate(debate_id)
        scores = current_debate.get("scores", {})
        await self._save_event(debate_id, {
            "type": "complete", "report": report, "scores": scores,
            "total_rounds": max_rounds, "consensus": False,
        })
        self._active_debates[debate_id] = False

    async def _execute_debate(self, debate_id: str):
        """执行辩论逻辑（后台任务），将事件存入DB

        这个方法不直接yield给SSE，而是把事件存入DB的events数组。
        SSE端点通过轮询DB获取新事件。
        """
        try:
            debate = await self.get_debate(debate_id)
            if not debate:
                logger.error(f"辩论 {debate_id} 不存在")
                return

            topic = debate["topic"]
            max_rounds = debate.get("config", {}).get("max_rounds", config.MAX_ROUNDS)
            score_threshold = debate.get("config", {}).get("score_threshold", config.SCORE_THRESHOLD)

            # 更新状态为进行中
            await self.db.debates.update_one(
                {"_id": ObjectId(debate_id)},
                {"$set": {"status": "ongoing", "updated_at": datetime.now()}}
            )

            # 发送开始事件
            await self._save_event(debate_id, {
                "type": "start",
                "topic": topic,
                "max_rounds": max_rounds,
                "score_threshold": score_threshold,
                "agents": [
                    {
                        "role": role.value,
                        "name": AGENTS[role].name,
                        "description": AGENTS[role].description,
                        "color": AGENT_COLORS[role],
                        "icon": AGENT_ICONS[role],
                    }
                    for role in AGENT_ORDER
                ],
            })

            # 辩论组织者进行议题分析
            await self._save_event(debate_id, {
                "type": "topic_analysis_start",
            })
            try:
                from agents import MODERATOR_ROLE
                moderator = AGENTS[MODERATOR_ROLE]
                analysis = await moderator.analyze_topic(topic)
                if analysis:
                    # 存入辩论文档
                    await self.db.debates.update_one(
                        {"_id": ObjectId(debate_id)},
                        {"$set": {"topic_analysis": analysis, "updated_at": datetime.now()}}
                    )
                    await self._save_event(debate_id, {
                        "type": "topic_analysis",
                        "content": analysis,
                    })
            except Exception as e:
                logger.error(f"议题分析失败: {e}", exc_info=True)
                await self._save_event(debate_id, {
                    "type": "topic_analysis",
                    "content": "议题分析失败，跳过。",
                })

            # 主循环
            for round_num in range(1, max_rounds + 1):
                if not self._active_debates.get(debate_id, False):
                    await self._save_event(debate_id, {
                        "type": "stopped",
                        "message": "辩论已被手动终止",
                    })
                    return

                # 暂停检查：等待用户恢复
                if not await self._wait_if_paused(debate_id):
                    await self._save_event(debate_id, {
                        "type": "stopped",
                        "message": "辩论已被手动终止",
                    })
                    return

                await self.db.debates.update_one(
                    {"_id": ObjectId(debate_id)},
                    {"$set": {"current_round": round_num, "updated_at": datetime.now()}}
                )

                await self._save_event(debate_id, {
                    "type": "round_start",
                    "round": round_num,
                })

                # 获取当前消息历史
                current_debate = await self.get_debate(debate_id)
                messages = current_debate.get("messages", [])

                # 上下文压缩检查
                if self._estimate_tokens(messages) > config.MAX_CONTEXT_TOKENS and len(messages) > 6:
                    old_messages = messages[:-4]
                    recent_messages = messages[-4:]

                    summary = await self._compress_history(old_messages)
                    summary_msg = {
                        "agent": "system",
                        "role": "system",
                        "round": round_num - 1,
                        "content": summary,
                        "timestamp": datetime.now().isoformat(),
                        "is_summary": True,
                    }
                    await self._save_message(debate_id, summary_msg)
                    messages = [summary_msg] + recent_messages

                    await self._save_event(debate_id, {
                        "type": "context_compressed",
                        "summary": summary,
                        "round": round_num,
                    })

                # 每个Agent依次发言
                for agent_role in AGENT_ORDER:
                    if not self._active_debates.get(debate_id, False):
                        await self._save_event(debate_id, {
                            "type": "stopped",
                            "message": "辩论已被手动终止",
                        })
                        return

                    # 暂停检查：等待用户恢复
                    if not await self._wait_if_paused(debate_id):
                        await self._save_event(debate_id, {
                            "type": "stopped",
                            "message": "辩论已被手动终止",
                        })
                        return

                    agent = AGENTS[agent_role]

                    await self._save_event(debate_id, {
                        "type": "agent_thinking",
                        "agent": agent_role.value,
                        "agent_name": agent.name,
                        "agent_icon": AGENT_ICONS[agent_role],
                        "round": round_num,
                    })

                    try:
                        content, score, score_reason, is_skip = await agent.respond(topic, messages, round_num)

                        msg = {
                            "agent": agent_role.value,
                            "role": agent_role.value,
                            "round": round_num,
                            "content": content,
                            "score": score,
                            "score_reason": score_reason,
                            "timestamp": datetime.now().isoformat(),
                            "is_summary": False,
                            "is_skip": is_skip,
                        }
                        await self._save_message(debate_id, msg)
                        messages.append(msg)

                        if is_skip:
                            await self._save_event(debate_id, {
                                "type": "agent_skip",
                                "agent": agent_role.value,
                                "agent_name": agent.name,
                                "agent_icon": AGENT_ICONS[agent_role],
                                "round": round_num,
                                "score": score,
                                "score_reason": score_reason,
                                "timestamp": msg["timestamp"],
                            })
                        else:
                            await self._save_event(debate_id, {
                                "type": "agent_message",
                                "agent": agent_role.value,
                                "agent_name": agent.name,
                                "agent_icon": AGENT_ICONS[agent_role],
                                "round": round_num,
                                "content": content,
                                "score": score,
                                "score_reason": score_reason,
                                "timestamp": msg["timestamp"],
                        })

                    except Exception as e:
                        logger.error(f"Agent {agent.name} 发言失败: {e}")
                        await self._save_event(debate_id, {
                            "type": "error",
                            "message": f"{agent.name} 发言失败: {str(e)}",
                        })
                        # 出错后终止辩论
                        await self.db.debates.update_one(
                            {"_id": ObjectId(debate_id)},
                            {"$set": {"status": "terminated", "updated_at": datetime.now()}}
                        )
                        self._active_debates[debate_id] = False
                        return

                # 检查评分
                # 暂停检查：等待用户恢复
                if not await self._wait_if_paused(debate_id):
                    await self._save_event(debate_id, {
                        "type": "stopped",
                        "message": "辩论已被手动终止",
                    })
                    return

                # 辩论组织者复盘
                moderator_status = await self._run_moderator(debate_id, topic, round_num, messages)
                if moderator_status == "DEAD_END":
                    # 死胡同：停止讨论，生成报告
                    await self._save_event(debate_id, {
                        "type": "generating_report",
                        "reason": "dead_end",
                    })
                    report = await self._generate_report(debate_id, topic)
                    await self.db.debates.update_one(
                        {"_id": ObjectId(debate_id)},
                        {"$set": {
                            "status": "completed",
                            "final_summary": report,
                            "updated_at": datetime.now(),
                        }}
                    )
                    current_debate = await self.get_debate(debate_id)
                    scores = current_debate.get("scores", {})
                    await self._save_event(debate_id, {
                        "type": "complete",
                        "report": report,
                        "scores": scores,
                        "total_rounds": round_num,
                        "consensus": False,
                        "end_reason": "讨论已达到需要实验/实证验证的瓶颈",
                    })
                    self._active_debates[debate_id] = False
                    logger.info(f"辩论 {debate_id} 因死胡同结束（第{round_num}轮）")
                    return

                current_debate = await self.get_debate(debate_id)
                scores = current_debate.get("scores", {})

                await self._save_event(debate_id, {
                    "type": "round_complete",
                    "round": round_num,
                    "scores": scores,
                    "score_threshold": score_threshold,
                })

                # 检查是否达成共识
                score_values = [v for v in scores.values() if v > 0]
                if len(score_values) == 3 and all(s >= score_threshold for s in score_values):
                    await self._save_event(debate_id, {"type": "generating_report"})

                    report = await self._generate_report(debate_id, topic)

                    await self.db.debates.update_one(
                        {"_id": ObjectId(debate_id)},
                        {"$set": {
                            "status": "completed",
                            "final_summary": report,
                            "updated_at": datetime.now(),
                        }}
                    )

                    await self._save_event(debate_id, {
                        "type": "complete",
                        "report": report,
                        "scores": scores,
                        "total_rounds": round_num,
                        "consensus": True,
                    })

                    self._active_debates[debate_id] = False
                    logger.info(f"辩论 {debate_id} 已完成（达成共识，{round_num}轮）")
                    return

            # 达到最大轮次，未达成共识
            await self._save_event(debate_id, {"type": "generating_report"})
            report = await self._generate_report(debate_id, topic)

            await self.db.debates.update_one(
                {"_id": ObjectId(debate_id)},
                {"$set": {
                    "status": "completed",
                    "final_summary": report,
                    "updated_at": datetime.now(),
                }}
            )

            current_debate = await self.get_debate(debate_id)
            scores = current_debate.get("scores", {})

            await self._save_event(debate_id, {
                "type": "complete",
                "report": report,
                "scores": scores,
                "total_rounds": max_rounds,
                "consensus": False,
            })

            self._active_debates[debate_id] = False
            logger.info(f"辩论 {debate_id} 已完成（达到最大轮次）")

        except Exception as e:
            logger.error(f"辩论执行异常: {e}", exc_info=True)
            self._active_debates[debate_id] = False
            await self.db.debates.update_one(
                {"_id": ObjectId(debate_id)},
                {"$set": {"status": "terminated", "updated_at": datetime.now()}}
            )
            await self._save_event(debate_id, {
                "type": "error",
                "message": f"服务器错误: {str(e)}",
            })

    # ==================== 辅助方法 ====================

    async def _save_event(self, debate_id: str, event_data: dict):
        """存储SSE事件到DB，自动分配序号（加锁防止并发冲突）"""
        if not ObjectId.is_valid(debate_id):
            return

        async with self._get_event_lock(debate_id):
            debate = await self.get_debate(debate_id)
            if not debate:
                return
            seq = len(debate.get("events", []))
            event = {
                "seq": seq,
                **event_data,
                "timestamp": datetime.now().isoformat(),
            }
            await self.db.debates.update_one(
                {"_id": ObjectId(debate_id)},
                {"$push": {"events": event}}
            )

    async def _run_moderator(self, debate_id: str, topic: str, round_num: int, messages: list) -> str:
        """运行辩论组织者复盘，返回状态: CONTINUE / DEAD_END / REDIRECT"""
        from agents import MODERATOR_ROLE, AGENTS, AGENT_ICONS

        moderator = AGENTS[MODERATOR_ROLE]

        await self._save_event(debate_id, {
            "type": "agent_thinking",
            "agent": MODERATOR_ROLE.value,
            "agent_name": moderator.name,
            "agent_icon": AGENT_ICONS[MODERATOR_ROLE],
            "round": round_num,
        })

        try:
            content, score, score_reason, status, redirect_topic = await moderator.respond_moderator(topic, messages, round_num)

            msg = {
                "agent": MODERATOR_ROLE.value,
                "role": MODERATOR_ROLE.value,
                "round": round_num,
                "content": content,
                "score": score,
                "score_reason": score_reason,
                "timestamp": datetime.now().isoformat(),
                "is_summary": False,
            }
            await self._save_message(debate_id, msg)
            messages.append(msg)

            # 发送组织者消息事件
            event_data = {
                "type": "agent_message",
                "agent": MODERATOR_ROLE.value,
                "agent_name": moderator.name,
                "agent_icon": AGENT_ICONS[MODERATOR_ROLE],
                "round": round_num,
                "content": content,
                "score": score,
                "score_reason": score_reason,
                "timestamp": msg["timestamp"],
                "moderator_status": status,
            }
            if redirect_topic:
                event_data["redirect_topic"] = redirect_topic
            await self._save_event(debate_id, event_data)

            # 发送组织者状态事件
            if status == "REDIRECT":
                await self._save_event(debate_id, {
                    "type": "topic_redirect",
                    "round": round_num,
                    "redirect_topic": redirect_topic,
                    "message": f"讨论偏离了原始议题，组织者建议拉回：{redirect_topic}",
                })
            elif status == "DEAD_END":
                await self._save_event(debate_id, {
                    "type": "dead_end",
                    "round": round_num,
                    "message": "讨论已达到需要实验或实证数据验证的瓶颈",
                })

            logger.info(f"辩论 {debate_id} 第{round_num}轮组织者状态: {status}")
            return status

        except Exception as e:
            logger.error(f"Moderator 发言失败: {e}")
            # 组织者出错不终止辩论，跳过本轮复盘
            return "CONTINUE"

    async def _save_message(self, debate_id: str, message: dict):
        """保存消息到数据库"""
        await self.db.debates.update_one(
            {"_id": ObjectId(debate_id)},
            {
                "$push": {"messages": message},
                "$set": {
                    "updated_at": datetime.now(),
                    f"scores.{message.get('agent', message.get('role', ''))}": message.get("score", 0),
                }
            }
        )

    async def _compress_history(self, messages: list) -> str:
        """压缩历史发言记录"""
        history_text = ""
        for msg in messages:
            if msg.get("is_summary"):
                history_text += f"[历史总结]\n{msg['content'][:800]}\n\n"
            else:
                agent_name = AGENT_NAMES.get(
                    AgentRole(msg.get("agent") or msg.get("role", "")), "未知"
                )
                history_text += f"[{agent_name} - 第{msg.get('round', '?')}轮]\n{msg['content'][:800]}\n"
                if msg.get("score"):
                    history_text += f"评分: {msg['score']}/10\n"
                history_text += "\n"

        prompt = f"""请将以下辩论历史压缩为一个精炼的总结，保留：
1. 各方提出的核心观点和关键概念
2. 主要的争议和分歧点
3. 已达成的部分共识
4. 各方的评分趋势

辩论历史：
{history_text}

请输出一个600字以内的总结。"""

        return await llm_service.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000
        )

    def _estimate_tokens(self, messages: list) -> int:
        """粗略估算token数量"""
        total_chars = sum(len(msg.get("content", "")) for msg in messages)
        return total_chars // 3  # 中文约2-3字符/token

    async def _generate_report(self, debate_id: str, topic: str) -> str:
        """生成最终总结报告"""
        debate = await self.get_debate(debate_id)
        messages = debate.get("messages", [])
        scores = debate.get("scores", {})

        history_text = ""
        for msg in messages:
            if msg.get("is_summary"):
                history_text += f"📋 [历史总结]\n{msg['content']}\n\n"
            else:
                agent_name = AGENT_NAMES.get(
                    AgentRole(msg.get("agent") or msg.get("role", "")), "未知"
                )
                history_text += f"👤 [{agent_name} - 第{msg.get('round', '?')}轮]\n{msg['content']}\n"
                if msg.get("score"):
                    history_text += f"📊 评分: {msg['score']}/10 - {msg.get('score_reason', '')}\n"
                history_text += "\n"

        score_lines = "\n".join(
            f"- {AGENT_NAMES[AgentRole(k)]}: {v}/10"
            for k, v in scores.items() if v > 0
        )

        prompt = f"""请为以下辩论生成一份完整的总结报告。

辩论主题：{topic}

辩论记录：
{history_text}

各参与者最终评分：
{score_lines}

请严格按照以下Markdown格式输出报告：

## 🧠 思想孵化报告

### 📌 议题
{topic}

### 💡 核心观点
（总结3个Agent讨论中产生的主要观点和创新概念，每个观点用一段话说明）

### ⚔️ 关键争议
（总结讨论中的主要分歧和争议点，包括反对者提出的核心批评）

### 🤝 达成的共识
（总结各方最终达成一致的结论）

### ❓ 未解决的问题
（总结尚未解决或仍有分歧的问题）

### 🔮 结论与展望
（最终的综合性结论和未来可能的发展方向）

### 📊 参与者评分
{score_lines}

### 📝 辩论轮次
共进行了 {debate.get('current_round', 0)} 轮讨论"""

        return await llm_service.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=3000
        )

    # ==================== 导出功能 ====================

    async def export_debate(self, debate_id: str, fmt: str):
        """多格式导出辩论"""
        if not ObjectId.is_valid(debate_id):
            return None
        debate = await self.get_debate(debate_id)
        if not debate:
            return None

        if fmt == "json":
            return self._export_json(debate)
        elif fmt == "md":
            return self._export_markdown(debate)
        elif fmt == "summary":
            return await self._export_summary(debate)
        elif fmt == "report":
            return debate.get("final_summary") or "报告尚未生成（辩论未完成）"
        return None

    def _export_json(self, debate: dict) -> dict:
        """导出完整JSON数据"""
        return {
            "id": debate["id"],
            "topic": debate["topic"],
            "status": debate.get("status", "unknown"),
            "created_at": debate["created_at"].isoformat() if isinstance(debate.get("created_at"), datetime) else str(debate.get("created_at", "")),
            "current_round": debate.get("current_round", 0),
            "config": debate.get("config", {}),
            "scores": debate.get("scores", {}),
            "messages": debate.get("messages", []),
            "final_summary": debate.get("final_summary"),
        }

    def _export_markdown(self, debate: dict) -> str:
        """导出完整辩论记录Markdown"""
        topic = debate["topic"]
        messages = debate.get("messages", [])
        scores = debate.get("scores", {})

        lines = [
            "# 思想孵化机 - 辩论记录",
            "",
            f"**议题:** {topic}",
            f"**状态:** {debate.get('status', 'unknown')}",
            f"**轮次:** {debate.get('current_round', 0)}",
            f"**创建时间:** {debate.get('created_at', '')}",
            "",
            "---",
            "",
        ]

        current_round = 0
        for msg in messages:
            if msg.get("is_summary"):
                lines.append("### [上下文压缩]")
                lines.append(msg.get("content", ""))
                lines.append("")
                continue

            if msg.get("round", 0) != current_round:
                current_round = msg["round"]
                lines.append(f"## 第 {current_round} 轮")
                lines.append("")

            if msg.get("is_user"):
                agent_name = "用户"
            else:
                try:
                    agent_name = AGENT_NAMES.get(
                        AgentRole(msg.get("agent") or msg.get("role", "")), msg.get("agent", "未知")
                    )
                except ValueError:
                    agent_name = msg.get("agent", "未知")

            if msg.get("is_skip"):
                lines.append(f"### {agent_name}（跳过发言）")
                lines.append(f"> 评分: {msg.get('score', '?')}/10 - {msg.get('score_reason', msg.get('content', ''))}")
                lines.append("")
            else:
                lines.append(f"### {agent_name}")
                lines.append("")
                lines.append(msg.get("content", ""))
                if msg.get("score"):
                    lines.append(f"\n> **评分:** {msg['score']}/10 - {msg.get('score_reason', '')}")
                lines.append("")

        # 评分汇总
        lines.append("---")
        lines.append("## 最终评分")
        for role, score in scores.items():
            try:
                name = AGENT_NAMES.get(AgentRole(role), role)
            except ValueError:
                name = role
            lines.append(f"- {name}: {score}/10")

        # 最终报告
        if debate.get("final_summary"):
            lines.append("")
            lines.append("---")
            lines.append("## 思想孵化报告")
            lines.append("")
            lines.append(debate["final_summary"])

        return "\n".join(lines)

    async def _export_summary(self, debate: dict) -> str:
        """生成精简纪要（调用LLM）"""
        messages = debate.get("messages", [])
        topic = debate["topic"]

        history_text = ""
        for msg in messages:
            if msg.get("is_summary"):
                history_text += f"[历史总结] {msg['content'][:500]}\n"
            elif msg.get("is_user"):
                history_text += f"[用户] {msg['content'][:500]}\n"
            else:
                name = AGENT_NAMES.get(
                    AgentRole(msg.get("agent") or msg.get("role", "")), "未知"
                )
                history_text += f"[{name}] {msg['content'][:500]}\n"

        prompt = f"""请将以下辩论精简为一份纪要，要求：
1. 核心议题和结论（3句话以内）
2. 各方关键观点（每方1-2条）
3. 主要分歧点（2-3条）
4. 最终共识或未解决问题

议题: {topic}

辩论内容:
{history_text}

请输出简洁的Markdown格式纪要，不超过800字。"""

        return await llm_service.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1500
        )


# 全局单例
debate_service = DebateService()
