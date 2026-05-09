"""AnnouncementProcessor unit tests (sub-PR 11b sediment, V3 §S2.5 implementation).

scope (sub-PR 11b acceptance per ADR-049 §3 Phase 1 step 4):
- announcement_type inference via title keyword regex (6 enum cases + edge cases)
- earnings disclosure EXCLUDE filter (annual_report + quarterly_report skip count, ADR-049 §2 Finding #2)
- 'other' type EXCLUDE filter (skipped_unknown count, conservative initial sub-PR 11b)
- announcement_raw INSERT path (mock conn + fetchone, RETURNING announcement_id)
- per-source fail-soft (DataPipeline aggregate, sustained sub-PR 7c contract)
- ValueError on unknown source enum (沿用铁律 33 fail-loud)

Mock strategy (沿用 sub-PR 7c test_news_ingestion_service.py precedent):
- DataPipeline mock with fetch_all returning preset list[NewsItem]
- conn mock with cursor.fetchone returning preset announcement_id
- NewsItem dataclass mock minimal fields (title + content + url + timestamp + source + lang)

关联:
- ADR-049 §1 Decision 3 RSSHub route reuse
- ADR-049 §2 Finding #2 announcement_type EXCLUDE earnings disclosure
- backend/app/services/news/announcement_processor.py
- backend/qm_platform/news/announcement_routes.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from backend.app.services.news.announcement_processor import (
    ANNOUNCEMENT_TYPE_ANNUAL,
    ANNOUNCEMENT_TYPE_DIVIDEND,
    ANNOUNCEMENT_TYPE_MATERIAL,
    ANNOUNCEMENT_TYPE_OTHER,
    ANNOUNCEMENT_TYPE_QUARTERLY,
    ANNOUNCEMENT_TYPE_SHAREHOLDER,
    AnnouncementProcessor,
    AnnouncementStats,
    _infer_announcement_type,
)
from backend.qm_platform.news.announcement_routes import (
    DEFAULT_CNINFO_ROUTE_TEMPLATE,
    build_announcement_route,
)
from backend.qm_platform.news.base import NewsItem

# ─────────────────────────────────────────────────────────────
# §1 build_announcement_route (announcement_routes.py)
# ─────────────────────────────────────────────────────────────


class TestBuildAnnouncementRoute:
    """build_announcement_route — source enum → route_path substitution."""

    def test_cninfo_substitutes_stockcode(self) -> None:
        route = build_announcement_route(source="cninfo", symbol_id="600519")
        assert route == "/cninfo/announcement/600519"

    def test_sse_reserved_route(self) -> None:
        route = build_announcement_route(source="sse", symbol_id="600519")
        assert route == "/sse/disclosure/600519"

    def test_szse_reserved_route(self) -> None:
        route = build_announcement_route(source="szse", symbol_id="000001")
        assert route == "/szse/disclosure/000001"

    def test_unknown_source_raises_value_error(self) -> None:
        # 沿用铁律 33 fail-loud — 反 silent default fallback
        with pytest.raises(ValueError, match="Unknown announcement source"):
            build_announcement_route(source="unknown", symbol_id="600519")

    def test_default_cninfo_template_constant(self) -> None:
        assert DEFAULT_CNINFO_ROUTE_TEMPLATE == "/cninfo/announcement/{stockCode}"


# ─────────────────────────────────────────────────────────────
# §2 _infer_announcement_type (title keyword regex)
# ─────────────────────────────────────────────────────────────


class TestInferAnnouncementType:
    """_infer_announcement_type — 6 enum + edge case coverage."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("贵州茅台 2025 年度报告", ANNOUNCEMENT_TYPE_ANNUAL),
            ("贵州茅台 2025 年报", ANNOUNCEMENT_TYPE_ANNUAL),
            ("2025 第一季度报告", ANNOUNCEMENT_TYPE_QUARTERLY),
            ("2025 一季报", ANNOUNCEMENT_TYPE_QUARTERLY),
            ("2025 半年度报告", ANNOUNCEMENT_TYPE_QUARTERLY),
            ("2025 半年报", ANNOUNCEMENT_TYPE_QUARTERLY),
            ("关于召开 2025 年第一次临时股东大会的通知", ANNOUNCEMENT_TYPE_SHAREHOLDER),
            ("2025 年股东大会决议公告", ANNOUNCEMENT_TYPE_SHAREHOLDER),
            ("关于 2025 年度利润分配方案的公告", ANNOUNCEMENT_TYPE_DIVIDEND),
            ("2025 年权益分派实施公告", ANNOUNCEMENT_TYPE_DIVIDEND),
            ("派息公告", ANNOUNCEMENT_TYPE_DIVIDEND),
            ("关于重大资产重组事项的进展公告", ANNOUNCEMENT_TYPE_MATERIAL),
            ("重大事项停牌公告", ANNOUNCEMENT_TYPE_MATERIAL),
            ("信息披露事务管理制度", ANNOUNCEMENT_TYPE_MATERIAL),
            ("公司公告 - 一般披露", ANNOUNCEMENT_TYPE_OTHER),
            ("普通通知", ANNOUNCEMENT_TYPE_OTHER),
        ],
    )
    def test_keyword_inference(self, title: str, expected: str) -> None:
        assert _infer_announcement_type(title) == expected

    def test_empty_title_returns_other(self) -> None:
        assert _infer_announcement_type("") == ANNOUNCEMENT_TYPE_OTHER

    def test_annual_priority_over_material(self) -> None:
        # 重大事项 + 年度报告同 title → annual_report 优先 (regex order matters)
        title = "关于年度报告披露的重大事项提示性公告"
        assert _infer_announcement_type(title) == ANNOUNCEMENT_TYPE_ANNUAL


