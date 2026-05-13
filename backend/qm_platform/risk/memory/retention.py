"""V3 §5.4 Risk Memory RAG — 4-tier retention filter (TB-3c sprint).

PURE function module: filter list[SimilarMemoryHit] by age-tiered similarity
thresholds. 0 IO / 0 DB / 0 LiteLLM / 0 BGE-M3 — Engine PURE side per 铁律 31.

Architecture (per package __init__.py docstring sustained):
  - 本 module = Engine PURE filter logic
  - Consumed by app/services/risk/risk_memory_rag.py RiskMemoryRAG orchestration
  - 4-tier: HOT / WARM / COLD / ARCHIVE based on event_timestamp age

Numerical thresholds 锁 (per ADR-068 候选 sediment, default policy):
  - HOT (0-7 day): cosine_sim ≥ 0.0 — recent context preserved liberally
    (V3 §5.4 line 710), but anti-correlated hits (negative sim) dropped as
    semantically irrelevant. Use `hot_threshold=-1.0` to keep truly all.
  - WARM (7-30 day): cosine_sim ≥ 0.60 (typical relevant hit threshold)
  - COLD (30-90 day): cosine_sim ≥ 0.70 (high-relevance only as quality drops
    with staleness)
  - ARCHIVE (>90 day): cosine_sim ≥ 0.80 (very high relevance only — old
    memories add noise unless extremely on-point)

Defaults are configurable per RetentionPolicy frozen dataclass. CC 实测决议 +
ADR-068 sediment 锁 (sustained TB-3 sprint plan §A LL/ADR candidate row).

关联 V3: §5.4 line 710 (RAG retrieval purpose) / §11.2 line 1228 (RiskMemoryRAG
  orchestration location 在 app/services/risk/risk_memory_rag.py)
关联 ADR: ADR-068 候选 (TB-3 sprint cumulative — 4-tier retention sediment 锁)
关联 铁律: 24 (单一职责 — 仅 filter) / 31 (PURE Engine) / 33 (fail-loud 输入校验) /
  41 (timezone-aware datetime arithmetic)
关联 LL: LL-161 候选 (TB-3 retention boundary case findings)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .interface import SimilarMemoryHit

logger = logging.getLogger(__name__)


class RetentionTier(StrEnum):
    """V3 §5.4 retention tier — drives similarity threshold per age bucket."""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class RetentionPolicy:
    """4-tier retention boundaries + similarity thresholds.

    All age boundaries are in days from query time. Defaults reflect
    ADR-068 候选 sediment (CC 实测决议 to lock at TB-3 closure).

    Args:
        hot_max_days: HOT tier covers 0..hot_max_days. Default 7.
        warm_max_days: WARM tier covers hot_max_days..warm_max_days. Default 30.
        cold_max_days: COLD tier covers warm_max_days..cold_max_days. Default 90.
            >cold_max_days = ARCHIVE.
        hot_threshold: HOT tier min cosine_sim (default 0.0 = all pass —
            recent context always valuable per V3 §5.4 line 710).
        warm_threshold: WARM tier min cosine_sim. Default 0.60.
        cold_threshold: COLD tier min cosine_sim. Default 0.70.
        archive_threshold: ARCHIVE tier min cosine_sim. Default 0.80.

    Frozen + immutable per Platform Engine 体例 (sustained TB-2a RegimeLabel /
    TB-3a RiskMemory pattern).
    """

    hot_max_days: int = 7
    warm_max_days: int = 30
    cold_max_days: int = 90
    hot_threshold: float = 0.0
    warm_threshold: float = 0.60
    cold_threshold: float = 0.70
    archive_threshold: float = 0.80

    def __post_init__(self) -> None:
        # Boundaries strictly increasing (fail-loud per 铁律 33).
        if not (0 < self.hot_max_days < self.warm_max_days < self.cold_max_days):
            raise ValueError(
                f"RetentionPolicy boundaries must be strictly increasing positive: "
                f"hot={self.hot_max_days} / warm={self.warm_max_days} / "
                f"cold={self.cold_max_days}"
            )
        # Thresholds in [0, 1] (cosine similarity range — same dir hemisphere
        # convention; pgvector docs note `1 - <=>` ∈ [-1, 1] but L1 push use
        # case treats negative as irrelevant — anything < 0 will be filtered
        # by warm/cold/archive thresholds anyway).
        for name, val in (
            ("hot_threshold", self.hot_threshold),
            ("warm_threshold", self.warm_threshold),
            ("cold_threshold", self.cold_threshold),
            ("archive_threshold", self.archive_threshold),
        ):
            if not (-1.0 <= val <= 1.0):
                raise ValueError(
                    f"RetentionPolicy.{name} must be in [-1.0, 1.0], got {val}"
                )
        # Thresholds typically increase with age — soft check (warn rather
        # than raise, to allow experimental policies).
        if not (
            self.hot_threshold
            <= self.warm_threshold
            <= self.cold_threshold
            <= self.archive_threshold
        ):
            logger.warning(
                "[risk-memory] RetentionPolicy thresholds not monotonic non-decreasing "
                "(hot=%.2f / warm=%.2f / cold=%.2f / archive=%.2f) — "
                "unusual policy, verify intent",
                self.hot_threshold,
                self.warm_threshold,
                self.cold_threshold,
                self.archive_threshold,
            )


# Module-level default — typical L1 push augmentation use case.
DEFAULT_POLICY: RetentionPolicy = RetentionPolicy()


def classify_tier(
    event_timestamp: datetime,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_POLICY,
) -> RetentionTier:
    """Bucket a memory's event_timestamp into a RetentionTier.

    Args:
        event_timestamp: when the risk event originally fired (tz-aware per 铁律 41).
        now: query reference time (tz-aware). Caller passes datetime.now(timezone.utc)
            OR a fixed timestamp for deterministic tests.
        policy: tier boundaries (default = DEFAULT_POLICY).

    Returns:
        RetentionTier enum value.

    Raises:
        ValueError: event_timestamp OR now is naive (no tzinfo) per 铁律 41.
    """
    if event_timestamp.tzinfo is None:
        raise ValueError(
            "classify_tier: event_timestamp must be tz-aware (铁律 41 sustained)"
        )
    if now.tzinfo is None:
        raise ValueError("classify_tier: now must be tz-aware (铁律 41 sustained)")

    age = now - event_timestamp
    # Use total_seconds → days fractional comparison to be precise on
    # sub-day boundaries (e.g. age = 7 days 1 hour ≠ HOT).
    age_days = age.total_seconds() / 86400.0

    # Reviewer-fix (PR #341 MEDIUM 1): negative age = event_timestamp > now.
    # Likely clock skew / timezone misconfiguration / test error. Soft-check
    # (warn rather than raise — filter processes N hits, one bad row should
    # not blow up the whole retrieval). Sustained line 115 monotonic-warning 体例.
    if age_days < 0:
        logger.warning(
            "[risk-memory] classify_tier: negative age_days=%.2f "
            "(event_timestamp=%s > now=%s) — clock skew / tz misconfig?",
            age_days,
            event_timestamp.isoformat(),
            now.isoformat(),
        )

    if age_days <= policy.hot_max_days:
        return RetentionTier.HOT
    if age_days <= policy.warm_max_days:
        return RetentionTier.WARM
    if age_days <= policy.cold_max_days:
        return RetentionTier.COLD
    return RetentionTier.ARCHIVE


def threshold_for_tier(tier: RetentionTier, policy: RetentionPolicy = DEFAULT_POLICY) -> float:
    """Map a RetentionTier to its min cosine_similarity threshold."""
    if tier is RetentionTier.HOT:
        return policy.hot_threshold
    if tier is RetentionTier.WARM:
        return policy.warm_threshold
    if tier is RetentionTier.COLD:
        return policy.cold_threshold
    return policy.archive_threshold


def filter_by_retention(
    hits: list[SimilarMemoryHit],
    now: datetime,
    policy: RetentionPolicy = DEFAULT_POLICY,
) -> list[SimilarMemoryHit]:
    """Apply 4-tier retention filter to similarity hits — drop low-relevance stale entries.

    Args:
        hits: ordered list (typically cosine_similarity DESC per TB-3a
            retrieve_similar contract). Order preserved post-filter.
        now: query reference time (tz-aware per 铁律 41).
        policy: tier boundaries + thresholds.

    Returns:
        Filtered list — same order, items where `cosine_similarity >=
        threshold_for_tier(classify_tier(event_timestamp))` retained.

    Raises:
        ValueError: now is naive OR any hit has naive event_timestamp.
    """
    if now.tzinfo is None:
        raise ValueError("filter_by_retention: now must be tz-aware (铁律 41 sustained)")

    filtered: list[SimilarMemoryHit] = []
    for hit in hits:
        tier = classify_tier(hit.memory.event_timestamp, now, policy)
        threshold = threshold_for_tier(tier, policy)
        if hit.cosine_similarity >= threshold:
            filtered.append(hit)

    logger.info(
        "[risk-memory] retention filter: %d/%d hits retained (policy hot≤%dd thr=%.2f "
        "/ warm≤%dd thr=%.2f / cold≤%dd thr=%.2f / archive thr=%.2f)",
        len(filtered),
        len(hits),
        policy.hot_max_days,
        policy.hot_threshold,
        policy.warm_max_days,
        policy.warm_threshold,
        policy.cold_max_days,
        policy.cold_threshold,
        policy.archive_threshold,
    )
    return filtered


def utcnow() -> datetime:
    """tz-aware UTC now — caller convenience for filter_by_retention."""
    return datetime.now(UTC)


__all__ = [
    "DEFAULT_POLICY",
    "RetentionPolicy",
    "RetentionTier",
    "classify_tier",
    "filter_by_retention",
    "threshold_for_tier",
    "utcnow",
]
