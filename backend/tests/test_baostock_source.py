"""MVP 2.1b Sub-commit 1 — BaostockDataSource 单测.

Mock Baostock 模块 (monkeypatch sys.modules["baostock"]).
不依赖真网络, 也不依赖真 DB.
"""
from __future__ import annotations

import sys
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.qm_platform.data.base_source import ContractViolation
from backend.qm_platform.data.sources.baostock_source import (
    MINUTE_BARS_DATA_CONTRACT,
    BaostockDataSource,
    _to_bs_code,
    _to_db_code,
)

# ---------- Fake baostock module ----------


class _FakeResultSet:
    def __init__(self, rows: list[list[str]], error_code: str = "0") -> None:
        self._rows = rows
        self._i = -1
        self.error_code = error_code
        self.error_msg = "ok" if error_code == "0" else "fail"

    def next(self) -> bool:  # noqa: A003 — baostock API name
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows[self._i]


class _FakeBaostock:
    """Stand-in for baostock module. rows_map: bs_code → list of 8-str rows."""

    def __init__(
        self,
        rows_map: dict[str, list[list[str]]] | None = None,
        login_code: str = "0",
        query_error: str = "0",
    ) -> None:
        self._rows_map = rows_map or {}
        self._login_code = login_code
        self._query_error = query_error
        self.login_calls = 0
        self.logout_calls = 0
        self.query_calls: list[tuple] = []

    def login(self) -> SimpleNamespace:
        self.login_calls += 1
        return SimpleNamespace(error_code=self._login_code, error_msg="login")

    def logout(self) -> SimpleNamespace:
        self.logout_calls += 1
        return SimpleNamespace(error_code="0", error_msg="logout")

    def query_history_k_data_plus(
        self, code, fields, start_date, end_date, frequency, adjustflag
    ) -> _FakeResultSet:
        self.query_calls.append((code, start_date, end_date, frequency, adjustflag))
        rows = self._rows_map.get(code, [])
        return _FakeResultSet(rows, error_code=self._query_error)


def _one_row(date_str: str = "2026-04-15", time_str: str = "20260415093500000") -> list[str]:
    """Single Baostock row (8 cols: date, time, open, high, low, close, volume, amount)."""
    return [date_str, time_str, "10.00", "10.20", "9.95", "10.10", "5000", "50500.0"]


@pytest.fixture
def fake_bs(monkeypatch) -> _FakeBaostock:
    """Inject fake baostock module into sys.modules."""
    fake = _FakeBaostock()
    monkeypatch.setitem(sys.modules, "baostock", fake)
    return fake


# ============================================================
# Test 1: _fetch_raw 返 schema 对齐 DataFrame + code 转换正确
# ============================================================


def test_fetch_raw_returns_schema_aligned(fake_bs) -> None:
    fake_bs._rows_map = {
        "sh.600519": [_one_row("2026-04-15", "20260415093500000")],
        "sz.000001": [_one_row("2026-04-15", "20260415093500000")],
    }
    src = BaostockDataSource(codes=["600519", "000001"], end=date(2026, 4, 15))
    df = src._fetch_raw(MINUTE_BARS_DATA_CONTRACT, since=date(2026, 4, 15))

    assert len(df) == 2
    assert set(df.columns) == {
        "code",
        "trade_date",
        "trade_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adjustflag",
    }
    assert set(df["code"]) == {"600519.SH", "000001.SZ"}
    assert all(df["adjustflag"] == "3")
    assert fake_bs.login_calls == 1
    assert fake_bs.logout_calls == 1
    assert len(fake_bs.query_calls) == 2


# ============================================================
# Test 2: fetch() Template 端到端 — PASS
# ============================================================


def test_fetch_end_to_end_passes(fake_bs) -> None:
    fake_bs._rows_map = {
        "sh.600519": [
            _one_row("2026-04-15", "20260415093500000"),
            _one_row("2026-04-15", "20260415094000000"),
        ]
    }
    src = BaostockDataSource(codes=["600519"], end=date(2026, 4, 15))
    df = src.fetch(MINUTE_BARS_DATA_CONTRACT, since=date(2026, 4, 15))
    assert len(df) == 2
    # validate 通过: 无 ContractViolation raised


# ============================================================
# Test 3: validate PK 重复 → ContractViolation
# ============================================================


def test_fetch_duplicate_pk_raises_contract_violation(fake_bs) -> None:
    # 2 行同 (code, trade_time) → PK 重复
    dup_row = _one_row("2026-04-15", "20260415093500000")
    fake_bs._rows_map = {"sh.600519": [dup_row, dup_row]}
    src = BaostockDataSource(codes=["600519"], end=date(2026, 4, 15))

    with pytest.raises(ContractViolation) as exc_info:
        src.fetch(MINUTE_BARS_DATA_CONTRACT, since=date(2026, 4, 15))
    assert any("primary_key" in msg for msg in exc_info.value.issues)


# ============================================================
# Test 4: _check_value_ranges — close <= 0 捕获
# ============================================================


