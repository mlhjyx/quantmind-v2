"""Announcement ingestion Celery tasks — sub-PR 11b sediment per ADR-049 §1 Decision 4 Beat cadence.

沿用 ADR-049 §Decision sustained:
- Decision 4 trading-hours-aligned cron `crontab(hour="9,11,13,15,17", minute=15)` Asia/Shanghai
  (5/day during 9:00-17:00 disclosure window, 反 23:00/03:00 cron waste, 反 PT collision minute=15 buffer)
- Decision 3 RSSHub route reuse (反 separate fetcher classes, sustained sub-PR 6 RsshubNewsFetcher precedent)
- Decision 5 per-source fail-soft sustained DataPipeline 体例 sub-PR 10 ADR-048 precedent

Task signature (沿用 sub-PR 8b-cadence-B news_ingest_tasks 体例):
- announcement_ingest(*, symbol_id, source, limit): 单 symbol 单 source ingest

Beat dispatch (per ADR-050 候选 sub-PR 11b sediment, sustained ADR-049 §1 Decision 4):
- crontab(hour="9,11,13,15,17", minute=15) Asia/Shanghai (trading-hours window)
- 反 hard collision PT chain 16:25/16:30/09:31 + 17:40 daily-quality-report (minute=15 buffer)
- 反 hard collision news_ingest cron `3,7,11,15,19,23 minute=0` (minute=15 vs minute=0 differ)

关联铁律:
- 17 (DataPipeline 入库走 AnnouncementProcessor orchestrator, 沿用 sub-PR 11b)
- 32 (Service 不 commit — task 真**事务边界**, conn.commit() task 层管)
- 33 (fail-loud — task fail 沿用 logger.exception + raise, Beat scheduler retry policy)
- 41 (timezone — Asia/Shanghai sustained celery_app.py + UTC decision_id 体例)
- 44 (X9 — Beat schedule restart 必显式, 沿用 LL-097 sediment, post-merge ops checklist `Servy restart QuantMind-CeleryBeat`)

关联文档:
- docs/adr/ADR-049 §1 Decision 3 + Decision 4 + Decision 5 (V3 §S2.5 architecture sediment)
- backend/app/api/news.py (sub-PR 11b 待 manual endpoint POST /ingest_announcement extension)
- backend/app/services/news/announcement_processor.py (sub-PR 11b orchestrator)
- backend/qm_platform/news/announcement_routes.py (sub-PR 11b route config)
- backend/migrations/2026_05_09_announcement_raw.sql (sub-PR 11a DDL, post-PR apply 沿用)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.announcement_ingest_tasks")

DEFAULT_SYMBOL_ID = (
    "600519"  # 贵州茅台 baseline (sub-PR 11b sustained, real production user override)
)
DEFAULT_SOURCE = "cninfo"  # 1/3 working baseline per ADR-049 §1 Decision 3
DEFAULT_LIMIT = 10


@celery_app.task(
    name="app.tasks.announcement_ingest_tasks.announcement_ingest",
    soft_time_limit=300,  # 5min — RSSHub Self-hosted localhost normally fast
    time_limit=600,  # 10min hard kill
)
def announcement_ingest(
    *,
    symbol_id: str | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> dict:
    """Single-symbol announcement ingestion Celery task (Beat-dispatched per ADR-049 §1 Decision 4).

    Wraps backend/app/api/news.py:_build_pipeline_rsshub_only() + AnnouncementProcessor.ingest()
    pattern (反 HTTP roundtrip, direct Python call sustained Celery task fast path).

    Args:
        symbol_id: stock code (default DEFAULT_SYMBOL_ID baseline). Real production caller
            should iterate portfolio symbols (sub-PR 12+ candidate — multi-symbol Beat dispatch
            architecture decision deferred per ADR-049 §2 Finding #3 sustained pattern).
        source: announcement source enum (default DEFAULT_SOURCE 'cninfo' 1/3 working baseline).
            sse/szse 真 reserved 待 S5 paper-mode 5d period verify (ADR-049 §2 Finding #1).
        limit: per-route fetch limit (default 10 沿用 sub-PR 6 RSSHub precedent).

    Returns:
        dict with stats fields (status/fetched/ingested/skipped_earnings/skipped_unknown/symbol_id/source/limit).

    Raises:
        Exception: fetcher init / pipeline run / DB insert 真 raise (fail-loud 铁律 33,
            Celery retry policy 沿用 expires=3600 in beat_schedule.py).
    """
    from app.api.news import _build_pipeline_announcement_akshare
    from app.services.db import get_sync_conn
    from app.services.news import AnnouncementProcessor

    # M1 reviewer adopt — proof-of-life audit 沿用 daily_pipeline.py:42-53 motivation
    from app.tasks.daily_pipeline import _write_scheduler_log_safe

    start_time = datetime.now(UTC)
    sid = symbol_id or DEFAULT_SYMBOL_ID
    src = source or DEFAULT_SOURCE
    lim = limit if limit is not None else DEFAULT_LIMIT

    logger.info(
        "announcement_ingest start symbol_id=%s source=%s limit=%d",
        sid,
        src,
        lim,
    )

    # sub-PR 13 ADR-052 reverse: AKShare direct API replaces RSSHub route reuse (LL-142 sediment)
    pipeline = _build_pipeline_announcement_akshare()
    processor = AnnouncementProcessor(pipeline=pipeline)

    conn = get_sync_conn()
    status = "error"  # default 反 silent success miss
    result_for_audit: dict | None = None
    try:
        stats = processor.ingest(
            symbol_id=sid,
            source=src,
            conn=conn,
            limit=lim,
        )
        conn.commit()
        result = {
            "status": "success",
            "fetched": stats.fetched,
            "ingested": stats.ingested,
            "skipped_earnings": stats.skipped_earnings,
            "skipped_unknown": stats.skipped_unknown,
            "symbol_id": sid,
            "source": src,
            "limit": lim,
        }
        status = "success"
        result_for_audit = result
        logger.info("announcement_ingest done: %s", result)
        return result
    except Exception as exc:
        conn.rollback()
        result_for_audit = {"error": f"{type(exc).__name__}: {exc}"}
        logger.exception(
            "announcement_ingest failed symbol_id=%s source=%s: %s",
            sid,
            src,
            exc,
        )
        raise
    finally:
        # proof-of-life audit (silent_ok on failure 沿用 daily_pipeline.py 体例)
        _write_scheduler_log_safe(
            task_name="announcement_ingest",
            start_time=start_time,
            status=status,
            result_json=result_for_audit,
        )
        conn.close()
