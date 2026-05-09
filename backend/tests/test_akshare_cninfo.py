"""Unit tests for AkshareCninfoFetcher (sub-PR 13 sediment per ADR-052 reverse decision).

scope (沿用 sub-PR 6 RsshubNewsFetcher precedent + 反 real AKShare API call in unit tests):
- AKShare API mock (反 actual cninfo.com.cn HTTP call in unit test, defer to integration smoke)
- DataFrame schema verify (反 silent column drift per LL-141 reverse case 体例)
- Empty result handling (data condition vs API failure)
- Schema drift detection (KeyError / column missing)
- timestamp tz-aware conversion (Asia/Shanghai naive → UTC)
- limit truncation (sort_values('公告时间', desc) + .head(limit))

关联铁律: 33 (fail-loud NewsFetchError) / 41 (timezone tz-aware) / 45 (4 doc fresh read SOP)
关联 ADR: ADR-052 (AKShare reverse decision NEW) / ADR-049 §1 Decision 3 amendment
关联 LL: LL-142 (RSSHub spec gap silent miss 第 2 case)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backend.qm_platform.news.akshare_cninfo import (
    ASIA_SHANGHAI,
    DEFAULT_LOOKBACK_DAYS,
    SOURCE_NAME,
    AkshareCninfoFetcher,
    _format_date,
)
from backend.qm_platform.news.base import NewsFetchError, NewsItem


def _make_akshare_df(rows: list[dict]) -> pd.DataFrame:
    """Helper: build pandas DataFrame matching AKShare stock_zh_a_disclosure_report_cninfo schema."""
    return pd.DataFrame(rows, columns=["代码", "简称", "公告标题", "公告时间", "公告链接"])


# §1 Constructor + defaults


class TestAkshareCninfoFetcherInit:
    """AkshareCninfoFetcher.__init__ — defaults + override."""

    def test_default_init(self) -> None:
        f = AkshareCninfoFetcher()
        assert f.source_name == SOURCE_NAME == "cninfo"
        assert f.market == "沪深京"
        assert f.lookback_days == DEFAULT_LOOKBACK_DAYS == 30
        assert f.category == ""

    def test_custom_init(self) -> None:
        f = AkshareCninfoFetcher(market="港股", lookback_days=7, category="年报")
        assert f.market == "港股"
        assert f.lookback_days == 7
        assert f.category == "年报"


# §2 fetch() success path


class TestAkshareCninfoFetcherFetch:
    """AkshareCninfoFetcher.fetch — full path with mocked akshare module."""

    def test_fetch_real_data_path(self) -> None:
        rows = [
            {
                "代码": "600519",
                "简称": "贵州茅台",
                "公告标题": "贵州茅台关于回购股份实施进展的公告",
                "公告时间": "2026-05-08 00:00:00",
                "公告链接": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=600519&announcementId=1234567890&orgId=gssh0600519",
            },
            {
                "代码": "600519",
                "简称": "贵州茅台",
                "公告标题": "贵州茅台 2026 年第一季度报告",
                "公告时间": "2026-04-25 00:00:00",
                "公告链接": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=600519&announcementId=1234567891&orgId=gssh0600519",
            },
        ]
        df = _make_akshare_df(rows)

        mock_ak = MagicMock()
        mock_ak.stock_zh_a_disclosure_report_cninfo = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareCninfoFetcher()
            items = f.fetch(query="600519", limit=10)

        assert len(items) == 2
        # Sort desc by 公告时间 — 5-08 first, 4-25 second
        assert items[0].title == "贵州茅台关于回购股份实施进展的公告"
        assert items[1].title == "贵州茅台 2026 年第一季度报告"
        # All items: source / lang / symbol_id
        for item in items:
            assert item.source == "cninfo"
            assert item.lang == "zh"
            assert item.symbol_id == "600519"
            assert item.url is not None and "cninfo.com.cn" in item.url

    def test_fetch_empty_result_returns_empty_list(self) -> None:
        """0 rows is data condition (反 schema drift, sustained LL-142 reverse case 体例)."""
        df = _make_akshare_df([])

        mock_ak = MagicMock()
        mock_ak.stock_zh_a_disclosure_report_cninfo = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareCninfoFetcher()
            items = f.fetch(query="000001", limit=10)

        assert items == []

    def test_fetch_none_result_returns_empty_list(self) -> None:
        """AKShare may return None on edge cases — handle gracefully (sustained 铁律 33 nuance)."""
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_disclosure_report_cninfo = MagicMock(return_value=None)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareCninfoFetcher()
            items = f.fetch(query="600519", limit=10)

        assert items == []

    def test_fetch_limit_truncation(self) -> None:
        rows = [
            {
                "代码": "600519",
                "简称": "贵州茅台",
                "公告标题": f"公告 {i}",
                "公告时间": f"2026-04-{i:02d} 00:00:00",
                "公告链接": f"http://example.com/{i}",
            }
            for i in range(1, 11)  # 10 rows
        ]
        df = _make_akshare_df(rows)

        mock_ak = MagicMock()
        mock_ak.stock_zh_a_disclosure_report_cninfo = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareCninfoFetcher()
            items = f.fetch(query="600519", limit=3)

        assert len(items) == 3
        # Sorted desc by 公告时间: 2026-04-10, 2026-04-09, 2026-04-08
        assert items[0].title == "公告 10"
        assert items[1].title == "公告 9"
        assert items[2].title == "公告 8"


# §3 fetch() failure paths


class TestAkshareCninfoFetcherFailures:
    """AkshareCninfoFetcher.fetch — fail-loud NewsFetchError per 铁律 33."""

    def test_fetch_akshare_api_exception_raises_news_fetch_error(self) -> None:
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_disclosure_report_cninfo = MagicMock(
            side_effect=RuntimeError("HTTP 500 cninfo backend timeout")
        )

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareCninfoFetcher()
            with pytest.raises(NewsFetchError, match=r"AKShare stock_zh_a_disclosure"):
                f.fetch(query="600519", limit=10)

    def test_fetch_schema_drift_missing_column_raises(self) -> None:
        # Missing 公告链接 column — schema drift 反 silent skip per LL-141 reverse case
        df = pd.DataFrame(
            [{"代码": "600519", "简称": "贵州茅台", "公告标题": "x", "公告时间": "2026-04-25"}]
        )

        mock_ak = MagicMock()
        mock_ak.stock_zh_a_disclosure_report_cninfo = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareCninfoFetcher()
            with pytest.raises(NewsFetchError, match=r"schema drift"):
                f.fetch(query="600519", limit=10)

    def test_fetch_import_error_raises(self) -> None:
        # sub-PR 14 ride-next P3.3 reviewer fix per ADR-053 — test ImportError fail-loud path.
        # patch.dict cannot directly cause ImportError; use builtins.__import__ instead.
        import builtins
        from unittest.mock import patch as _patch

        original_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "akshare":
                raise ImportError("No module named 'akshare'")
            return original_import(name, *args, **kwargs)

        with _patch.object(builtins, "__import__", side_effect=mock_import):
            f = AkshareCninfoFetcher()
            with pytest.raises(NewsFetchError, match=r"akshare package not installed"):
                f.fetch(query="600519", limit=10)


# §4 _parse_timestamp + _format_date helpers


class TestTimestampHelpers:
    """Timezone correctness — sustained 铁律 41 tz-aware UTC + Asia/Shanghai."""

    def test_format_date(self) -> None:
        dt = datetime(2026, 5, 9, 12, 30, 0)
        assert _format_date(dt) == "20260509"

    def test_parse_timestamp_string_full(self) -> None:
        ts = AkshareCninfoFetcher._parse_timestamp("2026-04-25 14:30:00")
        # 14:30 Asia/Shanghai = 06:30 UTC
        assert ts.tzinfo == UTC
        assert ts.year == 2026 and ts.month == 4 and ts.day == 25
        assert ts.hour == 6 and ts.minute == 30

    def test_parse_timestamp_string_date_only(self) -> None:
        ts = AkshareCninfoFetcher._parse_timestamp("2026-04-25")
        # 00:00 Asia/Shanghai = 16:00 UTC previous day
        assert ts.tzinfo == UTC
        assert ts.year == 2026 and ts.month == 4 and ts.day == 24
        assert ts.hour == 16

    def test_parse_timestamp_pandas_timestamp(self) -> None:
        ts_pd = pd.Timestamp("2026-04-25 09:00:00")
        ts = AkshareCninfoFetcher._parse_timestamp(ts_pd)
        # 09:00 Asia/Shanghai = 01:00 UTC
        assert ts.tzinfo == UTC
        assert ts.hour == 1

    def test_parse_timestamp_aware_datetime_passthrough(self) -> None:
        # If already tz-aware, just convert
        dt_aware = datetime(2026, 4, 25, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        ts = AkshareCninfoFetcher._parse_timestamp(dt_aware)
        assert ts.tzinfo == UTC
        assert ts.hour == 2  # 10:00 SH = 02:00 UTC

    def test_parse_timestamp_unexpected_type_raises(self) -> None:
        with pytest.raises(NewsFetchError, match=r"公告时间 type unexpected"):
            AkshareCninfoFetcher._parse_timestamp(12345)


# §5 ASIA_SHANGHAI sanity


def test_asia_shanghai_zone() -> None:
    assert ASIA_SHANGHAI.key == "Asia/Shanghai"


# §6 NewsFetcher ABC contract


class TestNewsFetcherContract:
    """AkshareCninfoFetcher implements NewsFetcher abc + returns NewsItem dataclass."""

    def test_fetcher_is_news_fetcher_subclass(self) -> None:
        from backend.qm_platform.news.base import NewsFetcher

        assert issubclass(AkshareCninfoFetcher, NewsFetcher)

    def test_fetch_returns_news_item_instances(self) -> None:
        df = _make_akshare_df(
            [
                {
                    "代码": "600519",
                    "简称": "贵州茅台",
                    "公告标题": "test",
                    "公告时间": "2026-04-25 00:00:00",
                    "公告链接": "http://example.com/1",
                }
            ]
        )

        mock_ak = MagicMock()
        mock_ak.stock_zh_a_disclosure_report_cninfo = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareCninfoFetcher()
            items = f.fetch(query="600519", limit=10)

        assert len(items) == 1
        assert isinstance(items[0], NewsItem)
        assert items[0].fetch_cost_usd == 0  # AKShare free
