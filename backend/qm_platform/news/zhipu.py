"""智谱 GLM-4.7-Flash News#1 fetcher (ADR-035 §2 sustained).

独立 httpx client (反 LiteLLM router yaml entry, 沿用 ADR-035 §2 line 60-68
"0 智谱 alias in LiteLLM router yaml. 智谱走 News ingestion 层独立 client (V3§3.1),
反 V4 路由层").

OpenAI 兼容 endpoint:
    POST https://open.bigmodel.cn/api/paas/v4/chat/completions
    Headers: Authorization: Bearer <ZHIPU_API_KEY>
    Body: {"model": "glm-4.7-flash", "messages": [...], ...}

Retry 体例 (沿用 ADR-035 §4 Negative cite "free tier qps cap finding"):
- tenacity exponential backoff: stop_after_attempt(3) + wait_exponential(min=4, max=60)
- retry on httpx.TimeoutException + httpx.HTTPStatusError (429/5xx)
- 反 retry on 401 (invalid API key) + 4xx 别 (caller bug, fail-loud)

5-06 Step 4-3 fresh verify findings sediment:
- glm-4.7-flash HTTP 429 rate limit code 1305 (free tier qps cap, 反 monthly quota)
- 60s cooldown sustained Step 4-2 cold-start retry 实证
"""
from __future__ import annotations

import json
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


class _ZhipuRetryableError(RuntimeError):
    """Internal retryable error (429 qps cap + 5xx transient server error).

    沿用 tenacity retry_if_exception_type 体例 (反 httpx.HTTPStatusError 直 raise,
    避免 tenacity 跟 4xx 别 (401/403/404) 误 retry. 4xx 别走 NewsFetchError fail-loud).
    """


DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.7-flash"
DEFAULT_TIMEOUT = 30.0  # 沿用 ADR-035 §4 Negative cite Step 4-2 cold-start 60s retry 体例
DEFAULT_LIMIT = 10
SYSTEM_PROMPT = (
    "你是金融新闻收集助手. 根据用户给的查询关键词, 输出最近的相关新闻列表.\n"
    "严格输出 JSON 格式: {\"items\": [{\"title\": \"\", \"content\": \"\", "
    "\"url\": \"\", \"timestamp\": \"YYYY-MM-DDTHH:MM:SS+08:00\"}]}\n"
    "timestamp 用 ISO 8601 + Asia/Shanghai timezone. 反 markdown / 反 ```code fence```."
)


class ZhipuNewsFetcher(NewsFetcher):
    """智谱 GLM-4.7-Flash News#1 fetcher.

    Args:
        api_key: ZHIPU_API_KEY (.env user 真填, Step 4-1/4-2 sediment).
        base_url: 智谱 API base (默认 https://open.bigmodel.cn/api/paas/v4).
        model: model_id (默认 "glm-4.7-flash" 沿用 ADR-035 §2 ground truth + Step 4-3 fresh verify).
        timeout: HTTP timeout 秒 (默认 30s, 沿用 Step 4-2 cold-start 60s retry 体例).

    Example:
        >>> fetcher = ZhipuNewsFetcher(api_key=settings.ZHIPU_API_KEY)
        >>> items = fetcher.fetch(query="贵州茅台 财报", limit=5)
        >>> for item in items:
        ...     print(item.title, item.timestamp)
    """

    source_name = "zhipu"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if not api_key:
            raise ValueError("ZHIPU_API_KEY is empty (沿用铁律 33 fail-loud)")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def fetch(self, *, query: str, limit: int = DEFAULT_LIMIT) -> list[NewsItem]:
        """Fetch news items via 智谱 GLM-4.7-Flash chat completion.

        Returns parsed JSON items (反 markdown fence). Empty list on parse failure
        (反 raise — content corruption shouldn't break caller).

        Raises:
            NewsFetchError: HTTP error / timeout / retry exhausted (网络层 / API 层 failure).
        """
        if not query.strip():
            raise ValueError("query is empty (沿用铁律 33 fail-loud)")

        t0 = time.perf_counter()
        try:
            response_data = self._call_api(query=query, limit=limit)
        except NewsFetchError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError, _ZhipuRetryableError) as e:
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
        retry=retry_if_exception_type((httpx.TimeoutException, _ZhipuRetryableError)),
        reraise=True,
    )
    def _call_api(self, *, query: str, limit: int) -> dict:
        """智谱 OpenAI 兼容 chat completion call (内部, retry-decorated).

        retry on TimeoutException + _ZhipuRetryableError (429/5xx, qps cap + transient
        server error). 反 retry on 4xx 别 (caller bug, fail-loud immediate raise via
        NewsFetchError, 反 retry on auth failure).
        """
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"查询: {query}. 最多 {limit} 条."},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, headers=headers, json=payload)

        if resp.status_code == 429 or resp.status_code >= 500:
            # 触发 tenacity retry (走 _ZhipuRetryableError, 反 raise_for_status 体例)
            raise _ZhipuRetryableError(
                f"HTTP {resp.status_code} (retryable: qps cap / 5xx): {resp.text[:200]}"
            )

        if resp.status_code >= 400:
            # 4xx 别 (401/403/404 etc.): caller bug, fail-loud immediate raise
            raise NewsFetchError(
                source=self.source_name,
                message=f"HTTP {resp.status_code} (non-retryable): {resp.text[:200]}",
            )

        return resp.json()

    def _parse_response(self, data: dict, *, latency_ms: int) -> list[NewsItem]:
        """Parse 智谱 chat completion response → list[NewsItem].

        Empty list on JSON parse failure (反 raise — content corruption shouldn't
        break caller, audit log 真依赖 caller 端).
        """
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return []

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return []

        raw_items = parsed.get("items", []) if isinstance(parsed, dict) else []
        if not isinstance(raw_items, list):
            return []

        items: list[NewsItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            title = raw.get("title", "").strip()
            if not title:
                continue
            ts_raw = raw.get("timestamp", "")
            ts = _parse_timestamp(ts_raw)
            items.append(
                NewsItem(
                    source=self.source_name,
                    timestamp=ts,
                    title=title,
                    content=raw.get("content"),
                    url=raw.get("url"),
                    lang="zh",
                    fetch_cost_usd=Decimal("0"),  # GLM-4.7-Flash 永久免费 (ADR-035 §1)
                    fetch_latency_ms=latency_ms,
                )
            )
        return items


def _parse_timestamp(raw: str) -> datetime:
    """Parse ISO 8601 timestamp (with timezone). Fallback to now() UTC if parse fail."""
    if not raw:
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return datetime.now(tz=UTC)
