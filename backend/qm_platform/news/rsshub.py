"""RSSHub 自部署 News#6 fetcher (sub-PR 6, V3§3.1 中文财经 RSS 长尾).

独立 httpx client (沿用 sub-PR 1+2+3+4+5 plugin 体例 sustained, 反 LiteLLM router).
本地自部署 (沿用 Step 4-5 verify (c) Native Node.js + Servy host 体例 sustained).

RSSHub endpoint (5-06 Phase 0 install + Phase 1 fresh verify):
    GET http://localhost:1200/<route_path> (e.g. /eastmoney/news/0)
    Headers: 0 (anonymous, 沿用 sub-PR 4 GDELT 体例 sustained)
    Response: RSS 2.0 / Atom 1.0 XML feed (反 sub-PR 1+2+3+4+5 JSON 体例)

RSSHub-specific finding (5-06 Phase 1 fresh verify, 反 sub-PR 1+2+3+4+5 体例):
- **Self-hosted localhost:1200** (反 SaaS hosted, sub-PR 6 unique)
- **0 API key** (沿用 sub-PR 4 GDELT anonymous 体例)
- **GET method** (沿用 sub-PR 3+4+5 体例)
- **RSS XML response** (反 sub-PR 1+2+3+4+5 JSON wrapper 体例) — feedparser parser
- **route path 体例** (e.g. /eastmoney/news/0 / /jin10/news / /caixin/finance) —
  fetch() query 沿用 route path 体例 (反 search keyword sub-PR 1+2+3+5 体例)
- **lang="zh"** sustained (V3§3.1 中文财经源 ground truth)

Retry 体例 (沿用 sub-PR 1+2+3+4+5 tenacity 体例 sustained):
- stop_after_attempt(3) + wait_exponential(min=4, max=60)
- retry on httpx.TimeoutException + _RsshubRetryableError (429 + 5xx)
- 反 retry on 4xx 别 → fail-loud immediate raise NewsFetchError
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import feedparser
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base import NewsFetcher, NewsFetchError, NewsItem


class _RsshubRetryableError(RuntimeError):
    """Internal retryable error (429 rate limit + 5xx transient).

    沿用 sub-PR 1+2+3+4+5 RetryableError 体例.
    """


DEFAULT_BASE_URL = "http://localhost:1200"
DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 10
DEFAULT_USER_AGENT = "QuantMind-V2/1.0 (Python httpx)"  # 沿用 sub-PR 5 custom UA


class RsshubNewsFetcher(NewsFetcher):
    """RSSHub 自部署 News#6 fetcher (V3§3.1 中文财经 RSS 长尾).

    Args:
        base_url: RSSHub local host (默认 http://localhost:1200).
        timeout: HTTP timeout 秒 (默认 30s, 沿用 sub-PR 1+2+3+4+5 sustained).
        user_agent: User-Agent header 沿用 sub-PR 5 custom UA 体例 sustained.

    Note:
        fetch(query=...) 真**route path** (反 sub-PR 1+2+3+5 search keyword 体例),
        因为 RSSHub 真 route-driven (各 source 真 path-specific). 沿用 plugin 体例
        sustained — caller 真传 "/eastmoney/news/0" / "/jin10/news" / "/caixin/finance"
        等 route path string. 沿用 sub-PR 7 集成时 NewsClassifier 走 route path map
        体例 sediment (V3§3.1 6 源 fan-out 体例 sustained).

    Example:
        >>> fetcher = RsshubNewsFetcher()
        >>> items = fetcher.fetch(query="/eastmoney/news/0", limit=10)
        >>> for item in items:
        ...     print(item.title, item.timestamp, item.source)
    """

    source_name = "rsshub"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._user_agent = user_agent

    def fetch(self, *, query: str, limit: int = DEFAULT_LIMIT) -> list[NewsItem]:
        """Fetch news items via RSSHub local server (RSS XML feed).

        Args:
            query: RSSHub route path (e.g. "/eastmoney/news/0",
                "/jin10/news", "/caixin/finance"). 反 search keyword.
            limit: max results (反 server-side clamp — RSSHub 反 limit query param,
                client-side slice 沿用 base class 体例).

        Raises:
            ValueError: query empty (fail-loud).
            NewsFetchError: HTTP error / timeout / retry exhausted / RSS parse failure.
        """
        if not query.strip():
            raise ValueError("query is empty (沿用铁律 33 fail-loud)")

        # Normalize route path: strip leading/trailing slashes, prepend "/"
        route = "/" + query.strip().strip("/")

        t0 = time.perf_counter()
        try:
            xml_content = self._call_api(route=route)
        except NewsFetchError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError, _RsshubRetryableError) as e:
            raise NewsFetchError(
                source=self.source_name,
                message=f"API call failed after retry: {e}",
                cause=e,
            ) from e
        latency_ms = int((time.perf_counter() - t0) * 1000)

        items = self._parse_rss(xml_content, latency_ms=latency_ms)
        return items[:limit]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((httpx.TimeoutException, _RsshubRetryableError)),
        reraise=True,
    )
    def _call_api(self, *, route: str) -> str:
        """RSSHub local server call (GET method, retry-decorated).

        Returns RSS XML feed content (str). 4xx 别 → NewsFetchError fail-loud.
        """
        url = f"{self._base_url}{route}"
        headers = {"User-Agent": self._user_agent}

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url, headers=headers)

        if resp.status_code == 429 or resp.status_code >= 500:
            raise _RsshubRetryableError(
                f"HTTP {resp.status_code} (retryable: rate limit / 5xx): {resp.text[:200]}"
            )

        if resp.status_code >= 400:
            raise NewsFetchError(
                source=self.source_name,
                message=f"HTTP {resp.status_code} (non-retryable): {resp.text[:200]}",
            )

        return resp.text

    def _parse_rss(self, xml_content: str, *, latency_ms: int) -> list[NewsItem]:
        """Parse RSSHub RSS/Atom XML feed → list[NewsItem].

        feedparser handles:
        - RSS 2.0 (item.title / item.link / item.description / item.pubDate)
        - Atom 1.0 (entry.title / entry.link / entry.summary / entry.updated)
        - RDF 1.0 (反 主流 RSSHub format, 沿用 fallback)

        Empty list on parse failure (反 raise — content corruption shouldn't break caller).
        """
        if not xml_content or not xml_content.strip():
            return []

        try:
            feed = feedparser.parse(xml_content)
        except Exception:  # noqa: BLE001 — feedparser internal exceptions
            return []

        # feedparser bozo bit: malformed feed, but partial parse may still yield entries
        entries = getattr(feed, "entries", None) or []
        if not isinstance(entries, list):
            return []

        items: list[NewsItem] = []
        for entry in entries:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            ts = _parse_feed_timestamp(entry)
            content = entry.get("summary") or entry.get("description")
            url = entry.get("link") or None
            items.append(
                NewsItem(
                    source=self.source_name,
                    timestamp=ts,
                    title=title,
                    content=content,
                    url=url,
                    lang="zh",  # RSSHub 中文财经源 (V3§3.1 ground truth)
                    fetch_cost_usd=Decimal("0"),  # 自部署 0 cost (V3§3.1)
                    fetch_latency_ms=latency_ms,
                )
            )
        return items


def _parse_feed_timestamp(entry: dict) -> datetime:
    """Parse feedparser entry timestamp.

    Tries (in priority order):
    1. published_parsed (RSS pubDate, struct_time tuple)
    2. updated_parsed (Atom updated, struct_time tuple)
    3. published / updated (raw string ISO 8601 fallback)
    4. now() UTC fallback (沿用 sub-PR 2+3+4+5 体例)
    """
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st is not None:
            try:
                return datetime(*st[:6], tzinfo=UTC)
            except (ValueError, TypeError):
                continue

    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw and isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw)
            except (ValueError, TypeError):
                continue

    return datetime.now(tz=UTC)
