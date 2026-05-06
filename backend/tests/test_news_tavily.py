"""Test Tavily News#2 fetcher (sub-PR 2, V3§3.1 海外信号).

3 layer test sediment 沿用 sub-PR 1 体例:
- mock: HTTP layer mock via httpx.MockTransport (反网络, fast unit)
- e2e (requires_tavily): 真 TAVILY_API_KEY .env 走 minimal payload (反耗 credit)
- smoke: 沿用 sub-PR 1 体例 (build/integration sanity)
"""
from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from backend.qm_platform.news import (
    NewsFetcher,
    NewsFetchError,
    TavilyNewsFetcher,
)
from backend.qm_platform.news.tavily import (
    DEFAULT_BASE_URL,
    DEFAULT_SEARCH_DEPTH,
    DEFAULT_TOPIC,
    _parse_timestamp,
    _TavilyRetryableError,
)

# ─────────────────────────── unit / mock ───────────────────────────


def test_tavily_fetcher_empty_api_key_raises():
    """TAVILY_API_KEY 空 → 沿用铁律 33 fail-loud raise ValueError."""
    with pytest.raises(ValueError, match="TAVILY_API_KEY is empty"):
        TavilyNewsFetcher(api_key="")


def test_tavily_fetcher_empty_query_raises():
    """query 空 → 沿用铁律 33 fail-loud raise ValueError."""
    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    with pytest.raises(ValueError, match="query is empty"):
        fetcher.fetch(query="   ")


def test_tavily_fetcher_source_name():
    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    assert fetcher.source_name == "tavily"


def test_tavily_fetcher_default_base_url():
    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    assert fetcher._base_url == DEFAULT_BASE_URL.rstrip("/")
    assert fetcher._topic == DEFAULT_TOPIC == "news"
    assert fetcher._search_depth == DEFAULT_SEARCH_DEPTH == "basic"


def test_tavily_fetcher_custom_base_url_strips_trailing_slash():
    fetcher = TavilyNewsFetcher(api_key="tvly-test-key", base_url="https://x.test/")
    assert fetcher._base_url == "https://x.test"


def test_tavily_fetcher_inherits_news_fetcher():
    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    assert isinstance(fetcher, NewsFetcher)


def test_parse_timestamp_iso8601_with_tz():
    ts = _parse_timestamp("2026-05-06T10:00:00+08:00")
    assert ts.tzinfo is not None
    assert ts.year == 2026


def test_parse_timestamp_none_falls_back_to_now():
    """published_date 缺 (Tavily docs cite 反 standard schema field) → now() UTC fallback."""
    ts = _parse_timestamp(None)
    assert ts.tzinfo is not None  # UTC fallback


def test_parse_timestamp_empty_falls_back_to_now():
    ts = _parse_timestamp("")
    assert ts.tzinfo is not None


def test_parse_timestamp_invalid_falls_back_to_now():
    ts = _parse_timestamp("not-a-timestamp")
    assert ts.tzinfo is not None


def test_parse_timestamp_non_string_falls_back_to_now():
    """Tavily response 真携带 published_date 反 string type → fallback."""
    ts = _parse_timestamp(12345)  # type: ignore[arg-type]
    assert ts.tzinfo is not None


def test_tavily_fetch_parses_valid_response(monkeypatch):
    """mock httpx 走 valid Tavily Search API response → NewsItem list."""
    mock_api_resp = {
        "query": "Apple earnings",
        "results": [
            {
                "title": "Apple Reports Q1 2026 Earnings",
                "url": "https://example.com/apple-q1",
                "content": "Apple reported strong Q1 earnings...",
                "score": 0.95,
                "published_date": "2026-05-06T09:00:00+00:00",
            },
            {
                "title": "Apple Stock Up 3%",
                "url": "https://example.com/apple-stock",
                "content": "AAPL closed up...",
                "score": 0.88,
                # 0 published_date → now() UTC fallback
            },
        ],
        "response_time": 1.23,
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    items = fetcher.fetch(query="Apple earnings", limit=5)

    assert len(items) == 2
    assert items[0].title == "Apple Reports Q1 2026 Earnings"
    assert items[0].source == "tavily"
    assert items[0].lang == "en"
    assert items[0].url == "https://example.com/apple-q1"
    assert items[0].fetch_cost_usd == Decimal("0")  # 1000 credits/月永久免费
    assert items[0].fetch_latency_ms >= 0
    # 2nd item 0 published_date → now() UTC fallback (反 raise)
    assert items[1].timestamp.tzinfo is not None


def test_tavily_fetch_4xx_400_raises_news_fetch_error_no_retry(monkeypatch):
    """HTTP 400 invalid params → fail-loud immediate raise, 反 retry."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(400, text="invalid topic")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    with pytest.raises(NewsFetchError, match="HTTP 400"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_tavily_fetch_401_raises_news_fetch_error_no_retry(monkeypatch):
    """HTTP 401 invalid API key → fail-loud immediate raise, 反 retry."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, text="Unauthorized: missing or invalid API key")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-bad-key")
    with pytest.raises(NewsFetchError, match="HTTP 401"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_tavily_fetch_432_plan_limit_raises_no_retry(monkeypatch):
    """HTTP 432 plan usage limit → fail-loud, 反 retry (反触 limit cliff)."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(432, text="plan usage limit exceeded")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    with pytest.raises(NewsFetchError, match="HTTP 432.*plan/PAYG limit"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_tavily_fetch_433_payg_limit_raises_no_retry(monkeypatch):
    """HTTP 433 PAYG spending limit → fail-loud, 反 retry."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(433, text="PAYG spending limit exceeded")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    with pytest.raises(NewsFetchError, match="HTTP 433.*plan/PAYG limit"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_tavily_fetch_429_retries_then_raises(monkeypatch):
    """HTTP 429 rate limit → tenacity retry 3 次后 raise NewsFetchError."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, text="rate limit exceeded")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch("backend.qm_platform.news.tavily.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_tavily_fetch_5xx_retries_then_raises(monkeypatch):
    """HTTP 500 server error → tenacity retry 3 次."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(500, text="internal server error")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch("backend.qm_platform.news.tavily.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_tavily_fetch_missing_results_returns_empty(monkeypatch):
    """API response 缺 results → empty list (反 raise)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": "test"})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    items = fetcher.fetch(query="test")
    assert items == []


def test_tavily_fetch_invalid_results_type_returns_empty(monkeypatch):
    """results 反 list type → empty list."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": "not-a-list"})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    items = fetcher.fetch(query="test")
    assert items == []


