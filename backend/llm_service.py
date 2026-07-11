"""思想孵化机 - LLM服务封装"""
import logging
from typing import Optional
from openai import AsyncOpenAI

from config import config

logger = logging.getLogger(__name__)


class LLMService:
    """统一的LLM调用服务，支持OpenAI兼容API"""

    def __init__(self):
        self._api_key: str = config.OPENAI_API_KEY
        self._api_base: str = config.OPENAI_API_BASE
        self._model: str = config.LLM_MODEL
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key or "dummy-key",
                base_url=self._api_base
            )
        return self._client

    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key != "dummy-key")

    def get_model(self) -> str:
        return self._model

    def get_api_base(self) -> str:
        return self._api_base

    def update_config(self, api_key: Optional[str] = None,
                       api_base: Optional[str] = None,
                       model: Optional[str] = None):
        if api_key is not None:
            self._api_key = api_key
        if api_base is not None:
            self._api_base = api_base
        if model is not None:
            self._model = model
        self._client = None  # 强制重建客户端
        logger.info(f"LLM配置已更新: model={self._model}, base={self._api_base}")

    async def chat(self, messages: list, temperature: float = 0.7,
                   max_tokens: int = 2000) -> str:
        """同步调用LLM，返回完整响应文本"""
        if not self.is_configured():
            raise ValueError("LLM API Key未配置，请在设置中填写API Key")

        try:
            response = await self.client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise

    async def chat_stream(self, messages: list, temperature: float = 0.7,
                          max_tokens: int = 2000):
        """流式调用LLM，逐token返回"""
        if not self.is_configured():
            raise ValueError("LLM API Key未配置，请在设置中填写API Key")

        try:
            stream = await self.client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta is not None:
                    yield delta
        except Exception as e:
            logger.error(f"LLM流式调用失败: {e}")
            raise


# 全局单例
llm_service = LLMService()
