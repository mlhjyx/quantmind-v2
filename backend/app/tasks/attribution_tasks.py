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
from datetime import date, datetime
from zoneinfo import ZoneInfo

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


@celery_app.task(bind=True, name="app.tasks.attribution_tasks.daily_attribution_compute_task")
def daily_attribution_compute_task(self, trade_date_str: str | None = None) -> dict:
    """Daily attribution Beat task — compute + persist + alert (MVP 4.2 iter 65).

    Beat 入口 `daily-attribution-compute` 16:30 Mon-Fri Asia/Shanghai.
    Trading-day guard 沿用 daily_pipeline.py 体例 (Beat crontab day_of_week=1-5 已过滤
    周末, 节假日 task 内部判断后续 wiring).

    Args:
        trade_date_str: optional YYYY-MM-DD override (manual replay); default = today SH.

    Returns:
        dict — {trade_date, strategy_id, row_id, residual_bps, alert_fired}.
    """
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
        strategy_id = "paper-strategy-default"  # TODO: resolve from settings.PAPER_STRATEGY_ID
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

        # ── Persist row (DI conn_factory: lazy import to keep Platform isolation) ──
        from app.core.db import get_pg_connection

        row_id = persist_attribution(get_pg_connection, attribution_final)

        # Commit (铁律 32 — Celery task = transaction owner)
        conn = get_pg_connection()
        conn.commit()

        # ── Fire residual alert (fail-soft 沿用 fire_residual_alert tier 1+2) ──
        alert_fired = fire_residual_alert(attribution_final, threshold_bps=20.0)

        result = {
            "trade_date": str(trade_date),
            "strategy_id": strategy_id,
            "row_id": row_id,
            "residual_bps": residual * 10000.0,
            "alert_fired": alert_fired,
        }
        logger.info("[Attribution] Daily compute OK: %s", result)
        return result

    except Exception as e:  # noqa: BLE001 — task body top-level fail-soft (铁律 33)
        logger.error("[Attribution] daily_attribution_compute_task failed: %s", e, exc_info=True)
        return {"error": str(e), "trade_date": trade_date_str or "today"}
