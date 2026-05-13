"""V3 §8 RiskReflectorAgent — application orchestration skeleton (TB-4a sprint).

Per V3 §11.2 line 1228 location SSOT: this module composes the Engine PURE
ReflectorAgent V4-Pro wrapper (qm_platform.risk.reflector.agent) with caller-
supplied ReflectionInput. TB-4a is the **skeleton scope** — caller passes
pre-composed input strs directly.

TB-4c will extend this service with input gathering from real DB tables:
  - risk_event_log (last period) → events_summary
  - execution_plans (last period STAGED + AUTO) → plans_summary
  - trade_log + position deltas → pnl_outcome
  - RiskMemoryRAG.retrieve (TB-3c) → rag_top5

TB-4b will add Celery Beat 3 cadence wire calling this service.

TB-4d will add `docs/risk_reflections/` markdown sediment + DingTalk push 摘要 +
user reply approve → CC auto PR generate flow.

DI factory pattern sustained (TB-2c IndicatorsProvider + TB-3b model_factory):
  - router_factory: Callable[[], _RouterProtocol] for lazy router construction
    (allows test injection of stub router without eager .get_llm_router() call)

铁律 31 alignment:
  - This module is `app/services/risk/`, NOT `qm_platform/risk/reflector/` —
    orchestration explicitly lives outside Engine PURE side per V3 §11.2
    line 1228. Engine PURE wrapper (ReflectorAgent) is composed here.

关联 V3: §8 (RiskReflector) / §11.2 line 1228 (RiskReflectorAgent location SSOT)
关联 ADR: ADR-031 (LiteLLMRouter) / ADR-036 (V4-Pro mapping) / ADR-064 / ADR-069 候选
关联 铁律: 17 (DataPipeline N/A 本 TB-4a no DB) / 24 (单一职责 skeleton) /
  31 (orchestration outside PURE) / 32 (Service 不 commit — N/A no DB) /
  33 (fail-loud propagates from ReflectorAgent) / 41 (tz-aware in caller)
关联 LL: LL-098 X10 / LL-159 (preflight) / LL-160 (DI factory)
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
    from backend.qm_platform.risk.reflector.agent import _RouterProtocol

logger = logging.getLogger(__name__)


@dataclass
class RiskReflectorAgent:
    """V3 §8 RiskReflector orchestration — Application layer skeleton.

    TB-4a scope: thin pass-through to underlying ReflectorAgent. Caller
    supplies fully-composed ReflectionInput.

    TB-4c scope (留): extends with `gather_input(period_start, period_end)`
    method that queries risk_event_log + execution_plans + trade_log + RAG
    and composes ReflectionInput.

    Args:
        router_factory: Callable returning _RouterProtocol per call. Caller
            owns router lifecycle (e.g. via `get_llm_router()` from
            qm_platform.llm.bootstrap). Lazy invocation — router constructed
            on first reflect() call, then cached in self._agent.
        agent_factory: optional override for tests — Callable[[router], ReflectorAgent]
            returning a pre-constructed ReflectorAgent (e.g. with stub prompt path).
            None = default ReflectorAgent(router) wrapping production prompt.

    Frozen=False so service can lazy-cache the ReflectorAgent after first
    reflect() call (sustained TB-3b BGEM3EmbeddingService lazy cache 体例).
    """

    router_factory: Callable[[], _RouterProtocol]
    agent_factory: Callable[[object], ReflectorAgent] | None = None
    _agent: ReflectorAgent | None = field(default=None, init=False, repr=False)

    def _ensure_agent(self) -> ReflectorAgent:
        """Lazy construct + cache ReflectorAgent (sustained TB-3b lazy load 体例).

        First call: invokes router_factory() + constructs ReflectorAgent.
        Subsequent calls: returns cached instance.

        Raises:
            RuntimeError: router_factory failure (propagated from caller).
        """
        if self._agent is None:
            router = self.router_factory()
            if self.agent_factory is not None:
                self._agent = self.agent_factory(router)
            else:
                self._agent = ReflectorAgent(router=router)
        return self._agent

    def reflect(
        self,
        input_data: ReflectionInput,
        *,
        decision_id: str | None = None,
        now: datetime | None = None,
    ) -> ReflectionOutput:
        """V3 §8.1 5 维反思 — delegate to underlying ReflectorAgent (TB-4a thin pass-through).

        TB-4c will add a parallel `gather_and_reflect(period_start, period_end)`
        method that gathers input from DB before reflecting.

        Args:
            input_data: caller-composed ReflectionInput (period + summaries).
            decision_id: optional audit trace UUID-like.
            now: tz-aware datetime for ReflectionOutput.generated_at. None =
                current UTC.

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


__all__ = ["RiskReflectorAgent"]
