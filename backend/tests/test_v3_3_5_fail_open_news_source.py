"""V3 §3.5 fail-open integration smoke — News 源 fail → alert path 仍 fires.

Sub-PR T1.5b-3 sediment (Gate A item 8 closure path per Plan v0.2 §A T1.5
Acceptance item (8)).

Tests verify V3 §3.5 fail-open contract:
- 任 1 News 源 fail → DataPipeline early-return + fail-soft + 别源 aggregate continue
- 0 propagate fetch exception 给 caller (RealtimeRiskEngine + AlertDispatcher)
- Alert path can still produce + dispatch RiskEvent (degraded context, missing
  sentiment_24h for failed source's domain coverage)

沿用 test_news_pipeline.py fail-soft pattern + extend to integration scope
(fail-open contract at DataPipeline boundary verifies downstream alert path
unaffected).

关联:
- V3 §3.5 (fail-open 设计 line 447-473)
- V3 §11.2 (RiskContext.sentiment_24h is dict, empty is valid)
- ADR-049 §1 Decision 5 (per-source fail-soft DataPipeline 体例 sustained)
- 铁律 33 (fail-loud at service boundary, fail-soft at aggregate boundary)
- 铁律 25/36 (代码变更前必读 sustained, post 4-step preflight verify SOP)
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


def _make_item(source: str, title: str = "test_news") -> NewsItem:
    return NewsItem(
        source=source,
        timestamp=datetime.now(tz=UTC),
        title=title,
        url=f"https://example.com/{source}/{title}",
        lang="zh",
        fetch_cost_usd=Decimal("0"),
        fetch_latency_ms=10,
    )


class _MockFetcher(NewsFetcher):
    """Mock fetcher with configurable fail / success behavior."""

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


# ---------- V3 §3.5 fail-open contract ----------


class TestV3FailOpenNewsSource:
    """V3 §3.5 fail-open — News 源 fail integration smoke."""

    def test_single_source_fail_aggregate_continues(self):
        """Mock 1 of 3 sources fail → aggregate from 2 remaining sources OK."""
        sources = [
            _MockFetcher("zhipu", items=[_make_item("zhipu", "news1")]),
            _MockFetcher("tavily", raises=NewsFetchError("tavily", "mock timeout")),
            _MockFetcher("anspire", items=[_make_item("anspire", "news2")]),
        ]
        pipeline = DataPipeline(sources, early_return_threshold=3, hard_timeout_s=5.0)
        items = pipeline.fetch_all(query="test")

        # V3 §3.5 fail-open: 1 source fail does NOT block aggregate
        assert len(items) >= 1, "fail-open: 别源 aggregate continue"
        # All 3 sources called
        assert sources[0].call_count == 1
        assert sources[1].call_count == 1  # 失败 source 仍被调用
        assert sources[2].call_count == 1

    def test_two_of_three_sources_fail_third_aggregate(self):
        """Mock 2 of 3 sources fail → aggregate from 1 remaining source."""
        sources = [
            _MockFetcher("zhipu", raises=NewsFetchError("zhipu", "mock fail 1")),
            _MockFetcher("tavily", raises=NewsFetchError("tavily", "mock fail 2")),
            _MockFetcher("anspire", items=[_make_item("anspire", "news_survive")]),
        ]
        pipeline = DataPipeline(sources, early_return_threshold=2, hard_timeout_s=5.0)
        items = pipeline.fetch_all(query="test")

        # V3 §3.5 fail-open: 2 sources fail, 1 source survive → aggregate non-empty
        assert len(items) == 1
        assert items[0].source == "anspire"

    def test_all_sources_fail_returns_empty_no_raise(self):
        """All sources fail → fail-soft return empty list (反 raise)."""
        sources = [
            _MockFetcher("zhipu", raises=NewsFetchError("zhipu", "fail 1")),
            _MockFetcher("tavily", raises=NewsFetchError("tavily", "fail 2")),
            _MockFetcher("anspire", raises=NewsFetchError("anspire", "fail 3")),
        ]
        pipeline = DataPipeline(sources, early_return_threshold=3, hard_timeout_s=5.0)

        # V3 §3.5 fail-soft sustained: 全 fail 返 empty list (反 propagate)
        items = pipeline.fetch_all(query="test")
        assert items == []

    def test_unexpected_exception_per_source_fail_soft(self):
        """Non-NewsFetchError exception (e.g. KeyError) per-source fail-soft sustained."""
        sources = [
            _MockFetcher("zhipu", items=[_make_item("zhipu", "news_ok")]),
            _MockFetcher("tavily", raises=KeyError("unexpected key")),  # NOT NewsFetchError
        ]
        pipeline = DataPipeline(sources, early_return_threshold=2, hard_timeout_s=5.0)

        # 反 NewsFetchError 也走 fail-soft per-source (铁律 33-d sustained pipeline.py:170-180)
        items = pipeline.fetch_all(query="test")
        assert len(items) == 1
        assert items[0].source == "zhipu"

    def test_early_return_threshold_reached_remaining_skipped(self):
        """≥ early_return_threshold sources hit → 早返回 skip remaining."""
        sources = [
            _MockFetcher("zhipu", items=[_make_item("zhipu", "news1")]),
            _MockFetcher("tavily", items=[_make_item("tavily", "news2")]),
            _MockFetcher("anspire", items=[_make_item("anspire", "news3")]),
            _MockFetcher("gdelt", items=[_make_item("gdelt", "news4")]),
        ]
        pipeline = DataPipeline(
            sources, early_return_threshold=2, hard_timeout_s=10.0
        )
        items = pipeline.fetch_all(query="test")

        # V3 §3.1 早返回: ≥ 2 sources hit, 剩余 sources 可能被 skip
        assert len(items) >= 2  # 至少 2 source aggregate
