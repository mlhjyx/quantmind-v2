"""FactorClassifier 单元测试。

验证清单:
- v1.1的5个Active因子分类结果与R1预期一致
- classify_factor()返回完整FactorClassification
- 支持ic_decay数据驱动分类（不是硬编码）
- 边界情况: 空ic_decay、极端值、混合型
- classify_batch批量分类
- register_type扩展注册
- classify_from_profile接口
"""

import pytest
from engines.factor_classifier import (
    FactorClassification,
    FactorClassifier,
    FactorSignalType,
    SelectionMethod,
    TriggerMode,
    WeightingScheme,
    classify_v11_factors,
)
from engines.factor_profile import FactorProfile

# ============================================================
# v1.1 Active因子IC衰减数据（来自R1 §1.2表格）
# ============================================================

V11_IC_DECAY = {
    "turnover_mean_20": {1: 0.064, 5: 0.058, 10: 0.051, 20: 0.042},
    "volatility_20": {1: 0.069, 5: 0.063, 10: 0.056, 20: 0.045},
    "reversal_20": {1: 0.052, 5: 0.041, 10: 0.032, 20: 0.021},
    "amihud_20": {1: 0.022, 5: 0.020, 10: 0.019, 20: 0.017},
    "bp_ratio": {1: 0.052, 5: 0.051, 10: 0.050, 20: 0.048},
}


