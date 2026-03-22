"""信号合成引擎 — 因子→信号→目标持仓。

Phase 0: 等权Top-N信号合成。
- 每个因子等权(1/N)
- 截面zscore后求和
- 排名取Top-N
- 行业约束(单行业≤25%)
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# 因子方向: +1表示因子值越大越好, -1表示越小越好
FACTOR_DIRECTION = {
    "momentum_5": 1,
    "momentum_10": 1,
    "momentum_20": 1,
    "reversal_5": 1,   # 已经取反(calc_reversal = -pct_change)
    "reversal_10": 1,
    "reversal_20": 1,
    "volatility_20": -1,     # 低波动好
    "volatility_60": -1,
    "volume_std_20": -1,     # 低量波动好
    "turnover_mean_20": -1,  # 低换手好
    "turnover_std_20": -1,
    "amihud_20": 1,          # 高非流动性=小盘溢价
    "ln_market_cap": -1,     # 小市值好(Phase 0)
    "bp_ratio": 1,           # 高B/P=价值股好
    "ep_ratio": 1,           # 高E/P好
    "price_volume_corr_20": -1,  # 低价量相关好
    "high_low_range_20": -1,     # 低振幅好
    "mf_momentum_divergence": -1,  # 资金流动量背离: 值越负=背离越大→信号越强
}


@dataclass
class SignalConfig:
    """信号生成配置。"""
    top_n: int = 20
    weight_method: str = "equal"  # 'equal' or 'score_weighted'
    industry_cap: float = 0.25   # 单行业上限25%
    rebalance_freq: str = "biweekly"  # 'weekly', 'biweekly', 'monthly'
    turnover_cap: float = 0.50   # 单次换手率上限50%
    factor_names: list[str] = field(default_factory=lambda: [
        # P0诊断后去冗余: 17→8个独立因子
        # 删除: momentum_5/10/20 (方向反, 与reversal完全冗余 corr=-1.0)
        # 删除: reversal_5/10 (只留20), volatility_60 (与vol20 corr=0.73)
        # 删除: volume_std_20 (弱IC), high_low_range_20 (与vol20 corr=0.90)
        # 删除: price_volume_corr_20 (信息重叠)
        "turnover_mean_20",  # IC=4.55%, 核心Alpha, 4/5年>3%
        "turnover_std_20",   # IC=3.90%, 4/5年>3%
        "volatility_20",     # IC=3.27%, 3/5年>3%
        "reversal_20",       # IC=2.48%, 反转效应
        "amihud_20",         # IC=2.80%, 流动性维度独立
        "bp_ratio",          # IC=2.64%, 价值维度
        "ln_market_cap",     # IC=1.51%, 规模维度
        "ep_ratio",          # IC=1.30%, 价值维度(与bp corr=0.33, 独立)
    ])


# Route A锁定配置: 5因子等权 + Top15月频 + IndCap=25% (v1.1: Top20→15)
PAPER_TRADING_CONFIG = SignalConfig(
    factor_names=[
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",
        "amihud_20",
        "bp_ratio",
    ],
    top_n=15,
    weight_method="equal",
    rebalance_freq="monthly",
    industry_cap=0.25,
    turnover_cap=0.50,
)


# v1.2候选配置: 6因子 = 基线5 + mf_momentum_divergence (资金流维度)
# 不替换v1.1(PAPER_TRADING_CONFIG)，v1.1继续Paper Trading跑
# mf_momentum_divergence IC=9.1%，与基线5因子正交（资金流-价格背离维度）
V12_CONFIG = SignalConfig(
    factor_names=[
        # 基线5因子（与PAPER_TRADING_CONFIG一致）
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",
        "amihud_20",
        "bp_ratio",
        # v1.2新增: 资金流维度
        "mf_momentum_divergence",
    ],
    top_n=15,
    weight_method="equal",
    rebalance_freq="monthly",
    industry_cap=0.25,
    turnover_cap=0.50,
)


class SignalComposer:
    """信号合成器 — 因子→composite score→排名。"""

    def __init__(self, config: SignalConfig):
        self.config = config

    def compose(
        self,
        factor_df: pd.DataFrame,
        universe: Optional[set[str]] = None,
    ) -> pd.Series:
        """合成综合因子得分。

        Args:
            factor_df: 宽表 columns=[code, factor_name, neutral_value]
                       （单日截面数据）
            universe: 可选的universe过滤集合

        Returns:
            pd.Series indexed by code, values = composite score
        """
        # Pivot to wide format: code × factor_name
        pivot = factor_df.pivot_table(
            index="code",
            columns="factor_name",
            values="neutral_value",
            aggfunc="first",
        )

        if universe:
            pivot = pivot[pivot.index.isin(universe)]

        # 选择配置的因子
        available = [f for f in self.config.factor_names if f in pivot.columns]
        if not available:
            logger.warning("无可用因子")
            return pd.Series(dtype=float)

        pivot = pivot[available]

        # 方向调整
        for fname in available:
            direction = FACTOR_DIRECTION.get(fname, 1)
            if direction == -1:
                pivot[fname] = -pivot[fname]

        # 等权合成
        weights = {f: 1.0 / len(available) for f in available}
        composite = sum(pivot[f] * w for f, w in weights.items())

        return composite.sort_values(ascending=False)


class PortfolioBuilder:
    """目标持仓构建器 — composite score → 目标权重。"""

    def __init__(self, config: SignalConfig):
        self.config = config

    def build(
        self,
        scores: pd.Series,
        industry: pd.Series,
        prev_holdings: Optional[dict[str, float]] = None,
    ) -> dict[str, float]:
        """构建目标持仓权重。

        Args:
            scores: 综合得分 (code → score), 已排序
            industry: 行业分类 (code → industry_sw1)
            prev_holdings: 上期持仓权重 (code → weight)

        Returns:
            dict: {code: target_weight}, 权重之和=1.0
        """
        top_n = self.config.top_n
        industry_cap = self.config.industry_cap
        max_per_industry = int(top_n * industry_cap)

        # 1. 按分数排名选股，加行业约束
        selected = []
        industry_count = {}

        for code in scores.index:
            if len(selected) >= top_n:
                break

            ind = industry.get(code, "其他")
            cnt = industry_count.get(ind, 0)
            if cnt >= max_per_industry:
                continue

            selected.append(code)
            industry_count[ind] = cnt + 1

        if not selected:
            return {}

        # 2. 等权
        if self.config.weight_method == "equal":
            weight = 1.0 / len(selected)
            target = {code: weight for code in selected}
        else:
            # score_weighted (Phase 1)
            sel_scores = scores.loc[selected]
            sel_scores = sel_scores - sel_scores.min() + 1e-6  # shift to positive
            total = sel_scores.sum()
            target = {code: float(s / total) for code, s in sel_scores.items()}

        # 3. 换手率约束
        if prev_holdings and self.config.turnover_cap < 1.0:
            target = self._apply_turnover_cap(target, prev_holdings)

        return target

    def _apply_turnover_cap(
        self,
        target: dict[str, float],
        prev: dict[str, float],
    ) -> dict[str, float]:
        """应用换手率上限（严格保持Top-N持仓数）。

        关键不变式: 输出持仓数 <= len(target) = top_n。
        旧持仓中不在target的股票目标权重=0（全卖），
        换手率上限只控制卖出速度，不保留旧持仓。

        Bug fix: 原代码对target∪prev取并集做blend,
        导致持仓从20膨胀到43。修复: blend后只保留target中的股票。
        """
        target_codes = set(target)
        all_codes = target_codes | set(prev)
        turnover = sum(
            abs(target.get(c, 0) - prev.get(c, 0)) for c in all_codes
        ) / 2  # 单边换手

        if turnover <= self.config.turnover_cap:
            return target

        # 缩放变化量，降低换手率
        ratio = self.config.turnover_cap / max(turnover, 1e-12)
        blended = {}
        for c in all_codes:
            t = target.get(c, 0)
            p = prev.get(c, 0)
            blended[c] = p + ratio * (t - p)

        # ── 关键修复: 只保留target中的股票 ──
        # 旧持仓中不在target的股票: blended值>0但不应保留在目标中。
        # 它们在execute时会因target_weight=0而被卖出（受can_trade限制）。
        blended = {c: w for c, w in blended.items()
                   if c in target_codes and w > 0.001}

        # 重新归一化
        total = sum(blended.values())
        if total > 0:
            blended = {c: w / total for c, w in blended.items()}

        return blended


def get_rebalance_dates(
    start_date: date,
    end_date: date,
    freq: str = "biweekly",
    conn=None,
) -> list[date]:
    """获取调仓日历(信号生成日)。

    调仓日=周五(信号日), 执行日=下周一。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        freq: 'weekly', 'biweekly', 'monthly'
        conn: psycopg2连接

    Returns:
        list of signal dates (Fridays)
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        all_dates = pd.read_sql(
            """SELECT DISTINCT trade_date FROM klines_daily
               WHERE trade_date BETWEEN %s AND %s
               ORDER BY trade_date""",
            conn, params=(start_date, end_date),
        )["trade_date"].tolist()

        if not all_dates:
            return []

        # 按周分组
        date_series = pd.Series(all_dates)

        if freq == "weekly":
            # 每周最后一个交易日
            weeks = date_series.groupby(
                date_series.apply(lambda d: d.isocalendar()[:2])
            ).last()
            return sorted(weeks.tolist())

        elif freq == "biweekly":
            # 每两周最后一个交易日
            weeks = date_series.groupby(
                date_series.apply(lambda d: d.isocalendar()[:2])
            ).last()
            return sorted(weeks.iloc[::2].tolist())

        elif freq == "monthly":
            # 每月最后一个交易日
            months = date_series.groupby(
                date_series.apply(lambda d: (d.year, d.month))
            ).last()
            return sorted(months.tolist())

        else:
            raise ValueError(f"Unknown freq: {freq}")
    finally:
        if close_conn:
            conn.close()
