"""Contract trade_date future-date guard (Session 26 LL-068).

验证:
  - ColumnSpec.max_future_days 字段 + __post_init__ validation
  - 3 core contracts (KLINES_DAILY/DAILY_BASIC/MONEYFLOW_DAILY) trade_date 配 7d
  - DataPipeline _validate rejects future rows (不 upsert)

不覆盖:
  - 真实 DB insert (走 smoke + 手工 dry-run scan)
  - 其他含 trade_date 列 Contract (FACTOR_IC_HISTORY 等) 本 PR 范围外
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.data_fetcher.contracts import (
    DAILY_BASIC,
    FACTOR_IC_HISTORY,
    FACTOR_VALUES,
    INDEX_DAILY,
    KLINES_DAILY,
    MINUTE_BARS,
    MONEYFLOW_DAILY,
    NORTHBOUND_HOLDINGS,
    SHADOW_PORTFOLIO,
    STOCK_STATUS_DAILY,
    ColumnSpec,
    TableContract,
)
from app.data_fetcher.pipeline import DataPipeline


class TestColumnSpecMaxFutureDays:
    """ColumnSpec.max_future_days 字段契约 + domain validation."""

    def test_field_default_is_none(self):
        """默认 None = 不校验 (向后兼容)."""
        spec = ColumnSpec("date", nullable=False)
        assert spec.max_future_days is None

    def test_explicit_none_does_not_raise(self):
        """dtype='date' + max_future_days=None 显式传 None, 不 raise (python-P3-2)."""
        spec = ColumnSpec("date", nullable=False, max_future_days=None)
        assert spec.max_future_days is None

    def test_field_can_be_set(self):
        spec = ColumnSpec("date", nullable=False, max_future_days=7)
        assert spec.max_future_days == 7

    def test_negative_raises(self):
        """负值无意义, import 时 raise (避 mis-config 拖到 ingest)."""
        with pytest.raises(ValueError, match="max_future_days must be > 0"):
            ColumnSpec("date", max_future_days=-1)

    def test_zero_raises(self):
        """0 天 = 今天也 reject, 不合理. 最小 1."""
        with pytest.raises(ValueError, match="max_future_days must be > 0"):
            ColumnSpec("date", max_future_days=0)

    def test_only_valid_for_date_dtype(self):
        """非 date 列配 max_future_days 无意义, 拒绝."""
        with pytest.raises(ValueError, match="only valid for dtype='date'"):
            ColumnSpec("float", max_future_days=7)
        with pytest.raises(ValueError, match="only valid for dtype='date'"):
            ColumnSpec("int", max_future_days=7)


class TestCoreContractsConfigured:
    """3 core contracts trade_date 列配 max_future_days=10.

    reviewer db-LOW-1: 7→10 防国庆 Golden Week (7d) + 调休 2-3d 边界误杀.
    测试用 >= 10 断言而非 == 10, 允许未来调整不破测试 (铁律 40 spirit).
    """

    def test_klines_daily(self):
        spec = KLINES_DAILY.columns["trade_date"]
        assert spec.dtype == "date"
        assert spec.nullable is False
        assert spec.max_future_days is not None and spec.max_future_days >= 10

    def test_daily_basic(self):
        spec = DAILY_BASIC.columns["trade_date"]
        assert spec.dtype == "date"
        assert spec.max_future_days is not None and spec.max_future_days >= 10

    def test_moneyflow_daily(self):
        spec = MONEYFLOW_DAILY.columns["trade_date"]
        assert spec.dtype == "date"
        assert spec.max_future_days is not None and spec.max_future_days >= 10


class TestExtendedContractsConfigured:
    """Session 26 follow-up (LL-068 扩散): 7 个 trade_date 列 Contract 配 guard.

    不含: SYMBOLS (list_date/delist_date 业务语义允许未来),
          EARNINGS_ANNOUNCEMENTS (ann_date 可能合法 preannouncement).
    """

    @pytest.mark.parametrize(
        "contract,col",
        [
            (INDEX_DAILY, "trade_date"),
            (FACTOR_VALUES, "trade_date"),
            (FACTOR_IC_HISTORY, "trade_date"),
            (NORTHBOUND_HOLDINGS, "trade_date"),
            (MINUTE_BARS, "trade_date"),
            (STOCK_STATUS_DAILY, "trade_date"),
            (SHADOW_PORTFOLIO, "trade_date"),
            (SHADOW_PORTFOLIO, "rebalance_date"),
        ],
    )
    def test_trade_date_max_future_days_configured(self, contract, col):
        spec = contract.columns[col]
        assert spec.dtype == "date", (
            f"{contract.table_name}.{col} 非 date 列不应该加 max_future_days"
        )
        assert spec.max_future_days is not None, (
            f"{contract.table_name}.{col} 缺 max_future_days guard"
        )
        assert spec.max_future_days >= 10, (
            f"{contract.table_name}.{col} max_future_days={spec.max_future_days} < 10 (Golden Week 边界风险)"
        )


class TestDataPipelineRejectsFutureDates:
    """DataPipeline._validate 在 dtype='date' 列 trade_date > today+N 时 reject."""

    def _make_pipeline(self):
        """DataPipeline 构造需要 conn, 用 MagicMock 跳 DB."""
        return DataPipeline(conn=MagicMock())

    def _toy_contract(self, max_future_days: int = 7) -> TableContract:
        """极简 contract 只验 trade_date 逻辑, 隔离 unit-conversion 等."""
        return TableContract(
            table_name="_test_toy",
            pk_columns=("code", "trade_date"),
            columns={
                "code": ColumnSpec("str", nullable=False),
                "trade_date": ColumnSpec("date", nullable=False, max_future_days=max_future_days),
                "close": ColumnSpec("float"),
            },
            skip_unit_conversion=True,
        )

    def test_future_row_rejected(self):
        """2099-04-30 应被 reject, 不进 valid_df."""
        today = date.today()
        pipeline = self._make_pipeline()
        contract = self._toy_contract(max_future_days=7)
        df = pd.DataFrame(
            {
                "code": ["TEST.SH", "TEST.SH"],
                "trade_date": [today, date(2099, 4, 30)],
                "close": [10.0, 10.0],
            }
        )
        valid_df, reasons = pipeline._validate(df, contract)
        assert len(valid_df) == 1
        assert valid_df.iloc[0]["trade_date"] == today
        # reject reason key 包含 "future"
        future_reasons = [k for k in reasons if "future" in k]
        assert len(future_reasons) == 1
        assert reasons[future_reasons[0]] == 1

    def test_today_plus_n_days_accepted(self):
        """today + 7d (边界) 应 accept (=今天起 7 天内, 实务覆盖长假)."""
        today = date.today()
        pipeline = self._make_pipeline()
        contract = self._toy_contract(max_future_days=7)
        df = pd.DataFrame(
            {
                "code": ["TEST.SH"],
                "trade_date": [today + timedelta(days=7)],
                "close": [10.0],
            }
        )
        valid_df, reasons = pipeline._validate(df, contract)
        assert len(valid_df) == 1
        assert not any("future" in k for k in reasons)

    def test_today_plus_8_days_rejected(self):
        """today + 8d 越界, reject."""
        today = date.today()
        pipeline = self._make_pipeline()
        contract = self._toy_contract(max_future_days=7)
        df = pd.DataFrame(
            {
                "code": ["TEST.SH"],
                "trade_date": [today + timedelta(days=8)],
                "close": [10.0],
            }
        )
        valid_df, reasons = pipeline._validate(df, contract)
        assert len(valid_df) == 0
        future_reasons = [k for k in reasons if "future" in k]
        assert len(future_reasons) == 1

    def test_no_max_future_days_no_check(self):
        """Contract 未配 max_future_days → 未来日期 accept (向后兼容)."""
        pipeline = self._make_pipeline()
        # 构造一个无 guard 的 contract (override trade_date spec)
        relaxed = TableContract(
            table_name="_test_toy_relaxed",
            pk_columns=("code", "trade_date"),
            columns={
                "code": ColumnSpec("str", nullable=False),
                "trade_date": ColumnSpec("date", nullable=False),  # no guard
                "close": ColumnSpec("float"),
            },
            skip_unit_conversion=True,
        )
        df = pd.DataFrame(
            {
                "code": ["TEST.SH"],
                "trade_date": [date(2099, 4, 30)],
                "close": [10.0],
            }
        )
        valid_df, reasons = pipeline._validate(df, relaxed)
        assert len(valid_df) == 1
        assert not any("future" in k for k in reasons)

    def test_mixed_valid_future_and_nat(self):
        """混合 row: past-valid + future-reject + NaT-safe (全 reviewer MEDIUM NaT 担忧)."""
        today = date.today()
        pipeline = self._make_pipeline()
        contract = self._toy_contract(max_future_days=7)
        df = pd.DataFrame(
            {
                "code": ["A.SH", "B.SH", "C.SH"],
                "trade_date": [today, date(2099, 4, 30), None],
                "close": [10.0, 20.0, 30.0],
            }
        )
        valid_df, reasons = pipeline._validate(df, contract)
        # past-valid row 保留; future reject; None (nullable=False) 被 null reject
        assert len(valid_df) == 1
        assert valid_df.iloc[0]["code"] == "A.SH"
        # 同时有 future reject 和 null reject
        assert any("future" in k for k in reasons)

    def test_unparseable_date_string_coerced_safe(self):
        """str 非法日期 → NaT, 不 raise TypeError (reviewer code-MED-1)."""
        today = date.today()
        pipeline = self._make_pipeline()
        # 宽松 contract 允 nullable trade_date 聚焦 NaT 行为
        relaxed = TableContract(
            table_name="_test_toy_nat",
            pk_columns=("code", "trade_date"),
            columns={
                "code": ColumnSpec("str", nullable=False),
                "trade_date": ColumnSpec("date", nullable=True, max_future_days=7),
                "close": ColumnSpec("float"),
            },
            skip_unit_conversion=True,
        )
        df = pd.DataFrame(
            {
                "code": ["A.SH", "B.SH"],
                "trade_date": [today, "not-a-valid-date"],
                "close": [10.0, 20.0],
            }
        )
        # 不 raise 即成功; NaT 被 fillna(False) 处理, 非 future 不 reject
        valid_df, reasons = pipeline._validate(df, relaxed)
        # NaT row 未被 future guard reject (被视为非 future)
        assert not any("future" in k for k in reasons)

    def test_klines_daily_contract_rejects_2099(self):
        """End-to-end: 真实 KLINES_DAILY contract 拒绝 2099-04-30 sentinel."""
        pipeline = self._make_pipeline()
        # KLINES_DAILY 有 unit_conversion + 更多列, 构造最小集合
        df = pd.DataFrame(
            {
                "code": ["TA010.SH"],
                "trade_date": [date(2099, 4, 30)],
                "open": [10.0],
                "high": [10.0],
                "low": [10.0],
                "close": [10.0],
                "pre_close": [10.0],
                "volume": [1000],
                "amount": [10.0],  # 千元
            }
        )
        valid_df, reasons = pipeline._validate(df, KLINES_DAILY)
        assert len(valid_df) == 0
        assert any("future" in k for k in reasons)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
