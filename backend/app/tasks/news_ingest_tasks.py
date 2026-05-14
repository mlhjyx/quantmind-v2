"""News ingestion Celery tasks — sub-PR 8b-cadence-B Beat schedule wire (5-07 sediment).

沿用 ADR-043 §Decision sustained:
- #1 Celery Beat mechanism (反 Windows Task Scheduler) 沿用 4 现存 Beat entries 体例
- #2 cron `crontab(hour="3,7,11,15,19,23", minute=0)` (4-hour offset 3h, 6/day)
- #3 RSSHub standalone caller route_path semantic (沿用 sub-PR 8b-rsshub PR #254)

Task signatures (Celery 反 keyword args 沿用 app.tasks.daily_pipeline 体例):
- news_ingest_5_sources(): 5 源 fetch + classify + persist (Zhipu/Tavily/Anspire/GDELT/Marketaux)
- news_ingest_rsshub(): RSSHub route_path 独立 caller (jin10/news 1/4 working sustained PR #254)

Beat dispatch:
- crontab(hour="3,7,11,15,19,23", minute=0) Asia/Shanghai (ADR-043 §Decision #2)
- 软 conflict Fri 19:00 factor-lifecycle-weekly tolerated (Beat sequential dispatch
  + Worker --pool=solo --concurrency=1 Windows queue 等待真**反 hard collision**)
- 反 hard collision PT chain 16:25/16:30/09:31 (Task Scheduler) +
  17:40 daily-quality-report + 22:00 Sun gp-weekly + 30s outbox (Beat)

关联铁律:
- 17 (DataPipeline 入库走 NewsIngestionService orchestrator, 沿用 sub-PR 7c)
- 32 (Service 不 commit — task 真**事务边界**, conn.commit() task 层管)
- 33 (fail-loud — task fail 沿用 logger.exception + raise, Beat scheduler retry policy 沿用 expires)
- 41 (timezone — Asia/Shanghai sustained celery_app.py:42-43 + UTC decision_id 体例)
- 44 (X9 — Beat schedule restart 必显式, 沿用 LL-097 sediment)

关联文档:
- docs/adr/ADR-043 §Decision (Beat schedule + cadence + RSSHub 路由层契约)
- backend/app/api/news.py:225-360 (POST /ingest + /ingest_rsshub manual endpoint 体例)
- backend/app/services/news/news_ingestion_service.py (sub-PR 7c orchestrator)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.tasks.celery_app import celery_app
from backend.qm_platform.risk.metrics.meta_alert_interface import NEWS_RUN_STATS_REDIS_KEY

logger = logging.getLogger("celery.news_ingest_tasks")

DEFAULT_5_SOURCE_QUERY = "A股 财经"
DEFAULT_5_SOURCE_LIMIT_PER_SOURCE = 2
DEFAULT_RSSHUB_ROUTE_PATH = "/jin10/news"
DEFAULT_RSSHUB_LIMIT = 10

# HC-1b3: News 元告警 instrumentation (V3 §13.3) — persist DataPipeline per-run
# aggregate to Redis so the out-of-process meta_monitor News collector can read it.
# Redis key = NEWS_RUN_STATS_REDIS_KEY (SSOT in meta_alert_interface — single
# definition shared with the meta_monitor reader, reviewer MEDIUM).
# TTL 8h > 4h news cadence → healthy pipeline always leaves a fresh-ish key;
# expired key → _collect_news treats as "no recent run stats" (not triggered).
_NEWS_RUN_STATS_TTL_S = 28800  # 8h


def _persist_news_run_stats(pipeline: Any) -> None:
    """HC-1b3: persist DataPipeline.get_last_run_stats() → Redis (meta_monitor News collector).

    Fail-soft — 元告警 instrumentation 是旁路, Redis 故障不阻塞 news ingestion 主路径
    (news 入库已 commit). 沿用 IntradayAlertDedup Redis 体例 (redis.from_url).
    """
    import redis as redis_lib  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    stats = pipeline.get_last_run_stats()
    if stats is None:
        return
    try:
        client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
        client.setex(NEWS_RUN_STATS_REDIS_KEY, _NEWS_RUN_STATS_TTL_S, json.dumps(stats))
        logger.info("[news-ingest] persisted run-stats to Redis: %s", stats)
    except Exception as e:  # noqa: BLE001 — fail-soft, 元告警 instrumentation 旁路
        logger.warning("[news-ingest] persist run-stats to Redis failed (fail-soft): %s", e)


@celery_app.task(
    name="app.tasks.news_ingest_tasks.news_ingest_5_sources",
    soft_time_limit=300,  # 5min — generous for 5 external API calls × limit_per_source=2
    time_limit=600,  # 10min hard kill (反 solo worker stall blocking outbox-publisher 30s)
)
def news_ingest_5_sources(
    *,
    query: str | None = None,
    limit_per_source: int | None = None,
) -> dict:
    """5-source News ingestion Celery task (Beat-dispatched, ADR-043 §Decision #2 cron).

    Wraps backend/app/api/news.py:_build_pipeline_5_sources() + NewsIngestionService.ingest()
    pattern (反 HTTP roundtrip, direct Python call sustained Celery task fast path).

    Args:
        query: search keyword (default DEFAULT_5_SOURCE_QUERY 沿用 IngestRequest 体例).
        limit_per_source: per-source max items (default 2 沿用 cost throttle ~$0.02-0.05/run).

    Returns:
        dict with stats fields (status/fetched/ingested/classified/classify_failed/query/limit_per_source).

    Raises:
        Exception: fetcher init / pipeline run / DB insert 真 raise (fail-loud 铁律 33,
            Celery retry policy 沿用 expires=3600 in beat_schedule.py).
    """
    from app.api.news import _build_pipeline_5_sources
    from app.services.db import get_sync_conn
    from app.services.news import NewsIngestionService, get_news_classifier

    # M1 reviewer adopt — proof-of-life audit 沿用 daily_pipeline.py:42-53 motivation
    # (Session 44 risk task dead-Beat silent miss reverse case sustained, audit chunk B P3 体例).
    from app.tasks.daily_pipeline import _write_scheduler_log_safe

    start_time = datetime.now(UTC)
    q = query or DEFAULT_5_SOURCE_QUERY
    lps = limit_per_source if limit_per_source is not None else DEFAULT_5_SOURCE_LIMIT_PER_SOURCE

    logger.info("news_ingest_5_sources start query=%r limit_per_source=%d", q, lps)

    pipeline = _build_pipeline_5_sources()
    classifier = get_news_classifier(conn_factory=get_sync_conn)
    service = NewsIngestionService(pipeline=pipeline, classifier=classifier)

    conn = get_sync_conn()
    status = "error"  # default 反 silent success miss, success 真 try block 内 set
    result_for_audit: dict | None = None
    try:
        stats = service.ingest(
            query=q,
            conn=conn,
            limit_per_source=lps,
            decision_id_prefix=f"news-beat-5src-{start_time.strftime('%Y%m%dT%H%M%SZ')}",
        )
        conn.commit()
        # HC-1b3: persist per-run aggregate → Redis for meta_monitor News 元告警
        # collector (V3 §13.3). fail-soft 旁路, 不阻塞已 commit 的 news 入库.
        _persist_news_run_stats(pipeline)
        result = {
            "status": "success",
            "fetched": stats.fetched,
            "ingested": stats.ingested,
            "classified": stats.classified,
            "classify_failed": stats.classify_failed,
            "query": q,
            "limit_per_source": lps,
        }
        status = "success"
        result_for_audit = result
        logger.info("news_ingest_5_sources done: %s", result)
        return result
    except Exception as exc:
        conn.rollback()
        result_for_audit = {"error": f"{type(exc).__name__}: {exc}"}
        logger.exception("news_ingest_5_sources failed query=%r: %s", q, exc)
        raise
    finally:
        # proof-of-life audit (silent_ok on failure 沿用 daily_pipeline.py 体例)
        _write_scheduler_log_safe(
            task_name="news_ingest_5_sources",
            start_time=start_time,
            status=status,
            result_json=result_for_audit,
        )
        conn.close()


@celery_app.task(
    name="app.tasks.news_ingest_tasks.news_ingest_rsshub",
    soft_time_limit=300,  # 5min — RSSHub Self-hosted localhost normally fast, defensive bound
    time_limit=600,  # 10min hard kill (反 solo worker stall blocking outbox-publisher 30s)
)
def news_ingest_rsshub(
    *,
    route_path: str | None = None,
    limit: int | None = None,
) -> dict:
    """RSSHub route_path News ingestion Celery task (Beat-dispatched, ADR-043 §Decision #2 cron).

    Wraps backend/app/api/news.py:_build_pipeline_rsshub_only() + NewsIngestionService.ingest().
    RSSHub 真 route-driven 体例 (反 search keyword semantic 沿用 sub-PR 1+2+3+5).

    Note (RSSHub routes baseline, sustained chunk C-RSSHub Path A closure + chunk C-ADR PR #267):
        Default route_path = '/jin10/news' (1/4 baseline). 4 working routes total:
        /jin10/news + /jin10/0 + /jin10/1 + /eastmoney/search/A股 (HTTP 200 verified).
        7 routes 503 sediment 待 sub-PR 9 investigation (RSSHub upstream config / cache /
        authentication 体例, sustained LL-114 + LL-115).

    Args:
        route_path: RSSHub route endpoint path (default DEFAULT_RSSHUB_ROUTE_PATH).
        limit: per-route fetch limit (default 10 沿用 sub-PR 6 体例).

    Returns:
        dict with stats fields (status/fetched/ingested/classified/classify_failed/route_path/limit).
    """
    from app.api.news import _build_pipeline_rsshub_only
    from app.services.db import get_sync_conn
    from app.services.news import NewsIngestionService, get_news_classifier

    # M1 reviewer adopt — proof-of-life audit 沿用 daily_pipeline.py:42-53 motivation.
    from app.tasks.daily_pipeline import _write_scheduler_log_safe

    start_time = datetime.now(UTC)
    rp = route_path or DEFAULT_RSSHUB_ROUTE_PATH
    lim = limit if limit is not None else DEFAULT_RSSHUB_LIMIT

    logger.info("news_ingest_rsshub start route_path=%r limit=%d", rp, lim)

    pipeline = _build_pipeline_rsshub_only()
    classifier = get_news_classifier(conn_factory=get_sync_conn)
    service = NewsIngestionService(pipeline=pipeline, classifier=classifier)

    conn = get_sync_conn()
    status = "error"  # default 反 silent success miss
    result_for_audit: dict | None = None
    try:
        stats = service.ingest(
            query=rp,
            conn=conn,
            limit_per_source=lim,
            decision_id_prefix=f"news-beat-rsshub-{start_time.strftime('%Y%m%dT%H%M%SZ')}",
        )
        conn.commit()
        result = {
            "status": "success",
            "fetched": stats.fetched,
            "ingested": stats.ingested,
            "classified": stats.classified,
            "classify_failed": stats.classify_failed,
            "route_path": rp,
            "limit": lim,
        }
        status = "success"
        result_for_audit = result
        logger.info("news_ingest_rsshub done: %s", result)
        return result
    except Exception as exc:
        conn.rollback()
        result_for_audit = {"error": f"{type(exc).__name__}: {exc}"}
        logger.exception("news_ingest_rsshub failed route_path=%r: %s", rp, exc)
        raise
    finally:
        # proof-of-life audit (silent_ok on failure 沿用 daily_pipeline.py 体例)
        _write_scheduler_log_safe(
            task_name="news_ingest_rsshub",
            start_time=start_time,
            status=status,
            result_json=result_for_audit,
        )
        conn.close()
