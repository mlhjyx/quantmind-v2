"""V3 §5.4 Risk Memory RAG — pure dataclass + Enum contract (TB-3a foundation).

本模块 0 IO / 0 DB / 0 Redis / 0 LiteLLM / 0 BGE-M3 (铁律 31 Platform Engine PURE).
所有 IO 由 concrete service (TB-3b service.py + TB-3c rag.py) + repository.py 承担.

对齐 V3 §5.4 (Risk Memory RAG) + V3 §11.2 line 1228 (RiskMemoryRAG location:
`backend/app/services/risk/risk_memory_rag.py`) + ADR-064 D2 BGE-M3 1024-dim sustained.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

# BGE-M3 embedding dimension (ADR-064 D2 + ADR-068 D2 sustained). Single source
# of truth — `embedding_service.py` + `repository.py` import this constant rather
# than hardcoding `1024` (TB-3b reviewer LOW resolved in TB-5c batch: defined here
# in the PURE interface module to avoid the embedding_service → interface circular
# import). Aligned with the DDL `embedding VECTOR(1024)`.
EMBEDDING_DIM: int = 1024


class ActionTaken(StrEnum):
    """V3 §5.4 line 700 6-state action_taken — 对齐 risk_memory.action_taken CHECK constraint.

    Note: str subclass for natural JSON / SQL serialization (sustained
    RegimeLabel pattern from TB-2a).
    """

    STAGED_EXECUTED = "STAGED_executed"
    STAGED_CANCELLED = "STAGED_cancelled"
    STAGED_TIMEOUT_EXECUTED = "STAGED_timeout_executed"
    MANUAL_SELL = "manual_sell"
    NO_ACTION = "no_action"
    REENTRY = "reentry"


class RiskMemoryError(RuntimeError):
    """RiskMemory persist / retrieve failures (DDL constraint violation /
    embedding dim mismatch / etc).

    Caller (TB-3c rag service) raises this for fail-loud 路径 (铁律 33).
    """


@dataclass(frozen=True)
class RiskMemoryOutcome:
    """V3 §5.4 line 701 outcome JSONB shape.

    Args:
      pnl_1d: 1-day post-event PnL (decimal fraction, e.g. -0.03 = -3%). None when not yet measurable.
      pnl_5d: 5-day post-event PnL.
      pnl_30d: 30-day post-event PnL.
      retrospective_correctness: TB-4 RiskReflectorAgent V4-Pro 评估
        — was the original action correct in hindsight? str enum:
          - "correct": action prevented further loss / captured gain
          - "incorrect": action caused unnecessary loss / missed opportunity
          - "ambiguous": outcome ambiguous (e.g. market reverted)
          - "pending": not yet evaluated
    """

    pnl_1d: float | None = None
    pnl_5d: float | None = None
    pnl_30d: float | None = None
    retrospective_correctness: str | None = None

    def __post_init__(self) -> None:
        valid_correctness = {"correct", "incorrect", "ambiguous", "pending", None}
        if self.retrospective_correctness not in valid_correctness:
            raise ValueError(
                f"retrospective_correctness must be in {valid_correctness}, "
                f"got {self.retrospective_correctness!r}"
            )

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for outcome JSONB column."""
        return {
            "pnl_1d": self.pnl_1d,
            "pnl_5d": self.pnl_5d,
            "pnl_30d": self.pnl_30d,
            "retrospective_correctness": self.retrospective_correctness,
        }


@dataclass(frozen=True)
class RiskMemory:
    """V3 §5.4 Risk Memory sediment — full risk event lesson record for RAG retrieval.

    Args:
      event_type: V3 §5.4 line 696 — LimitDown/RapidDrop/IndustryCorrelated/etc.
        Open vocab (RAG retrieval filters by exact match, no CHECK enum).
      symbol_id: stock code (e.g. "600519.SH") OR None for market-wide events.
      event_timestamp: tz-aware datetime when risk event triggered (铁律 41).
      context_snapshot: full L0/L1/L2 context at trigger moment (JSONB).
      action_taken: ActionTaken enum OR None pre-RiskReflectorAgent review.
      outcome: RiskMemoryOutcome OR None when not yet measured.
      lesson: TB-4 RiskReflectorAgent V4-Pro reflection text (≤ 500 chars).
        Drives RAG retrieval semantic similarity ranking. None pre-reflection.
      embedding: BGE-M3 1024-dim vector of `lesson || context_summary`.
        Computed by TB-3b EmbeddingService. None pre-embedding (NULL in DB,
        excluded from ivfflat partial index).
      created_at: post-persist DB-generated timestamp (None pre-persist).
      memory_id: BIGSERIAL post-persist (None pre-persist).

    Frozen + immutable per Platform Engine 体例 (sustained RegimeLabel /
    MarketRegime from TB-2a).
    """

    event_type: str
    event_timestamp: datetime
    context_snapshot: dict[str, Any]
    symbol_id: str | None = None
    action_taken: ActionTaken | None = None
    outcome: RiskMemoryOutcome | None = None
    lesson: str | None = None
    embedding: tuple[float, ...] | None = None
    created_at: datetime | None = None
    memory_id: int | None = None

    def __post_init__(self) -> None:
        if not self.event_type or not self.event_type.strip():
            raise ValueError("RiskMemory.event_type must be non-empty")
        if self.event_timestamp.tzinfo is None:
            raise ValueError("RiskMemory.event_timestamp must be tz-aware (铁律 41 sustained)")
        # Defensive: context_snapshot is mutable dict, but the field 是 dict[str, Any]
        # — Python frozen dataclass doesn't enforce dict immutability. Document only.
        if self.lesson is not None and len(self.lesson) > 500:
            raise ValueError(
                f"RiskMemory.lesson exceeds 500-char soft limit (TB-3a sediment "
                f"discipline, sustained TB-4 RiskReflectorAgent prompt cap), "
                f"got {len(self.lesson)} chars"
            )
        if self.embedding is not None and len(self.embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"RiskMemory.embedding must be {EMBEDDING_DIM}-dim (BGE-M3 per "
                f"ADR-064 D2), got {len(self.embedding)} dim"
            )

    def context_snapshot_jsonable(self) -> dict[str, Any]:
        """Return context_snapshot dict (already JSON-safe per caller contract).

        Caller is responsible for ensuring all values in context_snapshot are
        JSON-serializable (str / int / float / bool / None / list / dict).
        """
        return dict(self.context_snapshot)

    def outcome_jsonable(self) -> dict[str, Any] | None:
        """Serialize outcome to JSON-safe dict (None when outcome not yet measured)."""
        return self.outcome.to_jsonable() if self.outcome is not None else None


@dataclass(frozen=True)
class SimilarMemoryHit:
    """RiskMemoryRAG.retrieve_similar result item — RiskMemory + cosine similarity.

    Args:
      memory: RiskMemory row from DB.
      cosine_similarity: pgvector `1 - (embedding <=> query)` ∈ [-1, 1].
        Higher = more similar. Typical relevant hit > 0.7.
    """

    memory: RiskMemory
    cosine_similarity: float
