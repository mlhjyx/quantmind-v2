"""Test Marketaux News#5 fetcher (sub-PR 5, V3§3.1 金融信号 + sentiment 标签).

3 layer test sediment 沿用 sub-PR 1+2+3+4 体例:
- mock: HTTP layer mock via httpx.MockTransport (反网络, fast unit)
- e2e (requires_marketaux): 真 MARKETAUX_API_KEY .env 走 minimal payload
- smoke: 沿用 sub-PR 1+2+3+4 体例 (build/integration sanity)

Marketaux-specific tests (反 sub-PR 1+2+3+4 体例):
- `api_token` query param auth (反 Bearer header sub-PR 1+2+3)
- Custom User-Agent header required (Step 4-2 finding 沿用 sustained)
- `data` array wrapper (沿用 sub-PR 4 GDELT 单 wrapper 体例)
- `language` ISO code direct (反 GDELT human-readable mapping)
- `published_at` ISO 8601 microseconds + Z UTC parse
- description over snippet (snippet 含 cookie wall noise)
- LIMIT clamp [1, 100]
"""
from __future__ import annotations

import os
from datetime import UTC
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from backend.qm_platform.news import (
    MarketauxNewsFetcher,
    NewsFetcher,
    NewsFetchError,
)
from backend.qm_platform.news.marketaux import (
    DEFAULT_BASE_URL,
    DEFAULT_LANGUAGE,
    DEFAULT_USER_AGENT,
    LIMIT_MAX,
    LIMIT_MIN,
    _MarketauxRetryableError,
    _parse_published_at,
)

# ─────────────────────────── unit / mock ───────────────────────────


def test_marketaux_fetcher_empty_api_key_raises():
    """MARKETAUX_API_KEY 空 → 沿用铁律 33 fail-loud raise ValueError."""
    with pytest.raises(ValueError, match="MARKETAUX_API_KEY is empty"):
        MarketauxNewsFetcher(api_key="")


def test_marketaux_fetcher_empty_query_raises():
    fetcher = MarketauxNewsFetcher(api_key="test-key")
    with pytest.raises(ValueError, match="query is empty"):
        fetcher.fetch(query="   ")


def test_marketaux_fetcher_source_name():
    fetcher = MarketauxNewsFetcher(api_key="test-key")
    assert fetcher.source_name == "marketaux"


def test_marketaux_fetcher_default_base_url():
    fetcher = MarketauxNewsFetcher(api_key="test-key")
    assert fetcher._base_url == DEFAULT_BASE_URL.rstrip("/")
    assert fetcher._language == DEFAULT_LANGUAGE == "en"
    assert fetcher._user_agent == DEFAULT_USER_AGENT


def test_marketaux_fetcher_inherits_news_fetcher():
    fetcher = MarketauxNewsFetcher(api_key="test-key")
    assert isinstance(fetcher, NewsFetcher)


def test_marketaux_limit_sediment():
    assert LIMIT_MIN == 1
    assert LIMIT_MAX == 100


def test_marketaux_default_user_agent_sediment():
    """Step 4-2 finding sustained: default UA → Cloudflare 1010 block."""
    assert "QuantMind" in DEFAULT_USER_AGENT


# ─────────────────────────── timestamp parse ───────────────────────────


def test_parse_published_at_iso_microseconds_z():
    """Marketaux format: '2026-05-06T12:32:42.000000Z' → datetime UTC."""
    ts = _parse_published_at("2026-05-06T12:32:42.000000Z")
    assert ts.year == 2026
    assert ts.month == 5
    assert ts.day == 6
    assert ts.hour == 12
    assert ts.minute == 32
    assert ts.second == 42
    assert ts.tzinfo is not None


def test_parse_published_at_iso_no_microseconds():
    ts = _parse_published_at("2026-05-06T12:00:00Z")
    assert ts.tzinfo is not None
    assert ts.year == 2026


def test_parse_published_at_none_falls_back_to_now():
    ts = _parse_published_at(None)
    assert ts.tzinfo == UTC


def test_parse_published_at_empty_falls_back_to_now():
    ts = _parse_published_at("")
    assert ts.tzinfo == UTC


def test_parse_published_at_invalid_falls_back_to_now():
    ts = _parse_published_at("not-a-timestamp")
    assert ts.tzinfo == UTC


