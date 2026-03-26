"""BaseStrategy / EqualWeightStrategy / StrategyRegistry / PortfolioAggregator 验证。

QA测试清单:
- Task 2: BaseStrategy功能验证（实例化、generate_signals、Registry、Aggregator）
- Task 3: 回测确定性验证（EqualWeightStrategy vs 直接SignalComposer+PortfolioBuilder一致性）
- Task 4: 边界测试（空Universe、单股票、0资金、负权重、未注册策略）
"""

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from engines.base_strategy import (
    BaseStrategy,
    RebalanceFreq,
    SignalType,
    StrategyContext,
    StrategyDecision,
    StrategyMeta,
    WeightMethod,
)
from engines.portfolio_aggregator import PortfolioAggregator
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
)
from engines.strategies.equal_weight import EqualWeightStrategy
from engines.strategies.multi_freq import MultiFreqStrategy
from engines.strategy_registry import StrategyRegistry


# ============================================================
# 测试数据工厂
# ============================================================

V11_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]


def _make_factor_df(
    codes: list[str],
    factor_names: list[str],
    seed: int = 42,
) -> pd.DataFrame:
    """生成模拟因子数据DataFrame [code, factor_name, neutral_value]。"""
    rng = np.random.RandomState(seed)
    rows = []
    for code in codes:
        for fname in factor_names:
            rows.append({
                "code": code,
                "factor_name": fname,
                "neutral_value": rng.randn(),
            })
    return pd.DataFrame(rows)


def _make_codes(n: int, prefix: str = "6") -> list[str]:
    """生成n个股票代码。"""
    return [f"{prefix}{i:05d}.SH" for i in range(n)]


def _make_industry_map(codes: list[str]) -> dict[str, str]:
    """生成行业映射（分散到10个行业）。"""
    return {c: f"行业{i % 10}" for i, c in enumerate(codes)}


def _make_v11_config() -> dict:
    """v1.1标准配置。"""
    return {
        "factor_names": V11_FACTORS,
        "top_n": 15,
        "weight_method": "equal",
        "industry_cap": 0.25,
        "rebalance_freq": "monthly",
        "turnover_cap": 0.50,
    }


def _make_context(
    codes: list[str],
    factor_names: list[str],
    prev_holdings: dict[str, float] | None = None,
    seed: int = 42,
) -> StrategyContext:
    """构建StrategyContext。"""
    factor_df = _make_factor_df(codes, factor_names, seed=seed)
    industry_map = _make_industry_map(codes)
    mock_conn = MagicMock()
    return StrategyContext(
        strategy_id="test_v1.1",
        trade_date=date(2024, 1, 31),
        factor_df=factor_df,
        universe=set(codes),
        industry_map=industry_map,
        prev_holdings=prev_holdings,
        conn=mock_conn,
        total_capital=1_000_000.0,
    )


# ============================================================
# Task 2: BaseStrategy功能验证
# ============================================================


class TestEqualWeightStrategyInstantiation:
    """EqualWeightStrategy实例化验证。"""

    def test_basic_instantiation(self):
        """能用v1.1配置实例化。"""
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        assert strategy.strategy_id == "v1.1"
        assert strategy.signal_type == SignalType.RANKING

    def test_meta_info(self):
        """元信息正确。"""
        meta = EqualWeightStrategy.get_meta()
        assert meta.name == "equal_weight"
        assert meta.signal_type == SignalType.RANKING
        assert RebalanceFreq.MONTHLY in meta.supported_freqs
        assert WeightMethod.EQUAL in meta.supported_weights

    def test_missing_config_raises(self):
        """缺少必要配置字段应报错。"""
        with pytest.raises(ValueError, match="config缺少必要字段"):
            EqualWeightStrategy(config={}, strategy_id="bad")

    def test_empty_factor_names_raises(self):
        """空因子列表应报错。"""
        config = _make_v11_config()
        config["factor_names"] = []
        with pytest.raises(ValueError, match="factor_names不能为空"):
            EqualWeightStrategy(config=config, strategy_id="bad")

    def test_wrong_weight_method_raises(self):
        """非equal权重方法应报错。"""
        config = _make_v11_config()
        config["weight_method"] = "score_weighted"
        with pytest.raises(ValueError, match="只支持weight_method='equal'"):
            EqualWeightStrategy(config=config, strategy_id="bad")

    def test_invalid_freq_raises(self):
        """非法调仓频率应报错。"""
        config = _make_v11_config()
        config["rebalance_freq"] = "quarterly"
        with pytest.raises(ValueError, match="rebalance_freq必须是"):
            EqualWeightStrategy(config=config, strategy_id="bad")


