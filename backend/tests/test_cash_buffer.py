"""现金缓冲3%强制保留测试 — Sprint 1.10 Task 3.

验证 PortfolioBuilder 的 cash_buffer 参数:
1. 等权Top-15: 权重总和 = 0.97 (不是1.0)
2. cash_buffer=0 时权重总和 = 1.0 (向后兼容)
3. 整手约束后 cash_drag 不为负 (执行层验证)
4. 权重总和精确 = 1 - cash_buffer
5. PAPER_TRADING_CONFIG 默认含 3% 缓冲
"""

from __future__ import annotations

import pandas as pd
from engines.signal_engine import PAPER_TRADING_CONFIG, PortfolioBuilder, SignalConfig


def _make_scores(n: int) -> pd.Series:
    """构造n只股票的等差评分序列(从高到低)。"""
    codes = [f"{i:06d}" for i in range(1, n + 1)]
    scores = pd.Series(range(n, 0, -1), index=codes, dtype=float)
    return scores


def _make_industry(n: int, all_different: bool = True) -> pd.Series:
    """构造行业映射，默认所有股票不同行业（不触发行业约束）。"""
    codes = [f"{i:06d}" for i in range(1, n + 1)]
    if all_different:
        industries = [f"行业{i}" for i in range(1, n + 1)]
    else:
        industries = ["行业A"] * n
    return pd.Series(industries, index=codes)


class TestCashBuffer:
    """cash_buffer 逻辑验证。"""

    def test_default_cash_buffer_3pct(self):
        """默认cash_buffer=0.03，权重总和=0.97。"""
        config = SignalConfig(top_n=15, cash_buffer=0.03)
        builder = PortfolioBuilder(config)
        scores = _make_scores(100)
        industry = _make_industry(100)

        target = builder.build(scores, industry)

        assert len(target) == 15
        total_weight = sum(target.values())
        assert abs(total_weight - 0.97) < 1e-9, f"权重总和={total_weight:.6f}，期望0.97"

    def test_zero_cash_buffer_weights_sum_to_one(self):
        """cash_buffer=0时权重总和=1.0（向后兼容）。"""
        config = SignalConfig(top_n=15, cash_buffer=0.0)
        builder = PortfolioBuilder(config)
        scores = _make_scores(100)
        industry = _make_industry(100)

        target = builder.build(scores, industry)

        total_weight = sum(target.values())
        assert abs(total_weight - 1.0) < 1e-9, f"权重总和={total_weight:.6f}，期望1.0"

    def test_equal_weight_with_buffer(self):
        """Top-15等权+3%缓冲: 每只股票权重 = (1/15)*0.97。"""
        config = SignalConfig(top_n=15, cash_buffer=0.03)
        builder = PortfolioBuilder(config)
        scores = _make_scores(100)
        industry = _make_industry(100)

        target = builder.build(scores, industry)

        expected_weight = (1.0 / 15) * 0.97
        for code, weight in target.items():
            assert abs(weight - expected_weight) < 1e-9, (
                f"{code}: weight={weight:.8f} != {expected_weight:.8f}"
            )

    def test_cash_buffer_5pct(self):
        """自定义cash_buffer=0.05，权重总和=0.95。"""
        config = SignalConfig(top_n=10, cash_buffer=0.05)
        builder = PortfolioBuilder(config)
        scores = _make_scores(50)
        industry = _make_industry(50)

        target = builder.build(scores, industry)

        total_weight = sum(target.values())
        assert abs(total_weight - 0.95) < 1e-9, f"权重总和={total_weight:.6f}，期望0.95"

    def test_paper_trading_config_has_3pct_buffer(self):
        """PAPER_TRADING_CONFIG含3%现金缓冲配置。"""
        assert PAPER_TRADING_CONFIG.cash_buffer == 0.03

    def test_paper_trading_config_weights_sum_to_97pct(self):
        """PAPER_TRADING_CONFIG生成权重总和≤0.97（含行业约束可能更低）。"""
        builder = PortfolioBuilder(PAPER_TRADING_CONFIG)
        scores = _make_scores(500)
        industry = _make_industry(500)

        target = builder.build(scores, industry)

        total_weight = sum(target.values())
        assert total_weight <= 0.97 + 1e-9, f"权重总和={total_weight:.6f}超过0.97"

    def test_cash_drag_not_negative(self):
        """整手约束后现金拖累 cash_drag >= 0（即 cash >= 3%总资产）。

        模拟: 100万总资产，等权15只，3%缓冲，目标总权重=0.97=97万。
        每只目标金额=97万/15≈6.47万，下整手后≤6.47万。
        总投资≤97万，cash≥3万≥3%总资产。
        """
        total_value = 1_000_000
        config = SignalConfig(top_n=15, cash_buffer=0.03)
        builder = PortfolioBuilder(config)
        scores = _make_scores(500)
        industry = _make_industry(500)
        target = builder.build(scores, industry)

        lot_size = 100
        total_invested = 0.0
        avg_price = 50.0   # 假设每只股票均价50元

        for code, weight in target.items():
            target_value = total_value * weight
            shares = int(target_value / avg_price / lot_size) * lot_size
            actual_value = shares * avg_price
            total_invested += actual_value

        cash_remaining = total_value - total_invested
        cash_buffer_pct = cash_remaining / total_value

        assert cash_buffer_pct >= 0, (
            f"现金拖累为负: cash={cash_remaining:.0f}，cash_pct={cash_buffer_pct:.2%}"
        )
        # 通过3%缓冲，现金至少≥3% - 因整手约束通常会保留更多
        assert cash_buffer_pct >= 0.03 - 0.005, (
            f"现金比例{cash_buffer_pct:.2%}低于预期最低值~2.5%"
        )

    def test_empty_universe_returns_empty(self):
        """空股票池返回空dict，不报错。"""
        config = SignalConfig(top_n=15, cash_buffer=0.03)
        builder = PortfolioBuilder(config)
        scores = pd.Series(dtype=float)
        industry = pd.Series(dtype=str)

        target = builder.build(scores, industry)
        assert target == {}