def test_parse_published_at_non_string_falls_back():
    ts = _parse_published_at(12345)  # type: ignore[arg-type]
    assert ts.tzinfo == UTC


# ─────────────────────────── HTTP path ───────────────────────────


def test_marketaux_fetch_uses_get_with_api_token_query_param(monkeypatch):
    """Marketaux 真 GET + `api_token` query param + 0 Authorization header
    (反 sub-PR 1+2+3 Bearer auth, 沿用 plugin extension)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth_header"] = request.headers.get("Authorization", "")
        captured["user_agent"] = request.headers.get("User-Agent", "")
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test-token-xxx")
    fetcher.fetch(query="Apple", limit=5)
    assert captured["method"] == "GET"
    assert "api_token=test-token-xxx" in captured["url"]
    assert "search=Apple" in captured["url"]
    assert "language=en" in captured["url"]
    assert "limit=5" in captured["url"]
    assert captured["auth_header"] == ""  # 0 Bearer header
    assert "QuantMind" in captured["user_agent"]  # custom UA Step 4-2 sediment


def test_marketaux_fetch_custom_user_agent_in_request(monkeypatch):
    """Custom UA 真生效 (反 default httpx UA → Cloudflare 1010)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["user_agent"] = request.headers.get("User-Agent", "")
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test", user_agent="Custom/2.0")
    fetcher.fetch(query="test")
    assert captured["user_agent"] == "Custom/2.0"


def test_marketaux_fetch_limit_clamp_above_100(monkeypatch):
    """limit > 100 → limit=100 (clamp upper bound)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    fetcher.fetch(query="test", limit=500)
    assert "limit=100" in captured["url"]


def test_marketaux_fetch_limit_clamp_below_1(monkeypatch):
    """limit <= 0 → limit=1 (clamp lower bound)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    fetcher.fetch(query="test", limit=0)
    assert "limit=1" in captured["url"]


