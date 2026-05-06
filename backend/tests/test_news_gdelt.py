"""Test GDELT 2.0 News#4 fetcher (sub-PR 4, V3§3.1 全球事件 + 跨境 stream).

3 layer test sediment 沿用 sub-PR 1+2+3 体例:
- mock: HTTP layer mock via httpx.MockTransport (反网络, fast unit)
- e2e (requires_gdelt): 真 GDELT public API 走 minimal payload (0 API key, network only)
- smoke: 沿用 sub-PR 1+2+3 体例 (build/integration sanity)

GDELT-specific tests (反 sub-PR 1+2+3 体例):
- 0 API key 体例 (anonymous, 反 ValueError on empty key)
- GET method (沿用 sub-PR 3 Anspire 体例)
- `articles` wrapper (单 candidate, 反 sub-PR 3 多 candidate try)
- `seendate` YYYYMMDDTHHMMSSZ format (反 ISO 8601)
- `language` human-readable mapping (English→en, Chinese→zh)
- MAXRECORDS clamp [1, 250]
- 0 content field (ArtList mode 真值, 沿用 NewsItem.content=None)
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from backend.qm_platform.news import (
    GdeltNewsFetcher,
    NewsFetcher,
    NewsFetchError,
)
from backend.qm_platform.news.gdelt import (
    DEFAULT_BASE_URL,
    DEFAULT_FORMAT,
    DEFAULT_LANG,
    DEFAULT_MODE,
    DEFAULT_TIMESPAN,
    LANGUAGE_MAP,
    MAXRECORDS_MAX,
    MAXRECORDS_MIN,
    _GdeltRetryableError,
    _parse_seendate,
)

# ─────────────────────────── unit / mock ───────────────────────────


def test_gdelt_fetcher_no_api_key_required():
    """GDELT 0 API key (anonymous) — 反 sub-PR 1+2+3 ValueError on empty key 体例."""
    fetcher = GdeltNewsFetcher()
    assert fetcher.source_name == "gdelt"


def test_gdelt_fetcher_empty_query_raises():
    fetcher = GdeltNewsFetcher()
    with pytest.raises(ValueError, match="query is empty"):
        fetcher.fetch(query="   ")


def test_gdelt_fetcher_default_base_url():
    fetcher = GdeltNewsFetcher()
    assert fetcher._base_url == DEFAULT_BASE_URL.rstrip("/")
    assert fetcher._mode == DEFAULT_MODE == "ArtList"
    assert fetcher._timespan == DEFAULT_TIMESPAN == "1d"


def test_gdelt_fetcher_inherits_news_fetcher():
    fetcher = GdeltNewsFetcher()
    assert isinstance(fetcher, NewsFetcher)


def test_gdelt_default_format_is_json():
    fetcher = GdeltNewsFetcher()
    assert fetcher._format_or_default() == DEFAULT_FORMAT == "JSON"


def test_maxrecords_sediment():
    assert MAXRECORDS_MIN == 1
    assert MAXRECORDS_MAX == 250


def test_language_map_sediment():
    assert LANGUAGE_MAP["English"] == "en"
    assert LANGUAGE_MAP["Chinese"] == "zh"
    assert DEFAULT_LANG == "en"


# ─────────────────────────── seendate parse ───────────────────────────


def test_parse_seendate_gdelt_format():
    """YYYYMMDDTHHMMSSZ → datetime UTC (5-06 live verify 真值 format)."""
    ts = _parse_seendate("20260505T223000Z")
    assert ts.year == 2026
    assert ts.month == 5
    assert ts.day == 5
    assert ts.hour == 22
    assert ts.minute == 30
    assert ts.second == 0
    assert ts.tzinfo == UTC


def test_parse_seendate_iso8601_fallback():
    """ISO 8601 fallback (反 GDELT format) — sustained fromisoformat parse."""
    ts = _parse_seendate("2026-05-06T10:00:00+08:00")
    assert ts.tzinfo is not None
    assert ts.year == 2026


def test_parse_seendate_none_falls_back_to_now():
    ts = _parse_seendate(None)
    assert ts.tzinfo == UTC


def test_parse_seendate_empty_falls_back_to_now():
    ts = _parse_seendate("")
    assert ts.tzinfo == UTC


def test_parse_seendate_invalid_format_falls_back():
    ts = _parse_seendate("not-a-timestamp")
    assert ts.tzinfo == UTC


def test_parse_seendate_non_string_falls_back():
    ts = _parse_seendate(12345)  # type: ignore[arg-type]
    assert ts.tzinfo == UTC


def test_parse_seendate_invalid_gdelt_format_falls_back():
    """16 chars but invalid month/day → fallback to now()."""
    ts = _parse_seendate("20269999T999999Z")  # month 99
    assert ts.tzinfo == UTC


# ─────────────────────────── HTTP path ───────────────────────────


def test_gdelt_fetch_uses_get_method_with_no_auth_header(monkeypatch):
    """GDELT 真 GET method + 0 Authorization header (anonymous, 反 sub-PR 1+2+3)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth_header"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"articles": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    fetcher.fetch(query="Apple sourcelang:english", limit=10)
    assert captured["method"] == "GET"
    assert "QUERY=" in captured["url"]
    assert "MODE=ArtList" in captured["url"]
    assert "FORMAT=JSON" in captured["url"]
    assert "TIMESPAN=1d" in captured["url"]
    assert "MAXRECORDS=10" in captured["url"]
    assert captured["auth_header"] == ""  # 0 auth header (anonymous)


