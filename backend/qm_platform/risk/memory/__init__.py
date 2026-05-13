"""V3 §5.4 Risk Memory RAG (Tier B, TB-3 sprint chain).

Modules (TB-3 chunked sub-PR roadmap per Plan v0.2 §A):
  - interface (TB-3a, 本 PR): 纯 dataclass + Enum 契约 (0 IO / 0 DB / 0 LiteLLM / 0 BGE-M3)
  - repository (TB-3a, 本 PR): persist + retrieve helpers via PG + pgvector
    (takes embedding as input; embedding computation 留 TB-3b BGE-M3 wire)
  - embedding_service (TB-3b 留): BGE-M3 EmbeddingService wire — single-text encode
  - rag (TB-3c 留): RiskMemoryRAG.retrieve(query_text, k=5) — orchestrate
    embed query + ivfflat cosine search + 4-tier retention filter
  - retention (TB-3c 留): 4-tier retention strategy (hot/warm/cold/archive
    based on event_timestamp recency + retrieval freq)

Architecture (per V3 §5.4 sustained + ADR-064 D2 BGE-M3 1024-dim):
  - 本 package = Engine PURE side (interface + repository data layer)
  - app/services/risk/risk_memory_rag.py = Application orchestration (TB-3c 留)
  - Beat caller (TB-4 RiskReflectorAgent) = post-event sediment dispatch

Prereq:
  - pgvector v0.8.2 installed (Session 53+19 Phase B closure)
  - BGE-M3 model cached at ./models/bge-m3/ (Session 53+19 Phase A closure)

关联 V3: §5.4 (Risk Memory RAG) / §11.2 line 1228 (RiskMemoryRAG location)
关联 ADR: ADR-029 / ADR-064 (Plan v0.2 D2 BGE-M3) / ADR-066 (TB-1) /
  ADR-067 (TB-2 closure cumulative) / ADR-068 候选 (TB-3 sprint)
关联 铁律: 17 (DataPipeline 入库) / 31 (Engine PURE) / 41 (timezone-aware) / 24 (单一职责)
"""

from __future__ import annotations

from .interface import (
    ActionTaken,
    RiskMemory,
    RiskMemoryError,
    RiskMemoryOutcome,
)
from .repository import (
    persist_risk_memory,
    retrieve_similar,
)

__all__ = [
    "ActionTaken",
    "RiskMemory",
    "RiskMemoryError",
    "RiskMemoryOutcome",
    "persist_risk_memory",
    "retrieve_similar",
]
