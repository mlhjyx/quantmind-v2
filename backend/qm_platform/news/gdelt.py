"""GDELT 2.0 News#4 fetcher (sub-PR 4, V3§3.1 全球事件 + 跨境 stream).

独立 httpx client (沿用 sub-PR 1 智谱 + sub-PR 2 Tavily + sub-PR 3 Anspire
plugin 体例 sustained, 反 LiteLLM router).

GDELT 2.0 DOC API endpoint (5-06 fresh verify):
    GET https://api.gdeltproject.org/api/v2/doc/doc
    Headers: 0 (anonymous, 反 Bearer auth)
    Query: QUERY (search expr) + MODE=ArtList + FORMAT=JSON + TIMESPAN=1d
           + MAXRECORDS (default 75, max 250)

GDELT-specific finding (5-06 Phase 1 fresh verify, 反 sub-PR 1+2+3 体例):
- **0 API key** (anonymous, 反 sub-PR 1+2+3 Bearer auth)
- **GET method** + URL query params (沿用 sub-PR 3 Anspire 体例)
- **`articles` wrapper** (单 candidate, 反 sub-PR 3 多 candidate try)
- **`seendate` format = YYYYMMDDTHHMMSSZ** (反 ISO 8601, custom parse 体例)
- **`language` field = human-readable** ("English"/"Chinese", 反 ISO code)
- **0 `content` field** in ArtList mode (返 title-only, content 0 truncation)
- **MAXRECORDS clamp [1, 250]** (反 sub-PR 3 Anspire top_k enum 体例)
- **sourcelang inlined in QUERY** (e.g. "Apple sourcelang:english")

Retry 体例 (沿用 sub-PR 1+2+3 tenacity 体例 sustained):
- stop_after_attempt(3) + wait_exponential(min=4, max=60)
- retry on httpx.TimeoutException + _GdeltRetryableError (429 + 5xx)
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


class _GdeltRetryableError(RuntimeError):
    """Internal retryable error (429 rate limit + 5xx transient).

    沿用 sub-PR 1 _ZhipuRetryableError + sub-PR 2 _TavilyRetryableError +
    sub-PR 3 _AnspireRetryableError 体例.
    """


DEFAULT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 10
DEFAULT_MODE = "ArtList"  # 反 TimelineVol/ToneChart/ImageCollage — News fetcher scope
DEFAULT_FORMAT = "JSON"  # 反 HTML/CSV/RSS — JSON parse
DEFAULT_TIMESPAN = "1d"  # 24h rolling window (V3§3.1 实时 stream 体例)
MAXRECORDS_MIN = 1
MAXRECORDS_MAX = 250  # GDELT docs cite 真值 (5-06 fresh verify)

# GDELT `language` field 真值 = human-readable string ("English"/"Chinese").
# Map to ISO 639-1 code (沿用 sub-PR 1+2+3 lang="zh"/"en" 体例).
LANGUAGE_MAP = {
    "English": "en",
    "Chinese": "zh",
    "Japanese": "ja",
    "Korean": "ko",
    "French": "fr",
    "German": "de",
    "Spanish": "es",
    "Russian": "ru",
}
DEFAULT_LANG = "en"  # 反 0 lang sediment, fail-loud-soft fallback


class GdeltNewsFetcher(NewsFetcher):
    """GDELT 2.0 News#4 fetcher (V3§3.1 全球事件 + 跨境 stream).

    Args:
        base_url: GDELT API base (默认 https://api.gdeltproject.org/api/v2/doc/doc).
        timeout: HTTP timeout 秒 (默认 30s, 沿用 sub-PR 1+2+3 sustained).
        timespan: rolling window (e.g. "1d" / "1week" / "24h", 默认 "1d").
        mode: GDELT MODE param (默认 "ArtList" — News fetcher 体例).

    Example:
        >>> fetcher = GdeltNewsFetcher()
        >>> items = fetcher.fetch(query="Apple sourcelang:english", limit=5)
        >>> for item in items:
        ...     print(item.title, item.timestamp, item.lang)
    """

    source_name = "gdelt"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        timespan: str = DEFAULT_TIMESPAN,
        mode: str = DEFAULT_MODE,
    ):
        # GDELT 0 API key (anonymous), 反 sub-PR 1+2+3 ValueError on empty key 体例
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._timespan = timespan
        self._mode = mode

    def fetch(self, *, query: str, limit: int = DEFAULT_LIMIT) -> list[NewsItem]:
        """Fetch news items via GDELT 2.0 DOC API (GET method, anonymous).

        Args:
            query: GDELT search expression (沿用 docs 体例,
                e.g. "Apple sourcelang:english", "贵州茅台 sourcelang:chinese").
            limit: max results (clamp to [1, 250]).

        Raises:
            ValueError: query empty (fail-loud).
            NewsFetchError: HTTP error / timeout / retry exhausted.
        """
        if not query.strip():
            raise ValueError("query is empty (沿用铁律 33 fail-loud)")

        max_records = min(max(MAXRECORDS_MIN, limit), MAXRECORDS_MAX)
        t0 = time.perf_counter()
        try:
            response_data = self._call_api(query=query, max_records=max_records)
        except NewsFetchError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError, _GdeltRetryableError) as e:
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
        retry=retry_if_exception_type((httpx.TimeoutException, _GdeltRetryableError)),
        reraise=True,
    )
    def _call_api(self, *, query: str, max_records: int) -> dict:
        """GDELT 2.0 DOC API call (GET method, anonymous, retry-decorated).

        retry on TimeoutException + _GdeltRetryableError (429 + 5xx). 4xx 别 →
        NewsFetchError fail-loud immediate raise.
        """
        params = {
            "QUERY": query,
            "MODE": self._mode,
            "FORMAT": self._format_or_default(),
            "TIMESPAN": self._timespan,
            "MAXRECORDS": str(max_records),
        }

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(self._base_url, params=params)

        if resp.status_code == 429 or resp.status_code >= 500:
            raise _GdeltRetryableError(
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
            # GDELT 真返 HTML on某些 query (沿用 5-06 fresh verify, 反 silent guess JSON)
            return {}

    def _format_or_default(self) -> str:
        """Returns FORMAT param (default JSON, 反 HTML/CSV/RSS)."""
        return DEFAULT_FORMAT

    def _parse_response(self, data: dict, *, latency_ms: int) -> list[NewsItem]:
        """Parse GDELT 2.0 DOC API response → list[NewsItem].

        GDELT response schema (5-06 live verify, ArtList mode):
            {
                "articles": [
                    {
                        "url": "...",
                        "title": "...",
                        "seendate": "20260505T223000Z",  # YYYYMMDDTHHMMSSZ
                        "domain": "...",
                        "language": "English",  # human-readable
                        "sourcecountry": "..."
                    }
                ]
            }

        Empty list on parse failure (反 raise — content corruption shouldn't break caller).
        """
        if not isinstance(data, dict):
            return []

        raw_articles = data.get("articles", [])
        if not isinstance(raw_articles, list):
            return []

        items: list[NewsItem] = []
        for raw in raw_articles:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            if not title:
                continue
            ts = _parse_seendate(raw.get("seendate"))
            lang = LANGUAGE_MAP.get(raw.get("language", ""), DEFAULT_LANG)
            items.append(
                NewsItem(
                    source=self.source_name,
                    timestamp=ts,
                    title=title,
                    content=None,  # GDELT ArtList 0 content field (5-06 fresh verify)
                    url=raw.get("url"),
                    lang=lang,
                    fetch_cost_usd=Decimal("0"),  # 0 API key, anonymous (V3§3.1)
                    fetch_latency_ms=latency_ms,
                )
            )
        return items


def _parse_seendate(raw: object) -> datetime:
    """Parse GDELT `seendate` field (YYYYMMDDTHHMMSSZ, 反 ISO 8601).

    GDELT-specific 体例 (反 sub-PR 3 Anspire `date` ISO 8601 parse 体例):
    - "20260505T223000Z" → datetime(2026, 5, 5, 22, 30, 0, tzinfo=UTC)
    - 反 separator (反 "2026-05-05T22:30:00Z" sub-PR 3 体例)

    Fallback to now() UTC if missing/invalid (沿用 sub-PR 2+3 体例).
    """
    if not raw or not isinstance(raw, str):
        return datetime.now(tz=UTC)
    # GDELT format: YYYYMMDDTHHMMSSZ (no separators)
    if len(raw) == 16 and raw[8] == "T" and raw.endswith("Z"):
        try:
            return datetime(
                year=int(raw[0:4]),
                month=int(raw[4:6]),
                day=int(raw[6:8]),
                hour=int(raw[9:11]),
                minute=int(raw[11:13]),
                second=int(raw[13:15]),
                tzinfo=UTC,
            )
        except (ValueError, TypeError):
            return datetime.now(tz=UTC)
    # Fallback: try ISO 8601 parse (反 silent fail on别 format)
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return datetime.now(tz=UTC)
