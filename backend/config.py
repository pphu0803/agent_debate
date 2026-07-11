"""思想孵化机 - 全局配置管理"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ===== LLM 配置 =====
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

    # ===== MongoDB 配置 =====
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    MONGODB_DB: str = os.getenv("MONGODB_DB", "thought_incubator")

    # ===== 服务器配置 =====
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # ===== 辩论配置 =====
    MAX_ROUNDS: int = int(os.getenv("MAX_ROUNDS", "20"))
    SCORE_THRESHOLD: int = int(os.getenv("SCORE_THRESHOLD", "6"))
    MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "6000"))


config = Config()
