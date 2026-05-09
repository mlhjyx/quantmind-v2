"""AKShare cninfo announcement fetcher (sub-PR 13 sediment per ADR-052 reverse ADR-049 §1 Decision 3).

V3 §11.1 row 5 公告流 ingest 反**RSSHub route reuse** (ADR-049 §1 Decision 3) — 真值 verified
broken via sub-PR 13 Phase 0 active discovery (LL-142 sediment): local RSSHub instance does NOT
expose `/cninfo/announcement/*` routes (HTTP 404 across 5 variants probed) AND upstream
`rsshub.app` HTTP 403 blocks production usage (per RSSHub upstream policy 2025-10+ enforcement).

**Reverse decision** (ADR-052 sediment): switch to **AKShare direct API** for cninfo announcement
ingest — sustained `akshare 1.18.55` already installed in `.venv` (verified Phase 0) +
`stock_zh_a_disclosure_report_cninfo` returns real disclosure data with announcementId/orgId
preserved in URL (cninfo.com.cn canonical detail link).

AKShare API signature (verified Phase 0 fresh probe 2026-05-09):
    ak.stock_zh_a_disclosure_report_cninfo(
        symbol: str = '000001',           # stock code (6 digit)
        market: str = '沪深京',           # 沪深京 / 港股 / 新三板 / fund
        keyword: str = '',                # title keyword filter (optional)
        category: str = '',               # 年报 / 半年报 / 季报 / 重大事项 / etc (optional)
        start_date: str = '20230618',     # YYYYMMDD inclusive
        end_date: str = '20231219',       # YYYYMMDD inclusive
    ) -> pd.DataFrame
    Returns columns: 代码 / 简称 / 公告标题 / 公告时间 / 公告链接

Real-data 真测 (2026-05-09, sub-PR 13 Phase 0 verify, 600519=贵州茅台):
- 2026-04-01 ~ 2026-05-09 → 30 rows (含 5/8 回购股份实施进展 / 4/29 业绩说明会 / 4/25 一季报 / 等)
- 2025-01-01 ~ 2025-06-30 → 47 rows (含权益分派/差异化权益分派/利润分配方案/回购股份)
- category='年报' filter → 3 rows (年报 + 英文版 + 摘要)

设计原则 (沿用 sub-PR 1-7c plugin precedent + 反 abstraction premature post-真值-evidence):
- Implements `NewsFetcher` ABC (沿用 base.py:67 contract, source_name="cninfo")
- query 真值 = `symbol_id` (6 digit stock code) — 反 RSSHub route_path semantic (ADR-049 §1 Decision 3
  reverse 真值 evidence). caller `AnnouncementProcessor.ingest(symbol_id, ...)` 直 pass.
- date range default = last 30d rolling (反 over-fetch + AKShare API server load 友善)
- fail-loud: AKShare exceptions raised as `NewsFetchError` (沿用铁律 33 + sub-PR 1-6 体例)
- 0 retry (AKShare 自带 tqdm progress + cninfo backend retry, 反 retry 重叠)
- timestamp tz-aware (Asia/Shanghai → UTC, 沿用铁律 41)

关联铁律: 17 (DataPipeline 入库) / 31 (Engine 纯计算) / 33 (fail-loud NewsFetchError) /
          41 (timezone tz-aware) / 45 (4 doc fresh read SOP)
关联 ADR: ADR-049 §1 Decision 3 amendment (RSSHub route reuse 真值 verified broken) /
          ADR-052 (AKShare reverse decision NEW)
关联 LL: LL-142 (RSSHub spec gap silent miss 第 2 case + LL-141 reverse case 第 1 实证)
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .base import NewsFetcher, NewsFetchError, NewsItem

logger = logging.getLogger(__name__)


SOURCE_NAME = "cninfo"
DEFAULT_MARKET = "沪深京"
DEFAULT_LOOKBACK_DAYS = 30  # rolling window for fresh announcement ingest (反 over-fetch)
ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _format_date(d: datetime) -> str:
    """YYYYMMDD per AKShare API contract."""
    return d.strftime("%Y%m%d")


class AkshareCninfoFetcher(NewsFetcher):
    """V3 §S2.5 cninfo announcement fetcher via AKShare (sub-PR 13 sediment per ADR-052).

    Args:
        market: AKShare market enum (default 沪深京 = SSE/SZSE/BJSE A-shares).
        lookback_days: rolling date window for fetch (default 30d, 反 over-fetch).
        category: AKShare category filter (default '' = all categories, ADR-052 §category-filter
                  decision deferred to sub-PR 14+ post-真值-traffic-evidence).

    Note:
        fetch(query="<symbol_id>") 真**stock code 6-digit string** (反 RSSHub route_path semantic
        sub-PR 6 体例 reverse, ADR-049 §1 Decision 3 amendment 真值 evidence). caller
        `AnnouncementProcessor.ingest(symbol_id, source="cninfo", ...)` 直 pass symbol_id.

    Example:
        >>> fetcher = AkshareCninfoFetcher()
        >>> items = fetcher.fetch(query="600519", limit=10)
        >>> for item in items:
        ...     print(item.title, item.timestamp.date(), item.url)
    """

    source_name = SOURCE_NAME

    def __init__(
        self,
        *,
        market: str = DEFAULT_MARKET,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        category: str = "",
    ) -> None:
        self.market = market
        self.lookback_days = lookback_days
        self.category = category

    def fetch(self, *, query: str, limit: int = 10) -> list[NewsItem]:
        """Fetch cninfo announcements for stock symbol via AKShare.

        Args:
            query: stock code 6-digit string (e.g. "600519" 贵州茅台).
            limit: max NewsItem returned (反 over-fetch, default 10).

        Returns:
            list[NewsItem] (newest first, sorted by 公告时间 desc).

        Raises:
            NewsFetchError: AKShare API failure / DataFrame schema drift / column missing
                            (沿用铁律 33 fail-loud + caller fail-soft per V3 §3.5).
        """
        # Defer akshare import to call time (沿用 sub-PR 1-6 lazy import 体例 反 startup cost)
        try:
            import akshare as ak
        except ImportError as e:
            raise NewsFetchError(
                source=SOURCE_NAME,
                message="akshare package not installed in .venv",
                cause=e,
            ) from e

        end_dt = datetime.now(ASIA_SHANGHAI)
        start_dt = end_dt - timedelta(days=self.lookback_days)
        start_str = _format_date(start_dt)
        end_str = _format_date(end_dt)

        t0 = time.monotonic()
        try:
            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=query,
                market=self.market,
                keyword="",
                category=self.category,
                start_date=start_str,
                end_date=end_str,
            )
        except Exception as e:
            raise NewsFetchError(
                source=SOURCE_NAME,
                message=(
                    f"AKShare stock_zh_a_disclosure_report_cninfo failed for symbol={query!r} "
                    f"market={self.market!r} range={start_str}~{end_str}: {type(e).__name__}: {e}"
                ),
                cause=e,
            ) from e

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if df is None or len(df) == 0:
            logger.info(
                "AKShare cninfo 0 rows for symbol=%s range=%s~%s (data condition, NOT route fail)",
                query,
                start_str,
                end_str,
            )
            return []

        # Schema verify (反 silent column drift per LL-141 reverse case 体例)
        required_cols = {"代码", "简称", "公告标题", "公告时间", "公告链接"}
        missing = required_cols - set(df.columns)
        if missing:
            raise NewsFetchError(
                source=SOURCE_NAME,
                message=(
                    f"AKShare DataFrame schema drift — missing columns {missing} for symbol={query!r} "
                    f"(got columns: {list(df.columns)})"
                ),
            )

        # Sort by 公告时间 desc + take top `limit`
        df_sorted = df.sort_values("公告时间", ascending=False).head(limit)

        items: list[NewsItem] = []
        for _, row in df_sorted.iterrows():
            timestamp = self._parse_timestamp(row["公告时间"])
            items.append(
                NewsItem(
                    source=SOURCE_NAME,
                    timestamp=timestamp,
                    title=str(row["公告标题"]),
                    content=None,  # AKShare 0 content snippet (反 RsshubNewsFetcher feedparser content)
                    url=str(row["公告链接"]) if row["公告链接"] else None,
                    lang="zh",
                    symbol_id=str(row["代码"]),
                    fetch_cost_usd=Decimal("0"),  # AKShare free
                    fetch_latency_ms=elapsed_ms,
                )
            )

        logger.info(
            "AKShare cninfo %d items for symbol=%s range=%s~%s elapsed_ms=%d",
            len(items),
            query,
            start_str,
            end_str,
            elapsed_ms,
        )
        return items

    @staticmethod
    def _parse_timestamp(raw: object) -> datetime:
        """Parse AKShare 公告时间 column to tz-aware UTC datetime (沿用铁律 41).

        AKShare returns '公告时间' as either:
        - pandas Timestamp (most common)
        - str like '2026-04-25 00:00:00' (Asia/Shanghai naive)
        Both interpreted as Asia/Shanghai naive → convert to UTC tz-aware.
        """
        # pandas Timestamp has .to_pydatetime() / 0-tz string is parseable
        if hasattr(raw, "to_pydatetime"):
            naive = raw.to_pydatetime()
        elif isinstance(raw, str):
            # AKShare format: '2026-04-25 00:00:00' or '2026-04-25'
            try:
                naive = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                naive = datetime.strptime(raw, "%Y-%m-%d")
        elif isinstance(raw, datetime):
            naive = raw
        else:
            raise NewsFetchError(
                source=SOURCE_NAME,
                message=f"AKShare 公告时间 type unexpected: {type(raw).__name__} value={raw!r}",
            )

        # If naive, attach Asia/Shanghai then convert to UTC; if aware, just convert
        if naive.tzinfo is None:
            sh_aware = naive.replace(tzinfo=ASIA_SHANGHAI)
        else:
            sh_aware = naive
        return sh_aware.astimezone(UTC)
