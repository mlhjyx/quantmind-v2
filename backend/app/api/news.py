"""News ingestion API — Sprint 2 sub-PR 8a caller wire (5-07 sediment).

POST /api/news/ingest manual trigger 路径 — 真生产 caller 真**唯一 sanctioned 入口**
(沿用 ADR-031 §6 sub-PR 7c NewsIngestionService orchestrator + ADR-032 line 36
caller bootstrap factory 体例 + sub-PR 1-6 plugin sustained).

scope (sub-PR 8a, 反 sub-PR 8b Beat schedule wire):
- POST /api/news/ingest body={query, limit_per_source} → 同步 5 源 fetch + classify + persist
- GET /api/news/stats → 最近 24h DB row count (news_raw + news_classified) + last 5 ingestion samples
- 5 News 源默认 (Zhipu/Tavily/Anspire/GDELT/Marketaux) — RSSHub 走独立 caller pattern
  (V3§3.1 sub-PR 6 docstring "RSSHub 走独立 pipeline (route path 真预约)" sustained,
  sub-PR 8b cadence 决议时 wire)
- 0 broker call / 0 真发单 (LIVE_TRADING_DISABLED + EXECUTION_MODE=paper sustained)

caller 模式 (production manual trigger):
    curl -X POST http://localhost:8000/api/news/ingest \
        -H "Content-Type: application/json" \
        -d '{"query": "贵州茅台", "limit_per_source": 2}'

关联铁律:
- 17 (DataPipeline 入库走 NewsIngestionService orchestrator, 沿用 sub-PR 7c)
- 22 (文档跟随代码 — 同 PR ADR-DRAFT.md create + STATUS_REPORT memory sediment)
- 25 (改什么读什么 — Phase 0/1 全 6 doc + 全 fetcher 体例 fresh verify)
- 31 (Engine 层纯计算 — endpoint 真 orchestrator router, 0 业务逻辑)
- 32 (Service 不 commit — caller 真**事务边界**, conn.commit() endpoint 层管)
- 33 (fail-loud — fetcher fail-soft 沿用 NewsIngestionService contract;
       endpoint level HTTP 500 raise 走 FastAPI exception handler)
- 41 (timezone — NewsItem.timestamp tz-aware sustained sub-PR 1-6)
- 45 (4 doc fresh read SOP enforcement, IRONLAWS PR-B sediment)

关联文档:
- V3 line 1222 (NewsIngestionService backend/app/services/news/ 真预约 path)
- V3§3.1 line 312-356 (News 多源接入 + news_raw schema)
- ADR-031 §6 (V4 路由层 sustained DeepSeek + Ollama)
- ADR-032 §Decision (caller bootstrap factory + conn_factory DI 真预约)
- ADR-035 §2 (News ingestion 层独立 client, 反 V4 路由层)
- backend/app/services/news/news_ingestion_service.py (sub-PR 7c orchestrator)
- backend/app/services/news/bootstrap.py (sub-PR 7b.3 v2 get_news_classifier)
- backend/qm_platform/news/pipeline.py (sub-PR 7a DataPipeline 6 源并行)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from backend.qm_platform.news.pipeline import DataPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


class IngestRequest(BaseModel):
    """POST /api/news/ingest body schema.

    Args:
        query: 自然语言 search keyword (5 源兼容, ≤ 64 char Anspire 硬限).
            RSSHub 不在 5 源默认 (route path 走独立 caller, sub-PR 8b 真预约).
        limit_per_source: per-source max items (默认 2, sub-PR 8a 节流体例 ~$0.02-0.05/run).
        decision_id_prefix: 可选 LLM call audit prefix (默认 "news-{ts}", classifier 真消费).
    """

    query: str = Field(..., min_length=1, max_length=64)
    limit_per_source: int = Field(default=2, ge=1, le=10)
    decision_id_prefix: str | None = Field(default=None, max_length=64)


class IngestResponse(BaseModel):
    """POST /api/news/ingest response schema (沿用 IngestionStats dataclass)."""

    fetched: int
    ingested: int
    classified: int
    classify_failed: int
    query: str
    limit_per_source: int


class NewsRawSample(BaseModel):
    """GET /api/news/stats — last_5_news_raw row schema."""

    news_id: int
    source: str
    title: str
    timestamp: str | None
    fetched_at: str | None


class NewsClassifiedSample(BaseModel):
    """GET /api/news/stats — last_5_news_classified row schema."""

    news_id: int
    sentiment_score: float | None
    category: str | None
    urgency: str | None
    profile: str | None
    classifier_model: str | None
    classified_at: str | None


class NewsStatsResponse(BaseModel):
    """GET /api/news/stats response schema (P2-2 reviewer adopt)."""

    news_raw_24h_count: int
    news_classified_24h_count: int
    last_5_news_raw: list[NewsRawSample]
    last_5_news_classified: list[NewsClassifiedSample]


class IngestRsshubRequest(BaseModel):
    """POST /api/news/ingest_rsshub body schema (sub-PR 8b-rsshub 5-07 sediment).

    沿用 sub-PR 6 design intent: route_path 真**独立 caller pattern** (反主链路 5-source
    ingest). RSSHub 真**route-driven** (各 source path-specific) 反 search keyword
    semantic 沿用 sub-PR 1+2+3+5 体例.

    Args:
        route_path: RSSHub route 真生产 endpoint path (e.g. "/jin10/news",
            "/eastmoney/news/0", "/caixin/finance"). Slash prefix optional —
            RsshubNewsFetcher.fetch normalize.
        limit: per-route fetch limit (默认 10, max 50 沿用 sub-PR 6 体例).
        decision_id_prefix: 可选 LLM call audit prefix (默认 None, classifier 真消费).
    """

    route_path: str = Field(..., min_length=1, max_length=128)
    limit: int = Field(default=10, ge=1, le=50)
    decision_id_prefix: str | None = Field(default=None, max_length=64)


class IngestRsshubResponse(BaseModel):
    """POST /api/news/ingest_rsshub response schema."""

    fetched: int
    ingested: int
    classified: int
    classify_failed: int
    route_path: str
    limit: int


def _build_pipeline_5_sources() -> DataPipeline:
    """Build DataPipeline with 5 News 源 (Zhipu/Tavily/Anspire/GDELT/Marketaux).

    RSSHub 不含 — route path 走独立 caller pattern (sub-PR 8b 真预约).

    Returns:
        DataPipeline instance, 沿用 sub-PR 7a 6 源并行 + 早返回 + dedup 体例.

    Raises:
        ValueError: 任 1 源 api_key 空时, fetcher constructor **本函数构造时即 raise**
            (反 fetch-time, 沿用铁律 33 fail-loud — sub-PR 1-5 fetcher
            ZhipuNewsFetcher.__init__ etc. 体例 sustained). caller 真**注意**: 任 1
            settings.<X>_API_KEY 空走 endpoint 整体 fail (反 partial source 跑),
            sub-PR 8b 候选 partial-source 模式. P2-1 reviewer 沿用.
    """
    from app.config import settings
    from backend.qm_platform.news import (
        AnspireNewsFetcher,
        DataPipeline,
        GdeltNewsFetcher,
        MarketauxNewsFetcher,
        TavilyNewsFetcher,
        ZhipuNewsFetcher,
    )

    fetchers = [
        ZhipuNewsFetcher(
            api_key=settings.ZHIPU_API_KEY,
            base_url=settings.ZHIPU_BASE_URL,
        ),
        TavilyNewsFetcher(
            api_key=settings.TAVILY_API_KEY,
            base_url=settings.TAVILY_BASE_URL,
        ),
        AnspireNewsFetcher(
            api_key=settings.ANSPIRE_API_KEY,
            base_url=settings.ANSPIRE_BASE_URL,
        ),
        GdeltNewsFetcher(base_url=settings.GDELT_BASE_URL),
        MarketauxNewsFetcher(
            api_key=settings.MARKETAUX_API_KEY,
            base_url=settings.MARKETAUX_BASE_URL,
        ),
    ]
    return DataPipeline(fetchers)


def _build_pipeline_rsshub_only() -> DataPipeline:
    """Build DataPipeline with single RsshubNewsFetcher (sub-PR 8b-rsshub 5-07 sediment).

    沿用 sub-PR 6 design intent: route_path 真**独立 caller pattern** (反主链路
    5-source ingest). 0 API key (Self-hosted localhost:1200 anonymous, V3§3.1 + ADR-033 +
    sub-PR 6 sediment 沿用).

    Returns:
        DataPipeline with single fetcher — caller 真**route_path query** 沿用
        RsshubNewsFetcher.fetch 体例 (反 search keyword sub-PR 1+2+3+5 体例).

    Note (single-fetcher pipeline 沿用 sub-PR 7a contract sustained):
        DataPipeline 真**fetch_all** 沿用 single-fetcher case (反 multi-source dedup).
        sub-PR 8b-rsshub-multi-route 候选: 沿用 _YAML_REFERENCED_ENVS pattern 真**多
        route 体例** (沿用 settings.RSSHUB_ROUTES 真预约 list, sub-PR 8b-cadence 决议).
    """
    from app.config import settings
    from backend.qm_platform.news import DataPipeline, RsshubNewsFetcher

    fetchers = [RsshubNewsFetcher(base_url=settings.RSSHUB_BASE_URL)]
    return DataPipeline(fetchers)


@router.post("/ingest", response_model=IngestResponse)
def ingest_news(req: IngestRequest) -> IngestResponse:
    """Manual trigger 5 源 News ingestion + classify + persist.

    沿用 sub-PR 7c NewsIngestionService orchestrator + sub-PR 7b.3 v2 bootstrap singleton +
    sub-PR 7a DataPipeline 5 源并行 (RSSHub 不含).

    Args:
        req: IngestRequest body.

    Returns:
        IngestResponse with IngestionStats fields + echo query/limit_per_source.

    Raises:
        HTTPException 500: 任 fetcher init / pipeline run / DB insert 真 raise (fail-loud,
            FastAPI 走 default exception handler 返 500 + log error).

    Note (split-transaction LLM audit, P1-3 reviewer adopt):
        本 endpoint 走 2 套 conn 真**独立事务边界**:
        - news_raw + news_classified 真**主 conn** (本 endpoint open + commit/rollback)
        - llm_call_log 真**LLM router 内部 conn** (get_llm_router(conn_factory=...) lazy
          init 时 wire, audit row 走**独立 transaction** 真 fire-and-forget)
        即: ingestion fail rollback 时, llm_call_log row 真**仍 persist** (沿用
        ADR-032 §Decision split audit 体例 + bootstrap.py:79 docstring sustained).
        真意义: LLM cost 真**append-only audit ledger**, 反**主 ingestion transaction
        rollback 错杀**真 cost 数据.
    """
    from app.services.db import get_sync_conn
    from app.services.news import NewsIngestionService, get_news_classifier

    logger.info(
        "POST /api/news/ingest query=%r limit_per_source=%d",
        req.query,
        req.limit_per_source,
    )

    pipeline = _build_pipeline_5_sources()
    classifier = get_news_classifier(conn_factory=get_sync_conn)
    service = NewsIngestionService(pipeline=pipeline, classifier=classifier)

    conn = get_sync_conn()
    try:
        stats = service.ingest(
            query=req.query,
            conn=conn,
            limit_per_source=req.limit_per_source,
            decision_id_prefix=req.decision_id_prefix,
        )
        conn.commit()  # caller 真事务边界 (铁律 32)
    except Exception as exc:
        conn.rollback()
        logger.exception("ingest_news failed query=%r: %s", req.query, exc)
        # P2-3 reviewer adopt: 反 expose 内 exception message (DSN/table/column 真 leak)
        # 走 sanitized detail (logger.exception 真**保留 full stack** 反 truncate diagnose).
        raise HTTPException(
            status_code=500,
            detail=f"ingestion failed: {type(exc).__name__}",
        ) from exc
    finally:
        conn.close()

    return IngestResponse(
        fetched=stats.fetched,
        ingested=stats.ingested,
        classified=stats.classified,
        classify_failed=stats.classify_failed,
        query=req.query,
        limit_per_source=req.limit_per_source,
    )


@router.post("/ingest_rsshub", response_model=IngestRsshubResponse)
def ingest_news_rsshub(req: IngestRsshubRequest) -> IngestRsshubResponse:
    """Manual trigger RSSHub fetch + classify + persist (route-path 独立 caller, sub-PR 8b-rsshub).

    沿用 sub-PR 6 design intent + sub-PR 7c NewsIngestionService orchestrator + sub-PR
    7b.3 v2 bootstrap singleton classifier. RSSHub 真**route-driven** caller 体例,
    反主链路 5-source ingest (反 search keyword semantic).

    Args:
        req: IngestRsshubRequest body — route_path + limit + decision_id_prefix.

    Returns:
        IngestRsshubResponse with IngestionStats fields + echo route_path/limit.

    Raises:
        HTTPException 500: 任 fetcher init / pipeline run / DB insert 真 raise.
            P2-3 sub-PR 8a-followup-A 体例 sustained: detail 走 sanitized
            `type(exc).__name__` (反 expose 内 exception message DSN/table leak).

    Note (Beat schedule defer 到 sub-PR 8b-cadence):
        本 endpoint 真**manual trigger** sustained. cron 频率 + dingtalk rate-limit +
        cost cap 决议 留 sub-PR 8b-cadence 真预约 (沿用 ADR-DRAFT row 2 sediment).

    Note (split-transaction LLM audit, 沿用 sub-PR 8a 体例 sustained):
        ingestion 真**主 conn** rollback 时, llm_call_log row 真**仍 persist**
        (沿用 ADR-032 §Decision split audit 体例 + bootstrap.py:79 docstring sustained).
    """
    from app.services.db import get_sync_conn
    from app.services.news import NewsIngestionService, get_news_classifier

    logger.info(
        "POST /api/news/ingest_rsshub route_path=%r limit=%d",
        req.route_path,
        req.limit,
    )

    pipeline = _build_pipeline_rsshub_only()
    classifier = get_news_classifier(conn_factory=get_sync_conn)
    service = NewsIngestionService(pipeline=pipeline, classifier=classifier)

    conn = get_sync_conn()
    try:
        stats = service.ingest(
            query=req.route_path,
            conn=conn,
            limit_per_source=req.limit,
            decision_id_prefix=req.decision_id_prefix,
        )
        conn.commit()  # caller 真事务边界 (铁律 32)
    except Exception as exc:
        conn.rollback()
        logger.exception("ingest_news_rsshub failed route_path=%r: %s", req.route_path, exc)
        # P2-3 sub-PR 8a-followup-A 体例 sustained: sanitized exception detail
        raise HTTPException(
            status_code=500,
            detail=f"rsshub ingestion failed: {type(exc).__name__}",
        ) from exc
    finally:
        conn.close()

    return IngestRsshubResponse(
        fetched=stats.fetched,
        ingested=stats.ingested,
        classified=stats.classified,
        classify_failed=stats.classify_failed,
        route_path=req.route_path,
        limit=req.limit,
    )


@router.get("/stats", response_model=NewsStatsResponse)
def get_news_stats() -> NewsStatsResponse:
    """最近 24h news_raw + news_classified row count + last 5 ingestion samples.

    Returns:
        NewsStatsResponse with news_raw_24h_count / news_classified_24h_count /
        last_5_news_raw / last_5_news_classified.

    Raises:
        HTTPException 500: 任 SQL 执行 fail 真 raise (P1-2 reviewer adopt sanitize 体例).
    """
    from app.services.db import get_sync_conn

    conn = get_sync_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM news_raw
                WHERE fetched_at > NOW() - INTERVAL '24 hours'
                """
            )
            news_raw_24h = cur.fetchone()[0]

            cur.execute(
                """
                SELECT count(*) FROM news_classified
                WHERE classified_at > NOW() - INTERVAL '24 hours'
                """
            )
            news_classified_24h = cur.fetchone()[0]

            cur.execute(
                """
                SELECT news_id, source, title, timestamp, fetched_at
                FROM news_raw
                ORDER BY news_id DESC
                LIMIT 5
                """
            )
            last_5_raw = [
                NewsRawSample(
                    news_id=r[0],
                    source=r[1],
                    title=r[2][:80],
                    timestamp=r[3].isoformat() if r[3] else None,
                    fetched_at=r[4].isoformat() if r[4] else None,
                )
                for r in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT news_id, sentiment_score, category, urgency, profile,
                       classifier_model, classified_at
                FROM news_classified
                ORDER BY news_id DESC
                LIMIT 5
                """
            )
            last_5_classified = [
                NewsClassifiedSample(
                    news_id=r[0],
                    sentiment_score=float(r[1]) if r[1] is not None else None,
                    category=r[2],
                    urgency=r[3],
                    profile=r[4],
                    classifier_model=r[5],
                    classified_at=r[6].isoformat() if r[6] else None,
                )
                for r in cur.fetchall()
            ]

        return NewsStatsResponse(
            news_raw_24h_count=int(news_raw_24h),
            news_classified_24h_count=int(news_classified_24h),
            last_5_news_raw=last_5_raw,
            last_5_news_classified=last_5_classified,
        )
    except Exception as exc:
        # P1-2 reviewer adopt: 真 SQL fail wrap HTTPException 500 sanitize 体例
        # (反 expose 内 exception message 真 leak DSN/table/column).
        # logger.exception 真**保留 full stack** trace diagnose, response detail truncate.
        logger.exception("get_news_stats failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"stats query failed: {type(exc).__name__}",
        ) from exc
    finally:
        conn.close()
