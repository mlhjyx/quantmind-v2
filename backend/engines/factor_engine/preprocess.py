"""Factor engine — preprocess pipeline (MAD → fill → neutralize → zscore → clip).

Split from factor_engine.py at Phase C C1 (2026-04-16) for 铁律 31 compliance.
All functions in this module are pure: no DB access, no filesystem IO.
Input: cross-section Series, industry classification, ln_mcap. Output: Series.

铁律 4 (因子预处理顺序不可改):
    MAD去极值 → 缺失值填充 → WLS中性化 → zscore → clip(±3)

Source lineage: backend/engines/factor_engine.py lines 1056-1243 (Phase C C1 cut).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# ============================================================
# 预处理管道 (CLAUDE.md 强制顺序: MAD → fill → neutralize → zscore)
# ============================================================


def preprocess_mad(series: pd.Series, n_mad: float = 5.0) -> pd.Series:
    """Step 1: MAD去极值。

    将超出 median ± n_mad × MAD 的值截断到边界。

    Args:
        series: 单因子截面值 (一个trade_date的全部股票)
        n_mad: MAD倍数, 默认5倍

    Returns:
        去极值后的Series
    """
    median = series.median()
    mad = (series - median).abs().median()
    if mad < 1e-12:
        return series
    upper = median + n_mad * mad
    lower = median - n_mad * mad
    return series.clip(lower=lower, upper=upper)


def preprocess_fill(
    series: pd.Series,
    industry: pd.Series,
) -> pd.Series:
    """Step 2: 缺失值填充。

    先用行业中位数填充, 再用0填充剩余。

    Args:
        series: 单因子截面值
        industry: 对应的行业分类

    Returns:
        填充后的Series (无NaN)
    """
    # 行业中位数填充
    industry_median = series.groupby(industry).transform("median")
    filled = series.fillna(industry_median)
    # 剩余NaN用0填充
    filled = filled.fillna(0.0)
    return filled


def preprocess_neutralize(
    series: pd.Series,
    ln_mcap: pd.Series,
    industry: pd.Series,
) -> pd.Series:
    """Step 3: WLS中性化 — 加权最小二乘回归掉市值 + 行业。

    模型: factor = alpha + beta1 × ln_mcap + Σ(beta_i × industry_dummy) + residual
    权重: w_i = √market_cap_i = √exp(ln_mcap_i)（大市值股票权重更高）
    WLS变换: 用 √w_i 乘以 X 和 y，转化为等价的OLS问题后 lstsq 求解。
    残差: 用原始(未加权)的 y - X @ beta 计算，保留经济含义。

    设计文档: DESIGN_V5 §4.4 — WLS(√market_cap加权)回归。

    Args:
        series: 单因子截面值 (已去极值+填充)
        ln_mcap: 对数市值（ln(流通市值)）
        industry: 行业分类

    Returns:
        中性化后的残差 Series，无效样本保持 NaN
    """
    valid_mask = series.notna() & ln_mcap.notna() & industry.notna()
    if valid_mask.sum() < 30:
        logger.warning("中性化样本不足30，跳过中性化")
        return series

    y = series[valid_mask].values
    mcap_vals = ln_mcap[valid_mask].values

    # 构建设计矩阵 X: [intercept, ln_mcap, industry_dummies]
    mcap_col = mcap_vals.reshape(-1, 1)
    ind_dummies = pd.get_dummies(industry[valid_mask], drop_first=True).values
    x_mat = np.column_stack([np.ones(len(y)), mcap_col, ind_dummies])  # noqa: N806

    # WLS权重: w_i = √market_cap = √exp(ln_mcap)
    # WLS → OLS变换: 用 √w_i 乘以 X 和 y
    weights = np.sqrt(np.exp(mcap_vals))  # w_i = √market_cap
    w_sqrt = np.sqrt(weights)  # √w_i = market_cap^(1/4)
    # 归一化避免数值溢出 (不影响回归结果)
    w_sqrt = w_sqrt / w_sqrt.mean()

    xw = x_mat * w_sqrt[:, np.newaxis]
    yw = y * w_sqrt

    try:
        # WLS: beta = (X'WX)^-1 X'Wy，等价OLS on (Xw, yw)
        beta = np.linalg.lstsq(xw, yw, rcond=None)[0]
        # 残差使用原始空间（非加权），保留经济含义
        residual = y - x_mat @ beta

        result = series.copy()
        result[valid_mask] = residual
        result[~valid_mask] = np.nan
        return result
    except np.linalg.LinAlgError:
        logger.warning("WLS中性化回归失败(矩阵奇异)，返回原值")
        return series


def preprocess_zscore(series: pd.Series) -> pd.Series:
    """Step 4: zscore标准化。

    (x - mean) / std, 标准差为0时返回全0。
    """
    mean = series.mean()
    std = series.std()
    if std < 1e-12:
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def preprocess_pipeline(
    factor_series: pd.Series,
    ln_mcap: pd.Series,
    industry: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """完整预处理管道。

    返回 (raw_value, neutral_value)。
    neutral_value = 经过 MAD→fill→neutralize(WLS)→zscore→clip(±3) 全部5步处理后的值。

    步骤:
      1. MAD去极值 (5σ)
      2. 缺失值填充 (行业中位数→0)
      3. WLS中性化 (行业+市值加权回归，w=√market_cap)
      4. zscore标准化
      5. clip(±3): 截断|z|>3的极端值 (DESIGN_V5 §4.4)

    Args:
        factor_series: 原始因子截面值
        ln_mcap: 对数市值
        industry: 行业分类

    Returns:
        (raw_value, neutral_value) 两个Series
    """
    raw = factor_series.copy()

    # Step 1: MAD去极值 (5σ)
    step1 = preprocess_mad(raw)
    # Step 2: 缺失值填充
    step2 = preprocess_fill(step1, industry)
    # Step 3: WLS中性化 (行业+市值加权回归)
    step3 = preprocess_neutralize(step2, ln_mcap, industry)
    # Step 4: zscore
    step4 = preprocess_zscore(step3)
    # Step 5: clip ±3σ (截断zscore极端值)
    step5 = step4.clip(lower=-3.0, upper=3.0)

    return raw, step5


# ============================================================
# IC计算 (legacy — ic_calculator.py 是项目统一 IC 入口, 本函数仅保留兼容性)
# 铁律 19: 生产决策必须走 engines/ic_calculator.py compute_ic_series
# ============================================================


def calc_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    method: str = "spearman",
) -> float:
    """计算单日单因子的IC (Information Coefficient)。

    [Legacy] 本函数仅保留兼容, 新代码请用 engines/ic_calculator.py 统一入口.

    Args:
        factor_values: 因子截面值 (index=code)
        forward_returns: 前向超额收益 (index=code)
        method: 'spearman'(rank IC) 或 'pearson'

    Returns:
        IC值 (float)
    """
    # 对齐index
    common = factor_values.dropna().index.intersection(forward_returns.dropna().index)
    if len(common) < 30:
        return np.nan

    f = factor_values.loc[common]
    r = forward_returns.loc[common]

    if method == "spearman":
        return f.rank().corr(r.rank())
    else:
        return f.corr(r)
