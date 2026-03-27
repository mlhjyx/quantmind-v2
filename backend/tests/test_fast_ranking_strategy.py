"""FastRankingStrategy 单元测试。

验证清单:
- config验证: rebalance_freq只允许daily/weekly，top_n范围[5,30]
- new_position_discount折扣逻辑（换手率超目标时触发）
- turnover_target换手率控制
- 与EqualWeightStrategy的接口兼容性（都返回StrategyDecision）
- 覆盖率检查: <500抛错，<2000告警
- daily频率should_rebalance=True
- 因子缺失/空信号抛错
"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base_strategy import (
    RebalanceFreq,
    SignalType,
    StrategyContext,
    StrategyDecision,
    StrategyMeta,
    WeightMethod,
)
from engines.strategies.fast_ranking import FastRankingStrategy

# ============================================================
# 测试工具
# ============================================================


def _make_fast_config(**overrides) -> dict:
    """生成FastRankingStrategy标准配置。"""
    config = {
        "factor_names": ["vwap_bias"],
        "top_n": 10,
        "weight_method": "equal",
        "industry_cap": 0.50,
        "rebalance_freq": "weekly",
        "turnover_cap": 0.80,
        "turnover_target": 0.30,
        "new_position_discount": 0.80,
    }
    config.update(overrides)
    return config


def _make_factor_df(codes: list[str], factor_name: str = "vwap_bias", seed: int = 42) -> pd.DataFrame:
    """生成模拟因子DataFrame。"""
    rng = np.random.RandomState(seed)
    rows = [
        {"code": c, "factor_name": factor_name, "neutral_value": rng.randn()}
        for c in codes
    ]
    return pd.DataFrame(rows)


def _make_codes(n: int) -> list[str]:
    return [f"60{i:04d}.SH" for i in range(n)]


def _make_industry_map(codes: list[str]) -> dict[str, str]:
    return {c: f"行业{i % 10}" for i, c in enumerate(codes)}


def _make_context(
    codes: list[str],
    factor_names: list[str] | None = None,
    prev_holdings: dict[str, float] | None = None,
    seed: int = 42,
) -> StrategyContext:
    """构建StrategyContext，不含真实DB连接。"""
    if factor_names is None:
        factor_names = ["vwap_bias"]

    rows = []
    rng = np.random.RandomState(seed)
    for c in codes:
        for fn in factor_names:
            rows.append({"code": c, "factor_name": fn, "neutral_value": rng.randn()})

    factor_df = pd.DataFrame(rows)
    industry_map = _make_industry_map(codes)

    return StrategyContext(
        strategy_id="test_fast_ranking",
        trade_date=date(2024, 1, 31),
        factor_df=factor_df,
        universe=set(codes),
        industry_map=industry_map,
        prev_holdings=prev_holdings,
        conn=MagicMock(),
        total_capital=1_000_000.0,
    )


# ============================================================
# 1. 配置验证
# ============================================================


class TestFastRankingStrategyConfig:
    """FastRankingStrategy配置验证。"""

    def test_valid_weekly_config(self) -> None:
        """weekly频率可以实例化。"""
        config = _make_fast_config(rebalance_freq="weekly")
        strategy = FastRankingStrategy(config=config, strategy_id="fast_weekly")
        assert strategy.strategy_id == "fast_weekly"

    def test_valid_daily_config(self) -> None:
        """daily频率可以实例化。"""
        config = _make_fast_config(rebalance_freq="daily")
        strategy = FastRankingStrategy(config=config, strategy_id="fast_daily")
        assert strategy.strategy_id == "fast_daily"

    def test_monthly_freq_raises(self) -> None:
        """monthly频率不允许，应抛ValueError。"""
        config = _make_fast_config(rebalance_freq="monthly")
        with pytest.raises(ValueError, match="只支持快频率"):
            FastRankingStrategy(config=config, strategy_id="bad")

    def test_biweekly_freq_raises(self) -> None:
        """biweekly频率不允许，应抛ValueError。"""
        config = _make_fast_config(rebalance_freq="biweekly")
        with pytest.raises(ValueError, match="只支持快频率"):
            FastRankingStrategy(config=config, strategy_id="bad")

    def test_top_n_too_small_raises(self) -> None:
        """top_n=4 < 5，应抛ValueError。"""
        config = _make_fast_config(top_n=4)
        with pytest.raises(ValueError, match="top_n建议"):
            FastRankingStrategy(config=config, strategy_id="bad")

    def test_top_n_too_large_raises(self) -> None:
        """top_n=31 > 30，应抛ValueError。"""
        config = _make_fast_config(top_n=31)
        with pytest.raises(ValueError, match="top_n建议"):
            FastRankingStrategy(config=config, strategy_id="bad")

    def test_top_n_boundary_5_valid(self) -> None:
        """top_n=5（边界下限）合法。"""
        config = _make_fast_config(top_n=5)
        strategy = FastRankingStrategy(config=config, strategy_id="ok")
        assert strategy is not None

    def test_top_n_boundary_30_valid(self) -> None:
        """top_n=30（边界上限）合法。"""
        config = _make_fast_config(top_n=30)
        strategy = FastRankingStrategy(config=config, strategy_id="ok")
        assert strategy is not None

    def test_discount_below_half_raises(self) -> None:
        """new_position_discount=0.4 < 0.5，应抛ValueError。"""
        config = _make_fast_config(new_position_discount=0.4)
        with pytest.raises(ValueError, match="new_position_discount"):
            FastRankingStrategy(config=config, strategy_id="bad")

    def test_discount_above_1_raises(self) -> None:
        """new_position_discount=1.1 > 1.0，应抛ValueError。"""
        config = _make_fast_config(new_position_discount=1.1)
        with pytest.raises(ValueError, match="new_position_discount"):
            FastRankingStrategy(config=config, strategy_id="bad")

    def test_missing_factor_names_raises(self) -> None:
        """factor_names缺失应抛ValueError（继承BaseStrategy验证）。"""
        config = _make_fast_config()
        del config["factor_names"]
        with pytest.raises(ValueError):
            FastRankingStrategy(config=config, strategy_id="bad")

    def test_meta_info(self) -> None:
        """元信息包含daily和weekly频率。"""
        meta = FastRankingStrategy.get_meta()
        assert isinstance(meta, StrategyMeta)
        assert meta.name == "fast_ranking"
        assert RebalanceFreq.DAILY in meta.supported_freqs
        assert RebalanceFreq.WEEKLY in meta.supported_freqs
        assert RebalanceFreq.MONTHLY not in meta.supported_freqs
        assert WeightMethod.EQUAL in meta.supported_weights


# ============================================================
# 2. should_rebalance测试
# ============================================================


class TestFastRankingRebalance:
    """should_rebalance频率逻辑验证。"""

    def test_daily_always_rebalances(self) -> None:
        """daily频率每日调仓=True。"""
        config = _make_fast_config(rebalance_freq="daily")
        strategy = FastRankingStrategy(config=config, strategy_id="daily_strat")
        result = strategy.should_rebalance(date(2024, 1, 15), MagicMock())
        assert result is True

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_weekly_rebalances_on_rebalance_date(self, mock_dates) -> None:
        """weekly频率在调仓日返回True。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        config = _make_fast_config(rebalance_freq="weekly")
        strategy = FastRankingStrategy(config=config, strategy_id="weekly_strat")
        result = strategy.should_rebalance(date(2024, 1, 31), MagicMock())
        assert result is True

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_weekly_no_rebalance_on_non_rebalance_date(self, mock_dates) -> None:
        """weekly频率在非调仓日返回False。"""
        mock_dates.return_value = [date(2024, 2, 7)]
        config = _make_fast_config(rebalance_freq="weekly")
        strategy = FastRankingStrategy(config=config, strategy_id="weekly_strat")
        result = strategy.should_rebalance(date(2024, 1, 31), MagicMock())
        assert result is False


