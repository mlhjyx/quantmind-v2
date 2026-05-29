"""MVP 4.2 sub-iter 7 (iter 65) — Daily attribution Beat task wrapper.

Wraps qm_platform.eval.attribution compute_* + persist_attribution + fire_residual_alert
behind a Celery task `daily_attribution_compute_task`. Scheduled by Beat entry
`daily-attribution-compute` (16:30 Mon-Fri Asia/Shanghai).

Initial scope (iter 65 entry — minimal viable):
  - Read latest NAV change from existing data sources (paper trading: PT NAV table)
  - Compute attribution snapshot from existing read models:
    position_snapshot + factor_values + factor_ic_history + symbols/klines_daily
    + trade_log cost rows.
  - Persist row via persist_attribution
  - fire_residual_alert if |residual| > 20 bps

Follow-up wiring:
  - Real RegimeInfo from regime_detector latest state

铁律对齐:
  - 31 Engine 纯计算 (compute_* in attribution.py stateless; persist 走 DI conn_factory)
  - 32 Service 不 commit (caller — Celery task — manages transaction)
  - 33 fail-soft (fire_residual_alert swallows dispatch errors)
  - 41 UTC 内部 (created_at NOW() in SQL)
  - 44 X9 post-merge ops: 新 Beat entry 必须 Servy restart QuantMind-CeleryBeat + Celery
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.config import settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

SH_TZ = ZoneInfo("Asia/Shanghai")


def _to_float(value: object, default: float = 0.0) -> float:
    """Decimal/None-safe conversion for psycopg2 scalar rows."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _get_sh_trade_date() -> date:
    """Asia/Shanghai 当前日期 (Beat 触发时刻, 铁律 41)."""
    return datetime.now(SH_TZ).date()


def _fetch_nav_snapshot(
    conn,
    trade_date: date,
    strategy_id: str,
    execution_mode: str = "paper",
) -> tuple[float, float | None, float]:
    """Fetch exact-date NAV change, NAV value, and benchmark alpha.

    `performance_series` is the PT/QMT NAV history SSOT used by paper-trading
    status, risk, and graduation checks. Prefer its `daily_return`; if older rows
    only have NAV, derive the return from the previous available NAV.

    Returns:
        (nav_change_pct, nav, alpha_vs_benchmark), all decimal fractions except
        nav in yuan. Missing exact-date NAV returns (0.0, None, 0.0)
        (silent_ok: attribution no-op when PT is paused or no NAV row exists).
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT nav, daily_return, excess_return
           FROM performance_series
           WHERE strategy_id = %s
             AND execution_mode = %s
             AND trade_date = %s
           LIMIT 1""",
        (strategy_id, execution_mode, trade_date),
    )
    row = cur.fetchone()
    if not row:
        logger.info(
            "[Attribution] no performance_series row for %s/%s/%s; nav_change=0",
            trade_date,
            strategy_id,
            execution_mode,
        )
        return 0.0, None, 0.0

    nav, daily_return, excess_return = row
    alpha_vs_benchmark = _to_float(excess_return, 0.0)
    if daily_return is not None:
        return (
            _to_float(daily_return),
            _to_float(nav, 0.0) if nav is not None else None,
            alpha_vs_benchmark,
        )

    if nav is None:
        logger.info(
            "[Attribution] performance_series nav is NULL for %s/%s/%s; nav_change=0",
            trade_date,
            strategy_id,
            execution_mode,
        )
        return 0.0, None, alpha_vs_benchmark

    cur.execute(
        """SELECT nav
           FROM performance_series
           WHERE strategy_id = %s
             AND execution_mode = %s
             AND trade_date < %s
           ORDER BY trade_date DESC
           LIMIT 1""",
        (strategy_id, execution_mode, trade_date),
    )
    prev_row = cur.fetchone()
    if not prev_row or prev_row[0] is None:
        logger.info(
            "[Attribution] no previous performance_series NAV before %s/%s/%s; nav_change=0",
            trade_date,
            strategy_id,
            execution_mode,
        )
        return 0.0, _to_float(nav), alpha_vs_benchmark

    prev_nav = float(prev_row[0])
    if prev_nav <= 0:
        logger.info(
            "[Attribution] previous NAV <= 0 before %s/%s/%s; nav_change=0",
            trade_date,
            strategy_id,
            execution_mode,
        )
        return 0.0, _to_float(nav), alpha_vs_benchmark
    return _to_float(nav) / prev_nav - 1.0, _to_float(nav), alpha_vs_benchmark


