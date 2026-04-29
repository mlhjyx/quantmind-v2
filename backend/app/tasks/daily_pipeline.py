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
from dataclasses import replace
from datetime import UTC, date, datetime

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
# scheduler_task_log helper (Phase 2 Step C, Session 44 2026-04-29)
#
# 动机: Session 44 实测 risk_daily_check + intraday_risk_check **缺 scheduler_task_log
# 写入** — Beat 调度且 Celery worker 已收到, 但 audit log 0 行 → 无法事后审计
# "今天 14:30 风控真的跑了吗", 与 dead-Beat 无法区分.
#
# 与 risk_event_log 的区别:
#   - risk_event_log: 仅当 rule.evaluate 命中 (RuleResult 非空) 时写, 0 命中 = 0 行
#   - scheduler_task_log: 每次 task 跑完都写 (proof of life), 含 0 命中
#
# 镜像 scripts/pt_audit.py:_write_scheduler_task_log pattern (silent_ok 失败).
# 铁律: 33(c) 读路径 audit 失败 fail-silent + logger.warning, 不阻塞主流程.
# ════════════════════════════════════════════════════════════


def _write_scheduler_log_safe(
    task_name: str,
    start_time: datetime,
    status: str,
    result_json: dict | None,
) -> None:
    """Best-effort scheduler_task_log INSERT (silent_ok on failure).

    主路径已完成 (rules evaluated + alerts fired), audit 写失败仅 warning, 不 raise.
    与 pt_audit.py:_write_scheduler_task_log 同 pattern (PR #134/135 已沉淀).

    Args:
        task_name: Beat schedule entry name (e.g. "risk_daily_check")
        start_time: task 进入 timestamp (UTC, 上游捕获)
        status: 'success' | 'skipped' | 'disabled' | 'error' | 'retry'
        result_json: task summary dict (or {"error": str} on exception)
    """
    import psycopg2.extras

    from app.services.db import get_sync_conn

    end_time = datetime.now(UTC)
    duration_sec = int((end_time - start_time).total_seconds())
    try:
        with get_sync_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scheduler_task_log
                   (task_name, market, schedule_time, start_time, end_time,
                    duration_sec, status, result_json)
                   VALUES (%s, 'astock', %s, %s, %s, %s, %s, %s)""",
                (
                    task_name,
                    start_time,  # schedule_time 用 start (Beat 触发时刻 ≈ task 进入)
                    start_time,
                    end_time,
                    duration_sec,
                    status,
                    psycopg2.extras.Json(result_json or {}),
                ),
            )
    except Exception as e:  # noqa: BLE001
        # silent_ok: scheduler_task_log 失败不阻断主流程 audit / risk action
        # 已完成. 上层 logger.error 仍捕获故障 trace.
        logger.warning(
            "[scheduler_task_log] write failed task=%s: %s: %s",
            task_name, type(e).__name__, e,
        )


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

    from app.services.db import get_sync_conn

    # Phase 2 Step C (Session 44): scheduler_task_log audit 包络 — 每次 task 进入都
    # 必写一行, 含 0 命中 / skipped / disabled / error, 防 dead-Beat 与 0-trigger
    # 不可区分. try/finally 确保所有路径 (含 raise self.retry) 都写一行.
    _audit_start = datetime.now(UTC)
    _audit_status = "error"  # default if exception escapes try
    _audit_summary: dict = {}
    try:
        # reviewer P1-1 采纳 (code-reviewer): TradingDayChecker 无 conn 会降级到 Layer 4
        # 启发式 (约 7-10 个工作日法定节假日/年会误判为交易日). Risk 检查要求准确交易日
        # 判断, 传 conn 启用 Layer 3 本地 DB calendar (铁律 33 fail-loud vs silent drift).
        td_conn = get_sync_conn()
        try:
            checker = TradingDayChecker(conn=td_conn)
            is_td, reason = checker.is_trading_day(date.today())
        finally:
            td_conn.close()
        if not is_td:
            logger.info("[Risk] 非交易日(%s), 跳过", reason)
            _audit_summary = {"status": "skipped", "reason": reason}
            _audit_status = "skipped"
            return _audit_summary

        if not settings.PMS_ENABLED:
            # PMS_ENABLED=False 时整个 Risk Framework 关闭 (批 2 intraday 独立 flag 再加)
            logger.info("[Risk] PMS_ENABLED=False, 跳过")
            _audit_summary = {"status": "disabled"}
            _audit_status = "disabled"
            return _audit_summary

        execution_mode = settings.EXECUTION_MODE

        # MVP 3.2 批 4: 多策略 iteration via strategy_registry.get_live() + fail-safe
        # fallback. S1 固定 LIVE, 未来 S2 注册后自动加入迭代 (代码零改动).
        # Fail-safe: registry 挂 / empty → [S1MonthlyRanking()] legacy path, Monday 4-27
        # zero production 干扰.
        # MVP 3.1 批 3 (Session 30 末): CircuitBreakerRule Hybrid adapter 注入 daily engine
        # ADR-010 addendum 方案 C — 包 risk_control_service.check_circuit_breaker_sync
        # 14:30 评估 PMS + CB (两 rule 并列, CB 仅在 level 变化时返 RuleResult)
        #
        # P1 reviewer 采纳 (PR #139 fix): daily 14:30 与 intraday */5 9-14 共享 dedup,
        # 防同 (rule_id, strategy, mode, date) 双告警 (尤其 future auto_sell_l4=True 时
        # intraday 已发卖单, daily 不应再发第二次). dedup 失败 fail-open 允许告警.
        from app.services.risk_wiring import (
            IntradayAlertDedup,
            build_circuit_breaker_rule,
            build_risk_engine,
        )
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        strategies = get_live_strategies_for_risk_check()
        # P1 reviewer code (PR #72) 采纳: empty strategies 应显式 warn, 不 silent zero-work.
        # 理论 bootstrap 保底 [S1MonthlyRanking()] 非空, 但防御深度校验 — Monday 监控可见.
        if not strategies:
            logger.warning(
                "[Risk] get_live_strategies_for_risk_check() 返空 list — 14:30 风控检查 "
                "零策略执行. 检查 bootstrap fallback / strategy_registry DB 状态.",
            )
            _audit_summary = {
                "status": "ok",
                "execution_mode": execution_mode,
                "strategies": [],
                "strategies_count": 0,
                "total_checked": 0,
                "total_triggered": 0,
            }
            _audit_status = "success"
            return _audit_summary

        # P1 reviewer 采纳 (PR #139 fix): dedup 共享 intraday 同一 Redis key namespace —
        # 同 (rule_id, strategy, mode, date) 跨 daily/intraday 仅允许 1 次告警.
        dedup = IntradayAlertDedup()

        per_strategy_results: list[dict] = []
        total_checked = 0
        total_triggered = 0
        total_alerted = 0
        total_dedup_skipped = 0
        all_errored = True  # 若所有 strategy 都异常 → raise retry (Monday 安全兜底)

        for strategy in strategies:
            strategy_id = strategy.strategy_id
            try:
                engine = build_risk_engine(extra_rules=[build_circuit_breaker_rule()])
                context = engine.build_context(
                    strategy_id=strategy_id, execution_mode=execution_mode
                )
                if not context.positions:
                    logger.info("[Risk] strategy=%s 无持仓, 跳过", strategy_id)
                    per_strategy_results.append({
                        "strategy_id": strategy_id,
                        "status": "ok",
                        "checked": 0,
                        "triggered": 0,
                    })
                    all_errored = False
                    continue

                results = engine.run(context)

                # dedup gate (镜像 intraday_risk_check_task pattern, PR #60 reviewer P1):
                # 仅 should_alert 查询, mark 在 execute 成功后, 防 execute 失败永久 suppress.
                to_execute = []
                skipped = []
                for r in results:
                    if dedup.should_alert(r.rule_id, strategy_id, execution_mode):
                        to_execute.append(r)
                    else:
                        skipped.append(r.rule_id)

                if to_execute:
                    engine.execute(to_execute, context)
                    # mark_alerted AFTER successful execute (PR #60 reviewer P1 HIGH)
                    for r in to_execute:
                        dedup.mark_alerted(r.rule_id, strategy_id, execution_mode)

                per_strategy_results.append({
                    "strategy_id": strategy_id,
                    "status": "ok",
                    "checked": len(context.positions),
                    "triggered": len(results),
                    "alerted": len(to_execute),
                    "dedup_skipped": len(skipped),
                    "signals": [
                        {"rule_id": r.rule_id, "code": r.code, "shares": r.shares}
                        for r in to_execute
                    ],
                    "dedup_skipped_rules": skipped,
                })
                total_checked += len(context.positions)
                total_triggered += len(results)
                total_alerted += len(to_execute)
                total_dedup_skipped += len(skipped)
                all_errored = False
                logger.info(
                    "[Risk] strategy=%s 日检完成: checked=%d triggered=%d alerted=%d "
                    "dedup_skipped=%d",
                    strategy_id, len(context.positions), len(results),
                    len(to_execute), len(skipped),
                )

            except Exception as exc:
                # per-strategy 异常: log + 继续 (other strategies 不受影响). 若所有都异常
                # 最后 raise retry (all_errored guard).
                logger.error(
                    "[Risk] strategy=%s 异常: %s", strategy_id, exc, exc_info=True,
                )
                per_strategy_results.append({
                    "strategy_id": strategy_id,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })

        # 全 strategy 异常 → Celery retry (对齐原 max_retries=1 语义). Monday 安全兜底:
        # 若 batch 4 代码引入的新 code path 全挂, Celery retry 给 1 次机会 + 失败告警.
        if all_errored and strategies:
            first_err = next(
                (s for s in per_strategy_results if s.get("status") == "error"), None
            )
            err_msg = first_err.get("error", "unknown") if first_err else "all strategies failed"
            exc = RuntimeError(f"All {len(strategies)} strategies failed: {err_msg}")
            logger.error("[Risk] 所有策略全挂, Celery retry: %s", exc)
            _audit_summary = {
                "status": "retry",
                "error": str(exc),
                "strategies_failed": len(strategies),
            }
            _audit_status = "retry"
            raise self.retry(exc=exc)

        _audit_summary = {
            "status": "ok",
            "execution_mode": execution_mode,
            "strategies": per_strategy_results,
            "strategies_count": len(strategies),
            "total_checked": total_checked,
            "total_triggered": total_triggered,
            "total_alerted": total_alerted,
            "total_dedup_skipped": total_dedup_skipped,
        }
        _audit_status = "success"
        logger.info(
            "[Risk] 日检完成: strategies=%d total_checked=%d total_triggered=%d "
            "total_alerted=%d total_dedup_skipped=%d mode=%s",
            len(strategies), total_checked, total_triggered,
            total_alerted, total_dedup_skipped, execution_mode,
        )
        return _audit_summary
    except Exception as e:
        # try 内未被显式 set 状态 → 记 error (Celery 异常通过 raise self.retry 上面已 set)
        if _audit_status == "error":
            _audit_summary = {
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            }
        raise
    finally:
        _write_scheduler_log_safe(
            "risk_daily_check", _audit_start, _audit_status, _audit_summary,
        )


# ════════════════════════════════════════════════════════════
# T日 09:35-15:00 — Intraday Risk Framework 5min 检查 (MVP 3.1 批 2 PR 2 Session 30)
# 组合级 3%/5%/8% 跌幅告警 + QMT 断连告警, Celery Beat `intraday-risk-check`
# ════════════════════════════════════════════════════════════


@celery_app.task(
    bind=True,
    name="daily_pipeline.intraday_risk_check",
    acks_late=True,
    max_retries=0,  # 5min 下次会再跑, 不 retry 积压
    time_limit=60,  # 5min 周期硬超时 (远小于 crontab 5min 间隔)
)
def intraday_risk_check_task(self) -> dict:
    """Intraday Risk Framework 盘中检查 (MVP 3.1 批 2 PR 2, 2026-04-24 Session 30).

    Celery Beat `intraday-risk-check` 5min cron (09:35-15:00 Mon-Fri, 72 次/日).
    (reviewer P3 采纳 code: `*/5 × 6h (9-14) = 12 × 6 = 72 次`, 原注释 54 算错)
    4 规则评估: IntradayPortfolioDrop{3,5,8}PctRule + QMTDisconnectRule.

    流程:
        交易日 check → build_intraday_risk_engine → build_context (填 prev_close_nav
        from performance_series) → run → dedup (Redis 24h TTL 同 rule 同日限 1 次)
        → execute (log + 钉钉 + risk_event_log) → mark_alerted AFTER execute 成功
        (reviewer P1 采纳 code: 防 execute 失败时 dedup 永久 suppress 当日告警)

    Action: 全部 alert_only (批 2 不实盘卖, 批 3 升真 broker 统一).

    铁律: 22 / 33 (fail-silent 读路径 + fail-loud 生产) / 34 / 41

    Returns:
        执行摘要 dict.
    """
    from engines.trading_day_checker import TradingDayChecker

    from app.services.db import get_sync_conn

    # Phase 2 Step C (Session 44): scheduler_task_log audit 包络 — intraday 5min cron
    # 72 次/日, 缺 audit 等于 dead-Beat 不可区分. 镜像 risk_daily_check pattern.
    _audit_start = datetime.now(UTC)
    _audit_status = "error"
    _audit_summary: dict = {}
    try:
        # 交易日 check (复用批 1 pattern, Layer 3 conn 启用)
        td_conn = get_sync_conn()
        try:
            checker = TradingDayChecker(conn=td_conn)
            is_td, reason = checker.is_trading_day(date.today())
        finally:
            td_conn.close()
        if not is_td:
            logger.info("[IntradayRisk] 非交易日(%s), 跳过", reason)
            _audit_summary = {"status": "skipped", "reason": reason}
            _audit_status = "skipped"
            return _audit_summary

        if not settings.PMS_ENABLED:
            # PMS_ENABLED=False 全 Risk Framework 关 (intraday 批 2 共享 flag, 独立 flag 批 3 评估)
            logger.info("[IntradayRisk] PMS_ENABLED=False, 跳过")
            _audit_summary = {"status": "disabled"}
            _audit_status = "disabled"
            return _audit_summary

        execution_mode = settings.EXECUTION_MODE

        # MVP 3.2 批 4: 多策略 iteration. Dedup 天然 per-strategy (key 含 strategy_id),
        # 各 strategy 独立告警频控无交叉污染.
        from app.services.risk_wiring import (
            IntradayAlertDedup,
            _load_prev_close_nav,
            build_intraday_risk_engine,
        )
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        strategies = get_live_strategies_for_risk_check()
        # P1 reviewer code (PR #72) 采纳: empty strategies 显式 warn (防御深度)
        if not strategies:
            logger.warning(
                "[IntradayRisk] get_live_strategies_for_risk_check() 返空 list — 5min "
                "盘中检查零策略. 下 5min 周期会再跑一次自愈.",
            )
            _audit_summary = {
                "status": "ok",
                "execution_mode": execution_mode,
                "strategies": [],
                "strategies_count": 0,
                "total_triggered": 0,
                "total_alerted": 0,
                "total_dedup_skipped": 0,
            }
            _audit_status = "success"
            return _audit_summary

        dedup = IntradayAlertDedup()  # 共享 Redis client, 跨 strategy 复用

        per_strategy_results: list[dict] = []
        total_triggered = 0
        total_alerted = 0
        total_dedup_skipped = 0
        all_errored = True

        for strategy in strategies:
            strategy_id = strategy.strategy_id
            try:
                engine = build_intraday_risk_engine()

                # 1. build_context 走批 1 engine 同逻辑 (prev_close_nav=None 占位)
                context = engine.build_context(
                    strategy_id=strategy_id, execution_mode=execution_mode
                )

                # 2. 填 prev_close_nav (批 2 新增, intraday drop rules 需要, per-strategy)
                nav_conn = get_sync_conn()
                try:
                    prev_close_nav = _load_prev_close_nav(
                        nav_conn, strategy_id, execution_mode
                    )
                finally:
                    nav_conn.close()
                context = replace(context, prev_close_nav=prev_close_nav)

                # 3. run rules
                results = engine.run(context)

                # 4. dedup filter (Redis 24h TTL 防泛滥) — 仅 should_alert 查询, 不 mark
                # reviewer P1 采纳 (code HIGH, PR #60): mark_alerted 必须在 execute 成功
                # **之后** 防 execute 失败永久 suppress 告警.
                to_execute = []
                skipped = []
                for r in results:
                    if dedup.should_alert(r.rule_id, strategy_id, execution_mode):
                        to_execute.append(r)
                    else:
                        skipped.append(r.rule_id)

                # 5. execute dedup 后结果
                if to_execute:
                    engine.execute(to_execute, context)
                    # 6. mark_alerted AFTER successful execute (reviewer P1 HIGH)
                    for r in to_execute:
                        dedup.mark_alerted(r.rule_id, strategy_id, execution_mode)

                per_strategy_results.append({
                    "strategy_id": strategy_id,
                    "status": "ok",
                    "prev_close_nav": prev_close_nav,
                    "portfolio_nav": context.portfolio_nav,
                    "positions_count": len(context.positions),
                    "triggered": len(results),
                    "alerted": len(to_execute),
                    "dedup_skipped": len(skipped),
                    "signals": [
                        {"rule_id": r.rule_id, "code": r.code} for r in to_execute
                    ],
                })
                total_triggered += len(results)
                total_alerted += len(to_execute)
                total_dedup_skipped += len(skipped)
                all_errored = False
                logger.info(
                    "[IntradayRisk] strategy=%s 盘中完成: triggered=%d alerted=%d "
                    "dedup_skipped=%d",
                    strategy_id, len(results), len(to_execute), len(skipped),
                )

            except Exception as exc:
                # per-strategy 异常: log + 继续. max_retries=0 不 retry, 下 5min 会再跑.
                logger.error(
                    "[IntradayRisk] strategy=%s 异常: %s", strategy_id, exc, exc_info=True,
                )
                per_strategy_results.append({
                    "strategy_id": strategy_id,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })

        # 全 strategy 异常 + 有 strategies → raise propagate Celery FAILURE → 监控告警
        # (max_retries=0, 不 retry, 下 5min 周期会自然再跑一次)
        if all_errored and strategies:
            first_err = next(
                (s for s in per_strategy_results if s.get("status") == "error"), None
            )
            err_msg = first_err.get("error", "unknown") if first_err else "all strategies failed"
            _audit_summary = {
                "status": "error",
                "error": err_msg,
                "strategies_failed": len(strategies),
            }
            _audit_status = "error"
            raise RuntimeError(
                f"[IntradayRisk] All {len(strategies)} strategies failed: {err_msg}"
            )

        _audit_summary = {
            "status": "ok",
            "execution_mode": execution_mode,
            "strategies": per_strategy_results,
            "strategies_count": len(strategies),
            "total_triggered": total_triggered,
            "total_alerted": total_alerted,
            "total_dedup_skipped": total_dedup_skipped,
        }
        _audit_status = "success"
        logger.info(
            "[IntradayRisk] 盘中完成: strategies=%d total_triggered=%d total_alerted=%d "
            "total_dedup_skipped=%d mode=%s",
            len(strategies), total_triggered, total_alerted, total_dedup_skipped, execution_mode,
        )
        return _audit_summary
    except Exception as e:
        # P2 reviewer 采纳 (PR #144 fix): 与 risk_daily_check 对称, 移除 `and not
        # _audit_summary` guard. all_errored RuntimeError 路径已在 raise 前 set
        # 完整 _audit_summary, 此处覆盖等价 (同 error type/msg). 保符号一致防未来
        # 新增 error path 时 silent skip audit log.
        if _audit_status == "error":
            _audit_summary = {
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            }
        raise
    finally:
        _write_scheduler_log_safe(
            "intraday_risk_check", _audit_start, _audit_status, _audit_summary,
        )


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
       并入 Wave 3 MVP 3.1 Risk Framework (backend/qm_platform/risk/rules/pms.py).

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

    # Phase 2 (PR #129 reviewer P1): 显式声明 composite_mode 防 library default 漂移.
    # 默认 G1_ONLY 来源 PR #128 实证 (12 周回放 g1-only=550 demotes, 0 hypothesis 噪音).
    # 实战 dry-run 14 demotes / 0 CORE 受影响.
    backend_dir = project_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from engines.factor_lifecycle import CompositeMode

    try:
        result = run_lifecycle(
            dry_run=False,
            factor_filter=None,
            composite_mode=CompositeMode.G1_ONLY,
        )
        logger.info(
            f"[FactorLifecycle] checked={result['checked']} "
            f"no_data={result['no_data']} transitions={len(result['transitions'])} "
            f"composite={result.get('composite_mode', 'off')} "
            f"synthesized={len(result.get('composite_synthesized', []))}"
        )
        return {"status": "ok", **result}
    except Exception as e:
        logger.exception(f"[FactorLifecycle] 失败: {e}")
        raise
