"""V3 §8 L5 RiskReflector — Engine PURE side (TB-4 sprint chain).

Modules (TB-4 chunked sub-PR roadmap per Plan v0.2 §A):
  - interface (TB-4a, 本 PR): 纯 dataclass + Enum 契约 (0 IO / 0 DB / 0 LiteLLM)
  - agent (TB-4a, 本 PR): ReflectorAgent V4-Pro single-call wrapper (yaml load +
    LLM call + JSON parse + 5 维 validation) — Engine PURE per 铁律 31

Application orchestration (NOT in this package, per V3 §11.2 line 1228 SSOT):
  - app/services/risk/risk_reflector_agent.py (TB-4a 本 PR skeleton): RiskReflectorAgent —
    composes ReflectorAgent + (留 TB-4c) input gathering from risk_event_log +
    risk_memory + execution_plans + P&L outcome

Beat dispatch (留 TB-4b):
  - app/tasks/risk_reflector_tasks.py: Celery Beat 3 cadence (Sunday 19:00 周复盘 +
    月 1 日 09:00 月复盘 + event-triggered 24h post-event)

lesson→risk_memory 闭环 (留 TB-4c):
  - V4-Pro reflection outcome → V4-Flash 1024-dim embedding → INSERT risk_memory
    via DataPipeline 铁律 17

user reply approve → CC 自动 PR generate flow (留 TB-4d):
  - DingTalk webhook receiver patch (sustain Tier A S8 sub-PR 8b PR #248 体例)

Architecture (per V3 §8 + ADR-064 D2 sustained + V3 §11.2 line 1228 SSOT):
  - 本 package = Engine PURE side (interface + agent yaml/LLM/parse)
  - app/services/risk/risk_reflector_agent.py = Application orchestration
  - Beat caller (TB-4b 留) = Cadence dispatch

关联 V3: §8 (RiskReflector 5 维反思) / §11.2 line 1228 (RiskReflectorAgent location)
关联 ADR: ADR-036 (V4-Pro mapping) / ADR-064 (Plan v0.2 D2) / ADR-069 候选 (TB-4 sprint)
关联 铁律: 17 (DataPipeline 入库 — N/A 本 TB-4a) / 22 (doc 同步) / 24 (单一职责) /
  31 (Engine PURE) / 33 (fail-loud JSON parse) / 34 (yaml prompt SSOT path) /
  41 (timezone-aware datetime in caller side)
"""

from __future__ import annotations

from .agent import ReflectorAgent, ReflectorAgentError
from .interface import (
    ReflectionDimension,
    ReflectionDimensionOutput,
    ReflectionInput,
    ReflectionOutput,
)

__all__ = [
    "ReflectionDimension",
    "ReflectionDimensionOutput",
    "ReflectionInput",
    "ReflectionOutput",
    "ReflectorAgent",
    "ReflectorAgentError",
]
