"""DynamicThresholdEngine — L3 动态阈值计算引擎 (S7).

V3 §6 规范:
  §6.1 实时市场状态: Calm (1.0x) / Stress (0.8x) / Crisis (0.5x)
  §6.2 个股动态阈值: ATR / beta / liquidity 调整
  §6.3 Industry 联动: 同行业下跌 → CorrelatedDrop min_count 降低

Engine 纯计算 (铁律 31), 市场指标 + 个股数据通过参数注入.
输出: per-rule per-stock 的 effective multiplier.

用法:
    engine = DynamicThresholdEngine()
    state = engine.assess_market_state(indicators)  # Calm/Stress/Crisis
    cache = engine.evaluate(indicators, stock_data, positions)
    # cache["rapid_drop_5min"]["600519.SH"] = 0.8  # Stress 收紧
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class MarketState(Enum):
    """3 级市场状态 (V3 §6.1)."""

    CALM = "calm"  # 1.0x 默认
    STRESS = "stress"  # 0.8x 收紧
    CRISIS = "crisis"  # 0.5x 高敏感


# Per-state market multiplier
_MARKET_MULTIPLIER: dict[MarketState, float] = {
    MarketState.CALM: 1.0,
    MarketState.STRESS: 0.8,
    MarketState.CRISIS: 0.5,
}


@dataclass(frozen=True)
class MarketIndicators:
    """市场指标快照 (输入, V3 §6.1).

    All fields optional — engine handles partial data gracefully.
    """

    index_return: float | None = None  # 上证/CSI300 day return (%)
    limit_down_count: int | None = None  # 全市场跌停家数
    northbound_flow: float | None = None  # 北向净流入 (亿)
    regime: str | None = None  # Bull/Bear/Neutral (from L2, Tier B stub)


@dataclass
class StockMetrics:
    """个股指标 (输入, V3 §6.2).

    All fields optional — engine handles partial data gracefully.
    """

    code: str
    atr_ratio: float | None = None  # ATR(20) / price
    beta: float | None = None  # vs CSI300
    liquidity_percentile: float | None = None  # vol 分位 [0,1]
    industry: str | None = None  # SW1 行业


# ── Rule-level threshold defaults (from .env RT_* or hardcoded baseline) ──

# rule_id → default threshold value (不包 market/stock multiplier)
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "limit_down_detection": 0.099,  # 9.9%
    "near_limit_down": 0.095,  # 9.5%
    "gap_down_open": 0.05,  # 5%
    "rapid_drop_5min": 0.05,  # 5%
    "rapid_drop_15min": 0.08,  # 8%
    "volume_spike": 3.0,  # 3x
    "liquidity_collapse": 0.3,  # 0.3x
    "correlated_drop": 0.03,  # 3% per-stock
}

# rule_id → market-state 调整是否适用 (仅跌幅类规则适用, 量比不调)
_MARKET_SENSITIVE_RULES: frozenset[str] = frozenset(
    {
        "limit_down_detection",
        "near_limit_down",
        "gap_down_open",
        "rapid_drop_5min",
        "rapid_drop_15min",
        "correlated_drop",
    }
)

# rule_id → per-stock 调整是否适用
_STOCK_SENSITIVE_RULES: frozenset[str] = frozenset(
    {
        "rapid_drop_5min",
        "rapid_drop_15min",
        "liquidity_collapse",
        "correlated_drop",
    }
)


class DynamicThresholdEngine:
    """L3 动态阈值引擎 — market-aware + stock-aware threshold adjustment.

    纯计算 (铁律 31), 不 IO / 不 DB / 不 Redis.
    """

    def __init__(
        self,
        defaults: dict[str, float] | None = None,
    ) -> None:
        self._defaults = defaults or dict(_DEFAULT_THRESHOLDS)

    # ── Market state assessment (V3 §6.1) ──

    def assess_market_state(self, indicators: MarketIndicators) -> MarketState:
        """从市场指标评估 Calm / Stress / Crisis.

        Crisis (最高优先):
          - 大盘 -5% OR 跌停家数 > 200

        Stress:
          - regime=Bear OR 大盘 -2% OR 跌停家数 > 50

        Calm:
          - 默认

        Args:
            indicators: 市场指标快照 (字段可为 None).

        Returns:
            MarketState.
        """
        idx = indicators.index_return
        ldc = indicators.limit_down_count
        regime = indicators.regime

        # Crisis checks
        if (idx is not None and idx <= -0.05) or (ldc is not None and ldc > 200):
            return MarketState.CRISIS

        # Stress checks
        if (
            (regime is not None and regime.lower() == "bear")
            or (idx is not None and idx <= -0.02)
            or (ldc is not None and ldc > 50)
        ):
            return MarketState.STRESS

        return MarketState.CALM

    @property
    def market_multiplier(self) -> dict[MarketState, float]:
        """市场状态 → 阈值乘数."""
        return dict(_MARKET_MULTIPLIER)

    # ── Stock-level multiplier (V3 §6.2) ──

    def compute_stock_multiplier(self, metrics: StockMetrics) -> float:
        """计算单股阈值乘数.

        规则 (V3 §6.2):
          - 高 beta (β > 1.5): ×1.2 (更难触发, 减误报)
          - 低 liquidity (vol 分位 < 20%): ×1.5 (更敏感)
          - 高 ATR (ATR/price > 5%): ×1.5 (更难触发)

        Args:
            metrics: 个股指标.

        Returns:
            综合乘数 (默认 1.0). 各因子乘法叠加.
        """
        multiplier = 1.0

        if metrics.beta is not None and metrics.beta > 1.5:
            multiplier *= 1.2

        if metrics.liquidity_percentile is not None and metrics.liquidity_percentile < 0.20:
            multiplier *= 1.5

        if metrics.atr_ratio is not None and metrics.atr_ratio > 0.05:
            multiplier *= 1.5

        return round(multiplier, 4)

    # ── Industry adjustment (V3 §6.3) ──

    def compute_industry_adjustment(
        self,
        positions: list[str],
        stock_metrics: dict[str, StockMetrics],
        industry_day_return: dict[str, float] | None = None,
    ) -> int:
        """计算 CorrelatedDrop min_count 行业联动调整.

        V3 §6.3: 持仓 N 股同行业 + 行业 day -3% → min_count from 3 → 2.

        Args:
            positions: 持仓股 code 列表.
            stock_metrics: code → StockMetrics (含 industry).
            industry_day_return: industry → day return (%). None = no adjustment.

        Returns:
            调整后的 min_count (默认 3, 满足条件 → 2).
        """
        min_count = 3  # default

        if industry_day_return is None:
            return min_count

        # 统计行业持仓数
        industry_positions: dict[str, int] = {}
        for code in positions:
            sm = stock_metrics.get(code)
            if sm is None or sm.industry is None:
                continue
            industry_positions[sm.industry] = industry_positions.get(sm.industry, 0) + 1

        # 任一行业满足: ≥2 股 + 行业 day ≤ -3%
        for industry, count in industry_positions.items():
            ret = industry_day_return.get(industry)
            if ret is not None and ret <= -0.03 and count >= 2:
                min_count = 2
                logger.info(
                    "[dynamic-threshold] industry=%s day_ret=%.2f%% "
                    "positions=%d → CorrelatedDrop min_count %d→%d",
                    industry,
                    ret * 100,
                    count,
                    3,
                    min_count,
                )
                break  # 首个满足即调整

        return min_count

    # ── Full evaluate (V3 §6.4) ──

    def evaluate(
        self,
        indicators: MarketIndicators,
        stock_metrics: dict[str, StockMetrics] | None = None,
        industry_day_return: dict[str, float] | None = None,
    ) -> dict[str, dict[str, float]]:
        """完整阈值评估 → thresholds_cache dict.

        Args:
            indicators: 市场指标.
            stock_metrics: code → StockMetrics. None = 仅市场级调整.
            industry_day_return: industry → day return. None = 无行业调整.

        Returns:
            {rule_id: {code: effective_multiplier}}.
            "correlated_drop" 特殊: multiplier 存 adjusted min_count.

            effective_threshold = default * market_multiplier * stock_multiplier
        """
        state = self.assess_market_state(indicators)
        market_mult = _MARKET_MULTIPLIER[state]

        cache: dict[str, dict[str, float]] = {}

        # CorrelatedDrop min_count (industry adjustment)
        if stock_metrics:
            codes = list(stock_metrics.keys())
            adj_min_count = self.compute_industry_adjustment(
                codes, stock_metrics, industry_day_return
            )
        else:
            adj_min_count = 3

        for rule_id, default in self._defaults.items():
            cache[rule_id] = {}

            # Market-sensitive rules apply market multiplier
            is_market = rule_id in _MARKET_SENSITIVE_RULES
            is_stock = rule_id in _STOCK_SENSITIVE_RULES

            if stock_metrics:
                for code, sm in stock_metrics.items():
                    if rule_id == "correlated_drop":
                        # Store adjusted min_count (not a real multiplier)
                        cache[rule_id][code] = float(adj_min_count)
                    elif is_market and is_stock:
                        stock_mult = self.compute_stock_multiplier(sm)
                        cache[rule_id][code] = round(default * market_mult * stock_mult, 6)
                    elif is_market:
                        cache[rule_id][code] = round(default * market_mult, 6)
                    elif is_stock:
                        stock_mult = self.compute_stock_multiplier(sm)
                        cache[rule_id][code] = round(default * stock_mult, 6)
                    else:
                        cache[rule_id][code] = default
            else:
                # No per-stock data → market-level only
                if rule_id == "correlated_drop":
                    cache[rule_id][""] = float(adj_min_count)
                elif is_market:
                    cache[rule_id][""] = round(default * market_mult, 6)
                else:
                    cache[rule_id][""] = default

        logger.info(
            "[dynamic-threshold] evaluate complete state=%s market_mult=%.2f stocks=%d rules=%d",
            state.value,
            market_mult,
            len(stock_metrics) if stock_metrics else 0,
            len(cache),
        )
        return cache
