"""Test Anspire 安思派 News#3 fetcher (sub-PR 3, V3§3.1 中文财经主源).

3 layer test sediment 沿用 sub-PR 1+2 体例:
- mock: HTTP layer mock via httpx.MockTransport (反网络, fast unit)
- e2e (requires_anspire): 真 ANSPIRE_API_KEY .env 走 minimal payload (反耗 quota)
- smoke: 沿用 sub-PR 1+2 体例 (build/integration sanity)

Anspire-specific tests (反 sub-PR 1+2 体例):
- GET method (反 POST) verify
- top_k enum clamp (10/20/30/40/50, 反 free integer)
- query 64 char hard limit (fail-loud raise)
- `date` field parse (反 Tavily 0 published_date)
- response 顶层 wrapper 多 candidate (data / results / items) try parse
"""
from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from backend.qm_platform.news import (
    AnspireNewsFetcher,
    NewsFetcher,
    NewsFetchError,
)
from backend.qm_platform.news.anspire import (
    DEFAULT_BASE_URL,
    DEFAULT_SEARCH_TYPE,
    QUERY_MAX_CHARS,
    TOP_K_ENUM,
    _AnspireRetryableError,
    _clamp_top_k,
    _parse_timestamp,
)

# ─────────────────────────── unit / mock ───────────────────────────


def test_anspire_fetcher_empty_api_key_raises():
    """ANSPIRE_API_KEY 空 → 沿用铁律 33 fail-loud raise ValueError."""
    with pytest.raises(ValueError, match="ANSPIRE_API_KEY is empty"):
        AnspireNewsFetcher(api_key="")


def test_anspire_fetcher_empty_query_raises():
    fetcher = AnspireNewsFetcher(api_key="sk-test")
    with pytest.raises(ValueError, match="query is empty"):
        fetcher.fetch(query="   ")


def test_anspire_fetcher_query_overflow_raises():
    """query > 64 chars → fail-loud (反 silent truncate, Anspire-specific 体例)."""
    fetcher = AnspireNewsFetcher(api_key="sk-test")
    long_query = "a" * 65  # 1 char over
    with pytest.raises(ValueError, match="exceeds 64 chars"):
        fetcher.fetch(query=long_query)


def test_anspire_fetcher_query_at_64_chars_passes(monkeypatch):
    """query == 64 chars → 沿用 fetch (反 raise, boundary)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    items = fetcher.fetch(query="a" * 64)  # boundary OK
    assert items == []


def test_anspire_fetcher_source_name():
    fetcher = AnspireNewsFetcher(api_key="sk-test")
    assert fetcher.source_name == "anspire"


def test_anspire_fetcher_default_base_url():
    fetcher = AnspireNewsFetcher(api_key="sk-test")
    assert fetcher._base_url == DEFAULT_BASE_URL.rstrip("/")
    assert fetcher._search_type == DEFAULT_SEARCH_TYPE == "web"


def test_anspire_fetcher_inherits_news_fetcher():
    fetcher = AnspireNewsFetcher(api_key="sk-test")
    assert isinstance(fetcher, NewsFetcher)


# ─────────────────────────── top_k clamp ───────────────────────────


def test_clamp_top_k_below_min_returns_10():
    assert _clamp_top_k(0) == 10
    assert _clamp_top_k(5) == 10
    assert _clamp_top_k(10) == 10


def test_clamp_top_k_above_max_returns_50():
    assert _clamp_top_k(100) == 50
    assert _clamp_top_k(50) == 50


def test_clamp_top_k_in_between_picks_nearest():
    assert _clamp_top_k(15) == 10  # closer to 10
    assert _clamp_top_k(16) == 20  # closer to 20
    assert _clamp_top_k(25) == 20  # closer to 20 (tie → first match)
    assert _clamp_top_k(35) == 30
    assert _clamp_top_k(45) == 40


def test_top_k_enum_sediment():
    assert TOP_K_ENUM == (10, 20, 30, 40, 50)


def test_query_max_chars_sediment():
    assert QUERY_MAX_CHARS == 64


# ─────────────────────────── timestamp parse ───────────────────────────


def test_parse_timestamp_iso8601_with_tz():
    ts = _parse_timestamp("2026-05-06T10:00:00+08:00")
    assert ts.tzinfo is not None
    assert ts.year == 2026


def test_parse_timestamp_none_falls_back_to_now():
    ts = _parse_timestamp(None)
    assert ts.tzinfo is not None  # UTC fallback


def test_parse_timestamp_empty_falls_back_to_now():
    ts = _parse_timestamp("")
    assert ts.tzinfo is not None


def test_parse_timestamp_invalid_falls_back_to_now():
    ts = _parse_timestamp("not-a-timestamp")
    assert ts.tzinfo is not None


def test_parse_timestamp_non_string_falls_back_to_now():
    ts = _parse_timestamp(12345)  # type: ignore[arg-type]
    assert ts.tzinfo is not None


# ─────────────────────────── HTTP path ───────────────────────────


def test_anspire_fetch_uses_get_method(monkeypatch):
    """Anspire 真 GET method (反 sub-PR 1+2 POST 体例) — verify request method."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    fetcher.fetch(query="贵州茅台", limit=10)
    assert captured["method"] == "GET"
    assert "query=" in captured["url"]
    assert "top_k=10" in captured["url"]
    assert "search_type=web" in captured["url"]


