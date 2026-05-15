"""Tests for `backend.qm_platform.risk.realtime.rule_registry`.

V3 PT Cutover Plan v0.4 §A IC-1c WU-1: rule_registry is the SSOT for L1
rule set wiring (10 rules across tick/5min/15min cadences per ADR-029 §2.2).
Both `RiskBacktestAdapter.register_all_realtime_rules` (now a thin delegate)
and the forthcoming L1 production runner (IC-1c WU-2) import this function.

Test scope:
  - free function registers exactly 10 rules with correct cadence assignment
  - duplicate registration raises ValueError (engine fail-loud per 铁律 33)
  - rule_id set matches the canonical 10-rule contract
  - adapter delegate produces identical result as direct call (SSOT invariant)
"""

from __future__ import annotations

import pytest

from backend.qm_platform.risk.backtest_adapter import RiskBacktestAdapter
from backend.qm_platform.risk.realtime import (
    RealtimeRiskEngine,
    register_all_realtime_rules,
)

_CANONICAL_TICK_RULES = {
    "limit_down_detection",
    "near_limit_down",
    "gap_down_open",
    "trailing_stop",
}
_CANONICAL_5MIN_RULE_COUNT = 5
_CANONICAL_15MIN_RULE_COUNT = 1
_CANONICAL_TOTAL = 10


class TestRegisterAllRealtimeRules:
    """Free function `register_all_realtime_rules` — SSOT contract."""

    def test_register_10_rules_with_correct_cadence_map(self):
        """4 tick + 5 5min + 1 15min = 10 rules per ADR-029 §2.2."""
        engine = RealtimeRiskEngine()
        register_all_realtime_rules(engine)

        registered = engine.registered_rules
        assert len(registered["tick"]) == 4, (
            f"tick cadence: expected 4 rules, got {registered['tick']}"
        )
        assert set(registered["tick"]) == _CANONICAL_TICK_RULES, (
            f"tick rule_id set mismatch: {set(registered['tick'])} vs {_CANONICAL_TICK_RULES}"
        )
        assert len(registered["5min"]) == _CANONICAL_5MIN_RULE_COUNT
        assert len(registered["15min"]) == _CANONICAL_15MIN_RULE_COUNT

        total = sum(len(rules) for rules in registered.values())
        assert total == _CANONICAL_TOTAL

    def test_duplicate_registration_raises(self):
        """Re-registering on same engine raises ValueError (fail-loud per 铁律 33)."""
        engine = RealtimeRiskEngine()
        register_all_realtime_rules(engine)
        with pytest.raises(ValueError, match="already registered"):
            register_all_realtime_rules(engine)

    def test_fresh_engine_required(self):
        """Engine with any pre-registered rule on overlapping cadence raises."""
        from backend.qm_platform.risk.rules.realtime.limit_down import (
            LimitDownDetection,
        )

        engine = RealtimeRiskEngine()
        engine.register(LimitDownDetection(), cadence="tick")
        with pytest.raises(ValueError, match="already registered"):
            register_all_realtime_rules(engine)


class TestAdapterDelegateParity:
    """`RiskBacktestAdapter.register_all_realtime_rules` is a thin delegate
    — produces identical registered_rules as the free function (ADR-076 D1
    replay-vs-production parity invariant)."""

    def test_adapter_method_produces_identical_state(self):
        """adapter.register_all_realtime_rules(engine_a) ≡ free_fn(engine_b).

        Parity verified at two layers to prevent both insertion-order
        refactor flakes AND future rule-class divergence (WU-2 production
        runner could otherwise pass with same rule_ids but different
        constructor args — e.g. `TrailingStop(stop_pct=0.08)` vs default):

        Layer 1 — rule_id SET equality per cadence (intent: same rule set,
                  order-agnostic so a future alphabetical-sort refactor
                  inside the SSOT doesn't break the parity test).
        Layer 2 — rule CLASS-TYPE list per cadence (intent: catches future
                  divergence where rules gain non-trivial __init__ args and
                  the two callers might pass different values).
        """
        engine_a = RealtimeRiskEngine()
        engine_b = RealtimeRiskEngine()

        adapter = RiskBacktestAdapter()
        adapter.register_all_realtime_rules(engine_a)
        register_all_realtime_rules(engine_b)

        # Layer 1: rule_id set equality per cadence
        for cadence in ("tick", "5min", "15min"):
            assert set(engine_a.registered_rules[cadence]) == set(
                engine_b.registered_rules[cadence]
            ), (
                f"SSOT invariant violated at cadence={cadence!r}: rule_id set "
                f"diverged between adapter delegate and free function "
                f"(ADR-076 D1 replay-vs-production parity broken)."
            )

        # Layer 2: rule class-type equality per cadence (intent — sustain
        # parity once rules gain non-trivial constructor args in WU-2+)
        for cadence in ("tick", "5min", "15min"):
            types_a = sorted(type(r).__name__ for r in engine_a._rules[cadence].values())
            types_b = sorted(type(r).__name__ for r in engine_b._rules[cadence].values())
            assert types_a == types_b, (
                f"SSOT invariant violated at cadence={cadence!r}: rule class "
                f"types diverged adapter={types_a} vs free_fn={types_b}."
            )

    def test_adapter_delegate_total_count(self):
        """Adapter delegate also produces exactly 10 rules."""
        engine = RealtimeRiskEngine()
        adapter = RiskBacktestAdapter()
        adapter.register_all_realtime_rules(engine)

        total = sum(len(rules) for rules in engine.registered_rules.values())
        assert total == _CANONICAL_TOTAL
