"""structlog JSON结构化日志配置 — Sprint 1.15 Task 4。

设计基础:
    - R6研究: structlog JSON + RotatingFileHandler
    - 日志格式: JSON lines，便于后续解析

处理器链（R6 §7）:
    1. add_log_level      — 添加level字段
    2. add_logger_name    — 添加logger字段
    3. TimeStamper        — ISO8601时间戳
    4. StackInfoRenderer  — 异常堆栈
    5. JSONRenderer       — 输出JSON

文件策略:
    - 轮转: 每文件10MB，保留7个
    - 路径: D:/quantmind-v2/logs/app.log
    - 控制台: 开发模式时也输出到stdout（ConsoleRenderer）

集成方式（在main.py的lifespan中调用）:
    from app.logging_config import configure_logging
    configure_logging()

用法示例:
    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("回测完成", run_id="abc", sharpe=1.03)
    # → {"event": "回测完成", "run_id": "abc", "sharpe": 1.03, ...}
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

import structlog

# ─────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────

LOG_DIR = Path("D:/quantmind-v2/logs")
LOG_FILE = LOG_DIR / "app.log"
MAX_BYTES = 10 * 1024 * 1024  # 10MB per file
BACKUP_COUNT = 7               # 保留7个轮转文件
DEFAULT_LEVEL = logging.INFO


def _ensure_log_dir(log_file: Path | None = None) -> None:
    """确保日志目录存在。"""
    target = log_file.parent if log_file else LOG_DIR
    target.mkdir(parents=True, exist_ok=True)


def _build_processors(dev_mode: bool) -> list:
    """构建structlog处理器链。

    Args:
        dev_mode: True=开发模式（彩色控制台）, False=生产模式（JSON）

    Returns:
        structlog processors列表
    """
    shared = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if dev_mode:
        # 开发模式: 彩色可读格式
        shared.append(structlog.dev.ConsoleRenderer())
    else:
        # 生产模式: JSON lines
        shared.append(structlog.processors.JSONRenderer())

    return shared


def configure_logging(
    level: int = DEFAULT_LEVEL,
    dev_mode: bool | None = None,
    log_file: Path | None = None,
) -> None:
    """配置structlog JSON结构化日志。

    替换现有的basicConfig配置，在FastAPI启动时调用。

    Args:
        level: 日志级别（默认INFO）
        dev_mode: True=开发模式（彩色控制台），None=自动检测（读ENVIRONMENT变量）
        log_file: 日志文件路径（默认LOG_FILE）
    """
    if log_file is None:
        log_file = LOG_FILE
    _ensure_log_dir(log_file)

    # 自动检测开发/生产模式
    if dev_mode is None:
        env = os.environ.get("ENVIRONMENT", "development").lower()
        dev_mode = env in ("development", "dev", "local")

    processors = _build_processors(dev_mode)

    # ── structlog配置 ──
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ── stdlib logging配置（structlog通过stdlib桥接） ──
    handlers: list[logging.Handler] = []

    # 1. 文件处理器（RotatingFileHandler）
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(log_file),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    handlers.append(file_handler)

    # 2. 控制台处理器（始终启用，开发模式更详细）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    handlers.append(console_handler)

    # 配置根日志器
    logging.basicConfig(
        format="%(message)s",  # structlog已处理格式
        level=level,
        handlers=handlers,
        force=True,  # 替换现有配置
    )

    # 降低第三方库的日志级别（减少噪音）
    for noisy_logger in [
        "uvicorn.access",
        "sqlalchemy.engine",
        "asyncio",
        "socketio",
        "engineio",
        "celery",
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # 使用structlog输出启动日志
    logger = structlog.get_logger(__name__)
    logger.info(
        "日志系统已配置",
        mode="development" if dev_mode else "production",
        log_file=str(log_file),
        level=logging.getLevelName(level),
        max_bytes_mb=MAX_BYTES // (1024 * 1024),
        backup_count=BACKUP_COUNT,
    )


def get_logger(name: str = "") -> Any:
    """获取structlog logger实例（便捷函数）。

    替代 logging.getLogger(__name__)，用法相同。

    Args:
        name: logger名称（通常传__name__）

    Returns:
        structlog BoundLogger实例
    """
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()
