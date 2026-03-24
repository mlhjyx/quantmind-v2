"""应用配置 — pydantic-settings 读取 .env"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """QuantMind V2 全局配置。

    优先级: 环境变量 > .env 文件 > 默认值
    """

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 数据库 ---
    DATABASE_URL: str = "postgresql+asyncpg://xin:quantmind@localhost:5432/quantmind_v2"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- 数据源 ---
    TUSHARE_TOKEN: str = ""

    # --- AI ---
    DEEPSEEK_API_KEY: str = ""

    # --- 执行模式 ---
    EXECUTION_MODE: Literal["paper", "live"] = "paper"

    # --- 日志 ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "DEBUG"
    LOG_MAX_FILES: int = 10

    # --- 通知 ---
    DINGTALK_WEBHOOK_URL: str = ""
    DINGTALK_SECRET: str = ""  # HMAC签名密钥（加签模式），为空则不签名
    DINGTALK_KEYWORD: str = ""  # 自定义关键词（关键词模式），非空时自动追加到消息

    # --- Paper Trading ---
    PAPER_STRATEGY_ID: str = ""
    PAPER_INITIAL_CAPITAL: float = 1_000_000.0

    # --- 服务 ---
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000


settings = Settings()
