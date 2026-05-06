"""News DataPipeline — V3 §3.1 6 源并行查询 + 早返回 + dedup (sub-PR 7a sediment).

V3 §3.1 line 329 真预约: "并行查询 + 早返回. 任 3 源命中即继续 (full timeout 30s 全等待不可接受)".

体例 sustained (sub-PR 1-6 plugin 体例 + V3 §3.1 ground truth):
- 6 fetcher 全 sync httpx.Client → ThreadPoolExecutor (concurrent.futures) 走并行调用
- per-source NewsFetchError fail-soft (audit log + skip), 沿用 base.py docstring caller 模式
- 早返回 early-return: ≥ early_return_threshold 源命中后 NOT 等待剩余 future
- hard timeout (max_wait_seconds=30, V3§3.1 line 329 cite)
- dedup: url-first + title-hash fallback (DataPipeline-specific extension —
  V3§3.1 0 显式 dedup 真预约 + RSSHub 时 url 可能 None 走 title fallback)

scope (sub-PR 7a, sub-PR 7b NewsClassifier defer Sprint 3 prerequisite):
- DataPipeline class (本 file) — 6 fetcher 集成 + concurrent + dedup
- NewsClassifier — 反 本子包 scope (V3 line 1223 真预约 backend/app/services/news/,
  news/__init__.py:28 docstring "L0.2 NewsClassifier 跟本子包 0 重叠" sustained)

关联:
- V3 §3.1 (News 多源接入 line 312-356)
- ADR-033 (News 6 源换源决议, 沿用本 PR 7a patch)
- ADR-035 §2 (News ingestion 层独立 client, 反 V4 路由层)
- 铁律 31 (Engine 层纯计算 — DataPipeline 0 DB IO, caller 走入库)
- 铁律 33 (fail-loud — query empty 显式 raise; 全源 fail 走 fail-soft + 空 list 返)
- 铁律 41 (timezone — NewsItem.timestamp tz-aware sustained sub-PR 1-6)
- 铁律 45 (4 doc fresh read SOP enforcement, PR-B sediment)
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import NewsFetcher, NewsFetchError, NewsItem

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKERS = 6  # 沿用 6 源 sub-PR 1-6 plugin 体例
DEFAULT_LIMIT_PER_SOURCE = 10  # 沿用 NewsFetcher abc default
DEFAULT_HARD_TIMEOUT_SECONDS = 30.0  # V3 §3.1 line 329 真预约
DEFAULT_EARLY_RETURN_THRESHOLD = 3  # V3 §3.1 line 329 "任 3 源命中即继续"


class DataPipeline:
    """News 多源 DataPipeline — V3 §3.1 sub-PR 7a sediment.

    Args:
        fetchers: NewsFetcher list (典型 6 源 sub-PR 1-6 sediment).
        max_workers: ThreadPool size (默认 6).
        hard_timeout_s: 全源 hard timeout 秒 (默认 30s, V3§3.1 line 329).
        early_return_threshold: ≥ 此源命中后早返回 (默认 3, V3§3.1).

    Note:
        query 真**per-source semantics 沿用 sub-PR 1-6 plugin 体例**:
        - 智谱/Tavily/Marketaux: 自然语言 search keyword
        - Anspire: 64 char hard limit search keyword (sub-PR 3 finding)
        - GDELT: keyword-based (反 event-driven)
        - RSSHub: route path (e.g. "/jin10/news", sub-PR 6 finding)

        混用 fetchers 时 caller 真**约束 query 兼容多源 plugin** (推荐自然语言中文 +
        长度 ≤ 64 char; RSSHub 真 route path 走独立 caller pattern).

    Example:
        >>> from backend.qm_platform.news import (
        ...     ZhipuNewsFetcher, TavilyNewsFetcher, AnspireNewsFetcher,
        ...     GdeltNewsFetcher, MarketauxNewsFetcher, RsshubNewsFetcher,
        ...     DataPipeline,
        ... )
        >>> fetchers = [
        ...     ZhipuNewsFetcher(api_key="..."),
        ...     TavilyNewsFetcher(api_key="..."),
        ...     AnspireNewsFetcher(api_key="..."),
        ...     GdeltNewsFetcher(),
        ...     MarketauxNewsFetcher(api_key="..."),
        ...     # RSSHub 走独立 pipeline (route path 真预约)
        ... ]
        >>> pipeline = DataPipeline(fetchers)
        >>> items = pipeline.fetch_all(query="贵州茅台 财报", limit_per_source=10)
        >>> for item in items:
        ...     print(item.source, item.title, item.timestamp)
    """

    def __init__(
        self,
        fetchers: list[NewsFetcher],
        *,
        max_workers: int = DEFAULT_MAX_WORKERS,
        hard_timeout_s: float = DEFAULT_HARD_TIMEOUT_SECONDS,
        early_return_threshold: int = DEFAULT_EARLY_RETURN_THRESHOLD,
    ):
        if not fetchers:
            raise ValueError("fetchers list is empty (沿用铁律 33 fail-loud)")
        if early_return_threshold < 1:
            raise ValueError(
                f"early_return_threshold must be >= 1, got {early_return_threshold}"
            )
        if hard_timeout_s <= 0:
            raise ValueError(f"hard_timeout_s must be > 0, got {hard_timeout_s}")
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")

        self._fetchers = list(fetchers)
        self._max_workers = max_workers
        self._hard_timeout_s = hard_timeout_s
        self._early_return_threshold = early_return_threshold

    def fetch_all(
        self,
        *,
        query: str,
        limit_per_source: int = DEFAULT_LIMIT_PER_SOURCE,
        total_limit: int | None = None,
    ) -> list[NewsItem]:
        """6 源并行查询 + 早返回 + dedup, V3§3.1 line 329 真生产体例.

        Args:
            query: caller search query (per-source semantics 沿用 sub-PR 1-6 plugin 体例).
            limit_per_source: per-source limit (默认 10, 沿用 NewsFetcher abc).
            total_limit: aggregated dedup 后 total limit (None = 全保留).

        Returns:
            list[NewsItem] — concurrent fetch + dedup 结果. 空 list 表示全源 0 命中
            (反 raise — V3§3.1 fail-soft 体例 sustained).

        Raises:
            ValueError: query empty (沿用铁律 33 fail-loud).
        """
        if not query.strip():
            raise ValueError("query is empty (沿用铁律 33 fail-loud)")

        all_items: list[NewsItem] = []
        success_count = 0
        fail_count = 0

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            future_to_fetcher = {
                pool.submit(self._safe_fetch, f, query, limit_per_source): f
                for f in self._fetchers
            }

            try:
                for future in as_completed(
                    future_to_fetcher, timeout=self._hard_timeout_s
                ):
                    fetcher = future_to_fetcher[future]
                    try:
                        items = future.result()
                        all_items.extend(items)
                        success_count += 1
                        logger.debug(
                            "DataPipeline source=%s returned %d items "
                            "(success=%d, fail=%d)",
                            fetcher.source_name,
                            len(items),
                            success_count,
                            fail_count,
                        )
                        if success_count >= self._early_return_threshold:
                            logger.info(
                                "DataPipeline early return: %d sources hit "
                                "(threshold=%d, V3§3.1 line 329)",
                                success_count,
                                self._early_return_threshold,
                            )
                            break
                    except NewsFetchError as e:
                        fail_count += 1
                        logger.warning(
                            "DataPipeline fail-soft source=%s: %s "
                            "(V3§3.1 + base.py caller 模式)",
                            fetcher.source_name,
                            e,
                        )
                    except Exception as e:  # noqa: BLE001 — fail-soft per-source
                        # 反 NewsFetchError 别 exception (e.g. KeyError / AttributeError /
                        # httpx.DecodingError) 真 fail-soft sustained, 反 break 整 loop
                        # (沿用 V3§3.1 fail-soft per-source 体例 sustained, 铁律 33-d).
                        fail_count += 1
                        logger.error(
                            "DataPipeline unexpected error source=%s: %s "
                            "(fail-soft sustained, exc_info logged)",
                            fetcher.source_name,
                            e,
                            exc_info=True,
                        )
            except TimeoutError:
                logger.warning(
                    "DataPipeline hard timeout %.1fs reached "
                    "(success=%d, fail=%d, V3§3.1 line 329)",
                    self._hard_timeout_s,
                    success_count,
                    fail_count,
                )

        deduped = self._dedup_items(all_items)

        if total_limit is not None and total_limit > 0:
            deduped = deduped[:total_limit]

        logger.info(
            "DataPipeline aggregate: raw=%d deduped=%d "
            "(success_sources=%d, fail_sources=%d)",
            len(all_items),
            len(deduped),
            success_count,
            fail_count,
        )
        return deduped

    @staticmethod
    def _safe_fetch(
        fetcher: NewsFetcher, query: str, limit: int
    ) -> list[NewsItem]:
        """ThreadPool worker — 直接 raise NewsFetchError, caller fail-soft."""
        return fetcher.fetch(query=query, limit=limit)

    @staticmethod
    def _dedup_items(items: list[NewsItem]) -> list[NewsItem]:
        """URL-first + title-hash fallback dedup (DataPipeline-specific extension).

        URL 是 primary dedup key (反复 publish 同 article 跨源时 url 相同 + RSSHub 时
        url 可能 None 走 title fallback). title 走 strip().lower() 弱化空白/大小写差异.

        Args:
            items: 6 源 raw aggregate.

        Returns:
            list[NewsItem] — dedup 后 (沿用第 1 次 occurrence, 沿用 V3§3.1 0 显式
            "保留 multi-source 重复" 真预约 → 单 source 第 1 次 sustained).
        """
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        deduped: list[NewsItem] = []
        for item in items:
            title_key = item.title.strip().lower() if item.title else ""
            if not title_key:
                continue  # title empty 跳 (反 NewsItem 真预约 title required)
            if item.url and item.url in seen_urls:
                continue
            if title_key in seen_titles:
                continue
            if item.url:
                seen_urls.add(item.url)
            seen_titles.add(title_key)
            deduped.append(item)
        return deduped
