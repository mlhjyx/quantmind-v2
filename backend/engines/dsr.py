"""Deflated Sharpe Ratio (DSR) — 多策略测试Sharpe膨胀校正。

Bailey & Lopez de Prado (2014) 提出的DSR校正方法,
用于检测观测到的Sharpe是否可能是多重检验(data snooping)的产物。

核心思想: 从N个策略/配置中选最优, 观测到的Sharpe被膨胀。
DSR通过考虑试验次数、偏度、峰度来校正这种膨胀。

公式:
  E[max(SR)] ~ sigma_SR * ((1-gamma)*Phi^{-1}(1-1/N) + gamma*Phi^{-1}(1-1/(N*e)))
  gamma ~ 0.5772 (Euler-Mascheroni常数)

  DSR = Phi((SR_observed - E[max(SR)]) / sigma_SR_adj)

  其中 sigma_SR_adj 考虑了非正态性:
  sigma_SR_adj = sqrt((1 - skew*SR/3 + (kurt-3)*SR^2/4) / T)

解读:
  DSR > 0.95: 有统计显著性(Sharpe大概率不是运气)
  DSR 0.5-0.95: 可疑(可能部分来自过拟合)
  DSR < 0.5: 不显著(大概率是过拟合)

参考: DEV_BACKTEST_ENGINE.md S4.12.1
遵循CLAUDE.md: 类型注解 + Google style docstring(中文)
"""

from __future__ import annotations

import logging
import math

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)

# Euler-Mascheroni 常数
_EULER_MASCHERONI = 0.5772156649015329


def _sharpe_std(
    observed_sharpe: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
) -> float:
    """计算Sharpe比率的标准差估计。

    考虑非正态收益分布对Sharpe标准差的影响。
    Lo (2002) 修正公式:
      Var(SR) = (1 - skew*SR/3 + (kurt-3)*SR^2/4) / T

    Args:
        observed_sharpe: 观测到的Sharpe比率(年化前的, 即日频Sharpe)。
        n_observations: 观测数(回测天数)。
        skewness: 日收益率偏度。
        kurtosis: 日收益率峰度(非超额峰度, 正态为3)。

    Returns:
        Sharpe比率的标准差。
    """
    sr = observed_sharpe
    t = max(n_observations, 1)

    # 非正态修正项
    variance_numerator = (
        1.0
        - skewness * sr / 3.0
        + (kurtosis - 3.0) * sr * sr / 4.0
    )
    # 确保方差非负(极端偏度/峰度时可能出现)
    variance_numerator = max(variance_numerator, 1e-12)

    return math.sqrt(variance_numerator / t)


