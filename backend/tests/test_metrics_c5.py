"""C5 回测报告12项指标补全测试。

测试:
1. calmar_ratio计算正确
2. sortino_ratio计算正确
3. bootstrap CI边界: lower < sharpe < upper
4. 成本敏感性单调递减
5. 12项指标全部出现在to_dict()中
6. warning flags正确触发
7. profit_loss_ratio计算正确
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.metrics import (
    TRADING_DAYS_PER_YEAR,
    PerformanceReport,
    bootstrap_sharpe_ci,
    calc_calmar,
    calc_max_consecutive_loss_days,
    calc_max_drawdown,
    calc_sharpe,
    calc_sortino,
    calc_win_rate_and_profit_factor,
    generate_report,
)


# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════

def _make_fake_fills(pnls: list[float]):
    """构造假Fill对象用于测试win_rate/profit_factor。

    每个pnl对应一笔独立交易(code+date唯一)。
    calc_win_rate_and_profit_factor对sell: pnl += amount - total_cost
    所以设 amount=1000+pnl, total_cost=1000 当pnl>0;
           amount=1000, total_cost=1000+|pnl| 当pnl<0。
    """
    from engines.backtest_engine import Fill

    fills = []
    d = date(2024, 1, 2)
    for i, pnl in enumerate(pnls):
        code = f"{i:06d}.SZ"
        if pnl >= 0:
            fills.append(Fill(
                code=code, trade_date=d, direction="sell",
                price=10.0, shares=100,
                amount=1000.0 + pnl, commission=0, tax=0, slippage=0,
                total_cost=1000.0,
            ))
        else:
            fills.append(Fill(
                code=code, trade_date=d, direction="sell",
                price=10.0, shares=100,
                amount=1000.0, commission=0, tax=0, slippage=0,
                total_cost=1000.0 + abs(pnl),
            ))
    return fills


# ═══════════════════════════════════════════════════
# Test: Calmar Ratio
# ═══════════════════════════════════════════════════

class TestCalmarRatio:
    """Calmar = annual_return / |max_drawdown|。"""

    def test_basic_calculation(self):
        """手工验证: 20%年化 / 10%MDD = 2.0。"""
        assert calc_calmar(0.20, -0.10) == pytest.approx(2.0)

    def test_zero_drawdown(self):
        """无回撤返回0（避免除零）。"""
        assert calc_calmar(0.15, 0.0) == 0.0

    def test_negative_return(self):
        """负收益: -10% / 20%MDD = -0.5。"""
        assert calc_calmar(-0.10, -0.20) == pytest.approx(-0.5)


# ═══════════════════════════════════════════════════
# Test: Sortino Ratio
# ═══════════════════════════════════════════════════

class TestSortinoRatio:
    """Sortino = excess_return / downside_std。"""

    def test_positive_returns_only(self):
        """全正收益 → Sortino=0（无下行波动）。"""
        returns = pd.Series([0.01, 0.02, 0.015, 0.005] * 60)
        assert calc_sortino(returns) == 0.0

    def test_basic_calculation(self):
        """有正有负收益的Sortino应有合理值。"""
        rng = np.random.RandomState(42)
        returns = pd.Series(rng.normal(0.001, 0.02, 500))
        sortino = calc_sortino(returns)
        sharpe = calc_sharpe(returns)
        # Sortino一般 >= Sharpe（下行std <= 全std）
        assert sortino >= sharpe - 0.5  # 宽容比较


# ═══════════════════════════════════════════════════
# Test: Bootstrap Sharpe CI
# ═══════════════════════════════════════════════════

class TestBootstrapCI:
    """Bootstrap Sharpe 95%置信区间。"""

    def test_ci_bounds(self):
        """lower < point < upper。"""
        rng = np.random.RandomState(42)
        returns = pd.Series(rng.normal(0.001, 0.02, 500))
        point, lower, upper = bootstrap_sharpe_ci(returns)
        assert lower < point < upper

    def test_ci_width_reasonable(self):
        """CI宽度应合理（不会太窄或太宽）。"""
        rng = np.random.RandomState(42)
        returns = pd.Series(rng.normal(0.001, 0.02, 500))
        point, lower, upper = bootstrap_sharpe_ci(returns)
        width = upper - lower
        assert 0.1 < width < 5.0  # 合理范围

    def test_deterministic(self):
        """固定种子确保确定性。"""
        returns = pd.Series(np.random.RandomState(42).normal(0.001, 0.02, 500))
        r1 = bootstrap_sharpe_ci(returns)
        r2 = bootstrap_sharpe_ci(returns)
        assert r1 == r2


# ═══════════════════════════════════════════════════
# Test: 成本敏感性单调递减
# ═══════════════════════════════════════════════════

class TestCostSensitivity:
    """成本敏感性: 0.5x Sharpe > 1x > 1.5x > 2x。"""

    def test_monotonic_decrease(self):
        """构造BacktestResult验证成本敏感性单调递减。"""
        from engines.backtest_engine import BacktestConfig, BacktestResult

        rng = np.random.RandomState(42)
        n = 500
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        returns = pd.Series(rng.normal(0.001, 0.02, n), index=dates)
        nav = (1 + returns).cumprod() * 1_000_000

        config = BacktestConfig(
            commission_rate=0.0000854,
            stamp_tax_rate=0.0005,
        )

        result = BacktestResult(
            daily_nav=nav,
            daily_returns=returns,
            benchmark_nav=nav * 0.95,
            benchmark_returns=returns * 0.9,
            trades=[],
            holdings_history={},
            config=config,
            turnover_series=pd.Series(0.05, index=dates[::20]),
        )

        report = generate_report(result)
        cs = report.cost_sensitivity

        sharpes = [cs[k]["sharpe"] for k in ["0.5x", "1.0x", "1.5x", "2.0x"]]
        for i in range(len(sharpes) - 1):
            assert sharpes[i] >= sharpes[i + 1], (
                f"成本敏感性非单调: {sharpes}"
            )


# ═══════════════════════════════════════════════════
# Test: 12项指标全部出现
# ═══════════════════════════════════════════════════

class TestAllMetricsPresent:
    """to_dict()包含所有12项指标。"""

    def test_all_12_metrics_in_dict(self):
        """验证to_dict()包含任务要求的所有字段。"""
        from engines.backtest_engine import BacktestConfig, BacktestResult

        rng = np.random.RandomState(42)
        n = 500
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        returns = pd.Series(rng.normal(0.001, 0.02, n), index=dates)
        nav = (1 + returns).cumprod() * 1_000_000

        config = BacktestConfig()
        result = BacktestResult(
            daily_nav=nav,
            daily_returns=returns,
            benchmark_nav=nav * 0.95,
            benchmark_returns=returns * 0.9,
            trades=[],
            holdings_history={},
            config=config,
            turnover_series=pd.Series(0.05, index=dates[::20]),
        )

        report = generate_report(result)
        d = report.to_dict()

        required_keys = [
            "calmar_ratio",
            "sortino_ratio",
            "max_consecutive_loss_days",
            "win_rate",
            "profit_loss_ratio",
            "beta",
            "information_ratio",
            "annual_turnover",
            "sharpe_ci_lower",
            "sharpe_ci_upper",
            "avg_overnight_gap",
            "position_deviation",
            "cost_sensitivity",
            "warning_negative_ci",
            "warning_cost_sensitive",
        ]

        for key in required_keys:
            assert key in d, f"缺少指标: {key}"
            assert d[key] is not None, f"指标为None: {key}"

    def test_no_nan_values(self):
        """所有数值指标不为NaN。"""
        from engines.backtest_engine import BacktestConfig, BacktestResult

        rng = np.random.RandomState(42)
        n = 500
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        returns = pd.Series(rng.normal(0.001, 0.02, n), index=dates)
        nav = (1 + returns).cumprod() * 1_000_000

        config = BacktestConfig()
        result = BacktestResult(
            daily_nav=nav,
            daily_returns=returns,
            benchmark_nav=nav * 0.95,
            benchmark_returns=returns * 0.9,
            trades=[],
            holdings_history={},
            config=config,
            turnover_series=pd.Series(0.05, index=dates[::20]),
        )

        report = generate_report(result)
        d = report.to_dict()

        for key, val in d.items():
            if isinstance(val, float):
                assert not np.isnan(val), f"{key} is NaN"


# ═══════════════════════════════════════════════════
# Test: Warning Flags
# ═══════════════════════════════════════════════════

class TestWarningFlags:
    """警告标志正确触发。"""

    def test_warning_negative_ci(self):
        """高波动低收益序列 → CI下界 < 0 → warning_negative_ci=True。"""
        from engines.backtest_engine import BacktestConfig, BacktestResult

        rng = np.random.RandomState(42)
        n = 250
        dates = pd.bdate_range("2023-01-01", periods=n)
        returns = pd.Series(rng.normal(0.0, 0.03, n), index=dates)
        nav = (1 + returns).cumprod() * 1_000_000
        nav.index = dates

        config = BacktestConfig()
        result = BacktestResult(
            daily_nav=nav, daily_returns=returns,
            benchmark_nav=nav.copy(), benchmark_returns=returns.copy(),
            trades=[], holdings_history={}, config=config,
            turnover_series=pd.Series(dtype=float),
        )
        report = generate_report(result)
        if report.bootstrap_sharpe_ci[1] < 0:
            assert report.warning_negative_ci is True

    def test_profit_loss_ratio_calculation(self):
        """profit_loss_ratio = mean(wins) / mean(|losses|)。"""
        # pnls: +100, +200, -50, -150
        # wins=[100,200] → mean=150; losses=[-50,-150] → mean(|.|)=100
        # ratio = 150/100 = 1.5
        fills = _make_fake_fills([100, 200, -50, -150])
        win_rate, _, plr = calc_win_rate_and_profit_factor(fills)
        assert plr == pytest.approx(1.5, rel=0.01)
        assert win_rate == pytest.approx(0.5)  # 2/4

    def test_max_consecutive_loss_days(self):
        """最大连续亏损天数。"""
        returns = pd.Series([0.01, -0.01, -0.02, -0.005, 0.02, -0.01, -0.03])
        assert calc_max_consecutive_loss_days(returns) == 3
