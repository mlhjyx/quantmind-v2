"""Brinson-Fachler归因 + 市场状态检测器 测试。

覆盖:
- single_period: 同权重→excess=0
- single_period: 不同行业权重→allocation!=0
- total_excess = allocation + selection + interaction 恒等式
- multi_period + summary
- MarketStateDetector: 牛市/熊市/震荡分类
- segment_performance: 分段统计
"""

from datetime import date

import numpy as np
import pandas as pd
from engines.attribution import BrinsonAttribution, BrinsonResult, MarketStateDetector

# ===========================================================================
# Brinson单期归因测试
# ===========================================================================


class TestBrinsonSinglePeriod:
    """单期Brinson-Fachler归因。"""

    def setup_method(self):
        self.engine = BrinsonAttribution()
        self.period = (date(2023, 1, 1), date(2023, 1, 31))

    def test_same_weights_zero_excess(self):
        """组合权重=基准权重 → total_excess=0 (同收益率)。"""
        weights = {"A": 0.3, "B": 0.3, "C": 0.4}
        returns = {"A": 0.05, "B": -0.02, "C": 0.03}
        industry_map = {"A": "银行", "B": "电子", "C": "医药"}

        result = self.engine.single_period(
            portfolio_weights=weights,
            benchmark_weights=weights,
            portfolio_returns=returns,
            benchmark_returns=returns,
            industry_map=industry_map,
            period=self.period,
        )

        assert isinstance(result, BrinsonResult)
        assert abs(result.total_excess) < 1e-10
        assert abs(result.allocation_effect) < 1e-10
        assert abs(result.selection_effect) < 1e-10
        assert abs(result.interaction_effect) < 1e-10

    def test_different_weights_nonzero_allocation(self):
        """不同行业权重 → allocation_effect != 0。"""
        portfolio_weights = {"A": 0.5, "B": 0.2, "C": 0.3}
        benchmark_weights = {"A": 0.3, "B": 0.3, "C": 0.4}
        # 相同收益率 → selection=0, 但权重不同 → allocation!=0
        returns = {"A": 0.05, "B": -0.02, "C": 0.03}
        industry_map = {"A": "银行", "B": "电子", "C": "医药"}

        result = self.engine.single_period(
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=returns,
            benchmark_returns=returns,
            industry_map=industry_map,
            period=self.period,
        )

        # 权重不同但收益相同 → allocation != 0, selection = 0
        assert abs(result.allocation_effect) > 1e-10
        assert abs(result.selection_effect) < 1e-10

    def test_excess_decomposition_identity(self):
        """total_excess = allocation + selection + interaction 恒等式。"""
        portfolio_weights = {"A": 0.4, "B": 0.25, "C": 0.35}
        benchmark_weights = {"A": 0.3, "B": 0.3, "C": 0.4}
        portfolio_returns = {"A": 0.06, "B": -0.01, "C": 0.04}
        benchmark_returns = {"A": 0.05, "B": -0.02, "C": 0.03}
        industry_map = {"A": "银行", "B": "电子", "C": "医药"}

        result = self.engine.single_period(
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            industry_map=industry_map,
            period=self.period,
        )

        # 恒等式验证
        assert abs(
            result.total_excess
            - (result.allocation_effect + result.selection_effect + result.interaction_effect)
        ) < 1e-10

    def test_excess_matches_direct_calculation(self):
        """total_excess ≈ 组合收益 - 基准收益。"""
        portfolio_weights = {"A": 0.5, "B": 0.5}
        benchmark_weights = {"A": 0.3, "B": 0.7}
        portfolio_returns = {"A": 0.10, "B": -0.05}
        benchmark_returns = {"A": 0.08, "B": -0.03}
        industry_map = {"A": "银行", "B": "电子"}

        result = self.engine.single_period(
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            industry_map=industry_map,
            period=self.period,
        )

        # 直接计算
        r_p = sum(portfolio_weights[c] * portfolio_returns[c] for c in portfolio_weights)
        r_b = sum(benchmark_weights[c] * benchmark_returns[c] for c in benchmark_weights)
        expected_excess = r_p - r_b

        assert abs(result.total_excess - expected_excess) < 1e-10

    def test_industry_detail_columns(self):
        """归因结果的industry_detail应包含所需列。"""
        weights = {"A": 0.5, "B": 0.5}
        returns = {"A": 0.05, "B": 0.03}
        industry_map = {"A": "银行", "B": "电子"}

        result = self.engine.single_period(
            portfolio_weights=weights,
            benchmark_weights=weights,
            portfolio_returns=returns,
            benchmark_returns=returns,
            industry_map=industry_map,
            period=self.period,
        )

        expected_cols = {"industry", "w_p", "w_b", "r_p", "r_b",
                         "allocation", "selection", "interaction", "total"}
        assert expected_cols.issubset(set(result.industry_detail.columns))

    def test_unknown_industry(self):
        """无行业映射的股票归入'未知'。"""
        portfolio_weights = {"A": 0.5, "B": 0.5}
        benchmark_weights = {"A": 0.5, "B": 0.5}
        returns = {"A": 0.05, "B": 0.03}
        industry_map = {"A": "银行"}  # B没有映射

        result = self.engine.single_period(
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=returns,
            benchmark_returns=returns,
            industry_map=industry_map,
            period=self.period,
        )

        industries = result.industry_detail["industry"].tolist()
        assert "未知" in industries

    def test_empty_portfolios(self):
        """空组合应返回零归因。"""
        result = self.engine.single_period(
            portfolio_weights={},
            benchmark_weights={},
            portfolio_returns={},
            benchmark_returns={},
            industry_map={},
            period=self.period,
        )
        assert result.total_excess == 0.0
        assert result.industry_detail.empty

    def test_only_selection_effect(self):
        """同权重不同收益 → 只有selection effect。"""
        weights = {"A": 0.5, "B": 0.5}
        industry_map = {"A": "银行", "B": "电子"}
        p_returns = {"A": 0.10, "B": 0.02}
        b_returns = {"A": 0.05, "B": -0.01}

        result = self.engine.single_period(
            portfolio_weights=weights,
            benchmark_weights=weights,
            portfolio_returns=p_returns,
            benchmark_returns=b_returns,
            industry_map=industry_map,
            period=self.period,
        )

        # 权重相同 → allocation=0, interaction=0
        assert abs(result.allocation_effect) < 1e-10
        assert abs(result.interaction_effect) < 1e-10
        # 收益不同 → selection != 0
        assert abs(result.selection_effect) > 1e-10