# ============================================================
# 3. generate_signals输出验证
# ============================================================


class TestFastRankingGenerateSignals:
    """generate_signals核心逻辑验证。"""

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_returns_strategy_decision(self, mock_dates) -> None:
        """generate_signals返回StrategyDecision实例。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(2000)
        config = _make_fast_config(top_n=10)
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        context = _make_context(codes)

        decision = strategy.generate_signals(context)
        assert isinstance(decision, StrategyDecision)

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_returns_at_most_top_n_stocks(self, mock_dates) -> None:
        """返回持仓数≤top_n。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3000)
        config = _make_fast_config(top_n=10)
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        context = _make_context(codes)

        decision = strategy.generate_signals(context)
        assert len(decision.target_weights) <= 10

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_signal_type_is_ranking(self, mock_dates) -> None:
        """signal_type标记为RANKING。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(2000)
        config = _make_fast_config()
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        context = _make_context(codes)

        decision = strategy.generate_signals(context)
        assert decision.signal_type == SignalType.RANKING

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_weights_positive(self, mock_dates) -> None:
        """所有目标权重为正数。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(2000)
        config = _make_fast_config()
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        context = _make_context(codes)

        decision = strategy.generate_signals(context)
        for code, w in decision.target_weights.items():
            assert w > 0, f"{code}权重={w}不为正"

    def test_missing_factor_raises(self) -> None:
        """因子缺失应抛ValueError。"""
        codes = _make_codes(2000)
        config = _make_fast_config(factor_names=["vwap_bias"])
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        # 提供wrong_factor而非vwap_bias
        context = _make_context(codes, factor_names=["wrong_factor"])

        with pytest.raises(ValueError, match="因子缺失"):
            strategy.generate_signals(context)

    def test_low_coverage_raises(self) -> None:
        """覆盖率<500应抛ValueError。"""
        codes = _make_codes(100)
        config = _make_fast_config()
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        context = _make_context(codes)

        with pytest.raises(ValueError, match="覆盖率严重不足"):
            strategy.generate_signals(context)

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_medium_coverage_warns(self, mock_dates) -> None:
        """覆盖率500-2000产生警告但不抛错。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(800)
        config = _make_fast_config(top_n=5)
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        context = _make_context(codes)

        decision = strategy.generate_signals(context)
        assert any("覆盖率偏低" in w for w in decision.warnings)


# ============================================================
# 4. 新进个股折扣逻辑
# ============================================================


class TestNewPositionDiscount:
    """new_position_discount折扣逻辑验证。"""

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_no_prev_holdings_no_discount(self, mock_dates) -> None:
        """prev_holdings=None时不施加折扣（无上期持仓）。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(2000)
        config = _make_fast_config(new_position_discount=0.5, turnover_target=0.1)
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        context = _make_context(codes, prev_holdings=None)

        decision = strategy.generate_signals(context)
        # 无prev_holdings → _apply_new_position_discount不调用，无折扣告警
        assert not any("折扣" in w for w in decision.warnings)

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_high_turnover_triggers_discount(self, mock_dates) -> None:
        """换手率超目标时触发折扣并产生告警。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(2000)
        config = _make_fast_config(
            top_n=10,
            new_position_discount=0.7,
            turnover_target=0.01,  # 极低目标，必然触发
        )
        strategy = FastRankingStrategy(config=config, strategy_id="test")

        # prev_holdings：完全不同的10只老股（旧前缀）
        old_codes = [f"90{i:04d}.SH" for i in range(10)]
        prev = {c: 0.1 for c in old_codes}
        context = _make_context(codes, prev_holdings=prev)

        decision = strategy.generate_signals(context)
        # 高换手→触发折扣告警
        assert any("折扣" in w for w in decision.warnings)

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_low_turnover_no_discount(self, mock_dates) -> None:
        """换手率在目标内不触发折扣。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(2000)

        # 生成策略和信号，拿到top持仓
        config = _make_fast_config(top_n=5, turnover_target=0.99)
        strategy = FastRankingStrategy(config=config, strategy_id="test")
        context_no_prev = _make_context(codes, prev_holdings=None)
        base_decision = strategy.generate_signals(context_no_prev)

        # 将base_decision的持仓作为prev_holdings → 0换手
        prev = dict(base_decision.target_weights)
        strategy2 = FastRankingStrategy(config=config, strategy_id="test2")
        context_with_prev = _make_context(codes, prev_holdings=prev, seed=42)
        mock_dates.return_value = [date(2024, 1, 31)]
        decision = strategy2.generate_signals(context_with_prev)

        # 因为prev和target完全相同(seed相同)，换手率=0 < turnover_target=0.99
        assert not any("折扣" in w for w in decision.warnings)

    def test_discount_method_high_turnover(self) -> None:
        """直接测试_apply_new_position_discount在高换手场景。"""
        config = _make_fast_config(new_position_discount=0.6, turnover_target=0.1)
        strategy = FastRankingStrategy(config=config, strategy_id="test")

        # prev: A, B, C   target: C, D, E（换手率很高）
        prev = {"A.SH": 0.33, "B.SH": 0.33, "C.SH": 0.34}
        target = {"C.SH": 0.33, "D.SH": 0.33, "E.SH": 0.34}
        warnings: list[str] = []

        adjusted = strategy._apply_new_position_discount(target, prev, warnings)

        # 高换手 → 产生折扣告警
        assert len(warnings) > 0
        assert any("折扣" in w for w in warnings)
        # 总权重应保持（归一化）
        assert abs(sum(adjusted.values()) - sum(target.values())) < 1e-9

    def test_discount_method_no_new_stocks(self) -> None:
        """没有新进个股时，_apply_new_position_discount直接返回原target。"""
        config = _make_fast_config(new_position_discount=0.5)
        strategy = FastRankingStrategy(config=config, strategy_id="test")

        prev = {"A.SH": 0.5, "B.SH": 0.5}
        target = {"A.SH": 0.5, "B.SH": 0.5}  # 完全相同，无新进
        warnings: list[str] = []

        adjusted = strategy._apply_new_position_discount(target, prev, warnings)
        assert adjusted is target  # 直接返回原对象

    def test_discount_weight_reduced_for_new_stocks(self) -> None:
        """折扣后新进股票权重相对于原权重降低。"""
        config = _make_fast_config(new_position_discount=0.5, turnover_target=0.01)
        strategy = FastRankingStrategy(config=config, strategy_id="test")

        prev = {"A.SH": 1.0}
        # B和C是新进个股
        target = {"A.SH": 0.33, "B.SH": 0.33, "C.SH": 0.34}
        warnings: list[str] = []

        adjusted = strategy._apply_new_position_discount(target, prev, warnings)

        # 新进B, C应被折扣，权重相对A更低
        # 折扣后归一化，A的比例应高于B、C
        total = sum(adjusted.values())
        if total > 0:
            a_ratio = adjusted.get("A.SH", 0) / total
            b_ratio = adjusted.get("B.SH", 0) / total
            c_ratio = adjusted.get("C.SH", 0) / total
            # A未被折扣，比例应高于B和C（被折扣到50%）
            assert a_ratio > b_ratio
            assert a_ratio > c_ratio


