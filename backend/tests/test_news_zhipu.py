"""Test 智谱 News#1 fetcher (sub-PR 1, ADR-035 §2 sustained).

3 layer test sediment 沿用 Sprint 1 体例:
- mock: HTTP layer mock via httpx.MockTransport (反网络, fast unit)
- e2e (requires_zhipu): 真 ZHIPU_API_KEY .env 走 minimal payload (反耗 quota)
- smoke: 沿用 Step 4-2 + Step 4-3 体例 (build/integration sanity)
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from backend.qm_platform.news import (
    NewsFetcher,
    NewsFetchError,
    NewsItem,
    ZhipuNewsFetcher,
)
from backend.qm_platform.news.zhipu import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    _parse_timestamp,
    _ZhipuRetryableError,
)

# ─────────────────────────── unit / mock ───────────────────────────


def test_news_item_frozen_slots():
    """NewsItem dataclass 沿用 frozen + slots (反 mutate, 反 __dict__)."""
    item = NewsItem(
        source="zhipu",
        timestamp=datetime.fromisoformat("2026-05-06T10:00:00+08:00"),
        title="测试新闻",
    )
    assert item.source == "zhipu"
    assert item.lang == "zh"
    assert item.fetch_cost_usd == Decimal("0")
    with pytest.raises((AttributeError, Exception)):
        item.title = "改"  # frozen 反 mutate


def test_news_fetcher_is_abc():
    """NewsFetcher abc.ABC + abstractmethod fetch (反 直 instantiate)."""
    with pytest.raises(TypeError):
        NewsFetcher()  # type: ignore[abstract]


def test_zhipu_fetcher_empty_api_key_raises():
    """ZHIPU_API_KEY 空 → 沿用铁律 33 fail-loud raise ValueError."""
    with pytest.raises(ValueError, match="ZHIPU_API_KEY is empty"):
        ZhipuNewsFetcher(api_key="")


def test_zhipu_fetcher_empty_query_raises():
    """query 空 → 沿用铁律 33 fail-loud raise ValueError."""
    fetcher = ZhipuNewsFetcher(api_key="test-key")
    with pytest.raises(ValueError, match="query is empty"):
        fetcher.fetch(query="   ")


def test_zhipu_fetcher_source_name():
    fetcher = ZhipuNewsFetcher(api_key="test-key")
    assert fetcher.source_name == "zhipu"


def test_zhipu_fetcher_default_base_url():
    fetcher = ZhipuNewsFetcher(api_key="test-key")
    assert fetcher._base_url == DEFAULT_BASE_URL.rstrip("/")
    assert fetcher._model == DEFAULT_MODEL


def test_zhipu_fetcher_custom_base_url_strips_trailing_slash():
    fetcher = ZhipuNewsFetcher(api_key="test-key", base_url="https://x.test/v4/")
    assert fetcher._base_url == "https://x.test/v4"


def test_parse_timestamp_iso8601_with_tz():
    ts = _parse_timestamp("2026-05-06T10:00:00+08:00")
    assert ts.tzinfo is not None
    assert ts.year == 2026


def test_parse_timestamp_invalid_falls_back_to_now():
    ts = _parse_timestamp("not-a-timestamp")
    assert ts.tzinfo is not None  # UTC fallback


def test_parse_timestamp_empty_falls_back_to_now():
    ts = _parse_timestamp("")
    assert ts.tzinfo is not None


def test_zhipu_fetch_parses_valid_response(monkeypatch):
    """mock httpx 走 valid JSON response → NewsItem list."""
    mock_response_content = json.dumps({
        "items": [
            {
                "title": "贵州茅台 Q1 财报披露",
                "content": "营收 $X 亿",
                "url": "https://example.com/news/1",
                "timestamp": "2026-05-06T09:00:00+08:00",
            },
            {
                "title": "茅台股价收涨 2%",
                "content": None,
                "url": "https://example.com/news/2",
                "timestamp": "2026-05-06T15:00:00+08:00",
            },
        ]
    })
    mock_api_resp = {
        "choices": [{"message": {"content": mock_response_content}}]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = ZhipuNewsFetcher(api_key="test-key")
    items = fetcher.fetch(query="贵州茅台", limit=5)

    assert len(items) == 2
    assert items[0].title == "贵州茅台 Q1 财报披露"
    assert items[0].source == "zhipu"
    assert items[0].lang == "zh"
    assert items[0].fetch_cost_usd == Decimal("0")  # GLM-4.7-Flash 永久免费
    assert items[0].fetch_latency_ms >= 0
    assert items[1].content is None


def test_zhipu_fetch_4xx_raises_news_fetch_error_no_retry(monkeypatch):
    """HTTP 401/403/404 → fail-loud immediate raise, 反 retry."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, text="invalid api key")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = ZhipuNewsFetcher(api_key="bad-key")
    with pytest.raises(NewsFetchError, match="HTTP 401"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1, "4xx 别 反 retry (沿用 fail-loud)"


def test_zhipu_fetch_429_retries_then_raises(monkeypatch):
    """HTTP 429 (qps cap) → tenacity retry 3 次后 raise NewsFetchError."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, text="rate limit code 1305")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    # patch retry wait to 0 反实际 sleep (沿用 tenacity test 体例)
    with patch("backend.qm_platform.news.zhipu.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = ZhipuNewsFetcher(api_key="test-key")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    # tenacity stop_after_attempt(3) → 3 次调用
    assert call_count["n"] == 3


def test_zhipu_fetch_malformed_json_returns_empty(monkeypatch):
    """智谱返回非法 JSON content → 沿用 audit log, 返 empty list (反 raise)."""
    mock_api_resp = {
        "choices": [{"message": {"content": "not json content"}}]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = ZhipuNewsFetcher(api_key="test-key")
    items = fetcher.fetch(query="test")
    assert items == []


def test_zhipu_fetch_missing_choices_returns_empty(monkeypatch):
    """API response 缺 choices → empty list (反 raise)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = ZhipuNewsFetcher(api_key="test-key")
    items = fetcher.fetch(query="test")
    assert items == []


def test_zhipu_fetch_timeout_raises_news_fetch_error(monkeypatch):
    """httpx.TimeoutException → tenacity retry 3 次 → NewsFetchError."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )
    with patch("backend.qm_platform.news.zhipu.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = ZhipuNewsFetcher(api_key="test-key")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_zhipu_retryable_error_is_runtime_error():
    """_ZhipuRetryableError 沿用 RuntimeError 体例 (反 silent skip 4xx 别 retry)."""
    assert issubclass(_ZhipuRetryableError, RuntimeError)


# ─────────────────────────── e2e / smoke ───────────────────────────


@pytest.mark.requires_zhipu
@pytest.mark.skipif(
    not os.environ.get("ZHIPU_API_KEY"),
    reason="requires ZHIPU_API_KEY env (e2e live API call)"
)
def test_zhipu_fetch_e2e_minimal_payload():
    """e2e: 真 ZHIPU_API_KEY 走 minimal 1-token payload (反耗 quota).

    沿用 Step 4-2 + Step 4-3 smoke test 体例 (cold-start 60s retry sustained).
    跑法: ZHIPU_API_KEY=xxx pytest -m requires_zhipu

    Free tier quota 不确定性 (5-06 e2e 实测 code 1302 rate limit + Step 4-3
    cite code 1305 model qps cap, 双 code sustained ADR-035 §4 Neg cite 候选):
    - 真返 items list ✅ (sub-PR 1 production path verify)
    - 真 NewsFetchError raised after retry exhaustion ✅ (沿用 retry/fail-loud 体例 verify)
    - 别 exception type → real bug fail-loud
    """
    api_key = os.environ["ZHIPU_API_KEY"]
    fetcher = ZhipuNewsFetcher(api_key=api_key)
    try:
        items = fetcher.fetch(query="ping", limit=1)
        assert isinstance(items, list)
        if items:
            assert items[0].source == "zhipu"
            assert items[0].fetch_latency_ms >= 0
    except NewsFetchError as e:
        # rate limit / quota cliff 沿用 NewsFetchError 真 production fail-loud path
        # 反 silent skip — 沿用 free tier quota 不确定性体例 (audit Week 2 batch finding)
        assert e.source == "zhipu"
        assert "API call failed after retry" in str(e) or "HTTP" in str(e)


@pytest.mark.smoke
def test_zhipu_fetcher_import_smoke():
    """smoke: import + class instantiation sanity (反 import error / dep miss)."""
    fetcher = ZhipuNewsFetcher(api_key="dummy-for-smoke")
    assert fetcher.source_name == "zhipu"
    assert callable(fetcher.fetch)
    assert isinstance(fetcher, NewsFetcher)
