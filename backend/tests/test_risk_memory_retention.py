"""V3 §5.4 retention.py tests (TB-3c) — 4-tier filter PURE logic.

Coverage:
  - RetentionPolicy frozen + __post_init__ validation (boundaries / thresholds /
    monotonic warning)
  - classify_tier: HOT / WARM / COLD / ARCHIVE bucket boundaries (fractional days)
  - threshold_for_tier mapping
  - filter_by_retention: 4-tier threshold gating + order preservation + naive-tz
    fail-loud
  - DEFAULT_POLICY: sediment 锁 defaults match ADR-068 候选

LL-159 4-step preflight sustained — PURE unit tests, 0 IO / 0 DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from qm_platform.risk.memory.interface import RiskMemory, SimilarMemoryHit
from qm_platform.risk.memory.retention import (
    DEFAULT_POLICY,
    RetentionPolicy,
    RetentionTier,
    classify_tier,
    filter_by_retention,
    threshold_for_tier,
    utcnow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC)


def _memory_at(age_days: float, *, event_type: str = "LimitDown") -> RiskMemory:
    """Build RiskMemory with event_timestamp = _NOW - age_days."""
    ts = _NOW - timedelta(days=age_days)
    return RiskMemory(
        event_type=event_type,
        event_timestamp=ts,
        context_snapshot={"age_days": age_days},
        lesson=f"lesson age={age_days}d",
    )


def _hit(age_days: float, similarity: float) -> SimilarMemoryHit:
    return SimilarMemoryHit(memory=_memory_at(age_days), cosine_similarity=similarity)


# ---------------------------------------------------------------------------
# RetentionPolicy construction + validation
# ---------------------------------------------------------------------------


class TestRetentionPolicy:
    def test_default_policy_sediment_lock(self) -> None:
        """DEFAULT_POLICY matches ADR-068 候选 sediment defaults."""
        assert DEFAULT_POLICY.hot_max_days == 7
        assert DEFAULT_POLICY.warm_max_days == 30
        assert DEFAULT_POLICY.cold_max_days == 90
        assert DEFAULT_POLICY.hot_threshold == 0.0
        assert DEFAULT_POLICY.warm_threshold == 0.60
        assert DEFAULT_POLICY.cold_threshold == 0.70
        assert DEFAULT_POLICY.archive_threshold == 0.80

    def test_policy_is_frozen(self) -> None:
        import dataclasses

        p = RetentionPolicy()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.hot_max_days = 14  # type: ignore[misc]

    def test_non_increasing_boundaries_raise(self) -> None:
        with pytest.raises(ValueError, match="strictly increasing"):
            RetentionPolicy(hot_max_days=30, warm_max_days=7, cold_max_days=90)

    def test_zero_hot_max_raises(self) -> None:
        with pytest.raises(ValueError, match="strictly increasing"):
            RetentionPolicy(hot_max_days=0)

    def test_threshold_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="hot_threshold"):
            RetentionPolicy(hot_threshold=1.5)
        with pytest.raises(ValueError, match="warm_threshold"):
            RetentionPolicy(warm_threshold=-2.0)

    def test_non_monotonic_thresholds_warns_not_raises(self, caplog) -> None:
        """Soft-check (warning) — experimental policies allowed."""
        import logging

        with caplog.at_level(logging.WARNING):
            p = RetentionPolicy(
                hot_threshold=0.8, warm_threshold=0.5, cold_threshold=0.5
            )
        assert p.hot_threshold == 0.8  # constructed OK
        assert any("not monotonic" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# classify_tier
# ---------------------------------------------------------------------------


class TestClassifyTier:
    def test_age_0_is_hot(self) -> None:
        assert classify_tier(_NOW, _NOW) == RetentionTier.HOT

    def test_age_just_under_7d_is_hot(self) -> None:
        ts = _NOW - timedelta(days=7) + timedelta(seconds=1)
        assert classify_tier(ts, _NOW) == RetentionTier.HOT

    def test_age_exactly_7d_is_hot_inclusive(self) -> None:
        """Boundary inclusive: ≤ hot_max_days is HOT (not the next tier)."""
        ts = _NOW - timedelta(days=7)
        assert classify_tier(ts, _NOW) == RetentionTier.HOT

    def test_age_7d_1h_is_warm(self) -> None:
        ts = _NOW - timedelta(days=7, hours=1)
        assert classify_tier(ts, _NOW) == RetentionTier.WARM

    def test_age_15d_is_warm(self) -> None:
        ts = _NOW - timedelta(days=15)
        assert classify_tier(ts, _NOW) == RetentionTier.WARM

    def test_age_exactly_30d_is_warm_inclusive(self) -> None:
        ts = _NOW - timedelta(days=30)
        assert classify_tier(ts, _NOW) == RetentionTier.WARM

    def test_age_31d_is_cold(self) -> None:
        ts = _NOW - timedelta(days=31)
        assert classify_tier(ts, _NOW) == RetentionTier.COLD

    def test_age_60d_is_cold(self) -> None:
        ts = _NOW - timedelta(days=60)
        assert classify_tier(ts, _NOW) == RetentionTier.COLD

    def test_age_exactly_90d_is_cold_inclusive(self) -> None:
        ts = _NOW - timedelta(days=90)
        assert classify_tier(ts, _NOW) == RetentionTier.COLD

    def test_age_91d_is_archive(self) -> None:
        ts = _NOW - timedelta(days=91)
        assert classify_tier(ts, _NOW) == RetentionTier.ARCHIVE

    def test_age_365d_is_archive(self) -> None:
        ts = _NOW - timedelta(days=365)
        assert classify_tier(ts, _NOW) == RetentionTier.ARCHIVE

    def test_naive_event_timestamp_raises(self) -> None:
        naive = datetime(2026, 5, 1, 0, 0)
        with pytest.raises(ValueError, match="event_timestamp must be tz-aware"):
            classify_tier(naive, _NOW)

    def test_naive_now_raises(self) -> None:
        naive = datetime(2026, 5, 14, 12, 0)
        with pytest.raises(ValueError, match="now must be tz-aware"):
            classify_tier(_NOW, naive)

    def test_custom_policy_boundaries(self) -> None:
        custom = RetentionPolicy(hot_max_days=1, warm_max_days=3, cold_max_days=7)
        # Age 2 days under custom = WARM (under default = HOT)
        ts = _NOW - timedelta(days=2)
        assert classify_tier(ts, _NOW, custom) == RetentionTier.WARM
        assert classify_tier(ts, _NOW) == RetentionTier.HOT


# ---------------------------------------------------------------------------
# threshold_for_tier
# ---------------------------------------------------------------------------


class TestThresholdForTier:
    def test_hot_threshold_default(self) -> None:
        assert threshold_for_tier(RetentionTier.HOT) == 0.0

    def test_warm_threshold_default(self) -> None:
        assert threshold_for_tier(RetentionTier.WARM) == 0.60

    def test_cold_threshold_default(self) -> None:
        assert threshold_for_tier(RetentionTier.COLD) == 0.70

    def test_archive_threshold_default(self) -> None:
        assert threshold_for_tier(RetentionTier.ARCHIVE) == 0.80

    def test_custom_thresholds(self) -> None:
        custom = RetentionPolicy(
            hot_threshold=0.1,
            warm_threshold=0.5,
            cold_threshold=0.9,
            archive_threshold=0.95,
        )
        assert threshold_for_tier(RetentionTier.HOT, custom) == 0.1
        assert threshold_for_tier(RetentionTier.WARM, custom) == 0.5
        assert threshold_for_tier(RetentionTier.COLD, custom) == 0.9
        assert threshold_for_tier(RetentionTier.ARCHIVE, custom) == 0.95


# ---------------------------------------------------------------------------
# filter_by_retention
# ---------------------------------------------------------------------------


class TestFilterByRetention:
    def test_empty_input_returns_empty(self) -> None:
        assert filter_by_retention([], _NOW) == []

    def test_hot_tier_keeps_all_non_negative_similarity(self) -> None:
        """Default hot_threshold = 0.0 → all positive/zero-sim hits retained.

        Negative cosine_sim = anti-correlated ≠ "recent so include" — these
        are NOT relevant memories, so default threshold = 0.0 drops them.
        Caller can pass `RetentionPolicy(hot_threshold=-1.0)` to truly keep all.
        """
        hits = [
            _hit(age_days=1, similarity=0.05),
            _hit(age_days=3, similarity=0.0),  # at threshold → keep
            _hit(age_days=7, similarity=0.0),
        ]
        out = filter_by_retention(hits, _NOW)
        assert len(out) == 3

    def test_hot_tier_drops_negative_similarity_by_default(self) -> None:
        """Anti-correlated hits in HOT tier dropped (sustained semantic)."""
        hits = [
            _hit(age_days=1, similarity=-0.3),  # anti-correlated → drop
            _hit(age_days=3, similarity=0.5),  # positive → keep
        ]
        out = filter_by_retention(hits, _NOW)
        assert len(out) == 1
        assert out[0].cosine_similarity == 0.5

    def test_hot_tier_keep_all_via_explicit_negative_threshold(self) -> None:
        """Explicit hot_threshold=-1.0 keeps anti-correlated HOT hits."""
        policy = RetentionPolicy(hot_threshold=-1.0)
        hits = [
            _hit(age_days=1, similarity=-0.5),
            _hit(age_days=3, similarity=0.0),
        ]
        out = filter_by_retention(hits, _NOW, policy)
        assert len(out) == 2

    def test_warm_tier_threshold_gating(self) -> None:
        # Default warm_threshold = 0.60. Age 15 days.
        hits = [
            _hit(age_days=15, similarity=0.55),  # WARM, below threshold → DROP
            _hit(age_days=15, similarity=0.60),  # WARM, at threshold → KEEP
            _hit(age_days=15, similarity=0.85),  # WARM, above threshold → KEEP
        ]
        out = filter_by_retention(hits, _NOW)
        assert len(out) == 2
        assert all(h.cosine_similarity >= 0.60 for h in out)

    def test_cold_tier_threshold_gating(self) -> None:
        # Default cold_threshold = 0.70. Age 60 days.
        hits = [
            _hit(age_days=60, similarity=0.65),  # COLD, below → DROP
            _hit(age_days=60, similarity=0.70),  # COLD, at → KEEP
            _hit(age_days=60, similarity=0.95),  # COLD, above → KEEP
        ]
        out = filter_by_retention(hits, _NOW)
        assert len(out) == 2

    def test_archive_tier_threshold_gating(self) -> None:
        # Default archive_threshold = 0.80. Age 200 days.
        hits = [
            _hit(age_days=200, similarity=0.75),  # ARCHIVE, below → DROP
            _hit(age_days=200, similarity=0.80),  # ARCHIVE, at → KEEP
            _hit(age_days=200, similarity=0.99),  # ARCHIVE, above → KEEP
        ]
        out = filter_by_retention(hits, _NOW)
        assert len(out) == 2

    def test_mixed_tiers_filter_correctly(self) -> None:
        hits = [
            _hit(age_days=1, similarity=0.1),  # HOT keep (any sim)
            _hit(age_days=20, similarity=0.5),  # WARM drop (< 0.6)
            _hit(age_days=20, similarity=0.7),  # WARM keep
            _hit(age_days=60, similarity=0.6),  # COLD drop (< 0.7)
            _hit(age_days=60, similarity=0.75),  # COLD keep
            _hit(age_days=200, similarity=0.75),  # ARCHIVE drop (< 0.8)
            _hit(age_days=200, similarity=0.9),  # ARCHIVE keep
        ]
        out = filter_by_retention(hits, _NOW)
        # 4 keeps: HOT 0.1 / WARM 0.7 / COLD 0.75 / ARCHIVE 0.9
        assert len(out) == 4
        ages = [_NOW.toordinal() - h.memory.event_timestamp.toordinal() for h in out]
        assert ages == [1, 20, 60, 200]  # order preserved

    def test_order_preserved(self) -> None:
        """Input order (typically cosine DESC from repository) must be preserved."""
        hits = [
            _hit(age_days=5, similarity=0.95),  # HOT
            _hit(age_days=20, similarity=0.80),  # WARM
            _hit(age_days=60, similarity=0.75),  # COLD
        ]
        out = filter_by_retention(hits, _NOW)
        assert len(out) == 3
        sims = [h.cosine_similarity for h in out]
        assert sims == [0.95, 0.80, 0.75]

    def test_naive_now_raises(self) -> None:
        naive = datetime(2026, 5, 14, 12, 0)
        with pytest.raises(ValueError, match="now must be tz-aware"):
            filter_by_retention([_hit(1, 0.9)], naive)

    def test_custom_policy_loose(self) -> None:
        loose = RetentionPolicy(
            warm_threshold=0.3, cold_threshold=0.4, archive_threshold=0.5
        )
        hits = [
            _hit(age_days=20, similarity=0.35),  # WARM keep under loose
            _hit(age_days=60, similarity=0.45),  # COLD keep under loose
            _hit(age_days=200, similarity=0.55),  # ARCHIVE keep under loose
        ]
        out = filter_by_retention(hits, _NOW, loose)
        assert len(out) == 3


# ---------------------------------------------------------------------------
# utcnow helper
# ---------------------------------------------------------------------------


class TestUtcnow:
    def test_returns_tz_aware(self) -> None:
        ts = utcnow()
        assert ts.tzinfo is not None

    def test_returns_utc(self) -> None:
        ts = utcnow()
        assert ts.utcoffset() == timedelta(0)
