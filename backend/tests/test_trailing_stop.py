"""Unit tests for TrailingStop rule — V3 §7.3 (S9a).

覆盖:
  - 20% activation gate: pnl < 20% → no trigger, state cleared on retrace
  - 20-49% bracket: trailing = max(10%, ATR × 2)
  - 50-99% bracket: trailing = max(10%, ATR × 1.5)
  - 100%+ bracket: trailing = max(10%, ATR × 1)
  - peak ratchet: peak_price only increases, never decreases
  - trigger when current ≤ peak × (1 - trailing)
  - state reset after trigger (next entry rebuilds fresh)
  - missing ATR → falls back to 10% floor (反 silent skip)
  - reset() clears all per-symbol state
  - update_threshold() validation
  - RiskRule contract: rule_id / severity / action

铁律 31 sustained (state is rule-internal, evaluate is logically pure given state).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.qm_platform._types import Severity
from backend.qm_platform.risk.interface import Position, RiskContext
from backend.qm_platform.risk.rules.realtime.trailing_stop import TrailingStop


def _ctx(*positions: Position, realtime: dict | None = None) -> RiskContext:
    return RiskContext(
        strategy_id="test-strategy",
        execution_mode="paper",
        timestamp=datetime(2026, 5, 13, 10, 0, tzinfo=UTC),
        positions=tuple(positions),
        portfolio_nav=1_000_000.0,
        prev_close_nav=1_000_000.0,
        realtime=realtime,
    )


def _pos(
    code: str = "600519.SH",
    *,
    shares: int = 100,
    entry_price: float = 100.0,
    peak_price: float = 100.0,
    current_price: float = 100.0,
) -> Position:
    return Position(
        code=code,
        shares=shares,
        entry_price=entry_price,
        peak_price=peak_price,
        current_price=current_price,
    )


# ── Rule contract ──


class TestContract:
    def test_rule_id_set(self):
        assert TrailingStop.rule_id == "trailing_stop"

    def test_severity_p1(self):
        assert TrailingStop.severity == Severity.P1

    def test_action_sell(self):
        assert TrailingStop.action == "sell"


# ── Activation gate (20%) ──


class TestActivationGate:
    def test_below_20pct_no_trigger(self):
        rule = TrailingStop()
        # 15% PnL → not yet activated
        ctx = _ctx(_pos(entry_price=100, peak_price=115, current_price=115))
        assert rule.evaluate(ctx) == []

    def test_at_20pct_activates(self):
        rule = TrailingStop()
        # Exactly 20% → activated; peak=120, no ATR → 10% floor, stop=108
        # current=120 > 108 → no trigger this beat (peak just set)
        ctx = _ctx(_pos(entry_price=100, peak_price=120, current_price=120))
        result = rule.evaluate(ctx)
        assert result == []
        # State recorded
        assert "600519.SH" in rule._trail_state

    def test_state_persists_on_retrace_below_activation_without_trigger(self):
        """Reviewer P1 fix: previously misnamed test was passing by accident
        (current=110 → pnl=10% → also triggered trailing stop at 10% floor,
        purging state). The CORRECT semantic per V3 §7.3: once activated, state
        persists even if pnl retraces below 20% — that's the trailing stop's
        whole purpose. Test the no-trigger case explicitly.
        """
        rule = TrailingStop()
        # Activate at +25% (peak=125, no ATR → 10% floor, stop=112.5)
        rule.evaluate(_ctx(_pos(entry_price=100, peak_price=125, current_price=125)))
        assert "600519.SH" in rule._trail_state
        # Retrace to current=119 → pnl=19% (below 20% activation), BUT
        # stop=112.5 → 119 > 112.5 so no trigger; state should PERSIST.
        results = rule.evaluate(
            _ctx(_pos(entry_price=100, peak_price=125, current_price=119))
        )
        assert results == []  # no trigger
        assert "600519.SH" in rule._trail_state  # state persists

    def test_state_cleared_on_retrace_that_triggers_stop(self):
        """Companion test: retrace that DOES breach trailing stop fires a
        trigger and purges state post-trigger (sustained existing semantic).
        """
        rule = TrailingStop()
        rule.evaluate(_ctx(_pos(entry_price=100, peak_price=125, current_price=125)))
        # current=110 → stop=112.5 → 110 < 112.5 → TRIGGER → state purged
        results = rule.evaluate(
            _ctx(_pos(entry_price=100, peak_price=125, current_price=110))
        )
        assert len(results) == 1  # triggered
        assert "600519.SH" not in rule._trail_state  # state purged post-trigger


# ── Trigger logic ──


class TestTrigger:
    def test_trigger_on_drop_past_trailing_no_atr(self):
        rule = TrailingStop()
        # Activate at +30% (peak 130)
        ctx1 = _ctx(_pos(entry_price=100, peak_price=130, current_price=130))
        rule.evaluate(ctx1)
        # Current drops to 116 → 130 × (1 - 0.10) = 117. 116 < 117 → trigger
        ctx2 = _ctx(_pos(entry_price=100, peak_price=130, current_price=116))
        results = rule.evaluate(ctx2)
        assert len(results) == 1
        r = results[0]
        assert r.rule_id == "trailing_stop"
        assert r.code == "600519.SH"
        assert r.shares == 100
        assert r.metrics["stop_price"] == pytest.approx(117.0)

    def test_no_trigger_above_trailing(self):
        rule = TrailingStop()
        ctx1 = _ctx(_pos(entry_price=100, peak_price=130, current_price=130))
        rule.evaluate(ctx1)
        # Current at 120 → 130 × 0.9 = 117. 120 > 117 → no trigger
        ctx2 = _ctx(_pos(entry_price=100, peak_price=130, current_price=120))
        assert rule.evaluate(ctx2) == []

    def test_state_cleared_after_trigger(self):
        rule = TrailingStop()
        # Activate
        rule.evaluate(_ctx(_pos(entry_price=100, peak_price=130, current_price=130)))
        # Trigger
        results = rule.evaluate(_ctx(_pos(entry_price=100, peak_price=130, current_price=116)))
        assert len(results) == 1
        # State purged
        assert "600519.SH" not in rule._trail_state


# ── Bracket logic ──


class TestBrackets:
    def test_20pct_bracket_atr_x_2(self):
        # ATR 0.06, bracket 20-49% → trailing = max(0.10, 0.12) = 0.12
        rule = TrailingStop()
        realtime = {"600519.SH": {"atr_pct": 0.06}}
        ctx1 = _ctx(
            _pos(entry_price=100, peak_price=130, current_price=130),
            realtime=realtime,
        )
        rule.evaluate(ctx1)
        # Stop = 130 × (1 - 0.12) = 114.4; current 114 < 114.4 → trigger
        ctx2 = _ctx(
            _pos(entry_price=100, peak_price=130, current_price=114),
            realtime=realtime,
        )
        results = rule.evaluate(ctx2)
        assert len(results) == 1
        assert results[0].metrics["trailing_pct"] == pytest.approx(0.12)

    def test_50pct_bracket_atr_x_1_5(self):
        rule = TrailingStop()
        realtime = {"600519.SH": {"atr_pct": 0.10}}
        # PnL=60%, peak=160; trailing = max(0.10, 0.10 × 1.5) = 0.15
        ctx1 = _ctx(
            _pos(entry_price=100, peak_price=160, current_price=160),
            realtime=realtime,
        )
        rule.evaluate(ctx1)
        # Stop = 160 × 0.85 = 136; current 135 < 136 → trigger
        ctx2 = _ctx(
            _pos(entry_price=100, peak_price=160, current_price=135),
            realtime=realtime,
        )
        results = rule.evaluate(ctx2)
        assert len(results) == 1
        assert results[0].metrics["trailing_pct"] == pytest.approx(0.15)

    def test_100pct_bracket_atr_x_1(self):
        rule = TrailingStop()
        realtime = {"600519.SH": {"atr_pct": 0.20}}
        # PnL=120%, peak=220; trailing = max(0.10, 0.20 × 1) = 0.20
        ctx1 = _ctx(
            _pos(entry_price=100, peak_price=220, current_price=220),
            realtime=realtime,
        )
        rule.evaluate(ctx1)
        # Stop = 220 × 0.80 = 176; current 175 < 176 → trigger
        ctx2 = _ctx(
            _pos(entry_price=100, peak_price=220, current_price=175),
            realtime=realtime,
        )
        results = rule.evaluate(ctx2)
        assert len(results) == 1
        assert results[0].metrics["trailing_pct"] == pytest.approx(0.20)

    def test_atr_below_floor_uses_floor(self):
        """ATR × 2 = 0.04 < 10% floor → trailing = 0.10."""
        rule = TrailingStop()
        realtime = {"600519.SH": {"atr_pct": 0.02}}
        ctx1 = _ctx(
            _pos(entry_price=100, peak_price=130, current_price=130),
            realtime=realtime,
        )
        rule.evaluate(ctx1)
        ctx2 = _ctx(
            _pos(entry_price=100, peak_price=130, current_price=116),
            realtime=realtime,
        )
        results = rule.evaluate(ctx2)
        assert len(results) == 1
        # ATR × 2 = 0.04 floored to 0.10
        assert results[0].metrics["trailing_pct"] == pytest.approx(0.10)

    def test_no_atr_uses_floor(self):
        """Missing ATR → floor 10%."""
        rule = TrailingStop()
        ctx1 = _ctx(_pos(entry_price=100, peak_price=130, current_price=130))
        rule.evaluate(ctx1)
        ctx2 = _ctx(_pos(entry_price=100, peak_price=130, current_price=116))
        results = rule.evaluate(ctx2)
        assert len(results) == 1
        assert results[0].metrics["trailing_pct"] == pytest.approx(0.10)


# ── Peak ratchet ──


class TestPeakRatchet:
    def test_peak_only_increases(self):
        rule = TrailingStop()
        # Activate at peak=130
        rule.evaluate(_ctx(_pos(entry_price=100, peak_price=130, current_price=130)))
        # Drop to 125 (still above 20% activation but below peak)
        rule.evaluate(_ctx(_pos(entry_price=100, peak_price=130, current_price=125)))
        state = rule._trail_state["600519.SH"]
        # Peak should remain 130 (not retreat to 125)
        assert state.peak_price == 130.0

    def test_peak_ratchets_up_on_new_high(self):
        rule = TrailingStop()
        rule.evaluate(_ctx(_pos(entry_price=100, peak_price=130, current_price=130)))
        # New high at 140
        rule.evaluate(_ctx(_pos(entry_price=100, peak_price=140, current_price=140)))
        state = rule._trail_state["600519.SH"]
        assert state.peak_price == 140.0


# ── Defensive ──


class TestDefensive:
    def test_zero_shares_skipped(self):
        rule = TrailingStop()
        ctx = _ctx(_pos(shares=0, entry_price=100, peak_price=130, current_price=130))
        assert rule.evaluate(ctx) == []

    def test_zero_entry_price_skipped(self):
        rule = TrailingStop()
        ctx = _ctx(_pos(entry_price=0, peak_price=130, current_price=130))
        assert rule.evaluate(ctx) == []

    def test_zero_current_price_skipped(self):
        rule = TrailingStop()
        ctx = _ctx(_pos(entry_price=100, peak_price=130, current_price=0))
        assert rule.evaluate(ctx) == []

    def test_reset_clears_all_state(self):
        rule = TrailingStop()
        rule.evaluate(_ctx(_pos(entry_price=100, peak_price=130, current_price=130)))
        rule.evaluate(_ctx(_pos("000001.SZ", entry_price=10, peak_price=13, current_price=13)))
        assert len(rule._trail_state) == 2
        rule.reset()
        assert rule._trail_state == {}

    def test_update_threshold_valid(self):
        rule = TrailingStop()
        rule.update_threshold(0.30)
        assert rule._activation_pnl == 0.30

    @pytest.mark.parametrize("bad", [-0.1, 0, 1.0, 1.5])
    def test_update_threshold_rejects_invalid(self, bad: float):
        rule = TrailingStop()
        with pytest.raises(ValueError, match="activation_pnl must be in"):
            rule.update_threshold(bad)

    def test_multiple_positions_independent_state(self):
        rule = TrailingStop()
        ctx = _ctx(
            _pos("AAA", entry_price=100, peak_price=130, current_price=130),
            _pos("BBB", entry_price=50, peak_price=100, current_price=100),  # +100%
        )
        rule.evaluate(ctx)
        assert "AAA" in rule._trail_state
        assert "BBB" in rule._trail_state
        # Different peaks
        assert rule._trail_state["AAA"].peak_price == 130
        assert rule._trail_state["BBB"].peak_price == 100