def _fetch_nav_change(
    conn,
    trade_date: date,
    strategy_id: str,
    execution_mode: str = "paper",
) -> float:
    """Backward-compatible wrapper returning only NAV daily change."""
    nav_change, _nav, _alpha = _fetch_nav_snapshot(
        conn,
        trade_date=trade_date,
        strategy_id=strategy_id,
        execution_mode=execution_mode,
    )
    return nav_change


def _get_pt_factor_names() -> list[str]:
    """Read PT factor names from the SignalConfig SSOT."""
    try:
        from engines.signal_engine import PAPER_TRADING_CONFIG  # noqa: PLC0415

        return list(PAPER_TRADING_CONFIG.factor_names)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[Attribution] cannot load PAPER_TRADING_CONFIG factors: %s: %s",
            type(exc).__name__,
            exc,
        )
        return []


def _fetch_portfolio_weights(
    conn,
    trade_date: date,
    strategy_id: str,
    execution_mode: str = "paper",
) -> dict[str, float]:
    """Fetch latest holdings weights up to trade_date from position_snapshot."""
    cur = conn.cursor()
    cur.execute(
        """SELECT code, weight
           FROM position_snapshot
           WHERE strategy_id = %s
             AND execution_mode = %s
             AND trade_date = (
                 SELECT MAX(trade_date)
                 FROM position_snapshot
                 WHERE strategy_id = %s
                   AND execution_mode = %s
                   AND trade_date <= %s
             )
             AND COALESCE(quantity, 0) > 0
             AND weight IS NOT NULL
             AND weight > 0""",
        (strategy_id, execution_mode, strategy_id, execution_mode, trade_date),
    )
    return {str(code): _to_float(weight) for code, weight in cur.fetchall()}


def _fetch_factor_exposures(
    conn,
    trade_date: date,
    codes: list[str],
    factor_names: list[str],
) -> dict[str, dict[str, float]]:
    """Fetch latest factor exposures for current holdings."""
    if not codes or not factor_names:
        return {}
    cur = conn.cursor()
    cur.execute(
        """SELECT MAX(trade_date)
           FROM factor_values
           WHERE trade_date <= %s
             AND code = ANY(%s)
             AND factor_name = ANY(%s)""",
        (trade_date, codes, factor_names),
    )
    row = cur.fetchone()
    factor_trade_date = row[0] if row else None
    if factor_trade_date is None:
        return {}

    cur.execute(
        """SELECT factor_name, code, COALESCE(neutral_value, zscore, raw_value)
           FROM factor_values
           WHERE trade_date = %s
             AND code = ANY(%s)
             AND factor_name = ANY(%s)""",
        (factor_trade_date, codes, factor_names),
    )
    exposures: dict[str, dict[str, float]] = {}
    for factor_name, code, value in cur.fetchall():
        if value is None:
            continue
        exposures.setdefault(str(factor_name), {})[str(code)] = _to_float(value)
    return exposures