def test_gdelt_fetch_maxrecords_clamp_above_250(monkeypatch):
    """limit > 250 → MAXRECORDS=250 (clamp upper bound)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"articles": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    fetcher.fetch(query="test", limit=500)
    assert "MAXRECORDS=250" in captured["url"]


def test_gdelt_fetch_maxrecords_clamp_below_1(monkeypatch):
    """limit <= 0 → MAXRECORDS=1 (clamp lower bound)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"articles": []})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    fetcher.fetch(query="test", limit=0)
    assert "MAXRECORDS=1" in captured["url"]


def test_gdelt_fetch_parses_valid_response(monkeypatch):
    """mock httpx 走 GDELT live response schema → NewsItem list."""
    mock_api_resp = {
        "articles": [
            {
                "url": "https://9to5mac.com/article-1",
                "url_mobile": "",
                "title": "watchOS 26 added hypertension alerts",
                "seendate": "20260505T223000Z",
                "socialimage": "https://...",
                "domain": "9to5mac.com",
                "language": "English",
                "sourcecountry": "United States",
            },
            {
                "url": "https://example.cn/article-2",
                "title": "贵州茅台 Q1 财报",
                "seendate": "20260506T093000Z",
                "language": "Chinese",
                "sourcecountry": "China",
            },
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    items = fetcher.fetch(query="news", limit=5)

    assert len(items) == 2
    # 1st item: English source
    assert items[0].title.startswith("watchOS 26")
    assert items[0].source == "gdelt"
    assert items[0].lang == "en"
    assert items[0].url == "https://9to5mac.com/article-1"
    assert items[0].content is None  # GDELT ArtList 0 content field
    assert items[0].fetch_cost_usd == Decimal("0")
    assert items[0].fetch_latency_ms >= 0
    assert items[0].timestamp == datetime(2026, 5, 5, 22, 30, 0, tzinfo=UTC)
    # 2nd item: Chinese source
    assert items[1].lang == "zh"
    assert items[1].timestamp == datetime(2026, 5, 6, 9, 30, 0, tzinfo=UTC)


def test_gdelt_fetch_unknown_language_falls_back_to_default(monkeypatch):
    """language 反 LANGUAGE_MAP 候选 → fallback to DEFAULT_LANG ('en')."""
    mock_api_resp = {
        "articles": [
            {
                "url": "https://x",
                "title": "Test",
                "seendate": "20260505T223000Z",
                "language": "Klingon",  # 反 LANGUAGE_MAP
                "sourcecountry": "Vulcan",
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

    fetcher = GdeltNewsFetcher()
    items = fetcher.fetch(query="test")
    assert len(items) == 1
    assert items[0].lang == "en"  # DEFAULT_LANG fallback


def test_gdelt_fetch_4xx_400_raises_no_retry(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(400, text="bad query")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    with pytest.raises(NewsFetchError, match="HTTP 400"):
        fetcher.fetch(query="test")
    assert call_count["n"] == 1


def test_gdelt_fetch_429_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, text="rate limit")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch("backend.qm_platform.news.gdelt.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = GdeltNewsFetcher()
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_gdelt_fetch_5xx_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="server error")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch("backend.qm_platform.news.gdelt.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = GdeltNewsFetcher()
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_gdelt_fetch_timeout_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )
    with patch("backend.qm_platform.news.gdelt.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = GdeltNewsFetcher()
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="test")
    assert call_count["n"] == 3


def test_gdelt_fetch_missing_articles_returns_empty(monkeypatch):
    """`articles` wrapper missing → empty list (反 raise)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    items = fetcher.fetch(query="test")
    assert items == []


def test_gdelt_fetch_invalid_articles_type_returns_empty(monkeypatch):
    """`articles` 反 list type → empty list."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"articles": "not-a-list"})

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    items = fetcher.fetch(query="test")
    assert items == []


def test_gdelt_fetch_empty_title_skipped(monkeypatch):
    mock_api_resp = {
        "articles": [
            {"title": "", "url": "https://x", "seendate": "20260505T223000Z"},
            {"title": "Valid", "url": "https://y", "seendate": "20260505T223000Z"},
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_api_resp)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    items = fetcher.fetch(query="test")
    assert len(items) == 1
    assert items[0].title == "Valid"


def test_gdelt_fetch_html_response_returns_empty(monkeypatch):
    """GDELT 真返 HTML on某些 query → JSON parse fail → empty list (反 raise)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = GdeltNewsFetcher()
    items = fetcher.fetch(query="test")
    assert items == []


def test_gdelt_retryable_error_is_runtime_error():
    assert issubclass(_GdeltRetryableError, RuntimeError)


# ─────────────────────────── e2e / smoke ───────────────────────────


@pytest.mark.requires_gdelt
def test_gdelt_fetch_e2e_minimal_payload():
    """e2e: GDELT public API 走 minimal payload (0 API key, network reachability only).

    沿用 sub-PR 1+2+3 e2e 体例 (网络 不确定性接受 NewsFetchError).
    跑法: pytest -m requires_gdelt
    """
    fetcher = GdeltNewsFetcher()
    try:
        items = fetcher.fetch(query="Apple sourcelang:english", limit=2)
        assert isinstance(items, list)
        if items:
            assert items[0].source == "gdelt"
            assert items[0].fetch_latency_ms >= 0
    except NewsFetchError as e:
        # network / rate limit / parse failure 沿用 NewsFetchError fail-loud path
        assert e.source == "gdelt"
        assert "API call failed after retry" in str(e) or "HTTP" in str(e)


@pytest.mark.smoke
def test_gdelt_fetcher_import_smoke():
    """smoke: import + class instantiation sanity."""
    fetcher = GdeltNewsFetcher()
    assert fetcher.source_name == "gdelt"
    assert callable(fetcher.fetch)
    assert isinstance(fetcher, NewsFetcher)