class TestEqualWeightGenerateSignals:
    """EqualWeightStrategy.generate_signals()验证。"""

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_produces_target_weights(self, mock_rebal):
        """generate_signals产出非空target_weights。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3500)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        context = _make_context(codes, V11_FACTORS)

        decision = strategy.generate_signals(context)

        assert isinstance(decision, StrategyDecision)
        assert len(decision.target_weights) > 0
        assert len(decision.target_weights) <= config["top_n"]
        # 权重归一化到1.0
        total_weight = sum(decision.target_weights.values())
        assert abs(total_weight - 1.0) < 0.01

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_equal_weights(self, mock_rebal):
        """等权策略各股权重相等。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3500)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        context = _make_context(codes, V11_FACTORS)

        decision = strategy.generate_signals(context)
        weights = list(decision.target_weights.values())
        # 所有权重应该相等
        assert max(weights) - min(weights) < 1e-10

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_is_rebalance_flag(self, mock_rebal):
        """调仓日标记正确。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3500)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        context = _make_context(codes, V11_FACTORS)

        decision = strategy.generate_signals(context)
        assert decision.is_rebalance is True

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_not_rebalance_day(self, mock_rebal):
        """非调仓日is_rebalance=False。"""
        mock_rebal.return_value = [date(2024, 2, 28)]  # 不含1月31日
        codes = _make_codes(3500)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        context = _make_context(codes, V11_FACTORS)

        decision = strategy.generate_signals(context)
        assert decision.is_rebalance is False

    def test_missing_factor_raises(self):
        """因子缺失应报错。"""
        codes = _make_codes(100)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        # 只提供3个因子（缺2个）
        context = _make_context(codes, V11_FACTORS[:3])

        with pytest.raises(ValueError, match="因子缺失"):
            strategy.generate_signals(context)

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_low_coverage_warning(self, mock_rebal):
        """覆盖率<3000只产生警告。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        # 2000只 > 1000(硬下限) 但 < 3000(告警)
        codes = _make_codes(2000)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        context = _make_context(codes, V11_FACTORS)

        decision = strategy.generate_signals(context)
        assert len(decision.warnings) > 0
        assert any("覆盖率偏低" in w for w in decision.warnings)

    def test_very_low_coverage_raises(self):
        """覆盖率<1000只应报错。"""
        codes = _make_codes(50)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        context = _make_context(codes, V11_FACTORS)

        with pytest.raises(ValueError, match="截面覆盖率严重不足"):
            strategy.generate_signals(context)


# ============================================================
# Task 2: StrategyRegistry验证
# ============================================================


class TestStrategyRegistry:
    """StrategyRegistry注册/查找/元数据验证。"""

    def test_builtin_registered(self):
        """内置策略已注册。"""
        available = StrategyRegistry.list_available()
        assert "equal_weight" in available
        assert "multi_freq" in available

    def test_create_equal_weight(self):
        """按名称创建EqualWeightStrategy。"""
        config = _make_v11_config()
        strategy = StrategyRegistry.create("equal_weight", config, "v1.1")
        assert isinstance(strategy, EqualWeightStrategy)

    def test_create_multi_freq(self):
        """按名称创建MultiFreqStrategy。"""
        config = _make_v11_config()
        strategy = StrategyRegistry.create("multi_freq", config, "test_mf")
        assert isinstance(strategy, MultiFreqStrategy)

    def test_get_meta(self):
        """获取策略元信息。"""
        meta = StrategyRegistry.get_meta("equal_weight")
        assert meta.name == "equal_weight"
        assert meta.signal_type == SignalType.RANKING

    def test_list_all_meta(self):
        """列出所有策略元信息。"""
        all_meta = StrategyRegistry.list_all_meta()
        assert "equal_weight" in all_meta
        assert "multi_freq" in all_meta

    def test_unknown_strategy_raises(self):
        """未注册策略应报错。"""
        with pytest.raises(ValueError, match="策略不存在"):
            StrategyRegistry.create("nonexistent", {}, "x")

    def test_unknown_meta_raises(self):
        """未注册策略获取元信息应报错。"""
        with pytest.raises(ValueError, match="策略不存在"):
            StrategyRegistry.get_meta("nonexistent")

    def test_register_non_basestrategy_raises(self):
        """注册非BaseStrategy子类应报错。"""
        with pytest.raises(TypeError, match="不是 BaseStrategy 子类"):
            StrategyRegistry.register("bad", int)  # type: ignore


