"""Marketaux News#5 fetcher (sub-PR 5, V3§3.1 金融信号 + sentiment 标签).

独立 httpx client (沿用 sub-PR 1+2+3+4 plugin 体例 sustained, 反 LiteLLM router).

Marketaux endpoint (5-06 Phase 1 fresh verify, live HTTP 200 verified):
    GET https://api.marketaux.com/v1/news/all
    Query: api_token (反 Bearer header) + language + limit + 别 filters
    Headers: User-Agent: QuantMind-V2/1.0 (反 default UA → Cloudflare 1010 block)

Marketaux-specific finding (5-06 Phase 1 fresh verify, 反 sub-PR 1+2+3+4 体例):
- **`api_token` query param auth** (反 Bearer header sub-PR 1+2+3)
- **Custom UA header required** (Step 4-2 finding sustained: default UA → 1010 block)
- **`data` array wrapper** (沿用 sub-PR 4 GDELT 单 wrapper 体例)
- **`language` ISO code** ("en"/"zh", 沿用 sub-PR 1+2+3 NewsItem.lang 体例)
- **`published_at` ISO 8601 with microseconds + Z UTC** (e.g. "2026-05-06T12:32:42.000000Z")
- **`description` over `snippet`** — Marketaux snippet 含 cookie wall warning noise
- **0 `sentiment_score` by default** — sentiment_min filter 留 sub-PR 7 NewsClassifier 集成
- 100 req/day free tier (沿用 5-06 web_search Step 2 cite)

Retry 体例 (沿用 sub-PR 1+2+3+4 tenacity 体例 sustained):
- stop_after_attempt(3) + wait_exponential(min=4, max=60)
- retry on httpx.TimeoutException + _MarketauxRetryableError (429 + 5xx)
- 反 retry on 4xx 别 → fail-loud immediate raise NewsFetchError
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base import NewsFetcher, NewsFetchError, NewsItem


class _MarketauxRetryableError(RuntimeError):
    """Internal retryable error (429 rate limit + 5xx transient).

    沿用 sub-PR 1+2+3+4 RetryableError 体例 (反 httpx.HTTPStatusError 直 raise,
    避免 4xx 别 (400/401/402) 误 retry).
    """


DEFAULT_BASE_URL = "https://api.marketaux.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 10
DEFAULT_LANGUAGE = "en"  # 默认英文 (V3§3.1 海外信号 + 沿用 ADR-033 5-06 修订)
DEFAULT_USER_AGENT = "QuantMind-V2/1.0 (Python httpx)"
LIMIT_MIN = 1
LIMIT_MAX = 100  # Marketaux docs cite max limit per request


class MarketauxNewsFetcher(NewsFetcher):
    """Marketaux News#5 fetcher (V3§3.1 金融信号 + sentiment 标签).

    Args:
        api_key: MARKETAUX_API_KEY (.env user 真填, Step 4-2 体例).
        base_url: Marketaux API base (默认 https://api.marketaux.com).
        timeout: HTTP timeout 秒 (默认 30s, 沿用 sub-PR 1+2+3+4 sustained).
        language: 默认 ISO 639-1 code "en" (反 multi-lang sustained, fetch 时可 override).
        user_agent: 沿用 Step 4-2 finding "default UA → Cloudflare 1010" 体例.

    Example:
        >>> fetcher = MarketauxNewsFetcher(api_key=settings.MARKETAUX_API_KEY)
        >>> items = fetcher.fetch(query="Apple earnings", limit=5)
        >>> for item in items:
        ...     print(item.title, item.published_at, item.lang)
    """

    source_name = "marketaux"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        language: str = DEFAULT_LANGUAGE,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        if not api_key:
            raise ValueError("MARKETAUX_API_KEY is empty (沿用铁律 33 fail-loud)")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._language = language
        self._user_agent = user_agent

    def fetch(self, *, query: str, limit: int = DEFAULT_LIMIT) -> list[NewsItem]:
        """Fetch news items via Marketaux /v1/news/all.

        Args:
            query: search keyword (Marketaux `search` query param).
            limit: max results (clamp to [1, 100]).

        Raises:
            ValueError: query empty (fail-loud).
            NewsFetchError: HTTP error / timeout / retry exhausted.
        """
        if not query.strip():
            raise ValueError("query is empty (沿用铁律 33 fail-loud)")

        max_limit = min(max(LIMIT_MIN, limit), LIMIT_MAX)
        t0 = time.perf_counter()
        try:
            response_data = self._call_api(query=query, max_limit=max_limit)
        except NewsFetchError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError, _MarketauxRetryableError) as e:
            raise NewsFetchError(
                source=self.source_name,
                message=f"API call failed after retry: {e}",
                cause=e,
            ) from e
        latency_ms = int((time.perf_counter() - t0) * 1000)

        items = self._parse_response(response_data, latency_ms=latency_ms)
        return items[:limit]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((httpx.TimeoutException, _MarketauxRetryableError)),
        reraise=True,
    )
    def _call_api(self, *, query: str, max_limit: int) -> dict:
        """Marketaux /v1/news/all API call (GET method, retry-decorated).

        retry on TimeoutException + _MarketauxRetryableError (429 + 5xx). 4xx 别 →
        NewsFetchError fail-loud immediate raise.
        """
        url = f"{self._base_url}/v1/news/all"
        params = {
            "api_token": self._api_key,
            "search": query,
            "language": self._language,
            "limit": str(max_limit),
        }
        headers = {"User-Agent": self._user_agent}

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url, params=params, headers=headers)

        if resp.status_code == 429 or resp.status_code >= 500:
            raise _MarketauxRetryableError(
                f"HTTP {resp.status_code} (retryable: rate limit / 5xx): {resp.text[:200]}"
            )

        if resp.status_code >= 400:
            raise NewsFetchError(
                source=self.source_name,
                message=f"HTTP {resp.status_code} (non-retryable): {resp.text[:200]}",
            )

        try:
            return resp.json()
        except (ValueError, TypeError):
            return {}

    def _parse_response(self, data: dict, *, latency_ms: int) -> list[NewsItem]:
        """Parse Marketaux /v1/news/all response → list[NewsItem].

        Marketaux response schema (5-06 live verify):
            {
                "meta": {...},
                "data": [
                    {
                        "uuid": "...",
                        "title": "...",
                        "description": "...",
                        "snippet": "...",  # 含 cookie wall noise — 反优先
                        "url": "...",
                        "language": "en",  # ISO code
                        "published_at": "2026-05-06T12:32:42.000000Z",
                        "source": "seekingalpha.com",
                        "entities": [...],
                        ...
                    }
                ]
            }

        Empty list on parse failure (反 raise — content corruption shouldn't break caller).
        """
        if not isinstance(data, dict):
            return []

        raw_data = data.get("data", [])
        if not isinstance(raw_data, list):
            return []

        items: list[NewsItem] = []
        for raw in raw_data:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            if not title:
                continue
            ts = _parse_published_at(raw.get("published_at"))
            # description over snippet (snippet 含 cookie wall noise warning)
            content = raw.get("description") or raw.get("snippet")
            lang = raw.get("language") or self._language  # ISO code direct
            items.append(
                NewsItem(
                    source=self.source_name,
                    timestamp=ts,
                    title=title,
                    content=content,
                    url=raw.get("url"),
                    lang=lang,
                    fetch_cost_usd=Decimal("0"),  # 100 req/day free tier (V3§3.1)
                    fetch_latency_ms=latency_ms,
                )
            )
        return items


def _parse_published_at(raw: object) -> datetime:
    """Parse Marketaux `published_at` (ISO 8601 with microseconds + Z UTC).

    Marketaux format example: "2026-05-06T12:32:42.000000Z"
    沿用 fromisoformat (Python 3.11+ 真支持 Z suffix + microseconds).

    Fallback to now() UTC if missing/invalid (沿用 sub-PR 2+3+4 体例).
    """
    if not raw or not isinstance(raw, str):
        return datetime.now(tz=UTC)
    try:
        # Python 3.11+ fromisoformat 真支持 "Z" suffix
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        # 沿用 Z → +00:00 fallback (Python 3.10 兼容体例, 反 silent fail)
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return datetime.now(tz=UTC)