# ─────────────────────────────────────────────────────────────
# §3 AnnouncementProcessor.ingest (mock pipeline + conn)
# ─────────────────────────────────────────────────────────────


def _make_news_item(
    *,
    title: str,
    timestamp: datetime | None = None,
    url: str | None = "https://example.com/announce/1",
    content: str | None = "公告内容摘要",
) -> NewsItem:
    """Helper — build minimal NewsItem fixture."""
    return NewsItem(
        title=title,
        content=content,
        url=url,
        timestamp=timestamp or datetime(2026, 5, 9, 10, 30, tzinfo=UTC),
        source="rsshub",
        lang="zh",
        fetch_cost_usd=Decimal("0"),
        fetch_latency_ms=0,
    )


def _make_mock_conn(announcement_id_seq: list[int]) -> MagicMock:
    """Helper — build mock psycopg2 conn with cursor.fetchone returning preset IDs.

    Args:
        announcement_id_seq: list of announcement_id values RETURNING clause yields.
    """
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    # fetchone returns single-element tuple of next id (psycopg2 RETURNING semantics)
    fetchone_iter = iter([(aid,) for aid in announcement_id_seq])
    cursor.fetchone = MagicMock(side_effect=lambda: next(fetchone_iter))

    conn.cursor = MagicMock(return_value=cursor)
    return conn


