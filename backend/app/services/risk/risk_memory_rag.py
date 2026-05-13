"""V3 §5.4 RiskMemoryRAG — application orchestration (TB-3c sprint).

Per V3 §11.2 line 1228 location SSOT: this module composes Engine PURE pieces
(qm_platform.risk.memory.{embedding_service, repository, retention}) into the
end-to-end retrieval orchestration consumed by L1 push augmentation per V3
§5.4 line 710 ("类似情况 N 次, 做 X 动作, 平均结果 Y").

Flow per V3 §5.4:
  1. Caller (TB-4 RiskReflectorAgent OR L1 push integration TB-4+) provides
     query_text (typically `current_lesson || context_summary`).
  2. RAG embeds query via injected EmbeddingService (TB-3b BGE-M3).
  3. RAG calls retrieve_similar() (TB-3a repository) — over-fetch to absorb
     retention filter drops.
  4. RAG applies 4-tier retention filter (TB-3c retention.py).
  5. RAG returns top-k SimilarMemoryHit list (cosine_similarity DESC).

Performance baseline (V3 §5.4 line 710 + Plan v0.2 §A TB-3 retrieval API
< 200ms P99 sediment 锁 by ADR-068 候选):
  - encode: ~10-30ms (BGE-M3 single-text)
  - retrieve_similar (ivfflat): ~5-20ms (k_overfetch ≤ 50)
  - filter_by_retention: <1ms (pure Python, k_overfetch items)
  - Total: well under 200ms P99 typical

DI factory pattern sustained (TB-2e tushare_factory + TB-3b model_factory 体例):
  - embedding_service: injected EmbeddingService (encode contract only)
  - conn_factory: Callable[[], psycopg2.extensions.connection] — lazy
    connection acquisition per query (caller manages pool / pgbouncer)

铁律 31 alignment:
  - This module is `app/services/risk/`, NOT `qm_platform/risk/memory/` —
    orchestration explicitly lives outside Engine PURE side per V3 §11.2
    line 1228. Engine PURE pieces (embedding_service / repository /
    retention) are composed here.

关联 V3: §5.4 line 710 (RAG retrieval) / §11.2 line 1228 (location SSOT)
关联 ADR: ADR-064 D2 (BGE-M3 sustained) / ADR-068 候选 (TB-3 closure)
关联 铁律: 17 (DataPipeline 例外 N/A 本 PR retrieval-only) / 24 (单一职责) /
  31 (orchestration outside PURE) / 32 (Service 不 commit — read-only path) /
  33 (fail-loud) / 41 (timezone-aware)
关联 LL: LL-066 (DataPipeline 例外 N/A 本 PR) / LL-098 X10 sustained /
  LL-160 (DI factory) / LL-161 候选 (retrieval baseline)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from qm_platform.risk.memory.retention import (
    DEFAULT_POLICY,
    RetentionPolicy,
    filter_by_retention,
    utcnow,
)

if TYPE_CHECKING:
    import psycopg2.extensions
    from qm_platform.risk.memory.embedding_service import EmbeddingService
    from qm_platform.risk.memory.interface import SimilarMemoryHit

logger = logging.getLogger(__name__)


# Over-fetch multiplier — DB returns N×k hits then retention filter drops
# stale-low-sim items, finally trimmed to k. Larger multiplier = better
# recall under aggressive retention, smaller = faster.
_DEFAULT_OVERFETCH_MULTIPLIER: int = 3

# Cap on absolute over-fetch to bound ivfflat latency in case of large k
# (e.g. k=50 → over-fetch 150 → cap to 50). pgvector docs note ivfflat
# scans `probes × lists` items per query; over-fetch beyond probes×lists
# wastes work.
_OVERFETCH_HARD_CAP: int = 50


@dataclass
class RiskMemoryRAG:
    """V3 §5.4 RAG orchestration — embed + retrieve + retention filter.

    Args:
        embedding_service: EmbeddingService implementation (TB-3b BGE-M3 in
            production, stub in tests). Provides `encode(text) -> tuple[float]`.
        conn_factory: Callable returning a psycopg2 connection per query.
            Caller owns pool / pgbouncer / commit-rollback strategy. RAG calls
            retrieve_similar (read-only) — no commit needed (铁律 32 sustained).
        retention_policy: 4-tier filter (default = DEFAULT_POLICY).
        default_k: default top-N when caller omits k arg. Default 5
            (sustained V3 §11.2 line 1228 "类似情况 N 次", N typically 3-10).
        overfetch_multiplier: DB over-fetch factor — pre-retention candidates.
            Default 3 (e.g. k=5 → fetch 15 from DB, filter, trim to 5).

    Frozen=False because conn_factory + embedding_service may be reassigned
    in long-lived service contexts (e.g. swap model post-hot-reload). Tests
    construct fresh instances per case.
    """

    embedding_service: EmbeddingService
    conn_factory: Callable[[], psycopg2.extensions.connection]
    retention_policy: RetentionPolicy = field(default_factory=lambda: DEFAULT_POLICY)
    default_k: int = 5
    overfetch_multiplier: int = _DEFAULT_OVERFETCH_MULTIPLIER

    def retrieve(
        self,
        query_text: str,
        k: int | None = None,
        *,
        event_type: str | None = None,
        now: datetime | None = None,
    ) -> list[SimilarMemoryHit]:
        """End-to-end RAG retrieval — embed query + cosine search + retention filter.

        Args:
            query_text: non-empty query string (typically
                `current_lesson || context_summary` per V3 §5.4 line 706
                sediment 体例). Passed to EmbeddingService.encode.
            k: top-N hits to return. None → self.default_k (5 sustained).
                Must be > 0.
            event_type: optional event_type filter (e.g. "LimitDown") — narrows
                cosine search to same-category memories using composite index.
                None = search all event types.
            now: query reference time for retention filter (tz-aware). None =
                current UTC. Tests pass fixed timestamp.

        Returns:
            list[SimilarMemoryHit] sorted by cosine_similarity DESC, length ≤ k.
            Empty list when no risk_memory rows match OR all filtered out by
            retention.

        Raises:
            ValueError: query_text empty / k ≤ 0 / now naive.
            RiskMemoryError: embedding failure (chained from EmbeddingService).
            psycopg2.Error: DB failure (chained from retrieve_similar).
        """
        from qm_platform.risk.memory.repository import retrieve_similar  # noqa: PLC0415

        k_effective = k if k is not None else self.default_k
        if k_effective <= 0:
            raise ValueError(f"k must be > 0, got {k_effective}")

        now_effective = now if now is not None else utcnow()
        if now_effective.tzinfo is None:
            raise ValueError("retrieve: now must be tz-aware (铁律 41 sustained)")

        # Encode query (EmbeddingService validates non-empty text + dim).
        query_embedding = self.embedding_service.encode(query_text)

        # Over-fetch from DB to absorb retention drops.
        overfetch_k = min(
            k_effective * self.overfetch_multiplier,
            _OVERFETCH_HARD_CAP,
        )

        # Read-only path — caller-supplied connection. No commit/rollback
        # per 铁律 32 (read query has no transaction state to flush).
        conn = self.conn_factory()
        try:
            raw_hits = retrieve_similar(
                conn,
                query_embedding,
                k=overfetch_k,
                event_type=event_type,
                min_cosine_similarity=None,  # retention filter handles it
            )
        finally:
            # Caller owns connection lifecycle (pool return, etc). RAG just
            # uses + releases its reference. Connection 不 close here per
            # ADR-013 conn_factory 体例 (sustained TB-2c IndicatorsProvider).
            pass

        # 4-tier retention filter.
        filtered = filter_by_retention(raw_hits, now_effective, self.retention_policy)

        # Trim to k (filter preserves order, repository already sorts DESC).
        final_hits = filtered[:k_effective]

        logger.info(
            "[risk-memory-rag] retrieve query_len=%d k=%d event_type=%s "
            "raw_hits=%d filtered=%d returned=%d",
            len(query_text),
            k_effective,
            event_type or "(any)",
            len(raw_hits),
            len(filtered),
            len(final_hits),
        )

        return final_hits


__all__ = ["RiskMemoryRAG"]
