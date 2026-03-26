"""PT毕业评估4项新指标单元测试 (Sprint 1.10 Task 8)。

测试 metrics.py 中新增的4个函数：
- calc_fill_rate
- calc_avg_slippage_pct
- calc_tracking_error
- calc_signal_execution_gap_hours
"""

from datetime import datetime, date, timedelta

import numpy as np
import pandas as pd
import pytest

from engines.metrics import (
    TRADING_DAYS_PER_YEAR,
    calc_avg_slippage_pct,
    calc_fill_rate,
    calc_signal_execution_gap_hours,
    calc_tracking_error,
)


# ──────────────────── 辅助对象 ────────────────────


class _Fill:
    """模拟Fill对象（只需要code和price字段）。"""

    def __init__(self, code: str, price: float):
        self.code = code
        self.price = price


# ──────────────────── calc_fill_rate ────────────────────


class TestCalcFillRate:
    def test_all_fills_succeed(self):
        assert calc_fill_rate(10, 10) == 100.0

    def test_partial_fills(self):
        # 8/10 = 80%
        result = calc_fill_rate(10, 8)
        assert result == pytest.approx(80.0, abs=0.01)

    def test_zero_target_orders_returns_100(self):
        # 无调仓日 = 无失败 = 100%
        assert calc_fill_rate(0, 0) == 100.0

    def test_zero_fills_out_of_target(self):
        # 完全没成交 = 0%
        assert calc_fill_rate(5, 0) == 0.0

    def test_returns_float(self):
        result = calc_fill_rate(15, 14)
        assert isinstance(result, float)

    def test_boundary_95pct(self):
        # 刚好95% (19/20)
        result = calc_fill_rate(20, 19)
        assert result == pytest.approx(95.0, abs=0.01)


# ──────────────────── calc_avg_slippage_pct ────────────────────


class TestCalcAvgSlippagePct:
    def test_no_slippage(self):
        """实际价格=信号价格，滑点=0。"""
        fills = [_Fill("600519", 1800.0), _Fill("000001", 10.0)]
        signal_prices = {"600519": 1800.0, "000001": 10.0}
        result = calc_avg_slippage_pct(fills, signal_prices)
        assert result == 0.0

    def test_constant_slippage(self):
        """固定1%滑点：mean应为1%。"""
        fills = [
            _Fill("600519", 1818.0),  # 1800 * 1.01
            _Fill("000001", 10.1),    # 10.0 * 1.01
        ]
        signal_prices = {"600519": 1800.0, "000001": 10.0}
        result = calc_avg_slippage_pct(fills, signal_prices)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_takes_absolute_value(self):
        """滑点方向无关（买入高于信号 or 卖出低于信号都算）。"""
        fills = [
            _Fill("600519", 1818.0),  # +1%
            _Fill("000001", 9.9),     # -1%
        ]
        signal_prices = {"600519": 1800.0, "000001": 10.0}
        result = calc_avg_slippage_pct(fills, signal_prices)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_empty_fills_returns_zero(self):
        result = calc_avg_slippage_pct([], {"600519": 1800.0})
        assert result == 0.0

    def test_empty_signal_prices_returns_zero(self):
        fills = [_Fill("600519", 1800.0)]
        result = calc_avg_slippage_pct(fills, {})
        assert result == 0.0

    def test_missing_signal_price_skipped(self):
        """没有信号价格的成交跳过，不影响其他。"""
        fills = [
            _Fill("600519", 1818.0),   # +1%，有信号价
            _Fill("UNKNOWN", 100.0),   # 无信号价
        ]
        signal_prices = {"600519": 1800.0}  # UNKNOWN不在这里
        result = calc_avg_slippage_pct(fills, signal_prices)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_zero_price_fill_skipped(self):
        """price=0的成交跳过。"""
        fills = [_Fill("600519", 0.0)]
        signal_prices = {"600519": 1800.0}
        result = calc_avg_slippage_pct(fills, signal_prices)
        assert result == 0.0

    def test_returns_float(self):
        fills = [_Fill("600519", 1809.0)]
        signal_prices = {"600519": 1800.0}
        result = calc_avg_slippage_pct(fills, signal_prices)
        assert isinstance(result, float)


# ──────────────────── calc_tracking_error ────────────────────


