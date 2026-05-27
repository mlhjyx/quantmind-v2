"""MVP 4.2 sub-iter 7 (iter 65) — Daily attribution Beat task wrapper.

Wraps qm_platform.eval.attribution compute_* + persist_attribution + fire_residual_alert
behind a Celery task `daily_attribution_compute_task`. Scheduled by Beat entry
`daily-attribution-compute` (16:30 Mon-Fri Asia/Shanghai).

Initial scope (iter 65 entry — minimal viable):
  - Read latest NAV change from existing data sources (paper trading: PT NAV table)
  - Compute attribution snapshot (TBD: factor_returns / sector_returns / cost
    aggregation 待真 wiring in follow-up iter — initial impl persists nav_change_pct
    only; by_* dicts default empty; residual = nav_change - alpha_vs_benchmark)
  - Persist row via persist_attribution
  - fire_residual_alert if |residual| > 20 bps

Follow-up wiring (out of iter 65 scope, leave TODO):
  - Real factor_returns from factor_ic_history latest IC
  - Real sector_returns from SW1 industry returns
  - Real trade_log cost aggregation
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
from zoneinfo import ZoneInfo

from app.config import settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

SH_TZ = ZoneInfo("Asia/Shanghai")


def _get_sh_trade_date() -> date:
    """Asia/Shanghai 当前日期 (Beat 触发时刻, 铁律 41)."""
    return datetime.now(SH_TZ).date()


def _fetch_paper_nav_change() -> float:
    """Fetch latest PT NAV daily change (decimal fraction).

    Initial stub: reads from positions snapshot or signal task output.
    Follow-up: pull from authoritative NAV history table.

    Returns:
        float — decimal fraction (0.012 = 1.2%); 0.0 if unavailable
        (silent_ok: missing NAV → 0 residual no-op, Beat task does not raise).
    """
    # TODO(MVP 4.2 follow-up): real NAV pull from existing source.
    # For initial Beat activation, return 0.0 — persists row with all zeros,
    # validates DB write path + Beat schedule wiring without false alert.
    return 0.0


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
                compute_unexplained_residual,
                fire_residual_alert,
                persist_attribution,
            )

            # ── Parse trade_date ──
            if trade_date_str:
                trade_date = date.fromisoformat(trade_date_str)
            else:
                trade_date = _get_sh_trade_date()

            # ── Fetch inputs (iter 65 stub; full wiring in follow-up) ──
            strategy_id = settings.PAPER_STRATEGY_ID
            nav_change_pct = _fetch_paper_nav_change()

            # ── Build attribution (initial: empty dicts, real wiring next iter) ──
            attribution_initial = DailyAttribution(
                trade_date=trade_date,
                strategy_id=strategy_id,
                execution_mode="paper",
                nav_change_pct=nav_change_pct,
                by_factor={},
                by_sector={},
                by_regime=None,
                by_cost={},
                alpha_vs_benchmark=0.0,
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
            from app.services.db import get_sync_conn  # noqa: PLC0415

            conn = get_sync_conn()
            try:
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
