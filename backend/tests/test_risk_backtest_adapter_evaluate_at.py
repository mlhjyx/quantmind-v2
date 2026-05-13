"""RiskBacktestAdapter.evaluate_at — TB-1a full evaluator tests.

Plan v0.2 §A TB-1 sub-PR T1.5b...wait, TB-1a sediment. Tests cover:
- evaluate_at cadence dispatch (tick / 5min / 15min boundary detection)
- dedup per (timestamp, code, rule_id) uniqueness contract (V3 §11.4 line 1298)
- 纯函数契约 audit (verify_pure_function_contract method)
- register_all_realtime_rules helper (10 rules per ADR-029 amend)
- 铁律 41 timezone enforcement (evaluate_at raise on naive timestamp)
- reset() clears _evaluated_keys

沿用 sub-PR 5c stub test_risk_backtest_adapter.py 体例 + extend for TB-1a evaluator.

关联:
- V3 §11.4 (RiskBacktestAdapter pure function evaluate_at contract)
- ADR-029 (10 RealtimeRiskRule cumulative)
- ADR-064 (Plan v0.2 5 决议 lock — D3=b 2 关键窗口 sustained)
- ADR-066 候选 (TB-1a sediment 时机 决议)
- LL-159 (CC self silent drift family + 4-step preflight SOP sustained)
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.qm_platform.risk.backtest_adapter import RiskBacktestAdapter
from backend.qm_platform.risk.interface import Position, RiskContext, RuleResult
from backend.qm_platform.risk.realtime.engine import RealtimeRiskEngine


def _make_context(
    *,
    positions: tuple[Position, ...] = (),
    realtime: dict | None = None,
    timestamp: datetime | None = None,
) -> RiskContext:
    """Construct RiskContext for evaluator tests."""
    return RiskContext(
        strategy_id="test_tb_1a",
        execution_mode="paper",
        timestamp=timestamp or datetime.now(tz=UTC),
        positions=positions,
        portfolio_nav=1_000_000.0,
        prev_close_nav=1_000_000.0,
        realtime=realtime,
    )


class _StubRule:
    """Stub RiskRule for cadence dispatch testing."""

    def __init__(self, rule_id: str, *, results: list[RuleResult] | None = None):
        self.rule_id = rule_id
        self._results = results or []
        self.evaluate_count = 0

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        self.evaluate_count += 1
        return list(self._results)


# ---------- Cadence dispatch ----------


class TestEvaluateAtCadenceDispatch:
    """evaluate_at dispatches to engine cadence by timestamp boundary."""

    def test_tick_cadence_always_invoked(self):
        """tick cadence rules ALWAYS invoked regardless of timestamp."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        rule_tick = _StubRule("tick_rule_1")
        engine.register(rule_tick, cadence="tick")

        # Arbitrary timestamp (NOT 5min/15min boundary)
        ts = datetime(2024, 2, 5, 9, 37, 42, tzinfo=UTC)
        context = _make_context(timestamp=ts)

        adapter.evaluate_at(ts, context, engine)
        assert rule_tick.evaluate_count == 1

    def test_5min_boundary_triggers_5min_cadence(self):
        """5min boundary (minute % 5 == 0 + 0 sec) triggers 5min cadence."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        rule_tick = _StubRule("tick_rule")
        rule_5min = _StubRule("5min_rule")
        engine.register(rule_tick, cadence="tick")
        engine.register(rule_5min, cadence="5min")

        ts = datetime(2024, 2, 5, 9, 35, 0, tzinfo=UTC)  # 5min boundary
        context = _make_context(timestamp=ts)
        adapter.evaluate_at(ts, context, engine)

        assert rule_tick.evaluate_count == 1  # tick always
        assert rule_5min.evaluate_count == 1  # 5min triggered

    def test_5min_non_boundary_skips_5min_cadence(self):
        """Non-5min boundary skips 5min cadence."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        rule_5min = _StubRule("5min_rule")
        engine.register(rule_5min, cadence="5min")

        ts = datetime(2024, 2, 5, 9, 37, 42, tzinfo=UTC)  # NOT 5min boundary
        context = _make_context(timestamp=ts)
        adapter.evaluate_at(ts, context, engine)

        assert rule_5min.evaluate_count == 0  # 5min NOT triggered

    def test_15min_boundary_triggers_both_5min_and_15min(self):
        """15min boundary (minute % 15 == 0 + 0 sec) triggers BOTH 5min + 15min."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        rule_5min = _StubRule("5min_rule")
        rule_15min = _StubRule("15min_rule")
        engine.register(rule_5min, cadence="5min")
        engine.register(rule_15min, cadence="15min")

        ts = datetime(2024, 2, 5, 9, 45, 0, tzinfo=UTC)  # 15min boundary (also 5min)
        context = _make_context(timestamp=ts)
        adapter.evaluate_at(ts, context, engine)

        assert rule_5min.evaluate_count == 1  # 5min triggered (45 % 5 == 0)
        assert rule_15min.evaluate_count == 1  # 15min triggered (45 % 15 == 0)

    def test_15min_non_boundary_skips_15min_cadence(self):
        """Non-15min boundary skips 15min (even if it's a 5min boundary)."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        rule_15min = _StubRule("15min_rule")
        engine.register(rule_15min, cadence="15min")

        ts = datetime(2024, 2, 5, 9, 35, 0, tzinfo=UTC)  # 5min boundary, NOT 15min
        context = _make_context(timestamp=ts)
        adapter.evaluate_at(ts, context, engine)

        assert rule_15min.evaluate_count == 0


# ---------- Dedup contract (V3 §11.4 line 1298) ----------


class TestEvaluateAtDedupContract:
    """Dedup per (timestamp, code, rule_id) — backtest 重跑同一时段不重复触发."""

    def test_dedup_same_timestamp_returns_empty_on_replay(self):
        """Second evaluate_at at same timestamp returns empty list (dedup)."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        result = RuleResult(rule_id="r1", code="600519.SH", shares=100, reason="test", metrics={})
        rule = _StubRule("r1", results=[result])
        engine.register(rule, cadence="tick")

        ts = datetime(2024, 2, 5, 9, 30, 0, tzinfo=UTC)
        context = _make_context(timestamp=ts)

        first = adapter.evaluate_at(ts, context, engine)
        second = adapter.evaluate_at(ts, context, engine)

        assert len(first) == 1
        assert second == []  # 第二次 same timestamp → dedup empty

    def test_dedup_different_timestamps_allows_repeat(self):
        """Different timestamps + same (code, rule_id) → NOT deduped."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        result = RuleResult(rule_id="r1", code="600519.SH", shares=100, reason="test", metrics={})
        rule = _StubRule("r1", results=[result])
        engine.register(rule, cadence="tick")

        ts1 = datetime(2024, 2, 5, 9, 30, 0, tzinfo=UTC)
        ts2 = datetime(2024, 2, 5, 9, 31, 0, tzinfo=UTC)

        first = adapter.evaluate_at(ts1, _make_context(timestamp=ts1), engine)
        second = adapter.evaluate_at(ts2, _make_context(timestamp=ts2), engine)

        assert len(first) == 1
        assert len(second) == 1  # different ts → allowed

    def test_dedup_different_codes_at_same_timestamp_allowed(self):
        """Same timestamp + different code → NOT deduped (per-code uniqueness)."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        result1 = RuleResult(rule_id="r1", code="600519.SH", shares=100, reason="", metrics={})
        result2 = RuleResult(rule_id="r1", code="002415.SZ", shares=100, reason="", metrics={})
        rule = _StubRule("r1", results=[result1, result2])
        engine.register(rule, cadence="tick")

        ts = datetime(2024, 2, 5, 9, 30, 0, tzinfo=UTC)
        results = adapter.evaluate_at(ts, _make_context(timestamp=ts), engine)
        # Both results returned (different codes)
        assert len(results) == 2

    def test_dedup_evaluated_keys_count_grows(self):
        """evaluated_keys_count reflects dedup state size."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        result = RuleResult(rule_id="r1", code="600519.SH", shares=100, reason="", metrics={})
        rule = _StubRule("r1", results=[result])
        engine.register(rule, cadence="tick")

        assert adapter.evaluated_keys_count == 0
        ts1 = datetime(2024, 2, 5, 9, 30, 0, tzinfo=UTC)
        adapter.evaluate_at(ts1, _make_context(timestamp=ts1), engine)
        assert adapter.evaluated_keys_count == 1

        ts2 = datetime(2024, 2, 5, 9, 31, 0, tzinfo=UTC)
        adapter.evaluate_at(ts2, _make_context(timestamp=ts2), engine)
        assert adapter.evaluated_keys_count == 2

    def test_reset_clears_evaluated_keys(self):
        """reset() also clears _evaluated_keys for test isolation."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        result = RuleResult(rule_id="r1", code="600519.SH", shares=100, reason="", metrics={})
        rule = _StubRule("r1", results=[result])
        engine.register(rule, cadence="tick")

        ts = datetime(2024, 2, 5, 9, 30, 0, tzinfo=UTC)
        adapter.evaluate_at(ts, _make_context(timestamp=ts), engine)
        assert adapter.evaluated_keys_count == 1

        adapter.reset()
        assert adapter.evaluated_keys_count == 0
        # post-reset, same timestamp re-evaluates (NOT deduped)
        results = adapter.evaluate_at(ts, _make_context(timestamp=ts), engine)
        assert len(results) == 1


# ---------- 纯函数契约 audit (V3 §11.4) ----------


class TestPureFunctionContract:
    """verify_pure_function_contract: 0 broker / 0 INSERT / 0 alert during evaluate_at."""

    def test_evaluate_at_does_not_trigger_broker_or_alert(self):
        """evaluate_at on tick cadence rule does NOT touch sell_calls/alerts."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        result = RuleResult(rule_id="r1", code="600519.SH", shares=100, reason="", metrics={})
        rule = _StubRule("r1", results=[result])
        engine.register(rule, cadence="tick")

        before_sell = len(adapter.sell_calls)
        before_alert = len(adapter.alerts)
        ts = datetime(2024, 2, 5, 9, 30, 0, tzinfo=UTC)
        adapter.evaluate_at(ts, _make_context(timestamp=ts), engine)

        # 纯函数契约: 0 broker / 0 alert
        adapter.verify_pure_function_contract(
            before_sell_count=before_sell,
            before_alert_count=before_alert,
        )

    def test_verify_pure_function_contract_raises_on_sell(self):
        """verify_pure_function_contract raises AssertionError if sell occurred."""
        adapter = RiskBacktestAdapter()
        # Simulate sell call between before/after snapshot
        adapter.sell("600519.SH", 100, "test")
        with pytest.raises(AssertionError, match="pure-function contract violated.*sell_calls"):
            adapter.verify_pure_function_contract(
                before_sell_count=0, before_alert_count=0
            )

    def test_verify_pure_function_contract_raises_on_alert(self):
        """verify_pure_function_contract raises AssertionError if alert occurred."""
        adapter = RiskBacktestAdapter()
        adapter.send("test_title", "test_text", "warning")
        with pytest.raises(AssertionError, match="pure-function contract violated.*alerts"):
            adapter.verify_pure_function_contract(
                before_sell_count=0, before_alert_count=0
            )


# ---------- register_all_realtime_rules helper ----------


class TestRegisterAllRealtimeRules:
    """register_all_realtime_rules registers 10 RealtimeRiskRule per ADR-029."""

    def test_register_10_rules_correctly(self):
        """10 rules registered across tick / 5min / 15min cadences."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        adapter.register_all_realtime_rules(engine)

        registered = engine.registered_rules
        # tick: 4 rules
        assert len(registered["tick"]) == 4
        assert set(registered["tick"]) == {
            "limit_down_detection",
            "near_limit_down",
            "gap_down_open",
            "trailing_stop",
        }
        # 5min: 5 rules
        assert len(registered["5min"]) == 5
        # 15min: 1 rule
        assert len(registered["15min"]) == 1
        # Total: 10 rules
        total = sum(len(rules) for rules in registered.values())
        assert total == 10

    def test_register_duplicate_raises(self):
        """Calling register_all_realtime_rules twice on same engine raises (per engine fail-loud)."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        adapter.register_all_realtime_rules(engine)
        with pytest.raises(ValueError, match="already registered"):
            adapter.register_all_realtime_rules(engine)


# ---------- Edge cases ----------


class TestEvaluateAtEdgeCases:
    """Edge cases: naive timestamp / no rules / empty context."""

    def test_naive_timestamp_raises(self):
        """Naive (no tzinfo) timestamp raises ValueError per 铁律 41."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        naive_ts = datetime(2024, 2, 5, 9, 30, 0)  # NO tzinfo
        context = _make_context(timestamp=naive_ts.replace(tzinfo=UTC))
        with pytest.raises(ValueError, match="timezone-aware"):
            adapter.evaluate_at(naive_ts, context, engine)

    def test_empty_engine_returns_empty(self):
        """Engine with 0 rules returns empty list."""
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        ts = datetime(2024, 2, 5, 9, 30, 0, tzinfo=UTC)
        results = adapter.evaluate_at(ts, _make_context(timestamp=ts), engine)
        assert results == []
