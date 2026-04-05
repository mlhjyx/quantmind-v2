"""FastRankingStrategy — 快衰减因子专用排序策略。

专为ic_decay < 10天的快衰减因子设计（如vwap_bias）。
与MultiFreqStrategy的关键差异:
- 强制 rebalance_freq in {daily, weekly}，不支持低频
- 额外换手惩罚: 换手率超过 turnover_target 时对新进个股打折
- 支持 score_weighted 权重（快因子信号强时应集中）
- 覆盖率要求宽松（快因子数据点少时允许通过）

config必须包含:
    factor_names: list[str]            快衰减因子名称列表
    top_n: int                         选股数量 [5, 30]
    rebalance_freq: str                daily 或 weekly
    industry_cap: float                行业上限（0.5 适合集中策略）
    turnover_cap: float                换手上限 [0.1, 1.0]
    turnover_target: float             目标换手率（超过则打折新进），默认0.3
    weight_method: str                 equal | score_weighted
    new_position_discount: float       新进个股权重折扣系数 [0.5, 1.0]，默认0.8

设计文档对照:
- DESIGN_V5.md §6: 7步组合构建链路
- R1: ic_decay→调仓频率匹配（铁律8）
- R3: 核心+Modifier架构，本策略作为快频核心策略
"""

from datetime import date, timedelta
from typing import Any

import structlog

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

# 快衰减因子的最大调仓频率限制
_FAST_FREQS = {"daily", "weekly"}

# 新进个股折扣默认值（控制快因子换手成本）
_DEFAULT_NEW_POSITION_DISCOUNT = 0.8
_DEFAULT_TURNOVER_TARGET = 0.3


