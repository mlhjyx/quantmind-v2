"""Unit tests for BatchedPlanner — V3 §7.2 batched 平仓 PURE engine (S9a).

覆盖:
  - compute_batch_count: floor at 3, 0.3 ratio scaling, error on 0/neg
  - _split_qty: equal split / remainder placement / edge cases
  - _priority_key: drop_pct DESC, volume ASC, sentiment ASC, code ASC
  - generate_batched_plans: SUCCESS / mode routing (OFF/STAGED/AUTO) /
    batch_index 1-based / scheduled_at staggering / limit_price -2% /
    trigger_metrics propagation / 0-qty batch skip / Defensive errors

铁律 31 sustained: PURE — 0 broker / 0 DB / 0 network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.qm_platform.risk.execution.batched_planner import (
    DEFAULT_BATCH_INTERVAL_MIN,
    BatchedPositionInput,
    _priority_key,
    _split_qty,
    compute_batch_count,
    generate_batched_plans,
)
from backend.qm_platform.risk.execution.planner import (
    ExecutionMode,
    PlanStatus,
)


def _pos(
    code: str,
    *,
    shares: int = 100,
    current_price: float = 100.0,
    daily_volume: float = 1_000_000.0,
    drop_pct: float = -0.05,
    sentiment_24h: float | None = None,
) -> BatchedPositionInput:
    return BatchedPositionInput(
        code=code,
        shares=shares,
        current_price=current_price,
        daily_volume=daily_volume,
        drop_pct=drop_pct,
        sentiment_24h=sentiment_24h,
    )


# ── compute_batch_count ──


class TestBatchCount:
    @pytest.mark.parametrize(
        "n,expected",
        [
            (1, 3),  # floor
            (2, 3),
            (5, 3),  # ceil(5*0.3)=2, floor 3
            (10, 3),  # ceil(10*0.3)=3
            (11, 4),  # ceil(11*0.3)=4
            (20, 6),
            (100, 30),
        ],
    )
    def test_batch_count_formula(self, n: int, expected: int):
        assert compute_batch_count(n) == expected

    def test_zero_positions_raises(self):
        with pytest.raises(ValueError, match="must be > 0"):
            compute_batch_count(0)

    def test_negative_positions_raises(self):
        with pytest.raises(ValueError, match="must be > 0"):
            compute_batch_count(-5)


# ── _split_qty ──


class TestSplitQty:
    @pytest.mark.parametrize(
        "total,batches,expected",
        [
            (100, 3, [34, 33, 33]),
            (10, 3, [4, 3, 3]),
            (9, 3, [3, 3, 3]),
            (3, 3, [1, 1, 1]),
            (2, 3, [1, 1, 0]),  # 0-qty trailing batches
            (1, 3, [1, 0, 0]),
            (0, 3, [0, 0, 0]),  # zero qty splits into zeros
        ],
    )
    def test_split_qty_equal_with_remainder(self, total: int, batches: int, expected: list[int]):
        assert _split_qty(total, batches) == expected

    def test_negative_total_raises(self):
        with pytest.raises(ValueError, match="total must be"):
            _split_qty(-5, 3)

    def test_zero_batches_raises(self):
        with pytest.raises(ValueError, match="batches must be > 0"):
            _split_qty(100, 0)


# ── _priority_key ──


class TestPriorityKey:
    def test_drop_pct_descending_priority(self):
        """Largest drop sells first (most negative drop_pct)."""
        a = _pos("AAA", drop_pct=-0.10)
        b = _pos("BBB", drop_pct=-0.05)
        # sorted ascending key: more-negative first
        assert _priority_key(a) < _priority_key(b)

    def test_volume_tiebreaker(self):
        """Equal drop → lower volume first (less liquid)."""
        a = _pos("AAA", drop_pct=-0.10, daily_volume=500_000.0)
        b = _pos("BBB", drop_pct=-0.10, daily_volume=1_000_000.0)
        assert _priority_key(a) < _priority_key(b)

    def test_sentiment_tiebreaker(self):
        """Equal drop+volume → more-negative sentiment first."""
        a = _pos("AAA", drop_pct=-0.10, daily_volume=500_000.0, sentiment_24h=-0.5)
        b = _pos("BBB", drop_pct=-0.10, daily_volume=500_000.0, sentiment_24h=0.0)
        assert _priority_key(a) < _priority_key(b)

    def test_code_final_tiebreaker_for_determinism(self):
        a = _pos("AAA", drop_pct=-0.10, daily_volume=500_000.0, sentiment_24h=-0.5)
        b = _pos("BBB", drop_pct=-0.10, daily_volume=500_000.0, sentiment_24h=-0.5)
        assert _priority_key(a) < _priority_key(b)

    def test_none_sentiment_treated_as_zero(self):
        a = _pos("AAA", drop_pct=-0.10, daily_volume=500_000.0, sentiment_24h=None)
        b = _pos("BBB", drop_pct=-0.10, daily_volume=500_000.0, sentiment_24h=0.0)
        # tied on first 3 fields; code tiebreaker → AAA < BBB
        assert _priority_key(a) < _priority_key(b)


# ── generate_batched_plans ──


_NOW = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)


class TestGeneratePlansSuccess:
    def test_off_mode_emits_confirmed_plans(self):
        plans = generate_batched_plans(
            trigger_event_id=42,
            trigger_reason="CorrelatedDrop 4+ stocks",
            positions=[_pos("AAA", shares=300), _pos("BBB", shares=300)],
            mode=ExecutionMode.OFF,
            at=_NOW,
        )
        assert len(plans) == 2 * 3  # 2 positions × 3 batches
        for plan in plans:
            assert plan.status == PlanStatus.CONFIRMED
            assert plan.mode == ExecutionMode.OFF
            assert plan.action == "BATCH"

    def test_staged_mode_emits_pending_confirm(self):
        plans = generate_batched_plans(
            trigger_event_id=42,
            trigger_reason="test",
            positions=[_pos("AAA", shares=300)],
            mode=ExecutionMode.STAGED,
            at=_NOW,
        )
        for plan in plans:
            assert plan.status == PlanStatus.PENDING_CONFIRM
            assert plan.mode == ExecutionMode.STAGED

    def test_batch_index_1_based_and_total_matches(self):
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=[_pos("AAA", shares=300)],
            mode=ExecutionMode.OFF,
            at=_NOW,
        )
        assert len(plans) == 3
        assert [p.batch_index for p in plans] == [1, 2, 3]
        assert all(p.batch_total == 3 for p in plans)

    def test_scheduled_at_staggered(self):
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=[_pos("AAA", shares=300)],
            mode=ExecutionMode.OFF,
            at=_NOW,
            batch_interval_min=5,
        )
        assert plans[0].scheduled_at == _NOW
        assert plans[1].scheduled_at == _NOW + timedelta(minutes=5)
        assert plans[2].scheduled_at == _NOW + timedelta(minutes=10)

    def test_cancel_deadline_per_batch_30min(self):
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=[_pos("AAA", shares=300)],
            mode=ExecutionMode.OFF,
            at=_NOW,
        )
        # each batch has own deadline = scheduled_at + 30min
        for plan in plans:
            assert plan.cancel_deadline == plan.scheduled_at + timedelta(minutes=30)

    def test_limit_price_minus_2_pct(self):
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=[_pos("AAA", shares=300, current_price=100.0)],
            mode=ExecutionMode.OFF,
            at=_NOW,
        )
        for plan in plans:
            assert plan.limit_price == pytest.approx(98.0)

    def test_priority_ordering_within_batch(self):
        """Higher-drop position emitted before lower-drop within same batch."""
        positions = [
            _pos("AAA", shares=300, drop_pct=-0.05),  # lower drop
            _pos("BBB", shares=300, drop_pct=-0.10),  # higher drop → priority
        ]
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=positions,
            mode=ExecutionMode.OFF,
            at=_NOW,
        )
        # Group by batch_index, check order within batch 1
        batch_1 = [p for p in plans if p.batch_index == 1]
        assert [p.symbol_id for p in batch_1] == ["BBB", "AAA"]

    def test_qty_split_equal_across_batches(self):
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=[_pos("AAA", shares=300)],
            mode=ExecutionMode.OFF,
            at=_NOW,
        )
        assert [p.qty for p in plans] == [100, 100, 100]

    def test_qty_split_with_remainder(self):
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=[_pos("AAA", shares=10)],
            mode=ExecutionMode.OFF,
            at=_NOW,
        )
        assert [p.qty for p in plans] == [4, 3, 3]

    def test_zero_qty_batches_skipped(self):
        """Position with only 1 share spreads to first batch; remaining zero."""
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=[_pos("AAA", shares=1)],
            mode=ExecutionMode.OFF,
            at=_NOW,
        )
        # 1 share / 3 batches → [1, 0, 0] → only batch 1 emitted
        assert len(plans) == 1
        assert plans[0].batch_index == 1
        assert plans[0].qty == 1

    def test_trigger_metrics_propagated(self):
        plans = generate_batched_plans(
            trigger_event_id=None,
            trigger_reason="test",
            positions=[_pos("AAA", shares=300, sentiment_24h=-0.7)],
            mode=ExecutionMode.OFF,
            at=_NOW,
            trigger_metrics={"portfolio_drop_pct": -0.06, "correlated_count": 5},
        )
        for plan in plans:
            assert plan.risk_metrics["portfolio_drop_pct"] == pytest.approx(-0.06)
            assert plan.risk_metrics["correlated_count"] == 5
            assert plan.risk_metrics["sentiment_24h"] == pytest.approx(-0.7)
            assert "batch_qty" in plan.risk_metrics


# ── Defensive ──


class TestDefensive:
    def test_empty_positions_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            generate_batched_plans(
                trigger_event_id=None,
                trigger_reason="test",
                positions=[],
                mode=ExecutionMode.OFF,
                at=_NOW,
            )

    def test_zero_shares_raises(self):
        with pytest.raises(ValueError, match="shares must be > 0"):
            generate_batched_plans(
                trigger_event_id=None,
                trigger_reason="test",
                positions=[_pos("AAA", shares=0)],
                mode=ExecutionMode.OFF,
                at=_NOW,
            )

    def test_zero_batch_interval_raises(self):
        with pytest.raises(ValueError, match="batch_interval_min must be > 0"):
            generate_batched_plans(
                trigger_event_id=None,
                trigger_reason="test",
                positions=[_pos("AAA", shares=100)],
                mode=ExecutionMode.OFF,
                at=_NOW,
                batch_interval_min=0,
            )

    def test_default_batch_interval(self):
        assert DEFAULT_BATCH_INTERVAL_MIN == 5

    def test_duplicate_codes_rejected(self):
        """Reviewer P2 fix: duplicate code → ValueError (反 silent dict
        overwrite producing double plans with wrong quantities)."""
        with pytest.raises(ValueError, match="duplicate position codes"):
            generate_batched_plans(
                trigger_event_id=None,
                trigger_reason="test",
                positions=[_pos("AAA", shares=100), _pos("AAA", shares=200)],
                mode=ExecutionMode.OFF,
                at=_NOW,
            )

    def test_zero_current_price_rejected(self):
        """Reviewer P2 fix: 0 current_price → 0 limit_price = nonsensical
        sell order; fail fast."""
        with pytest.raises(ValueError, match="current_price must be > 0"):
            generate_batched_plans(
                trigger_event_id=None,
                trigger_reason="test",
                positions=[_pos("AAA", shares=100, current_price=0)],
                mode=ExecutionMode.OFF,
                at=_NOW,
            )

    def test_negative_current_price_rejected(self):
        with pytest.raises(ValueError, match="current_price must be > 0"):
            generate_batched_plans(
                trigger_event_id=None,
                trigger_reason="test",
                positions=[_pos("AAA", shares=100, current_price=-1.0)],
                mode=ExecutionMode.OFF,
                at=_NOW,
            )