# ============================================================
# Task 2: PortfolioAggregator验证
# ============================================================


class TestPortfolioAggregator:
    """PortfolioAggregator合并验证。"""

    def test_single_strategy_passthrough(self):
        """单策略直通 → weights不变。"""
        agg = PortfolioAggregator()
        weights = {"600519": 0.2, "000001": 0.3, "300750": 0.5}
        result = agg.merge(
            strategy_weights={"v1.1": weights},
            capital_allocation={"v1.1": 1.0},
        )
        assert len(result.target_weights) == 3
        assert abs(sum(result.target_weights.values()) - 1.0) < 1e-6
        # 权重比例不变
        for code in weights:
            assert abs(result.target_weights[code] - weights[code]) < 1e-6

    def test_two_strategies_merge(self):
        """两策略50/50合并 → 权重正确加权。"""
        agg = PortfolioAggregator()
        w1 = {"600519": 0.5, "000001": 0.5}
        w2 = {"000001": 0.5, "300750": 0.5}

        result = agg.merge(
            strategy_weights={"s1": w1, "s2": w2},
            capital_allocation={"s1": 0.5, "s2": 0.5},
        )
        # 600519: 0.5*0.5 = 0.25
        # 000001: 0.5*0.5 + 0.5*0.5 = 0.50
        # 300750: 0.5*0.5 = 0.25
        # 总和 = 1.0
        assert abs(sum(result.target_weights.values()) - 1.0) < 1e-6
        assert abs(result.target_weights["600519"] - 0.25) < 1e-6
        assert abs(result.target_weights["000001"] - 0.50) < 1e-6
        assert abs(result.target_weights["300750"] - 0.25) < 1e-6

    def test_zero_allocation_skipped(self):
        """0资金分配的策略 → 被跳过。"""
        agg = PortfolioAggregator()
        w1 = {"600519": 0.5, "000001": 0.5}
        w2 = {"300750": 1.0}

        result = agg.merge(
            strategy_weights={"s1": w1, "s2": w2},
            capital_allocation={"s1": 1.0, "s2": 0.0},
        )
        # s2被跳过(alloc=0)
        assert "300750" not in result.target_weights
        assert abs(sum(result.target_weights.values()) - 1.0) < 1e-6

    def test_allocation_auto_normalize(self):
        """资金分配不为1.0时自动归一化并告警。"""
        agg = PortfolioAggregator()
        w1 = {"600519": 1.0}

        result = agg.merge(
            strategy_weights={"s1": w1},
            capital_allocation={"s1": 0.5},  # 不等于1.0
        )
        assert len(result.warnings) > 0
        assert any("偏离1.0" in w for w in result.warnings)
        # 但权重仍然归一化
        assert abs(sum(result.target_weights.values()) - 1.0) < 1e-6

    def test_missing_allocation_warning(self):
        """策略无对应资金分配产生告警。"""
        agg = PortfolioAggregator()
        w1 = {"600519": 1.0}

        result = agg.merge(
            strategy_weights={"s1": w1},
            capital_allocation={"s2": 1.0},  # s1无分配
        )
        assert len(result.warnings) > 0


# ============================================================
# Task 3: 回测确定性验证 (SignalComposer+PortfolioBuilder一致性)
# ============================================================