class TestAnnouncementProcessorIngest:
    """AnnouncementProcessor.ingest — full orchestration with mocked DataPipeline + conn."""

    def test_ingest_material_event_inserts(self) -> None:
        # Given: DataPipeline returns 1 material_event item
        items = [_make_news_item(title="关于重大资产重组事项的进展公告")]
        pipeline = MagicMock()
        pipeline.fetch_all = MagicMock(return_value=items)
        conn = _make_mock_conn([12345])

        processor = AnnouncementProcessor(pipeline=pipeline)

        # When: ingest
        stats = processor.ingest(
            symbol_id="600519",
            source="cninfo",
            conn=conn,
            limit=10,
        )

        # Then: 1 ingested, 0 skipped
        assert stats == AnnouncementStats(
            fetched=1,
            ingested=1,
            skipped_earnings=0,
            skipped_unknown=0,
        )

        # pipeline.fetch_all called with symbol_id (sub-PR 13 ADR-052 reverse — AKShare query semantic)
        pipeline.fetch_all.assert_called_once_with(
            query="600519",
            limit_per_source=10,
        )

        # conn.cursor.execute called once (1 INSERT)
        assert conn.cursor().execute.call_count == 1

    def test_ingest_excludes_earnings_disclosure(self) -> None:
        # Given: 3 items — annual_report (skip), quarterly_report (skip), material_event (insert)
        items = [
            _make_news_item(title="贵州茅台 2025 年度报告"),
            _make_news_item(title="2025 一季报"),
            _make_news_item(title="重大事项停牌公告"),
        ]
        pipeline = MagicMock()
        pipeline.fetch_all = MagicMock(return_value=items)
        conn = _make_mock_conn([99999])

        processor = AnnouncementProcessor(pipeline=pipeline)
        stats = processor.ingest(
            symbol_id="600519",
            source="cninfo",
            conn=conn,
            limit=10,
        )

        # Then: only material_event ingested, 2 earnings skipped
        assert stats.fetched == 3
        assert stats.ingested == 1
        assert stats.skipped_earnings == 2
        assert stats.skipped_unknown == 0

    def test_ingest_excludes_unknown_type(self) -> None:
        # Given: 2 'other' type items + 1 dividend
        items = [
            _make_news_item(title="一般通知公告"),
            _make_news_item(title="普通披露"),
            _make_news_item(title="2025 年度利润分配方案"),
        ]
        pipeline = MagicMock()
        pipeline.fetch_all = MagicMock(return_value=items)
        conn = _make_mock_conn([1, 2, 3])

        processor = AnnouncementProcessor(pipeline=pipeline)
        stats = processor.ingest(
            symbol_id="600519",
            source="cninfo",
            conn=conn,
            limit=10,
        )

        # Then: only dividend ingested, 2 unknown skipped
        assert stats.fetched == 3
        assert stats.ingested == 1
        assert stats.skipped_earnings == 0
        assert stats.skipped_unknown == 2

    def test_ingest_empty_pipeline_returns_zero_stats(self) -> None:
        pipeline = MagicMock()
        pipeline.fetch_all = MagicMock(return_value=[])
        conn = _make_mock_conn([])

        processor = AnnouncementProcessor(pipeline=pipeline)
        stats = processor.ingest(
            symbol_id="600519",
            source="cninfo",
            conn=conn,
            limit=10,
        )

        assert stats == AnnouncementStats(
            fetched=0,
            ingested=0,
            skipped_earnings=0,
            skipped_unknown=0,
        )

        # 0 INSERT calls
        # MagicMock cursor() returns same instance per call, so execute count reflects 0 calls
        # check via call_args_list which should be empty-ish
        cur = conn.cursor()
        # cur was instantiated once at conn.cursor() call, but execute() was never called
        # Inspecting cur.execute call_count requires storing initial cursor mock — verify 0 calls
        # by checking no execute was triggered for empty fetch_all
        assert cur.execute.call_count == 0

    def test_ingest_unknown_source_raises_value_error(self) -> None:
        pipeline = MagicMock()
        processor = AnnouncementProcessor(pipeline=pipeline)
        conn = _make_mock_conn([])

        with pytest.raises(ValueError, match="Unknown announcement source"):
            processor.ingest(
                symbol_id="600519",
                source="invalid",
                conn=conn,
                limit=10,
            )

        # pipeline.fetch_all NOT called (route building fails before fetch)
        pipeline.fetch_all.assert_not_called()

    def test_ingest_dividend_inserts_with_correct_type(self) -> None:
        # Given: dividend item with content snippet
        items = [
            _make_news_item(
                title="2025 年权益分派实施公告",
                content="每 10 股派发现金红利 30 元",
            )
        ]
        pipeline = MagicMock()
        pipeline.fetch_all = MagicMock(return_value=items)
        conn = _make_mock_conn([42])

        processor = AnnouncementProcessor(pipeline=pipeline)
        stats = processor.ingest(
            symbol_id="600519",
            source="cninfo",
            conn=conn,
            limit=5,
        )

        assert stats.ingested == 1

        # Verify INSERT params include announcement_type=dividend
        execute_call_args = conn.cursor().execute.call_args
        params = execute_call_args[0][1]  # kwargs dict 2nd positional
        assert params["announcement_type"] == ANNOUNCEMENT_TYPE_DIVIDEND
        assert params["symbol_id"] == "600519"
        assert params["source"] == "cninfo"
        assert params["title"] == "2025 年权益分派实施公告"

    def test_ingest_truncates_content_snippet(self) -> None:
        # Given: very long content (defensive truncate to 1000 chars)
        long_content = "x" * 5000
        items = [_make_news_item(title="重大事项公告", content=long_content)]
        pipeline = MagicMock()
        pipeline.fetch_all = MagicMock(return_value=items)
        conn = _make_mock_conn([1])

        processor = AnnouncementProcessor(pipeline=pipeline)
        processor.ingest(symbol_id="600519", source="cninfo", conn=conn, limit=1)

        # Verify content_snippet truncated to 1000 char
        params = conn.cursor().execute.call_args[0][1]
        assert len(params["content_snippet"]) == 1000

    def test_ingest_handles_none_content(self) -> None:
        # Given: NewsItem with content=None (RSSHub feed without summary)
        items = [_make_news_item(title="股东大会通知", content=None)]
        pipeline = MagicMock()
        pipeline.fetch_all = MagicMock(return_value=items)
        conn = _make_mock_conn([1])

        processor = AnnouncementProcessor(pipeline=pipeline)
        stats = processor.ingest(symbol_id="600519", source="cninfo", conn=conn, limit=1)

        assert stats.ingested == 1
        params = conn.cursor().execute.call_args[0][1]
        assert params["content_snippet"] is None
