"""FactorClassifier — 因子分类与策略匹配引擎。

基于R1研究报告的因子-策略匹配框架，将因子按信号特征自动分类，
并推荐匹配的策略类型和参数配置。

核心分类维度（R1 §6.1）:
1. IC衰减半衰期 (half_life_days) — 决定调仓频率
2. 信号稀疏度 (signal_sparsity) — 区分排序型vs事件型
3. 触发模式 (trigger_mode) — continuous/event/condition

初始四类（数据驱动可扩展，非固定枚举）:
- Ranking: 半衰期>15天, 稀疏度>50%, 持续触发 (bp_ratio, turnover, volatility, amihud)
- FastRanking: 半衰期<15天, 稀疏度>50%, 持续触发 (reversal_20)
- Event: 稀疏度<20%, 事件/条件触发 (RSRS, PEAD)
- Modifier: 半衰期>60天, 条件触发 (regime, volatility_target)

设计文档对照:
- R1_factor_strategy_matching.md §6.1-6.3: 分类标准+决策树
- DEV_BACKTEST_ENGINE.md §4.12.4: BaseStrategy接口
- DEV_PARAM_CONFIG.md §3.4: 组合构建6个可配参数
- IMPLEMENTATION_MASTER.md §4.1: FactorClassifier任务规格
"""

import structlog
from dataclasses import dataclass, field
from enum import StrEnum

from engines.factor_profile import FactorProfile, fit_exponential_decay, recommend_freq

logger = structlog.get_logger(__name__)


# ============================================================
# 枚举定义
# ============================================================


class FactorSignalType(StrEnum):
    """因子信号类型（R1 §6.1, 可扩展）。"""

    RANKING = "ranking"            # 排序型: Top-N定期调仓
    FAST_RANKING = "fast_ranking"  # 快排序型: Top-N高频调仓
    EVENT = "event"                # 事件型: 阈值触发+固定持有期
    MODIFIER = "modifier"          # 调节型: 仓位调整/风险预算
    HYBRID = "hybrid"              # 混合型: 排序+事件特征共存
    CONDITIONAL = "conditional"    # 条件型: 只在特定regime下有效
    PAIRED = "paired"              # 配对型: 需多因子联合触发
    ADAPTIVE = "adaptive"          # 自适应型: 参数随市场状态切换
    UNCLASSIFIED = "unclassified"  # 未分类: 需人工审查


class SelectionMethod(StrEnum):
    """选股方式。"""

    TOP_N = "top_n"              # 截面排序Top-N
    THRESHOLD = "threshold"      # 阈值过滤
    EVENT_TRIGGER = "event_trigger"  # 事件触发


class WeightingScheme(StrEnum):
    """权重方案。"""

    EQUAL = "equal"              # 等权 1/N
    IC_WEIGHTED = "ic_weighted"  # IC加权
    SIGNAL_STRENGTH = "signal_strength"  # 信号强度加权
    RISK_PARITY = "risk_parity"  # 风险平价


class TriggerMode(StrEnum):
    """触发模式。"""

    CONTINUOUS = "continuous"  # 每个截面都有信号
    EVENT = "event"            # 外部事件驱动
    CONDITION = "condition"    # 市场状态切换


# ============================================================
# 数据类
# ============================================================


@dataclass
class FactorClassification:
    """因子分类结果，包含连续特征向量和离散类型。

    对应R1 §6.3中的classify_factor()输出规格。
    """

    factor_name: str
    signal_type: FactorSignalType
    recommended_frequency: str   # daily/weekly/biweekly/monthly
    recommended_selection: SelectionMethod
    recommended_weighting: WeightingScheme
    feature_vector: dict[str, float]
    confidence: float            # 0-1, 越低越可能是边界/混合型
    reasoning: str               # 经济学解释
    recommended_config: dict = field(default_factory=dict)


# ============================================================
# 类型注册表（可扩展，新类型通过register_type添加）
# ============================================================

