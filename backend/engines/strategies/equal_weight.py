"""EqualWeightStrategy — 等权Top-N定期调仓策略。

v1.1/v1.2等配置使用此策略。核心逻辑复用SignalComposer/PortfolioBuilder，
本类负责编排调用顺序和4项验证。

config必须包含:
    factor_names: list[str]
    top_n: int
    rebalance_freq: str  # monthly/biweekly/weekly
    industry_cap: float
    turnover_cap: float
    weight_method: str   # "equal"
    max_replace: int | None  # 每次最大换仓数，None=不限制
"""

import logging
from datetime import date
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

logger = logging.getLogger(__name__)


class EqualWeightStrategy(BaseStrategy):
    """等权Top-N定期调仓策略（v1.1/v1.2等配置）。"""

    signal_type = SignalType.RANKING

    @classmethod
    def get_meta(cls) -> StrategyMeta:
        """策略元信息。"""
        return StrategyMeta(
            name="equal_weight",
            signal_type=SignalType.RANKING,
            supported_freqs=[
                RebalanceFreq.WEEKLY,
                RebalanceFreq.BIWEEKLY,
                RebalanceFreq.MONTHLY,
            ],
            supported_weights=[WeightMethod.EQUAL],
            description="等权Top-N定期调仓（v1.1/v1.2配置）",
        )

    def generate_signals(self, context: StrategyContext) -> StrategyDecision:
        """因子->信号->目标持仓。

        流程:
        1. compute_alpha: 等权合成综合得分
        2. build_portfolio: Top-N + 行业约束 + 换手约束
        3. max_replace限制（可选）
        4. 4项验证（因子覆盖/行业集中/换手/持仓重合）

        Args:
            context: 运行时上下文

        Returns:
            StrategyDecision: 目标权重 + 是否调仓 + 告警
        """
        warnings: list[str] = []

        # ── 检查因子完整性 ──
        available_factors = set(context.factor_df["factor_name"].unique())
        required_factors = set(self.config["factor_names"])
        missing = required_factors - available_factors
        if missing:
            raise ValueError(
                f"因子缺失: {missing}。"
                f"配置要求{len(required_factors)}因子，"
                f"实际只有{len(required_factors - missing)}。不允许静默降级。"
            )

        # ── 因子截面覆盖率检查 ──
        for fname in self.config["factor_names"]:
            count = context.factor_df[
                context.factor_df["factor_name"] == fname
            ].shape[0]
            if count < 1000:
                raise ValueError(
                    f"因子 {fname} 截面覆盖率严重不足: {count}只 < 1000"
                )
            elif count < 3000:
                msg = (
                    f"因子 {fname} 截面覆盖率偏低: {count}只 < 3000。"
                    f"信号生成继续，但请排查数据完整性。"
                )
                logger.warning(f"[EqualWeightStrategy] P1 {msg}")
                warnings.append(msg)

        # ── 信号合成 ──
        scores = self.compute_alpha(context.factor_df, context.universe)
        if scores.empty:
            raise ValueError("信号合成结果为空(scores为空)")

        # ── 构建目标持仓 ──
        target = self.build_portfolio(
            scores, context.industry_map, context.prev_holdings,
        )
        logger.info(
            f"[EqualWeightStrategy] 目标持仓: {len(target)}只, "
            f"总权重={sum(target.values()):.3f}"
        )

        # ── max_replace限制 ──
        max_replace = self.config.get("max_replace")
        if max_replace is not None and context.prev_holdings:
            target = self._apply_max_replace(
                target, context.prev_holdings, max_replace
            )

        # ── 是否调仓日 ──
        is_rebalance = self.should_rebalance(context.trade_date, context.conn)

        # ── 行业集中度检查 ──
        ind_warning = self._check_industry_concentration(
            target, context.industry_map
        )
        if ind_warning:
            warnings.append(ind_warning)

        # ── 持仓重合度检查 ──
        if context.prev_holdings:
            overlap_warning = self._check_overlap(
                target, context.prev_holdings
            )
            if overlap_warning:
                warnings.append(overlap_warning)

        return StrategyDecision(
            target_weights=target,
            is_rebalance=is_rebalance,
            reasoning=(
                f"等权{len(self.config['factor_names'])}因子合成, "
                f"Top-{self.config['top_n']}, "
                f"频率={self.config['rebalance_freq']}"
            ),
            warnings=warnings,
        )

    def should_rebalance(self, trade_date: date, conn: Any) -> bool:
        """判断是否调仓日。基于get_rebalance_dates。"""
        from datetime import timedelta

        # 获取trade_date前后各7天的调仓日，检查当天是否在其中
        start = trade_date - timedelta(days=7)
        end = trade_date + timedelta(days=7)
        rebalance_dates = get_rebalance_dates(
            start, end,
            freq=self.config.get("rebalance_freq", "monthly"),
            conn=conn,
        )
        return trade_date in rebalance_dates

    def _apply_max_replace(
        self,
        target: dict[str, float],
        prev_holdings: dict[str, float],
        max_replace: int,
    ) -> dict[str, float]:
        """限制单次最大换仓数。

        如果新目标相对上期变动股票数超过max_replace，
        优先保留上期持仓中仍在target的股票，新进股票按得分排序截断。
        """
        prev_codes = set(prev_holdings.keys())
        target_codes = set(target.keys())

        new_in = target_codes - prev_codes
        if len(new_in) <= max_replace:
            return target

        # 按权重排序新进股票，只保留max_replace个
        sorted_new = sorted(new_in, key=lambda c: target.get(c, 0), reverse=True)
        keep_new = set(sorted_new[:max_replace])

        # 保留: 上期持仓中仍在target的 + 限制后的新进
        kept_codes = (target_codes & prev_codes) | keep_new
        trimmed = {c: target[c] for c in kept_codes}

        # 重新归一化
        total = sum(trimmed.values())
        if total > 0:
            trimmed = {c: w / total for c, w in trimmed.items()}

        logger.info(
            f"[EqualWeightStrategy] max_replace={max_replace}, "
            f"新进{len(new_in)}->保留{len(keep_new)}"
        )
        return trimmed

    def _check_industry_concentration(
        self,
        target: dict[str, float],
        industry_map: dict[str, str],
    ) -> Optional[str]:
        """行业集中度检查。最大行业权重>25%时告警。"""
        if not target:
            return None

        industry_weights: dict[str, float] = {}
        for code, weight in target.items():
            ind = industry_map.get(code, "未知")
            industry_weights[ind] = industry_weights.get(ind, 0) + weight

        max_ind = max(industry_weights, key=lambda k: industry_weights[k])
        max_weight = industry_weights[max_ind]

        if max_weight > self.config.get("industry_cap", 0.25):
            top5 = sorted(industry_weights.items(), key=lambda x: -x[1])[:5]
            return (
                f"行业集中度过高: {max_ind} 权重={max_weight:.1%} > "
                f"{self.config.get('industry_cap', 0.25):.0%}。"
                f"行业分布: {', '.join(f'{k}={v:.1%}' for k, v in top5)}"
            )
        return None

    def _check_overlap(
        self,
        target: dict[str, float],
        prev_holdings: dict[str, float],
    ) -> Optional[str]:
        """持仓重合度检查。<30%重合时告警。"""
        current_codes = set(target.keys())
        prev_codes = set(prev_holdings.keys())
        if not prev_codes:
            return None

        overlap = len(current_codes & prev_codes)
        overlap_ratio = overlap / max(len(prev_codes), 1)

        if overlap_ratio < 0.30:
            new_in = ", ".join(sorted(current_codes - prev_codes)[:10])
            out = ", ".join(sorted(prev_codes - current_codes)[:10])
            return (
                f"持仓重合度过低: {overlap}/{len(prev_codes)} "
                f"= {overlap_ratio:.0%} < 30%。换手剧烈。"
                f"\n新进: {new_in}\n退出: {out}"
            )
        return None

    def _validate_config(self) -> None:
        """验证EqualWeight策略配置。"""
        super()._validate_config()
        valid_freqs = {"weekly", "biweekly", "monthly"}
        freq = self.config.get("rebalance_freq", "monthly")
        if freq not in valid_freqs:
            raise ValueError(
                f"rebalance_freq必须是{valid_freqs}之一，当前: {freq}"
            )
        if self.config.get("weight_method", "equal") != "equal":
            raise ValueError("EqualWeightStrategy只支持weight_method='equal'")
