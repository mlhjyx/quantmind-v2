"""News fetcher base class + NewsItem schema + NewsFetchError.

V3§3.1 news_raw schema (line 336-348) 沿用 dataclass(frozen=True) 体例.
sub-PR 2-7 沿用 NewsFetcher abc 实现各源 plugin (Tavily / Anspire / GDELT / Marketaux / RSSHub).

关联:
- ADR-035 §2 (智谱 News#1, V4 路由层 0 智谱)
- V3 §3.1 line 336-348 (news_raw schema)
- 铁律 33 (fail-loud — NewsFetchError 显式 raise)
- 铁律 41 (timezone — timestamp tz-aware)
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class NewsFetchError(RuntimeError):
    """News fetcher 调用层 failure (反 silent skip, 沿用铁律 33).

    caller 接住 → audit log + 走下一源 (V3§3.1 "并行查询 + 早返回, 任 3 源命中即继续").

    Args:
        source: fetcher 源标识 (e.g. "zhipu" / "tavily")
        message: 真因 cite (e.g. "HTTP 429 rate limit / network timeout / API key invalid")
        cause: 原始 Exception (httpx.HTTPError / TimeoutException 等), retry exhausted 后 raise
    """

    def __init__(self, source: str, message: str, cause: Exception | None = None):
        super().__init__(f"[{source}] {message}")
        self.source = source
        self.cause = cause


@dataclass(frozen=True, slots=True)
class NewsItem:
    """V3§3.1 news_raw schema 沿用 (line 336-348).

    Fields align 1:1 to news_raw DDL columns:
    - source = news_raw.source (VARCHAR(20), required)
    - timestamp = news_raw.timestamp (TIMESTAMPTZ, required, **tz-aware** 铁律 41)
    - title = news_raw.title (TEXT, required)
    - content = news_raw.content (TEXT, optional)
    - url = news_raw.url (TEXT, optional)
    - lang = news_raw.lang (VARCHAR(10), default "zh")
    - symbol_id = news_raw.symbol_id (VARCHAR(20), optional, NULL = 大盘/行业)
    - fetch_cost_usd = news_raw.fetch_cost (NUMERIC(8,4), default 0)
    - fetch_latency_ms = news_raw.fetch_latency_ms (INT, default 0)

    Note: news_id (BIGSERIAL) + fetched_at (TIMESTAMPTZ DEFAULT NOW()) 由 DB 真生成,
    fetcher 层不携带 (DataPipeline 入库时填补).
    """

    source: str
    timestamp: datetime
    title: str
    content: str | None = None
    url: str | None = None
    lang: str = "zh"
    symbol_id: str | None = None
    fetch_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    fetch_latency_ms: int = 0


class NewsFetcher(abc.ABC):
    """News fetcher base class (sub-PR 1 sediment, sub-PR 2-7 沿用 plugin 体例).

    各源 implementation 沿用本 abc:
    - sub-PR 1: ZhipuNewsFetcher (智谱 GLM-4.7-Flash, ADR-035)
    - sub-PR 2: TavilyNewsFetcher (沿用)
    - sub-PR 3: AnspireNewsFetcher
    - sub-PR 4: GdeltNewsFetcher (0 API key)
    - sub-PR 5: MarketauxNewsFetcher
    - sub-PR 6: RSShubNewsFetcher (自部署)

    caller 调用模式 (V3§3.1 "并行查询 + 早返回, 任 3 源命中即继续"):

        fetchers = [ZhipuNewsFetcher(...), TavilyNewsFetcher(...), ...]
        results = []
        for f in fetchers:
            try:
                items = f.fetch(query="贵州茅台", limit=10)
                results.extend(items)
            except NewsFetchError as e:
                # audit log + skip, 沿用 V3§3.1 "早返回" 策略
                logger.warning("News fetcher %s failed: %s", f.source_name, e)
        return results
    """

    source_name: str

    @abc.abstractmethod
    def fetch(self, *, query: str, limit: int = 10) -> list[NewsItem]:
        """Fetch news items matching query.

        Args:
            query: 查询关键词 (e.g. 股票名称 / 行业 / 事件描述)
            limit: 返回 item 上限 (默认 10, 反 over-fetch 耗 quota)

        Returns:
            list[NewsItem] (可能为空 list, 反 None)

        Raises:
            NewsFetchError: HTTP error / timeout / API key invalid / retry exhausted
        """
        raise NotImplementedError
