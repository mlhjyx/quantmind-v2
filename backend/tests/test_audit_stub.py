"""Unit tests for backend.qm_platform.signal.audit.StubExecutionAuditTrail (MVP 3.3 batch 3).

测试覆盖:
  - __init__: log_level validation
  - record(): logger.info / record_count++ / event_type validation / payload validation
  - trace(): NotImplementedError with diagnostic message
  - record_count property
  - 集成: PlatformOrderRouter audit hook 注入 + record 调用 + 计数
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest

from backend.qm_platform._types import Signal
from backend.qm_platform.signal.audit import (
    AuditMissing,
    StubExecutionAuditTrail,
)
from backend.qm_platform.signal.router import PlatformOrderRouter

# ─── __init__ 验证 ────────────────────────────────────────────


class TestInit:
    def test_default_log_level_info(self):
        stub = StubExecutionAuditTrail()
        assert stub.record_count == 0

    def test_custom_log_level(self):
        stub = StubExecutionAuditTrail(log_level=logging.DEBUG)
        # 触发 record 验 DEBUG level 路径
        stub.record("test.event", {"x": 1})
        assert stub.record_count == 1

    def test_invalid_log_level_raises(self):
        with pytest.raises(ValueError, match="log_level 必须"):
            StubExecutionAuditTrail(log_level=999)


# ─── record() ────────────────────────────────────────────────


class TestRecord:
    def test_record_increments_count(self):
        stub = StubExecutionAuditTrail()
        assert stub.record_count == 0
        stub.record("signal.composed", {"strategy_id": "s1"})
        assert stub.record_count == 1
        stub.record("order.routed", {"order_id": "abc"})
        assert stub.record_count == 2

    def test_record_logs_event(self, caplog):
        stub = StubExecutionAuditTrail()
        with caplog.at_level(logging.INFO, logger="backend.qm_platform.signal.audit"):
            stub.record("order.routed", {"order_id": "a1b2", "strategy_id": "s1"})
        infos = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("audit.record" in r.message for r in infos)
        assert any("order.routed" in r.message for r in infos)

    def test_empty_event_type_raises(self):
        stub = StubExecutionAuditTrail()
        with pytest.raises(ValueError, match="event_type 必须是非空"):
            stub.record("", {"x": 1})

    def test_none_event_type_raises(self):
        stub = StubExecutionAuditTrail()
        with pytest.raises(ValueError, match="event_type 必须是非空"):
            stub.record(None, {"x": 1})  # type: ignore[arg-type]

    def test_non_string_event_type_raises(self):
        stub = StubExecutionAuditTrail()
        with pytest.raises(ValueError, match="event_type 必须是非空"):
            stub.record(123, {"x": 1})  # type: ignore[arg-type]

    def test_non_dict_payload_raises(self):
        stub = StubExecutionAuditTrail()
        with pytest.raises(ValueError, match="payload 必须是 dict"):
            stub.record("test.event", "not a dict")  # type: ignore[arg-type]


# ─── trace() ─────────────────────────────────────────────────


class TestTrace:
    def test_trace_raises_not_implemented(self):
        stub = StubExecutionAuditTrail()
        with pytest.raises(NotImplementedError, match="MVP 3.4"):
            stub.trace("fill-uuid-1")

    def test_trace_includes_fill_id_in_message(self):
        stub = StubExecutionAuditTrail()
        with pytest.raises(NotImplementedError, match="fill-abc"):
            stub.trace("fill-abc")


# ─── AuditMissing 异常 ────────────────────────────────────────


class TestAuditMissing:
    def test_audit_missing_is_runtime_error(self):
        assert issubclass(AuditMissing, RuntimeError)

    def test_audit_missing_can_be_raised(self):
        with pytest.raises(AuditMissing, match="链路中断"):
            raise AuditMissing("链路中断 test")


# ─── PlatformOrderRouter audit hook 集成 ─────────────────────


class TestRouterAuditHook:
    """验证 PlatformOrderRouter 通过 audit_trail DI 调用 stub.record('order.routed', ...).

    设计: audit_trail 默认 None → 不调 record (backward compat). 注入后每 Order 调一次.
    """

    def _signal(self, code="600519.SH", weight=0.10, price=100.0):
        return Signal(
            strategy_id="s1-uuid",
            code=code,
            target_weight=weight,
            score=1.0,
            trade_date=date(2026, 4, 27),
            metadata={"price": price},
        )

    def test_no_audit_trail_no_record(self):
        """audit_trail=None → router 不调 record, backward compat."""
        router = PlatformOrderRouter(audit_trail=None)
        sig = self._signal()
        orders = router.route(
            signals=[sig], current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert len(orders) == 1  # order 仍生成

    def test_audit_trail_records_per_order(self):
        """audit_trail 注入 → 每 Order 调 record 一次."""
        stub = StubExecutionAuditTrail()
        router = PlatformOrderRouter(audit_trail=stub)
        sigs = [
            self._signal(code="600519.SH", weight=0.10),
            self._signal(code="000001.SZ", weight=0.05),
        ]
        orders = router.route(
            signals=sigs, current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert len(orders) == 2
        # 2 orders 应触发 2 次 record
        assert stub.record_count == 2

    def test_audit_records_event_type_order_routed(self, caplog):
        """record event_type 必为 'order.routed'."""
        stub = StubExecutionAuditTrail()
        router = PlatformOrderRouter(audit_trail=stub)
        sig = self._signal()
        with caplog.at_level(logging.INFO, logger="backend.qm_platform.signal.audit"):
            router.route(
                signals=[sig], current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )
        infos = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("order.routed" in r.message for r in infos), (
            f"missing 'order.routed' log: {[r.message for r in infos]}"
        )

    def test_audit_skipped_for_no_op_signals(self):
        """delta=0 跳过 order 生成 → record 也不触发 (record 跟 Order 1:1)."""
        stub = StubExecutionAuditTrail()
        router = PlatformOrderRouter(audit_trail=stub)
        sig = self._signal(weight=0.10, price=100.0)
        # current = 1000 = target → delta=0, 跳过
        orders = router.route(
            signals=[sig],
            current_positions={"600519.SH": 1000},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert orders == []
        assert stub.record_count == 0  # 无 Order 无 record
