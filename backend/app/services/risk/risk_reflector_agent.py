"""V3 §8 RiskReflectorAgent — application orchestration (TB-4a skeleton + TB-4c lesson loop).

Per V3 §11.2 line 1228 location SSOT: this module composes the Engine PURE
ReflectorAgent V4-Pro wrapper (qm_platform.risk.reflector.agent) with caller-
supplied ReflectionInput, and (TB-4c) sediments the reflection lesson into
risk_memory for RAG retrieval (V3 §8.3 闭环).

TB-4a: skeleton — caller passes pre-composed ReflectionInput, reflect() delegates.
TB-4c (本 PR): lesson→risk_memory 闭环 — sediment_lesson() composes lesson text
  + BGE-M3 embedding + RiskMemory + persist_risk_memory INSERT.
TB-4c boundary 留 TB-4d: real input gathering (gather_input from risk_event_log /
  execution_plans / trade_log / RAG) + user reply approve → CC auto PR generate flow.

lesson→risk_memory 闭环 embedding 选型 (IMPORTANT — pre-ADR-064 spec drift resolved):
  V3 §8.3 line 962 + §16.2 line 727 + Plan v0.2 §A TB-4 row cite "V4-Flash
  embedding" — BUT ADR-064 D2 + ADR-068 D2 superseded this with BGE-M3 local
  embedding (0 cost vs LiteLLM Flash ~$0.01/event, 中文优化, 1024-dim). TB-4c
  sustains BGE-M3 (TB-3b BGEM3EmbeddingService) per ADR-064/068 D2 lock — the
  "V4-Flash embedding" cite in V3 spec is a pre-ADR-064 artifact (留 TB-5c batch
  V3 §8.3/§16.2 doc amend per ADR-022 反 retroactive content edit).

DI factory pattern sustained (TB-2e tushare_factory + TB-3b model_factory):
  - router_factory: Callable[[], _RouterProtocol] — lazy router construction
  - embedding_factory: Callable[[], EmbeddingService] — lazy BGE-M3 service
    (None until TB-4c sediment_lesson called; reflect() skeleton path doesn't need it)

铁律 alignment:
  - 17: risk_memory INSERT 走 persist_risk_memory single-row (LL-066 subset 例外
    sustained — small per-reflection sediment, not batch). TB-4c task is caller /
    transaction owner (铁律 32 explicit commit).
  - 31: orchestration outside Engine PURE (qm_platform/risk/reflector + memory).
  - 32: Service 不 commit — sediment_lesson takes caller-injected conn, caller commits.
  - 33: fail-loud — embedding / persist failure propagates (chained).
  - 41: tz-aware event_timestamp throughout.

关联 V3: §8 (RiskReflector) / §8.3 (lesson 闭环) / §11.2 line 1228 (location SSOT)
关联 ADR: ADR-031 (LiteLLMRouter) / ADR-036 (V4-Pro mapping) / ADR-064 D2 + ADR-068 D2
  (BGE-M3 embedding sustained) / ADR-069 候选 (TB-4 closure cumulative)
关联 铁律: 17 / 24 / 31 / 32 / 33 / 41 / 42
关联 LL: LL-066 (DataPipeline subset 例外) / LL-098 X10 / LL-159 (preflight) / LL-160 (DI factory)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from backend.qm_platform.risk.reflector import (
    ReflectionInput,
    ReflectionOutput,
    ReflectorAgent,
)

if TYPE_CHECKING:
    import psycopg2.extensions

    from backend.qm_platform.risk.memory.embedding_service import EmbeddingService
    from backend.qm_platform.risk.reflector.agent import _RouterProtocol

logger = logging.getLogger(__name__)

# risk_memory.lesson DDL CHECK constraint: length(lesson) <= 500 (TB-3a sustained).
# RiskMemory.__post_init__ also enforces 500-char cap.
_LESSON_MAX_CHARS: int = 500


def _compose_lesson_text(output: ReflectionOutput) -> str:
    """Compose a ≤500-char lesson text from ReflectionOutput for risk_memory.lesson.

    V3 §8.3 line 962: lesson sediment drives RAG retrieval semantic similarity.
    Composition: overall_summary as the core lesson; if it exceeds 500 chars
    (ReflectionOutput allows ≤600), truncate with ellipsis (反 DDL CHECK violation).

    The full 5 维 detail lives in the markdown report (docs/risk_reflections/);
    risk_memory.lesson is the embedding-ranked retrieval snippet.

    Args:
        output: ReflectionOutput from ReflectorAgent.reflect.

    Returns:
        Lesson text, guaranteed ≤ _LESSON_MAX_CHARS (500).
    """
    lesson = output.overall_summary.strip()
    if len(lesson) > _LESSON_MAX_CHARS:
        # Truncate with ellipsis — codepoint-safe (Python str slicing).
        lesson = lesson[: _LESSON_MAX_CHARS - 1] + "…"
    return lesson


def _compose_context_snapshot(output: ReflectionOutput) -> dict[str, object]:
    """Compose risk_memory.context_snapshot JSONB from ReflectionOutput.

    V3 §5.4 line 699: context_snapshot is the trigger-moment snapshot. For a
    reflection sediment, the "context" is the reflection metadata + 5 维 summary
    digest — enough to reconstruct what the reflection observed without the
    full markdown report.

    Returns:
        JSON-safe dict (str / int / float / bool / None / list / dict only).
    """
    return {
        "source": "risk_reflector",
        "period_label": output.period_label,
        "generated_at": output.generated_at.isoformat(),
        "total_findings": sum(len(r.findings) for r in output.reflections),
        "total_candidates": sum(len(r.candidates) for r in output.reflections),
        "dimension_summaries": {
            r.dimension.value: r.summary for r in output.reflections
        },
    }


@dataclass
class RiskReflectorAgent:
    """V3 §8 RiskReflector orchestration — Application layer (TB-4a + TB-4c).

    TB-4a: thin pass-through to ReflectorAgent (caller supplies ReflectionInput).
    TB-4c: + sediment_lesson() — lesson→risk_memory 闭环 via BGE-M3 embedding.
    TB-4d 留: gather_input() real DB gathering + user reply approve → CC PR flow.

    Args:
        router_factory: Callable returning _RouterProtocol per first reflect().
        embedding_factory: Callable returning EmbeddingService (BGE-M3) per first
            sediment_lesson(). None = caller must inject before sediment_lesson
            OR ImportError raised lazily (skeleton reflect() path doesn't need it).
        agent_factory: optional test override — Callable[[router], ReflectorAgent].

    Frozen=False so service can lazy-cache the ReflectorAgent + EmbeddingService
    after first use (sustained TB-3b BGEM3EmbeddingService lazy cache 体例).
    """

    router_factory: Callable[[], _RouterProtocol]
    embedding_factory: Callable[[], EmbeddingService] | None = None
    agent_factory: Callable[[object], ReflectorAgent] | None = None
    _agent: ReflectorAgent | None = field(default=None, init=False, repr=False)
    _embedding_service: EmbeddingService | None = field(
        default=None, init=False, repr=False
    )

    def _ensure_agent(self) -> ReflectorAgent:
        """Lazy construct + cache ReflectorAgent (sustained TB-3b lazy load 体例)."""
        if self._agent is None:
            router = self.router_factory()
            if self.agent_factory is not None:
                self._agent = self.agent_factory(router)
            else:
                self._agent = ReflectorAgent(router=router)
        return self._agent

    def _ensure_embedding_service(self) -> EmbeddingService:
        """Lazy construct + cache EmbeddingService (BGE-M3) for lesson loop.

        Raises:
            RuntimeError: embedding_factory not injected (TB-4c sediment_lesson
                requires it — skeleton reflect() path does not).
        """
        if self._embedding_service is None:
            if self.embedding_factory is None:
                raise RuntimeError(
                    "RiskReflectorAgent.sediment_lesson requires embedding_factory "
                    "(BGE-M3 EmbeddingService) — inject via constructor. "
                    "Sustained ADR-064 D2 + ADR-068 D2 BGE-M3 embedding lock."
                )
            self._embedding_service = self.embedding_factory()
        return self._embedding_service

    def reflect(
        self,
        input_data: ReflectionInput,
        *,
        decision_id: str | None = None,
        now: datetime | None = None,
    ) -> ReflectionOutput:
        """V3 §8.1 5 维反思 — delegate to underlying ReflectorAgent.

        Args:
            input_data: caller-composed ReflectionInput (period + summaries).
            decision_id: optional audit trace UUID-like.
            now: tz-aware datetime for ReflectionOutput.generated_at. None = UTC now.

        Returns:
            ReflectionOutput with 5 维 reflections + overall_summary + raw_response.

        Raises:
            PromptLoadError / ReflectorAgentError / LLM SDK errors propagate
            from underlying ReflectorAgent (sustained fail-loud 铁律 33).
        """
        agent = self._ensure_agent()
        logger.info(
            "[risk-reflector-service] reflect period=%s decision_id=%s",
            input_data.period_label,
            decision_id or "(none)",
        )
        return agent.reflect(input_data, decision_id=decision_id, now=now)

    def sediment_lesson(
        self,
        output: ReflectionOutput,
        conn: psycopg2.extensions.connection,
        *,
        event_type: str,
        symbol_id: str | None = None,
        event_timestamp: datetime | None = None,
    ) -> int:
        """V3 §8.3 lesson→risk_memory 闭环 — embed reflection lesson + persist.

        Flow (TB-4c):
          1. Compose lesson text (≤500 char) + context_snapshot from ReflectionOutput.
          2. BGE-M3 embed lesson text → 1024-dim tuple (ADR-064/068 D2 sustained).
          3. Construct RiskMemory frozen dataclass (TB-3a interface).
          4. persist_risk_memory(conn, memory) → risk_memory INSERT, return memory_id.

        Caller (TB-4b risk_reflector_tasks._run_reflection) owns transaction —
        this method does NOT commit (铁律 32 sustained). Caller must conn.commit()
        after success / conn.rollback() on exception.

        Args:
            output: ReflectionOutput from reflect().
            conn: psycopg2 connection (caller-injected, caller commits per 铁律 32).
            event_type: risk_memory.event_type — for reflections, the period
                category (e.g. "WeeklyReflection" / "MonthlyReflection") OR the
                triggering event type for event_reflection. Open vocab per V3 §5.4.
            symbol_id: optional stock code (None for market-wide reflections —
                weekly/monthly are market-wide; event_reflection may carry a symbol).
            event_timestamp: tz-aware datetime of the reflected event/period.
                None = output.generated_at (the reflection completion time).

        Returns:
            memory_id (BIGSERIAL) of the inserted risk_memory row.

        Raises:
            RuntimeError: embedding_factory not injected.
            RiskMemoryError: embedding dim mismatch / RiskMemory validation /
                persist failure (chained — caller catches single type).
            ValueError: invalid RiskMemory field (event_type empty / naive ts / etc).
            psycopg2.Error: SQL execution failure (caller rolls back).
        """
        from backend.qm_platform.risk.memory.interface import RiskMemory  # noqa: PLC0415
        from backend.qm_platform.risk.memory.repository import (  # noqa: PLC0415
            persist_risk_memory,
        )

        lesson = _compose_lesson_text(output)
        context_snapshot = _compose_context_snapshot(output)
        ts = event_timestamp if event_timestamp is not None else output.generated_at
        if ts.tzinfo is None:
            raise ValueError(
                "sediment_lesson: event_timestamp must be tz-aware (铁律 41 sustained)"
            )

        # BGE-M3 embed the lesson text (ADR-064/068 D2 sustained, NOT V4-Flash).
        embedding_service = self._ensure_embedding_service()
        embedding = embedding_service.encode(lesson)

        memory = RiskMemory(
            event_type=event_type,
            event_timestamp=ts,
            context_snapshot=context_snapshot,
            symbol_id=symbol_id,
            action_taken=None,  # reflections are review, not action — no action_taken
            outcome=None,  # outcome backfill 留 TB-4d+ (post-reflection P&L tracking)
            lesson=lesson,
            embedding=embedding,
        )

        memory_id = persist_risk_memory(conn, memory)
        logger.info(
            "[risk-reflector-service] lesson sedimented: memory_id=%d event_type=%s "
            "period=%s symbol=%s lesson_len=%d embedding_dim=%d",
            memory_id,
            event_type,
            output.period_label,
            symbol_id or "(market-wide)",
            len(lesson),
            len(embedding),
        )
        return memory_id


__all__ = ["RiskReflectorAgent"]