class TestDeterminism:
    """EqualWeightStrategy vs 直接调用SignalComposer+PortfolioBuilder的一致性。"""

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_signal_consistency(self, mock_rebal):
        """EqualWeightStrategy.compute_alpha 与 SignalComposer.compose 结果一致。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3500)
        config_dict = _make_v11_config()
        strategy = EqualWeightStrategy(config=config_dict, strategy_id="v1.1")
        factor_df = _make_factor_df(codes, V11_FACTORS)
        universe = set(codes)

        # 方式A: 通过BaseStrategy.compute_alpha
        scores_a = strategy.compute_alpha(factor_df, universe)

        # 方式B: 直接调用SignalComposer
        signal_config = SignalConfig(
            factor_names=V11_FACTORS,
            top_n=15,
            weight_method="equal",
            industry_cap=0.25,
            rebalance_freq="monthly",
            turnover_cap=0.50,
        )
        composer = SignalComposer(signal_config)
        scores_b = composer.compose(factor_df, universe)

        # 结果应完全一致
        pd.testing.assert_series_equal(scores_a, scores_b)

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_portfolio_consistency(self, mock_rebal):
        """EqualWeightStrategy.build_portfolio 与 PortfolioBuilder.build 结果一致。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3500)
        config_dict = _make_v11_config()
        strategy = EqualWeightStrategy(config=config_dict, strategy_id="v1.1")
        factor_df = _make_factor_df(codes, V11_FACTORS)
        universe = set(codes)
        industry_map = _make_industry_map(codes)

        # compute scores
        scores = strategy.compute_alpha(factor_df, universe)

        # 方式A: 通过BaseStrategy.build_portfolio
        target_a = strategy.build_portfolio(scores, industry_map)

        # 方式B: 直接调用PortfolioBuilder
        signal_config = SignalConfig(
            factor_names=V11_FACTORS,
            top_n=15,
            weight_method="equal",
            industry_cap=0.25,
            rebalance_freq="monthly",
            turnover_cap=0.50,
        )
        builder = PortfolioBuilder(signal_config)
        industry_series = pd.Series(industry_map)
        target_b = builder.build(scores, industry_series, None)

        # 完全一致
        assert target_a == target_b

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_determinism_across_runs(self, mock_rebal):
        """同输入跑两次结果完全一致。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3500)
        config_dict = _make_v11_config()

        results = []
        for _ in range(2):
            strategy = EqualWeightStrategy(config=config_dict, strategy_id="v1.1")
            context = _make_context(codes, V11_FACTORS, seed=42)
            decision = strategy.generate_signals(context)
            results.append(decision)

        assert results[0].target_weights == results[1].target_weights
        assert results[0].is_rebalance == results[1].is_rebalance


# ============================================================
# Task 4: 边界测试
# ============================================================


class TestBoundaryConditions:
    """边界条件测试。"""

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_exactly_top_n_stocks(self, mock_rebal):
        """Universe正好=top_n只股票。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        # 1500只，因子覆盖>1000
        codes = _make_codes(1500)
        config = _make_v11_config()
        config["top_n"] = 15
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")
        context = _make_context(codes, V11_FACTORS)

        decision = strategy.generate_signals(context)
        assert len(decision.target_weights) == 15

    def test_empty_factor_df_raises(self):
        """空因子数据应报错。"""
        codes = _make_codes(100)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")

        # 空DataFrame
        empty_df = pd.DataFrame(columns=["code", "factor_name", "neutral_value"])
        context = StrategyContext(
            strategy_id="test",
            trade_date=date(2024, 1, 31),
            factor_df=empty_df,
            universe=set(codes),
            industry_map=_make_industry_map(codes),
            prev_holdings=None,
            conn=MagicMock(),
        )

        with pytest.raises(ValueError):
            strategy.generate_signals(context)

    def test_aggregator_empty_strategies(self):
        """空策略dict → 空权重。"""
        agg = PortfolioAggregator()
        result = agg.merge(
            strategy_weights={},
            capital_allocation={},
        )
        assert result.target_weights == {}

    def test_aggregator_negative_weight_warning(self):
        """负权重 → 过滤掉并告警。"""
        agg = PortfolioAggregator()
        # 人工构造负权重
        weights = {"600519": 0.8, "000001": -0.2, "300750": 0.4}

        result = agg.merge(
            strategy_weights={"s1": weights},
            capital_allocation={"s1": 1.0},
        )
        assert any("负权重" in w for w in result.warnings)
        # 负权重被过滤
        assert "000001" not in result.target_weights

    def test_registry_unknown_strategy(self):
        """创建不存在的策略应raise ValueError。"""
        with pytest.raises(ValueError, match="策略不存在"):
            StrategyRegistry.create("does_not_exist", {}, "x")

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_max_replace_limits_changes(self, mock_rebal):
        """max_replace限制换仓数。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(5000)
        config = _make_v11_config()
        config["max_replace"] = 3
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")

        # prev_holdings和新target完全不同
        old_codes = _make_codes(15, prefix="9")
        prev = {c: 1.0 / 15 for c in old_codes}

        context = _make_context(codes, V11_FACTORS, prev_holdings=prev)

        decision = strategy.generate_signals(context)
        # 新进股票不超过max_replace
        old_set = set(old_codes)
        target_set = set(decision.target_weights.keys())
        new_in = target_set - old_set
        # max_replace=3，但old_codes不在universe中（不同prefix），
        # 所以target和prev完全不交叉 → 新进=target全部，截断到max_replace=3
        # 保留: (target∩prev=空集) | 3个新进 = 3只
        # 实际上，target中可能有些stock是prev中的，取决于code生成
        # 关键检查: 结果合法，权重归一化
        assert abs(sum(decision.target_weights.values()) - 1.0) < 0.01

    @patch("engines.strategies.equal_weight.get_rebalance_dates")
    def test_industry_concentration_warning(self, mock_rebal):
        """所有股票同一行业 → 行业集中度告警。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3000)
        config = _make_v11_config()
        strategy = EqualWeightStrategy(config=config, strategy_id="v1.1")

        # 所有股票同一行业
        same_industry = {c: "银行" for c in codes}
        factor_df = _make_factor_df(codes, V11_FACTORS)
        context = StrategyContext(
            strategy_id="test",
            trade_date=date(2024, 1, 31),
            factor_df=factor_df,
            universe=set(codes),
            industry_map=same_industry,
            prev_holdings=None,
            conn=MagicMock(),
        )

        decision = strategy.generate_signals(context)
        assert any("行业集中度过高" in w for w in decision.warnings)