# ===========================================================================
# Brinson summary测试
# ===========================================================================


class TestBrinsonSummary:
    """multi_period的summary汇总。"""

    def test_summary_empty(self):
        engine = BrinsonAttribution()
        summary = engine.summary([])
        assert summary["cumulative_excess"] == 0.0
        assert summary["period_count"] == 0

    def test_summary_accumulates(self):
        """多期summary正确累加。"""
        engine = BrinsonAttribution()
        r1 = BrinsonResult(
            total_excess=0.02, allocation_effect=0.01,
            selection_effect=0.008, interaction_effect=0.002,
            industry_detail=pd.DataFrame([
                {"industry": "银行", "allocation": 0.01, "selection": 0.005,
                 "interaction": 0.001, "total": 0.016}
            ]),
            period=(date(2023, 1, 1), date(2023, 1, 31)),
        )
        r2 = BrinsonResult(
            total_excess=0.03, allocation_effect=0.015,
            selection_effect=0.01, interaction_effect=0.005,
            industry_detail=pd.DataFrame([
                {"industry": "银行", "allocation": 0.008, "selection": 0.012,
                 "interaction": 0.003, "total": 0.023}
            ]),
            period=(date(2023, 2, 1), date(2023, 2, 28)),
        )

        summary = engine.summary([r1, r2])
        assert abs(summary["cumulative_excess"] - 0.05) < 1e-10
        assert abs(summary["cumulative_allocation"] - 0.025) < 1e-10
        assert summary["period_count"] == 2
        assert not summary["industry_summary"].empty