def test_marketaux_fetch_parses_valid_response(monkeypatch):
    """mock httpx 走 Marketaux live response schema → NewsItem list."""
    mock_api_resp = {
        "meta": {"total": 2, "returned": 2, "limit": 10, "page": 1},
        "data": [
            {
                "uuid": "uuid-1",
                "title": "Apple Q1 2026 Earnings Beat Estimates",
                "description": "Apple reported strong Q1 results.",
                "snippet": "To ensure this doesn't happen, please enable...",
                "url": "https://example.com/apple-q1",
                "language": "en",
                "published_at": "2026-05-06T12:32:42.000000Z",
                "source": "example.com",
                "entities": [],
            },
            {
                "uuid": "uuid-2",
                "title": "贵州茅台 Q1 财报披露",
                "description": "营收增长 10%",
                "snippet": "",
                "url": "https://example.cn/茅台",
                "language": "zh",
                "published_at": "2026-05-06T09:00:00.000000Z",
                "source": "example.cn",
                "entities": [],
            },
        ],
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    items = fetcher.fetch(query="news", limit=5)

    assert len(items) == 2
    # 1st item: English source — description over snippet
    assert items[0].title.startswith("Apple Q1")
    assert items[0].source == "marketaux"
    assert items[0].lang == "en"
    assert items[0].url == "https://example.com/apple-q1"
    assert items[0].content == "Apple reported strong Q1 results."  # description preferred
    assert items[0].fetch_cost_usd == Decimal("0")
    assert items[0].fetch_latency_ms >= 0
    # 1st item timestamp parsed
    assert items[0].timestamp.year == 2026
    assert items[0].timestamp.month == 5
    assert items[0].timestamp.day == 6
    # 2nd item: Chinese source
    assert items[1].lang == "zh"


def test_marketaux_fetch_description_over_snippet(monkeypatch):
    """`description` 优先 over `snippet` (snippet 含 cookie wall noise)."""
    mock_api_resp = {
        "data": [
            {
                "title": "Test",
                "description": "real description",
                "snippet": "noise warning text",
                "url": "https://x",
                "language": "en",
                "published_at": "2026-05-06T12:00:00Z",
            }
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    items = fetcher.fetch(query="test")
    assert items[0].content == "real description"


def test_marketaux_fetch_snippet_fallback_when_description_empty(monkeypatch):
    """description 空时 fallback to snippet."""
    mock_api_resp = {
        "data": [
            {
                "title": "Test",
                "description": "",
                "snippet": "snippet content",
                "url": "https://x",
                "language": "en",
                "published_at": "2026-05-06T12:00:00Z",
            }
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    items = fetcher.fetch(query="test")
    assert items[0].content == "snippet content"


def test_marketaux_fetch_4xx_400_raises_no_retry(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(400, text="bad request")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    with pytest.raises(NewsFetchError, match="HTTP 400"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_marketaux_fetch_401_raises_no_retry(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, text="invalid api token")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="bad")
    with pytest.raises(NewsFetchError, match="HTTP 401"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_marketaux_fetch_429_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, text="rate limit")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch("backend.qm_platform.news.marketaux.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = MarketauxNewsFetcher(api_key="test")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_marketaux_fetch_5xx_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="server error")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch("backend.qm_platform.news.marketaux.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = MarketauxNewsFetcher(api_key="test")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_marketaux_fetch_timeout_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )
    with patch("backend.qm_platform.news.marketaux.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = MarketauxNewsFetcher(api_key="test")
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_marketaux_fetch_missing_data_returns_empty(monkeypatch):
    """`data` wrapper missing → empty list (反 raise)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"meta": {}})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    items = fetcher.fetch(query="test")
    assert items == []


def test_marketaux_fetch_invalid_data_type_returns_empty(monkeypatch):
    """`data` 反 list type → empty list."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": "not-a-list"})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    items = fetcher.fetch(query="test")
    assert items == []


def test_marketaux_fetch_empty_title_skipped(monkeypatch):
    mock_api_resp = {
        "data": [
            {"title": "", "url": "https://x", "published_at": "2026-05-06T12:00:00Z"},
            {"title": "Valid", "url": "https://y", "published_at": "2026-05-06T12:00:00Z"},
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    items = fetcher.fetch(query="test")
    assert len(items) == 1
    assert items[0].title == "Valid"


def test_marketaux_fetch_invalid_json_returns_empty(monkeypatch):
    """Invalid JSON response → empty list (反 raise)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test")
    items = fetcher.fetch(query="test")
    assert items == []


def test_marketaux_fetch_missing_language_uses_default(monkeypatch):
    """language field missing → fallback to fetcher.language (default 'en')."""
    mock_api_resp = {
        "data": [{"title": "Test", "url": "https://x", "published_at": "2026-05-06T12:00:00Z"}]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = MarketauxNewsFetcher(api_key="test", language="zh")
    items = fetcher.fetch(query="test")
    assert items[0].lang == "zh"  # fetcher default fallback


def test_marketaux_retryable_error_is_runtime_error():
    assert issubclass(_MarketauxRetryableError, RuntimeError)


# ─────────────────────────── e2e / smoke ───────────────────────────


@pytest.mark.requires_marketaux
@pytest.mark.skipif(
    not os.environ.get("MARKETAUX_API_KEY"),
    reason="requires MARKETAUX_API_KEY env (e2e live API call)"
)
def test_marketaux_fetch_e2e_minimal_payload():
    """e2e: 真 MARKETAUX_API_KEY 走 minimal 1-result payload (反耗 100/day quota).

    沿用 sub-PR 1+2+3+4 e2e 体例 (free tier quota 不确定性接受 NewsFetchError).
    跑法: MARKETAUX_API_KEY=xxx pytest -m requires_marketaux
    """
    api_key = os.environ["MARKETAUX_API_KEY"]
    fetcher = MarketauxNewsFetcher(api_key=api_key)
    try:
        items = fetcher.fetch(query="Apple", limit=1)
        assert isinstance(items, list)
        if items:
            assert items[0].source == "marketaux"
            assert items[0].lang in ("en", "zh", "fr", "de", "es", "ru", "ja", "ko")
            assert items[0].fetch_latency_ms >= 0
    except NewsFetchError as e:
        # 100/day quota / Cloudflare / network 沿用 NewsFetchError fail-loud path
        assert e.source == "marketaux"
        assert "API call failed after retry" in str(e) or "HTTP" in str(e)


@pytest.mark.smoke
def test_marketaux_fetcher_import_smoke():
    """smoke: import + class instantiation sanity."""
    fetcher = MarketauxNewsFetcher(api_key="dummy-for-smoke")
    assert fetcher.source_name == "marketaux"
    assert callable(fetcher.fetch)
    assert isinstance(fetcher, NewsFetcher)