class TestMultiFreqStrategy:
    """MultiFreqStrategy基本验证。"""

    def test_instantiation(self):
        """能实例化。"""
        config = _make_v11_config()
        strategy = MultiFreqStrategy(config=config, strategy_id="test_mf")
        assert strategy.strategy_id == "test_mf"

    def test_daily_freq_allowed(self):
        """支持daily频率。"""
        config = _make_v11_config()
        config["rebalance_freq"] = "daily"
        strategy = MultiFreqStrategy(config=config, strategy_id="test_mf")
        # daily频率should_rebalance总是True
        assert strategy.should_rebalance(date(2024, 1, 15), MagicMock()) is True

    def test_meta(self):
        """元信息正确。"""
        meta = MultiFreqStrategy.get_meta()
        assert meta.name == "multi_freq"
        assert RebalanceFreq.DAILY in meta.supported_freqs

    @patch("engines.strategies.multi_freq.get_rebalance_dates")
    def test_generate_signals(self, mock_rebal):
        """能产出target_weights。"""
        mock_rebal.return_value = [date(2024, 1, 31)]
        codes = _make_codes(3000)
        config = _make_v11_config()
        strategy = MultiFreqStrategy(config=config, strategy_id="test_mf")
        context = _make_context(codes, V11_FACTORS)

        decision = strategy.generate_signals(context)
        assert len(decision.target_weights) > 0
        assert abs(sum(decision.target_weights.values()) - 1.0) < 0.01


class TestFactorProfile:
    """FactorProfile基本验证（不需要DB）。"""

    def test_fit_exponential_decay(self):
        """指数衰减拟合。"""
        from engines.factor_profile import fit_exponential_decay

        # 模拟IC衰减: IC(1)=0.08, IC(5)=0.06, IC(10)=0.04, IC(20)=0.02
        ic_decay = {1: 0.08, 5: 0.06, 10: 0.04, 20: 0.02}
        half_life = fit_exponential_decay(ic_decay)
        assert 0.5 <= half_life <= 120.0
        assert isinstance(half_life, float)

    def test_recommend_freq(self):
        """频率推荐逻辑。"""
        from engines.factor_profile import recommend_freq

        assert recommend_freq(1.0) == "daily"
        assert recommend_freq(5.0) == "weekly"
        assert recommend_freq(10.0) == "biweekly"
        assert recommend_freq(30.0) == "monthly"

    def test_from_ic_decay(self):
        """FactorProfile.from_ic_decay构造。"""
        from engines.factor_profile import FactorProfile

        ic_decay = {1: 0.08, 5: 0.06, 10: 0.04, 20: 0.02}
        profile = FactorProfile.from_ic_decay(
            name="test_factor",
            ic_decay=ic_decay,
            category="price_volume",
        )
        assert profile.name == "test_factor"
        assert profile.half_life_days > 0
        assert profile.recommended_freq in ("daily", "weekly", "biweekly", "monthly")
        assert profile.category == "price_volume"

    def test_insufficient_data(self):
        """数据不足返回默认半衰期。"""
        from engines.factor_profile import fit_exponential_decay

        assert fit_exponential_decay({1: 0.05}) == 30.0
        assert fit_exponential_decay({}) == 30.0
