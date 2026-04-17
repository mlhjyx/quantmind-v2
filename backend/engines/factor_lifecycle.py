"""因子生命周期状态转换 — 纯规则 (铁律 31).

根据 DEV_AI_EVOLUTION V2.1 §3.1 实现 L1-auto 状态转换:
    active  →  warning    (|IC_MA20| < |IC_MA60| × 0.8)
    warning →  critical   (|IC_MA20| < |IC_MA60| × 0.5 持续 20 天)
    warning →  active     (恢复: ratio 回到 ≥ 0.8)

critical → retired 需 L2 人确认, 本模块不包含.

状态值与 DDL factor_registry.status 对齐:
    candidate / active / warning / critical / retired

输入/输出均为原生 Python 类型, 可单元测试, 无 IO.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FactorStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    WARNING = "warning"
    CRITICAL = "critical"
    RETIRED = "retired"


# Thresholds per DEV_AI_EVOLUTION V2.1 §3.1
WARNING_RATIO = 0.8   # |IC_MA20|/|IC_MA60| < 0.8 → warning (轻度衰减)
CRITICAL_RATIO = 0.5  # |IC_MA20|/|IC_MA60| < 0.5 → critical (需持续)
CRITICAL_PERSISTENCE_DAYS = 20
MIN_ABS_IC_MA60 = 1e-6  # 基线 IC ≈ 0 时比率无意义


@dataclass(frozen=True)
class TransitionDecision:
    """状态转换决策."""

    factor_name: str
    from_status: str
    to_status: str
    reason: str
    ic_ma20: float
    ic_ma60: float
    ratio: float


def evaluate_transition(
    factor_name: str,
    current_status: str,
    ic_ma20: float | None,
    ic_ma60: float | None,
    days_below_critical: int = 0,
) -> TransitionDecision | None:
    """判定因子状态转换.

    Args:
        factor_name: 因子名.
        current_status: 当前状态 (candidate/active/warning/critical/retired).
        ic_ma20: 最新 20 日 IC 移动平均, None 表示无数据.
        ic_ma60: 最新 60 日 IC 移动平均, None 表示无数据.
        days_below_critical: 最近连续满足 |IC_MA20| < |IC_MA60|×0.5 的天数,
            用于 warning → critical 的持续性判定.

    Returns:
        TransitionDecision 如需转换, None 如无变化或数据不足.
    """
    if ic_ma20 is None or ic_ma60 is None:
        return None
    if abs(ic_ma60) < MIN_ABS_IC_MA60:
        return None  # 基线 IC ≈ 0, 比率不稳定

    ratio = abs(ic_ma20) / abs(ic_ma60)

    if current_status == FactorStatus.ACTIVE.value:
        if ratio < WARNING_RATIO:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=current_status,
                to_status=FactorStatus.WARNING.value,
                reason=f"|IC_MA20|/|IC_MA60|={ratio:.3f} < {WARNING_RATIO}",
                ic_ma20=ic_ma20,
                ic_ma60=ic_ma60,
                ratio=ratio,
            )
        return None

    if current_status == FactorStatus.WARNING.value:
        if ratio < CRITICAL_RATIO and days_below_critical >= CRITICAL_PERSISTENCE_DAYS:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=current_status,
                to_status=FactorStatus.CRITICAL.value,
                reason=(
                    f"|IC_MA20|/|IC_MA60|={ratio:.3f} < {CRITICAL_RATIO} "
                    f"持续 {days_below_critical} 天"
                ),
                ic_ma20=ic_ma20,
                ic_ma60=ic_ma60,
                ratio=ratio,
            )
        if ratio >= WARNING_RATIO:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=current_status,
                to_status=FactorStatus.ACTIVE.value,
                reason=f"|IC_MA20|/|IC_MA60|={ratio:.3f} ≥ {WARNING_RATIO} (恢复)",
                ic_ma20=ic_ma20,
                ic_ma60=ic_ma60,
                ratio=ratio,
            )
        return None

    # candidate / critical / retired: 不做 L1 自动转换
    return None


def count_days_below_critical(ic_ratios: list[float], lookback_days: int = 30) -> int:
    """计算最近 lookback_days 天中连续 ratio < CRITICAL_RATIO 的天数 (从最新往回数).

    用于 warning → critical 的持续性判定.

    Args:
        ic_ratios: 时间序列的 |IC_MA20|/|IC_MA60| 比率, 从旧到新.
        lookback_days: 最多回溯天数.

    Returns:
        从最新一天向前数, 连续满足 ratio < CRITICAL_RATIO 的天数.
    """
    if not ic_ratios:
        return 0
    tail = ic_ratios[-lookback_days:]
    count = 0
    for r in reversed(tail):
        if r < CRITICAL_RATIO:
            count += 1
        else:
            break
    return count
