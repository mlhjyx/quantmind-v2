"""NewsIngestionService — V3 line 1222 真预约 orchestrator (sub-PR 7c #243 sediment).

scope (sub-PR 7c, Sprint 2 ingestion 闭环 Layer 2.2 完整闭环 sediment):
- DataPipeline (sub-PR 7a #239) 6 源并行 fetch → list[NewsItem]
- 逐 item: INSERT news_raw RETURNING news_id (沿用 sub-PR 7b.1 v2 #240 DDL BIGSERIAL PK)
- NewsClassifierService.classify (sub-PR 7b.2 #241) → ClassificationResult
- NewsClassifierService.persist (sub-PR 7b.3 v2 #242) → news_classified UPSERT (FK news_raw)
- per-item ClassificationParseError fail-soft (audit log + skip, sub-PR 7b.2 contract)
- DB errors (psycopg2.Error from INSERT news_raw / persist UPSERT) 真 fail-loud raise
  (沿用铁律 33, caller rollback batch — sub-PR 7c LL-067 reviewer P1 sediment 真**修订**:
  反 silent swallow non-ClassificationParseError, fail-loud propagate to caller)
- 0 conn.commit (铁律 32 sustained, caller 真**事务边界管理者**)

caller 真**唯一 sanctioned 入口** (沿用 sub-PR 7b.3 v2 bootstrap 体例 sustained):
    from backend.app.services.news import NewsIngestionService, get_news_classifier
    from backend.qm_platform.news import (
        DataPipeline, ZhipuNewsFetcher, TavilyNewsFetcher, ...
    )
    from backend.app.services.db import get_sync_conn

    pipeline = DataPipeline([ZhipuNewsFetcher(...), TavilyNewsFetcher(...), ...])
    classifier = get_news_classifier(conn_factory=get_sync_conn)
    service = NewsIngestionService(pipeline=pipeline, classifier=classifier)

    with get_sync_conn() as conn:
        stats = service.ingest(query="贵州茅台", conn=conn, limit_per_source=10)
        conn.commit()  # caller 真事务边界 (铁律 32)
        # stats: {ingested: 9, classified: 8, classify_failed: 1}

关联铁律:
- 17 (DataPipeline 入库 — INSERT news_raw 走本 service orchestrator, 沿用 sub-PR 7a 0 DB IO + 本 service 真**入库点**)
- 22 (文档跟随代码 — ADR-031 §6 line 153 patch sediment 同 PR)
- 25 (改什么读什么 — Phase 0/1 6 doc + V3 + ADR + sub-PR 1-6/7a/7b.1 v2/7b.2/7b.3 v2 fresh verify sustained)
- 31 (Engine 层纯计算 sustained — DataPipeline 0 DB IO sustained, NewsIngestionService 真**orchestrator** 走 conn)
- 32 (Service 不 commit, 事务边界由 Router/Celery 管 — caller 真 commit/rollback)
- 33 (fail-loud — DataPipeline error / unexpected exception 真 raise; per-item ClassificationParseError 真 fail-soft 沿用 sub-PR 7b.2 contract)
- 41 (timezone — NewsItem.timestamp tz-aware sustained sub-PR 1-6 sediment)
- 45 (4 doc fresh read SOP enforcement, IRONLAWS PR-B sediment)

关联文档:
- V3 line 1222 (NewsIngestionService backend/app/services/news/ 真预约 path)
- V3§3.1 line 336-356 (news_raw schema sediment)
- V3§3.2 line 359-393 (news_classified + classify schema sediment)
- ADR-031 §6 line 153 (sub-PR 7c sediment 真预约)
- ADR-032 line 36 (caller bootstrap factory + conn_factory DI 真预约)
- backend/qm_platform/news/pipeline.py (sub-PR 7a DataPipeline)
- backend/app/services/news/news_classifier_service.py (sub-PR 7b.2 + 7b.3 v2)
- backend/app/services/news/bootstrap.py (sub-PR 7b.3 v2 get_news_classifier)
- backend/migrations/2026_05_06_news_raw.sql (sub-PR 7b.1 v2 DDL)
- backend/migrations/2026_05_06_news_classified.sql (sub-PR 7b.1 v2 DDL FK CASCADE)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .news_classifier_service import ClassificationParseError

if TYPE_CHECKING:
    from backend.qm_platform.news.base import NewsItem
    from backend.qm_platform.news.pipeline import DataPipeline

    from .news_classifier_service import NewsClassifierService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionStats:
    """NewsIngestionService.ingest 真返 stats (sub-PR 7c 沿用 V3§3.1 fail-soft 体例).

    Fields:
        fetched: DataPipeline.fetch_all 返 raw item count (post-dedup).
        ingested: news_raw INSERT 成功 row count.
        classified: NewsClassifierService.classify+persist 成功 row count.
        classify_failed: ClassificationParseError fail-soft skip count
                         (沿用 sub-PR 7b.2 contract — caller 接住 audit + skip).
    """

    fetched: int
    ingested: int
    classified: int
    classify_failed: int


class NewsIngestionService:
    """V3 line 1222 真预约 orchestrator — DataPipeline → news_raw → classify → persist.

    DI 体例 (沿用 sub-PR 7b.3 v2 bootstrap factory pattern + ADR-032 line 36):
        pipeline = DataPipeline([fetcher1, fetcher2, ...])  # sub-PR 7a sediment
        classifier = get_news_classifier(conn_factory=get_sync_conn)  # sub-PR 7b.3 v2
        service = NewsIngestionService(pipeline=pipeline, classifier=classifier)

    architecture (沿用铁律 31 + 32 sustained 真讽刺案例 #11 候选 lesson 真应用):
        - DataPipeline (qm_platform/news/, 0 DB IO 铁律 31) → list[NewsItem]
        - 本 service (app/services/news/, orchestrator 真入库点) → conn → INSERT news_raw
        - NewsClassifierService.classify+persist (app/services/news/, sub-PR 7b.2/7b.3 v2)
        - 0 conn.commit (铁律 32, caller 真事务边界)
    """

    def __init__(
        self,
        *,
        pipeline: DataPipeline,
        classifier: NewsClassifierService,
    ) -> None:
        """Initialize NewsIngestionService.

        Args:
            pipeline: DataPipeline (sub-PR 7a, 6 源并行 fetch).
            classifier: NewsClassifierService (sub-PR 7b.2 classify + 7b.3 v2 persist).

        Note:
            两参数均 keyword-only — 反 positional swap silent bug.
            DI 体例反 hidden coupling (反 内调 get_news_classifier / DataPipeline init).
        """
        self._pipeline = pipeline
        self._classifier = classifier

    def ingest(
        self,
        *,
        query: str,
        conn: Any,
        limit_per_source: int = 10,
        total_limit: int | None = None,
        decision_id_prefix: str | None = None,
    ) -> IngestionStats:
        """Orchestrate full ingestion → classify → persist 全链.

        Args:
            query: caller search query (per-source semantics 沿用 sub-PR 1-6 plugin 体例).
            conn: psycopg2 connection — caller 真**事务边界管理者** (铁律 32 sustained).
            limit_per_source: per-source fetch limit (默认 10).
            total_limit: aggregated dedup 后 total limit (None = 全保留).
            decision_id_prefix: optional decision_id prefix for audit traceability
                                (e.g. "ingest-20260507-1430" → "ingest-20260507-1430-001").

        Returns:
            IngestionStats — fetched / ingested / classified / classify_failed counts.

        Raises:
            ValueError: query empty (沿用 DataPipeline.fetch_all 真 fail-loud, 铁律 33).

        Note (per-item ClassificationParseError fail-soft only, 沿用 sub-PR 7b.2 contract):
            **仅 ClassificationParseError 真 fail-soft** (audit log + skip, 反 single bad
            LLM response kill batch). news_raw INSERT 真**已成功** (count in `ingested`),
            classified count 0 该 item.

            **别 exception (psycopg2.Error / RuntimeError / ValueError) 真 fail-loud
            propagate** — sub-PR 7c LL-067 reviewer P1 finding sediment sustained 真**修订**:
            DB-level error (FK violation / NOT NULL / connection drop / persist news_id
            None silent path) 真**反 silent swallow**, raise to caller, caller 真 rollback
            batch (沿用铁律 33 fail-loud sustained).

            sub-PR 7c 真**反 rollback** 单 ClassificationParseError item — caller 沿用
            batch-level transaction 可选择: 全 batch commit (容忍 partial classify, 沿用
            sub-PR 7b.2 真**未来 backfill** path 真预约) OR 全 batch rollback
            (沿用 sub-PR 7b.1 v2 FK CASCADE 真**自然 cleanup**).

        Note (0 conn.commit, 铁律 32 sustained):
            本 service 0 conn.commit / 0 conn.rollback. caller 真**事务边界管理者**
            (沿用 sub-PR 7b.3 v2 体例 sustained ADR-032 line 36 真预约).
        """
        items = self._pipeline.fetch_all(
            query=query,
            limit_per_source=limit_per_source,
            total_limit=total_limit,
        )

        ingested = 0
        classified = 0
        classify_failed = 0

        for idx, item in enumerate(items):
            news_id = self._insert_news_raw(item, conn=conn)
            ingested += 1

            decision_id = (
                f"{decision_id_prefix}-{idx:03d}"
                if decision_id_prefix
                else None
            )
            try:
                result = self._classifier.classify(item, decision_id=decision_id)
                self._classifier.persist(result, conn=conn, news_id=news_id)
                classified += 1
            except ClassificationParseError as e:
                # fail-soft 沿用 sub-PR 7b.2 contract sustained
                classify_failed += 1
                logger.warning(
                    "NewsIngestionService classify fail-soft news_id=%d source=%s: %s",
                    news_id,
                    item.source,
                    e,
                )

        stats = IngestionStats(
            fetched=len(items),
            ingested=ingested,
            classified=classified,
            classify_failed=classify_failed,
        )

        logger.info(
            "NewsIngestionService.ingest query=%r stats=%s",
            query,
            stats,
        )
        return stats

    @staticmethod
    def _insert_news_raw(item: NewsItem, *, conn: Any) -> int:
        """INSERT NewsItem → news_raw, RETURNING news_id (BIGSERIAL PK).

        9 columns INSERT (沿用 sub-PR 7b.1 v2 #240 DDL + NewsItem schema 1:1 align,
        反 news_id BIGSERIAL + fetched_at DEFAULT NOW() — 走 DB 自动填补).

        Args:
            item: NewsItem (sub-PR 1-6 sediment, NewsFetcher.fetch 真返).
            conn: psycopg2 connection (caller 真事务边界, 铁律 32).

        Returns:
            news_id (BIGSERIAL, FK news_classified 真依赖 sub-PR 7b.1 v2 sediment).

        Raises:
            psycopg2.Error: INSERT 失败 raise (caller rollback, 铁律 33 fail-loud).
        """
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_raw (
                    source, timestamp, title, content, url, lang, symbol_id,
                    fetch_cost, fetch_latency_ms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING news_id
                """,
                (
                    item.source,
                    item.timestamp,
                    item.title,
                    item.content,
                    item.url,
                    item.lang,
                    item.symbol_id,
                    item.fetch_cost_usd,
                    item.fetch_latency_ms,
                ),
            )
            row = cur.fetchone()
        if row is None:
            # PG INSERT...RETURNING 真**保证返单 row** (反 RETURNING 0 row 真 silent skip)
            raise RuntimeError(
                "INSERT news_raw RETURNING news_id 真 0 row — PG 异常或 BIGSERIAL 故障 "
                "(沿用铁律 33 fail-loud, caller rollback)"
            )
        return int(row[0])
