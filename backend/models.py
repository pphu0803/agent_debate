"""思想孵化机 - 数据模型定义"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class AgentRole(str, Enum):
    INNOVATOR = "innovator"
    CRITIC = "critic"
    SCHOLAR = "scholar"
    MODERATOR = "moderator"


class CreateDebateRequest(BaseModel):
    """创建辩论请求"""
    topic: str = Field(..., min_length=1, max_length=5000, description="辩论主题")
    max_rounds: Optional[int] = Field(default=None, ge=1, le=50, description="最大轮次")
    score_threshold: Optional[int] = Field(default=None, ge=1, le=10, description="达成共识的评分阈值")


class UpdateConfigRequest(BaseModel):
    """更新配置请求"""
    api_key: Optional[str] = Field(default=None, description="LLM API密钥")
    api_base: Optional[str] = Field(default=None, description="API基础地址")
    model: Optional[str] = Field(default=None, description="模型名称")


class InjectMessageRequest(BaseModel):
    """用户注入消息请求"""
    content: str = Field(..., min_length=1, max_length=10000, description="用户发言内容")


class AgentInfo(BaseModel):
    """Agent信息"""
    role: AgentRole
    name: str
    description: str
    color: str


class DebateSummary(BaseModel):
    """辩论列表项"""
    id: str
    topic: str
    status: str
    created_at: str
    current_round: int
    message_count: int
    final_summary: Optional[str] = None


class SSEEvent(BaseModel):
    """SSE事件"""
    type: str
    data: Dict[str, Any] = {}
