"""Tavily News fetcher (sub-PR 2, V3§3.1 + ADR-033).

独立 httpx client (沿用 sub-PR 1 ZhipuNewsFetcher 体例 sustained, 反 LiteLLM router).

POST /search endpoint:
    POST https://api.tavily.com/search
    Headers: Authorization: Bearer <TAVILY_API_KEY>
    Body: {"query": "...", "topic": "news", "max_results": int, "search_depth": "basic"}

Retry 体例 (沿用 sub-PR 1 ZhipuNewsFetcher tenacity 体例 sustained):
- stop_after_attempt(3) + wait_exponential(min=4, max=60)
- retry on httpx.TimeoutException + _TavilyRetryableError (429 + 5xx)
- 反 retry on 401 (auth) / 400 (param) / 432 (plan limit) / 433 (PAYG limit)
  → fail-loud immediate raise NewsFetchError (反 retry 触 limit cliff)

Tavily-specific finding (sub-PR 2 fresh verify, 反 sub-PR 1 智谱体例):
- response 0 `published_date` field → timestamp 沿用 now() UTC fallback
- response_time (float, sec) → fetch_latency_ms × 1000
- Tavily 错码 432 (plan usage limit) + 433 (PAYG spending limit) NEW (反智谱)
- 1000 credits/月永久免费 (V3§3.1 沿用)
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


class _TavilyRetryableError(RuntimeError):
    """Internal retryable error (429 rate limit + 5xx transient).

    沿用 sub-PR 1 _ZhipuRetryableError 体例 (反 httpx.HTTPStatusError 直 raise,
    避免 4xx 别 (400/401/432/433) 误 retry. 432/433 走 NewsFetchError fail-loud
    — plan/PAYG limit retry 反破费).
    """


DEFAULT_BASE_URL = "https://api.tavily.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 10
DEFAULT_TOPIC = "news"  # 反 "general" — Tavily docs cite News 主题专用 endpoint
DEFAULT_SEARCH_DEPTH = "basic"  # 反 "advanced" — credit cost ÷ 2, sub-PR 2 minimal 体例


class TavilyNewsFetcher(NewsFetcher):
    """Tavily News fetcher (英文 + 翻译, V3§3.1 海外信号).

    Args:
        api_key: TAVILY_API_KEY (.env user 真填, Step 4-2 体例).
        base_url: Tavily API base (默认 https://api.tavily.com).
        timeout: HTTP timeout 秒 (默认 30s, 沿用 sub-PR 1 sustained).
        topic: "news" (默认) | "general" (反 News 用途).
        search_depth: "basic" (默认, 1 credit/call) | "advanced" (2 credit/call).

    Example:
        >>> fetcher = TavilyNewsFetcher(api_key=settings.TAVILY_API_KEY)
        >>> items = fetcher.fetch(query="Apple earnings Q1 2026", limit=5)
        >>> for item in items:
        ...     print(item.title, item.url)
    """

    source_name = "tavily"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        topic: str = DEFAULT_TOPIC,
        search_depth: str = DEFAULT_SEARCH_DEPTH,
    ):
        if not api_key:
            raise ValueError("TAVILY_API_KEY is empty (沿用铁律 33 fail-loud)")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._topic = topic
        self._search_depth = search_depth

    def fetch(self, *, query: str, limit: int = DEFAULT_LIMIT) -> list[NewsItem]:
        """Fetch news items via Tavily Search API.

        Tavily max_results 范围 0-20 (官方 cite). limit > 20 走 clamp 20.

        Raises:
            NewsFetchError: HTTP error / timeout / retry exhausted / plan limit / PAYG limit.
        """
        if not query.strip():
            raise ValueError("query is empty (沿用铁律 33 fail-loud)")

        max_results = min(max(0, limit), 20)
        t0 = time.perf_counter()
        try:
            response_data = self._call_api(query=query, max_results=max_results)
        except NewsFetchError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError, _TavilyRetryableError) as e:
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
        retry=retry_if_exception_type((httpx.TimeoutException, _TavilyRetryableError)),
        reraise=True,
    )
    def _call_api(self, *, query: str, max_results: int) -> dict:
        """Tavily Search API call (内部, retry-decorated).

        retry on TimeoutException + _TavilyRetryableError (429 + 5xx). 4xx 别
        (400/401/432/433) → NewsFetchError fail-loud immediate raise.
        """
        url = f"{self._base_url}/search"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "topic": self._topic,
            "max_results": max_results,
            "search_depth": self._search_depth,
        }

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, headers=headers, json=payload)

        if resp.status_code == 429 or resp.status_code >= 500:
            raise _TavilyRetryableError(
                f"HTTP {resp.status_code} (retryable: rate limit / 5xx): {resp.text[:200]}"
            )

        if resp.status_code in (432, 433):
            # 432 plan usage limit / 433 PAYG spending limit — NEVER retry (沿用 fail-loud)
            raise NewsFetchError(
                source=self.source_name,
                message=(
                    f"HTTP {resp.status_code} (plan/PAYG limit, NOT retryable): "
                    f"{resp.text[:200]}"
                ),
            )

        if resp.status_code >= 400:
            # 400 invalid params / 401 invalid key / 别 4xx
            raise NewsFetchError(
                source=self.source_name,
                message=f"HTTP {resp.status_code} (non-retryable): {resp.text[:200]}",
            )

        return resp.json()

    def _parse_response(self, data: dict, *, latency_ms: int) -> list[NewsItem]:
        """Parse Tavily Search API response → list[NewsItem].

        Tavily response schema (5-06 fresh verify docs.tavily.com):
        - results[].title / .url / .content / .score / .published_date (optional)
        - 0 published_date 走 now() UTC fallback (沿用 V3§3.1 fetched_at 体例)

        Empty list on parse failure (反 raise — content corruption shouldn't break caller).
        """
        if not isinstance(data, dict):
            return []

        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            return []

        items: list[NewsItem] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            if not title:
                continue
            ts = _parse_timestamp(raw.get("published_date"))
            items.append(
                NewsItem(
                    source=self.source_name,
                    timestamp=ts,
                    title=title,
                    content=raw.get("content"),
                    url=raw.get("url"),
                    lang="en",  # Tavily 默认英文 (V3§3.1 海外信号体例)
                    fetch_cost_usd=Decimal("0"),  # 1000 credits/月永久免费 (V3§3.1)
                    fetch_latency_ms=latency_ms,
                )
            )
        return items


def _parse_timestamp(raw: object) -> datetime:
    """Parse Tavily published_date (optional). Fallback to now() UTC if missing/invalid.

    Tavily docs cite published_date 反 standard schema field (5-06 fresh verify),
    某些 result 真携带, 某些反携带. 反携带走 now() UTC fallback (沿用 V3§3.1
    news_raw.fetched_at DEFAULT NOW() 体例).
    """
    if not raw or not isinstance(raw, str):
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return datetime.now(tz=UTC)
