"""Test RSSHub 自部署 News#6 fetcher (sub-PR 6, V3§3.1 中文财经 RSS 长尾).

3 layer test sediment 沿用 sub-PR 1+2+3+4+5 体例:
- mock: HTTP layer mock via httpx.MockTransport (反网络, fast unit) + RSS XML fixture
- e2e (requires_rsshub): 真 RSSHub localhost:1200 走 minimal route (network only)
- smoke: 沿用 sub-PR 1+2+3+4+5 体例 (build/integration sanity)

RSSHub-specific tests (反 sub-PR 1+2+3+4+5 体例):
- Self-hosted localhost:1200 (反 SaaS endpoint)
- 0 API key (沿用 sub-PR 4 GDELT)
- GET method (沿用 sub-PR 3+4+5)
- RSS XML response (反 JSON wrapper) — feedparser parser
- route path query (e.g. /eastmoney/news/0, 反 search keyword)
- lang="zh" sustained (V3§3.1 中文财经源)
"""
from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from backend.qm_platform.news import (
    NewsFetcher,
    NewsFetchError,
    RsshubNewsFetcher,
)
from backend.qm_platform.news.rsshub import (
    DEFAULT_BASE_URL,
    DEFAULT_USER_AGENT,
    _parse_feed_timestamp,
    _RsshubRetryableError,
)

# ─────────────────────────── unit / mock ───────────────────────────


SAMPLE_RSS_2_0 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>东方财富新闻</title>
    <link>https://www.eastmoney.com</link>
    <description>东方财富新闻 RSSHub feed</description>
    <item>
      <title>贵州茅台 Q1 财报披露</title>
      <link>https://www.eastmoney.com/a/202605061234.html</link>
      <description>营收增长 10%</description>
      <pubDate>Tue, 06 May 2026 12:00:00 +0000</pubDate>
    </item>
    <item>
      <title>A 股盘中震荡</title>
      <link>https://www.eastmoney.com/a/202605061235.html</link>
      <description>沪指收涨 0.5%</description>
      <pubDate>Tue, 06 May 2026 14:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""

SAMPLE_ATOM_1_0 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>金十财经</title>
  <link href="https://www.jin10.com"/>
  <updated>2026-05-06T12:00:00Z</updated>
  <entry>
    <title>美联储利率决议</title>
    <link href="https://www.jin10.com/news/123"/>
    <updated>2026-05-06T12:30:00Z</updated>
    <summary>降息 25 个基点</summary>
  </entry>
</feed>"""


def test_rsshub_fetcher_no_api_key_required():
    """RSSHub 0 API key (anonymous, 沿用 sub-PR 4 GDELT)."""
    fetcher = RsshubNewsFetcher()
    assert fetcher.source_name == "rsshub"


def test_rsshub_fetcher_empty_query_raises():
    fetcher = RsshubNewsFetcher()
    with pytest.raises(ValueError, match="query is empty"):
        fetcher.fetch(query="   ")


def test_rsshub_fetcher_default_base_url():
    fetcher = RsshubNewsFetcher()
    assert fetcher._base_url == DEFAULT_BASE_URL.rstrip("/") == "http://localhost:1200"
    assert fetcher._user_agent == DEFAULT_USER_AGENT


def test_rsshub_fetcher_custom_base_url():
    fetcher = RsshubNewsFetcher(base_url="http://192.168.1.10:1200/")
    assert fetcher._base_url == "http://192.168.1.10:1200"


def test_rsshub_fetcher_inherits_news_fetcher():
    fetcher = RsshubNewsFetcher()
    assert isinstance(fetcher, NewsFetcher)


# ─────────────────────────── route path normalize ───────────────────────────


def test_rsshub_fetch_route_path_with_leading_slash(monkeypatch):
    """query='/eastmoney/news/0' → URL: http://localhost:1200/eastmoney/news/0"""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text=SAMPLE_RSS_2_0)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    fetcher.fetch(query="/eastmoney/news/0", limit=10)
    assert captured["url"] == "http://localhost:1200/eastmoney/news/0"


