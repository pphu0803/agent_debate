"""思想孵化机 - 三个AI Agent定义"""
import re
import logging
from typing import Tuple, List

from models import AgentRole
from llm_service import llm_service

logger = logging.getLogger(__name__)

# Agent显示名映射
AGENT_NAMES = {
    AgentRole.INNOVATOR: "激进的创新者",
    AgentRole.CRITIC: "严厉的反对者",
    AgentRole.SCHOLAR: "保守的学者",
}

# Agent颜色（前端用）
AGENT_COLORS = {
    AgentRole.INNOVATOR: "#ff6b6b",
    AgentRole.CRITIC: "#4ecdc4",
    AgentRole.SCHOLAR: "#95e1d3",
}

# Agent图标
AGENT_ICONS = {
    AgentRole.INNOVATOR: "💡",
    AgentRole.CRITIC: "⚔️",
    AgentRole.SCHOLAR: "📚",
}


class BaseAgent:
    """Agent基类"""

    def __init__(self, role: AgentRole, name: str, description: str,
                 system_prompt: str, temperature: float = 0.7):
        self.role = role
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.temperature = temperature

    def build_context(self, topic: str, history: list) -> list:
        """构建LLM上下文消息"""
        messages = [{"role": "system", "content": self.system_prompt}]

        context = f"【辩论主题】\n{topic}\n"
        context += "=" * 40 + "\n\n"

        if not history:
            context += "这是第一轮发言，之前没有讨论记录。\n"
        else:
            context += "【讨论记录】\n"
            for msg in history:
                agent_name = AGENT_NAMES.get(
                    msg.get("agent") or msg.get("role"), "未知"
                ) if isinstance(msg, dict) else AGENT_NAMES.get(msg.agent, "未知")

                content = msg.get("content", "") if isinstance(msg, dict) else msg.content
                round_num = msg.get("round", 0) if isinstance(msg, dict) else msg.round
                score = msg.get("score") if isinstance(msg, dict) else msg.score
                is_summary = msg.get("is_summary", False) if isinstance(msg, dict) else getattr(msg, "is_summary", False)

                if is_summary:
                    context += f"📋 [历史总结]\n{content}\n\n"
                else:
                    context += f"👤 [{agent_name} - 第{round_num}轮]\n{content}\n"
                    if score:
                        context += f"📊 评分: {score}/10\n"
                    context += "\n"

        context += "=" * 40 + "\n"
        context += f"\n现在轮到你【{self.name}】发言。\n"
        context += "要求：\n"
        context += "1. 必须基于以上所有发言记录进行回应和延伸\n"
        context += "2. 发挥你的角色特点\n"
        context += "3. 发言要有实质内容，不要泛泛而谈\n"
        context += "4. 在发言末尾给出你对当前讨论结论的接受度评分\n\n"
        context += "请在发言末尾严格按照以下格式给出评分：\n"
        context += "【评分】X/10\n"
        context += "【评分理由】简要说明评分原因（一两句话即可）"

        messages.append({"role": "user", "content": context})
        return messages

    def parse_response(self, response: str) -> Tuple[str, int, str]:
        """从LLM响应中解析内容、评分和评分理由"""
        # 解析评分
        score_pattern = r'【评分】\s*(\d+)\s*/\s*10'
        reason_pattern = r'【评分理由】\s*(.+)'

        score_match = re.search(score_pattern, response)
        reason_match = re.search(reason_pattern, response, re.DOTALL)

        score = int(score_match.group(1)) if score_match else 5
        score = max(1, min(10, score))

        reason = reason_match.group(1).strip() if reason_match else "未提供评分理由"

        # 从内容中移除评分部分
        content = re.sub(r'\n*【评分】.*', '', response, flags=re.DOTALL).strip()

        if not content:
            content = response

        return content, score, reason

    async def respond(self, topic: str, history: list) -> Tuple[str, int, str]:
        """Agent发言"""
        messages = self.build_context(topic, history)
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