def test_tavily_fetch_empty_title_skipped(monkeypatch):
    """results item 缺 title → 沿用 sub-PR 1 体例 skip (反 NewsItem create)."""
    mock_api_resp = {
        "results": [
            {"title": "", "url": "https://example.com/1", "content": "x"},
            {"title": "Valid Title", "url": "https://example.com/2", "content": "y"},
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    items = fetcher.fetch(query="test")
    assert len(items) == 1
    assert items[0].title == "Valid Title"


def test_tavily_fetch_timeout_retries_then_raises(monkeypatch):
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
    with patch("backend.qm_platform.news.tavily.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_tavily_retryable_error_is_runtime_error():
    """_TavilyRetryableError 沿用 RuntimeError (反 silent skip 4xx 别 retry)."""
    assert issubclass(_TavilyRetryableError, RuntimeError)


def test_tavily_fetch_max_results_clamp_above_20(monkeypatch):
    """Tavily max_results 范围 0-20 (官方 cite). limit > 20 走 clamp 20."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    fetcher.fetch(query="test", limit=100)
    assert captured["body"]["max_results"] == 20  # clamp


# ─────────────────────────── e2e / smoke ───────────────────────────


@pytest.mark.requires_tavily
@pytest.mark.skipif(
    not os.environ.get("TAVILY_API_KEY"),
    reason="requires TAVILY_API_KEY env (e2e live API call)"
)
def test_tavily_fetch_e2e_minimal_payload():
    """e2e: 真 TAVILY_API_KEY 走 minimal 1-credit payload (反耗 credit).

    沿用 sub-PR 1 ZhipuNewsFetcher e2e 体例 (free tier quota 不确定性接受 NewsFetchError).
    跑法: TAVILY_API_KEY=tvly-xxx pytest -m requires_tavily

    Tavily free tier 体例 (5-06 fresh verify):
    - 1000 credits/月永久免费 + 真返 results list ✅ (sub-PR 2 production path verify)
    - HTTP 432 plan limit / 433 PAYG limit / 429 rate limit → NewsFetchError fail-loud
    - 别 exception type → real bug fail-loud
    """
    api_key = os.environ["TAVILY_API_KEY"]
    fetcher = TavilyNewsFetcher(api_key=api_key)
    try:
        items = fetcher.fetch(query="Apple", limit=1)
        assert isinstance(items, list)
        if items:
            assert items[0].source == "tavily"
            assert items[0].lang == "en"
            assert items[0].fetch_latency_ms >= 0
    except NewsFetchError as e:
        # rate limit / plan limit / PAYG limit / quota cliff 沿用 NewsFetchError
        assert e.source == "tavily"
        assert "API call failed after retry" in str(e) or "HTTP" in str(e)


@pytest.mark.smoke
def test_tavily_fetcher_import_smoke():
    """smoke: import + class instantiation sanity (反 import error / dep miss)."""
    fetcher = TavilyNewsFetcher(api_key="dummy-for-smoke")
    assert fetcher.source_name == "tavily"
    assert callable(fetcher.fetch)
    assert isinstance(fetcher, NewsFetcher)


def test_tavily_news_item_uses_en_lang(monkeypatch):
    """Tavily NewsItem 默认 lang="en" (V3§3.1 海外信号体例)."""
    mock_api_resp = {
        "results": [{"title": "Test", "url": "https://x", "content": "y"}]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = TavilyNewsFetcher(api_key="tvly-test-key")
    items = fetcher.fetch(query="test")
    assert len(items) == 1
    assert items[0].lang == "en"
