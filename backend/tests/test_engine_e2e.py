"""回测引擎端到端测试 — 从Parquet加载到metrics输出。"""

import json
from pathlib import Path

import pandas as pd
import pytest
from engines.backtest.config import BacktestConfig, PMSConfig
from engines.backtest.runner import run_hybrid_backtest
from engines.metrics import calc_sharpe
from engines.slippage_model import SlippageConfig

BASELINE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "baseline"


def _load_baseline():
    """加载cache/baseline/确定性数据。"""
    if not (BASELINE_DIR / "price_data_5yr.parquet").exists():
        pytest.skip("cache/baseline/ not available")
    price = pd.read_parquet(BASELINE_DIR / "price_data_5yr.parquet")
    factor = pd.read_parquet(BASELINE_DIR / "factor_data_5yr.parquet")
    bench = pd.read_parquet(BASELINE_DIR / "benchmark_5yr.parquet")
    return price, factor, bench


def _default_config() -> BacktestConfig:
    return BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )


DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}


class TestEngineE2E:
    def test_5yr_matches_baseline(self):
        """5yr回测结果跟regression基准匹配。"""
        price, factor, bench = _load_baseline()
        config = _default_config()
        result = run_hybrid_backtest(factor, DIRECTIONS, price, config, bench)

        nav = result.daily_nav
        sharpe = calc_sharpe(result.daily_returns)

        # 加载基准metrics
        metrics_path = BASELINE_DIR / "metrics_5yr.json"
        if metrics_path.exists():
            with open(metrics_path) as f:
                baseline = json.load(f)
            assert abs(sharpe - baseline["sharpe"]) < 0.001

        assert len(nav) > 1000  # 5yr > 1000 trading days
        assert float(nav.iloc[0]) == 1_000_000.0

    def test_deterministic_two_runs(self):
        """两次运行结果完全一致。"""
        price, factor, bench = _load_baseline()
        config = _default_config()

        r1 = run_hybrid_backtest(factor, DIRECTIONS, price, config, bench)
        r2 = run_hybrid_backtest(factor, DIRECTIONS, price, config, bench)

        diff = (r1.daily_nav - r2.daily_nav).abs().max()
        assert diff == 0.0

    def test_empty_factor_raises(self):
        """空因子数据 → 应该raise。"""
        price, _, bench = _load_baseline()
        empty_factor = pd.DataFrame(columns=["code", "trade_date", "factor_name", "raw_value"])
        config = _default_config()

        with pytest.raises(ValueError, match="target_portfolios为空"):
            run_hybrid_backtest(empty_factor, DIRECTIONS, price, config, bench)

    def test_single_month_runs(self):
        """单月数据能跑通(最小可行回测)。"""
        price, factor, bench = _load_baseline()

        # 只取2024-06一个月
        from datetime import date
        m_start = date(2024, 6, 1)
        m_end = date(2024, 6, 30)
        p = price[(price["trade_date"] >= m_start) & (price["trade_date"] <= m_end)]
        f = factor[(factor["trade_date"] >= m_start) & (factor["trade_date"] <= m_end)]
        b = bench[(bench["trade_date"] >= m_start) & (bench["trade_date"] <= m_end)]

        if p.empty or f.empty:
            pytest.skip("No data for 2024-06")

        config = _default_config()
        result = run_hybrid_backtest(f, DIRECTIONS, p, config, b)
        assert len(result.daily_nav) > 0
