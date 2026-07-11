"""思想孵化机 - AI Agent定义

设计哲学：
- 自由讨论，而非机器人式的结构化填表
- 每个Agent有自己的视角和风格，但有方向性指引
- Agent可以自行判断是否需要发言（跳过=只给评分）
- 每3轮触发反思模式，避免陷入思想盆地
- 辩论组织者负责纠偏和死胡同检测

三个核心角色：
- 创新者：提出新视角、新机制、新的解释路径
- 批判者：逻辑审查，发现问题给出修复方向
- 严谨者：建立已有知识映射，用事实和证据支撑讨论
"""

import re
import logging
from typing import Tuple, List

from models import AgentRole
from llm_service import llm_service
from web_search import web_search

logger = logging.getLogger(__name__)

AGENT_NAMES = {
    AgentRole.INNOVATOR: "创新者",
    AgentRole.CRITIC: "批判者",
    AgentRole.SCHOLAR: "严谨者",
    AgentRole.MODERATOR: "组织者",
}

AGENT_COLORS = {
    AgentRole.INNOVATOR: "#ff6b6b",
    AgentRole.CRITIC: "#4ecdc4",
    AgentRole.SCHOLAR: "#95e1d3",
    AgentRole.MODERATOR: "#a78bfa",
}

AGENT_ICONS = {
    AgentRole.INNOVATOR: "💡",
    AgentRole.CRITIC: "⚔️",
    AgentRole.SCHOLAR: "🔍",
    AgentRole.MODERATOR: "🎭",
}

# 跳过发言标记
SKIP_PATTERN = r'【跳过发言】'

# 反思模式：每N轮触发一次
REFLECTION_INTERVAL = 3