def test_check_value_ranges_close_non_positive() -> None:
    src = BaostockDataSource(codes=["600519"])
    df = pd.DataFrame(
        {
            "code": ["600519.SH", "600519.SH"],
            "close": [10.0, -5.0],
            "high": [10.5, 0.0],
            "low": [9.5, 0.0],
            "volume": [100, 100],
        }
    )
    issues = src._check_value_ranges(df, MINUTE_BARS_DATA_CONTRACT)
    assert any("close" in msg and "≤ 0" in msg for msg in issues)


# ============================================================
# Test 5: _check_value_ranges — high < low 捕获
# ============================================================


def test_check_value_ranges_high_below_low() -> None:
    src = BaostockDataSource(codes=["600519"])
    df = pd.DataFrame(
        {
            "code": ["600519.SH"],
            "close": [10.0],
            "high": [9.0],  # high < low
            "low": [10.0],
            "volume": [100],
        }
    )
    issues = src._check_value_ranges(df, MINUTE_BARS_DATA_CONTRACT)
    assert any("high<low" in msg for msg in issues)


# ============================================================
# Test 6: code 格式转换 (SH/SZ/BJ 三区)
# ============================================================


@pytest.mark.parametrize(
    "code6,expected_bs,expected_db",
    [
        ("600519", "sh.600519", "600519.SH"),
        ("000001", "sz.000001", "000001.SZ"),
        ("300750", "sz.300750", "300750.SZ"),
        ("688981", "sh.688981", "688981.SH"),
        ("430047", "bj.430047", "430047.BJ"),
        ("830799", "bj.830799", "830799.BJ"),
        ("900901", "sh.900901", "900901.SH"),
    ],
)
def test_code_format_conversion(code6, expected_bs, expected_db) -> None:
    assert _to_bs_code(code6) == expected_bs
    assert _to_db_code(code6) == expected_db


# ============================================================
# Test 7: Empty baostock result → empty DataFrame (不 raise)
# ============================================================


def test_empty_baostock_result_returns_empty_df(fake_bs) -> None:
    fake_bs._rows_map = {"sh.600519": []}  # 无数据
    src = BaostockDataSource(codes=["600519"], end=date(2026, 4, 15))
    df = src._fetch_raw(MINUTE_BARS_DATA_CONTRACT, since=date(2026, 4, 15))
    assert df.empty
    # 列仍在
    assert "code" in df.columns
    assert "trade_time" in df.columns
    # 空 df 过 validate (PK/NaN/range 都跳过)
    result = src.validate(df, MINUTE_BARS_DATA_CONTRACT)
    assert result.passed is True
    assert result.row_count == 0


# ============================================================
# Test 8: Baostock 登录失败 → RuntimeError (铁律 33 fail-loud)
# ============================================================


def test_baostock_login_failure_raises(monkeypatch) -> None:
    fake = _FakeBaostock(login_code="10001002")  # 非 0 = 登录失败
    monkeypatch.setitem(sys.modules, "baostock", fake)
    src = BaostockDataSource(codes=["600519"])
    with pytest.raises(RuntimeError, match=r"Baostock 登录失败"):
        src._fetch_raw(MINUTE_BARS_DATA_CONTRACT, since=date(2026, 4, 15))


# ============================================================
# Test 9: Constructor 校验 — 空 codes / 格式错误
# ============================================================


def test_constructor_rejects_empty_codes() -> None:
    with pytest.raises(ValueError, match=r"codes 不可为空"):
        BaostockDataSource(codes=[])


def test_constructor_rejects_malformed_codes() -> None:
    with pytest.raises(ValueError, match=r"格式错误"):
        BaostockDataSource(codes=["60051"])  # 5 位
    with pytest.raises(ValueError, match=r"格式错误"):
        BaostockDataSource(codes=["ABCDEF"])  # 非数字
    with pytest.raises(ValueError, match=r"格式错误"):
        BaostockDataSource(codes=["600519.SH"])  # 带后缀不允许


# ============================================================
# Test 10: nan_ratio_threshold 可配置
# ============================================================


def test_nan_ratio_threshold_configurable(fake_bs) -> None:
    # 制造 NaN close (data[5] 空字符串 → None 走 `float(data[5]) if data[5] else None`)
    nan_row = ["2026-04-15", "20260415093500000", "10.0", "10.2", "9.9", "", "100", "1000.0"]
    good_row = _one_row("2026-04-15", "20260415094000000")
    # 1/2 = 50% NaN close
    fake_bs._rows_map = {"sh.600519": [nan_row, good_row]}

    # threshold=0.1 (默认) → FAIL (50% > 10%)
    src_strict = BaostockDataSource(codes=["600519"], end=date(2026, 4, 15))
    with pytest.raises(ContractViolation):
        src_strict.fetch(MINUTE_BARS_DATA_CONTRACT, since=date(2026, 4, 15))

    # 刷新 fake 数据
    fake_bs._rows_map = {"sh.600519": [nan_row, good_row]}
    # threshold=0.6 → PASS
    src_loose = BaostockDataSource(
        codes=["600519"], nan_ratio_threshold=0.6, end=date(2026, 4, 15)
    )
    df = src_loose.fetch(MINUTE_BARS_DATA_CONTRACT, since=date(2026, 4, 15))
    assert len(df) == 2
