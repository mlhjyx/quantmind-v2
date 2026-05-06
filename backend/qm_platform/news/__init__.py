"""Framework News — V3 §3.1 News 多源接入 (L0.1 News fetcher 主体).

归属: Framework #News ingestion 子模块 (V3 §3.1 News 多源接入真预约).
位置: backend/qm_platform/news/ (沿用 ADR-035 §2 News ingestion 层独立 client 决议).

scope (sub-PR 1+2 sediment):
- NewsItem (V3§3.1 news_raw schema 沿用 dataclass)
- NewsFetcher (abc base class, sub-PR 2-7 沿用 plugin 体例)
- NewsFetchError (exception 层)
- ZhipuNewsFetcher (智谱 GLM-4.7-Flash News#1 fetcher, ADR-035 §2, sub-PR 1)
- TavilyNewsFetcher (Tavily 英文 + 翻译, V3§3.1 海外信号, sub-PR 2)

公共 API 真**唯一 sanctioned 入口**:

    from backend.qm_platform.news import (
        NewsFetcher, NewsItem, ZhipuNewsFetcher, TavilyNewsFetcher,
    )

    zhipu = ZhipuNewsFetcher(api_key=settings.ZHIPU_API_KEY)
    tavily = TavilyNewsFetcher(api_key=settings.TAVILY_API_KEY)
    items = zhipu.fetch(query="贵州茅台 财报", limit=10) + tavily.fetch(query="Apple Q1", limit=5)
    for item in items:
        print(item.title, item.timestamp, item.source)

架构 (ADR-035 §2 line 60-68 sustained):
- 6 源全独立 httpx client (反 LiteLLM router yaml entry, 反 V4 路由层)
- 6 源沿用 NewsFetcher abc + plugin 体例 (sub-PR 1 base + 2-7 各源)
- L0.2 NewsClassifier (V4-Flash routed) 走 LiteLLMRouter, 跟本子包 0 重叠

关联铁律:
- 31 (Engine 层纯计算 — fetcher 0 DB IO, caller 走 DataPipeline 入库)
- 33 (fail-loud — NewsFetchError 显式 raise, 反 silent fallback)
- 41 (timezone — NewsItem.timestamp 沿用 tz-aware UTC + Asia/Shanghai 展示)

关联文档:
- ADR-035 (智谱 GLM-4.7-Flash News#1 + V4 路由层 0 智谱)
- ADR-031 §6 (V4 路由层 sustained DeepSeek + Ollama, 0 智谱 alias)
- ADR-033 (News 6 源换源决议)
- V3 §3.1 (News 多源接入 line 312-356)
"""
from .anspire import AnspireNewsFetcher
from .base import NewsFetcher, NewsFetchError, NewsItem
from .gdelt import GdeltNewsFetcher
from .tavily import TavilyNewsFetcher
from .zhipu import ZhipuNewsFetcher

__all__ = [
    "AnspireNewsFetcher",
    "GdeltNewsFetcher",
    "NewsFetcher",
    "NewsFetchError",
    "NewsItem",
    "TavilyNewsFetcher",
    "ZhipuNewsFetcher",
]
