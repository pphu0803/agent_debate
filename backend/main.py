"""思想孵化机 - FastAPI主应用"""
import json
import logging
from pathlib import Path
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from sse_starlette.sse import EventSourceResponse

from config import config
from models import CreateDebateRequest, UpdateConfigRequest
from debate_service import debate_service
from llm_service import llm_service
from agents import AGENTS, AGENT_ORDER, AGENT_NAMES, AGENT_COLORS, AGENT_ICONS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("thought_incubator")

app = FastAPI(title="思想孵化机", description="AI Agent辩论机器")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_db():
    """连接MongoDB"""
    client = AsyncIOMotorClient(config.MONGODB_URL)
    db = client[config.MONGODB_DB]
    debate_service.init_db(db)
    logger.info(f"MongoDB已连接: {config.MONGODB_URL}/{config.MONGODB_DB}")
    logger.info(f"LLM配置: model={llm_service.get_model()}, configured={llm_service.is_configured()}")


# ==================== API路由 ====================

@app.post("/api/debates")
async def create_debate(request: CreateDebateRequest):
    """创建新辩论"""
    if not llm_service.is_configured():
        raise HTTPException(status_code=400, detail="LLM API Key未配置，请先在设置中填写")
    result = await debate_service.create_debate(request)
    return result


@app.get("/api/debates/{debate_id}/stream")
async def stream_debate(debate_id: str):
    """SSE流式获取辩论实时更新

    辩论逻辑在后台asyncio任务中运行，此端点只负责推送事件。
    ping=15每15秒发送心跳，防止代理网关因空闲超时断开连接。
    客户端断开重连时自动回放历史事件，不丢失任何内容。
    """
    async def event_generator():
        try:
            async for event in debate_service.stream_debate(debate_id):
                yield event
        except Exception as e:
            logger.error(f"SSE流异常: {e}")
            yield {"data": json.dumps(
                {"type": "error", "message": f"服务器错误: {str(e)}"},
                ensure_ascii=False
            )}

    return EventSourceResponse(event_generator(), ping=15)


@app.get("/api/debates/{debate_id}")
async def get_debate(debate_id: str):
    """获取辩论详情"""
    debate = await debate_service.get_debate(debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="辩论不存在")
    return debate


@app.get("/api/debates")
async def list_debates():
    """获取辩论列表"""
    return await debate_service.list_debates()


@app.post("/api/debates/{debate_id}/stop")
async def stop_debate(debate_id: str):
    """终止辩论"""
    success = await debate_service.stop_debate(debate_id)
    if not success:
        raise HTTPException(status_code=404, detail="辩论不存在")
    return {"status": "terminated"}


@app.get("/api/config")
async def get_config():
    """获取当前配置状态"""
    return {
        "configured": llm_service.is_configured(),
        "model": llm_service.get_model(),
        "api_base": llm_service.get_api_base(),
    }


@app.post("/api/config")
async def update_config(request: UpdateConfigRequest):
    """更新LLM配置"""
    llm_service.update_config(
        api_key=request.api_key,
        api_base=request.api_base,
        model=request.model,
    )
    return {
        "status": "updated",
        "configured": llm_service.is_configured(),
        "model": llm_service.get_model(),
    }


@app.get("/api/agents")
async def get_agents():
    """获取Agent信息"""
    return [
        {
            "role": role.value,
            "name": AGENTS[role].name,
            "description": AGENTS[role].description,
            "color": AGENT_COLORS[role],
            "icon": AGENT_ICONS[role],
            "temperature": AGENTS[role].temperature,
        }
        for role in AGENT_ORDER
    ]


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "time": datetime.now().isoformat()}


# ==================== 静态文件 ====================

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
    logger.info(f"前端静态文件目录: {frontend_path}")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
        log_level="info",
    )
