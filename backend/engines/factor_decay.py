"""因子衰减3级自动处置引擎 — 纯计算无IO。

设计文档: DESIGN_V5 §4.5 因子IC衰减分级处置。

三级处置规则:
- L0 正常: IC_MA20 >= IC_MA60 × 0.8
- L1 告警: IC_MA20 < IC_MA60 × 0.8（近期IC显著弱于长期均值）
  → P2告警推送，不改权重
- L2 自动降权: IC_MA20 < IC_MA60 × 0.5（近期IC严重衰减）
  → 权重自动降至0.5x
- L3 退役: IC_MA20 < 0.01 连续60个交易日（因子基本失效）
  → 状态从active改为candidate，权重降至0

Engine层规范: 纯计算，无IO，无数据库访问。
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


class DecayLevel(StrEnum):
    """因子衰减等级。"""
    L0 = "L0"  # 正常
    L1 = "L1"  # 告警
    L2 = "L2"  # 自动降权
    L3 = "L3"  # 退役


@dataclass
class DecayResult:
    """单因子衰减检测结果。"""
    factor_name: str
    decay_level: DecayLevel
    ic_ma20: float
    ic_ma60: float
    consecutive_low_days: int  # IC < 0.01 的连续天数
    reason: str

    # L1/L2阈值（供日志/告警使用）
    l1_threshold: float  # IC_MA60 × 0.8
    l2_threshold: float  # IC_MA60 × 0.5

    @property
    def weight_multiplier(self) -> float:
        """该衰减等级对应的权重倍数。"""
        if self.decay_level == DecayLevel.L3:
            return 0.0
        if self.decay_level == DecayLevel.L2:
            return 0.5
        return 1.0

    @property
    def target_status(self) -> str:
        """该衰减等级对应的factor_registry目标状态。"""
        return {
            DecayLevel.L0: "active",
            DecayLevel.L1: "active",   # L1只告警，不改状态
            DecayLevel.L2: "warning",
            DecayLevel.L3: "candidate",
        }[self.decay_level]


# ────────────────── 配置常量 ──────────────────

L1_RATIO = 0.8    # IC_MA20 < IC_MA60 × 0.8 → L1
L2_RATIO = 0.5    # IC_MA20 < IC_MA60 × 0.5 → L2
L3_IC_THRESHOLD = 0.01  # IC绝对值阈值
L3_CONSECUTIVE_DAYS = 60  # 连续低IC天数


def classify_decay_level(
    ic_ma20: float,
    ic_ma60: float,
    consecutive_low_days: int,
) -> DecayLevel:
    """根据IC移动均值判定衰减等级。

    Args:
        ic_ma20: 20日IC移动均值（绝对值）。
        ic_ma60: 60日IC移动均值（绝对值）。
        consecutive_low_days: IC < 0.01 的连续交易日数。

    Returns:
        衰减等级。
    """
    # L3优先: 连续60天IC < 0.01
    if consecutive_low_days >= L3_CONSECUTIVE_DAYS:
        return DecayLevel.L3

    # IC_MA60 <= 0 时无法计算比值，用绝对值判断
    if ic_ma60 <= 1e-12:
        if ic_ma20 < L3_IC_THRESHOLD:
            return DecayLevel.L2
        return DecayLevel.L0

    # L2: IC_MA20 < IC_MA60 × 0.5
    if ic_ma20 < ic_ma60 * L2_RATIO:
        return DecayLevel.L2

    # L1: IC_MA20 < IC_MA60 × 0.8
    if ic_ma20 < ic_ma60 * L1_RATIO:
        return DecayLevel.L1

    return DecayLevel.L0


def calc_consecutive_low_ic_days(
    ic_series: pd.Series,
    threshold: float = L3_IC_THRESHOLD,
) -> int:
    """计算IC绝对值连续低于阈值的天数（从最近一天往前数）。

    Args:
        ic_series: IC时序（index=trade_date, values=IC值），需已排序。
        threshold: IC绝对值阈值。

    Returns:
        从最近一天开始连续低于阈值的天数。
    """
    if ic_series.empty:
        return 0

    # 从最后一天往前看
    abs_ic = ic_series.abs()
    count = 0
    for val in reversed(abs_ic.values):
        if np.isnan(val) or val < threshold:
            count += 1
        else:
            break
    return count


def check_factor_decay(
    factor_name: str,
    ic_daily: pd.Series,
) -> DecayResult:
    """检测单因子衰减等级。

    Args:
        factor_name: 因子名称。
        ic_daily: 日频IC时序（index=trade_date, values=IC值），已排序。

    Returns:
        DecayResult。
    """
    # 计算IC移动均值（用绝对值，衡量因子预测能力强弱）
    abs_ic = ic_daily.abs()

    if len(abs_ic) >= 20:
        ic_ma20 = float(abs_ic.iloc[-20:].mean())
    else:
        ic_ma20 = float(abs_ic.mean()) if not abs_ic.empty else 0.0

    if len(abs_ic) >= 60:
        ic_ma60 = float(abs_ic.iloc[-60:].mean())
    else:
        ic_ma60 = float(abs_ic.mean()) if not abs_ic.empty else 0.0

    # 连续低IC天数
    consecutive_low = calc_consecutive_low_ic_days(ic_daily)

    # 分级
    level = classify_decay_level(ic_ma20, ic_ma60, consecutive_low)

    # 阈值
    l1_thresh = ic_ma60 * L1_RATIO
    l2_thresh = ic_ma60 * L2_RATIO

    # 原因说明
    reasons = {
        DecayLevel.L0: "正常",
        DecayLevel.L1: (
            f"IC_MA20({ic_ma20:.4f}) < IC_MA60×0.8({l1_thresh:.4f})"
        ),
        DecayLevel.L2: (
            f"IC_MA20({ic_ma20:.4f}) < IC_MA60×0.5({l2_thresh:.4f})"
        ),
        DecayLevel.L3: (
            f"IC<{L3_IC_THRESHOLD}连续{consecutive_low}天(>={L3_CONSECUTIVE_DAYS}天)"
        ),
    }

    return DecayResult(
        factor_name=factor_name,
        decay_level=level,
        ic_ma20=round(ic_ma20, 6),
        ic_ma60=round(ic_ma60, 6),
        consecutive_low_days=consecutive_low,
        reason=reasons[level],
        l1_threshold=round(l1_thresh, 6),
        l2_threshold=round(l2_thresh, 6),
    )


def check_all_factors_decay(
    factor_ic_data: dict[str, pd.Series],
) -> list[DecayResult]:
    """批量检测所有因子的衰减等级。

    Args:
        factor_ic_data: {factor_name: ic_daily_series}

    Returns:
        DecayResult列表。
    """
    results = []
    for fname, ic_series in sorted(factor_ic_data.items()):
        result = check_factor_decay(fname, ic_series)
        results.append(result)
        if result.decay_level != DecayLevel.L0:
            logger.warning(
                "[Decay] %s: %s — %s",
                fname, result.decay_level.value, result.reason,
            )
    return results