class InnovatorAgent(BaseAgent):
    """激进的创新者"""

    def __init__(self):
        super().__init__(
            role=AgentRole.INNOVATOR,
            name="激进的创新者",
            description="提出新的概念、新的理论、新的机制来解释问题",
            system_prompt="""你是一个激进的创新者。你的使命是用大胆的、创造性的思维来探索问题。

你的核心特点：
- 不受传统思维束缚，敢于提出全新的概念和理论框架
- 善于跨学科思考，将看似不相关的领域知识融合产生新洞察
- 提出具有颠覆性的新机制、新模型、新视角
- 在前人观点的基础上，推向更远、更深的方向
- 用生动的类比和隐喻来阐述复杂的新思想

你的发言要求：
- 充满激情和想象力，但论证要有逻辑结构
- 每次发言必须提出至少一个新观点、新概念或新角度
- 必须明确回应和延伸前两位发言者的观点
- 可以大胆假设，但要说明思考过程
- 如果被反对者批评了，要用新的论据或新视角来回应

评分标准（对当前讨论的整体评价）：
- 10分：讨论已形成完整且高度创新的理论框架
- 7-9分：讨论有出色的创新点，但还可以更深入
- 4-6分：有一些新想法，但创新性不足或过于保守
- 1-3分：讨论缺乏新意，只是在重复已知内容""",
            temperature=0.9
        )


class CriticAgent(BaseAgent):
    """严厉的反对者"""

    def __init__(self):
        super().__init__(
            role=AgentRole.CRITIC,
            name="严厉的反对者",
            description="对成果进行严厉的批判，指出逻辑上的漏洞、矛盾、缺失等",
            system_prompt="""你是一个严厉的反对者。你的使命是对所有观点进行严格、无情的批判。

你的核心特点：
- 以逻辑和理性为武器，不留情面地指出每一个问题
- 敏锐地发现逻辑漏洞、自相矛盾、证据不足、概念混淆
- 提出尖锐的反例和极端边界情况来检验理论
- 质疑每个假设的合理性、适用范围和潜在盲区
- 指出理论可能导致的不良后果或误导

你的发言要求：
- 严谨、犀利、一针见血，每个批评都要有明确论据
- 不是为了反对而反对，而是为了让理论更加完善
- 必须具体指出前两位发言者观点中的具体问题
- 提出建设性的改进方向（即使是批评，也要指向如何修复）
- 如果前一轮提出的问题已被解决，应该承认并继续找新问题

评分标准（对当前讨论的逻辑严谨性评价）：
- 10分：论述逻辑严密，无明显漏洞，论据充分有力
- 7-9分：基本合理，有轻微问题但不影响核心逻辑
- 4-6分：存在明显的逻辑问题或关键证据缺失
- 1-3分：漏洞百出，逻辑混乱，难以自洽""",
            temperature=0.3
        )


class ScholarAgent(BaseAgent):
    """保守的学者"""

    def __init__(self):
        super().__init__(
            role=AgentRole.SCHOLAR,
            name="保守的学者",
            description="搜索现有文献材料，整理并指出与现有问题的交叉",
            system_prompt="""你是一个保守的学者。你的使命是将讨论与已有的知识和研究成果联系起来。

你的核心特点：
- 拥有广博的学识，熟悉各学科的经典理论和最新研究进展
- 谨慎、客观、不轻易下结论，对一切保持怀疑和审慎
- 善于找到新观点与已有理论之间的联系、交叉和分歧
- 指出哪些部分已被前人研究过，结果如何，有何争议
- 提醒大家注意已有的反面证据、适用边界和已知局限

你的发言要求：
- 学术、严谨、引用尽量具体（指出理论名称、学者、学科领域）
- 保持中立立场，既不盲目支持也不一味否定
- 每次发言都要指出讨论内容与现有知识的交叉
- 如果有相关的研究、实验或历史案例，请具体引用
- 谨慎地评估当前讨论与已有知识体系的一致性

评分标准（对讨论与现有知识体系的一致性评价）：
- 10分：论述有充分的知识支撑，与现有研究高度一致
- 7-9分：基本符合现有知识，但某些方面缺乏足够支撑
- 4-6分：与部分已有研究矛盾，或缺乏充分的文献支撑
- 1-3分：严重违背已知事实或已被证伪的理论""",
            temperature=0.5
        )


# Agent实例
AGENTS: dict = {
    AgentRole.INNOVATOR: InnovatorAgent(),
    AgentRole.CRITIC: CriticAgent(),
    AgentRole.SCHOLAR: ScholarAgent(),
}

# 发言顺序：创新者提出 → 反对者批判 → 学者参照
AGENT_ORDER: list = [AgentRole.INNOVATOR, AgentRole.CRITIC, AgentRole.SCHOLAR]
