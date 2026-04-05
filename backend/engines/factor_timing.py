"""因子择时权重调整引擎 — 纯计算无IO。

设计文档: DESIGN_V5 §4.6 基于滚动IC动态调整因子权重。

权重调整逻辑:
- timing_score = IC_MA20 / IC_MA60
- timing_score > 1.0: 近期IC强于长期，权重上调（最高1.5x）
- timing_score < 1.0: 近期IC弱于长期，权重下调（最低0.5x）
- clip到[0.5, 1.5]，然后归一化

与C3集成:
- decay_level=L2 → 强制weight=0.5x
- decay_level=L3 → 强制weight=0

Engine层规范: 纯计算，无IO，无数据库访问。
"""


import numpy as np
import pandas as pd
import structlog

from engines.factor_decay import DecayLevel, DecayResult

logger = structlog.get_logger(__name__)

# ────────────────── 配置常量 ──────────────────

TIMING_WEIGHT_MIN = 0.5   # 最低权重倍数
TIMING_WEIGHT_MAX = 1.5   # 最高权重倍数
MIN_IC_DAYS = 60           # IC数据最少天数（不够则不调整）


def calc_timing_score(ic_daily: pd.Series) -> float | None:
    """计算单因子的timing_score = IC_MA20 / IC_MA60。

    Args:
        ic_daily: 日频IC时序（已排序），取绝对值衡量预测能力。

    Returns:
        timing_score，IC数据不足时返回None。
    """
    abs_ic = ic_daily.abs()

    if len(abs_ic) < MIN_IC_DAYS:
        return None

    ic_ma20 = float(abs_ic.iloc[-20:].mean())
    ic_ma60 = float(abs_ic.iloc[-60:].mean())

    if ic_ma60 < 1e-12:
        return None

    return ic_ma20 / ic_ma60


def calc_timing_weights(
    factor_names: list[str],
    ic_data: dict[str, pd.Series],
    base_weights: dict[str, float] | None = None,
    decay_results: list[DecayResult] | None = None,
) -> dict[str, float]:
    """计算择时调整后的因子权重。

    Args:
        factor_names: 因子名称列表。
        ic_data: {factor_name: ic_daily_series}，IC日频时序。
        base_weights: 基础权重（默认等权）。
        decay_results: C3衰减检测结果（用于L2/L3强制覆盖）。

    Returns:
        归一化后的权重 {factor_name: weight}，和为1.0。
    """
    n = len(factor_names)
    if n == 0:
        return {}

    # 默认等权
    if base_weights is None:
        base_weights = {f: 1.0 / n for f in factor_names}

    # 构建decay_level索引
    decay_map: dict[str, DecayLevel] = {}
    if decay_results:
        for dr in decay_results:
            decay_map[dr.factor_name] = dr.decay_level

    adjusted: dict[str, float] = {}

    for fname in factor_names:
        bw = base_weights.get(fname, 1.0 / n)
        decay_level = decay_map.get(fname, DecayLevel.L0)

        # L3退役: 权重=0
        if decay_level == DecayLevel.L3:
            adjusted[fname] = 0.0
            continue

        # 计算timing_score
        ic_series = ic_data.get(fname)
        if ic_series is None or ic_series.empty:
            # 无IC数据: 保持基础权重
            multiplier = 1.0
        else:
            score = calc_timing_score(ic_series)
            if score is None:
                # 数据不足: 保持基础权重
                multiplier = 1.0
            else:
                # 线性映射到[0.5, 1.5]
                multiplier = float(np.clip(score, TIMING_WEIGHT_MIN, TIMING_WEIGHT_MAX))

        # L2强制: 权重上限0.5x
        if decay_level == DecayLevel.L2:
            multiplier = min(multiplier, 0.5)

        adjusted[fname] = bw * multiplier

    # 归一化
    total = sum(adjusted.values())
    if total < 1e-12:
        # 所有因子都被L3退役，返回等权（安全fallback）
        logger.warning("[Timing] 所有因子权重为0（全部L3退役），回退到等权")
        return {f: 1.0 / n for f in factor_names}

    return {f: w / total for f, w in adjusted.items()}


def compare_timing_vs_equal(
    factor_names: list[str],
    ic_data: dict[str, pd.Series],
    decay_results: list[DecayResult] | None = None,
) -> dict:
    """对比择时权重 vs 等权。

    Args:
        factor_names: 因子名称列表。
        ic_data: {factor_name: ic_daily_series}。
        decay_results: C3衰减检测结果。

    Returns:
        对比报告dict。
    """
    n = len(factor_names)
    equal_weights = {f: 1.0 / n for f in factor_names}
    timing_weights = calc_timing_weights(
        factor_names, ic_data, decay_results=decay_results,
    )

    # timing scores
    scores = {}
    for fname in factor_names:
        ic_series = ic_data.get(fname)
        if ic_series is not None and not ic_series.empty:
            scores[fname] = calc_timing_score(ic_series)
        else:
            scores[fname] = None

    report = {
        "factor_names": factor_names,
        "equal_weights": equal_weights,
        "timing_weights": timing_weights,
        "timing_scores": scores,
        "weight_changes": {},
    }

    for fname in factor_names:
        ew = equal_weights[fname]
        tw = timing_weights[fname]
        change_pct = (tw / ew - 1) * 100 if ew > 0 else 0.0
        report["weight_changes"][fname] = {
            "equal": round(ew, 4),
            "timing": round(tw, 4),
            "change_pct": round(change_pct, 1),
            "timing_score": scores.get(fname),
        }

    return report
