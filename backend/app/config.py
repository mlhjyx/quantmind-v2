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
    # S1 F15 / S2 F65 (2026-04-15): default 含占位密码 "quantmind", 实际生产必须由 .env 覆盖.
    # 如果 .env 缺失, Settings() 会用本默认值 (可能连到本地开发数据库但密码弱).
    DATABASE_URL: str = "postgresql+asyncpg://xin:REPLACE_WITH_ENV@localhost:5432/quantmind_v2"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- 数据源 ---
    TUSHARE_TOKEN: str = ""

    # --- AI ---
    DEEPSEEK_API_KEY: str = ""

    # --- 执行模式 ---
    EXECUTION_MODE: Literal["paper", "live"] = "paper"

    # --- 真金硬开关 (T1 sprint link-pause, 2026-04-29) ---
    # 默认 True (fail-secure): MiniQMTBroker.place_order / cancel_order 直 raise
    # LiveTradingDisabledError. paper_broker 物理隔离不受影响 (guard 只挂 MiniQMTBroker).
    # 双因素 OVERRIDE bypass:
    #   LIVE_TRADING_FORCE_OVERRIDE=1
    #   LIVE_TRADING_OVERRIDE_REASON='<明确原因>'
    # 缺一者拒绝 + DingTalk P0 + audit log.
    # 撤销: docs/audit/link_paused_2026_04_29.md (T1.4 完成 / 批 2 写路径漂移修后).
    LIVE_TRADING_DISABLED: bool = True

    # --- Paper Trading 核心参数 ---
    PT_TOP_N: int = 20  # was 15, changed 2026-04-04, backtest X-D Sharpe 1.15
    PT_INDUSTRY_CAP: float = 1.0  # was 0.25, changed 2026-04-04, removing constraint +0.09 Sharpe
    # S2 F62 fix (2026-04-15): default 从 0.0 改为 0.50.
    # 原因: 当前 PT CORE3+dv_ttm WF OOS Sharpe=0.8659 强依赖 Size-Neutral b=0.50 (Step 6-H 验证).
    # 如果 .env 意外缺失 PT_SIZE_NEUTRAL_BETA, 旧 default 0.0 会静默降级到无 SN (-27% Sharpe).
    # 需显式关闭 SN 请在 .env 写 PT_SIZE_NEUTRAL_BETA=0.0
    PT_SIZE_NEUTRAL_BETA: float = 0.50

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
    # T0-15/16/批 2 (2026-04-30): 钉钉告警全局 default-off 双锁. False 时 dingtalk_alert
    # helper 不真发请求, 仅写 alert_dedup audit row + log. True 时配合 alert_dedup 1h
    # 去重才真发. 防 5-5 周一前真生产风暴, 也防 PR #150 36h spam 重演.
    DINGTALK_ALERTS_ENABLED: bool = False
    # alert_dedup TTL 默认 60 min (1h, 业界默认 + Q9 决议)
    DINGTALK_DEDUP_TTL_MIN: int = 60
    DINGTALK_SECRET: str = ""  # HMAC签名密钥（加签模式），为空则不签名
    DINGTALK_KEYWORD: str = ""  # 自定义关键词（关键词模式），非空时自动追加到消息

    # MVP 4.1 batch 3+ Platform SDK 迁移开关 (默认 True 走 PlatformAlertRouter SDK,
    # 含 cross-process PG dedup + AlertRulesEngine yaml-driven). caller 设 False 走旧
    # dingtalk.send_markdown_sync 直调路径 (fallback, 紧急回滚用). 17 scripts 串行迁移
    # 期间 caller 各自独立切换 (不影响其他 scripts).
    OBSERVABILITY_USE_PLATFORM_SDK: bool = True

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
