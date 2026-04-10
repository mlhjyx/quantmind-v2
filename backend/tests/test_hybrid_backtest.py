"""Hybrid回测架构测试 — Phase A/B分离 + 一致性验证。

测试:
1. Phase A (vectorized_signal) 单独运行
2. Phase B (SimpleBacktester) 给定固定target_weights执行确定性
3. Hybrid vs Simple NAV一致性
4. Hybrid vs Simple 交易记录一致性
5. Hybrid性能(应更快)
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.backtest_engine import (
    BacktestConfig,
    BacktestResult,
    SimpleBacktester,
    run_hybrid_backtest,
)
from engines.vectorized_signal import (
    SignalConfig,
    build_target_portfolios,
    compute_rebalance_dates,
)

# ═══════════════════════════════════════════════════
# Fixtures: 合成测试数据
# ═══════════════════════════════════════════════════

def _make_trading_days(start: date, n_days: int) -> list[date]:
    """生成n个交易日（跳过周末）。"""
    days = []
    d = start
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _make_price_data(codes: list[str], trading_days: list[date], seed: int = 42) -> pd.DataFrame:
    """生成合成行情数据。"""
    rng = np.random.RandomState(seed)
    rows = []
    for code in codes:
        base_price = rng.uniform(10, 50)
        for _i, td in enumerate(trading_days):
            ret = rng.normal(0.001, 0.02)
            close = base_price * (1 + ret)
            base_price = close
            pre_close = close / (1 + ret)
            volume = int(rng.uniform(50000, 500000))
            amount = close * volume * 100 / 1000  # 千元
            rows.append({
                "code": code,
                "trade_date": td,
                "open": round(close * (1 + rng.normal(0, 0.005)), 2),
                "close": round(close, 2),
                "pre_close": round(pre_close, 2),
                "volume": volume,
                "amount": round(amount, 2),
                "up_limit": round(pre_close * 1.10, 2),
                "down_limit": round(pre_close * 0.90, 2),
                "turnover_rate": round(rng.uniform(1, 10), 2),
            })
    return pd.DataFrame(rows)


def _make_factor_data(
    codes: list[str],
    trading_days: list[date],
    factors: list[str],
    directions: dict[str, int],
    seed: int = 42,
) -> pd.DataFrame:
    """生成合成因子数据。"""
    rng = np.random.RandomState(seed)
    rows = []
    for td in trading_days:
        for code in codes:
            for f in factors:
                rows.append({
                    "code": code,
                    "trade_date": td,
                    "factor_name": f,
                    "raw_value": round(rng.normal(0, 1), 4),
                })
    return pd.DataFrame(rows)


@pytest.fixture
def test_data():
    """标准测试数据集。"""
    codes = [f"{i:06d}" for i in range(1, 51)]  # 50只股票
    trading_days = _make_trading_days(date(2024, 1, 2), 250)  # ~1年
    factors = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    directions = {
        "turnover_mean_20": -1, "volatility_20": -1, "reversal_20": -1,
        "amihud_20": -1, "bp_ratio": 1,
    }

    price_df = _make_price_data(codes, trading_days)
    factor_df = _make_factor_data(codes, trading_days, factors, directions)

    return {
        "codes": codes,
        "trading_days": trading_days,
        "factors": factors,
        "directions": directions,
        "price_df": price_df,
        "factor_df": factor_df,
    }


# ═══════════════════════════════════════════════════
# Test: Phase A — 向量化信号层
# ═══════════════════════════════════════════════════

class TestPhaseASignal:
    """Phase A vectorized_signal 单独测试。"""

    def test_compute_rebalance_dates_monthly(self, test_data):
        """月度调仓日正确计算。"""
        rebal = compute_rebalance_dates(test_data["trading_days"], "monthly")
        assert len(rebal) > 0
        assert len(rebal) <= 12  # 最多12个月
        # 每个调仓日应该是该月最后一个交易日
        for rd in rebal:
            assert rd in test_data["trading_days"]

    def test_compute_rebalance_dates_weekly(self, test_data):
        """周度调仓日。"""
        rebal = compute_rebalance_dates(test_data["trading_days"], "weekly")
        assert len(rebal) > 40  # ~52周

    def test_compute_rebalance_dates_empty(self):
        """空交易日列表。"""
        assert compute_rebalance_dates([], "monthly") == []

    def test_build_target_portfolios_basic(self, test_data):
        """Phase A生成target_portfolios基本验证。"""
        rebal = compute_rebalance_dates(test_data["trading_days"], "monthly")
        config = SignalConfig(top_n=15)

        targets = build_target_portfolios(
            test_data["factor_df"], test_data["directions"], rebal, config,
        )

        assert len(targets) > 0
        for _rd, portfolio in targets.items():
            assert len(portfolio) == 15
            weights = list(portfolio.values())
            assert abs(sum(weights) - 1.0) < 1e-10  # 权重和=1
            assert all(w == pytest.approx(1.0 / 15) for w in weights)

    def test_build_target_portfolios_top5(self, test_data):
        """Top-5选股。"""
        rebal = compute_rebalance_dates(test_data["trading_days"], "monthly")
        config = SignalConfig(top_n=5)

        targets = build_target_portfolios(
            test_data["factor_df"], test_data["directions"], rebal, config,
        )

        for _rd, portfolio in targets.items():
            assert len(portfolio) == 5
            assert abs(sum(portfolio.values()) - 1.0) < 1e-10

    def test_build_target_portfolios_deterministic(self, test_data):
        """相同输入产生相同输出。"""
        rebal = compute_rebalance_dates(test_data["trading_days"], "monthly")
        config = SignalConfig(top_n=15)

        t1 = build_target_portfolios(
            test_data["factor_df"], test_data["directions"], rebal, config,
        )
        t2 = build_target_portfolios(
            test_data["factor_df"], test_data["directions"], rebal, config,
        )

        assert t1.keys() == t2.keys()
        for rd in t1:
            assert t1[rd] == t2[rd]


# ═══════════════════════════════════════════════════
# Test: Phase B — 事件驱动执行确定性
# ═══════════════════════════════════════════════════

class TestPhaseBExecution:
    """Phase B SimpleBacktester 给定固定target_weights确定性。"""

    def test_fixed_targets_deterministic(self, test_data):
        """给定固定target_weights，两次执行结果完全一致。"""
        rebal = compute_rebalance_dates(test_data["trading_days"], "monthly")
        config = SignalConfig(top_n=15)
        targets = build_target_portfolios(
            test_data["factor_df"], test_data["directions"], rebal, config,
        )

        bt_config = BacktestConfig(
            initial_capital=1_000_000,
            top_n=15,
            rebalance_freq="monthly",
            slippage_mode="fixed",
            slippage_bps=10.0,
        )

        r1 = SimpleBacktester(bt_config).run(targets, test_data["price_df"])
        r2 = SimpleBacktester(bt_config).run(targets, test_data["price_df"])

        pd.testing.assert_series_equal(r1.daily_nav, r2.daily_nav)
        assert len(r1.trades) == len(r2.trades)


# ═══════════════════════════════════════════════════
# Test: Hybrid vs Simple 一致性
# ═══════════════════════════════════════════════════

class TestHybridConsistency:
    """Hybrid回测确定性: 同一输入跑两次结果完全一致（铁律15）。

    NOTE: 原测试比较 build_target_portfolios(旧路径) vs run_hybrid_backtest(生产路径)。
    两者存在5处设计分歧(raw_value vs neutral_value, 排除逻辑, z-score clip等)。
    铁律16要求信号路径唯一(SignalComposer), build_target_portfolios是遗留函数。
    Phase 1.2 改为验证确定性: 同一输入跑两次run_hybrid_backtest结果完全一致。
    """

    def _run_hybrid(self, test_data) -> BacktestResult:
        """生产路径: run_hybrid_backtest()。"""
        bt_config = BacktestConfig(
            initial_capital=1_000_000,
            top_n=15,
            rebalance_freq="monthly",
            slippage_mode="fixed",
            slippage_bps=10.0,
        )
        return run_hybrid_backtest(
            factor_df=test_data["factor_df"],
            directions=test_data["directions"],
            price_data=test_data["price_df"],
            config=bt_config,
        )

    def test_nav_identical(self, test_data):
        """确定性: 两次运行NAV序列完全一致。"""
        run1 = self._run_hybrid(test_data)
        run2 = self._run_hybrid(test_data)

        assert len(run1.daily_nav) == len(run2.daily_nav)
        diff = (run1.daily_nav - run2.daily_nav).abs()
        assert diff.max() == 0.0, f"Non-deterministic! Max NAV diff: {diff.max():.4f}"

    def test_trades_identical(self, test_data):
        """确定性: 两次运行交易记录完全一致。"""
        run1 = self._run_hybrid(test_data)
        run2 = self._run_hybrid(test_data)

        assert len(run1.trades) == len(run2.trades), (
            f"Trade count mismatch: run1={len(run1.trades)}, run2={len(run2.trades)}"
        )

        for f1, f2 in zip(run1.trades, run2.trades, strict=False):
            assert f1.code == f2.code, f"Code mismatch: {f1.code} vs {f2.code}"
            assert f1.direction == f2.direction
            assert f1.shares == f2.shares
            assert f1.trade_date == f2.trade_date

    def test_final_nav_match(self, test_data):
        """确定性: 两次运行最终NAV完全一致。"""
        run1 = self._run_hybrid(test_data)
        run2 = self._run_hybrid(test_data)

        assert run1.daily_nav.iloc[-1] == run2.daily_nav.iloc[-1]


# ═══════════════════════════════════════════════════
# Test: 性能
# ═══════════════════════════════════════════════════

class TestHybridPerformance:
    """Hybrid性能测试。"""

    def test_phase_a_fast(self, test_data):
        """Phase A信号生成应该很快(<1s for 50 stocks * 250 days)。"""
        rebal = compute_rebalance_dates(test_data["trading_days"], "monthly")
        config = SignalConfig(top_n=15)

        t0 = time.monotonic()
        build_target_portfolios(
            test_data["factor_df"], test_data["directions"], rebal, config,
        )
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"Phase A太慢: {elapsed:.2f}s"