def _expected_max_sharpe(
    n_trials: int,
    sharpe_std: float,
) -> float:
    """计算多重检验下Sharpe最大值的期望。

    Bonferroni近似:
      E[max(SR)] ~ sigma_SR * ((1-gamma)*Phi^{-1}(1-1/N) + gamma*Phi^{-1}(1-1/(N*e)))

    Args:
        n_trials: 测试过的策略/配置数量。
        sharpe_std: Sharpe比率的标准差。

    Returns:
        期望的最大Sharpe值。
    """
    if n_trials <= 1:
        return 0.0

    gamma = _EULER_MASCHERONI
    n = float(n_trials)

    # 避免ppf(1.0)返回inf
    p1 = min(1.0 - 1.0 / n, 1.0 - 1e-15)
    p2 = min(1.0 - 1.0 / (n * math.e), 1.0 - 1e-15)

    e_max = sharpe_std * (
        (1.0 - gamma) * float(norm.ppf(p1))
        + gamma * float(norm.ppf(p2))
    )
    return e_max


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_observations: int,
    skewness: float,
    kurtosis: float,
    sharpe_std: float | None = None,
) -> float:
    """计算Deflated Sharpe Ratio。

    考虑多重检验偏差和非正态收益分布, 校正观测到的Sharpe比率。
    DSR < 0.95 表示Sharpe可能是过拟合产物。

    算法步骤:
      1. 估计Sharpe标准差(考虑偏度和峰度)
      2. 计算多重检验下期望最大Sharpe
      3. 计算标准化z值并转为概率

    Args:
        observed_sharpe: 观测到的Sharpe比率(年化后)。
            通常从回测结果直接获取。
        n_trials: 测试过的策略/配置数量。
            包括grid search的所有参数组合、Walk-Forward的窗口数等。
            n_trials越大, DSR越低(惩罚越重)。
        n_observations: 回测天数(交易日数)。
            观测数越多, DSR越高(样本越充分)。
        skewness: 日收益率偏度。
            负偏(左尾肥)降低DSR, 正偏提高DSR。
        kurtosis: 日收益率峰度(非超额峰度, 正态分布为3)。
            尖峰(>3)降低DSR。
        sharpe_std: Sharpe标准差, 可选。
            如果提供(例如从bootstrap得到), 直接使用。
            如果不提供, 用Lo(2002)公式从偏度/峰度估计。

    Returns:
        DSR值, 范围[0, 1]。
        > 0.95: 统计显著, Sharpe大概率不是运气。
        0.5-0.95: 可疑, 可能部分来自过拟合。
        < 0.5: 不显著, 大概率是过拟合。

    Raises:
        ValueError: n_trials < 1 或 n_observations < 2。

    Examples:
        >>> dsr = deflated_sharpe_ratio(
        ...     observed_sharpe=1.2,
        ...     n_trials=50,
        ...     n_observations=1000,
        ...     skewness=-0.3,
        ...     kurtosis=4.5,
        ... )
        >>> dsr > 0.5
        True
    """
    if n_trials < 1:
        raise ValueError(f"n_trials必须>=1, 收到: {n_trials}")
    if n_observations < 2:
        raise ValueError(f"n_observations必须>=2, 收到: {n_observations}")

    # 特殊情况: 只有1次试验, 无需校正
    if n_trials == 1:
        logger.debug("n_trials=1, DSR退化为原始Sharpe的显著性检验")
        # 单次试验: 直接检验Sharpe是否显著>0
        sr_std = sharpe_std or _sharpe_std(
            observed_sharpe, n_observations, skewness, kurtosis
        )
        if sr_std < 1e-12:
            return 1.0 if observed_sharpe > 0 else 0.0
        z = observed_sharpe / sr_std
        return float(norm.cdf(z))

    # 将年化Sharpe转为日频(用于标准差估计)
    # 年化Sharpe = 日频Sharpe * sqrt(244)
    sr_daily = observed_sharpe / np.sqrt(244)

    # 1. 估计Sharpe标准差
    if sharpe_std is not None:
        sigma_sr = sharpe_std
    else:
        sigma_sr = _sharpe_std(sr_daily, n_observations, skewness, kurtosis)

    if sigma_sr < 1e-12:
        logger.warning("Sharpe标准差过小(%.2e), DSR可能不准确", sigma_sr)
        return 1.0 if observed_sharpe > 0 else 0.0

    # 2. 期望最大Sharpe (日频)
    e_max_sr = _expected_max_sharpe(n_trials, sigma_sr)

    # 3. DSR = Phi((SR_observed - E[max(SR)]) / sigma_SR)
    # 注意: 这里用日频Sharpe比较
    z = (sr_daily - e_max_sr) / sigma_sr
    dsr = float(norm.cdf(z))

    logger.debug(
        "DSR计算: SR_obs=%.4f(日频), E[max(SR)]=%.4f, sigma_SR=%.4f, z=%.4f, DSR=%.4f",
        sr_daily, e_max_sr, sigma_sr, z, dsr,
    )

    return dsr


def interpret_dsr(dsr: float) -> str:
    """解读DSR值, 返回中文说明。

    Args:
        dsr: Deflated Sharpe Ratio值。

    Returns:
        中文解读文本。
    """
    if dsr > 0.95:
        return "统计显著: Sharpe大概率不是运气"
    elif dsr > 0.5:
        return "可疑: 可能部分来自过拟合"
    else:
        return "不显著: 大概率是过拟合"
