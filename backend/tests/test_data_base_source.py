"""MVP 2.1a BaseDataSource Template method + validation helpers 单测."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from backend.platform.data.base_source import BaseDataSource, ContractViolation
from backend.platform.data.interface import DataContract

# ---------- Fixtures ----------


@pytest.fixture
def contract() -> DataContract:
    return DataContract(
        name="test_klines",
        version="v1",
        schema={
            "code": "str",
            "trade_date": "date",
            "close": "float64 元",
            "volume": "int64 手",
        },
        primary_key=("code", "trade_date"),
        source="test",
        unit_convention={"close": "元", "volume": "手"},
    )


class _FakeDataSource(BaseDataSource):
    """Minimal concrete for testing template method."""

    def __init__(self, df_to_return: pd.DataFrame, nan_ratio_threshold: float = 0.1) -> None:
        super().__init__(nan_ratio_threshold=nan_ratio_threshold)
        self._df = df_to_return

    def _fetch_raw(self, contract: DataContract, since: Any) -> pd.DataFrame:
        del contract, since
        return self._df


def _make_good_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["600000.SH", "600000.SH", "000001.SZ"],
            "trade_date": [date(2026, 4, 15), date(2026, 4, 16), date(2026, 4, 15)],
            "close": [10.0, 10.5, 9.8],
            "volume": [1000, 1100, 1200],
        }
    )


# ---------- validate: 正常 pass ----------


def test_validate_good_df_passes(contract) -> None:
    src = _FakeDataSource(_make_good_df())
    result = src.validate(_make_good_df(), contract)
    assert result.passed is True
    assert result.row_count == 3
    assert result.issues == []
    assert result.metadata["validator"] == "_FakeDataSource"


# ---------- validate: schema 缺列 ----------


def test_validate_missing_column(contract) -> None:
    df = _make_good_df().drop(columns=["volume"])
    src = _FakeDataSource(df)
    result = src.validate(df, contract)
    assert result.passed is False
    assert any("missing required columns" in msg and "volume" in msg for msg in result.issues)


# ---------- validate: PK 重复 ----------


def test_validate_primary_key_duplicate(contract) -> None:
    df = pd.DataFrame(
        {
            "code": ["600000.SH", "600000.SH"],
            "trade_date": [date(2026, 4, 15), date(2026, 4, 15)],  # 同 code+date
            "close": [10.0, 10.5],
            "volume": [1000, 1100],
        }
    )
    src = _FakeDataSource(df)
    result = src.validate(df, contract)
    assert result.passed is False
    assert any("primary_key uniqueness" in msg for msg in result.issues)


# ---------- validate: NaN ratio 超标 ----------


def test_validate_nan_ratio_exceeded(contract) -> None:
    df = pd.DataFrame(
        {
            "code": ["600000.SH", "000001.SZ", "600519.SH", "002415.SZ"],
            "trade_date": [
                date(2026, 4, 15), date(2026, 4, 15),
                date(2026, 4, 15), date(2026, 4, 15),
            ],
            "close": [10.0, None, None, None],  # 3/4 = 75% NaN
            "volume": [1000, 1100, 1200, 1300],
        }
    )
    src = _FakeDataSource(df, nan_ratio_threshold=0.1)
    result = src.validate(df, contract)
    assert result.passed is False
    assert any("NaN ratio" in msg and "'close'" in msg for msg in result.issues)


def test_validate_pk_column_nan_zero_tolerance(contract) -> None:
    """PK 列 NaN 0 容忍 — 无论 threshold 多大."""
    df = pd.DataFrame(
        {
            "code": ["600000.SH", None],  # 1 NaN in PK
            "trade_date": [date(2026, 4, 15), date(2026, 4, 16)],
            "close": [10.0, 10.5],
            "volume": [1000, 1100],
        }
    )
    src = _FakeDataSource(df, nan_ratio_threshold=1.0)  # 100% 允许, 但 PK 强制
    result = src.validate(df, contract)
    assert result.passed is False
    assert any("PK column" in msg and "NaN" in msg for msg in result.issues)


# ---------- fetch (Template method) ----------


def test_fetch_good_df_returns(contract) -> None:
    src = _FakeDataSource(_make_good_df())
    df = src.fetch(contract, since=date(2026, 4, 1))
    assert len(df) == 3


def test_fetch_bad_df_raises_contract_violation(contract) -> None:
    bad_df = _make_good_df().drop(columns=["volume"])
    src = _FakeDataSource(bad_df)
    with pytest.raises(ContractViolation) as exc_info:
        src.fetch(contract, since=date(2026, 4, 1))
    assert exc_info.value.issues
    assert any("volume" in msg for msg in exc_info.value.issues)


# ---------- Helper override ----------


def test_subclass_override_value_ranges(contract) -> None:
    """子类 override _check_value_ranges 加业务 range 检查."""

    class CloseNonNegativeSource(_FakeDataSource):
        def _check_value_ranges(self, df, contract):
            issues = []
            if "close" in df.columns and (df["close"] < 0).any():
                issues.append("[range] close 列含负值 (价格不可能 < 0)")
            return issues

    df = pd.DataFrame(
        {
            "code": ["600000.SH", "000001.SZ"],
            "trade_date": [date(2026, 4, 15), date(2026, 4, 16)],
            "close": [10.0, -5.0],  # 负价格
            "volume": [1000, 1100],
        }
    )
    src = CloseNonNegativeSource(df)
    result = src.validate(df, contract)
    assert result.passed is False
    assert any("含负值" in msg for msg in result.issues)


# ---------- Constructor 边界 ----------


def test_nan_ratio_threshold_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match=r"nan_ratio_threshold"):
        _FakeDataSource(_make_good_df(), nan_ratio_threshold=1.5)
    with pytest.raises(ValueError):
        _FakeDataSource(_make_good_df(), nan_ratio_threshold=-0.1)


def test_empty_df_validates_cleanly(contract) -> None:
    """空 df: schema 缺列检查跳过 (列不存在), NaN/PK 也跳过."""
    df = pd.DataFrame(columns=["code", "trade_date", "close", "volume"])
    src = _FakeDataSource(df)
    result = src.validate(df, contract)
    assert result.passed is True
    assert result.row_count == 0
