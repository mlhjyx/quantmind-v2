"""MultiFreqStrategy — 可配置频率策略（用于因子重验证）。

与EqualWeightStrategy的关键差异:
- rebalance_freq支持daily/weekly/biweekly/monthly
- 可以只使用部分因子（用于单因子或因子组合测试）
- 不强制weight_method='equal'，支持score_weighted

config必须包含:
    factor_names: list[str]
    top_n: int
    rebalance_freq: str  # daily/weekly/biweekly/monthly
    industry_cap: float
    turnover_cap: float
    weight_method: str   # "equal" or "score_weighted"
"""

import structlog
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd

from engines.base_strategy import (
    BaseStrategy,
    RebalanceFreq,
    SignalType,
    StrategyContext,
    StrategyDecision,
    StrategyMeta,
    WeightMethod,
)
from engines.signal_engine import get_rebalance_dates

logger = structlog.get_logger(__name__)


class MultiFreqStrategy(BaseStrategy):
    """可配置频率策略，用于因子重验证和回测对比。"""

    signal_type = SignalType.RANKING

    @classmethod
    def get_meta(cls) -> StrategyMeta:
        """策略元信息。"""
        return StrategyMeta(
            name="multi_freq",
            signal_type=SignalType.RANKING,
            supported_freqs=[
                RebalanceFreq.DAILY,
                RebalanceFreq.WEEKLY,
                RebalanceFreq.BIWEEKLY,
                RebalanceFreq.MONTHLY,
            ],
            supported_weights=[WeightMethod.EQUAL, WeightMethod.SCORE_WEIGHTED],
            description="可配置频率策略（因子重验证和回测对比）",
        )

    def generate_signals(self, context: StrategyContext) -> StrategyDecision:
        """因子->信号->目标持仓。

        与EqualWeightStrategy相比:
        - 不做max_replace限制
        - 不做覆盖率告警（测试场景可能用少量数据）
        - 精简验证逻辑

        Args:
            context: 运行时上下文

        Returns:
            StrategyDecision
        """
        warnings: list[str] = []

        # ── 因子完整性检查 ──
        available_factors = set(context.factor_df["factor_name"].unique())
        required_factors = set(self.config["factor_names"])
        missing = required_factors - available_factors
        if missing:
            raise ValueError(f"因子缺失: {missing}")

        # ── 信号合成 ──
        scores = self.compute_alpha(context.factor_df, context.universe)
        if scores.empty:
            raise ValueError("信号合成结果为空")

        # ── 构建目标持仓 ──
        target = self.build_portfolio(
            scores, context.industry_map, context.prev_holdings,
        )

        # ── 是否调仓日 ──
        is_rebalance = self.should_rebalance(context.trade_date, context.conn)

        return StrategyDecision(
            target_weights=target,
            is_rebalance=is_rebalance,
            reasoning=(
                f"MultiFreq {len(self.config['factor_names'])}因子, "
                f"Top-{self.config['top_n']}, "
                f"频率={self.config['rebalance_freq']}, "
                f"权重={self.config.get('weight_method', 'equal')}"
            ),
            warnings=warnings,
        )

    def should_rebalance(self, trade_date: date, conn: Any) -> bool:
        """判断是否调仓日。支持daily频率。"""
        freq = self.config.get("rebalance_freq", "monthly")

        if freq == "daily":
            # daily频率: 每个交易日都调仓
            return True

        start = trade_date - timedelta(days=7)
        end = trade_date + timedelta(days=7)
        rebalance_dates = get_rebalance_dates(start, end, freq=freq, conn=conn)
        return trade_date in rebalance_dates

    def _validate_config(self) -> None:
        """验证MultiFreq策略配置。"""
        super()._validate_config()
        valid_freqs = {"daily", "weekly", "biweekly", "monthly"}
        freq = self.config.get("rebalance_freq", "monthly")
        if freq not in valid_freqs:
            raise ValueError(
                f"rebalance_freq必须是{valid_freqs}之一，当前: {freq}"
            )