def test_rsshub_fetch_route_path_no_leading_slash(monkeypatch):
    """query='eastmoney/news/0' → URL prepends '/'"""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text=SAMPLE_RSS_2_0)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    fetcher.fetch(query="eastmoney/news/0", limit=10)
    assert captured["url"] == "http://localhost:1200/eastmoney/news/0"


def test_rsshub_fetch_uses_get_method_with_custom_ua(monkeypatch):
    """GET method + custom UA, 0 Authorization header (沿用 sub-PR 4 体例)."""
    captured: dict = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["auth_header"] = request.headers.get("Authorization", "")
        captured["user_agent"] = request.headers.get("User-Agent", "")
        return httpx.Response(200, text=SAMPLE_RSS_2_0)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    fetcher.fetch(query="/eastmoney/news/0")
    assert captured["method"] == "GET"
    assert captured["auth_header"] == ""  # anonymous
    assert "QuantMind" in captured["user_agent"]  # custom UA


# ─────────────────────────── RSS / Atom parse ───────────────────────────


def test_rsshub_fetch_parses_rss_2_0(monkeypatch):
    """RSS 2.0 feed → NewsItem list (item.title / item.link / item.pubDate)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_RSS_2_0)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    items = fetcher.fetch(query="/eastmoney/news/0", limit=10)

    assert len(items) == 2
    assert items[0].title == "贵州茅台 Q1 财报披露"
    assert items[0].source == "rsshub"
    assert items[0].lang == "zh"
    assert items[0].url == "https://www.eastmoney.com/a/202605061234.html"
    assert items[0].content == "营收增长 10%"
    assert items[0].fetch_cost_usd == Decimal("0")
    assert items[0].fetch_latency_ms >= 0
    # pubDate "Tue, 06 May 2026 12:00:00 +0000" → datetime(2026, 5, 6, 12, ...)
    assert items[0].timestamp.year == 2026
    assert items[0].timestamp.month == 5


def test_rsshub_fetch_parses_atom_1_0(monkeypatch):
    """Atom 1.0 feed → NewsItem list (entry.title / entry.link / entry.updated)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_ATOM_1_0)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    items = fetcher.fetch(query="/jin10/news", limit=10)

    assert len(items) == 1
    assert items[0].title == "美联储利率决议"
    assert items[0].lang == "zh"


def test_rsshub_fetch_limit_slice(monkeypatch):
    """limit=1 → only 1 item returned (client-side slice, RSSHub 反 limit query)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_RSS_2_0)  # 2 items

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    items = fetcher.fetch(query="/eastmoney/news/0", limit=1)
    assert len(items) == 1


def test_rsshub_fetch_empty_xml_returns_empty(monkeypatch):
    """Empty XML response → empty list (反 raise)."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    items = fetcher.fetch(query="/eastmoney/news/0")
    assert items == []


def test_rsshub_fetch_malformed_xml_returns_empty(monkeypatch):
    """Malformed XML → feedparser bozo + 0 entries → empty list."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<not-rss>not valid</not-rss>")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    items = fetcher.fetch(query="/eastmoney/news/0")
    assert items == []


def test_rsshub_fetch_empty_title_skipped(monkeypatch):
    """RSS item 缺 title → skip (沿用 sub-PR 1-5 体例)."""
    rss_with_empty = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title></title><link>https://x</link><description>x</description></item>
<item><title>Valid</title><link>https://y</link><description>y</description></item>
</channel></rss>"""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=rss_with_empty)

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    items = fetcher.fetch(query="/x")
    assert len(items) == 1
    assert items[0].title == "Valid"


# ─────────────────────────── HTTP error handling ───────────────────────────


