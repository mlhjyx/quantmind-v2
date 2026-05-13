"""V3 §13.2 daily metrics extract — Celery task (S10 operational wire).

Closes the last code prereq for S10 5d operational kickoff: wraps
`scripts/v3_paper_mode_5d_extract_metrics.py` CLI logic into a Celery task
that fires daily at 16:30 Asia/Shanghai (post-market-close, after PT trade_log
+ risk_event_log + execution_plans have settled for the day).

Beat schedule: `risk-metrics-daily-extract-16-30` (crontab 30 16 * * 1-5).

Flow per fire:
  1. compute target_date = (now Asia/Shanghai).date() (i.e. today's metrics,
     fired post-close so day is complete)
  2. get_sync_conn() → aggregate_daily_metrics → upsert_daily_metrics → commit
  3. log summary for capture by Celery worker log

Cohort with l4_sweep_tasks (PR #308) and dynamic_threshold_tasks (PR #306)
— same task-body shape (conn = None pre-assign / commit / rollback on except /
close in finally).

铁律 31: not directly invoked (task layer, not engine).
铁律 32: caller (this task) owns conn.commit; PURE module 0 commit.
铁律 33: SQL errors propagate to Celery retry. Per-query rollback in
  daily_aggregator._run_query_safe is per-query error recovery, NOT
  transaction boundary write — module docstring clarifies.
铁律 41: Asia/Shanghai timezone for target_date computation (16:30 post-close).
铁律 44 X9: post-merge ops checklist `Servy restart QuantMind-CeleryBeat AND
  QuantMind-Celery` (sustained pattern from S7 dynamic threshold + S8 8c sweep).

关联 ADR: ADR-062 §6 (CLI wrappers as scripted seams) — this task is the
  Celery-side counterpart of the extract_metrics CLI.
关联 LL: LL-156 §3 (code-vs-operational split — this PR closes the
  operational-side code gap).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.services.db import get_sync_conn
from app.tasks.celery_app import celery_app
from backend.qm_platform.risk.metrics import (
    aggregate_daily_metrics,
    upsert_daily_metrics,
)

logger = logging.getLogger("celery.daily_metrics_extract")


def _today_shanghai() -> datetime:
    """Returns current Asia/Shanghai datetime (timezone-aware).

    Beat fires at 16:30 Asia/Shanghai, so this is post-close and the day's
    risk events / execution plans / LLM cost rows are complete.
    """
    return datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai"))


@celery_app.task(
    name="app.tasks.daily_metrics_extract_tasks.extract_daily_metrics",
    soft_time_limit=60,  # 60s soft — typical aggregation <2s for 9 specs
    time_limit=120,  # 120s hard kill (反 stuck task blocking Beat next fire)
)
def extract_daily_metrics() -> dict[str, Any]:
    """Aggregate today's risk_metrics_daily row + upsert.

    Beat schedule: `risk-metrics-daily-extract-16-30` (crontab `30 16 * * 1-5`
    Asia/Shanghai; post-market-close + post-trade_log-settled).

    Returns:
        {
            "ok": bool,
            "date": str (Asia/Shanghai date ISO),
            "rowcount": int (1 on insert/update),
            "alerts_p0": int,
            "staged_plans": int,
            "llm_cost": float,
        }

    Raises:
        psycopg2.Error: any DB error propagates to Celery retry.
    """
    # Reviewer-style pre-assign conn=None (sustained 8c-partial pattern):
    # get_sync_conn() failure would otherwise raise UnboundLocalError in finally.
    conn = None
    try:
        target_date = _today_shanghai().date()
        conn = get_sync_conn()
        result = aggregate_daily_metrics(conn, target_date)
        rowcount = upsert_daily_metrics(conn, result)
        conn.commit()
        logger.info(
            "[daily-metrics-extract] date=%s rowcount=%d alerts_p0=%d staged=%d cost=%.4f",
            target_date,
            rowcount,
            result.alerts_p0_count,
            result.staged_plans_count,
            result.llm_cost_total,
        )
        return {
            "ok": True,
            "date": target_date.isoformat(),
            "rowcount": rowcount,
            "alerts_p0": result.alerts_p0_count,
            "staged_plans": result.staged_plans_count,
            "llm_cost": float(result.llm_cost_total),
        }
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


__all__ = ["extract_daily_metrics"]