class BaseAgent:
    """Agent基类"""

    def __init__(self, role: AgentRole, name: str, description: str,
                 system_prompt: str, temperature: float = 0.7,
                 enable_search: bool = False):
        self.role = role
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.enable_search = enable_search

    async def _get_search_context(self, topic: str, history: list) -> str:
        """获取搜索上下文（如果启用了搜索）"""
        if not self.enable_search:
            return ""

        try:
            # 从讨论历史中提取关键信息用于搜索
            search_query = await self._generate_search_query(topic, history)
            if not search_query:
                return ""

            results = await web_search.search(search_query, num_results=4)
            if results:
                return "\n\n" + web_search.format_search_results(results, search_query)
        except Exception as e:
            logger.warning(f"Agent {self.name} 搜索失败: {e}")

        return ""

    async def _generate_search_query(self, topic: str, history: list) -> str:
        """基于讨论内容生成搜索关键词"""
        # 取最近几条消息的关键词
        recent_texts = []
        for msg in history[-6:]:
            content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            if content and not msg.get("is_summary", False):
                recent_texts.append(content[:200])

        context_text = "\n".join(recent_texts) if recent_texts else topic

        prompt = f"""基于以下讨论内容，提取1-2个最适合联网搜索的关键词或短语。
只输出搜索词，不要任何解释。搜索词应该能帮助获取最新的事实、数据或案例。

讨论主题：{topic}

最近讨论内容：
{context_text[:600]}

搜索词："""

        try:
            response = await llm_service.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=50
            )
            return response.strip().strip('"').strip("'")
        except Exception:
            return topic[:50]

    def build_context(self, topic: str, history: list, round_num: int = 0,
                      search_context: str = "") -> list:
        """构建LLM上下文消息"""
        messages = [{"role": "system", "content": self.system_prompt}]

        context = f"【讨论议题】\n{topic}\n"
        context += "=" * 40 + "\n\n"

        if not history:
            context += "这是第一轮发言，之前没有讨论记录。\n"
        else:
            context += "【讨论记录】\n"
            for msg in history:
                is_user = msg.get("is_user", False) if isinstance(msg, dict) else getattr(msg, "is_user", False)
                is_summary = msg.get("is_summary", False) if isinstance(msg, dict) else getattr(msg, "is_summary", False)
                is_skip = msg.get("is_skip", False) if isinstance(msg, dict) else getattr(msg, "is_skip", False)

                content = msg.get("content", "") if isinstance(msg, dict) else msg.content
                round_n = msg.get("round", 0) if isinstance(msg, dict) else msg.round
                score = msg.get("score") if isinstance(msg, dict) else msg.score

                if is_summary:
                    context += f"[历史总结]\n{content}\n\n"
                elif is_user:
                    context += f"[用户 - 第{round_n}轮]\n{content}\n\n"
                elif is_skip:
                    agent_name = AGENT_NAMES.get(
                        msg.get("agent") or msg.get("role"), "未知"
                    ) if isinstance(msg, dict) else AGENT_NAMES.get(msg.agent, "未知")
                    context += f"[{agent_name} - 第{round_n}轮] 跳过发言（评分: {score}/10，理由: {content}）\n\n"
                else:
                    agent_name = AGENT_NAMES.get(
                        msg.get("agent") or msg.get("role"), "未知"
                    ) if isinstance(msg, dict) else AGENT_NAMES.get(msg.agent, "未知")
                    context += f"[{agent_name} - 第{round_n}轮]\n{content}\n"
                    if score:
                        context += f"评分: {score}/10\n"
                    context += "\n"

        # 注入搜索结果
        if search_context:
            context += search_context + "\n"

        context += "=" * 40 + "\n"
        context += f"\n现在轮到你【{self.name}】发言。当前是第{round_num}轮。\n"

        # 反思模式：每REFLECTION_INTERVAL轮，给创新者注入反思指令
        if round_num > 0 and round_num % REFLECTION_INTERVAL == 0 and self.role == AgentRole.INNOVATOR:
            context += (
                "\n🌀 本轮是反思轮。反思一下之前的讨论，是否陷入了思想盆地里？"
                "有没有可能存在一个完全新的机制、理论能够更好地解释和分析？"
                "不需要推翻已有讨论，但试着从全新的角度思考一下。\n"
            )

        context += (
            "\n你可以选择跳过本轮发言。如果你对当前讨论方向基本认可，"
            "没有需要补充或质疑的内容，可以输出【跳过发言】并只给出评分和理由。"
            "但如果后续讨论偏离了你的关注点，你可以在之后的轮次重新加入对话。\n"
        )
        context += "\n在发言最末尾（或跳过标记后），给出你对当前讨论方向的接受度评分：\n"
        context += "【评分】X/10\n"
        context += "【评分理由】一两句话说明原因"

        messages.append({"role": "user", "content": context})
        return messages

    def parse_response(self, response: str) -> Tuple[str, int, str, bool]:
        """从LLM响应中解析内容、评分、评分理由、是否跳过

        返回: (content, score, score_reason, is_skip)
        """
        is_skip = bool(re.search(SKIP_PATTERN, response))

        score_pattern = r'【评分】\s*(\d+)\s*/\s*10'
        reason_pattern = r'【评分理由】\s*(.+)'

        score_match = re.search(score_pattern, response)
        reason_match = re.search(reason_pattern, response, re.DOTALL)

        score = int(score_match.group(1)) if score_match else 5
        score = max(1, min(10, score))

        reason = reason_match.group(1).strip() if reason_match else "未提供评分理由"

        # 从内容中移除评分部分和跳过标记
        content = re.sub(r'\n*【跳过发言】.*', '', response, flags=re.DOTALL)
        content = re.sub(r'\n*【评分】.*', '', content, flags=re.DOTALL).strip()

        if is_skip:
            # 跳过时content用作简短理由
            if not content:
                content = reason
        elif not content:
            content = response

        return content, score, reason, is_skip

    async def respond(self, topic: str, history: list, round_num: int = 0) -> Tuple[str, int, str, bool]:
        """Agent发言，返回(content, score, score_reason, is_skip)"""
        search_context = await self._get_search_context(topic, history)
        messages = self.build_context(topic, history, round_num, search_context)
        try:
            response = await llm_service.chat(
                messages=messages,
                temperature=self.temperature,
                max_tokens=2000
            )
            return self.parse_response(response)
        except Exception as e:
            logger.error(f"Agent {self.name} 发言失败: {e}")
            raise


# ============================================================
# 创新者：提出新视角、新机制、新路径
# ============================================================

class InnovatorAgent(BaseAgent):
    """创新者 — 自由思考，有方向性约束，每3轮反思"""

    def __init__(self):
        super().__init__(
            role=AgentRole.INNOVATOR,
            name="创新者",
            description="提出新视角和新机制，推动讨论向前",
            temperature=0.8,
            enable_search=True,
            system_prompt="""你是一个创新者，参与一场自由讨论。

你的角色是推动思考向前走——提出新视角、新机制、新的解释路径。但你不是在表演，而是在真正地思考问题。

指引方向：
- 直接回应别人的观点，不要自说自话。如果别人指出了问题，先回应那个问题。
- 新概念只有在已有理论确实解释不了时才提出。提出时要说清楚：它增加了什么解释力？在什么条件下会失效？
- 优先通过修改已有机制来解决问题，而不是不断堆砌新概念。
- 如果讨论卡在某个点上反复绕圈子，试着换一个角度切入。
- 模型应该越改越简洁，而不是越改越复杂。
- 偶尔问自己：是不是变量找错了？是不是尺度错了？是不是因果方向反了？

什么时候可以跳过：
- 如果你认为当前理论方向是对的，且你没有新的内容要补充，可以选择跳过。
- 跳过不等于放弃——如果后续讨论偏离了，你可以在之后的轮次重新加入。

评分标准（评价的是当前讨论的质量和方向）：
- 10分：讨论聚焦、有实质进展、思路越来越清晰
- 7-9分：基本在轨，但有些环节可以更聚焦
- 4-6分：讨论开始发散，或陷入概念堆砌
- 1-3分：严重偏离主题或陷入空转

请自然地发言，像在一场真实的讨论中一样。不需要分点编号，不需要固定格式。""",
        )