def test_rsshub_fetch_4xx_404_raises_no_retry(monkeypatch):
    """HTTP 404 (route not found) → fail-loud, 反 retry."""
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404, text="route not found")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    fetcher = RsshubNewsFetcher()
    with pytest.raises(NewsFetchError, match="HTTP 404"):
        fetcher.fetch(query="/nonexistent")
    assert call_count["n"] == 1


def test_rsshub_fetch_429_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, text="rate limit")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch("backend.qm_platform.news.rsshub.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = RsshubNewsFetcher()
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="/eastmoney/news/0")
    assert call_count["n"] == 3


def test_rsshub_fetch_5xx_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="server error")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    with patch("backend.qm_platform.news.rsshub.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = RsshubNewsFetcher()
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="/eastmoney/news/0")
    assert call_count["n"] == 3


def test_rsshub_fetch_timeout_retries_then_raises(monkeypatch):
    call_count = {"n": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(mock_handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )
    with patch("backend.qm_platform.news.rsshub.wait_exponential", lambda **_: lambda *_: 0):
        fetcher = RsshubNewsFetcher()
        with pytest.raises(NewsFetchError, match="API call failed after retry"):
            fetcher.fetch(query="/eastmoney/news/0")
    assert call_count["n"] == 3


def test_rsshub_retryable_error_is_runtime_error():
    assert issubclass(_RsshubRetryableError, RuntimeError)


# ─────────────────────────── timestamp parse ───────────────────────────


def test_parse_feed_timestamp_published_parsed():
    """RSS pubDate → struct_time → datetime UTC."""
    import time
    entry = {"published_parsed": time.struct_time((2026, 5, 6, 12, 30, 0, 0, 0, 0))}
    ts = _parse_feed_timestamp(entry)  # type: ignore[arg-type]
    assert ts.year == 2026
    assert ts.month == 5
    assert ts.day == 6
    assert ts.tzinfo == UTC


def test_parse_feed_timestamp_updated_parsed_fallback():
    """published_parsed missing → updated_parsed fallback."""
    import time
    entry = {"updated_parsed": time.struct_time((2026, 5, 6, 12, 0, 0, 0, 0, 0))}
    ts = _parse_feed_timestamp(entry)  # type: ignore[arg-type]
    assert ts.year == 2026


def test_parse_feed_timestamp_published_string_fallback():
    """published string (no parsed struct) → fromisoformat fallback."""
    entry = {"published": "2026-05-06T12:00:00+00:00"}
    ts = _parse_feed_timestamp(entry)  # type: ignore[arg-type]
    assert ts.year == 2026


def test_parse_feed_timestamp_no_timestamps_falls_back_to_now():
    """0 timestamp fields → now() UTC fallback."""
    ts = _parse_feed_timestamp({})  # type: ignore[arg-type]
    assert ts.tzinfo == UTC


# ─────────────────────────── e2e / smoke ───────────────────────────


@pytest.mark.requires_rsshub
def test_rsshub_fetch_e2e_eastmoney():
    """e2e: 真 RSSHub localhost:1200/eastmoney/news/0 (Servy register service ready).

    跑法: pytest -m requires_rsshub (requires RSSHub Servy service running)
    """
    fetcher = RsshubNewsFetcher()
    try:
        items = fetcher.fetch(query="/eastmoney/news/0", limit=2)
        assert isinstance(items, list)
        if items:
            assert items[0].source == "rsshub"
            assert items[0].lang == "zh"
            assert items[0].fetch_latency_ms >= 0
    except NewsFetchError as e:
        # Server unreachable / route not found / 别 沿用 NewsFetchError fail-loud
        assert e.source == "rsshub"
        assert "API call failed after retry" in str(e) or "HTTP" in str(e)


@pytest.mark.smoke
def test_rsshub_fetcher_import_smoke():
    """smoke: import + class instantiation sanity."""
    fetcher = RsshubNewsFetcher()
    assert fetcher.source_name == "rsshub"
    assert callable(fetcher.fetch)
    assert isinstance(fetcher, NewsFetcher)