class TestCalcTrackingError:
    def test_zero_te_when_identical(self):
        """实际收益=目标收益，TE=0。"""
        returns = pd.Series([0.01, 0.02, -0.01, 0.005, -0.005])
        result = calc_tracking_error(returns, returns.copy())
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_positive_te(self):
        """有偏差时TE>0。"""
        actual = pd.Series([0.01, 0.02, -0.01, 0.005, -0.005] * 10)
        target = pd.Series([0.01, 0.021, -0.011, 0.004, -0.006] * 10)
        result = calc_tracking_error(actual, target)
        assert result > 0.0

    def test_annualization(self):
        """验证年化公式: TE = std(diff) × sqrt(244) × 100。"""
        rng = np.random.default_rng(42)
        actual = pd.Series(rng.normal(0, 0.01, 100))
        target = pd.Series(rng.normal(0, 0.01, 100))
        diff = actual - target
        expected_te = float(diff.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100)
        result = calc_tracking_error(actual, target)
        assert result == pytest.approx(expected_te, rel=1e-4)

    def test_insufficient_data_returns_zero(self):
        """数据不足(<3个)返回0.0。"""
        actual = pd.Series([0.01, 0.02])
        target = pd.Series([0.01, 0.021])
        result = calc_tracking_error(actual, target)
        assert result == 0.0

    def test_empty_series_returns_zero(self):
        result = calc_tracking_error(pd.Series([], dtype=float), pd.Series([], dtype=float))
        assert result == 0.0

    def test_returns_float(self):
        actual = pd.Series([0.01, 0.02, -0.01])
        target = pd.Series([0.011, 0.019, -0.009])
        result = calc_tracking_error(actual, target)
        assert isinstance(result, float)


# ──────────────────── calc_signal_execution_gap_hours ────────────────────


class TestCalcSignalExecutionGapHours:
    def _make_timestamps(self, signal_hour=17, exec_hour=9, n=5):
        """生成模拟时间戳对。"""
        base = date(2026, 3, 1)
        signals = [
            datetime.combine(base + timedelta(days=i), datetime.min.time()).replace(
                hour=signal_hour, minute=20
            )
            for i in range(n)
        ]
        # exec是signal的次日
        execs = [
            datetime.combine(base + timedelta(days=i + 1), datetime.min.time()).replace(
                hour=exec_hour, minute=30
            )
            for i in range(n)
        ]
        return signals, execs

    def test_standard_gap(self):
        """标准链路: T日17:20 → T+1日09:30 = 16h10min ≈ 16.17h。"""
        signals, execs = self._make_timestamps(signal_hour=17, exec_hour=9, n=5)
        result = calc_signal_execution_gap_hours(signals, execs)
        # 17:20 → 09:30 = 16h10min = 16.1667h
        assert result == pytest.approx(16.17, abs=0.01)

    def test_empty_lists_returns_zero(self):
        result = calc_signal_execution_gap_hours([], [])
        assert result == 0.0

    def test_mismatched_lengths_returns_zero(self):
        signals, execs = self._make_timestamps(n=3)
        result = calc_signal_execution_gap_hours(signals, execs[:2])
        assert result == 0.0

    def test_negative_gaps_excluded(self):
        """执行时间早于信号时间（数据异常），该对被跳过。"""
        base = date(2026, 3, 1)
        signals = [
            datetime.combine(base, datetime.min.time()).replace(hour=17),
            datetime.combine(base + timedelta(1), datetime.min.time()).replace(hour=17),
        ]
        execs = [
            # 第1个：执行早于信号（异常数据）
            datetime.combine(base, datetime.min.time()).replace(hour=10),
            # 第2个：正常16h
            datetime.combine(base + timedelta(2), datetime.min.time()).replace(hour=9),
        ]
        result = calc_signal_execution_gap_hours(signals, execs)
        # 只用第2个有效对（16h）
        assert result == pytest.approx(16.0, abs=0.1)

    def test_multiple_gaps_averaged(self):
        """多个时延取平均。"""
        base = date(2026, 3, 1)
        # 两个时延：16h 和 18h
        signals = [
            datetime.combine(base, datetime.min.time()).replace(hour=17),
            datetime.combine(base + timedelta(1), datetime.min.time()).replace(hour=17),
        ]
        execs = [
            datetime.combine(base + timedelta(1), datetime.min.time()).replace(hour=9),    # 16h
            datetime.combine(base + timedelta(2), datetime.min.time()).replace(hour=11),   # 18h
        ]
        result = calc_signal_execution_gap_hours(signals, execs)
        assert result == pytest.approx(17.0, abs=0.01)

    def test_returns_float(self):
        signals, execs = self._make_timestamps(n=3)
        result = calc_signal_execution_gap_hours(signals, execs)
        assert isinstance(result, float)

    def test_graduation_range_check(self):
        """验证标准链路时延在12h-20h范围内（毕业标准）。"""
        signals, execs = self._make_timestamps(signal_hour=17, exec_hour=9, n=10)
        result = calc_signal_execution_gap_hours(signals, execs)
        # 标准链路约16h，应在[12, 20]范围内
        assert 12.0 <= result <= 20.0