# ============================================================
# 批判者：逻辑审查为主，不强制找错
# ============================================================

class CriticAgent(BaseAgent):
    """批判者 — 逻辑过关即可放行"""

    def __init__(self):
        super().__init__(
            role=AgentRole.CRITIC,
            name="批判者",
            description="逻辑审查，发现问题给出修复方向",
            temperature=0.4,
            enable_search=False,
            system_prompt="""你是一个批判者，参与一场自由讨论。

你的使命不是否定一切，而是让思考变强。

核心原则：
- 围绕逻辑性做判断。只要逻辑能过关，你是允许放行的。
- 不要为了找错而找错。观点本身就有冲突，你总能找到反对意见，但那不意味着对方是错的。
- 挑出明显有问题的地方就可以。如果论证在逻辑上是自洽的，即使你不完全认同其前提，也应该放行。
- 如果上一轮提出的问题已被较好回应，明确承认。

当你确实发现问题时：
- 聚焦最大的一个漏洞，不要面面俱到。
- 给出具体的逻辑论证，不能仅凭直觉否定。
- 附带修复建议："如果我是作者，我会这样修。"
- 如果你已经连续两轮提出同一批评且对方未回应，第三轮停止重复。

什么时候可以跳过：
- 如果这一轮的逻辑没有明显问题，你可以选择跳过，只给评分。
- 不要觉得每轮都必须找到问题——"没有大问题"本身就是有价值的判断。

不要用标签化攻击。用逻辑说话。

评分标准（评价的是当前论证的逻辑质量）：
- 10分：逻辑严密，论证充分
- 7-9分：基本合理，有可改善之处但非致命
- 4-6分：存在明显的逻辑问题
- 1-3分：框架本身存在根本性逻辑缺陷

请自然地发言，像在一场真实的讨论中一样。不需要分点编号，不需要固定格式。""",
        )


# ============================================================
# 严谨者：建立已有知识映射 + 识别缺失
# ============================================================

class ScholarAgent(BaseAgent):
    """严谨者 — 用事实和证据支撑讨论，建立已有知识映射"""

    def __init__(self):
        super().__init__(
            role=AgentRole.SCHOLAR,
            name="严谨者",
            description="用事实和证据支撑讨论，建立已有知识映射，识别讨论中的缺失视角",
            temperature=0.5,
            enable_search=True,
            system_prompt="""你是一个严谨者，参与一场自由讨论。

你的使命是用事实、数据和已有知识来支撑讨论，并识别讨论中可能缺失的视角。

指引方向：
- 判断当前讨论和已有知识的关系：是支持、矛盾、还是启发？
- 引用要精确：指出具体的观点、案例、数据来源，不要泛泛提及。可以说"根据实际情况"、"有案例表明"、"数据显示"等。
- 如果某个领域没有直接相关的资料，直接说明，不要硬凑。
- 识别当前讨论中"真正新的东西"是什么。
- 如果有联网搜索结果，请优先参考搜索结果中的事实和数据。

关于"找缺失"（温和版）：
- 看看有没有什么重要的视角、案例或数据始终没有进入讨论。
- 如果有，温和地提出来："你们讨论了这么久，始终没人提到X，也许值得考虑一下。"
- 不需要强制——如果讨论本身已经足够丰富，可以不提。
- 你的目标是温和地扩大信息面，而不是打断讨论。

什么时候可以跳过：
- 如果当前讨论与已有知识的映射你已经说清楚了，且没有发现明显的缺失，可以选择跳过。

评分标准（评价的是讨论与已有知识体系的一致性）：
- 10分：讨论有充分的事实支撑，观点明确且有意义
- 7-9分：基本与已有知识一致
- 4-6分：与部分已有事实矛盾，或缺乏经验支撑
- 1-3分：严重违背已知事实

请自然地发言，像在一场真实的讨论中一样。不需要分点编号，不需要固定格式。""",
        )


# ============================================================
# 组织者：纠偏与死胡同检测
# ============================================================

DEAD_END_PATTERN = r'【辩论状态】\s*(CONTINUE|DEAD_END|REDIRECT)'
REDIRECT_TOPIC_PATTERN = r'【拉回议题】\s*(.+)'

