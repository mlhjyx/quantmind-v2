"""Unit tests for AkshareValuationFetcher (sub-PR 14 sediment per ADR-053).

scope (沿用 sub-PR 13 test_akshare_cninfo precedent):
- AKShare API mock (反 actual cninfo HTTP call in unit test, defer to integration smoke)
- DataFrame schema verify (反 silent column drift per LL-141/142 reverse case 体例)
- Empty result handling (FundamentalFetchError raised vs sub-PR 13 cninfo empty list)
- Schema drift detection (column missing → FundamentalFetchError)
- date parse: pandas Timestamp / str / datetime.date variants
- ImportError path (sustained sub-PR 13 P3.3 ride-next finding 体例)
- _safe_float NaN / None / non-numeric handling

关联铁律: 33 (fail-loud FundamentalFetchError) / 41 (timezone date) / 45 (4 doc fresh read SOP)
关联 ADR: ADR-053 (V3 §S4 (minimal) architecture + AKShare 1 source decision)
关联 LL: LL-144 (S4 minimal scope sub-PR 14 sediment + sub-PR 15+ expansion 体例)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.qm_platform.data.fundamental.akshare_valuation import (
    SOURCE_NAME,
    AkshareValuationFetcher,
    FundamentalFetchError,
    ValuationContext,
    _safe_float,
)


def _make_akshare_value_df(rows: list[dict]) -> pd.DataFrame:
    cols = [
        "数据日期",
        "当日收盘价",
        "当日涨跌幅",
        "总市值",
        "流通市值",
        "总股本",
        "流通股本",
        "PE(TTM)",
        "PE(静)",
        "市净率",
        "PEG值",
        "市现率",
        "市销率",
    ]
    return pd.DataFrame(rows, columns=cols)


# §1 fetch() success path


class TestAkshareValuationFetcherFetch:
    """AkshareValuationFetcher.fetch — full path with mocked akshare module."""

    def test_fetch_real_data_path(self) -> None:
        rows = [
            {
                "数据日期": "2026-05-08",
                "当日收盘价": 1372.99,
                "当日涨跌幅": 0.14,
                "总市值": 1.72e12,
                "流通市值": 1.72e12,
                "总股本": 1.25e9,
                "流通股本": 1.25e9,
                "PE(TTM)": 20.79,
                "PE(静)": 20.89,
                "市净率": 6.35,
                "PEG值": -5.02,
                "市现率": 21.59,
                "市销率": 9.81,
            },
            {
                "数据日期": "2026-05-07",
                "当日收盘价": 1371.05,
                "当日涨跌幅": -0.29,
                "总市值": 1.72e12,
                "流通市值": 1.72e12,
                "总股本": 1.25e9,
                "流通股本": 1.25e9,
                "PE(TTM)": 20.76,
                "PE(静)": 20.86,
                "市净率": 6.34,
                "PEG值": -5.01,
                "市现率": 21.56,
                "市销率": 9.79,
            },
        ]
        df = _make_akshare_value_df(rows)

        mock_ak = MagicMock()
        mock_ak.stock_value_em = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareValuationFetcher()
            ctx = f.fetch(symbol_id="600519")

        # Latest row (2026-05-08, sorted desc)
        assert ctx.symbol_id == "600519"
        assert ctx.date == date(2026, 5, 8)
        assert ctx.valuation["pe_ttm"] == 20.79
        assert ctx.valuation["pe_static"] == 20.89
        assert ctx.valuation["pb"] == 6.35
        assert ctx.valuation["peg"] == -5.02
        assert ctx.valuation["pcf"] == 21.59
        assert ctx.valuation["ps"] == 9.81
        assert ctx.valuation["market_cap_total"] == 1.72e12
        assert ctx.valuation["market_cap_float"] == 1.72e12
        assert ctx.fetch_cost == Decimal("0")
        assert ctx.fetch_latency_ms >= 0

    def test_fetch_empty_dataframe_raises(self) -> None:
        df = _make_akshare_value_df([])
        mock_ak = MagicMock()
        mock_ak.stock_value_em = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareValuationFetcher()
            with pytest.raises(FundamentalFetchError, match=r"returned 0 rows"):
                f.fetch(symbol_id="999999")

    def test_fetch_none_dataframe_raises(self) -> None:
        mock_ak = MagicMock()
        mock_ak.stock_value_em = MagicMock(return_value=None)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareValuationFetcher()
            with pytest.raises(FundamentalFetchError, match=r"returned 0 rows"):
                f.fetch(symbol_id="600519")

    def test_fetch_picks_latest_by_date_desc(self) -> None:
        # Out-of-order rows — sort_values must put latest first
        rows = [
            {
                "数据日期": "2026-04-15",
                "当日收盘价": 1300.0,
                "当日涨跌幅": 0.0,
                "总市值": 1.6e12,
                "流通市值": 1.6e12,
                "总股本": 1.25e9,
                "流通股本": 1.25e9,
                "PE(TTM)": 19.5,
                "PE(静)": 19.6,
                "市净率": 6.0,
                "PEG值": -4.9,
                "市现率": 20.0,
                "市销率": 9.5,
            },
            {
                "数据日期": "2026-05-08",  # latest
                "当日收盘价": 1372.99,
                "当日涨跌幅": 0.14,
                "总市值": 1.72e12,
                "流通市值": 1.72e12,
                "总股本": 1.25e9,
                "流通股本": 1.25e9,
                "PE(TTM)": 20.79,
                "PE(静)": 20.89,
                "市净率": 6.35,
                "PEG值": -5.02,
                "市现率": 21.59,
                "市销率": 9.81,
            },
        ]
        df = _make_akshare_value_df(rows)

        mock_ak = MagicMock()
        mock_ak.stock_value_em = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareValuationFetcher()
            ctx = f.fetch(symbol_id="600519")

        assert ctx.date == date(2026, 5, 8)
        assert ctx.valuation["pe_ttm"] == 20.79


# §2 fetch() failure paths


class TestAkshareValuationFetcherFailures:
    """fetch — fail-loud FundamentalFetchError per 铁律 33."""

    def test_fetch_api_exception_raises(self) -> None:
        mock_ak = MagicMock()
        mock_ak.stock_value_em = MagicMock(side_effect=RuntimeError("HTTP 500 EM backend timeout"))

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareValuationFetcher()
            with pytest.raises(FundamentalFetchError, match=r"AKShare stock_value_em failed"):
                f.fetch(symbol_id="600519")

    def test_fetch_schema_drift_missing_column_raises(self) -> None:
        df = pd.DataFrame([{"数据日期": "2026-05-08", "PE(TTM)": 20.79}])

        mock_ak = MagicMock()
        mock_ak.stock_value_em = MagicMock(return_value=df)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            f = AkshareValuationFetcher()
            with pytest.raises(FundamentalFetchError, match=r"schema drift"):
                f.fetch(symbol_id="600519")

    def test_fetch_import_error_raises(self) -> None:
        # Sustained sub-PR 13 P3.3 ride-next finding fix体例 — test ImportError path.
        # patch.dict cannot directly cause ImportError; use builtins.__import__ instead.
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "akshare":
                raise ImportError("No module named 'akshare'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            f = AkshareValuationFetcher()
            with pytest.raises(FundamentalFetchError, match=r"akshare package not installed"):
                f.fetch(symbol_id="600519")


# §3 _parse_date helpers


class TestParseDate:
    """date parse — pandas Timestamp / str / datetime.date / unexpected type."""

    def test_parse_date_pandas_timestamp(self) -> None:
        ts = pd.Timestamp("2026-05-08")
        d = AkshareValuationFetcher._parse_date(ts)
        assert d == date(2026, 5, 8)

    def test_parse_date_string(self) -> None:
        d = AkshareValuationFetcher._parse_date("2026-05-08")
        assert d == date(2026, 5, 8)

    def test_parse_date_datetime_date(self) -> None:
        d = AkshareValuationFetcher._parse_date(date(2026, 5, 8))
        assert d == date(2026, 5, 8)

    def test_parse_date_datetime_passthrough(self) -> None:
        # datetime has .date() method → caught by hasattr branch
        dt = datetime(2026, 5, 8, 16, 0, 0)
        d = AkshareValuationFetcher._parse_date(dt)
        assert d == date(2026, 5, 8)

    def test_parse_date_unexpected_type_raises(self) -> None:
        with pytest.raises(FundamentalFetchError, match=r"数据日期 type unexpected"):
            AkshareValuationFetcher._parse_date(12345)


# §4 _safe_float


class TestSafeFloat:
    """_safe_float — NaN / None / non-numeric → None (反 NaN 入库 per 铁律 29)."""

    def test_safe_float_normal(self) -> None:
        assert _safe_float(20.79) == 20.79
        assert _safe_float(0) == 0.0
        assert _safe_float(-5.02) == -5.02

    def test_safe_float_nan_returns_none(self) -> None:
        nan = float("nan")
        assert _safe_float(nan) is None

    def test_safe_float_none_returns_none(self) -> None:
        assert _safe_float(None) is None

    def test_safe_float_non_numeric_returns_none(self) -> None:
        assert _safe_float("abc") is None
        assert _safe_float({"x": 1}) is None


# §5 ValuationContext dataclass + SOURCE_NAME


def test_source_name() -> None:
    assert SOURCE_NAME == "akshare_valuation"
    assert AkshareValuationFetcher.source_name == "akshare_valuation"


def test_valuation_context_frozen() -> None:
    ctx = ValuationContext(
        date=date(2026, 5, 8),
        symbol_id="600519",
        valuation={"pe_ttm": 20.79},
        fetch_cost=Decimal("0"),
        fetch_latency_ms=15,
    )
    # frozen dataclass with slots=True — assigning raises FrozenInstanceError or AttributeError
    from dataclasses import FrozenInstanceError

    with pytest.raises((FrozenInstanceError, AttributeError)):
        ctx.symbol_id = "000001"  # type: ignore[misc]