# ============================================================
# 5. 接口兼容性（与EqualWeightStrategy对比）
# ============================================================


class TestFastRankingInterfaceCompatibility:
    """FastRankingStrategy与EqualWeightStrategy接口兼容性。"""

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_returns_strategy_decision_type(self, mock_dates) -> None:
        """返回StrategyDecision（与EqualWeightStrategy接口一致）。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(2000)
        config = _make_fast_config()
        strategy = FastRankingStrategy(config=config, strategy_id="compat_test")
        context = _make_context(codes)

        result = strategy.generate_signals(context)
        assert isinstance(result, StrategyDecision)
        assert hasattr(result, "target_weights")
        assert hasattr(result, "is_rebalance")
        assert hasattr(result, "reasoning")
        assert hasattr(result, "warnings")
        assert hasattr(result, "signal_type")

    @patch("engines.strategies.fast_ranking.get_rebalance_dates")
    def test_deterministic_same_input_same_output(self, mock_dates) -> None:
        """同输入跑两次结果完全一致（确定性）。"""
        mock_dates.return_value = [date(2024, 1, 31)]
        codes = _make_codes(2000)
        config = _make_fast_config(top_n=8)

        results = []
        for _ in range(2):
            strategy = FastRankingStrategy(config=config, strategy_id="det_test")
            context = _make_context(codes, seed=42)
            decision = strategy.generate_signals(context)
            results.append(decision.target_weights)

        assert results[0] == results[1]

    def test_can_be_used_in_composite_as_core(self) -> None:
        """FastRankingStrategy可作为CompositeStrategy的核心策略（duck typing）。"""

        # FastRankingStrategy有generate_signals方法，符合BaseStrategy协议
        assert hasattr(FastRankingStrategy, "generate_signals")
        assert hasattr(FastRankingStrategy, "should_rebalance")
        assert hasattr(FastRankingStrategy, "get_meta")
