"""AnnouncementProcessor — V3 §11.1 row 5 公告流 orchestrator (sub-PR 11b sediment per ADR-049).

scope (sub-PR 11b, S2.5 implementation 闭环 Layer 2.2 完整闭环 sediment, sustained sub-PR 7c
NewsIngestionService precedent 体例):
- RsshubNewsFetcher (sub-PR 6) route_path 走 announcement-specific routes (e.g.
  `/cninfo/announcement/{stockCode}`) per ADR-049 §1 Decision 3 RSSHub route reuse
- 逐 NewsItem → infer announcement_type via title keyword regex (annual_report / quarterly_report /
  material_event / shareholder_meeting / dividend / other)
- announcement_type filter EXCLUDE earnings disclosure (annual_report + quarterly_report) per
  ADR-049 §2 Finding #2 resolution — 反 dedup with earnings_announcements 207K rows Tushare path
- 逐 surviving item: INSERT announcement_raw RETURNING announcement_id (沿用 sub-PR 11a DDL BIGSERIAL PK)
- per-source fail-soft (任 1 source fail, 仅缺 announcement context, V3 §3.5 + ADR-049 §1 Decision 5)
- 0 conn.commit (铁律 32 sustained, caller 真**事务边界管理者**)

caller 真**唯一 sanctioned 入口** (沿用 sub-PR 7c bootstrap 体例 sustained):
    from backend.app.services.news import AnnouncementProcessor
    from backend.qm_platform.news import DataPipeline, RsshubNewsFetcher
    from backend.app.services.db import get_sync_conn

    pipeline = DataPipeline([RsshubNewsFetcher(base_url="http://localhost:1200")])
    processor = AnnouncementProcessor(pipeline=pipeline)

    with get_sync_conn() as conn:
        stats = processor.ingest(
            symbol_id="600519",
            source="cninfo",
            conn=conn,
            limit=10,
        )
        conn.commit()  # caller 真值 事务边界 (铁律 32)
        # stats: AnnouncementStats(fetched=10, ingested=7, skipped_earnings=3, skipped_unknown=0)

关联铁律:
- 17 (DataPipeline 入库 — INSERT announcement_raw 走本 service orchestrator)
- 22 (文档跟随代码 — ADR-049 §3 Phase 2 sub-PR 11b implementation 真值落地)
- 25 (改什么读什么 — Phase 0/1 fresh verify sustained sub-PR 11a sediment)
- 31 (Engine 层纯计算 sustained — DataPipeline 0 DB IO, AnnouncementProcessor 真**orchestrator** 走 conn)
- 32 (Service 不 commit, 事务边界由 Router/Celery 管 — caller 真 commit/rollback)
- 33 (fail-loud — DataPipeline error / DB error 真 raise, per-item type inference 真 fail-soft as 'other')
- 41 (timezone — NewsItem.timestamp tz-aware sustained sub-PR 1-6 sediment)
- 45 (4 doc fresh read SOP enforcement)

关联文档:
- V3 line 1224 (AnnouncementProcessor backend/app/services/news/ 真值 预约 path)
- ADR-049 (V3 §S2.5 architecture sediment + RSSHub route reuse decision: 6 decisions + 3 findings)
- backend/migrations/2026_05_09_announcement_raw.sql (sub-PR 11a DDL 12 columns + 6 enum CHECK)
- backend/qm_platform/news/announcement_routes.py (sub-PR 11b route config)
- backend/qm_platform/news/rsshub.py (sub-PR 6 RsshubNewsFetcher route_path arg precedent)
- backend/app/services/news/news_ingestion_service.py (sub-PR 7c orchestrator precedent)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.qm_platform.news.base import NewsItem
    from backend.qm_platform.news.pipeline import DataPipeline

logger = logging.getLogger(__name__)


# announcement_type enum sustained sub-PR 11a DDL CHECK constraint 6 enum
ANNOUNCEMENT_TYPE_ANNUAL = "annual_report"
ANNOUNCEMENT_TYPE_QUARTERLY = "quarterly_report"
ANNOUNCEMENT_TYPE_MATERIAL = "material_event"
ANNOUNCEMENT_TYPE_SHAREHOLDER = "shareholder_meeting"
ANNOUNCEMENT_TYPE_DIVIDEND = "dividend"
ANNOUNCEMENT_TYPE_OTHER = "other"

# Type inference regex (title keyword based, sustained 公告 真生产 wording precedent).
# `_PATTERN_ANNUAL` uses negative lookbehind `(?<!半)` to make it order-independent vs
# `_PATTERN_QUARTERLY` (反 sub-PR 11b reviewer P2 regex order fragility ride-next finding):
# `半年度报告` / `半年报` (semi-annual = quarterly_report) used to falsely match 年度报告 / 年报
# substring under naive ordering. With negative lookbehind, ANNUAL match requires the 年 char
# NOT preceded by 半, so 半年报 → ANNUAL=NO MATCH → falls through to QUARTERLY (which already
# explicitly captures 半年[度报]?报告|半年报). Order-independence sustained sub-PR 12 cleanup.
_PATTERN_ANNUAL = re.compile(r"(?<!半)年[度报]?报告|(?<!半)年报", re.IGNORECASE)
_PATTERN_QUARTERLY = re.compile(r"季[度报]?报告|季报|半年[度报]?报告|半年报", re.IGNORECASE)
_PATTERN_SHAREHOLDER = re.compile(r"股东大会|临时股东大会|股东会议", re.IGNORECASE)
_PATTERN_DIVIDEND = re.compile(r"分红|派息|利润分配|股利|权益分派", re.IGNORECASE)
_PATTERN_MATERIAL = re.compile(
    r"重大[事项件]|重要事项|重大资产|重大合同|重大诉讼|信息披露", re.IGNORECASE
)


def _infer_announcement_type(title: str) -> str:
    """Infer announcement_type from title via keyword regex.

    Order is defensive but NOT strictly required (sub-PR 12 ride-next reviewer P1 fix):
    `_PATTERN_ANNUAL` uses negative lookbehind `(?<!半)` to reject semi-annual matches
    regardless of check order — see 8-line comment block above the pattern definitions.
    Quarterly is still checked first as belt-and-suspenders + clear ordering intent.

    Earnings (annual / quarterly) checked before material_event since 重大事项 wording
    can co-occur with earnings disclosure (e.g. 重大事项 提示: 关于年度报告披露). 沿用 ADR-049
    §2 Finding #2 resolution (annual_report + quarterly_report 真值 之后 service-layer filter
    EXCLUDE dedup with earnings_announcements Tushare path).

    Args:
        title: announcement 公告 title text.

    Returns:
        announcement_type enum string (one of 6 sub-PR 11a DDL CHECK constraint values).
    """
    if _PATTERN_QUARTERLY.search(title):
        return ANNOUNCEMENT_TYPE_QUARTERLY
    if _PATTERN_ANNUAL.search(title):
        return ANNOUNCEMENT_TYPE_ANNUAL
    if _PATTERN_SHAREHOLDER.search(title):
        return ANNOUNCEMENT_TYPE_SHAREHOLDER
    if _PATTERN_DIVIDEND.search(title):
        return ANNOUNCEMENT_TYPE_DIVIDEND
    if _PATTERN_MATERIAL.search(title):
        return ANNOUNCEMENT_TYPE_MATERIAL
    return ANNOUNCEMENT_TYPE_OTHER


# Earnings disclosure types — EXCLUDED from announcement_raw INSERT per ADR-049 §2 Finding #2
# (反 dedup with earnings_announcements 207K rows Tushare-fed PEAD subset path)
_EARNINGS_TYPES = frozenset({ANNOUNCEMENT_TYPE_ANNUAL, ANNOUNCEMENT_TYPE_QUARTERLY})


@dataclass(frozen=True, slots=True)
class AnnouncementStats:
    """AnnouncementProcessor.ingest 真值 stats (sub-PR 11b sediment).

    Fields:
        fetched: RsshubNewsFetcher returned NewsItem count.
        ingested: announcement_raw INSERT 成功 row count.
        skipped_earnings: annual_report + quarterly_report skip count
                          (per ADR-049 §2 Finding #2 EXCLUDE earnings disclosure dedup).
        skipped_unknown: 'other' type skip count (反 silent insert noise content,
                         sub-PR 11b 起手 conservative — 'other' filtered out;
                         sub-PR 12+ candidate to relax based on real production traffic).
    """

    fetched: int
    ingested: int
    skipped_earnings: int
    skipped_unknown: int


class AnnouncementProcessor:
    """V3 §11.1 row 5 真值 预约 orchestrator — RsshubNewsFetcher → infer type → announcement_raw.

    DI 体例 (沿用 sub-PR 7c NewsIngestionService DI pattern + ADR-032 line 36):
        pipeline = DataPipeline([RsshubNewsFetcher(...)])  # sub-PR 6 sediment
        processor = AnnouncementProcessor(pipeline=pipeline)

    architecture (沿用 ADR-049 §1 Decision 2 hybrid module boundary + 铁律 31 sustained):
        - DataPipeline (qm_platform/news/, 0 DB IO 铁律 31) → list[NewsItem]
        - 本 service (app/services/news/, orchestrator 真值 入库点) → conn → INSERT announcement_raw
        - 0 separate fetcher class (ADR-049 §1 Decision 3 RSSHub route reuse sustained)
        - 0 conn.commit (铁律 32, caller 真值 事务边界)
    """

    def __init__(self, *, pipeline: DataPipeline) -> None:
        """Initialize AnnouncementProcessor.

        Args:
            pipeline: DataPipeline (sub-PR 7a, single-fetcher RSSHub route_path query).

        Note:
            keyword-only — 反 positional swap silent bug (沿用 sub-PR 7c contract).
            DI 体例反 hidden coupling (反 内调 RsshubNewsFetcher init).
        """
        self._pipeline = pipeline

    def ingest(
        self,
        *,
        symbol_id: str,
        source: str,
        conn: Any,
        limit: int = 10,
    ) -> AnnouncementStats:
        """Orchestrate full announcement ingestion: RSSHub fetch → infer type → filter → INSERT.

        Args:
            symbol_id: stock code (e.g. "600519" for 贵州茅台). 公告 必 attached to symbol
                (sub-PR 11a DDL announcement_raw.symbol_id NOT NULL, 反 大盘公告 unmapped).
            source: announcement source enum (cninfo/sse/szse, ADR-049 §1 Decision 3).
                NOTE: cninfo 真**1/3 working baseline** sub-PR 11b sediment, sustained
                LL-115 capacity expansion 真值 silent overwrite anti-pattern reverse case.
                sse/szse 真 reserved 待 S5 paper-mode 5d period verify (ADR-049 §2 Finding #1).
            conn: psycopg2 connection — caller 真**事务边界管理者** (铁律 32 sustained).
            limit: per-route fetch limit (默认 10, RSSHub 反 server-side clamp).

        Returns:
            AnnouncementStats — fetched / ingested / skipped_earnings / skipped_unknown counts.

        Raises:
            ValueError: unknown source enum (反 silent default fallback, 沿用铁律 33 fail-loud).

        Note (per-source fail-soft, ADR-049 §1 Decision 5 sustained DataPipeline 体例):
            DataPipeline.fetch_all 真**aggregate fail-soft** sustained sub-PR 7a 体例 — single
            source fail per partial success. 反 silent skip silent-source-zero-result 真 logged
            via DataPipeline.fail-soft mechanism.

        Note (announcement_type filter, ADR-049 §2 Finding #2 sediment):
            annual_report + quarterly_report 真**EXCLUDE** (skipped_earnings count) — 反 dedup
            with earnings_announcements 207K rows Tushare-fed PEAD subset path. sub-PR 12+
            候选 relax based on Tushare deprecation OR fresh evidence sub-PR 11b post-merge.
            'other' type 真**EXCLUDE** (skipped_unknown count) — 反 silent insert noise content
            initially, sub-PR 12+ relax based on real production traffic patterns.

        Note (0 conn.commit, 铁律 32 sustained):
            本 service 0 conn.commit / 0 conn.rollback. caller 真值 事务边界管理者
            (沿用 sub-PR 7c NewsIngestionService 体例 sustained ADR-032 line 36).

        Note (sub-PR 13 ADR-052 reverse — AKShare query semantic):
            pipeline.fetch_all(query=symbol_id) 反 RSSHub route_path semantic (sub-PR 11b reverse).
            ADR-049 §1 Decision 3 RSSHub route reuse 真值 verified broken (LL-142 sediment).
            AkshareCninfoFetcher.fetch(query=symbol_id) 直 pass 6-digit stock code.
        """
        from backend.qm_platform.news.announcement_routes import validate_source

        # Source enum validation (sustained 铁律 33 fail-loud, sub-PR 13 ADR-052 reverse)
        validate_source(source)

        # AKShare cninfo fetcher takes symbol_id directly as query (反 RSSHub route_path semantic)
        items = self._pipeline.fetch_all(
            query=symbol_id,
            limit_per_source=limit,
        )

        ingested = 0
        skipped_earnings = 0
        skipped_unknown = 0

        for item in items:
            ann_type = _infer_announcement_type(item.title)

            if ann_type in _EARNINGS_TYPES:
                # ADR-049 §2 Finding #2 EXCLUDE earnings disclosure dedup
                skipped_earnings += 1
                logger.debug(
                    "AnnouncementProcessor skip earnings type=%s symbol=%s title=%r",
                    ann_type,
                    symbol_id,
                    item.title[:80],
                )
                continue

            if ann_type == ANNOUNCEMENT_TYPE_OTHER:
                # Conservative: 'other' type 真 skip (反 silent insert noise)
                skipped_unknown += 1
                logger.debug(
                    "AnnouncementProcessor skip unknown type symbol=%s title=%r",
                    symbol_id,
                    item.title[:80],
                )
                continue

            self._insert_announcement_raw(
                item=item,
                conn=conn,
                symbol_id=symbol_id,
                source=source,
                announcement_type=ann_type,
            )
            ingested += 1

        stats = AnnouncementStats(
            fetched=len(items),
            ingested=ingested,
            skipped_earnings=skipped_earnings,
            skipped_unknown=skipped_unknown,
        )

        logger.info(
            "AnnouncementProcessor.ingest symbol=%s source=%s stats=%s",
            symbol_id,
            source,
            stats,
        )
        return stats

    @staticmethod
    def _insert_announcement_raw(
        *,
        item: NewsItem,
        conn: Any,
        symbol_id: str,
        source: str,
        announcement_type: str,
    ) -> int:
        """INSERT NewsItem mapped → announcement_raw, RETURNING announcement_id (BIGSERIAL PK).

        Mapping (sub-PR 11a DDL 12 columns):
        - announcement_id BIGSERIAL → DB auto-fill
        - symbol_id NOT NULL → caller arg (公告 必 attached to symbol per DDL)
        - source NOT NULL → caller arg ('cninfo'/'sse'/'szse'/'rsshub')
        - announcement_type NOT NULL CHECK → inferred from title via _infer_announcement_type
        - title TEXT NOT NULL → item.title
        - url TEXT → item.url (RSSHub None URL fallback per sub-PR 6 RSSHub None URL precedent)
        - pdf_url TEXT → None (sub-PR 11b 起手 — pdf_url extraction defer to sub-PR 12+
          based on real RSSHub feed structure verify ADR-049 §2 Finding #1)
        - disclosure_date DATE NOT NULL → item.timestamp.date() (公告 disclosure T 日)
        - content_snippet TEXT → item.content (truncated to 1000 char defensively)
        - fetch_cost NUMERIC NOT NULL DEFAULT 0 → 0 (RSSHub anonymous, $0 cost sub-PR 6)
        - fetch_latency_ms INT NOT NULL DEFAULT 0 → 0 (per-item not measured at orchestrator layer)
        - fetched_at TIMESTAMPTZ DEFAULT NOW() → DB auto-fill

        Args:
            item: NewsItem from RsshubNewsFetcher.
            conn: psycopg2 connection (caller-managed transaction).
            symbol_id: stock code.
            source: announcement source enum.
            announcement_type: inferred enum (must NOT be in _EARNINGS_TYPES or 'other').

        Returns:
            announcement_id BIGSERIAL value (RETURNING clause).

        Raises:
            psycopg2.Error: DB-level error 真**fail-loud raise** (caller rollback batch).
        """
        sql = """
            INSERT INTO announcement_raw (
                symbol_id, source, announcement_type, title, url, pdf_url,
                disclosure_date, content_snippet
            ) VALUES (
                %(symbol_id)s, %(source)s, %(announcement_type)s, %(title)s, %(url)s,
                %(pdf_url)s, %(disclosure_date)s, %(content_snippet)s
            )
            RETURNING announcement_id
        """

        # Defensive content_snippet truncate (反 unbounded TEXT bloat from full PDF content paste)
        content_snippet = (item.content or "")[:1000] if item.content else None

        # disclosure_date from item.timestamp (NewsItem.timestamp tz-aware UTC, 铁律 41).
        # date() conversion drops tz info — disclosure_date is DATE type (T 日, 反 fetched_at).
        disclosure_dt: date = item.timestamp.date()

        with conn.cursor() as cur:
            cur.execute(
                sql,
                {
                    "symbol_id": symbol_id,
                    "source": source,
                    "announcement_type": announcement_type,
                    "title": item.title,
                    "url": item.url,
                    "pdf_url": None,  # sub-PR 12+ candidate
                    "disclosure_date": disclosure_dt,
                    "content_snippet": content_snippet,
                },
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(
                    "announcement_raw INSERT RETURNING returned None — DDL constraint violation"
                )
            return int(row[0])
