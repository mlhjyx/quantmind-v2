"""金融数学工具函数。

集中管理 IC、Sharpe、MDD 等指标计算。
引擎层 engines/metrics.py 有完整实现，此处提供轻量级便捷函数供 Service 层使用。

使用:
    from app.utils.math_utils import calc_sharpe, calc_mdd, calc_ic
"""

from __future__ import annotations

import math

import pandas as pd


def calc_sharpe(returns: pd.Series | list[float], rf: float = 0.0, annualize: int = 252) -> float:
    """计算年化Sharpe比率。

    Args:
        returns: 日收益率序列。
        rf: 日无风险利率，默认0。
        annualize: 年化因子，A股252个交易日。

    Returns:
        年化Sharpe比率。无数据或标准差为0时返回0。
    """
    if isinstance(returns, list):
        returns = pd.Series(returns)
    excess = returns - rf
    if len(excess) < 2 or excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * math.sqrt(annualize))


def calc_mdd(nav_series: pd.Series | list[float]) -> float:
    """计算最大回撤（负值表示）。

    Args:
        nav_series: 净值序列。

    Returns:
        最大回撤（负值，如 -0.15 表示 15% 回撤）。
    """
    if isinstance(nav_series, list):
        nav_series = pd.Series(nav_series)
    if len(nav_series) < 2:
        return 0.0
    peak = nav_series.cummax()
    drawdown = (nav_series - peak) / peak
    return float(drawdown.min())


def calc_ic(factor_values: pd.Series, forward_returns: pd.Series) -> float:
    """计算信息系数（Spearman rank IC）。

    Args:
        factor_values: 因子截面值。
        forward_returns: 未来收益率。

    Returns:
        Spearman相关系数。数据不足返回NaN。
    """
    mask = factor_values.notna() & forward_returns.notna()
    fv = pd.Series(factor_values[mask], dtype=float)
    fr = pd.Series(forward_returns[mask], dtype=float)
    if len(fv) < 10:
        return float("nan")
    return float(fv.rank().corr(fr.rank()))


def calc_annual_return(nav_series: pd.Series | list[float], trading_days: int = 252) -> float:
    """计算年化收益率。

    Args:
        nav_series: 净值序列。
        trading_days: 年交易日数。

    Returns:
        年化收益率。
    """
    if isinstance(nav_series, list):
        nav_series = pd.Series(nav_series)
    if len(nav_series) < 2:
        return 0.0
    total_return = nav_series.iloc[-1] / nav_series.iloc[0]
    n_days = len(nav_series)
    return float(total_return ** (trading_days / n_days) - 1)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """安全除法，分母为0时返回default。"""
    if denominator == 0 or not math.isfinite(denominator):
        return default
    result = numerator / denominator
    return result if math.isfinite(result) else default
