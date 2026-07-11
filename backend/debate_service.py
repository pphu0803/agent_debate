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
            debates.append({
                "id": str(d["_id"]),
                "topic": d["topic"],
                "status": d.get("status", "unknown"),
                "created_at": d["created_at"].isoformat() if isinstance(d.get("created_at"), datetime) else str(d.get("created_at", "")),
                "current_round": d.get("current_round", 0),
                "message_count": len(d.get("messages", [])),
                "final_summary": d.get("final_summary"),
            })
        return debates

    async def stop_debate(self, debate_id: str) -> bool:
        """终止辩论"""
        if not ObjectId.is_valid(debate_id):
            return False
        self._active_debates[debate_id] = False
        result = await self.db.debates.update_one(
            {"_id": ObjectId(debate_id)},
            {"$set": {"status": "terminated", "updated_at": datetime.now()}}
        )
        return result.modified_count > 0

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

        # 如果辩论还没开始，启动后台任务
        if debate["status"] == "pending" and not self._active_debates.get(debate_id, False):
            self._start_debate_background(debate_id)
            # 等待后台任务启动并更新状态
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

            # 主循环
            for round_num in range(1, max_rounds + 1):
                if not self._active_debates.get(debate_id, False):
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

                    agent = AGENTS[agent_role]

                    await self._save_event(debate_id, {
                        "type": "agent_thinking",
                        "agent": agent_role.value,
                        "agent_name": agent.name,
                        "agent_icon": AGENT_ICONS[agent_role],
                        "round": round_num,
                    })

                    try:
                        content, score, score_reason = await agent.respond(topic, messages)

                        msg = {
                            "agent": agent_role.value,
                            "role": agent_role.value,
                            "round": round_num,
                            "content": content,
                            "score": score,
                            "score_reason": score_reason,
                            "timestamp": datetime.now().isoformat(),
                            "is_summary": False,
                        }
                        await self._save_message(debate_id, msg)
                        messages.append(msg)

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
        """存储SSE事件到DB，自动分配序号"""
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


# 全局单例
debate_service = DebateService()