def test_anspire_fetch_top_k_clamp_in_request(monkeypatch):
    """limit=15 → top_k=10 (clamp-to-nearest, Anspire enum 体例)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    fetcher.fetch(query="test", limit=15)
    assert "top_k=10" in captured["url"]  # clamp 15 → 10


def test_anspire_fetch_parses_valid_response_with_date(monkeypatch):
    """mock httpx 走 valid response with `date` field → NewsItem list."""
    mock_api_resp = {
        "data": {
            "results": [
                {
                    "title": "贵州茅台 Q1 财报披露",
                    "url": "https://example.com/news/1",
                    "content": "营收 100 亿",
                    "score": 0.95,
                    "date": "2026-05-06T09:00:00+08:00",
                },
                {
                    "title": "茅台股价收涨",
                    "url": "https://example.com/news/2",
                    "content": "AAPL 收涨...",
                    "score": 0.88,
                    # 0 date → now() UTC fallback
                },
            ]
        }
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    items = fetcher.fetch(query="贵州茅台", limit=5)

    assert len(items) == 2
    assert items[0].title == "贵州茅台 Q1 财报披露"
    assert items[0].source == "anspire"
    assert items[0].lang == "zh"
    assert items[0].fetch_cost_usd == Decimal("0")
    assert items[0].fetch_latency_ms >= 0
    # 1st item has `date` → ISO parse
    assert items[0].timestamp.year == 2026
    # 2nd item 0 date → now() UTC fallback
    assert items[1].timestamp.tzinfo is not None


def test_anspire_fetch_response_wrapper_results(monkeypatch):
    """response 顶层 wrapper "results" (反 "data.results") sustained."""
    mock_api_resp = {"results": [{"title": "Test", "url": "https://x", "content": "y"}]}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    items = fetcher.fetch(query="test")
    assert len(items) == 1
    assert items[0].title == "Test"


def test_anspire_fetch_response_wrapper_items(monkeypatch):
    """response 顶层 wrapper "items" (反 "data" / "results") sustained."""
    mock_api_resp = {"items": [{"title": "Test", "url": "https://x"}]}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    items = fetcher.fetch(query="test")
    assert len(items) == 1


def test_anspire_fetch_4xx_400_raises_no_retry(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(400, text="invalid query")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    with pytest.raises(NewsFetchError, match="HTTP 400"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_anspire_fetch_4xx_401_raises_no_retry(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, text="invalid api key")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-bad")
    with pytest.raises(NewsFetchError, match="HTTP 401"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_anspire_fetch_429_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, text="rate limit")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch(
        "backend.qm_platform.news.anspire.wait_exponential", lambda **_: lambda *_: 0
    ):
        fetcher = AnspireNewsFetcher(api_key="sk-test")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_anspire_fetch_5xx_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(500, text="server error")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch(
        "backend.qm_platform.news.anspire.wait_exponential", lambda **_: lambda *_: 0
    ):
        fetcher = AnspireNewsFetcher(api_key="sk-test")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_anspire_fetch_timeout_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )
    with patch(
        "backend.qm_platform.news.anspire.wait_exponential", lambda **_: lambda *_: 0
    ):
        fetcher = AnspireNewsFetcher(api_key="sk-test")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_anspire_fetch_missing_results_returns_empty(monkeypatch):
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    items = fetcher.fetch(query="test")
    assert items == []


def test_anspire_fetch_empty_title_skipped(monkeypatch):
    mock_api_resp = {
        "results": [
            {"title": "", "url": "https://x"},
            {"title": "Valid", "url": "https://y"},
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    items = fetcher.fetch(query="test")
    assert len(items) == 1
    assert items[0].title == "Valid"


def test_anspire_retryable_error_is_runtime_error():
    assert issubclass(_AnspireRetryableError, RuntimeError)


def test_anspire_news_item_uses_zh_lang(monkeypatch):
    """Anspire NewsItem 默认 lang="zh" (V3§3.1 中文财经源体例)."""
    mock_api_resp = {"results": [{"title": "Test", "url": "https://x"}]}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = AnspireNewsFetcher(api_key="sk-test")
    items = fetcher.fetch(query="test")
    assert len(items) == 1
    assert items[0].lang == "zh"


# ─────────────────────────── e2e / smoke ───────────────────────────


@pytest.mark.requires_anspire
@pytest.mark.skipif(
    not os.environ.get("ANSPIRE_API_KEY"),
    reason="requires ANSPIRE_API_KEY env (e2e live API call)"
)
def test_anspire_fetch_e2e_minimal_payload():
    """e2e: 真 ANSPIRE_API_KEY 走 minimal payload (反耗 quota).

    沿用 sub-PR 1+2 e2e 体例 (free tier quota 不确定性接受 NewsFetchError).
    跑法: ANSPIRE_API_KEY=sk-xxx pytest -m requires_anspire
    """
    api_key = os.environ["ANSPIRE_API_KEY"]
    fetcher = AnspireNewsFetcher(api_key=api_key)
    try:
        items = fetcher.fetch(query="测试", limit=10)
        assert isinstance(items, list)
        if items:
            assert items[0].source == "anspire"
            assert items[0].lang == "zh"
            assert items[0].fetch_latency_ms >= 0
    except NewsFetchError as e:
        # rate limit / quota / network 沿用 NewsFetchError fail-loud path
        assert e.source == "anspire"
        assert "API call failed after retry" in str(e) or "HTTP" in str(e)


@pytest.mark.smoke
def test_anspire_fetcher_import_smoke():
    """smoke: import + class instantiation sanity."""
    fetcher = AnspireNewsFetcher(api_key="dummy-for-smoke")
    assert fetcher.source_name == "anspire"
    assert callable(fetcher.fetch)
    assert isinstance(fetcher, NewsFetcher)