# 每个类型的特征空间范围: (half_life_min, half_life_max, sparsity_min, sparsity_max, trigger)
FACTOR_TYPE_REGISTRY: dict[str, dict] = {
    "ranking": {
        "half_life": (15.0, 120.0),
        "sparsity": (0.50, 1.0),
        "trigger": TriggerMode.CONTINUOUS,
    },
    "fast_ranking": {
        "half_life": (0.5, 15.0),
        "sparsity": (0.50, 1.0),
        "trigger": TriggerMode.CONTINUOUS,
    },
    "event": {
        "half_life": (0.0, 999.0),
        "sparsity": (0.0, 0.20),
        "trigger": TriggerMode.EVENT,
    },
    "modifier": {
        "half_life": (60.0, 999.0),
        "sparsity": (0.0, 1.0),
        "trigger": TriggerMode.CONDITION,
    },
}

# 类型 -> 推荐策略类名
STRATEGY_MAP: dict[str, str] = {
    "ranking": "EqualWeightStrategy",
    "fast_ranking": "FastRankingStrategy",
    "event": "EventDrivenStrategy",
    "modifier": "ModifierPlugin",
    "hybrid": "manual_review",
    "unclassified": "manual_review",
}


# ============================================================
# FactorClassifier 核心类
# ============================================================


