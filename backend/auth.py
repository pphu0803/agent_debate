"""思想孵化机 - 访问鉴权

单一密码鉴权机制：
- 设一个访问密码(ACCESS_PASSWORD)，登录成功后返回HMAC签名token
- token不设过期(个人应用)，改密码即失效
- ACCESS_PASSWORD为空时不启用鉴权(本地开发模式)
"""
import hmac
import hashlib
import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from config import config


def _sign(payload: str) -> str:
    """用ACCESS_PASSWORD作为HMAC密钥签名"""
    key = (config.ACCESS_PASSWORD or "dev-no-auth").encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def create_token() -> str:
    """生成token：随机nonce + 时间戳的HMAC签名"""
    nonce = secrets.token_hex(8)
    ts = str(int(datetime.now().timestamp()))
    payload = f"{nonce}.{ts}"
    sig = _sign(payload)
    return f"{payload}.{sig}"


def verify_token(token: str) -> bool:
    """验证token签名是否有效"""
    if not config.ACCESS_PASSWORD:
        return True  # 未设密码 = 不鉴权
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    payload = f"{parts[0]}.{parts[1]}"
    sig = parts[2]
    expected = _sign(payload)
    return hmac.compare_digest(sig, expected)


async def require_auth(request: Request):
    """FastAPI依赖：要求请求携带有效token

    支持两种传递方式：
    - Header: Authorization: Bearer <token>  (普通API请求)
    - Query: ?token=<token>                  (SSE连接，EventSource无法设header)
    """
    if not config.ACCESS_PASSWORD:
        return  # 未设密码，不鉴权

    # 先从header读
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # 再从query param读（SSE用）
        token = request.query_params.get("token", "")

    if not verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )


class LoginRequest(BaseModel):
    """登录请求"""
    password: str
