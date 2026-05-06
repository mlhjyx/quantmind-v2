"""Anspire 安思派 News#3 fetcher (sub-PR 3, V3§3.1 中文财经主源).

独立 httpx client (沿用 sub-PR 1 ZhipuNewsFetcher + sub-PR 2 TavilyNewsFetcher
plugin 体例 sustained, 反 LiteLLM router).

GET endpoint (反 sub-PR 1+2 POST 体例, Anspire-specific finding 5-06 fresh verify):
    GET https://plugin.anspire.cn/api/ntsearch/search?query=...&top_k=...
    Headers: Authorization: Bearer <ANSPIRE_API_KEY>

Anspire-specific finding (5-06 Phase 1 fresh verify, 反 sub-PR 1+2 体例):
- **GET method** (反 POST) — query string params, 反 JSON body
- **`date` field** in response (反 Tavily 0 published_date, 真有 published date ✅)
- **`top_k` enum**: 10/20/30/40/50 only (反 free integer, clamp-to-nearest 体例)
- **`query` max 64 chars** (反 silent truncate, fail-loud raise on overflow)
- **`search_type`**: 默认 'web' (反 image/video, News fetcher 体例)
- 0 fresh rate limit policy + 0 fresh error code cite (沿用 generic 4xx fail-loud + 429/5xx retry 体例 sustained sub-PR 1+2)

Retry 体例 (沿用 sub-PR 1+2 tenacity 体例 sustained):
- stop_after_attempt(3) + wait_exponential(min=4, max=60)
- retry on httpx.TimeoutException + _AnspireRetryableError (429 + 5xx)
- 反 retry on 4xx 别 (auth/param) → fail-loud immediate raise NewsFetchError
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


class _AnspireRetryableError(RuntimeError):
    """Internal retryable error (429 rate limit + 5xx transient).

    沿用 sub-PR 1 _ZhipuRetryableError + sub-PR 2 _TavilyRetryableError 体例.
    """


DEFAULT_BASE_URL = "https://plugin.anspire.cn"
DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 10
DEFAULT_SEARCH_TYPE = "web"  # 反 'image'/'video' — News fetcher scope
QUERY_MAX_CHARS = 64  # Anspire docs cite 真值 (5-06 fresh verify)
TOP_K_ENUM = (10, 20, 30, 40, 50)  # Anspire docs cite 真值 (反 free integer)


def _clamp_top_k(limit: int) -> int:
    """Clamp limit → nearest TOP_K_ENUM value (反 silent truncate to free integer).

    Anspire `top_k` 真 enum 限制, 反 free integer. limit < 10 走 10, > 50 走 50,
    in-between 走 nearest 10/20/30/40/50.
    """
    if limit <= 10:
        return 10
    if limit >= 50:
        return 50
    # in-between: nearest 10/20/30/40
    return min(TOP_K_ENUM, key=lambda x: abs(x - limit))


class AnspireNewsFetcher(NewsFetcher):
    """Anspire 安思派 News#3 fetcher (V3§3.1 中文财经主源).

    Args:
        api_key: ANSPIRE_API_KEY (.env user 真填, Step 4-2 体例).
        base_url: Anspire API base (默认 https://plugin.anspire.cn).
        timeout: HTTP timeout 秒 (默认 30s, 沿用 sub-PR 1+2 sustained).
        search_type: "web" (默认) | "image" | "video" — 反 image/video News fetcher 体例.

    Example:
        >>> fetcher = AnspireNewsFetcher(api_key=settings.ANSPIRE_API_KEY)
        >>> items = fetcher.fetch(query="贵州茅台 财报", limit=10)
        >>> for item in items:
        ...     print(item.title, item.timestamp)
    """

    source_name = "anspire"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        search_type: str = DEFAULT_SEARCH_TYPE,
    ):
        if not api_key:
            raise ValueError("ANSPIRE_API_KEY is empty (沿用铁律 33 fail-loud)")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._search_type = search_type

    def fetch(self, *, query: str, limit: int = DEFAULT_LIMIT) -> list[NewsItem]:
        """Fetch news items via Anspire AI Search API (GET method, Anspire-specific 体例).

        Anspire-specific behavior:
        - query 走 64 char hard limit (反 silent truncate, fail-loud raise on overflow)
        - limit clamp 到 top_k enum (10/20/30/40/50, 反 silent truncate)

        Raises:
            ValueError: query empty / query > 64 chars (fail-loud).
            NewsFetchError: HTTP error / timeout / retry exhausted.
        """
        if not query.strip():
            raise ValueError("query is empty (沿用铁律 33 fail-loud)")
        if len(query) > QUERY_MAX_CHARS:
            raise ValueError(
                f"query exceeds {QUERY_MAX_CHARS} chars (Anspire hard limit, 沿用铁律 33)"
            )

        top_k = _clamp_top_k(limit)
        t0 = time.perf_counter()
        try:
            response_data = self._call_api(query=query, top_k=top_k)
        except NewsFetchError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError, _AnspireRetryableError) as e:
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
        retry=retry_if_exception_type((httpx.TimeoutException, _AnspireRetryableError)),
        reraise=True,
    )
    def _call_api(self, *, query: str, top_k: int) -> dict:
        """Anspire AI Search API call (GET method, retry-decorated).

        retry on TimeoutException + _AnspireRetryableError (429 + 5xx). 4xx 别 →
        NewsFetchError fail-loud immediate raise.
        """
        url = f"{self._base_url}/api/ntsearch/search"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        params = {
            "query": query,
            "top_k": str(top_k),  # Anspire docs cite top_k as String (反 int)
            "search_type": self._search_type,
        }

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url, headers=headers, params=params)

        if resp.status_code == 429 or resp.status_code >= 500:
            raise _AnspireRetryableError(
                f"HTTP {resp.status_code} (retryable: rate limit / 5xx): {resp.text[:200]}"
            )

        if resp.status_code >= 400:
            raise NewsFetchError(
                source=self.source_name,
                message=f"HTTP {resp.status_code} (non-retryable): {resp.text[:200]}",
            )

        return resp.json()

    def _parse_response(self, data: dict, *, latency_ms: int) -> list[NewsItem]:
        """Parse Anspire AI Search API response → list[NewsItem].

        Anspire response schema (5-06 fresh verify docs.anspire.cn):
        - results[].title / .content / .url / .score / .date (✅ NEW vs Tavily 0 published_date)
        - response 顶层 cite 走 "data" / "results" / "items" 沿用 generic 体例 try

        Empty list on parse failure (反 raise — content corruption shouldn't break caller).
        """
        if not isinstance(data, dict):
            return []

        # Anspire docs 0 fresh verify response 顶层 wrapper, try common fields
        raw_results = data.get("data") or data.get("results") or data.get("items") or []
        if isinstance(raw_results, dict):
            # 沿用 nested data.results 体例
            raw_results = raw_results.get("results", []) or raw_results.get("items", [])
        if not isinstance(raw_results, list):
            return []

        items: list[NewsItem] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            if not title:
                continue
            ts = _parse_timestamp(raw.get("date"))
            items.append(
                NewsItem(
                    source=self.source_name,
                    timestamp=ts,
                    title=title,
                    content=raw.get("content"),
                    url=raw.get("url"),
                    lang="zh",  # Anspire 中文财经源 (V3§3.1 ground truth)
                    fetch_cost_usd=Decimal("0"),  # 新户 2500 点免费 (Step 4-1 sediment)
                    fetch_latency_ms=latency_ms,
                )
            )
        return items


def _parse_timestamp(raw: object) -> datetime:
    """Parse Anspire `date` field (ISO 8601 or epoch fallback now() UTC).

    Anspire docs cite "date" field 真值 (5-06 fresh verify, 反 Tavily 0 published_date).
    某些 result 真携带, 0 携带走 now() UTC fallback (沿用 V3§3.1 fetched_at 体例).
    """
    if not raw or not isinstance(raw, str):
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return datetime.now(tz=UTC)
