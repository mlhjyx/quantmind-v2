"""CompositeStrategy + ModifierBase 单元测试。

验证清单:
- CompositeStrategy(core + RegimeModifier)编排逻辑
- ModifierBase.apply_adjustments的clip+归一化+max_daily_adjustment限制
- Modifier链顺序应用（多个Modifier串联）
- 空Modifier链 = 透传核心策略结果
- RegimeModifier三级fallback: HMM失败→VolRegime→常数1.0
- cash_buffer=3%归一化正确性
- CompositeDecision输出完整性
"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base_strategy import (
    SignalType,
    StrategyContext,
    StrategyDecision,
)
from engines.modifiers.base import ModifierBase, ModifierResult
from engines.strategies.composite import CompositeDecision, CompositeStrategy

# ============================================================
# 测试工具
# ============================================================


def _make_base_weights(n: int = 5) -> dict[str, float]:
    """生成等权持仓。"""
    codes = [f"60{i:04d}.SH" for i in range(n)]
    w = 1.0 / n
    return {c: w for c in codes}


def _make_context() -> StrategyContext:
    """构建最小化StrategyContext（不含DB）。"""
    return StrategyContext(
        strategy_id="test_composite",
        trade_date=date(2024, 1, 31),
        factor_df=pd.DataFrame(columns=["code", "factor_name", "neutral_value"]),
        universe=set(),
        industry_map={},
        prev_holdings=None,
        conn=None,
        total_capital=1_000_000.0,
    )


class _AlwaysTriggeredModifier(ModifierBase):
    """每次都触发的测试Modifier，将所有持仓系数设为fixed_factor。"""

    def __init__(self, name: str, fixed_factor: float = 0.8) -> None:
        super().__init__(name=name, config={})
        self.fixed_factor = fixed_factor

    def should_trigger(self, context: StrategyContext) -> bool:
        return True

    def compute_adjustments(
        self, base_weights: dict[str, float], context: StrategyContext
    ) -> ModifierResult:
        factors = {code: self.fixed_factor for code in base_weights}
        return ModifierResult(
            adjustment_factors=factors,
            triggered=True,
            reasoning=f"测试Modifier: factor={self.fixed_factor}",
        )


class _NeverTriggeredModifier(ModifierBase):
    """从不触发的测试Modifier。"""

    def __init__(self, name: str) -> None:
        super().__init__(name=name, config={})

    def should_trigger(self, context: StrategyContext) -> bool:
        return False

    def compute_adjustments(
        self, base_weights: dict[str, float], context: StrategyContext
    ) -> ModifierResult:
        return ModifierResult(
            adjustment_factors={},
            triggered=False,
            reasoning="未触发",
        )


class _RaisingModifier(ModifierBase):
    """compute_adjustments抛出异常的Modifier（测试异常容错）。"""

    def __init__(self) -> None:
        super().__init__(name="raising_modifier", config={})

    def should_trigger(self, context: StrategyContext) -> bool:
        return True

    def compute_adjustments(
        self, base_weights: dict[str, float], context: StrategyContext
    ) -> ModifierResult:
        raise RuntimeError("模拟Modifier内部崩溃")


def _make_mock_core(
    target_weights: dict[str, float] | None = None,
    is_rebalance: bool = True,
    warnings: list[str] | None = None,
) -> MagicMock:
    """构建返回指定结果的mock核心策略。"""
    core = MagicMock()
    core.strategy_id = "mock_core"
    # 用sentinel区分"未传入"和"传入空dict"
    weights = _make_base_weights() if target_weights is None else target_weights
    core.generate_signals.return_value = StrategyDecision(
        target_weights=weights,
        is_rebalance=is_rebalance,
        reasoning="mock core",
        warnings=warnings or [],
        signal_type=SignalType.RANKING,
    )
    return core


# ============================================================
# 1. 空Modifier链透传测试
# ============================================================


class TestCompositeStrategyNoModifiers:
    """空Modifier链 = 透传核心策略结果，只做cash_buffer归一化。"""

    def test_empty_modifiers_passthrough_weights(self) -> None:
        """无Modifier时，final_weights是core_weights归一化到1-cash_buffer。"""
        raw_weights = {"600519.SH": 0.5, "000001.SH": 0.5}
        core = _make_mock_core(target_weights=raw_weights)
        composite = CompositeStrategy(core=core, modifiers=[], cash_buffer=0.03)
        decision = composite.generate(_make_context())

        # 总权重 = 1.0 - 0.03 = 0.97
        total = sum(decision.final_weights.values())
        assert abs(total - 0.97) < 1e-9

    def test_empty_modifiers_correct_stock_count(self) -> None:
        """无Modifier时，final_weights持仓只数不变。"""
        raw_weights = _make_base_weights(10)
        core = _make_mock_core(target_weights=raw_weights)
        composite = CompositeStrategy(core=core, modifiers=[])
        decision = composite.generate(_make_context())
        assert len(decision.final_weights) == 10

    def test_empty_modifier_log(self) -> None:
        """无Modifier时modifier_log为空列表。"""
        core = _make_mock_core()
        composite = CompositeStrategy(core=core, modifiers=[])
        decision = composite.generate(_make_context())
        assert decision.modifier_log == []

    def test_core_weights_preserved(self) -> None:
        """core_weights存储核心策略原始输出（未归一化）。"""
        raw_weights = {"600519.SH": 0.3, "000001.SH": 0.3}
        core = _make_mock_core(target_weights=raw_weights)
        composite = CompositeStrategy(core=core, modifiers=[])
        decision = composite.generate(_make_context())
        # core_weights是原始的
        assert decision.core_weights == raw_weights

    def test_is_rebalance_propagated(self) -> None:
        """is_rebalance标志从核心策略透传。"""
        core = _make_mock_core(is_rebalance=False)
        composite = CompositeStrategy(core=core, modifiers=[])
        decision = composite.generate(_make_context())
        assert decision.is_rebalance is False


# ============================================================
# 2. 单Modifier应用测试
# ============================================================


class TestCompositeStrategySingleModifier:
    """单Modifier应用逻辑验证。"""

    def test_triggered_modifier_changes_weights(self) -> None:
        """触发的Modifier应改变权重。"""
        raw_weights = _make_base_weights(5)
        core = _make_mock_core(target_weights=raw_weights)
        # factor=0.5使所有权重减半，然后归一化回原总权重
        modifier = _AlwaysTriggeredModifier("m1", fixed_factor=0.5)
        composite = CompositeStrategy(core=core, modifiers=[modifier])
        decision = composite.generate(_make_context())

        # 权重总和仍=1-cash_buffer
        total = sum(decision.final_weights.values())
        assert abs(total - 0.97) < 1e-6

    def test_non_triggered_modifier_skips(self) -> None:
        """未触发的Modifier不应影响权重。"""
        raw_weights = _make_base_weights(5)
        core = _make_mock_core(target_weights=raw_weights)
        modifier = _NeverTriggeredModifier("m_skip")
        composite = CompositeStrategy(core=core, modifiers=[modifier])
        decision = composite.generate(_make_context())

        # 权重应与空Modifier链一致
        core2 = _make_mock_core(target_weights=raw_weights)
        composite2 = CompositeStrategy(core=core2, modifiers=[])
        decision2 = composite2.generate(_make_context())

        assert decision.final_weights == pytest.approx(decision2.final_weights, abs=1e-9)

    def test_modifier_log_records_triggered(self) -> None:
        """modifier_log记录触发状态。"""
        core = _make_mock_core()
        modifier = _AlwaysTriggeredModifier("m_log")
        composite = CompositeStrategy(core=core, modifiers=[modifier])
        decision = composite.generate(_make_context())

        assert len(decision.modifier_log) == 1
        log = decision.modifier_log[0]
        assert log["modifier"] == "m_log"
        assert log["triggered"] is True
        assert len(log["reasoning"]) > 0

    def test_modifier_log_records_not_triggered(self) -> None:
        """modifier_log记录未触发状态。"""
        core = _make_mock_core()
        modifier = _NeverTriggeredModifier("m_not")
        composite = CompositeStrategy(core=core, modifiers=[modifier])
        decision = composite.generate(_make_context())

        assert len(decision.modifier_log) == 1
        log = decision.modifier_log[0]
        assert log["triggered"] is False

    def test_modifier_exception_graceful_skip(self) -> None:
        """Modifier抛出异常时，应跳过并记录告警，不崩溃。"""
        core = _make_mock_core()
        bad_modifier = _RaisingModifier()
        composite = CompositeStrategy(core=core, modifiers=[bad_modifier])
        decision = composite.generate(_make_context())

        # 不崩溃，告警中含报错信息
        assert any("执行失败" in w or "raising_modifier" in w for w in decision.warnings)
        # 持仓正常输出
        assert len(decision.final_weights) > 0


# ============================================================
# 3. 多Modifier链顺序测试
# ============================================================


class TestCompositeStrategyMultipleModifiers:
    """多Modifier串联应用验证。"""

    def test_two_modifiers_both_applied(self) -> None:
        """两个触发的Modifier均被应用，modifier_log有2条记录。"""
        core = _make_mock_core()
        m1 = _AlwaysTriggeredModifier("m1", fixed_factor=0.8)
        m2 = _AlwaysTriggeredModifier("m2", fixed_factor=0.9)
        composite = CompositeStrategy(core=core, modifiers=[m1, m2])
        decision = composite.generate(_make_context())

        assert len(decision.modifier_log) == 2
        assert decision.modifier_log[0]["modifier"] == "m1"
        assert decision.modifier_log[1]["modifier"] == "m2"

    def test_modifier_order_matters(self) -> None:
        """Modifier顺序影响结果：m1应用后权重变化，m2在新权重基础上应用。

        注意：若两个Modifier factor相同，顺序不影响最终权重总和，
        但若factor不同，应用顺序会影响中间状态。
        """
        # 两个不同factor的Modifier
        m1 = _AlwaysTriggeredModifier("reduce_m1", fixed_factor=0.5)
        m2 = _AlwaysTriggeredModifier("expand_m2", fixed_factor=1.2)

        composite_12 = CompositeStrategy(core=MagicMock(), modifiers=[m1, m2])
        composite_12.core = _make_mock_core()

        composite_21 = CompositeStrategy(core=MagicMock(), modifiers=[m2, m1])
        composite_21.core = _make_mock_core()

        d12 = composite_12.generate(_make_context())
        d21 = composite_21.generate(_make_context())

        # 总权重在两种顺序下都应等于1-cash_buffer
        assert abs(sum(d12.final_weights.values()) - 0.97) < 1e-6
        assert abs(sum(d21.final_weights.values()) - 0.97) < 1e-6

    def test_one_triggered_one_not(self) -> None:
        """一个触发一个不触发，只有触发的生效。"""
        raw_weights = _make_base_weights(5)
        core = _make_mock_core(target_weights=raw_weights)
        m_active = _AlwaysTriggeredModifier("active", fixed_factor=0.5)
        m_skip = _NeverTriggeredModifier("skip")
        composite = CompositeStrategy(core=core, modifiers=[m_active, m_skip])
        decision = composite.generate(_make_context())

        assert len(decision.modifier_log) == 2
        assert decision.modifier_log[0]["triggered"] is True
        assert decision.modifier_log[1]["triggered"] is False

    def test_dynamic_add_modifier(self) -> None:
        """add_modifier动态添加后生效。"""
        core = _make_mock_core()
        composite = CompositeStrategy(core=core, modifiers=[])
        assert composite.modifier_names == []

        new_mod = _AlwaysTriggeredModifier("new_mod")
        composite.add_modifier(new_mod)
        assert "new_mod" in composite.modifier_names

        # 重新生成，新Modifier应被应用
        composite.core = _make_mock_core()
        decision = composite.generate(_make_context())
        assert len(decision.modifier_log) == 1

    def test_remove_modifier(self) -> None:
        """remove_modifier按名称移除Modifier。"""
        core = _make_mock_core()
        m1 = _AlwaysTriggeredModifier("keep_me")
        m2 = _AlwaysTriggeredModifier("remove_me")
        composite = CompositeStrategy(core=core, modifiers=[m1, m2])

        removed = composite.remove_modifier("remove_me")
        assert removed is True
        assert "remove_me" not in composite.modifier_names
        assert "keep_me" in composite.modifier_names

    def test_remove_nonexistent_modifier_returns_false(self) -> None:
        """移除不存在的Modifier返回False。"""
        core = _make_mock_core()
        composite = CompositeStrategy(core=core, modifiers=[])
        assert composite.remove_modifier("ghost") is False


# ============================================================
# 4. cash_buffer归一化测试
# ============================================================


class TestCashBuffer:
    """cash_buffer=3%归一化正确性验证。"""

    def test_cash_buffer_3_percent(self) -> None:
        """默认cash_buffer=3%，总权重=0.97。"""
        core = _make_mock_core(target_weights={"A": 0.5, "B": 0.5})
        composite = CompositeStrategy(core=core, cash_buffer=0.03)
        decision = composite.generate(_make_context())
        assert abs(sum(decision.final_weights.values()) - 0.97) < 1e-9

    def test_custom_cash_buffer_0_percent(self) -> None:
        """cash_buffer=0时总权重=1.0。"""
        core = _make_mock_core(target_weights={"A": 0.5, "B": 0.5})
        composite = CompositeStrategy(core=core, cash_buffer=0.0)
        decision = composite.generate(_make_context())
        assert abs(sum(decision.final_weights.values()) - 1.0) < 1e-9

    def test_custom_cash_buffer_5_percent(self) -> None:
        """cash_buffer=5%时总权重=0.95。"""
        core = _make_mock_core(target_weights={"A": 1.0 / 3, "B": 1.0 / 3, "C": 1.0 / 3})
        composite = CompositeStrategy(core=core, cash_buffer=0.05)
        decision = composite.generate(_make_context())
        assert abs(sum(decision.final_weights.values()) - 0.95) < 1e-9

    def test_empty_weights_from_core_returns_empty(self) -> None:
        """核心策略返回空权重时，final_weights也为空。"""
        core = _make_mock_core(target_weights={})
        composite = CompositeStrategy(core=core, cash_buffer=0.03)
        decision = composite.generate(_make_context())
        assert decision.final_weights == {}


# ============================================================
# 5. ModifierBase.apply_adjustments测试
# ============================================================


class TestModifierApplyAdjustments:
    """ModifierBase.apply_adjustments: clip+归一化+max_daily_adjustment。"""

    def _make_modifier(self, clip_low: float = 0.5, clip_high: float = 1.5) -> ModifierBase:
        return _AlwaysTriggeredModifier("test_mod")

    def test_factor_1_no_change(self) -> None:
        """adjustment_factor=1.0不改变权重。"""
        modifier = _AlwaysTriggeredModifier("neutral", fixed_factor=1.0)
        base = {"A": 0.3, "B": 0.7}
        result = ModifierResult(
            adjustment_factors={"A": 1.0, "B": 1.0},
            triggered=True,
            reasoning="无调节",
        )
        adjusted = modifier.apply_adjustments(base, result)
        assert adjusted == pytest.approx(base, abs=1e-9)

    def test_factor_clipped_below(self) -> None:
        """adjustment_factor < clip_low被截断到clip_low。"""
        modifier = _AlwaysTriggeredModifier("clipper", fixed_factor=0.1)
        modifier.clip_low = 0.5
        base = {"A": 0.5, "B": 0.5}
        result = ModifierResult(
            adjustment_factors={"A": 0.01, "B": 0.01},  # 极小值，应截断到0.5
            triggered=True,
            reasoning="低因子",
        )
        adjusted = modifier.apply_adjustments(base, result)
        # 截断后 factor=0.5，权重×0.5，总权重减半→归一化回原总权重
        assert abs(sum(adjusted.values()) - sum(base.values())) < 1e-9

    def test_factor_clipped_above(self) -> None:
        """adjustment_factor > clip_high被截断到clip_high。"""
        modifier = _AlwaysTriggeredModifier("capper", fixed_factor=5.0)
        modifier.clip_high = 1.5
        base = {"A": 0.5, "B": 0.5}
        result = ModifierResult(
            adjustment_factors={"A": 99.0, "B": 99.0},  # 极大值，应截断到1.5
            triggered=True,
            reasoning="高因子",
        )
        adjusted = modifier.apply_adjustments(base, result)
        # 截断后 factor=1.5，权重×1.5，然后归一化回原总权重
        assert abs(sum(adjusted.values()) - sum(base.values())) < 1e-9

    def test_not_triggered_returns_base_unchanged(self) -> None:
        """triggered=False时直接返回base_weights不做任何处理。"""
        modifier = _AlwaysTriggeredModifier("skip_mod")
        base = {"A": 0.4, "B": 0.6}
        result = ModifierResult(
            adjustment_factors={"A": 0.1},
            triggered=False,
            reasoning="未触发",
        )
        adjusted = modifier.apply_adjustments(base, result)
        assert adjusted is base  # 返回原对象引用

    def test_max_daily_adjustment_clamps_large_change(self) -> None:
        """调节量超过max_daily_adjustment时，按比例缩减。"""
        modifier = _AlwaysTriggeredModifier("big_mod")
        base = {"A": 0.5, "B": 0.5}
        # factor=0.1使得总调节量=80%（远超20%上限）
        result = ModifierResult(
            adjustment_factors={"A": 0.1, "B": 0.1},
            triggered=True,
            reasoning="大幅调节",
        )
        adjusted = modifier.apply_adjustments(base, result, max_daily_adjustment=0.20)
        # 调节后总权重仍应接近原始总权重（归一化保持）
        assert abs(sum(adjusted.values()) - sum(base.values())) < 1e-6

    def test_weights_normalized_after_adjustment(self) -> None:
        """调节后权重总和应等于原始总权重（归一化）。"""
        modifier = _AlwaysTriggeredModifier("normalizer", fixed_factor=0.7)
        base = {"A": 0.2, "B": 0.3, "C": 0.4}
        result = ModifierResult(
            adjustment_factors={"A": 0.7, "B": 0.7, "C": 0.7},
            triggered=True,
            reasoning="统一降权",
        )
        adjusted = modifier.apply_adjustments(base, result)
        # 归一化回原总权重 (0.9)
        assert abs(sum(adjusted.values()) - sum(base.values())) < 1e-9

    def test_code_not_in_factors_uses_factor_1(self) -> None:
        """factors中没有的code默认factor=1.0，不被调节。"""
        modifier = _AlwaysTriggeredModifier("partial_mod")
        base = {"A": 0.5, "B": 0.5}
        result = ModifierResult(
            adjustment_factors={"A": 0.5},  # 只调节A，B不含
            triggered=True,
            reasoning="部分调节",
        )
        adjusted = modifier.apply_adjustments(base, result)
        # B的权重×1.0不变，A的权重×0.5，然后归一化
        # 验证B相对A权重变大（A被降权）
        assert adjusted["B"] > adjusted["A"]


# ============================================================
# 6. RegimeModifier三级fallback测试
# ============================================================


class TestRegimeModifierFallback:
    """RegimeModifier三级fallback: HMM → VolRegime → 常数1.0。"""

    def _make_regime_modifier(self, **kwargs):
        from engines.modifiers.regime_modifier import RegimeModifier

        config = {"use_hmm": True, "min_hmm_samples": 252}
        config.update(kwargs)
        return RegimeModifier(config=config)

    def test_should_trigger_always_true(self) -> None:
        """RegimeModifier每次都触发。"""
        modifier = self._make_regime_modifier()
        assert modifier.should_trigger(_make_context()) is True

    def test_fallback_to_constant_when_no_db(self) -> None:
        """conn=None时三级全部失败，fallback到常数1.0。"""
        modifier = self._make_regime_modifier()
        base_weights = _make_base_weights(5)
        context = _make_context()  # conn=None

        result = modifier.compute_adjustments(base_weights, context)
        assert result.triggered is True
        # 常数fallback: 所有code的factor=1.0
        for _code, factor in result.adjustment_factors.items():
            assert abs(factor - 1.0) < 1e-9
        # 应有fallback告警
        assert any("fallback" in w.lower() or "失败" in w for w in result.warnings)

    @patch("engines.regime_detector.HMMRegimeDetector")
    def test_hmm_success_risk_on(self, mock_hmm_cls) -> None:
        """HMM成功且状态=risk_on，缩放系数=1.0。"""
        from engines.modifiers.regime_modifier import RegimeModifier

        mock_detector = MagicMock()
        mock_result = MagicMock()
        mock_result.state = "risk_on"
        # PR-C2 (Session 36): production `regime_modifier.py:124` 返
        # `result.scale, result.state, f"hmm({result.source})"`, line 93
        # 用 `f"...{scale:.2f}..."` 格式化. MagicMock 默认 `__format__` 不支持 `.2f`
        # → TypeError. 必须显式赋 float scale + str source.
        mock_result.scale = 1.0
        mock_result.source = "expanding"
        mock_detector.fit_predict.return_value = mock_result
        mock_hmm_cls.return_value = mock_detector

        modifier = RegimeModifier(config={"use_hmm": True, "min_hmm_samples": 5})
        base_weights = {"A": 0.5, "B": 0.5}

        # 构建有DB连接的context，返回足够条收盘价数据
        context = _make_context()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # 生成超过min_hmm_samples(5)条数据
        rows = [(f"2024-01-{i:02d}", 3000.0 + i) for i in range(1, 10)]
        mock_cur.fetchall.return_value = rows
        mock_conn.cursor.return_value = mock_cur
        context.conn = mock_conn

        result = modifier.compute_adjustments(base_weights, context)
        assert result.triggered is True
        # risk_on缩放系数=1.0
        for factor in result.adjustment_factors.values():
            assert abs(factor - 1.0) < 1e-9

    @patch("engines.regime_detector.HMMRegimeDetector")
    def test_hmm_success_risk_off(self, mock_hmm_cls) -> None:
        """HMM成功且状态=risk_off，缩放系数=0.3。"""
        from engines.modifiers.regime_modifier import RegimeModifier

        mock_detector = MagicMock()
        mock_result = MagicMock()
        mock_result.state = "risk_off"
        # PR-C2 (Session 36): 同上 — 显式赋 float scale + str source.
        mock_result.scale = 0.3
        mock_result.source = "expanding"
        mock_detector.fit_predict.return_value = mock_result
        mock_hmm_cls.return_value = mock_detector

        modifier = RegimeModifier(config={"use_hmm": True, "min_hmm_samples": 5})
        base_weights = {"A": 0.5, "B": 0.5}

        context = _make_context()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        rows = [(f"2024-01-{i:02d}", 3000.0 + i) for i in range(1, 10)]
        mock_cur.fetchall.return_value = rows
        mock_conn.cursor.return_value = mock_cur
        context.conn = mock_conn

        result = modifier.compute_adjustments(base_weights, context)
        for factor in result.adjustment_factors.values():
            assert abs(factor - 0.3) < 1e-9

    def test_hmm_failure_falls_to_vol_regime(self) -> None:
        """HMM失败时降级到VolRegime（L2 fallback）。"""
        from engines.modifiers.regime_modifier import RegimeModifier

        modifier = RegimeModifier(config={"use_hmm": True, "min_hmm_samples": 999})
        # min_hmm_samples=999，数据只有9条，HMM因样本不足而跳过（走L2 VolRegime路径）
        base_weights = {"A": 0.5, "B": 0.5}

        context = _make_context()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # 21+条数据足够VolRegime
        rows = [(f"2024-01-{i:02d}", 3000.0 + i) for i in range(1, 30)]
        mock_cur.fetchall.return_value = rows
        mock_conn.cursor.return_value = mock_cur
        context.conn = mock_conn

        result = modifier.compute_adjustments(base_weights, context)
        assert result.triggered is True
        # 通过VolRegime处理，来源应为vol_regime（reasoning中含vol_regime）
        assert "vol_regime" in result.reasoning

    def test_use_hmm_false_skips_to_vol_regime(self) -> None:
        """use_hmm=False时跳过HMM直接用VolRegime。"""
        from engines.modifiers.regime_modifier import RegimeModifier

        modifier = RegimeModifier(config={"use_hmm": False})
        base_weights = {"A": 0.5}
        context = _make_context()  # conn=None → VolRegime也失败 → 常数1.0

        result = modifier.compute_adjustments(base_weights, context)
        assert result.triggered is True
        # 无HMM告警
        assert not any("HMM" in w for w in result.warnings)

    def test_composite_with_regime_modifier_no_db(self) -> None:
        """CompositeStrategy + RegimeModifier，无DB时fallback不崩溃，权重正确。"""
        from engines.modifiers.regime_modifier import RegimeModifier

        regime_mod = RegimeModifier(config={"use_hmm": False})
        core = _make_mock_core(target_weights=_make_base_weights(5))
        composite = CompositeStrategy(core=core, modifiers=[regime_mod], cash_buffer=0.03)
        decision = composite.generate(_make_context())

        assert isinstance(decision, CompositeDecision)
        assert abs(sum(decision.final_weights.values()) - 0.97) < 1e-6
        assert len(decision.modifier_log) == 1


# ============================================================
# 7. CompositeDecision输出完整性
# ============================================================


class TestCompositeDecisionCompleteness:
    """CompositeDecision输出字段完整性。"""

    def test_all_fields_present(self) -> None:
        """CompositeDecision包含所有必要字段。"""
        core = _make_mock_core()
        composite = CompositeStrategy(core=core, modifiers=[])
        decision = composite.generate(_make_context())

        assert isinstance(decision, CompositeDecision)
        assert isinstance(decision.final_weights, dict)
        assert isinstance(decision.core_weights, dict)
        assert isinstance(decision.modifier_log, list)
        assert isinstance(decision.is_rebalance, bool)
        assert isinstance(decision.warnings, list)
        # Phase B: aggregated_portfolio=None
        assert decision.aggregated_portfolio is None

    def test_warnings_aggregated_from_core_and_modifiers(self) -> None:
        """warnings聚合了核心策略和Modifier的告警。"""
        core = _make_mock_core(warnings=["core告警"])
        m1 = _AlwaysTriggeredModifier("m1")
        composite = CompositeStrategy(core=core, modifiers=[m1])
        decision = composite.generate(_make_context())

        assert "core告警" in decision.warnings

    def test_satellites_logged_but_not_used(self, capsys) -> None:
        """设置satellites时产生警告，但当前仅运行core+modifiers。"""
        core = _make_mock_core()
        satellite = MagicMock()
        # structlog输出到stdout/stderr，验证警告消息存在
        CompositeStrategy(core=core, satellites=[satellite])
        captured = capsys.readouterr()
        assert "satellites" in captured.out.lower() or "phase b" in captured.out.lower()
