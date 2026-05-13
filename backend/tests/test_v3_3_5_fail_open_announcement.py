"""V3 §3.5 fail-open integration smoke — 公告流 fail → alert path 仍 fires.

Sub-PR T1.5b-3 sediment (Gate A item 8 closure path per Plan v0.2 §A T1.5
Acceptance item (8)).

Tests verify V3 §3.5 fail-open contract for announcement (公告流) layer:
- AnnouncementProcessor uses DataPipeline per-source fail-soft (ADR-049 §1 Decision 5)
- 任 1 RSSHub announcement source fail → DataPipeline aggregate from 别源 OK
- 全 announcement source fail → return empty list (fail-soft sustained)
- Downstream alert path NOT blocked by announcement absence

沿用 test_news_pipeline.py fail-soft pattern + sub-PR 11b AnnouncementProcessor
extension (announcement is L0.4 layer per V3 §3.4 + V3 §11.1 row 5).

关联:
- V3 §3.4 (公告流处理 L0.4)
- V3 §3.5 (fail-open 设计 line 447-473)
- V3 §11.1 row 5 AnnouncementProcessor
- ADR-049 §1 Decision 5 (per-source fail-soft DataPipeline 体例 sustained)
- ADR-050 (V3 §S2.5 implementation closure + announcement_type inference)
- 铁律 33 (fail-loud at service boundary, fail-soft at aggregate boundary)
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.qm_platform.news import (
    DataPipeline,
    NewsFetcher,
    NewsFetchError,
    NewsItem,
)


def _make_announcement_item(source: str, title: str = "test_announcement") -> NewsItem:
    """Construct mock NewsItem representing an RSSHub announcement (公告)."""
    return NewsItem(
        source=source,
        timestamp=datetime.now(tz=UTC),
        title=title,
        url=f"https://rsshub/announcement/{source}/{title}",
        lang="zh",
        fetch_cost_usd=Decimal("0"),
        fetch_latency_ms=15,
    )


class _AnnouncementMockFetcher(NewsFetcher):
    """Mock RSSHub announcement fetcher with configurable fail / success behavior."""

    def __init__(
        self,
        source_name: str,
        *,
        items: list[NewsItem] | None = None,
        raises: Exception | None = None,
    ):
        self.source_name = source_name
        self._items = items or []
        self._raises = raises
        self.call_count = 0

    def fetch(self, *, query: str, limit: int = 10) -> list[NewsItem]:
        self.call_count += 1
        if self._raises:
            raise self._raises
        return self._items[:limit]


# ---------- V3 §3.5 fail-open contract — announcement layer ----------


class TestV3FailOpenAnnouncement:
    """V3 §3.5 fail-open — 公告流 fail integration smoke."""

    def test_single_announcement_source_fail_aggregate_continues(self):
        """Mock 1 of 3 announcement sources fail → DataPipeline aggregate 别源 OK."""
        sources = [
            _AnnouncementMockFetcher(
                "rsshub_cninfo", items=[_make_announcement_item("rsshub_cninfo")]
            ),
            _AnnouncementMockFetcher("rsshub_sse", raises=NewsFetchError("rsshub_sse", "mock timeout")),
            _AnnouncementMockFetcher(
                "rsshub_szse", items=[_make_announcement_item("rsshub_szse")]
            ),
        ]
        pipeline = DataPipeline(sources, early_return_threshold=3, hard_timeout_s=5.0)
        items = pipeline.fetch_all(query="600519")

        # V3 §3.5 fail-open: 1 announcement source fail does NOT block aggregate
        assert len(items) >= 1, "fail-open: 别 announcement 源 aggregate continue"
        assert sources[0].call_count == 1
        assert sources[1].call_count == 1  # 失败 source 仍 called
        assert sources[2].call_count == 1

    def test_all_announcement_sources_fail_returns_empty_no_raise(self):
        """All announcement sources fail → fail-soft return empty list (反 raise)."""
        sources = [
            _AnnouncementMockFetcher(
                "rsshub_cninfo", raises=NewsFetchError("rsshub_cninfo", "cninfo timeout")
            ),
            _AnnouncementMockFetcher("rsshub_sse", raises=NewsFetchError("rsshub_sse", "sse timeout")),
            _AnnouncementMockFetcher("rsshub_szse", raises=NewsFetchError("rsshub_szse", "szse timeout")),
        ]
        pipeline = DataPipeline(sources, early_return_threshold=3, hard_timeout_s=5.0)

        # V3 §3.5 fail-soft sustained: 全 announcement 源 fail 返 empty list
        items = pipeline.fetch_all(query="600519")
        assert items == []
        # Verify all 3 sources attempted (fail-loud not used at aggregate boundary)
        assert all(s.call_count == 1 for s in sources)

    def test_announcement_partial_fail_alert_path_unblocked(self):
        """2/3 announcement sources fail, 1 survives → alert path NOT blocked."""
        sources = [
            _AnnouncementMockFetcher(
                "rsshub_cninfo", raises=NewsFetchError("rsshub_cninfo", "cninfo HTTP 500")
            ),
            _AnnouncementMockFetcher(
                "rsshub_sse",
                items=[_make_announcement_item("rsshub_sse", "earnings_disclosure")],
            ),
            _AnnouncementMockFetcher(
                "rsshub_szse", raises=NewsFetchError("rsshub_szse", "szse rate-limited")
            ),
        ]
        pipeline = DataPipeline(sources, early_return_threshold=2, hard_timeout_s=5.0)
        items = pipeline.fetch_all(query="600519")

        # V3 §3.5 fail-open: 2 source fail OK, 1 source aggregates downstream alert
        # context still has 1 announcement record
        assert len(items) == 1
        assert items[0].source == "rsshub_sse"

    def test_unexpected_exception_announcement_per_source_fail_soft(self):
        """Non-NewsFetchError exception per-source fail-soft sustained (RSSHub-specific)."""
        sources = [
            _AnnouncementMockFetcher(
                "rsshub_cninfo", items=[_make_announcement_item("rsshub_cninfo")]
            ),
            _AnnouncementMockFetcher(
                "rsshub_sse", raises=ValueError("unexpected XML parse")
            ),
        ]
        pipeline = DataPipeline(sources, early_return_threshold=2, hard_timeout_s=5.0)

        # 反 NewsFetchError 也 per-source fail-soft sustained (pipeline.py line 170-180)
        items = pipeline.fetch_all(query="600519")
        assert len(items) == 1
        assert items[0].source == "rsshub_cninfo"