class FastRankingStrategy(BaseStrategy):
    """快衰减因子专用排序策略（daily/weekly调仓）。

    针对 ic_decay < 10天 的因子（如 vwap_bias）设计。
    在换手成本和信号时效之间取得平衡：
    - 新进个股打折（降低换手冲动）
    - 保留上期持仓中仍排名靠前的标的（减少不必要换手）
    """

    signal_type = SignalType.RANKING

    @classmethod
    def get_meta(cls) -> StrategyMeta:
        """策略元信息。"""
        return StrategyMeta(
            name="fast_ranking",
            signal_type=SignalType.RANKING,
            supported_freqs=[RebalanceFreq.DAILY, RebalanceFreq.WEEKLY],
            supported_weights=[WeightMethod.EQUAL, WeightMethod.SCORE_WEIGHTED],
            description="快衰减因子排序策略（daily/weekly，ic_decay<10天）",
        )

    def generate_signals(self, context: StrategyContext) -> StrategyDecision:
        """因子->信号->目标持仓，含新进折扣和换手抑制。

        流程:
        1. 因子完整性检查（快因子宽松阈值）
        2. compute_alpha合成得分
        3. build_portfolio（Top-N + 行业约束 + 换手约束）
        4. 新进个股折扣（turnover成本控制）
        5. 归一化

        Args:
            context: 运行时上下文

        Returns:
            StrategyDecision: 目标权重 + 是否调仓 + 告警
        """
        warnings: list[str] = []

        # ── 因子完整性检查（快因子覆盖率阈值宽松）──
        available_factors = set(context.factor_df["factor_name"].unique())
        required_factors = set(self.config["factor_names"])
        missing = required_factors - available_factors
        if missing:
            raise ValueError(
                f"[FastRankingStrategy] 因子缺失: {missing}。"
                f"快衰减因子数据必须完整，不允许静默降级。"
            )

        for fname in self.config["factor_names"]:
            count = context.factor_df[context.factor_df["factor_name"] == fname].shape[0]
            if count < 500:
                # 快因子覆盖率下限较低（500 vs 1000），适合日频数据
                raise ValueError(
                    f"[FastRankingStrategy] 快因子 {fname} 覆盖率严重不足: {count}只 < 500"
                )
            elif count < 2000:
                msg = f"快因子 {fname} 覆盖率偏低: {count}只 < 2000"
                logger.warning(f"[FastRankingStrategy] P2 {msg}")
                warnings.append(msg)

        # ── 信号合成 ──
        scores = self.compute_alpha(context.factor_df, context.universe)
        if scores.empty:
            raise ValueError("[FastRankingStrategy] 信号合成结果为空")

        # ── 构建目标持仓 ──
        target = self.build_portfolio(
            scores,
            context.industry_map,
            context.prev_holdings,
        )
        logger.info(
            f"[FastRankingStrategy] 目标持仓: {len(target)}只, 总权重={sum(target.values()):.3f}"
        )

        # ── 新进个股折扣（换手成本控制）──
        if context.prev_holdings:
            target = self._apply_new_position_discount(
                target,
                context.prev_holdings,
                warnings,
            )

        # ── 是否调仓日 ──
        is_rebalance = self.should_rebalance(context.trade_date, context.conn)

        return StrategyDecision(
            target_weights=target,
            is_rebalance=is_rebalance,
            reasoning=(
                f"FastRanking {len(self.config['factor_names'])}快因子, "
                f"Top-{self.config['top_n']}, "
                f"频率={self.config['rebalance_freq']}, "
                f"新进折扣={self.config.get('new_position_discount', _DEFAULT_NEW_POSITION_DISCOUNT)}"
            ),
            warnings=warnings,
            signal_type=SignalType.RANKING,
        )

    def should_rebalance(self, trade_date: date, conn: Any) -> bool:
        """判断是否调仓日。daily=每日，weekly=每周首个交易日。"""
        freq = self.config.get("rebalance_freq", "weekly")
        if freq == "daily":
            return True

        start = trade_date - timedelta(days=7)
        end = trade_date + timedelta(days=7)
        rebalance_dates = get_rebalance_dates(start, end, freq=freq, conn=conn)
        return trade_date in rebalance_dates

    def _apply_new_position_discount(
        self,
        target: dict[str, float],
        prev_holdings: dict[str, float],
        warnings: list[str],
    ) -> dict[str, float]:
        """对新进个股施加权重折扣，抑制换手。

        折扣系数 new_position_discount ∈ [0.5, 1.0]。
        折扣后重新归一化，保持总权重不变。

        Args:
            target: 原始目标权重 {code: weight}
            prev_holdings: 上期持仓 {code: weight}
            warnings: 告警列表（原地追加）

        Returns:
            折扣+归一化后的目标权重
        """
        discount = self.config.get("new_position_discount", _DEFAULT_NEW_POSITION_DISCOUNT)
        turnover_target = self.config.get("turnover_target", _DEFAULT_TURNOVER_TARGET)

        prev_codes = set(prev_holdings.keys())
        target_codes = set(target.keys())
        new_in = target_codes - prev_codes

        if not new_in:
            return target

        # 计算当前换手率（新进+退出两端）
        out = prev_codes - target_codes
        turnover = (len(new_in) + len(out)) / max(len(prev_codes | target_codes), 1)

        if turnover <= turnover_target:
            # 换手率在目标内，不施加额外折扣
            return target

        # 换手率超标，对新进个股施加折扣
        adjusted: dict[str, float] = {}
        for code, weight in target.items():
            if code in new_in:
                adjusted[code] = weight * discount
            else:
                adjusted[code] = weight

        # 归一化，保持原始总权重
        original_total = sum(target.values())
        adjusted_total = sum(adjusted.values())
        if adjusted_total > 1e-9:
            scale = original_total / adjusted_total
            adjusted = {c: w * scale for c, w in adjusted.items()}

        msg = (
            f"换手率={turnover:.0%} > 目标{turnover_target:.0%}，"
            f"对{len(new_in)}只新进个股施加{discount:.0%}折扣"
        )
        logger.info(f"[FastRankingStrategy] {msg}")
        warnings.append(msg)
        return adjusted

    def _validate_config(self) -> None:
        """验证FastRanking策略配置。"""
        super()._validate_config()
        freq = self.config.get("rebalance_freq", "weekly")
        if freq not in _FAST_FREQS:
            raise ValueError(
                f"FastRankingStrategy只支持快频率{_FAST_FREQS}，当前: {freq}。"
                "月度/双周策略请用EqualWeightStrategy。"
            )
        top_n = self.config.get("top_n", 10)
        if not (5 <= top_n <= 30):
            raise ValueError(
                f"FastRankingStrategy top_n建议[5,30]，当前: {top_n}。"
                "快因子集中持股风险高，不建议>30。"
            )
        discount = self.config.get("new_position_discount", _DEFAULT_NEW_POSITION_DISCOUNT)
        if not (0.5 <= discount <= 1.0):
            raise ValueError(f"new_position_discount必须在[0.5, 1.0]，当前: {discount}")