class FactorClassifier:
    """因子分类器 — 基于信号特征将因子路由到匹配策略。

    使用方式:
        classifier = FactorClassifier()
        result = classifier.classify_factor(
            factor_name="reversal_20",
            ic_decay={1: 0.052, 5: 0.041, 10: 0.032, 20: 0.021},
            signal_sparsity=0.85,
            trigger_mode=TriggerMode.CONTINUOUS,
        )
        print(result.signal_type)  # FactorSignalType.FAST_RANKING

    也可从FactorProfile直接分类:
        profile = FactorProfile.from_ic_decay("reversal_20", ic_decay)
        result = classifier.classify_from_profile(profile, signal_sparsity=0.85)
    """

    def __init__(
        self,
        type_registry: dict[str, dict] | None = None,
        strategy_map: dict[str, str] | None = None,
    ) -> None:
        self._type_registry = type_registry or FACTOR_TYPE_REGISTRY.copy()
        self._strategy_map = strategy_map or STRATEGY_MAP.copy()

    def classify_factor(
        self,
        factor_name: str,
        ic_decay: dict[int, float],
        signal_sparsity: float = 0.80,
        trigger_mode: TriggerMode = TriggerMode.CONTINUOUS,
        category: str = "",
    ) -> FactorClassification:
        """对单个因子进行分类并推荐策略配置。

        决策树（R1 §6.3）:
        Step 1: 拟合IC衰减半衰期
        Step 2: 评估信号稀疏度
        Step 3: 判断触发模式
        Step 4: 分类决策
        Step 5: 推荐策略参数

        Args:
            factor_name: 因子名称。
            ic_decay: {horizon_days: mean_ic} 映射, e.g. {1: 0.064, 5: 0.058, 10: 0.051, 20: 0.042}。
            signal_sparsity: 有效信号占截面总数的比例(0-1)。
                >0.50: 连续排序型(大部分股票有有效排序信号)。
                <0.20: 稀疏触发/事件型。
            trigger_mode: 触发模式。
            category: 因子类别(辅助信息，不影响分类)。

        Returns:
            FactorClassification: 含类型、特征向量、置信度、推荐配置。
        """
        # Step 1: 拟合半衰期
        half_life = fit_exponential_decay(ic_decay)

        # 构建特征向量
        trigger_score = {
            TriggerMode.CONTINUOUS: 0.0,
            TriggerMode.CONDITION: 0.5,
            TriggerMode.EVENT: 1.0,
        }[trigger_mode]

        feature_vector = {
            "half_life_days": half_life,
            "signal_sparsity": signal_sparsity,
            "trigger_score": trigger_score,
            "ic_decay_rate": self._calc_decay_rate(ic_decay),
            "signal_persistence": self._calc_persistence(ic_decay),
        }

        # Step 4: 分类决策
        signal_type, confidence = self._classify_decision_tree(
            half_life, signal_sparsity, trigger_mode,
        )

        # Step 5: 推荐配置
        recommended_freq = self._recommend_frequency(signal_type, half_life)
        selection = self._recommend_selection(signal_type)
        weighting = self._recommend_weighting(signal_type)
        config = self._recommend_strategy_config(signal_type, half_life)
        reasoning = self._generate_reasoning(
            factor_name, signal_type, half_life, signal_sparsity, trigger_mode, ic_decay,
        )

        return FactorClassification(
            factor_name=factor_name,
            signal_type=signal_type,
            recommended_frequency=recommended_freq,
            recommended_selection=selection,
            recommended_weighting=weighting,
            feature_vector=feature_vector,
            confidence=confidence,
            reasoning=reasoning,
            recommended_config=config,
        )

    def classify_from_profile(
        self,
        profile: FactorProfile,
        signal_sparsity: float = 0.80,
        trigger_mode: TriggerMode = TriggerMode.CONTINUOUS,
    ) -> FactorClassification:
        """从已有FactorProfile分类。

        Args:
            profile: 包含ic_decay和half_life_days的FactorProfile。
            signal_sparsity: 有效信号占比。
            trigger_mode: 触发模式。

        Returns:
            FactorClassification。
        """
        return self.classify_factor(
            factor_name=profile.name,
            ic_decay=profile.ic_decay,
            signal_sparsity=signal_sparsity,
            trigger_mode=trigger_mode,
            category=profile.category,
        )

    def classify_batch(
        self,
        factors: list[dict],
    ) -> list[FactorClassification]:
        """批量分类多个因子。

        Args:
            factors: 因子配置列表, 每个元素是classify_factor()的关键字参数dict。
                必须包含 factor_name 和 ic_decay。

        Returns:
            FactorClassification列表。
        """
        results = []
        for factor_info in factors:
            result = self.classify_factor(**factor_info)
            results.append(result)
            logger.info(
                "因子 %s: type=%s, freq=%s, confidence=%.2f",
                result.factor_name,
                result.signal_type.value,
                result.recommended_frequency,
                result.confidence,
            )
        return results

    def register_type(
        self,
        type_name: str,
        half_life_range: tuple[float, float],
        sparsity_range: tuple[float, float],
        trigger: TriggerMode,
        strategy_name: str,
    ) -> None:
        """注册新的因子类型（可扩展框架）。

        Args:
            type_name: 类型名称。
            half_life_range: (min, max) 半衰期范围。
            sparsity_range: (min, max) 稀疏度范围。
            trigger: 触发模式。
            strategy_name: 推荐策略类名。
        """
        self._type_registry[type_name] = {
            "half_life": half_life_range,
            "sparsity": sparsity_range,
            "trigger": trigger,
        }
        self._strategy_map[type_name] = strategy_name
        logger.info("注册因子类型: %s -> %s", type_name, strategy_name)

    # ── 分类决策树 ──

    def _classify_decision_tree(
        self,
        half_life: float,
        sparsity: float,
        trigger: TriggerMode,
    ) -> tuple[FactorSignalType, float]:
        """R1 §6.3 决策树实现。

        Returns:
            (signal_type, confidence) 元组。
        """
        # Rule 1: 事件触发 → 事件型
        if trigger == TriggerMode.EVENT:
            return FactorSignalType.EVENT, 0.90

        # Rule 2: 条件触发 + 超长半衰期 → 调节型
        if trigger == TriggerMode.CONDITION and half_life > 60:
            return FactorSignalType.MODIFIER, 0.85

        # Rule 3: 低稀疏度 + 非持续触发 → 事件型
        if sparsity < 0.20 and trigger != TriggerMode.CONTINUOUS:
            return FactorSignalType.EVENT, 0.75

        # Rule 4: 短半衰期 + 高稀疏度 → 快排序型
        if half_life < 15 and sparsity >= 0.50:
            confidence = 0.85
            # 边界区域降低置信度
            if 12 < half_life < 18:
                confidence *= 0.70
            return FactorSignalType.FAST_RANKING, confidence

        # Rule 5: 长半衰期 + 高稀疏度 → 排序型
        if half_life >= 15 and sparsity >= 0.50:
            confidence = 0.85
            if 12 < half_life < 18:
                confidence *= 0.70
            return FactorSignalType.RANKING, confidence

        # Rule 6: 中间稀疏度 (0.20-0.50) → 混合型
        if 0.20 <= sparsity < 0.50:
            confidence = 0.50
            if 0.15 < sparsity < 0.25:
                confidence *= 0.70
            return FactorSignalType.HYBRID, confidence

        # 兜底: 未分类
        return FactorSignalType.UNCLASSIFIED, 0.30

    # ── 推荐逻辑 ──

    def _recommend_frequency(
        self, signal_type: FactorSignalType, half_life: float,
    ) -> str:
        """推荐调仓频率。"""
        if signal_type == FactorSignalType.EVENT:
            return "daily"  # 事件型每天检查信号
        if signal_type == FactorSignalType.MODIFIER:
            return "monthly"  # 调节型随主策略
        # 排序型和快排序型: 基于半衰期
        return recommend_freq(half_life)

    @staticmethod
    def _recommend_selection(signal_type: FactorSignalType) -> SelectionMethod:
        """推荐选股方式。"""
        if signal_type == FactorSignalType.EVENT:
            return SelectionMethod.EVENT_TRIGGER
        if signal_type == FactorSignalType.MODIFIER:
            return SelectionMethod.THRESHOLD
        return SelectionMethod.TOP_N

    @staticmethod
    def _recommend_weighting(signal_type: FactorSignalType) -> WeightingScheme:
        """推荐权重方案。"""
        if signal_type == FactorSignalType.EVENT:
            return WeightingScheme.SIGNAL_STRENGTH
        if signal_type == FactorSignalType.MODIFIER:
            return WeightingScheme.RISK_PARITY
        # LL-018: 等权是5因子等权场景的最优解
        return WeightingScheme.EQUAL

    def _recommend_strategy_config(
        self, signal_type: FactorSignalType, half_life: float,
    ) -> dict:
        """根据分类推荐完整策略配置。

        对应R1 §6.3 Step 5。
        """
        if signal_type == FactorSignalType.RANKING:
            return {
                "strategy_class": self._strategy_map.get("ranking", "EqualWeightStrategy"),
                "rebalance_freq": recommend_freq(half_life),
                "top_n": 15,
                "weight_method": "equal",
                "turnover_cap": 0.50,
                "industry_cap": 0.25,
            }
        elif signal_type == FactorSignalType.FAST_RANKING:
            return {
                "strategy_class": self._strategy_map.get("fast_ranking", "FastRankingStrategy"),
                "rebalance_freq": recommend_freq(half_life),
                "top_n": 15,
                "weight_method": "equal",
                "turnover_cap": 0.70,
                "signal_reversal_exit": True,
                "max_replace": 8,
            }
        elif signal_type == FactorSignalType.EVENT:
            return {
                "strategy_class": self._strategy_map.get("event", "EventDrivenStrategy"),
                "holding_days": max(5, int(half_life * 2)),
                "signal_threshold": -2.0,
                "max_positions": 10,
                "position_size": 0.05,
                "stop_loss_pct": -0.05,
                "confirmation_delay": 1,
            }
        elif signal_type == FactorSignalType.MODIFIER:
            return {
                "strategy_class": self._strategy_map.get("modifier", "ModifierPlugin"),
                "target_strategy": "equal_weight",
                "regime_method": "vol_scaling",
                "scaling_range": [0.5, 2.0],
            }
        else:
            return {
                "strategy_class": "manual_review",
                "notes": "需人工审查确定策略类型",
            }

    # ── 辅助计算 ──

    @staticmethod
    def _calc_decay_rate(ic_decay: dict[int, float]) -> float:
        """计算IC衰减速率: IC(20d) / IC(1d)。

        比率越小衰减越快。1.0表示无衰减。
        """
        if not ic_decay:
            return 1.0
        horizons = sorted(ic_decay.keys())
        if len(horizons) < 2:
            return 1.0
        ic_first = abs(ic_decay[horizons[0]])
        ic_last = abs(ic_decay[horizons[-1]])
        if ic_first < 1e-8:
            return 1.0
        return round(ic_last / ic_first, 4)

    @staticmethod
    def _calc_persistence(ic_decay: dict[int, float]) -> float:
        """计算信号持续性: IC(10d) / IC(1d)。

        >0.8 表示高持续性(适合月度), <0.5 表示快衰减(适合周度)。
        """
        if not ic_decay:
            return 1.0
        ic_1 = abs(ic_decay.get(1, 0.0))
        ic_10 = abs(ic_decay.get(10, ic_decay.get(5, 0.0)))
        if ic_1 < 1e-8:
            return 1.0
        return round(ic_10 / ic_1, 4)

    @staticmethod
    def _generate_reasoning(
        factor_name: str,
        signal_type: FactorSignalType,
        half_life: float,
        sparsity: float,
        trigger: TriggerMode,
        ic_decay: dict[int, float],
    ) -> str:
        """生成分类的经济学解释。"""
        ic_1 = ic_decay.get(1, 0.0)
        ic_20 = ic_decay.get(20, 0.0)
        decay_pct = (1 - abs(ic_20) / abs(ic_1)) * 100 if abs(ic_1) > 1e-8 else 0

        parts = [
            f"因子 {factor_name} 分类为 {signal_type.value}。",
            f"IC半衰期={half_life:.1f}天，IC从{ic_1:.2%}(1日)衰减到{ic_20:.2%}(20日)，"
            f"衰减{decay_pct:.0f}%。",
        ]

        if signal_type == FactorSignalType.RANKING:
            parts.append(
                f"信号稀疏度{sparsity:.0%}，截面排序有效。"
                f"半衰期>{15}天，月度调仓匹配。"
            )
        elif signal_type == FactorSignalType.FAST_RANKING:
            parts.append(
                f"信号稀疏度{sparsity:.0%}，截面排序有效。"
                f"但半衰期仅{half_life:.0f}天，月度调仓时信号已衰减过半，"
                f"推荐{recommend_freq(half_life)}调仓。"
            )
        elif signal_type == FactorSignalType.EVENT:
            parts.append(
                f"信号稀疏度仅{sparsity:.0%}，有效信号集中在极端分位。"
                f"触发模式为{trigger.value}，适合阈值触发+固定持有期策略。"
            )
        elif signal_type == FactorSignalType.MODIFIER:
            parts.append(
                f"触发模式为{trigger.value}，半衰期{half_life:.0f}天(超长)。"
                f"不独立选股，叠加到核心策略上调节仓位。"
            )
        elif signal_type == FactorSignalType.HYBRID:
            parts.append(
                f"信号稀疏度{sparsity:.0%}介于排序型(>50%)和事件型(<20%)之间，"
                f"分类置信度较低，建议测试多种策略后择优。"
            )

        return " ".join(parts)