class ModeratorAgent(BaseAgent):
    """组织者 — 检查偏题和死胡同"""

    def __init__(self):
        super().__init__(
            role=AgentRole.MODERATOR,
            name="组织者",
            description="中立复盘，检查讨论是否偏离原始议题，检测死胡同",
            temperature=0.3,
            enable_search=False,
            system_prompt="""你是组织者，是这场讨论的中立观察者和裁判。

你不提出自己的观点，你的职责是：
1. 检查讨论是否偏离了用户的原始议题
2. 检测讨论是否陷入了死胡同（需要实验或实证数据才能继续推进）
3. 总结本轮讨论的进展

指引方向：

**关于偏题检测：**
- 用户的原始议题是最重要的锚点。每轮都要检查：大家还在讨论用户问的问题吗？
- 如果讨论偏移到了某个参与者自己提出的细节里，而忽略了对原始议题的思考，你需要明确指出。
- 偏题不等于深入。如果"深入"的方向已经与原始议题无关，要拉回来。

**关于死胡同检测：**
- 如果当前的争议只能通过实验、实证数据或实际操作来解决，无法通过纯推演继续，这就是死胡同。
- 死胡同不是失败——能识别出"这里需要实践验证了"本身就是讨论的重要成果。
- 常见的死胡同信号：
  - 各方反复争论同一个问题但没有新的论据
  - 核心争议变成了"实际会怎样"而非"理论上该怎么推"
  - 某个关键假设无法通过纯逻辑验证或证伪
  - 讨论已经收敛到几个明确的、可检验的方向，接下来只能靠实践

**关于跳过发言的处理：**
- 如果多个参与者选择跳过发言，这本身就是一个信号：讨论可能已经收敛。
- 如果大部分人都跳过且评分较高，你可以考虑给出DEAD_END状态（讨论已自然收敛）。

**你的输出要求：**
先自然地写你的复盘分析，然后在最末尾输出以下标记：

【辩论状态】CONTINUE 或 DEAD_END 或 REDIRECT
（CONTINUE=讨论正常进行；DEAD_END=遇到死胡同或已自然收敛，需要停止；REDIRECT=讨论偏离了原始议题）

如果状态是REDIRECT，另起一行写：
【拉回议题】简要说明讨论偏离了哪里，以及应该回到什么方向

然后照常给出评分：
【评分】X/10
【评分理由】一两句话

注意：
- 你的评分评价的是"讨论对用户原始议题的推进程度"，不是观点本身的好坏。
- 10分：讨论高度聚焦于用户议题，有实质进展
- 7-9分：基本在轨，略有偏移
- 4-6分：明显偏题，或原地打转
- 1-3分：完全偏离议题，或陷入无效争论

请自然地写复盘分析，像一位真实的会议主持人一样。状态标记放在最后。""",
        )

    def parse_moderator_response(self, response: str) -> Tuple[str, int, str, str, str]:
        """解析组织者响应：内容、评分、评分理由、辩论状态、拉回方向"""
        content, score, score_reason, _ = self.parse_response(response)

        status_match = re.search(DEAD_END_PATTERN, response)
        status = status_match.group(1) if status_match else "CONTINUE"

        redirect_topic = ""
        if status == "REDIRECT":
            redirect_match = re.search(REDIRECT_TOPIC_PATTERN, response, re.DOTALL)
            if redirect_match:
                redirect_topic = redirect_match.group(1).strip()
                redirect_topic = redirect_topic.split('\n')[0].strip()

        content = re.sub(r'\n*【辩论状态】.*', '', content, flags=re.DOTALL).strip()
        content = re.sub(r'\n*【拉回议题】.*', '', content, flags=re.DOTALL).strip()

        return content, score, score_reason, status, redirect_topic

    async def respond_moderator(self, topic: str, history: list, round_num: int = 0) -> Tuple[str, int, str, str, str]:
        """组织者发言，返回额外的状态信息"""
        messages = self.build_context(topic, history, round_num)
        try:
            response = await llm_service.chat(
                messages=messages,
                temperature=self.temperature,
                max_tokens=1500
            )
            return self.parse_moderator_response(response)
        except Exception as e:
            logger.error(f"Moderator 发言失败: {e}")
            raise


# Agent实例
AGENTS: dict = {
    AgentRole.INNOVATOR: InnovatorAgent(),
    AgentRole.CRITIC: CriticAgent(),
    AgentRole.SCHOLAR: ScholarAgent(),
    AgentRole.MODERATOR: ModeratorAgent(),
}

# 发言顺序：创新者 → 批判者 → 严谨者 → 组织者复盘
AGENT_ORDER: list = [AgentRole.INNOVATOR, AgentRole.CRITIC, AgentRole.SCHOLAR]
MODERATOR_ROLE: AgentRole = AgentRole.MODERATOR
