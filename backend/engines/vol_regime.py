"""波动率Regime缩放 — 根据CSI300当前波动率调整仓位比例。

Sprint 1.1设计：高波动时缩减仓位，低波动时加仓，clip[0.5, 2.0]。

计算逻辑:
1. 用对数收益率（log returns）计算波动率，而非pct_change
   （对数收益率更接近正态分布，对极端值更稳健）
2. baseline_vol = 5年历史中位数（不用均值，对极端波动期更稳健）
3. scale = baseline_vol / current_vol，clip到[0.5, 2.0]
   - 当前波动率 > baseline → scale < 1 → 降仓
   - 当前波动率 < baseline → scale > 1 → 加仓
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Sprint 1.1: 仓位缩放区间 [0.5, 2.0]
VOL_REGIME_CLIP_LOW: float = 0.5
VOL_REGIME_CLIP_HIGH: float = 2.0

# 当前波动率计算窗口（交易日）
VOL_WINDOW: int = 20


def calc_vol_regime(
    csi300_closes: pd.Series,
    baseline_vol: Optional[float] = None,
) -> float:
    """根据CSI300波动率计算仓位缩放系数。

    Args:
        csi300_closes: CSI300收盘价序列（需至少21个数据点以计算20日波动率）。
                       传入时间升序排列（index从旧到新）。
        baseline_vol: 基准波动率（年化）。若为None，自动使用输入序列的
                      20日滚动波动率的中位数作为baseline。
                      生产环境建议预计算5年历史中位数后作为固定参数传入。

    Returns:
        仓位缩放系数，clip到 [VOL_REGIME_CLIP_LOW, VOL_REGIME_CLIP_HIGH]。
        1.0表示不调整，<1.0表示降仓，>1.0表示加仓。
        当数据不足（<21条）时返回1.0（不调整）。

    Example:
        >>> closes = pd.Series([...])  # 5年CSI300日收盘价
        >>> baseline = calc_baseline_vol(closes)   # 预计算基准
        >>> scale = calc_vol_regime(closes, baseline_vol=baseline)
    """
    if len(csi300_closes) < VOL_WINDOW + 1:
        logger.warning(
            f"[VolRegime] 数据点不足({len(csi300_closes)})，需≥{VOL_WINDOW + 1}，返回1.0"
        )
        return 1.0

    # 对数收益率（比pct_change更稳健）
    log_returns = np.log(csi300_closes / csi300_closes.shift(1)).dropna()

    if len(log_returns) < VOL_WINDOW:
        logger.warning("[VolRegime] 对数收益率序列不足，返回1.0")
        return 1.0

    # 当前20日波动率（日波动率，年化=×sqrt(244)）
    current_vol_daily = float(log_returns.iloc[-VOL_WINDOW:].std())
    current_vol = current_vol_daily * np.sqrt(244)

    if current_vol < 1e-12:
        logger.warning("[VolRegime] 当前波动率接近0，返回1.0")
        return 1.0

    # 基准波动率
    if baseline_vol is None:
        # 滚动20日波动率序列的中位数（5年历史数据中位数）
        rolling_vols = log_returns.rolling(VOL_WINDOW).std().dropna()
        if len(rolling_vols) == 0:
            logger.warning("[VolRegime] 无法计算滚动波动率，返回1.0")
            return 1.0
        baseline_vol = float(rolling_vols.median()) * np.sqrt(244)
        logger.debug(
            f"[VolRegime] 自动baseline_vol(中位数)={baseline_vol:.4f}"
        )

    if baseline_vol < 1e-12:
        logger.warning("[VolRegime] baseline_vol接近0，返回1.0")
        return 1.0

    # scale = baseline / current: 波动率高→scale小→降仓
    scale_raw = baseline_vol / current_vol
    scale = float(np.clip(scale_raw, VOL_REGIME_CLIP_LOW, VOL_REGIME_CLIP_HIGH))

    logger.info(
        f"[VolRegime] current_vol={current_vol:.4f}, baseline_vol={baseline_vol:.4f}, "
        f"scale_raw={scale_raw:.4f} → clipped={scale:.4f}"
    )

    return scale


def calc_baseline_vol(csi300_closes: pd.Series) -> float:
    """预计算基准波动率（5年历史20日滚动波动率中位数）。

    在生产环境中，每季度或每年重新计算一次，然后固定传给calc_vol_regime。

    Args:
        csi300_closes: CSI300收盘价历史序列（建议5年，约1220个交易日）。

    Returns:
        年化基准波动率。数据不足时返回0.0。
    """
    if len(csi300_closes) < VOL_WINDOW + 1:
        return 0.0

    log_returns = np.log(csi300_closes / csi300_closes.shift(1)).dropna()
    rolling_vols = log_returns.rolling(VOL_WINDOW).std().dropna()

    if len(rolling_vols) == 0:
        return 0.0

    return float(rolling_vols.median()) * np.sqrt(244)