# ============================================================
# 便捷函数
# ============================================================


def classify_v11_factors() -> list[FactorClassification]:
    """对v1.1的5个Active因子进行分类（使用R1报告中的ic_decay数据）。

    Returns:
        5个因子的分类结果列表。
    """
    classifier = FactorClassifier()

    v11_factors = [
        {
            "factor_name": "turnover_mean_20",
            "ic_decay": {1: 0.064, 5: 0.058, 10: 0.051, 20: 0.042},
            "signal_sparsity": 0.85,
            "trigger_mode": TriggerMode.CONTINUOUS,
            "category": "liquidity",
        },
        {
            "factor_name": "volatility_20",
            "ic_decay": {1: 0.069, 5: 0.063, 10: 0.056, 20: 0.045},
            "signal_sparsity": 0.85,
            "trigger_mode": TriggerMode.CONTINUOUS,
            "category": "risk",
        },
        {
            "factor_name": "reversal_20",
            "ic_decay": {1: 0.052, 5: 0.041, 10: 0.032, 20: 0.021},
            "signal_sparsity": 0.85,
            "trigger_mode": TriggerMode.CONTINUOUS,
            "category": "price_volume",
        },
        {
            "factor_name": "amihud_20",
            "ic_decay": {1: 0.022, 5: 0.020, 10: 0.019, 20: 0.017},
            "signal_sparsity": 0.85,
            "trigger_mode": TriggerMode.CONTINUOUS,
            "category": "liquidity",
        },
        {
            "factor_name": "bp_ratio",
            "ic_decay": {1: 0.052, 5: 0.051, 10: 0.050, 20: 0.048},
            "signal_sparsity": 0.85,
            "trigger_mode": TriggerMode.CONTINUOUS,
            "category": "fundamental",
        },
    ]

    return classifier.classify_batch(v11_factors)