def _fetch_factor_returns(
    conn,
    trade_date: date,
    factor_names: list[str],
) -> dict[str, float]:
    """Fetch latest IC proxy as per-factor attribution return input."""
    if not factor_names:
        return {}
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (factor_name)
                  factor_name,
                  COALESCE(ic_1d, ic_ma20, ic_5d, ic_10d, ic_20d)
           FROM factor_ic_history
           WHERE factor_name = ANY(%s)
             AND trade_date <= %s
           ORDER BY factor_name, trade_date DESC""",
        (factor_names, trade_date),
    )
    return {
        str(factor_name): _to_float(value)
        for factor_name, value in cur.fetchall()
        if value is not None
    }


def _fetch_sector_inputs(
    conn,
    trade_date: date,
    codes: list[str],
) -> tuple[dict[str, str], dict[str, float]]:
    """Fetch SW1 industry map and latest industry return inputs."""
    if not codes:
        return {}, {}
    cur = conn.cursor()
    cur.execute(
        """SELECT code, COALESCE(industry_sw1, '_unmapped')
           FROM symbols
           WHERE code = ANY(%s)""",
        (codes,),
    )
    industry_map = {str(code): str(industry) for code, industry in cur.fetchall()}

    cur.execute(
        """SELECT MAX(trade_date)
           FROM klines_daily
           WHERE trade_date <= %s""",
        (trade_date,),
    )
    row = cur.fetchone()
    price_trade_date = row[0] if row else None
    if price_trade_date is None:
        return industry_map, {}

    cur.execute(
        """SELECT COALESCE(s.industry_sw1, '_unmapped') AS industry,
                  AVG(k.pct_change) / 100.0 AS industry_return
           FROM klines_daily k
           JOIN symbols s ON s.code = k.code
           WHERE k.trade_date = %s
             AND COALESCE(s.industry_sw1, '_unmapped') = ANY(%s)
             AND k.pct_change IS NOT NULL
           GROUP BY COALESCE(s.industry_sw1, '_unmapped')""",
        (price_trade_date, list(set(industry_map.values()))),
    )
    return industry_map, {
        str(industry): _to_float(industry_return)
        for industry, industry_return in cur.fetchall()
        if industry_return is not None
    }


def _fetch_cost_trades(
    conn,
    trade_date: date,
    strategy_id: str,
    execution_mode: str,
) -> list[dict[str, float]]:
    """Fetch same-day trade costs for compute_by_cost."""
    cur = conn.cursor()
    cur.execute(
        """SELECT commission, stamp_tax, swap_cost, slippage_bps, fill_price, quantity
           FROM trade_log
           WHERE strategy_id = %s
             AND execution_mode = %s
             AND trade_date = %s
             AND fill_price IS NOT NULL
             AND quantity IS NOT NULL""",
        (strategy_id, execution_mode, trade_date),
    )
    trades: list[dict[str, float]] = []
    for commission, stamp_tax, swap_cost, slippage_bps, fill_price, quantity in cur.fetchall():
        traded_value = _to_float(fill_price) * _to_float(quantity)
        slippage = abs(_to_float(slippage_bps, 0.0)) / 10000.0 * traded_value
        trades.append(
            {
                "commission": _to_float(commission) + _to_float(stamp_tax) + _to_float(swap_cost),
                "slippage": slippage,
                "impact": 0.0,
                "overnight_gap": 0.0,
            }
        )
    return trades


# ════════════════════════════════════════════════════════════
# scheduler_task_log helper (iter 132 — Wave 4 audit envelope, LL-204 canonical)
# ════════════════════════════════════════════════════════════
# 镜像 daily_pipeline.py:_write_scheduler_log_safe (Session 44 Phase 2 Step C, iter 103
# PR #479 LL-204 sediment). Module-local copy per LL-206 sibling pattern; iter 134+
# promotion candidate to shared service when 5+ callers established.
# iter 132 (2026-05-26): W2-A F1 P0 closure — silent dispatch gap (0 scheduler_task_log
# row past 7d for daily-attribution-compute despite Beat schedule active).


def _write_scheduler_log_safe(
    task_name: str,
    start_time: datetime,
    status: str,
    result_json: dict | None,
) -> None:
    """Best-effort scheduler_task_log INSERT (silent_ok on failure).

    Args:
        task_name: Beat schedule entry name (e.g. "daily_attribution_compute")
        start_time: task 进入 timestamp (UTC, 上游捕获)
        status: 'success' | 'skipped' | 'disabled' | 'error' | 'retry'
        result_json: task summary dict (or {"error": str} on exception)
    """
    import psycopg2.extras  # noqa: PLC0415

    from app.services.db import get_sync_conn  # noqa: PLC0415

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
                    start_time,  # schedule_time ≈ start_time (Beat 触发时刻)
                    start_time,
                    end_time,
                    duration_sec,
                    status,
                    psycopg2.extras.Json(result_json or {}),
                ),
            )
    except Exception as e:  # noqa: BLE001
        # silent_ok: scheduler_task_log 失败不阻断主流程 audit/alert action 已完成.
        logger.warning(
            "[scheduler_task_log] write failed task=%s: %s: %s",
            task_name,
            type(e).__name__,
            e,
        )


@celery_app.task(bind=True, name="app.tasks.attribution_tasks.daily_attribution_compute_task")
def daily_attribution_compute_task(self, trade_date_str: str | None = None) -> dict:
    """Daily attribution Beat task — compute + persist + alert (MVP 4.2 iter 65).

    Beat 入口 `daily-attribution-compute` 16:30 Mon-Fri Asia/Shanghai.
    Trading-day guard 沿用 daily_pipeline.py 体例 (Beat crontab day_of_week=1-5 已过滤
    周末, 节假日 task 内部判断后续 wiring).

    iter 132 (2026-05-26): wrapped with scheduler_task_log audit envelope per W2-A F1
    P0 closure (sibling daily_pipeline.py factor_lifecycle_task iter 103 LL-204
    canonical). Fail-soft contract preserved — inner try/except swallows + returns
    error dict; outer try/finally writes scheduler_task_log row regardless.

    Args:
        trade_date_str: optional YYYY-MM-DD override (manual replay); default = today SH.

    Returns:
        dict — {trade_date, strategy_id, row_id, residual_bps, alert_fired} on success;
        {error, trade_date} on failure (fail-soft per 铁律 33 BLE001 annotation).
    """
    # iter 132: scheduler_task_log audit envelope (LL-204 canonical sibling pattern).
    # _audit_status default = "error" covers the fail-soft path (inner except swallows
    # + returns error dict, never re-raises) and also covers any unexpected escape
    # past the inner except. Success path explicitly sets "success" (L218-219); error
    # path explicitly sets "error" at the top of the inner except (L223 below).
    _audit_start = datetime.now(UTC)
    _audit_status = "error"
    _audit_summary: dict = {}
    try:
        try:
            from backend.qm_platform.eval.attribution import (
                DailyAttribution,
                compute_by_cost,
                compute_by_factor,
                compute_by_sector,
                compute_unexplained_residual,
                fire_residual_alert,
                persist_attribution,
            )

            # ── Parse trade_date ──
            if trade_date_str:
                trade_date = date.fromisoformat(trade_date_str)
            else:
                trade_date = _get_sh_trade_date()

            # ── Fetch inputs ──
            strategy_id = settings.PAPER_STRATEGY_ID

            from app.services.db import get_sync_conn  # noqa: PLC0415

            conn = get_sync_conn()
            try:
                nav_change_pct, nav_value, alpha_vs_benchmark = _fetch_nav_snapshot(
                    conn,
                    trade_date=trade_date,
                    strategy_id=strategy_id,
                    execution_mode="paper",
                )
                factor_names = _get_pt_factor_names()
                portfolio_weights = _fetch_portfolio_weights(
                    conn,
                    trade_date=trade_date,
                    strategy_id=strategy_id,
                    execution_mode="paper",
                )
                holding_codes = list(portfolio_weights)
                factor_exposures = _fetch_factor_exposures(
                    conn,
                    trade_date=trade_date,
                    codes=holding_codes,
                    factor_names=factor_names,
                )
                factor_returns = _fetch_factor_returns(
                    conn,
                    trade_date=trade_date,
                    factor_names=factor_names,
                )
                by_factor = compute_by_factor(
                    portfolio_weights,
                    factor_exposures,
                    factor_returns,
                )
                industry_map, industry_returns = _fetch_sector_inputs(
                    conn,
                    trade_date=trade_date,
                    codes=holding_codes,
                )
                by_sector = compute_by_sector(
                    portfolio_weights,
                    industry_map,
                    industry_returns,
                )
                cost_trades = _fetch_cost_trades(
                    conn,
                    trade_date=trade_date,
                    strategy_id=strategy_id,
                    execution_mode="paper",
                )
                by_cost = (
                    compute_by_cost(cost_trades, nav=nav_value)
                    if nav_value is not None and nav_value > 0
                    else {}
                )

                # ── Build attribution ──
                attribution_initial = DailyAttribution(
                    trade_date=trade_date,
                    strategy_id=strategy_id,
                    execution_mode="paper",
                    nav_change_pct=nav_change_pct,
                    by_factor=by_factor,
                    by_sector=by_sector,
                    by_regime=None,
                    by_cost=by_cost,
                    alpha_vs_benchmark=alpha_vs_benchmark,
                )

                residual = compute_unexplained_residual(attribution_initial)

                # Rebuild with populated residual (frozen dataclass)
                attribution_final = DailyAttribution(
                    trade_date=attribution_initial.trade_date,
                    strategy_id=attribution_initial.strategy_id,
                    execution_mode=attribution_initial.execution_mode,
                    nav_change_pct=attribution_initial.nav_change_pct,
                    by_factor=attribution_initial.by_factor,
                    by_sector=attribution_initial.by_sector,
                    by_regime=attribution_initial.by_regime,
                    by_cost=attribution_initial.by_cost,
                    alpha_vs_benchmark=attribution_initial.alpha_vs_benchmark,
                    unexplained_residual=residual,
                )

                # ── Persist row (open conn once, lambda factory for same-conn DI) ──
                # iter 132 fix F7 (phantom `app.core.db.get_pg_connection`) — `app/core/db.py`
                # doesn't exist (0 grep hits, 0 callers other than this line); canonical sync
                # conn factory = `app.services.db.get_sync_conn` (sibling meta_monitor +
                # daily_pipeline).
                #
                # iter 132 fix F8 P0 (PR #484 reviewer cycle 1) — single-conn lifecycle
                # eliminates double-open leak. Old pattern passed `get_pg_connection` as
                # factory → persist_attribution opens conn #1 + INSERT (no commit, per Engine
                # contract); caller then opens *separate* conn #2 + commits conn #2 → conn #1
                # garbage-collected with uncommitted INSERT (Postgres autorollback) → since
                # iter 65 MVP 4.2 first run (24+ days), every persist attempt silently rolled
                # back. Fix: open conn once + `lambda: conn` factory always returns the same
                # already-open conn + commit same conn after persist returns + close in finally.
                # Preserves persist_attribution's conn_factory DI contract + honors 铁律 32
                # transaction-owner-is-caller semantics.
                row_id = persist_attribution(lambda: conn, attribution_final)
                conn.commit()  # 铁律 32 — caller owns commit, same conn as persist INSERT

                # ── Fire residual alert (fail-soft 沿用 fire_residual_alert tier 1+2) ──
                alert_fired = fire_residual_alert(attribution_final, threshold_bps=20.0)
            finally:
                conn.close()

            result = {
                "trade_date": str(trade_date),
                "strategy_id": strategy_id,
                "row_id": row_id,
                "residual_bps": residual * 10000.0,
                "alert_fired": alert_fired,
                "factor_contributors": len(by_factor),
                "sector_contributors": len(by_sector),
                "cost_contributors": sum(1 for value in by_cost.values() if abs(value) > 1e-12),
            }
            logger.info("[Attribution] Daily compute OK: %s", result)
            _audit_summary = result
            _audit_status = "success"
            return result

        except Exception as e:  # noqa: BLE001 — task body top-level fail-soft (铁律 33)
            logger.error(
                "[Attribution] daily_attribution_compute_task failed: %s", e, exc_info=True
            )
            # iter 132 PR #484 reviewer P1: explicit _audit_status set for clarity (matches
            # factor_lifecycle_task canonical iter 103 sibling pattern). Default at L142 also
            # covers, but explicit set + comment makes the audit-envelope contract obvious.
            _audit_status = "error"
            error_result = {"error": str(e), "trade_date": trade_date_str or "today"}
            _audit_summary = {
                **error_result,  # adds trade_date + str(e) error first
                "status": "error",
                "error": f"{type(e).__name__}: {e}",  # OVERRIDE with typed error for audit context
            }
            return error_result
    finally:
        _write_scheduler_log_safe(
            "daily_attribution_compute",
            _audit_start,
            _audit_status,
            _audit_summary,
        )
