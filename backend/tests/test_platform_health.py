"""MVP 4.1 batch 2.2 unit tests — HealthReport + safe_check + aggregate_status."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from qm_platform.observability import (
    HealthReport,
    aggregate_status,
    safe_check,
)


def _now() -> datetime:
    return datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC)


# ─────────────────────────── HealthReport ───────────────────────────


def test_health_report_default_factories():
    r = HealthReport(framework="x", status="ok")
    assert r.framework == "x"
    assert r.status == "ok"
    assert r.message == ""
    assert r.last_check_ts.tzinfo == UTC  # 默认 utcnow tz-aware
    assert r.details == {}


def test_health_report_to_dict_json_friendly():
    r = HealthReport(
        framework="alert_router",
        status="degraded",
        message="dingtalk slow",
        last_check_ts=_now(),
        details={"latency_ms": 800},
    )
    d = r.to_dict()
    assert d["framework"] == "alert_router"
    assert d["status"] == "degraded"
    assert d["message"] == "dingtalk slow"
    assert d["last_check_ts"] == "2026-04-29T12:00:00+00:00"
    assert d["details"] == {"latency_ms": 800}


def test_health_report_frozen_immutable():
    r = HealthReport(framework="x", status="ok")
    with pytest.raises((AttributeError, TypeError)):
        r.status = "down"  # type: ignore[misc]


def test_health_report_details_is_mapping_proxy_immutable():
    """reviewer P2 采纳: frozen=True 不防 details 字典 in-place mutation, 必包 MappingProxyType."""
    r = HealthReport(
        framework="x",
        status="ok",
        details={"latency_ms": 12, "queue": 0},
    )
    # 读取仍正常
    assert r.details["latency_ms"] == 12
    # 写入必 raise (MappingProxyType 不允许)
    with pytest.raises(TypeError, match="does not support item assignment"):
        r.details["injected"] = "bad"  # type: ignore[index]


def test_health_report_details_caller_mutation_after_construct_isolated():
    """caller 修改原 dict 不影响已构造 HealthReport.details (浅拷贝隔离)."""
    original = {"k": "v"}
    r = HealthReport(framework="x", status="ok", details=original)
    original["k"] = "MUTATED"  # caller 改原 dict
    assert r.details["k"] == "v", "原 dict 修改不应影响 HealthReport (浅拷贝)"


# ─────────────────────────── safe_check ───────────────────────────


def test_safe_check_returns_report_unchanged():
    expected = HealthReport(framework="x", status="ok", message="all good")

    def good_check() -> HealthReport:
        return expected

    r = safe_check("x", good_check)
    assert r == expected


def test_safe_check_catches_exception_returns_down():
    """check_fn raise → 不传播, 返 status=down + traceback 摘要 (防 /health 自杀)."""

    def boom() -> HealthReport:
        raise RuntimeError("PG conn refused")

    r = safe_check("alert_router", boom)
    assert r.status == "down"
    assert r.framework == "alert_router"
    assert "RuntimeError" in r.message
    assert "PG conn refused" in r.message
    assert "traceback" in r.details
    assert "RuntimeError" in r.details["traceback"]


def test_safe_check_rejects_non_health_report_return():
    """check_fn 返非 HealthReport 视为 bug, 转 down (类型验证)."""

    def bad_return() -> HealthReport:  # 实际返 str
        return "ok"  # type: ignore[return-value]

    r = safe_check("x", bad_return)
    assert r.status == "down"
    assert "TypeError" in r.message


# ─────────────────────────── aggregate_status ───────────────────────────


def test_aggregate_all_ok():
    reports = [
        HealthReport(framework="a", status="ok"),
        HealthReport(framework="b", status="ok"),
    ]
    assert aggregate_status(reports) == "ok"


def test_aggregate_one_degraded():
    reports = [
        HealthReport(framework="a", status="ok"),
        HealthReport(framework="b", status="degraded"),
        HealthReport(framework="c", status="ok"),
    ]
    assert aggregate_status(reports) == "degraded"


def test_aggregate_one_down_overrides_degraded():
    reports = [
        HealthReport(framework="a", status="degraded"),
        HealthReport(framework="b", status="down"),
        HealthReport(framework="c", status="ok"),
    ]
    assert aggregate_status(reports) == "down"


def test_aggregate_empty_returns_down():
    """空列表 = 0 Framework 注册, 视为 down (异常状态)."""
    assert aggregate_status([]) == "down"