# ===========================================================================
# MarketStateDetector测试
# ===========================================================================


class TestMarketStateDetector:
    """市场状态检测器: 牛/熊/震荡分类。"""

    def setup_method(self):
        self.detector = MarketStateDetector()

    def _make_returns(self, daily_return: float, n_days: int = 200) -> pd.Series:
        """构造恒定日收益的Series。"""
        dates = pd.bdate_range("2023-01-01", periods=n_days)
        return pd.Series(daily_return, index=dates)

    def test_bull_market_detection(self):
        """持续正收益应被分类为牛市。"""
        # 日收益0.3%，60日累计≈19.7%，远超10%阈值
        returns = self._make_returns(0.003, n_days=200)
        states = self.detector.classify(returns)

        # 前60天数据不够，后面应有bull
        bull_count = (states == "bull").sum()
        assert bull_count > 0

    def test_bear_market_detection(self):
        """持续负收益应被分类为熊市。"""
        # 日收益-0.3%，60日累计≈-16.5%
        returns = self._make_returns(-0.003, n_days=200)
        states = self.detector.classify(returns)

        bear_count = (states == "bear").sum()
        assert bear_count > 0

    def test_sideways_market(self):
        """小幅波动应被分类为震荡。"""
        # 交替正负小收益
        rng = np.random.default_rng(42)
        dates = pd.bdate_range("2023-01-01", periods=200)
        returns = pd.Series(rng.normal(0, 0.002, 200), index=dates)
        states = self.detector.classify(returns)

        sideways_count = (states == "sideways").sum()
        # 小波动时大部分应是sideways
        assert sideways_count > len(states) * 0.3

    def test_short_series_all_sideways(self):
        """短序列(< long_ma窗口)全部标为sideways。"""
        dates = pd.bdate_range("2023-01-01", periods=30)
        returns = pd.Series(0.001, index=dates)
        states = self.detector.classify(returns)

        assert (states == "sideways").all()

    def test_empty_returns(self):
        """空Series返回空states。"""
        returns = pd.Series(dtype=float)
        states = self.detector.classify(returns)
        assert len(states) == 0

    def test_classify_returns_correct_index(self):
        """分类结果index应与输入一致。"""
        returns = self._make_returns(0.001, 100)
        states = self.detector.classify(returns)
        assert states.index.equals(returns.index)

    def test_only_valid_state_values(self):
        """所有值只能是 bull/bear/sideways。"""
        returns = self._make_returns(0.002, 200)
        states = self.detector.classify(returns)
        valid_states = {"bull", "bear", "sideways"}
        assert set(states.unique()).issubset(valid_states)

    def test_segment_performance_structure(self):
        """segment_performance返回正确结构。"""
        dates = pd.bdate_range("2023-01-01", periods=200)
        rng = np.random.default_rng(42)
        strat_returns = pd.Series(rng.normal(0.0005, 0.01, 200), index=dates)
        bm_returns = pd.Series(rng.normal(0.0003, 0.008, 200), index=dates)

        perf = self.detector.segment_performance(strat_returns, bm_returns)

        assert "bull" in perf
        assert "bear" in perf
        assert "sideways" in perf

        for state_perf in perf.values():
            assert "ann_return" in state_perf
            assert "sharpe" in state_perf
            assert "mdd" in state_perf
            assert "trading_days" in state_perf
            assert "excess_return" in state_perf

    def test_segment_performance_days_sum(self):
        """所有状态的交易日数之和应等于总交易日。"""
        dates = pd.bdate_range("2023-01-01", periods=200)
        rng = np.random.default_rng(123)
        strat_returns = pd.Series(rng.normal(0.0005, 0.01, 200), index=dates)
        bm_returns = pd.Series(rng.normal(0.0003, 0.008, 200), index=dates)

        perf = self.detector.segment_performance(strat_returns, bm_returns)

        total_days = sum(p["trading_days"] for p in perf.values())
        assert total_days == 200
