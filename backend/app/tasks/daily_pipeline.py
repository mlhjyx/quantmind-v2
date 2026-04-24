"""Paper Trading 日调度任务 — Celery task 封装。

每个 task 用 asyncio.run() 包装 async 逻辑（CLAUDE.md 标准写法）。
实际业务逻辑复用 scripts/run_paper_trading.py 中的函数，
本模块只负责 Celery 任务注册 + 异常处理 + 日志记录。

Sprint 1.0: 任务定义，可通过 celery_app.send_task() 手动触发。
Sprint 1.1: 由 Beat 自动调度。
Sprint 1.9: health_check结果写Redis，signal_task启动前检查。
"""

import asyncio
import json
import logging
import time
from datetime import date, datetime

import redis

from app.config import settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.daily_pipeline")

# Redis key模板: health_check结果，TTL=24h
HEALTH_CHECK_KEY_TEMPLATE = "task_status:{date}:health_check"
HEALTH_CHECK_TTL = 86400  # 24小时


def _get_redis_client() -> redis.Redis:
    """获取Redis连接（用于任务间状态传递）。"""
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def _health_check_key(d: date) -> str:
    """生成health_check Redis key。"""
    return HEALTH_CHECK_KEY_TEMPLATE.format(date=d.isoformat())


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
    结果写入Redis供signal_task检查。

    Returns:
        预检结果 dict（JSON 序列化存 Celery result backend）。
    """
    logger.info("[HealthCheck] 开始预检...")
    t0 = time.time()
    try:
        result = asyncio.run(_async_health_check())
        elapsed = time.time() - t0
        logger.info(f"[HealthCheck] 完成 ({elapsed:.1f}s): pass={result.get('all_pass')}")

        # 写入Redis供signal_task检查
        try:
            r = _get_redis_client()
            key = _health_check_key(date.today())
            r.setex(key, HEALTH_CHECK_TTL, json.dumps(result))
            logger.info("[HealthCheck] 结果已写入Redis: %s", key)
        except Exception as e:
            logger.error("[HealthCheck] 写入Redis失败: %s", e)

        # ── StreamBus: 健康检查结果事件 ──
        try:
            from app.core.stream_bus import STREAM_HEALTH_CHECK_RESULT, get_stream_bus

            get_stream_bus().publish_sync(
                STREAM_HEALTH_CHECK_RESULT,
                {
                    "date": date.today().isoformat(),
                    "all_pass": result.get("all_pass"),
                    "elapsed_s": round(elapsed, 1),
                    "checks": result,
                },
                source="daily_pipeline",
            )
        except Exception:
            # S3 F78 修复: 加 logger.warning, publish 失败不阻塞但必须可追溯
            logger.warning(
                "[daily_pipeline] health_check StreamBus publish 失败", exc_info=True
            )

        return result
    except Exception as exc:
        logger.error(f"[HealthCheck] 异常: {exc}")
        raise self.retry(exc=exc) from exc


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
        usage = shutil.disk_usage("D:\\")
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
# T日 14:30 — Risk Framework 日检 (MVP 3.1 批 1 Session 29)
# 替代老 pms_check, 走 PlatformRiskEngine + PMSRule (ADR-010 D3)
# ════════════════════════════════════════════════════════════


@celery_app.task(
    bind=True,
    name="daily_pipeline.risk_check",
    acks_late=True,
    max_retries=1,
    default_retry_delay=60,
    time_limit=300,
)
def risk_daily_check_task(self) -> dict:
    """Risk Framework 日检 (MVP 3.1 批 1 PR 3, 2026-04-24 Session 29).

    Celery Beat risk-daily-check 14:30 Mon-Fri 触发. 非交易日自动跳过.
    走 PlatformRiskEngine + PMSRule (替代老 pms_engine.check_protection).

    批 1 行为保持 v1 语义: LoggingSellBroker 仅 log 不实盘卖, 批 2 接真 broker.
    risk_event_log 仍完整记录触发上下文 (risk_wiring.LoggingSellBroker + engine._log_event).

    关联铁律: 22 (doc 跟随代码) / 24 (单一职责) / 33 (fail-loud) / 34 (Config SSOT)

    Returns:
        执行摘要: {status, checked, triggered, signals}
    """
    from engines.trading_day_checker import TradingDayChecker

    checker = TradingDayChecker()
    is_td, reason = checker.is_trading_day(date.today())
    if not is_td:
        logger.info("[Risk] 非交易日(%s), 跳过", reason)
        return {"status": "skipped", "reason": reason}

    if not settings.PMS_ENABLED:
        # PMS_ENABLED=False 时整个 Risk Framework 关闭 (批 2 intraday 独立 flag 再加)
        logger.info("[Risk] PMS_ENABLED=False, 跳过")
        return {"status": "disabled"}

    strategy_id = getattr(settings, "PAPER_STRATEGY_ID", "")
    if not strategy_id:
        logger.error("[Risk] PAPER_STRATEGY_ID 未配置")
        return {"status": "error", "message": "PAPER_STRATEGY_ID未配置"}

    execution_mode = getattr(settings, "EXECUTION_MODE", "paper")

    from app.services.risk_wiring import build_risk_engine

    try:
        engine = build_risk_engine()
        context = engine.build_context(
            strategy_id=strategy_id, execution_mode=execution_mode
        )
        if not context.positions:
            logger.info("[Risk] 无持仓, 跳过")
            return {
                "status": "ok",
                "checked": 0,
                "triggered": 0,
                "execution_mode": execution_mode,
            }

        results = engine.run(context)
        engine.execute(results, context)

        summary = {
            "status": "ok",
            "checked": len(context.positions),
            "triggered": len(results),
            "execution_mode": execution_mode,
            "signals": [
                {"rule_id": r.rule_id, "code": r.code, "shares": r.shares}
                for r in results
            ],
        }
        logger.info(
            "[Risk] 日检完成: checked=%d triggered=%d mode=%s",
            summary["checked"], summary["triggered"], execution_mode,
        )
        return summary

    except Exception as exc:
        logger.error("[Risk] 日检异常: %s", exc, exc_info=True)
        raise self.retry(exc=exc) from exc


# ════════════════════════════════════════════════════════════
# DEPRECATED: 老 pms_check (ADR-010 Session 21 已停 Beat, MVP 3.1 批 1 新 risk_check 替代)
# 保留 1 sprint 供紧急回滚, 批 3 CB adapter 完成后 + pms_engine.py 一并物理删除
# ════════════════════════════════════════════════════════════


@celery_app.task(
    bind=True,
    name="daily_pipeline.pms_check",
    acks_late=True,
    max_retries=1,
    default_retry_delay=60,
    time_limit=300,
)
def pms_daily_check_task(self) -> dict:
    """PMS阶梯利润保护检查 [DEPRECATED per ADR-010].

    .. warning::
       **DEPRECATED per ADR-010 (Session 21 2026-04-21) — MVP 3.1 批 1 Session 29 新任务替代**

       Celery Beat pms-daily-check 调度已停 (beat_schedule.py Session 21).
       本 task function 保留仅供参考, 手工触发 (task queue 直发) 仍能跑但**禁止**生产使用.
       新生产任务 = `daily_pipeline.risk_check` (走 PlatformRiskEngine + PMSRule).
       并入 Wave 3 MVP 3.1 Risk Framework (backend/platform/risk/rules/pms.py).

    14:30执行，检查所有持仓是否触发利润保护。
    非交易日自动跳过。

    Returns:
        检查结果 dict。
    """
    # 交易日检查
    from engines.trading_day_checker import TradingDayChecker

    from app.core.qmt_client import get_qmt_client
    from app.services.pms_engine import PMSEngine
    checker = TradingDayChecker()
    is_td, reason = checker.is_trading_day(date.today())
    if not is_td:
        logger.info("[PMS] 非交易日(%s)，跳过", reason)
        return {"status": "skipped", "reason": reason}

    if not settings.PMS_ENABLED:
        logger.info("[PMS] PMS已禁用")
        return {"status": "disabled"}

    engine = PMSEngine()
    strategy_id = getattr(settings, "PAPER_STRATEGY_ID", "")
    if not strategy_id:
        return {"status": "error", "message": "PAPER_STRATEGY_ID未配置"}

    conn = _get_redis_client  # 占位，实际用sync DB连接
    from app.services.db import get_sync_conn
    conn = get_sync_conn()

    try:
        positions = engine.sync_positions(conn, strategy_id)
        if not positions:
            logger.info("[PMS] 无持仓，跳过")
            return {"status": "ok", "checked": 0, "triggered": 0}

        codes = [p["code"] for p in positions]
        peak_prices = engine.get_peak_prices(conn, codes)

        client = get_qmt_client()
        current_prices = client.get_prices(codes)

        sell_signals = engine.check_all_positions(positions, peak_prices, current_prices)

        # ADR-010 F31 去重 (Session 21 2026-04-21, reviewer MEDIUM 采纳):
        # 原此处有 StreamBus publish, 与 api/pms.py 重复且无消费者 (F27).
        # PMS v1 整体 DEPRECATED per ADR-010, 仅保留 record_trigger + logger.info
        # 供调试 (已停 Beat, 手工触发仍能跑但禁生产). Risk Framework MVP 3.1 批 2 迁移时删.
        for sig in sell_signals:
            engine.record_trigger(conn, sig, strategy_id, date.today())
            logger.info(
                "[PMS] 触发: %s 层级%d 浮盈=%.1f%% 回撤=%.1f%%",
                sig.code, sig.level,
                sig.unrealized_pnl_pct * 100,
                sig.drawdown_from_peak_pct * 100,
            )

        conn.commit()

        result = {
            "status": "ok",
            "checked": len(positions),
            "triggered": len(sell_signals),
            "signals": [
                {"code": s.code, "level": s.level}
                for s in sell_signals
            ],
        }
        logger.info("[PMS] 检查完成: %d只持仓, %d只触发", len(positions), len(sell_signals))
        return result

    except Exception as exc:
        conn.rollback()
        logger.error("[PMS] 检查异常: %s", exc, exc_info=True)
        raise self.retry(exc=exc) from exc
    finally:
        conn.close()


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

    启动前检查Redis中的health_check结果:
    - 未通过: 跳过信号生成 + 发送P0告警
    - 无结果: 放行但打warning log（手动触发场景）

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

    # ── 检查health_check结果 ──
    health_status = _check_health_gate(trade_date)
    if health_status == "failed":
        msg = f"[Signal] health_check未通过，跳过T日={trade_date}信号生成"
        logger.error(msg)
        _send_health_gate_alert(trade_date)
        return {"status": "skipped", "trade_date": trade_date_str,
                "reason": "health_check_failed"}
    elif health_status == "missing":
        logger.warning(
            "[Signal] 无health_check结果(T日=%s)，放行（可能是手动触发）",
            trade_date,
        )

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
        raise self.retry(exc=exc) from exc


def _check_health_gate(trade_date: date) -> str:
    """检查Redis中的health_check结果。

    Args:
        trade_date: T日日期。

    Returns:
        "passed" / "failed" / "missing"。
    """
    try:
        r = _get_redis_client()
        key = _health_check_key(trade_date)
        raw = r.get(key)
        if raw is None:
            return "missing"
        result = json.loads(raw)
        return "passed" if result.get("all_pass") else "failed"
    except Exception as e:
        logger.warning("[Signal] 读取health_check Redis失败: %s，放行", e)
        return "missing"


def _send_health_gate_alert(trade_date: date) -> None:
    """health_check未通过时发送P0告警。"""
    try:
        from app.services.notification_service import NotificationService

        ns = NotificationService()
        # 读取失败详情
        r = _get_redis_client()
        key = _health_check_key(trade_date)
        raw = r.get(key)
        details = json.loads(raw) if raw else {}
        failed_items = [k for k, v in details.items() if k != "all_pass" and not v]

        import psycopg2
        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        try:
            ns.send_sync(
                conn=conn,
                level="P0",
                category="pipeline",
                title=f"健康预检未通过，信号生成已跳过 T={trade_date}",
                content=f"失败项: {', '.join(failed_items) if failed_items else '未知'}",
                force=True,
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error("[Signal] 发送P0告警失败: %s", e)


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
        raise self.retry(exc=exc) from exc


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


# ════════════════════════════════════════════════════════════
# T日 17:40 — 数据质量报告 (DATA_SYSTEM_V1 P1-2)
# ════════════════════════════════════════════════════════════


@celery_app.task(
    bind=True,
    name="daily_pipeline.data_quality_report",
    acks_late=True,
    max_retries=1,
    default_retry_delay=300,
    time_limit=900,
)
def data_quality_report_task(self, trade_date_str: str | None = None) -> dict:
    """T日 17:40 数据质量日报.

    触发: Celery Beat daily-quality-report (17:40 work days)
    内容: L1 ingest + L2 factor_raw/neutral + L3 reconcile + freshness
    输出: logs/quality_report_{date}.json + StreamBus 告警 (WARN/FAIL)
    铁律对齐: DATA_SYSTEM_V1 §8.1 + 铁律 29 (NaN 检测) + 铁律 20 (质量)

    非交易日快速跳过.
    """
    from engines.trading_day_checker import TradingDayChecker

    td = (
        datetime.strptime(trade_date_str, "%Y-%m-%d").date()
        if trade_date_str else date.today()
    )
    checker = TradingDayChecker()
    is_td, reason = checker.is_trading_day(td)
    if not is_td:
        logger.info(f"[QualityReport] 非交易日({reason}), 跳过")
        return {"status": "skipped", "reason": reason, "trade_date": str(td)}

    from app.core.stream_bus import get_stream_bus
    from app.services.data_orchestrator import DataOrchestrator

    DEFAULT_FACTORS = [
        "turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm",
        "high_freq_volatility_20", "volume_concentration_20", "volume_autocorr_20",
        "smart_money_ratio_20", "opening_volume_share_20", "closing_trend_strength_20",
        "vwap_deviation_20", "order_flow_imbalance_20", "intraday_momentum_20",
        "volume_price_divergence_20",
    ]
    DEFAULT_L1 = ["klines_daily", "daily_basic", "moneyflow_daily",
                  "minute_bars", "index_daily", "symbols"]

    orch = DataOrchestrator("2021-01-01", "2025-12-31")
    t0 = time.time()
    report = orch.run_daily_quality(trade_date=td, factor_names=DEFAULT_FACTORS)
    report["freshness"] = orch.check_freshness(DEFAULT_L1)
    report["elapsed_sec"] = round(time.time() - t0, 1)

    # 持久化
    import json
    from pathlib import Path

    out_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"quality_report_{td}.json"
    out_path.write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )

    # 告警
    if report["overall"] in ("WARN", "FAIL"):
        try:
            bus = get_stream_bus()
            bus.publish_sync(
                "qm:quality:alert",
                {
                    "level": report["overall"],
                    "trade_date": str(td),
                    "failures": report["failures"],
                    "warnings": report["warnings"],
                },
                source="quality_report_beat",
            )
        except Exception as e:  # silent_ok: 告警失败不阻塞
            logger.warning(f"[QualityReport] 告警广播失败: {e}")

    logger.info(
        f"[QualityReport] trade_date={td} overall={report['overall']} "
        f"elapsed={report['elapsed_sec']}s warnings={len(report['warnings'])} "
        f"failures={len(report['failures'])} out={out_path.name}"
    )
    return {
        "status": "ok",
        "trade_date": str(td),
        "overall": report["overall"],
        "warnings": len(report["warnings"]),
        "failures": len(report["failures"]),
        "output": str(out_path),
    }


@celery_app.task(
    bind=True,
    name="daily_pipeline.factor_lifecycle",
    acks_late=True,
    max_retries=1,
    default_retry_delay=300,
    time_limit=600,
)
def factor_lifecycle_task(self) -> dict:
    """因子生命周期自动状态转换 (Phase 3 MVP A).

    触发: Celery Beat factor-lifecycle-weekly (周五 19:00 工作日)
    规则: DEV_AI_EVOLUTION V2.1 §3.1
        active ↔ warning  (|IC_MA20|/|IC_MA60| < 0.8 / ≥ 0.8)
        warning → critical (ratio < 0.5 持续 20 天)
    L2 critical → retired 需人确认, 本 task 不自动执行.
    铁律 23/24: 独立可执行 MVP. 铁律 32: task 负责 commit.
    """
    import sys
    from pathlib import Path

    # 复用 scripts/factor_lifecycle_monitor.py 的 run() 函数 (纯 Python 调用)
    # __file__ = backend/app/tasks/daily_pipeline.py → parents[3] = quantmind-v2 root
    project_root = Path(__file__).resolve().parents[3]
    scripts_dir = project_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from factor_lifecycle_monitor import run as run_lifecycle

    try:
        result = run_lifecycle(dry_run=False, factor_filter=None)
        logger.info(
            f"[FactorLifecycle] checked={result['checked']} "
            f"no_data={result['no_data']} transitions={len(result['transitions'])}"
        )
        return {"status": "ok", **result}
    except Exception as e:
        logger.exception(f"[FactorLifecycle] 失败: {e}")
        raise
