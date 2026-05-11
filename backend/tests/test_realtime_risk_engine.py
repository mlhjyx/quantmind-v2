"""L1 unit tests for RealtimeRiskEngine (S5 sub-PR 5a).

覆盖:
  - 规则注册: 正常/重复/cadence 无效
  - Tick/5min/15min 评估分组
  - 规则内部异常不阻塞其他规则
  - registered_rules 属性
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.qm_platform._types import Severity
from backend.qm_platform.risk import RiskContext, RiskRule, RuleResult
from backend.qm_platform.risk.realtime import RealtimeRiskEngine


class _DummyTickRule(RiskRule):
    """Tick 级测试规则 — 始终触发."""
    rule_id: str = "dummy_tick"
    severity: Severity = Severity.P0
    action: str = "alert_only"

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        return [RuleResult(
            rule_id=self.rule_id,
            code="600519.SH",
            shares=0,
            reason="dummy tick trigger",
            metrics={"val": 1.0},
        )]


class _Dummy5minRule(RiskRule):
    """5min 级测试规则 — 始终触发."""
    rule_id: str = "dummy_5min"
    severity: Severity = Severity.P1
    action: str = "alert_only"

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        return [RuleResult(
            rule_id=self.rule_id,
            code="",
            shares=0,
            reason="dummy 5min trigger",
            metrics={"val": 2.0},
        )]


class _DummyNoTriggerRule(RiskRule):
    """从不触发的规则."""
    rule_id: str = "dummy_noop"
    severity: Severity = Severity.INFO
    action: str = "bypass"

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        return []


class _CrashRule(RiskRule):
    """evaluate 抛异常的规则 — 测试隔离."""
    rule_id: str = "dummy_crash"
    severity: Severity = Severity.P0
    action: str = "alert_only"

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        msg = "intentional crash"
        raise RuntimeError(msg)


def _make_context(realtime: dict | None = None) -> RiskContext:
    return RiskContext(
        strategy_id="test-s5-engine",
        execution_mode="paper",
        timestamp=datetime.now(UTC),
        positions=(),
        portfolio_nav=1_000_000.0,
        prev_close_nav=1_000_000.0,
        realtime=realtime,
    )


class TestRealtimeRiskEngine:
    def test_register_and_evaluate_tick(self):
        engine = RealtimeRiskEngine()
        engine.register(_DummyTickRule(), cadence="tick")
        results = engine.on_tick(_make_context())
        assert len(results) == 1
        assert results[0].rule_id == "dummy_tick"

    def test_register_and_evaluate_5min(self):
        engine = RealtimeRiskEngine()
        engine.register(_Dummy5minRule(), cadence="5min")
        results = engine.on_5min_beat(_make_context())
        assert len(results) == 1
        assert results[0].rule_id == "dummy_5min"

    def test_cadence_isolation(self):
        """Tick 规则不在 5min 评估中出现."""
        engine = RealtimeRiskEngine()
        engine.register(_DummyTickRule(), cadence="tick")
        assert engine.on_5min_beat(_make_context()) == []

    def test_no_trigger_returns_empty(self):
        engine = RealtimeRiskEngine()
        engine.register(_DummyNoTriggerRule(), cadence="tick")
        assert engine.on_tick(_make_context()) == []

    def test_rule_crash_does_not_block_others(self):
        engine = RealtimeRiskEngine()
        engine.register(_CrashRule(), cadence="tick")
        engine.register(_DummyTickRule(), cadence="tick")
        results = engine.on_tick(_make_context())
        assert len(results) == 1  # only _DummyTickRule results
        assert results[0].rule_id == "dummy_tick"

    def test_duplicate_registration_raises(self):
        engine = RealtimeRiskEngine()
        engine.register(_DummyTickRule(), cadence="tick")
        with pytest.raises(ValueError, match="already registered"):
            engine.register(_DummyTickRule(), cadence="tick")

    def test_invalid_cadence_raises(self):
        engine = RealtimeRiskEngine()
        with pytest.raises(ValueError, match="Invalid cadence"):
            engine.register(_DummyTickRule(), cadence="hourly")  # type: ignore[arg-type]

    def test_registered_rules_property(self):
        engine = RealtimeRiskEngine()
        engine.register(_DummyTickRule(), cadence="tick")
        engine.register(_Dummy5minRule(), cadence="5min")
        rules = engine.registered_rules
        assert "dummy_tick" in rules["tick"]
        assert "dummy_5min" in rules["5min"]
        assert rules["15min"] == []

    def test_15min_cadence(self):
        engine = RealtimeRiskEngine()
        engine.register(_Dummy5minRule(), cadence="15min")
        results = engine.on_15min_beat(_make_context())
        assert len(results) == 1

    def test_on_tick_with_realtime_context(self):
        engine = RealtimeRiskEngine()
        engine.register(_DummyTickRule(), cadence="tick")
        ctx = _make_context(realtime={"600519.SH": {"price": 100.0}})
        results = engine.on_tick(ctx)
        assert len(results) == 1
