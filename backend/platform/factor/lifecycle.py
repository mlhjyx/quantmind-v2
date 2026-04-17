"""MVP 1.3c Framework #2 Factor — PlatformLifecycleMonitor concrete 实现.

纯规则 (copy from engines/factor_lifecycle.py — Platform 不 import engines 保严格
隔离, MVP 1.1 test_platform_strict_isolation 要求). MVP A 的 engines 版保留不动,
老 scripts/factor_lifecycle_monitor.py 继续走 engines 路径, Platform 版是平行新路径.

状态语义 (interface.FactorStatus 7 值):
  - ACTIVE → WARNING   当 |IC_MA20|/|IC_MA60| < 0.8
  - WARNING → ACTIVE   当 ratio ≥ 0.8 (恢复)
  - WARNING → WARNING + metrics[critical_alert]=True
                        当 ratio < 0.5 持续 20 天 (MVP 1.3c D1:
                        CRITICAL 不落 DB, 仅 publish 事件给 L2 人确认)

  CANDIDATE / TESTING / DEPRECATED / INVALIDATED / RETIRED 不自动转换
  (需 onboarding 流程 / L2 人确认).

关联铁律:
  - 11: IC 可追溯
  - 31: Engine 纯计算 (本模块纯规则函数 evaluate_transition 无 IO)
  - 33: 禁 silent failure (异常向上 raise, 调用方决定)

Usage:
    from backend.platform.factor.registry import DBFactorRegistry
    from backend.platform.factor.lifecycle import PlatformLifecycleMonitor

    def ic_reader(factor_name: str, lookback: int) -> list[dict]:
        # 调用方提供: 查 factor_ic_history 返 tail [{"trade_date","ic_ma20","ic_ma60"},...]
        ...

    monitor = PlatformLifecycleMonitor(registry=DBFactorRegistry(dal), ic_reader=ic_reader)
    for decision in monitor.evaluate_all():
        print(decision.factor_name, decision.from_status, decision.to_status, decision.reason)
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from backend.platform.factor.interface import (
    FactorLifecycleMonitor,
    FactorStatus,
    TransitionDecision,
)

if TYPE_CHECKING:
    from backend.platform.factor.interface import FactorRegistry


# ---------- 纯规则常量 (对齐 DEV_AI_EVOLUTION V2.1 §3.1) ----------

WARNING_RATIO: float = 0.8
"""|IC_MA20|/|IC_MA60| < 0.8 → ACTIVE → WARNING (轻度衰减)."""

CRITICAL_RATIO: float = 0.5
"""|IC_MA20|/|IC_MA60| < 0.5 → critical 阈值 (需持续 20 天触发 critical_alert)."""

CRITICAL_PERSISTENCE_DAYS: int = 20
"""连续低于 CRITICAL_RATIO 超过此天数 → critical_alert."""

MIN_ABS_IC_MA60: float = 1e-6
"""基线 IC 绝对值 < 此阈值则比率无意义 (分母近零)."""

PERSISTENCE_LOOKBACK_DAYS: int = 30
"""回溯窗口 (大于 CRITICAL_PERSISTENCE_DAYS 20 天, 覆盖冲突安全)."""


# ---------- 纯规则函数 ----------


def count_days_below_critical(
    ic_ratios: list[float],
    lookback_days: int = PERSISTENCE_LOOKBACK_DAYS,
) -> int:
    """计算最近 lookback_days 天中连续 ratio < CRITICAL_RATIO 的天数 (从最新往回数).

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


def evaluate_transition(
    factor_name: str,
    current_status: FactorStatus,
    ic_ma20: float | None,
    ic_ma60: float | None,
    days_below_critical: int = 0,
) -> TransitionDecision | None:
    """判定单因子的状态转换 (纯规则, 无 IO).

    Args:
      factor_name: 因子名.
      current_status: 当前 FactorStatus (interface 版).
      ic_ma20: 最新 20 日 IC 移动平均.
      ic_ma60: 最新 60 日 IC 移动平均.
      days_below_critical: 持续性天数 (≥ 0).

    Returns:
      TransitionDecision 如需转换 (或触发 critical_alert 的 WARNING→WARNING),
      None 如无变化或数据不足.
    """
    if ic_ma20 is None or ic_ma60 is None:
        return None
    abs_ma60 = abs(float(ic_ma60))
    if abs_ma60 < MIN_ABS_IC_MA60:
        return None  # 分母近零, 比率不稳定

    ratio = abs(float(ic_ma20)) / abs_ma60
    common_metrics: dict[str, Any] = {
        "ic_ma20": float(ic_ma20),
        "ic_ma60": float(ic_ma60),
        "ratio": ratio,
        "days_below_critical": days_below_critical,
    }

    if current_status == FactorStatus.ACTIVE:
        if ratio < WARNING_RATIO:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=FactorStatus.ACTIVE,
                to_status=FactorStatus.WARNING,
                reason=f"|IC_MA20|/|IC_MA60|={ratio:.3f} < {WARNING_RATIO}",
                metrics=common_metrics,
            )
        return None

    if current_status == FactorStatus.WARNING:
        # 持续 critical: 保 DB status=WARNING, metrics 带 critical_alert=True
        if ratio < CRITICAL_RATIO and days_below_critical >= CRITICAL_PERSISTENCE_DAYS:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=FactorStatus.WARNING,
                to_status=FactorStatus.WARNING,  # 不落 DB 转换, 仅事件
                reason=(
                    f"|IC_MA20|/|IC_MA60|={ratio:.3f} < {CRITICAL_RATIO} "
                    f"持续 {days_below_critical} 天 — L2 人确认 (MVP 1.3c D1)"
                ),
                metrics={**common_metrics, "critical_alert": True},
            )
        # 恢复
        if ratio >= WARNING_RATIO:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=FactorStatus.WARNING,
                to_status=FactorStatus.ACTIVE,
                reason=f"|IC_MA20|/|IC_MA60|={ratio:.3f} ≥ {WARNING_RATIO} (恢复)",
                metrics=common_metrics,
            )
        return None

    # CANDIDATE / TESTING / DEPRECATED / INVALIDATED / RETIRED: 不自动转换
    return None


