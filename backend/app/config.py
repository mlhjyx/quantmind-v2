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

    # --- Paper Trading 核心参数 ---
    PT_TOP_N: int = 20  # was 15, changed 2026-04-04, backtest X-D Sharpe 1.15
    PT_INDUSTRY_CAP: float = 1.0  # was 0.25, changed 2026-04-04, removing constraint +0.09 Sharpe
    PT_SIZE_NEUTRAL_BETA: float = 0.0  # 0.0=关闭, 0.50=Step 6-H验证最优. .env设置覆盖

    # --- PMS 阶梯利润保护 ---
    PMS_ENABLED: bool = True
    PMS_LEVEL1_GAIN: float = 0.30
    PMS_LEVEL1_DRAWDOWN: float = 0.15
    PMS_LEVEL2_GAIN: float = 0.20
    PMS_LEVEL2_DRAWDOWN: float = 0.12
    PMS_LEVEL3_GAIN: float = 0.10
    PMS_LEVEL3_DRAWDOWN: float = 0.10

    # --- 日志 ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "DEBUG"
    LOG_MAX_FILES: int = 10

    # --- 通知 ---
    DINGTALK_WEBHOOK_URL: str = ""
    DINGTALK_SECRET: str = ""  # HMAC签名密钥（加签模式），为空则不签名
    DINGTALK_KEYWORD: str = ""  # 自定义关键词（关键词模式），非空时自动追加到消息

    # --- miniQMT ---
    QMT_PATH: str = ""  # miniQMT userdata_mini路径
    QMT_ACCOUNT_ID: str = ""  # 资金账号
    QMT_EXE_PATH: str = ""  # XtMiniQmt.exe完整路径（自启动用）
    QMT_ALWAYS_CONNECT: bool = False  # True=不管EXECUTION_MODE都尝试连接QMT

    # --- Paper Trading ---
    PAPER_STRATEGY_ID: str = ""
    PAPER_INITIAL_CAPITAL: float = 1_000_000.0

    # --- 执行操作认证 ---
    ADMIN_TOKEN: str = ""  # 执行操作API认证token

    # --- 远程状态API ---
    REMOTE_API_KEY: str = ""  # 空字符串=禁用认证（仅本地开发），生产必须设置

    # --- 服务 ---
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000


settings = Settings()
