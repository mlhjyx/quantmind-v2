"""DataPipeline tests — V3 §3.1 6 源并行查询 + 早返回 + dedup (sub-PR 7a sediment).

Coverage:
- happy path (concurrent fetch + 全源命中 + dedup)
- fail-soft (per-source NewsFetchError → log + skip + 别源继续)
- 全源 fail (返空 list, 反 raise — V3§3.1 fail-soft sustained)
- 早返回 (≥ early_return_threshold 后停止等待剩余 future)
- dedup (URL match / title match / mixed / RSSHub None URL fallback)
- limit (limit_per_source + total_limit)
- 边界 (empty fetchers list / 0 timeout / 0 threshold / empty query)

沿用 sub-PR 1-6 体例 (mock NewsFetcher + NewsItem + NewsFetchError).
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.qm_platform.news import (
    DataPipeline,
    NewsFetcher,
    NewsFetchError,
    NewsItem,
)


def _make_item(
    source: str,
    title: str,
    *,
    url: str | None = None,
    timestamp: datetime | None = None,
) -> NewsItem:
    return NewsItem(
        source=source,
        timestamp=timestamp or datetime.now(tz=UTC),
        title=title,
        url=url,
        lang="zh",
        fetch_cost_usd=Decimal("0"),
        fetch_latency_ms=10,
    )


class _StubFetcher(NewsFetcher):
    """Configurable mock fetcher for testing."""

    def __init__(
        self,
        source_name: str,
        *,
        items: list[NewsItem] | None = None,
        raises: Exception | None = None,
        delay_s: float = 0.0,
    ):
        self.source_name = source_name
        self._items = items or []
        self._raises = raises
        self._delay_s = delay_s
        self.call_count = 0

    def fetch(self, *, query: str, limit: int = 10) -> list[NewsItem]:
        self.call_count += 1
        if self._delay_s:
            time.sleep(self._delay_s)
        if self._raises:
            raise self._raises
        return self._items[:limit]


# ---------- Constructor validation ----------


class TestConstructor:
    def test_empty_fetchers_raises(self):
        with pytest.raises(ValueError, match="empty"):
            DataPipeline([])

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="early_return_threshold"):
            DataPipeline([_StubFetcher("a")], early_return_threshold=0)

    def test_invalid_timeout_raises(self):
        with pytest.raises(ValueError, match="hard_timeout_s"):
            DataPipeline([_StubFetcher("a")], hard_timeout_s=0)

    def test_invalid_workers_raises(self):
        with pytest.raises(ValueError, match="max_workers"):
            DataPipeline([_StubFetcher("a")], max_workers=0)

    def test_valid_construction(self):
        pipeline = DataPipeline(
            [_StubFetcher("zhipu"), _StubFetcher("tavily")],
            max_workers=2,
            hard_timeout_s=10.0,
            early_return_threshold=2,
        )
        assert pipeline._max_workers == 2
        assert pipeline._hard_timeout_s == 10.0
        assert pipeline._early_return_threshold == 2


# ---------- fetch_all happy path ----------


class TestHappyPath:
    def test_single_fetcher_returns_items(self):
        items = [_make_item("zhipu", "title-1", url="http://a")]
        pipeline = DataPipeline(
            [_StubFetcher("zhipu", items=items)],
            early_return_threshold=1,
        )
        result = pipeline.fetch_all(query="test")
        assert len(result) == 1
        assert result[0].title == "title-1"
        assert result[0].source == "zhipu"

    def test_three_fetchers_all_hit(self):
        f1 = _StubFetcher(
            "zhipu", items=[_make_item("zhipu", "z1", url="http://z1")]
        )
        f2 = _StubFetcher(
            "tavily", items=[_make_item("tavily", "t1", url="http://t1")]
        )
        f3 = _StubFetcher(
            "anspire", items=[_make_item("anspire", "a1", url="http://a1")]
        )
        pipeline = DataPipeline([f1, f2, f3], early_return_threshold=3)
        result = pipeline.fetch_all(query="test")
        assert len(result) == 3
        sources = {item.source for item in result}
        assert sources == {"zhipu", "tavily", "anspire"}


# ---------- fail-soft ----------


class TestFailSoft:
    def test_one_fetcher_fails_others_succeed(self):
        f_ok = _StubFetcher(
            "zhipu", items=[_make_item("zhipu", "ok-1", url="http://ok")]
        )
        f_fail = _StubFetcher(
            "tavily",
            raises=NewsFetchError("tavily", "HTTP 500"),
        )
        f_ok2 = _StubFetcher(
            "anspire", items=[_make_item("anspire", "ok-2", url="http://ok2")]
        )
        pipeline = DataPipeline(
            [f_ok, f_fail, f_ok2], early_return_threshold=2
        )
        result = pipeline.fetch_all(query="test")
        # 2 ok + 1 fail (fail-soft) → 2 items
        assert len(result) == 2
        sources = {item.source for item in result}
        assert sources == {"zhipu", "anspire"}

    def test_all_fail_returns_empty(self):
        f1 = _StubFetcher(
            "zhipu", raises=NewsFetchError("zhipu", "rate limit")
        )
        f2 = _StubFetcher(
            "tavily", raises=NewsFetchError("tavily", "timeout")
        )
        pipeline = DataPipeline([f1, f2], early_return_threshold=1)
        result = pipeline.fetch_all(query="test")
        assert result == []


# ---------- early return ----------


class TestEarlyReturn:
    def test_early_return_after_threshold(self):
        # 5 fetchers, threshold=3 — 3 命中后早返回, 反等待 4+5
        f_fast = [
            _StubFetcher(
                f"src{i}",
                items=[_make_item(f"src{i}", f"item-{i}", url=f"http://s{i}")],
            )
            for i in range(3)
        ]
        # 4+5 真 slow (50ms 沿用 reasonable test 时间, 反阻 CI)
        f_slow = [
            _StubFetcher(
                f"slow{i}",
                items=[_make_item(f"slow{i}", f"slow-{i}", url=f"http://sl{i}")],
                delay_s=0.05,
            )
            for i in range(2)
        ]
        pipeline = DataPipeline(
            f_fast + f_slow,
            max_workers=5,
            early_return_threshold=3,
            hard_timeout_s=5.0,
        )
        t0 = time.perf_counter()
        result = pipeline.fetch_all(query="test")
        elapsed = time.perf_counter() - t0
        # 3 fast 命中早返回; slow 真在 ThreadPool 后台继续运行 (反 cancel),
        # but as_completed loop break 后 caller 真不再等. ThreadPool exit 沿用
        # context manager wait — real elapsed may ~0.05s due to slow worker
        # still draining. 真生产 caller 真已得 3 fast 结果.
        assert len(result) >= 3  # 至少 3 fast 命中
        # 反 hard timeout 全 30s 等待
        assert elapsed < 1.0


# ---------- dedup ----------


class TestDedup:
    def test_url_dedup(self):
        f1 = _StubFetcher(
            "zhipu", items=[_make_item("zhipu", "Title A", url="http://x")]
        )
        f2 = _StubFetcher(
            "tavily",
            items=[_make_item("tavily", "Title A different", url="http://x")],
        )
        pipeline = DataPipeline([f1, f2], early_return_threshold=2)
        result = pipeline.fetch_all(query="test")
        # 同 url → dedup 1 row 沿用 first occurrence
        assert len(result) == 1

    def test_title_dedup(self):
        # 同 title 跨源 (反 url) → dedup 1 row
        f1 = _StubFetcher(
            "zhipu", items=[_make_item("zhipu", "Same Title", url="http://a")]
        )
        f2 = _StubFetcher(
            "tavily",
            items=[_make_item("tavily", "Same Title", url="http://b")],
        )
        pipeline = DataPipeline([f1, f2], early_return_threshold=2)
        result = pipeline.fetch_all(query="test")
        assert len(result) == 1

    def test_title_normalization(self):
        # title 真 strip().lower() 走 dedup
        f1 = _StubFetcher(
            "zhipu", items=[_make_item("zhipu", "Same Title", url="http://a")]
        )
        f2 = _StubFetcher(
            "tavily",
            items=[_make_item("tavily", "  same title  ", url="http://b")],
        )
        pipeline = DataPipeline([f1, f2], early_return_threshold=2)
        result = pipeline.fetch_all(query="test")
        assert len(result) == 1

    def test_rsshub_none_url_title_fallback(self):
        # RSSHub 真 url 可能 None — title-only dedup
        f1 = _StubFetcher(
            "rsshub", items=[_make_item("rsshub", "RSS Title", url=None)]
        )
        f2 = _StubFetcher(
            "tavily",
            items=[_make_item("tavily", "RSS Title", url="http://t")],
        )
        pipeline = DataPipeline([f1, f2], early_return_threshold=2)
        result = pipeline.fetch_all(query="test")
        assert len(result) == 1

    def test_empty_title_skipped(self):
        # title empty 跳 (反 NewsItem 真预约 title required, 但 frozen=True
        # default 0 raise — pipeline 真 dedup 时跳)
        f1 = _StubFetcher(
            "zhipu",
            items=[
                _make_item("zhipu", "", url="http://a"),  # empty title 跳
                _make_item("zhipu", "valid title", url="http://b"),
            ],
        )
        pipeline = DataPipeline([f1], early_return_threshold=1)
        result = pipeline.fetch_all(query="test")
        assert len(result) == 1
        assert result[0].title == "valid title"


# ---------- limit ----------


class TestLimit:
    def test_limit_per_source_passed(self):
        items = [
            _make_item("zhipu", f"t-{i}", url=f"http://z{i}") for i in range(20)
        ]
        f = _StubFetcher("zhipu", items=items)
        pipeline = DataPipeline([f], early_return_threshold=1)
        result = pipeline.fetch_all(query="test", limit_per_source=5)
        assert len(result) == 5

    def test_total_limit_post_dedup(self):
        items_z = [
            _make_item("zhipu", f"t-{i}", url=f"http://z{i}") for i in range(10)
        ]
        items_t = [
            _make_item("tavily", f"t-{i}", url=f"http://t{i}") for i in range(10)
        ]
        f1 = _StubFetcher("zhipu", items=items_z)
        f2 = _StubFetcher("tavily", items=items_t)
        pipeline = DataPipeline([f1, f2], early_return_threshold=2)
        result = pipeline.fetch_all(
            query="test", limit_per_source=10, total_limit=15
        )
        # raw 20 → dedup (titles 重复 t-0~t-9 跨源) → 10 → total_limit=15 → 10
        # 真 sustained dedup 走 title (zhipu t-0 + tavily t-0 真 dedup)
        assert len(result) == 10


# ---------- query validation ----------


class TestQueryValidation:
    def test_empty_query_raises(self):
        f = _StubFetcher("zhipu")
        pipeline = DataPipeline([f])
        with pytest.raises(ValueError, match="empty"):
            pipeline.fetch_all(query="")

    def test_whitespace_query_raises(self):
        f = _StubFetcher("zhipu")
        pipeline = DataPipeline([f])
        with pytest.raises(ValueError, match="empty"):
            pipeline.fetch_all(query="   ")

    def test_each_fetcher_called_once(self):
        f1 = _StubFetcher("zhipu", items=[_make_item("zhipu", "z", url="http://z")])
        f2 = _StubFetcher("tavily", items=[_make_item("tavily", "t", url="http://t")])
        pipeline = DataPipeline([f1, f2], early_return_threshold=2)
        pipeline.fetch_all(query="test")
        assert f1.call_count == 1
        assert f2.call_count == 1


# ---------- timeout & unexpected exception (reviewer findings) ----------


class TestTimeout:
    def test_hard_timeout_returns_partial(self):
        # 1 fast fetcher 命中 + 1 slow fetcher 超时 (hard_timeout_s 触发)
        # threshold=3 反命中, 走 timeout path
        f_fast = _StubFetcher(
            "fast", items=[_make_item("fast", "fast-item", url="http://f")]
        )
        f_slow = _StubFetcher(
            "slow",
            items=[_make_item("slow", "slow-item", url="http://s")],
            delay_s=0.5,
        )
        pipeline = DataPipeline(
            [f_fast, f_slow],
            max_workers=2,
            hard_timeout_s=0.05,  # 50ms hard timeout
            early_return_threshold=3,  # 反命中, 强制走 timeout
        )
        result = pipeline.fetch_all(query="test")
        # 真 fast 命中, slow 真 timeout 漏 (沿用 V3§3.1 line 329 partial result)
        # ThreadPool exit 真等 slow 完成 (~0.5s), 真 caller 真已得 fast 结果
        assert any(item.source == "fast" for item in result)
        # 真 caller 真**收 partial result** (反 raise / 反 hang)
        assert isinstance(result, list)


class TestUnexpectedException:
    def test_unexpected_keyerror_fail_soft(self):
        # 反 NewsFetchError 别 exception (e.g. KeyError) 真 fail-soft, 沿用
        # 铁律 33-d (反 break 整 loop, sediment ADR-033 patch reviewer MEDIUM finding)
        f_ok = _StubFetcher(
            "zhipu", items=[_make_item("zhipu", "ok", url="http://ok")]
        )
        f_unexpected = _StubFetcher("tavily", raises=KeyError("unexpected key"))
        f_ok2 = _StubFetcher(
            "anspire", items=[_make_item("anspire", "ok2", url="http://ok2")]
        )
        pipeline = DataPipeline(
            [f_ok, f_unexpected, f_ok2], early_return_threshold=2
        )
        result = pipeline.fetch_all(query="test")
        # 2 ok + 1 unexpected (fail-soft) → 2 items
        assert len(result) == 2
        sources = {item.source for item in result}
        assert sources == {"zhipu", "anspire"}

    def test_unexpected_attribute_error_fail_soft(self):
        f_ok = _StubFetcher(
            "zhipu", items=[_make_item("zhipu", "ok", url="http://ok")]
        )
        f_attr = _StubFetcher(
            "tavily", raises=AttributeError("invalid attr")
        )
        pipeline = DataPipeline([f_ok, f_attr], early_return_threshold=1)
        result = pipeline.fetch_all(query="test")
        assert len(result) == 1
        assert result[0].source == "zhipu"