# ---------- PlatformLifecycleMonitor concrete ----------


# 类型别名: ic_reader 返 list of dict with keys: trade_date, ic_ma20, ic_ma60
ICReaderFn = Callable[[str, int], list[dict[str, Any]]]


class PlatformLifecycleMonitor(FactorLifecycleMonitor):
    """Framework #2 Factor — 周期性巡检生命周期 (Platform concrete).

    用法 (Celery Beat 周五 19:00 触发 via orchestration 脚本):
        monitor = PlatformLifecycleMonitor(registry, ic_reader)
        decisions = monitor.evaluate_all()
        for d in decisions:
            # 调用方负责 apply_transition + publish event (铁律 32: Service 不 commit)
            ...

    Args:
      registry: FactorRegistry 实例 (需实现 get_active). 典型 DBFactorRegistry.
      ic_reader: Callable[(factor_name, lookback_days), list[row]], row 需含
        ic_ma20 / ic_ma60 keys (float or None). 从旧到新排序.
      lookback_days: 持续性判定窗口, 默认 PERSISTENCE_LOOKBACK_DAYS (30).
    """

    def __init__(
        self,
        registry: FactorRegistry,
        ic_reader: ICReaderFn,
        *,
        lookback_days: int = PERSISTENCE_LOOKBACK_DAYS,
    ) -> None:
        self._registry = registry
        self._ic_reader = ic_reader
        self._lookback = lookback_days

    def evaluate_all(self) -> list[TransitionDecision]:
        """扫描所有 ACTIVE / WARNING 因子, 返回状态转换建议."""
        decisions: list[TransitionDecision] = []
        # 注: MVP 1.3c Day 2 实现 get_active 后此调用返 FactorMeta list
        for meta in self._registry.get_active():
            decision = self._evaluate_one(meta)
            if decision is not None:
                decisions.append(decision)
        return decisions

    def _evaluate_one(self, meta: Any) -> TransitionDecision | None:
        """对单因子执行: 拉 IC tail → 计算 ratios + days_below → 调 evaluate_transition."""
        tail = self._ic_reader(meta.name, self._lookback)
        if not tail:
            return None

        latest = tail[-1]
        ic_ma20 = latest.get("ic_ma20")
        ic_ma60 = latest.get("ic_ma60")
        if ic_ma20 is None or ic_ma60 is None:
            return None

        # 构建 ratios 序列 (从旧到新, 无效值记 1.0 使 count 不触发)
        ratios: list[float] = []
        for r in tail:
            m20 = r.get("ic_ma20")
            m60 = r.get("ic_ma60")
            if m20 is None or m60 is None or abs(float(m60)) < MIN_ABS_IC_MA60:
                ratios.append(1.0)
            else:
                ratios.append(abs(float(m20)) / abs(float(m60)))

        days_below = count_days_below_critical(ratios, self._lookback)

        # meta.status 是 FactorStatus 实例 (interface 版 Enum)
        status = meta.status
        if not isinstance(status, FactorStatus):
            # 兼容字符串: get_active 若返字典类型, 转成 enum
            try:
                status = FactorStatus(status)
            except (ValueError, TypeError):
                return None

        return evaluate_transition(
            factor_name=meta.name,
            current_status=status,
            ic_ma20=float(ic_ma20),
            ic_ma60=float(ic_ma60),
            days_below_critical=days_below,
        )


__all__ = [
    "PlatformLifecycleMonitor",
    "evaluate_transition",
    "count_days_below_critical",
    "WARNING_RATIO",
    "CRITICAL_RATIO",
    "CRITICAL_PERSISTENCE_DAYS",
    "MIN_ABS_IC_MA60",
    "PERSISTENCE_LOOKBACK_DAYS",
    "ICReaderFn",
]
