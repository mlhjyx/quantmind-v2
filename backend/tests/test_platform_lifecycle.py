"""MVP 1.3c Platform Lifecycle 单测 — 纯规则 + PlatformLifecycleMonitor.

覆盖:
  - 常量值 (对齐 DEV_AI_EVOLUTION V2.1 §3.1)
  - count_days_below_critical 边界
  - evaluate_transition 6 条状态机规则
  - PlatformLifecycleMonitor.evaluate_all 集成 (MagicMock registry + ic_reader)
  - CRITICAL 不落 DB (to_status 保 WARNING + metrics[critical_alert]=True)

执行:
  pytest backend/tests/test_platform_lifecycle.py -v
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.factor.interface import FactorStatus, TransitionDecision
from backend.qm_platform.factor.lifecycle import (
    CRITICAL_PERSISTENCE_DAYS,
    CRITICAL_RATIO,
    MIN_ABS_IC_MA60,
    PERSISTENCE_LOOKBACK_DAYS,
    WARNING_RATIO,
    PlatformLifecycleMonitor,
    count_days_below_critical,
    evaluate_transition,
)

# ---------- helpers ----------


@dataclass
class _StubMeta:
    """FactorMeta 替身 — Day 2 get_active concrete 前用, 只用 name + status."""

    name: str
    status: FactorStatus


# ---------- 常量 ----------


def test_constants_match_spec() -> None:
    """常量值对齐 DEV_AI_EVOLUTION V2.1 §3.1."""
    assert WARNING_RATIO == 0.8
    assert CRITICAL_RATIO == 0.5
    assert CRITICAL_PERSISTENCE_DAYS == 20
    assert MIN_ABS_IC_MA60 == 1e-6
    assert PERSISTENCE_LOOKBACK_DAYS == 30
    assert PERSISTENCE_LOOKBACK_DAYS >= CRITICAL_PERSISTENCE_DAYS  # 覆盖冲突


# ---------- count_days_below_critical ----------


def test_count_days_empty() -> None:
    assert count_days_below_critical([]) == 0


def test_count_days_all_below() -> None:
    ratios = [0.3, 0.4, 0.2, 0.1, 0.45]
    assert count_days_below_critical(ratios) == 5


def test_count_days_mixed_breaks_at_first_above() -> None:
    # 从最新往回数, 遇到 ratio >= CRITICAL_RATIO 立即停
    ratios = [0.4, 0.9, 0.3, 0.2, 0.1]  # 最新=0.1 连续 3 → 遇 0.9 break
    assert count_days_below_critical(ratios) == 3


def test_count_days_respects_lookback_limit() -> None:
    ratios = [0.3] * 50
    # 默认 lookback=30, 截尾 30 个
    assert count_days_below_critical(ratios) == 30
    assert count_days_below_critical(ratios, lookback_days=10) == 10


# ---------- evaluate_transition: ACTIVE → WARNING ----------


def test_active_stays_when_ratio_ok() -> None:
    d = evaluate_transition("f1", FactorStatus.ACTIVE, ic_ma20=0.05, ic_ma60=0.05)
    assert d is None  # ratio=1.0 >= 0.8


def test_active_degrades_to_warning() -> None:
    d = evaluate_transition("f1", FactorStatus.ACTIVE, ic_ma20=0.02, ic_ma60=0.05)
    assert d is not None
    assert d.from_status == FactorStatus.ACTIVE
    assert d.to_status == FactorStatus.WARNING
    assert d.metrics["ratio"] == pytest.approx(0.4)
    assert "< 0.8" in d.reason


# ---------- evaluate_transition: WARNING ----------


def test_warning_recovers_to_active() -> None:
    d = evaluate_transition("f1", FactorStatus.WARNING, ic_ma20=0.05, ic_ma60=0.05)
    assert d is not None
    assert d.from_status == FactorStatus.WARNING
    assert d.to_status == FactorStatus.ACTIVE
    assert "恢复" in d.reason


def test_warning_critical_alert_but_no_db_transition() -> None:
    """MVP 1.3c D1: CRITICAL 不落 DB — to_status 保 WARNING + metrics[critical_alert]=True."""
    d = evaluate_transition(
        "f1",
        FactorStatus.WARNING,
        ic_ma20=0.01,
        ic_ma60=0.05,  # ratio=0.2 < 0.5
        days_below_critical=CRITICAL_PERSISTENCE_DAYS,  # 20 天触发
    )
    assert d is not None
    assert d.from_status == FactorStatus.WARNING
    assert d.to_status == FactorStatus.WARNING  # 不落 DB
    assert d.metrics["critical_alert"] is True
    assert "L2 人确认" in d.reason


def test_warning_below_critical_but_persistence_insufficient() -> None:
    d = evaluate_transition(
        "f1",
        FactorStatus.WARNING,
        ic_ma20=0.01,
        ic_ma60=0.05,
        days_below_critical=CRITICAL_PERSISTENCE_DAYS - 1,  # 19 天, 不触发
    )
    assert d is None  # 未触发 critical_alert 也未恢复


# ---------- evaluate_transition: 边界 / 无效输入 ----------


def test_none_ic_returns_none() -> None:
    assert evaluate_transition("f1", FactorStatus.ACTIVE, None, 0.05) is None
    assert evaluate_transition("f1", FactorStatus.ACTIVE, 0.05, None) is None


def test_near_zero_ic_ma60_returns_none() -> None:
    # 分母近零, 比率不稳定
    assert evaluate_transition("f1", FactorStatus.ACTIVE, 0.05, MIN_ABS_IC_MA60 / 10) is None


def test_non_active_non_warning_no_transition() -> None:
    """CANDIDATE / DEPRECATED / RETIRED / TESTING / INVALIDATED 不自动转换."""
    for s in (
        FactorStatus.CANDIDATE,
        FactorStatus.TESTING,
        FactorStatus.DEPRECATED,
        FactorStatus.INVALIDATED,
        FactorStatus.RETIRED,
    ):
        d = evaluate_transition("f1", s, ic_ma20=0.01, ic_ma60=0.05)
        assert d is None, f"状态 {s} 不应触发自动转换"


# ---------- PlatformLifecycleMonitor ----------


def _make_ic_tail(ic_ma20: float, ic_ma60: float, n: int = 30) -> list[dict]:
    """构造 n 天 IC tail, 值全部相同 (静态 ratio)."""
    return [{"trade_date": f"2026-01-{i+1:02d}", "ic_ma20": ic_ma20, "ic_ma60": ic_ma60} for i in range(n)]


def test_monitor_evaluate_all_empty_active() -> None:
    registry = MagicMock()
    registry.get_active.return_value = []
    monitor = PlatformLifecycleMonitor(registry, ic_reader=lambda n, d: [])
    assert monitor.evaluate_all() == []


def test_monitor_returns_active_to_warning_decision() -> None:
    meta = _StubMeta(name="f1", status=FactorStatus.ACTIVE)
    registry = MagicMock()
    registry.get_active.return_value = [meta]

    def ic_reader(name: str, lookback: int) -> list[dict]:
        assert name == "f1"
        return _make_ic_tail(0.02, 0.05)  # ratio=0.4 < 0.8 → WARNING

    monitor = PlatformLifecycleMonitor(registry, ic_reader)
    decisions = monitor.evaluate_all()
    assert len(decisions) == 1
    d = decisions[0]
    assert isinstance(d, TransitionDecision)
    assert d.factor_name == "f1"
    assert d.to_status == FactorStatus.WARNING


def test_monitor_skips_factor_without_ic_data() -> None:
    meta = _StubMeta(name="f_no_data", status=FactorStatus.ACTIVE)
    registry = MagicMock()
    registry.get_active.return_value = [meta]
    monitor = PlatformLifecycleMonitor(registry, ic_reader=lambda n, d: [])
    assert monitor.evaluate_all() == []


def test_monitor_critical_alert_propagated() -> None:
    meta = _StubMeta(name="f_decay", status=FactorStatus.WARNING)
    registry = MagicMock()
    registry.get_active.return_value = [meta]

    # 30 天连续 ratio=0.2 (< 0.5) → days_below=30 ≥ 20 → critical_alert
    def ic_reader(name: str, lookback: int) -> list[dict]:
        return _make_ic_tail(0.01, 0.05, n=30)

    monitor = PlatformLifecycleMonitor(registry, ic_reader)
    decisions = monitor.evaluate_all()
    assert len(decisions) == 1
    d = decisions[0]
    assert d.to_status == FactorStatus.WARNING  # 不落 DB
    assert d.metrics["critical_alert"] is True
    assert d.metrics["days_below_critical"] >= CRITICAL_PERSISTENCE_DAYS


def test_monitor_handles_string_status_from_db() -> None:
    """兼容: 若 registry 返的 meta.status 是字符串 (非 Enum), 自动转 Enum."""

    @dataclass
    class _StrStatusMeta:
        name: str
        status: str

    meta = _StrStatusMeta(name="f1", status="active")  # 字符串, 非 Enum
    registry = MagicMock()
    registry.get_active.return_value = [meta]
    monitor = PlatformLifecycleMonitor(
        registry, ic_reader=lambda n, d: _make_ic_tail(0.02, 0.05)
    )
    decisions = monitor.evaluate_all()
    assert len(decisions) == 1
    assert decisions[0].from_status == FactorStatus.ACTIVE


def test_monitor_returns_interface_transition_decision() -> None:
    """Blueprint 锚定: evaluate_all 必须返 interface.TransitionDecision (不是 engines 版)."""
    meta = _StubMeta(name="f1", status=FactorStatus.ACTIVE)
    registry = MagicMock()
    registry.get_active.return_value = [meta]
    monitor = PlatformLifecycleMonitor(
        registry, ic_reader=lambda n, d: _make_ic_tail(0.02, 0.05)
    )
    d = monitor.evaluate_all()[0]
    assert isinstance(d, TransitionDecision)
    # interface 版 dataclass 字段: factor_name, from_status, to_status, reason, metrics
    assert hasattr(d, "factor_name")
    assert hasattr(d, "metrics")
    assert isinstance(d.metrics, dict)
    # interface 版没有 engines 版 ic_ma20 / ic_ma60 / ratio 硬字段 (全在 metrics)
    assert not hasattr(d, "ic_ma20")
    assert not hasattr(d, "ratio")


def test_monitor_multiple_factors_independent_decisions() -> None:
    """多因子并行: 每个独立判定."""
    metas = [
        _StubMeta(name="f_active", status=FactorStatus.ACTIVE),
        _StubMeta(name="f_warning_ok", status=FactorStatus.WARNING),
        _StubMeta(name="f_retired", status=FactorStatus.RETIRED),
    ]
    registry = MagicMock()
    registry.get_active.return_value = metas

    def ic_reader(name: str, lookback: int) -> list[dict]:
        if name == "f_active":
            return _make_ic_tail(0.02, 0.05)  # → WARNING
        if name == "f_warning_ok":
            return _make_ic_tail(0.05, 0.05)  # 恢复 → ACTIVE
        return _make_ic_tail(0.01, 0.05)  # RETIRED 不触发

    monitor = PlatformLifecycleMonitor(registry, ic_reader)
    decisions = monitor.evaluate_all()
    assert len(decisions) == 2
    by_name = {d.factor_name: d for d in decisions}
    assert by_name["f_active"].to_status == FactorStatus.WARNING
    assert by_name["f_warning_ok"].to_status == FactorStatus.ACTIVE
    assert "f_retired" not in by_name  # RETIRED 不转换


# 锚点: MVP 1.1 isolation — lifecycle.py 自身 __dict__ 不含 engines reference
def test_import_lifecycle_no_engines_import() -> None:
    """Platform 严格隔离 — lifecycle.py 依赖的模块不含 backend.engines.

    主 AST 扫描在 test_platform_skeleton::test_platform_strict_isolation 覆盖.
    本测试做运行时 smoke: 通过 __module__ 反查 lifecycle 依赖的符号来源.
    """
    import backend.qm_platform.factor.lifecycle as lc

    src_names = {v.__module__ for v in vars(lc).values() if hasattr(v, "__module__")}
    for mod in src_names:
        assert not mod.startswith("backend.engines"), (
            f"lifecycle.py 依赖了 {mod} — 违反 MVP 1.1 严格隔离"
        )
        assert not mod.startswith("engines."), (
            f"lifecycle.py 依赖了 {mod} — 违反 MVP 1.1 严格隔离"
        )