class TestFactorClassifierV11:
    """v1.1五因子分类验证——R1 §6.4 A组预期结果。"""

    @pytest.fixture
    def classifier(self) -> FactorClassifier:
        return FactorClassifier()

    def test_turnover_mean_20_is_ranking(self, classifier: FactorClassifier) -> None:
        """turnover_mean_20: 排序型, 月度, 半衰期~25天。"""
        result = classifier.classify_factor(
            factor_name="turnover_mean_20",
            ic_decay=V11_IC_DECAY["turnover_mean_20"],
            signal_sparsity=0.85,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        assert result.signal_type == FactorSignalType.RANKING
        assert result.recommended_frequency == "monthly"
        assert result.recommended_selection == SelectionMethod.TOP_N
        assert result.recommended_weighting == WeightingScheme.EQUAL
        assert result.confidence >= 0.7
        assert result.feature_vector["half_life_days"] > 15

    def test_volatility_20_is_ranking(self, classifier: FactorClassifier) -> None:
        """volatility_20: 排序型, 月度, 半衰期~28天。"""
        result = classifier.classify_factor(
            factor_name="volatility_20",
            ic_decay=V11_IC_DECAY["volatility_20"],
            signal_sparsity=0.85,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        assert result.signal_type == FactorSignalType.RANKING
        assert result.recommended_frequency == "monthly"
        assert result.confidence >= 0.7

    def test_reversal_20_is_fast_ranking(self, classifier: FactorClassifier) -> None:
        """reversal_20: 快排序型, 周度/双周, 半衰期~10天。

        R1核心发现: reversal_20月度调仓是错配, 半衰期~10天应用更高频调仓。
        """
        result = classifier.classify_factor(
            factor_name="reversal_20",
            ic_decay=V11_IC_DECAY["reversal_20"],
            signal_sparsity=0.85,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        assert result.signal_type == FactorSignalType.FAST_RANKING
        assert result.recommended_frequency in ("weekly", "biweekly")
        assert result.recommended_selection == SelectionMethod.TOP_N
        assert result.feature_vector["half_life_days"] < 15
        assert result.confidence >= 0.5  # 边界区域(14.7天接近15天阈值)置信度可能降低
        # 推荐配置应包含更高换手上限
        assert result.recommended_config.get("turnover_cap", 0) >= 0.70

    def test_amihud_20_is_ranking(self, classifier: FactorClassifier) -> None:
        """amihud_20: 排序型, 月度, 半衰期~30天。慢衰减流动性因子。"""
        result = classifier.classify_factor(
            factor_name="amihud_20",
            ic_decay=V11_IC_DECAY["amihud_20"],
            signal_sparsity=0.85,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        assert result.signal_type == FactorSignalType.RANKING
        assert result.recommended_frequency == "monthly"
        assert result.confidence >= 0.7

    def test_bp_ratio_is_ranking(self, classifier: FactorClassifier) -> None:
        """bp_ratio: 排序型, 月度(季度更优), 半衰期~60天。极慢衰减价值因子。"""
        result = classifier.classify_factor(
            factor_name="bp_ratio",
            ic_decay=V11_IC_DECAY["bp_ratio"],
            signal_sparsity=0.85,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        assert result.signal_type == FactorSignalType.RANKING
        assert result.recommended_frequency == "monthly"
        assert result.confidence >= 0.7
        # bp_ratio半衰期极长，衰减率应接近1
        assert result.feature_vector["signal_persistence"] > 0.9


class TestFactorClassifierDecisionTree:
    """决策树逻辑验证——覆盖R1 §6.3所有分支。"""

    @pytest.fixture
    def classifier(self) -> FactorClassifier:
        return FactorClassifier()

    def test_event_trigger_classifies_as_event(self, classifier: FactorClassifier) -> None:
        """事件触发因子 → 事件型（RSRS/PEAD场景）。"""
        result = classifier.classify_factor(
            factor_name="rsrs_raw_18",
            ic_decay={1: 0.04, 5: 0.03, 10: 0.02, 20: 0.01},
            signal_sparsity=0.10,
            trigger_mode=TriggerMode.EVENT,
        )
        assert result.signal_type == FactorSignalType.EVENT
        assert result.confidence >= 0.85
        assert result.recommended_selection == SelectionMethod.EVENT_TRIGGER
        assert result.recommended_config.get("signal_threshold") is not None

    def test_condition_trigger_long_halflife_is_modifier(self, classifier: FactorClassifier) -> None:
        """条件触发+长半衰期 → 调节型（regime场景）。"""
        result = classifier.classify_factor(
            factor_name="regime_hmm",
            ic_decay={1: 0.01, 5: 0.01, 10: 0.01, 20: 0.01},
            signal_sparsity=0.50,
            trigger_mode=TriggerMode.CONDITION,
        )
        assert result.signal_type == FactorSignalType.MODIFIER
        assert result.confidence >= 0.80
        assert result.recommended_weighting == WeightingScheme.RISK_PARITY

    def test_low_sparsity_condition_is_event(self, classifier: FactorClassifier) -> None:
        """低稀疏度+条件触发 → 事件型。"""
        result = classifier.classify_factor(
            factor_name="pead_surprise",
            ic_decay={1: 0.05, 5: 0.04, 10: 0.03, 20: 0.02},
            signal_sparsity=0.10,
            trigger_mode=TriggerMode.CONDITION,
        )
        assert result.signal_type == FactorSignalType.EVENT
        assert result.confidence >= 0.70

    def test_medium_sparsity_is_hybrid(self, classifier: FactorClassifier) -> None:
        """中间稀疏度(20%-50%) → 混合型（mf_divergence场景）。"""
        result = classifier.classify_factor(
            factor_name="mf_divergence",
            ic_decay={1: 0.091, 5: 0.070, 10: 0.050, 20: 0.030},
            signal_sparsity=0.35,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        assert result.signal_type == FactorSignalType.HYBRID
        assert result.confidence < 0.70  # 混合型置信度应较低

    def test_halflife_boundary_reduces_confidence(self, classifier: FactorClassifier) -> None:
        """半衰期在12-18天边界区域应降低置信度。"""
        # 构造一个半衰期恰好在13-14天的因子(快衰减但接近边界)
        result = classifier.classify_factor(
            factor_name="boundary_factor",
            ic_decay={1: 0.060, 5: 0.047, 10: 0.036, 20: 0.021},
            signal_sparsity=0.85,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        # 应被分类但置信度因边界区域而降低
        assert result.signal_type in (FactorSignalType.RANKING, FactorSignalType.FAST_RANKING)
        assert result.confidence < 0.85  # 边界降低置信度


class TestFactorClassificationOutput:
    """验证FactorClassification输出完整性。"""

    @pytest.fixture
    def classifier(self) -> FactorClassifier:
        return FactorClassifier()

    def test_classification_has_all_fields(self, classifier: FactorClassifier) -> None:
        """classify_factor()返回完整FactorClassification。"""
        result = classifier.classify_factor(
            factor_name="test_factor",
            ic_decay={1: 0.05, 5: 0.04, 10: 0.03, 20: 0.02},
            signal_sparsity=0.80,
        )
        assert isinstance(result, FactorClassification)
        assert result.factor_name == "test_factor"
        assert isinstance(result.signal_type, FactorSignalType)
        assert result.recommended_frequency in ("daily", "weekly", "biweekly", "monthly")
        assert isinstance(result.recommended_selection, SelectionMethod)
        assert isinstance(result.recommended_weighting, WeightingScheme)
        assert isinstance(result.feature_vector, dict)
        assert "half_life_days" in result.feature_vector
        assert "signal_sparsity" in result.feature_vector
        assert "trigger_score" in result.feature_vector
        assert "ic_decay_rate" in result.feature_vector
        assert "signal_persistence" in result.feature_vector
        assert 0 <= result.confidence <= 1
        assert len(result.reasoning) > 0
        assert isinstance(result.recommended_config, dict)

    def test_feature_vector_values(self, classifier: FactorClassifier) -> None:
        """特征向量的值应在合理范围。"""
        result = classifier.classify_factor(
            factor_name="test_factor",
            ic_decay={1: 0.05, 5: 0.04, 10: 0.03, 20: 0.02},
            signal_sparsity=0.80,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        fv = result.feature_vector
        assert fv["half_life_days"] > 0
        assert 0 <= fv["signal_sparsity"] <= 1
        assert fv["trigger_score"] == 0.0  # CONTINUOUS
        assert 0 < fv["ic_decay_rate"] <= 1  # IC衰减
        assert 0 < fv["signal_persistence"] <= 1


class TestClassifyFromProfile:
    """从FactorProfile分类接口验证。"""

    def test_classify_from_profile_matches_direct(self) -> None:
        """classify_from_profile与直接classify_factor结果一致。"""
        classifier = FactorClassifier()
        ic_decay = {1: 0.064, 5: 0.058, 10: 0.051, 20: 0.042}

        profile = FactorProfile.from_ic_decay("turnover_mean_20", ic_decay)
        result_profile = classifier.classify_from_profile(
            profile, signal_sparsity=0.85, trigger_mode=TriggerMode.CONTINUOUS,
        )
        result_direct = classifier.classify_factor(
            factor_name="turnover_mean_20",
            ic_decay=ic_decay,
            signal_sparsity=0.85,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        assert result_profile.signal_type == result_direct.signal_type
        assert result_profile.recommended_frequency == result_direct.recommended_frequency
        assert result_profile.confidence == result_direct.confidence


class TestClassifyBatch:
    """批量分类验证。"""

    def test_batch_classifies_all(self) -> None:
        """classify_batch正确处理多个因子。"""
        classifier = FactorClassifier()
        factors = [
            {"factor_name": "f1", "ic_decay": {1: 0.05, 5: 0.04, 10: 0.03, 20: 0.02}},
            {"factor_name": "f2", "ic_decay": {1: 0.03, 5: 0.03, 10: 0.03, 20: 0.03}},
        ]
        results = classifier.classify_batch(factors)
        assert len(results) == 2
        assert results[0].factor_name == "f1"
        assert results[1].factor_name == "f2"


class TestClassifyV11Convenience:
    """classify_v11_factors便捷函数验证。"""

    def test_v11_returns_5_results(self) -> None:
        """classify_v11_factors返回5个分类结果。"""
        results = classify_v11_factors()
        assert len(results) == 5
        names = [r.factor_name for r in results]
        assert "turnover_mean_20" in names
        assert "volatility_20" in names
        assert "reversal_20" in names
        assert "amihud_20" in names
        assert "bp_ratio" in names

    def test_v11_correct_types(self) -> None:
        """v1.1因子分类类型符合R1预期。"""
        results = classify_v11_factors()
        type_map = {r.factor_name: r.signal_type for r in results}

        # R1 §6.4 A组预期
        assert type_map["turnover_mean_20"] == FactorSignalType.RANKING
        assert type_map["volatility_20"] == FactorSignalType.RANKING
        assert type_map["reversal_20"] == FactorSignalType.FAST_RANKING
        assert type_map["amihud_20"] == FactorSignalType.RANKING
        assert type_map["bp_ratio"] == FactorSignalType.RANKING

    def test_v11_reversal_not_monthly(self) -> None:
        """reversal_20不应推荐月度调仓（R1核心发现）。"""
        results = classify_v11_factors()
        reversal = next(r for r in results if r.factor_name == "reversal_20")
        assert reversal.recommended_frequency != "monthly"


class TestRegisterType:
    """类型注册扩展验证。"""

    def test_register_new_type(self) -> None:
        """注册新因子类型后可被使用。"""
        classifier = FactorClassifier()
        classifier.register_type(
            type_name="ultra_fast",
            half_life_range=(0.1, 3.0),
            sparsity_range=(0.5, 1.0),
            trigger=TriggerMode.CONTINUOUS,
            strategy_name="UltraFastStrategy",
        )
        assert "ultra_fast" in classifier._type_registry
        assert classifier._strategy_map["ultra_fast"] == "UltraFastStrategy"


class TestEdgeCases:
    """边界和异常情况。"""

    @pytest.fixture
    def classifier(self) -> FactorClassifier:
        return FactorClassifier()

    def test_minimal_ic_decay(self, classifier: FactorClassifier) -> None:
        """最少2个点的ic_decay也能分类。"""
        result = classifier.classify_factor(
            factor_name="sparse_ic",
            ic_decay={1: 0.05, 20: 0.03},
            signal_sparsity=0.80,
        )
        assert isinstance(result.signal_type, FactorSignalType)
        assert result.feature_vector["half_life_days"] > 0

    def test_single_point_ic_decay_defaults(self, classifier: FactorClassifier) -> None:
        """只有1个点的ic_decay使用默认半衰期30天。"""
        result = classifier.classify_factor(
            factor_name="one_point",
            ic_decay={1: 0.05},
            signal_sparsity=0.80,
        )
        # 默认半衰期30天 → 排序型
        assert result.signal_type == FactorSignalType.RANKING

    def test_empty_ic_decay(self, classifier: FactorClassifier) -> None:
        """空ic_decay使用默认半衰期。"""
        result = classifier.classify_factor(
            factor_name="empty",
            ic_decay={},
            signal_sparsity=0.80,
        )
        assert isinstance(result.signal_type, FactorSignalType)

    def test_no_decay_factor(self, classifier: FactorClassifier) -> None:
        """IC不衰减的因子(值不变) → 排序型+长半衰期。"""
        result = classifier.classify_factor(
            factor_name="constant_ic",
            ic_decay={1: 0.05, 5: 0.05, 10: 0.05, 20: 0.05},
            signal_sparsity=0.80,
        )
        assert result.signal_type == FactorSignalType.RANKING
        assert result.feature_vector["half_life_days"] >= 60

    def test_extreme_fast_decay(self, classifier: FactorClassifier) -> None:
        """极快衰减因子 → 快排序型(daily/weekly)。"""
        result = classifier.classify_factor(
            factor_name="ultra_fast",
            ic_decay={1: 0.10, 5: 0.03, 10: 0.01, 20: 0.001},
            signal_sparsity=0.80,
        )
        assert result.signal_type == FactorSignalType.FAST_RANKING
        assert result.recommended_frequency in ("daily", "weekly")
