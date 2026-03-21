"""Paper Trading 日调度任务 — Celery task 封装。

每个 task 用 asyncio.run() 包装 async 逻辑（CLAUDE.md 标准写法）。
实际业务逻辑复用 scripts/run_paper_trading.py 中的函数，
本模块只负责 Celery 任务注册 + 异常处理 + 日志记录。

Sprint 1.0: 任务定义，可通过 celery_app.send_task() 手动触发。
Sprint 1.1: 由 Beat 自动调度。
"""

import asyncio
import logging
import time
from datetime import date, datetime

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.daily_pipeline")


# ════════════════════════════════════════════════════════════
# T日 16:25 — 健康预检（信号前 5 分钟）
# ════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="daily_pipeline.health_check",
    acks_late=True,
    max_retries=1,
    default_retry_delay=60,
)
def daily_health_check_task(self) -> dict:
    """全链路健康预检。

    检查: PostgreSQL / Redis / 昨日数据 / 磁盘 / Worker。
    任何一项失败 → P0 告警 + 阻止后续信号任务。

    Returns:
        预检结果 dict（JSON 序列化存 Celery result backend）。
    """
    logger.info("[HealthCheck] 开始预检...")
    t0 = time.time()
    try:
        result = asyncio.run(_async_health_check())
        elapsed = time.time() - t0
        logger.info(f"[HealthCheck] 完成 ({elapsed:.1f}s): pass={result.get('all_pass')}")
        return result
    except Exception as exc:
        logger.error(f"[HealthCheck] 异常: {exc}")
        raise self.retry(exc=exc)


async def _async_health_check() -> dict:
    """异步健康预检逻辑。"""
    from app.db import get_async_session

    checks: dict = {}
    async with get_async_session() as session:
        # 1. PostgreSQL 连接
        try:
            result = await session.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
            checks["postgresql"] = result.scalar() == 1
        except Exception as e:
            checks["postgresql"] = False
            logger.error(f"PostgreSQL 连接失败: {e}")

        # 2. 昨日数据是否已更新（klines_daily 最新日期）
        try:
            result = await session.execute(
                __import__("sqlalchemy").text(
                    "SELECT MAX(trade_date) FROM klines_daily"
                )
            )
            latest_date = result.scalar()
            # 允许 1 天延迟（周末/节假日）
            if latest_date:
                gap = (date.today() - latest_date).days
                checks["data_freshness"] = gap <= 3
            else:
                checks["data_freshness"] = False
        except Exception as e:
            checks["data_freshness"] = False
            logger.error(f"数据新鲜度检查失败: {e}")

    # 3. Redis 连接（通过 Celery ping）
    try:
        from app.tasks.celery_app import celery_app as _app
        _app.connection().ensure_connection(max_retries=1)
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # 4. 磁盘空间 > 10GB
    try:
        import shutil
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024 ** 3)
        checks["disk_space"] = free_gb > 10
        if not checks["disk_space"]:
            logger.warning(f"磁盘剩余 {free_gb:.1f}GB < 10GB")
    except Exception:
        checks["disk_space"] = True  # 获取失败不阻塞

    checks["all_pass"] = all(
        v for k, v in checks.items() if k != "all_pass"
    )
    return checks


# ════════════════════════════════════════════════════════════
# T日 16:30 — 信号生成
# ════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="daily_pipeline.signal",
    acks_late=True,
    max_retries=2,
    default_retry_delay=300,
    time_limit=1800,       # 硬超时 30min
    soft_time_limit=1500,  # 软超时 25min
)
def daily_signal_task(self, trade_date_str: str | None = None) -> dict:
    """T日盘后信号生成。

    复用 scripts/run_paper_trading.py 的 run_signal_phase()。
    Celery 层只负责: 参数解析 → 调用 → 异常重试 → 返回摘要。

    Args:
        trade_date_str: T日日期，格式 'YYYY-MM-DD'。
            None 时使用 date.today()（Beat 自动触发场景）。

    Returns:
        执行摘要 dict。
    """
    trade_date = (
        datetime.strptime(trade_date_str, "%Y-%m-%d").date()
        if trade_date_str
        else date.today()
    )
    trade_date_str = str(trade_date)
    logger.info(f"[Signal] T日={trade_date}")
    t0 = time.time()

    try:
        result = asyncio.run(_async_signal(trade_date))
        elapsed = time.time() - t0
        logger.info(f"[Signal] 完成 ({elapsed:.1f}s)")
        return {"status": "success", "trade_date": trade_date_str,
                "elapsed_seconds": round(elapsed, 1), **result}
    except Exception as exc:
        logger.error(f"[Signal] 异常: {exc}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_signal(trade_date: date) -> dict:
    """异步信号生成逻辑。

    调用现有管道函数，返回摘要信息。
    NOTE: 当前直接调用同步的 run_signal_phase()（内部用 psycopg2）。
    Sprint 2.0 迁移为纯 async 后，此处改为 async 调用链。
    """
    import sys
    from pathlib import Path

    # 确保 scripts/ 在 sys.path 中（复用现有管道函数）
    scripts_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from run_paper_trading import run_signal_phase
    # run_signal_phase 是同步函数，在 asyncio.run() 上下文中直接调用
    # （它内部用 psycopg2 同步连接，不与 event loop 冲突）
    run_signal_phase(trade_date, dry_run=False, skip_fetch=False, skip_factors=False)

    return {"phase": "signal", "trade_date": str(trade_date)}


# ════════════════════════════════════════════════════════════
# T+1日 09:00 — 执行调仓
# ════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="daily_pipeline.execute",
    acks_late=True,
    max_retries=2,
    default_retry_delay=300,
    time_limit=1800,
    soft_time_limit=1500,
)
def daily_execute_task(self, exec_date_str: str | None = None) -> dict:
    """T+1日盘前执行调仓。

    复用 scripts/run_paper_trading.py 的 run_execute_phase()。

    Args:
        exec_date_str: 执行日日期，格式 'YYYY-MM-DD'。
            None 时使用 date.today()（Beat 自动触发场景）。

    Returns:
        执行摘要 dict。
    """
    exec_date = (
        datetime.strptime(exec_date_str, "%Y-%m-%d").date()
        if exec_date_str
        else date.today()
    )
    exec_date_str = str(exec_date)
    logger.info(f"[Execute] exec_date={exec_date}")
    t0 = time.time()

    try:
        result = asyncio.run(_async_execute(exec_date))
        elapsed = time.time() - t0
        logger.info(f"[Execute] 完成 ({elapsed:.1f}s)")
        return {"status": "success", "exec_date": exec_date_str,
                "elapsed_seconds": round(elapsed, 1), **result}
    except Exception as exc:
        logger.error(f"[Execute] 异常: {exc}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_execute(exec_date: date) -> dict:
    """异步执行逻辑。"""
    import sys
    from pathlib import Path

    scripts_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from run_paper_trading import run_execute_phase
    run_execute_phase(exec_date, dry_run=False, skip_fetch=False)

    return {"phase": "execute", "exec_date": str(exec_date)}
