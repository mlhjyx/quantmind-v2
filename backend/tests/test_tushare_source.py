"""MVP 2.1b Sub-commit 3 — TushareDataSource 单测.

Mock TushareAPI.query (无 TUSHARE_TOKEN / 无网络).
覆盖 3 contract dispatch + board 识别 + value_ranges + fail-loud.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.platform.data.base_source import ContractViolation
from backend.platform.data.interface import DataContract
from backend.platform.data.sources.tushare_source import (
    DAILY_BASIC_DATA_CONTRACT,
    KLINES_DAILY_DATA_CONTRACT,
    MONEYFLOW_DATA_CONTRACT,
    TushareDataSource,
    _board_from_ts_code,
)

# ---------- Fake TushareAPI ----------


class _FakeTushareClient:
    """Stand-in for TushareAPI — 只需 query(api_name, **kwargs) → DataFrame."""

    def __init__(
        self,
        responses: dict[tuple[str, str], pd.DataFrame] | None = None,
        raise_on_api: str | None = None,
    ) -> None:
        """responses key = (api_name, trade_date_str), value = DataFrame."""
        self._responses = responses or {}
        self._raise_on = raise_on_api
        self.query_calls: list[dict] = []

    def query(self, api_name: str, **kwargs) -> pd.DataFrame:
        self.query_calls.append({"api": api_name, **kwargs})
        if api_name == self._raise_on:
            raise ConnectionError(f"Tushare {api_name} rate limit")
        td = kwargs.get("trade_date", "")
        df = self._responses.get((api_name, td))
        if df is None:
            return pd.DataFrame()  # 空帧 = 该日无数据 (停市 / 跳过)
        return df.copy()


def _klines_frame(ts_codes: list[str], td: str) -> pd.DataFrame:
    """构造 Tushare daily endpoint 样板 DataFrame."""
    return pd.DataFrame(
        {
            "ts_code": ts_codes,
            "trade_date": [td] * len(ts_codes),
            "open": [10.0] * len(ts_codes),
            "high": [10.5] * len(ts_codes),
            "low": [9.9] * len(ts_codes),
            "close": [10.2] * len(ts_codes),
            "pre_close": [10.0] * len(ts_codes),
            "change": [0.2] * len(ts_codes),
            "pct_chg": [2.0] * len(ts_codes),
            "vol": [5000] * len(ts_codes),
            "amount": [5100.0] * len(ts_codes),  # 千元
        }
    )


# ============================================================
# Constructor
# ============================================================


def test_constructor_rejects_none_client() -> None:
    with pytest.raises(ValueError, match=r"client 不可为 None"):
        TushareDataSource(client=None)


def test_constructor_rejects_client_without_query() -> None:
    class _Bad:
        pass

    with pytest.raises(TypeError, match=r"缺少 query 方法"):
        TushareDataSource(client=_Bad())


# ============================================================
# Contract dispatch
# ============================================================


def test_unsupported_contract_raises_value_error() -> None:
    src = TushareDataSource(client=_FakeTushareClient(), end=date(2026, 4, 15))
    bogus = DataContract(
        name="unknown_endpoint",
        version="v1",
        schema={},
        primary_key=(),
        source="tushare",
        unit_convention={},
    )
    with pytest.raises(ValueError, match=r"不支持 contract="):
        src._fetch_raw(bogus, since=date(2026, 4, 15))


# ============================================================
# klines_daily
# ============================================================


def _adj_frame(ts_codes: list[str], td: str, factors: list[float] | None = None) -> pd.DataFrame:
    """构造 Tushare adj_factor endpoint 样板."""
    return pd.DataFrame(
        {
            "ts_code": ts_codes,
            "trade_date": [td] * len(ts_codes),
            "adj_factor": factors or [1.5] * len(ts_codes),
        }
    )


def _stk_limit_frame(
    ts_codes: list[str], td: str, up: list[float] | None = None, down: list[float] | None = None
) -> pd.DataFrame:
    """构造 Tushare stk_limit endpoint 样板."""
    return pd.DataFrame(
        {
            "ts_code": ts_codes,
            "trade_date": [td] * len(ts_codes),
            "up_limit": up or [11.0] * len(ts_codes),
            "down_limit": down or [9.0] * len(ts_codes),
        }
    )


def test_fetch_klines_daily_single_day() -> None:
    """MVP 2.1c Sub3-prep: 单日 klines 走 3 API 合并, 全绿."""
    td = "20260415"
    responses = {
        ("daily", td): _klines_frame(["600519.SH", "000001.SZ"], td),
        ("adj_factor", td): _adj_frame(["600519.SH", "000001.SZ"], td, [2.5, 1.2]),
        ("stk_limit", td): _stk_limit_frame(
            ["600519.SH", "000001.SZ"], td, [11.22, 13.22], [9.18, 10.82]
        ),
    }
    client = _FakeTushareClient(responses=responses)
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    df = src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))

    assert len(df) == 2
    assert set(df["ts_code"]) == {"600519.SH", "000001.SZ"}
    # 列对齐 contract.schema (14 列, 含 3 新字段)
    assert set(df.columns) == set(KLINES_DAILY_DATA_CONTRACT.schema.keys())
    # 单位 RAW (千元 未转换, vol 手未转换)
    assert df.iloc[0]["amount"] == 5100.0
    assert df.iloc[0]["vol"] == 5000
    # 3 新字段合并生效
    row_600519 = df[df["ts_code"] == "600519.SH"].iloc[0]
    assert row_600519["adj_factor"] == 2.5
    assert row_600519["up_limit"] == 11.22
    assert row_600519["down_limit"] == 9.18
    # 1 天 × 3 API = 3 次 query
    assert len(client.query_calls) == 3


def test_fetch_klines_daily_multi_day() -> None:
    """MVP 2.1c Sub3-prep: 3 天 klines × 3 API = 9 次 query."""
    responses = {}
    for td in ("20260413", "20260414", "20260415"):
        responses[("daily", td)] = _klines_frame(["600519.SH"], td)
        responses[("adj_factor", td)] = _adj_frame(["600519.SH"], td)
        responses[("stk_limit", td)] = _stk_limit_frame(["600519.SH"], td)
    client = _FakeTushareClient(responses=responses)
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    df = src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 13))
    assert len(df) == 3  # 3 天
    assert len(client.query_calls) == 9  # 3 天 × 3 API


def test_fetch_klines_empty_result_returns_schema_frame() -> None:
    """Tushare 周末 / 空响应 → empty DataFrame 列对齐."""
    client = _FakeTushareClient(responses={})  # 全空
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    df = src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))
    assert df.empty
    assert set(df.columns) == set(KLINES_DAILY_DATA_CONTRACT.schema.keys())


def test_fetch_klines_tushare_raises_propagates() -> None:
    client = _FakeTushareClient(raise_on_api="daily")
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    with pytest.raises(RuntimeError, match=r"Tushare daily 查询"):
        src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))


def test_since_greater_than_end_raises() -> None:
    client = _FakeTushareClient()
    src = TushareDataSource(client=client, end=date(2026, 4, 10))
    with pytest.raises(ValueError, match=r"since=.* > end="):
        src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))


# ============================================================
# daily_basic
# ============================================================


def test_fetch_daily_basic() -> None:
    df_mock = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "trade_date": ["20260415"],
            "close": [1650.5],
            "turnover_rate": [0.5],
            "turnover_rate_f": [0.6],
            "volume_ratio": [1.2],
            "pe": [30.0],
            "pe_ttm": [32.0],
            "pb": [8.0],
            "ps": [10.0],
            "ps_ttm": [10.5],
            "dv_ratio": [1.5],
            "dv_ttm": [1.6],
            "total_share": [1250000.0],  # 万股
            "float_share": [1250000.0],
            "free_share": [1200000.0],
            "total_mv": [20000000.0],  # 万元
            "circ_mv": [20000000.0],
        }
    )
    client = _FakeTushareClient(responses={("daily_basic", "20260415"): df_mock})
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    df = src.fetch(DAILY_BASIC_DATA_CONTRACT, since=date(2026, 4, 15))
    assert len(df) == 1
    assert df.iloc[0]["pe"] == 30.0
    assert df.iloc[0]["total_mv"] == 20000000.0


# ============================================================
# moneyflow
# ============================================================


def test_fetch_moneyflow() -> None:
    cols = {c: [100] if c.endswith("_vol") else [100.0] for c in MONEYFLOW_DATA_CONTRACT.schema if c not in ("ts_code", "trade_date")}
    cols["ts_code"] = ["600519.SH"]
    cols["trade_date"] = ["20260415"]
    df_mock = pd.DataFrame(cols)
    client = _FakeTushareClient(responses={("moneyflow", "20260415"): df_mock})
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    df = src.fetch(MONEYFLOW_DATA_CONTRACT, since=date(2026, 4, 15))
    assert len(df) == 1
    assert df.iloc[0]["buy_sm_vol"] == 100
    assert df.iloc[0]["net_mf_amount"] == 100.0


# ============================================================
# _check_value_ranges
# ============================================================


def test_check_value_ranges_klines_negative_price() -> None:
    client = _FakeTushareClient()
    src = TushareDataSource(client=client)
    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "open": [10.0],
            "high": [10.5],
            "low": [-5.0],  # 负 low
            "close": [10.2],
            "pre_close": [10.0],
            "vol": [1000],
            "amount": [10000.0],
            "pct_chg": [2.0],
        }
    )
    issues = src._check_value_ranges(df, KLINES_DAILY_DATA_CONTRACT)
    assert any("low" in msg and "< 0" in msg for msg in issues)


def test_check_value_ranges_klines_abnormal_pct_chg() -> None:
    """阈值 Session 5 末放宽 30.5 → 1100 (覆盖新股首日 +1000%+, 过滤真 bug)."""
    client = _FakeTushareClient()
    src = TushareDataSource(client=client)
    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.9],
            "close": [10.2],
            "pre_close": [10.0],
            "vol": [1000],
            "amount": [10000.0],
            "pct_chg": [1500.0],  # 异常 (15x, 超过新股首日极限)
        }
    )
    issues = src._check_value_ranges(df, KLINES_DAILY_DATA_CONTRACT)
    assert any("pct_chg" in msg and "1100" in msg for msg in issues)


# ============================================================
# MVP 2.1c Sub3-prep — 3 API merge 扩展 (5 新 unit + 1 value_range)
# ============================================================


def test_klines_merge_adj_and_limit_missing_apis_use_fallbacks() -> None:
    """MVP 2.1c Sub3-prep: daily 有 / adj_factor + stk_limit 全空 → fallback (1.0 + None)."""
    td = "20260415"
    responses = {
        ("daily", td): _klines_frame(["600519.SH"], td),
        # adj_factor & stk_limit 全不提供 (fake client 返回空 DataFrame)
    }
    client = _FakeTushareClient(responses=responses)
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    df = src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))
    assert len(df) == 1
    row = df.iloc[0]
    # adj_factor 空 API → fallback 1.0 (对齐老 fetcher)
    assert row["adj_factor"] == 1.0
    # stk_limit 空 API → None
    assert pd.isna(row["up_limit"])
    assert pd.isna(row["down_limit"])
    # 当日 3 次 query (daily + adj_factor + stk_limit 都被调 1 次)
    assert len(client.query_calls) == 3


def test_klines_merge_adj_factor_partial_fills_na_with_one() -> None:
    """adj_factor API 覆盖部分 ts_code (left merge 后缺失行 fillna 1.0, 对齐老 fetcher)."""
    td = "20260415"
    responses = {
        ("daily", td): _klines_frame(["600519.SH", "000001.SZ"], td),
        ("adj_factor", td): _adj_frame(["600519.SH"], td, [3.7]),  # 只覆盖 600519
        ("stk_limit", td): _stk_limit_frame(["600519.SH", "000001.SZ"], td),
    }
    client = _FakeTushareClient(responses=responses)
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    df = src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))
    assert len(df) == 2  # daily 2 行全保留 (left merge)
    row_600519 = df[df["ts_code"] == "600519.SH"].iloc[0]
    row_000001 = df[df["ts_code"] == "000001.SZ"].iloc[0]
    assert row_600519["adj_factor"] == 3.7
    # 000001.SZ 不在 adj_factor, merge 后 NA → fillna(1.0)
    assert row_000001["adj_factor"] == 1.0


def test_klines_daily_api_empty_skips_day_no_downstream_queries() -> None:
    """daily API 当日空 (如周末 / 交易中断), 不应调 adj_factor / stk_limit."""
    # 日期 4/13 (周一, 假装 daily 返空), 4/14 有数据
    td_empty = "20260413"
    td_ok = "20260414"
    responses = {
        # 4/13 无 daily (responses 不含 → fake client 返 empty)
        ("daily", td_ok): _klines_frame(["600519.SH"], td_ok),
        ("adj_factor", td_ok): _adj_frame(["600519.SH"], td_ok),
        ("stk_limit", td_ok): _stk_limit_frame(["600519.SH"], td_ok),
    }
    client = _FakeTushareClient(responses=responses)
    src = TushareDataSource(client=client, end=date(2026, 4, 14))
    df = src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 13))
    assert len(df) == 1  # 仅 4/14 有数据
    assert df.iloc[0]["trade_date"] == td_ok
    # Query 次数: 4/13 daily (1) + 4/14 daily/adj/stk (3) = 4
    # 关键: 4/13 daily 空后不应再调 adj/stk
    calls_by_date: dict[str, list[str]] = {}
    for c in client.query_calls:
        calls_by_date.setdefault(c.get("trade_date", ""), []).append(c["api"])
    assert calls_by_date[td_empty] == ["daily"], (
        f"4/13 daily 空后不应调 adj/stk, 实际: {calls_by_date[td_empty]}"
    )
    assert set(calls_by_date[td_ok]) == {"daily", "adj_factor", "stk_limit"}


def test_klines_adj_factor_api_raises_propagates() -> None:
    """adj_factor API 异常 → RuntimeError 含 'Tushare adj_factor 查询'."""
    td = "20260415"
    responses = {
        ("daily", td): _klines_frame(["600519.SH"], td),
    }
    # daily 能返回, adj_factor 调时 raise (通过 raise_on_api)
    client = _FakeTushareClient(responses=responses, raise_on_api="adj_factor")
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    with pytest.raises(RuntimeError, match=r"Tushare adj_factor 查询"):
        src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))


def test_klines_stk_limit_api_raises_propagates() -> None:
    """stk_limit API 异常 → RuntimeError 含 'Tushare stk_limit 查询'."""
    td = "20260415"
    responses = {
        ("daily", td): _klines_frame(["600519.SH"], td),
        ("adj_factor", td): _adj_frame(["600519.SH"], td),
    }
    client = _FakeTushareClient(responses=responses, raise_on_api="stk_limit")
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    with pytest.raises(RuntimeError, match=r"Tushare stk_limit 查询"):
        src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))


def test_check_value_ranges_klines_negative_adj_factor() -> None:
    """MVP 2.1c Sub3-prep: adj_factor <= 0 检测."""
    client = _FakeTushareClient()
    src = TushareDataSource(client=client)
    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH", "000001.SZ"],
            "open": [10.0, 10.0],
            "high": [10.5, 10.5],
            "low": [9.9, 9.9],
            "close": [10.2, 10.2],
            "pre_close": [10.0, 10.0],
            "vol": [1000, 1000],
            "amount": [10000.0, 10000.0],
            "pct_chg": [2.0, 2.0],
            "adj_factor": [-0.5, 1.0],  # 负值 + 正常值
            "up_limit": [11.0, 11.0],
            "down_limit": [9.0, 9.0],
        }
    )
    issues = src._check_value_ranges(df, KLINES_DAILY_DATA_CONTRACT)
    assert any("adj_factor" in m and "<= 0" in m for m in issues), issues


def test_check_value_ranges_daily_basic_negative_mv() -> None:
    client = _FakeTushareClient()
    src = TushareDataSource(client=client)
    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "close": [10.0],
            "total_mv": [-100.0],  # 负市值
            "circ_mv": [100.0],
            "total_share": [1000.0],
            "float_share": [1000.0],
        }
    )
    issues = src._check_value_ranges(df, DAILY_BASIC_DATA_CONTRACT)
    assert any("total_mv" in msg and "< 0" in msg for msg in issues)


def test_check_value_ranges_moneyflow_negative_buy_vol() -> None:
    client = _FakeTushareClient()
    src = TushareDataSource(client=client)
    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "buy_sm_vol": [-100],  # 买方 vol 不应为负
            "buy_sm_amount": [100.0],
            "net_mf_vol": [-50],  # net 允许负 (净流出)
            "net_mf_amount": [-500.0],
        }
    )
    issues = src._check_value_ranges(df, MONEYFLOW_DATA_CONTRACT)
    assert any("buy_sm_vol" in msg and "< 0" in msg for msg in issues)
    # net_mf_vol < 0 允许, 不应被标记
    assert not any("net_mf_vol" in msg for msg in issues)


# ============================================================
# Board 识别
# ============================================================


@pytest.mark.parametrize(
    "ts_code,expected_board",
    [
        ("600519.SH", "main"),
        ("000001.SZ", "main"),
        ("688981.SH", "star"),
        ("300750.SZ", "gem"),
        ("430047.BJ", "bse"),
        ("830799.BJ", "bse"),
        ("900901.SH", "main"),  # B 股默认 main
    ],
)
def test_board_from_ts_code(ts_code, expected_board) -> None:
    assert _board_from_ts_code(ts_code) == expected_board


# ============================================================
# Validate 端到端 — PK 重复
# ============================================================


def test_fetch_klines_pk_duplicate_raises() -> None:
    # 同 ts_code + 同 trade_date 返回 2 行 → PK 重复
    dup = _klines_frame(["600519.SH", "600519.SH"], "20260415")
    client = _FakeTushareClient(responses={("daily", "20260415"): dup})
    src = TushareDataSource(client=client, end=date(2026, 4, 15))
    with pytest.raises(ContractViolation) as exc_info:
        src.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 15))
    assert any("primary_key" in msg for msg in exc_info.value.issues)


# ============================================================
# nan_ratio_threshold 行为 (daily_basic 停牌日 field 缺)
# ============================================================


def test_daily_basic_nan_tolerance() -> None:
    """daily_basic 停牌日 pe/pb 可能 NaN, 默认 10% 容忍."""
    codes = [f"00000{i}.SZ" for i in range(10)]
    df_mock = pd.DataFrame(
        {
            "ts_code": codes,
            "trade_date": ["20260415"] * 10,
            "close": [1650.0] * 10,
            "turnover_rate": [0.5] * 10,
            "turnover_rate_f": [0.6] * 10,
            "volume_ratio": [1.2] * 10,
            "pe": [30.0] * 10,
            "pe_ttm": [None] * 2 + [32.0] * 8,  # 20% NaN — 超 10%
            "pb": [8.0] * 10,
            "ps": [10.0] * 10,
            "ps_ttm": [10.5] * 10,
            "dv_ratio": [1.5] * 10,
            "dv_ttm": [1.6] * 10,
            "total_share": [1000.0] * 10,
            "float_share": [1000.0] * 10,
            "free_share": [1000.0] * 10,
            "total_mv": [20000000.0] * 10,
            "circ_mv": [20000000.0] * 10,
        }
    )
    client = _FakeTushareClient(responses={("daily_basic", "20260415"): df_mock})

    # 默认 threshold 0.1 → FAIL
    src_strict = TushareDataSource(client=client, end=date(2026, 4, 15))
    with pytest.raises(ContractViolation):
        src_strict.fetch(DAILY_BASIC_DATA_CONTRACT, since=date(2026, 4, 15))

    # threshold 0.25 → PASS
    client2 = _FakeTushareClient(responses={("daily_basic", "20260415"): df_mock})
    src_loose = TushareDataSource(
        client=client2, end=date(2026, 4, 15), nan_ratio_threshold=0.25
    )
    df = src_loose.fetch(DAILY_BASIC_DATA_CONTRACT, since=date(2026, 4, 15))
    assert len(df) == 10
