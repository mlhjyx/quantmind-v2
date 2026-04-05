"""Phase A 向量化信号层 — 因子合成 → 排序 → 目标持仓生成。

纯pandas/numpy批量运算，无逐日循环，无交易约束。
输入: 因子DataFrame + 配置
输出: dict[date, dict[code, weight]] — 每个调仓日的目标持仓

设计文档: DEV_BACKTEST_ENGINE.md §3.1 Phase A
"""

import structlog
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

logger = structlog.get_logger(__name__)


@dataclass
class SignalConfig:
    """Phase A 信号生成配置。"""
    top_n: int = 15
    rebalance_freq: str = "monthly"         # daily/weekly/biweekly/monthly
    weight_mode: str = "equal"              # equal (后续支持 ic_weighted)
    min_factor_ratio: float = 0.5           # 股票至少有50%因子有值才保留
    industry_cap: float = 0.25              # 行业上限(暂不在Phase A实现，留给Phase B)


def compute_rebalance_dates(trading_days: list[date], freq: str) -> list[date]:
    """从交易日列表计算调仓日期。

    Args:
        trading_days: 已排序的交易日列表
        freq: 调仓频率 daily/weekly/biweekly/monthly

    Returns:
        调仓日期列表（每个周期的最后一个交易日）
    """
    if not trading_days:
        return []

    td_series = pd.Series(trading_days)

    if freq == "daily":
        return list(trading_days)
    elif freq == "weekly":
        return list(
            td_series.groupby(
                td_series.apply(lambda d: (d.year, d.isocalendar()[1]))
            ).last()
        )
    elif freq == "biweekly":
        weekly = list(
            td_series.groupby(
                td_series.apply(lambda d: (d.year, d.isocalendar()[1]))
            ).last()
        )
        return weekly[::2]
    elif freq == "monthly":
        return list(
            td_series.groupby(
                td_series.apply(lambda d: (d.year, d.month))
            ).last()
        )
    else:
        # 默认月度
        return list(
            td_series.groupby(
                td_series.apply(lambda d: (d.year, d.month))
            ).last()
        )


def build_target_portfolios(
    factor_df: pd.DataFrame,
    directions: dict[str, int],
    rebal_dates: list[date],
    config: SignalConfig | None = None,
) -> dict[date, dict[str, float]]:
    """构建目标持仓: 因子z-score合成 → 排序 → TopN等权。

    Args:
        factor_df: 因子长表 (code, trade_date, factor_name, raw_value)
        directions: {factor_name: direction} (+1正向, -1反向)
        rebal_dates: 调仓日期列表
        config: 信号配置（默认SignalConfig()）

    Returns:
        {signal_date: {code: weight}} — 每个调仓日的目标持仓
    """
    if config is None:
        config = SignalConfig()

    top_n = config.top_n
    factor_names = list(directions.keys())
    targets: dict[date, dict[str, float]] = {}

    for rd in rebal_dates:
        # 取调仓日当天或之前最近一天的因子数据
        day_data = factor_df[factor_df["trade_date"] <= rd]
        if day_data.empty:
            continue

        latest_date = day_data["trade_date"].max()
        day_data = day_data[day_data["trade_date"] == latest_date]

        # pivot: code x factor_name → raw_value
        pivot = pd.DataFrame(day_data).pivot_table(
            index="code", columns="factor_name", values="raw_value", aggfunc="first",
        )

        available_factors = [f for f in factor_names if f in pivot.columns]
        if not available_factors:
            continue

        min_factors = max(1, int(len(available_factors) * config.min_factor_ratio) + 1)
        pivot = pivot[available_factors].dropna(thresh=min_factors)
        if len(pivot) < top_n:
            continue

        # z-score + direction
        scores = pd.DataFrame(index=pivot.index)
        for f in available_factors:
            col = pivot[f]
            std = col.std()
            if std > 0:
                z = (col - col.mean()) / std
            else:
                z = col * 0.0
            direction = directions.get(f, 1)
            scores[f] = z * direction

        # 等权平均
        alpha = scores.mean(axis=1).dropna()
        if len(alpha) < top_n:
            continue

        # Top-N 等权
        top_codes: list[str] = alpha.nlargest(top_n).index.tolist()
        weight = 1.0 / len(top_codes)
        targets[rd] = {c: weight for c in top_codes}

    logger.info(
        "Phase A信号生成完成: %d个调仓日, %d个因子, Top-%d",
        len(targets), len(factor_names), top_n,
    )
    return targets
