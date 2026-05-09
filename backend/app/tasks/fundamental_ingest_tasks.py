"""Fundamental context daily ingestion Celery tasks — sub-PR 14 sediment per ADR-053.

沿用 ADR-053 §1 Decision sustained:
- Decision 4 daily Beat cron `0 16 * * *` Asia/Shanghai (every day 16:00 post-market close, V3 §3.3
  line 426 cite "更新 cadence: 每日 16:00 (盘后入库)")
- Decision 1 1 source AKShare valuation 维 baseline (sub-PR 14 minimal, 反 ensemble premature)
- Decision 5 per-source fail-soft sustained (反 reraise after FundamentalFetchError logged)

Task signature (沿用 sub-PR 11b announcement_ingest_tasks 体例):
- fundamental_context_ingest(*, symbol_id): 单 symbol valuation 维 ingest

Beat dispatch (per ADR-053 §1 Decision 4 sediment):
- crontab(hour=16, minute=0) Asia/Shanghai (daily 16:00 post-market)
- 反 hard collision PT chain 16:25/16:30 + announcement-ingest 16:15 (15min buffer)
- weekend 真生产 0 fresh data (AKShare returns previous trade date, fail-soft per LL-141 体例)

关联铁律:
- 17 (DataPipeline 入库走 FundamentalContextService orchestrator, 沿用 sub-PR 11b)
- 32 (Service 不 commit — task 真**事务边界**, conn.commit() task 层管)
- 33 (fail-loud — task fail 沿用 logger.exception + raise, Celery retry policy)
- 41 (timezone — Asia/Shanghai sustained celery_app.py + UTC decision_id 体例)
- 44 (X9 — Beat schedule restart 必显式, 沿用 LL-097 + LL-141 4-step sediment)

关联文档:
- docs/adr/ADR-053 (V3 §S4 (minimal) architecture sediment)
- backend/app/services/fundamental_context_service.py (sub-PR 14 orchestrator)
- backend/qm_platform/data/fundamental/akshare_valuation.py (sub-PR 14 fetcher)
- backend/migrations/2026_05_10_fundamental_context_daily.sql (sub-PR 14 DDL, post-PR apply)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.fundamental_ingest_tasks")

DEFAULT_SYMBOL_ID = (
    "600519"  # 贵州茅台 baseline (sub-PR 14 sustained, real production caller override)
)


@celery_app.task(
    name="app.tasks.fundamental_ingest_tasks.fundamental_context_ingest",
    soft_time_limit=120,  # 2min — AKShare stock_value_em normally fast
    time_limit=300,  # 5min hard kill
)
def fundamental_context_ingest(
    *,
    symbol_id: str | None = None,
) -> dict:
    """Single-symbol fundamental_context daily ingestion Celery task (Beat-dispatched per ADR-053).

    Wraps AkshareValuationFetcher + FundamentalContextService.ingest() pattern (反 HTTP roundtrip,
    direct Python call sustained Celery task fast path).

    Args:
        symbol_id: stock code (default DEFAULT_SYMBOL_ID baseline). Real production caller should
            iterate portfolio symbols (sub-PR 15+ candidate — multi-symbol Beat dispatch).

    Returns:
        dict with stats fields (status/symbol_id/date/valuation_filled/fetch_latency_ms).

    Raises:
        Exception: fetcher fail / DB UPSERT 真 raise (fail-loud 铁律 33).
    """
    from app.services.db import get_sync_conn
    from app.services.fundamental_context_service import FundamentalContextService

    # M1 reviewer adopt — proof-of-life audit 沿用 sub-PR 11b体例 + LL-141 1:1 simulation enforce
    from app.tasks.daily_pipeline import _write_scheduler_log_safe
    from backend.qm_platform.data.fundamental import AkshareValuationFetcher

    start_time = datetime.now(UTC)
    sid = symbol_id or DEFAULT_SYMBOL_ID

    logger.info("fundamental_context_ingest start symbol_id=%s", sid)

    # sub-PR 14 (minimal) ADR-053 §1 Decision 1: AKShare 1 source baseline
    fetcher = AkshareValuationFetcher()
    service = FundamentalContextService(fetcher=fetcher)

    conn = get_sync_conn()
    status = "error"  # default 反 silent success miss
    result_for_audit: dict | None = None
    try:
        stats = service.ingest(symbol_id=sid, conn=conn)
        conn.commit()
        result = {
            "status": "success",
            "symbol_id": stats.symbol_id,
            "date": stats.date.isoformat(),
            "valuation_filled": stats.valuation_filled,
            "fetch_latency_ms": stats.fetch_latency_ms,
        }
        status = "success"
        result_for_audit = result
        logger.info("fundamental_context_ingest done: %s", result)
        return result
    except Exception as exc:
        conn.rollback()
        result_for_audit = {"error": f"{type(exc).__name__}: {exc}"}
        logger.exception("fundamental_context_ingest failed symbol_id=%s: %s", sid, exc)
        raise
    finally:
        # proof-of-life audit (silent_ok on failure 沿用 daily_pipeline.py 体例)
        _write_scheduler_log_safe(
            task_name="fundamental_context_ingest",
            start_time=start_time,
            status=status,
            result_json=result_for_audit,
        )
        conn.close()
