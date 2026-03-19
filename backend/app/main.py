"""FastAPI 入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化资源，关闭时释放连接池。"""
    yield
    await engine.dispose()


app = FastAPI(
    title="QuantMind V2",
    description="A股+外汇绝对收益量化交易系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "execution_mode": settings.EXECUTION_MODE,
    }
