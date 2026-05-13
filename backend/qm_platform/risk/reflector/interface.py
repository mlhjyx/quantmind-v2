"""V3 §8 RiskReflector 5 维反思 — pure dataclass + Enum contract (TB-4a).

本模块 0 IO / 0 DB / 0 Redis / 0 LiteLLM (铁律 31 Platform Engine PURE).
所有 IO 由 concrete agent (TB-4a agent.py V4-Pro call) + service (留 TB-4c
input gathering) + Beat task (留 TB-4b) 承担.

对齐 V3 §8.1 line 927-933 5 维反思:
  - Detection: alert 是否及时? 漏报/误报 case? → 漏报清单 + 误报率 + 改进候选
  - Threshold: 阈值是否合理? L3 dynamic adjust 是否正确? → 阈值调整候选 + 论据
  - Action: STAGED cancel 率 / AUTO 触发是否事后正确? → 决策准确率 + STAGED default 是否需调
  - Context: L2 sentiment / fundamental 是否提供 actionable 信息? → context 命中率 + 升级候选
  - Strategy: 整体风控是否符合 user 风险偏好? → 风格漂移诊断
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ReflectionDimension(StrEnum):
    """V3 §8.1 5 维反思 — 严格对齐 V3 line 927-933 不变 enum.

    Note: str subclass for natural JSON / SQL serialization (sustained
    RegimeLabel + ActionTaken pattern from TB-2a / TB-3a).
    """

    DETECTION = "detection"
    THRESHOLD = "threshold"
    ACTION = "action"
    CONTEXT = "context"
    STRATEGY = "strategy"


class ReflectorAgentError(RuntimeError):
    """RiskReflector V4-Pro call / yaml load / JSON parse / schema 失败.

    Caller (TB-4c service / TB-4b Beat task) raises this for fail-loud 路径
    (铁律 33).
    """


@dataclass(frozen=True)
class ReflectionInput:
    """V3 §8.1 line 923 RiskReflector 上周期数据输入快照.

    Args:
      period_label: human-readable period (e.g. "W18-2026" / "2026-05" /
        "event-2026-05-14-LimitDownCluster"). Drives reflection_v1.yaml
        user_template substitution + DingTalk push 摘要 header.
      period_start: tz-aware datetime (period start inclusive). 铁律 41.
      period_end: tz-aware datetime (period end exclusive). 铁律 41.
      events_summary: V3 §8.1 line 923 — risk_event_log rows summarized.
        Free-form str (JSON / markdown table / etc.) — caller composes.
        Typical content: event_type counts + P0/P1/P2 breakdown + 漏报 list.
      plans_summary: V3 §8.1 line 923 — execution_plans status summarized.
        Free-form str. Typical: STAGED cancel rate / AUTO trigger correctness.
      pnl_outcome: V3 §8.1 line 923 — 实际 P&L outcome summarized.
        Free-form str. Typical: daily P&L deltas + drawdown peaks.
      rag_top5: V3 §8.1 line 923 — risk_memory similar lessons (top-K from
        TB-3c RiskMemoryRAG.retrieve, typically K=5). Free-form str —
        caller serializes SimilarMemoryHit list.

    Frozen + immutable per Platform Engine 体例 (sustained TB-2a RegimeLabel /
    TB-3a RiskMemory pattern).

    Note: TB-4a (本 PR) accepts pre-composed str summaries directly. TB-4c
    will extend RiskReflectorAgent service to query risk_event_log +
    execution_plans + trade_log + RAG and compose these str fields.
    """

    period_label: str
    period_start: datetime
    period_end: datetime
    events_summary: str
    plans_summary: str
    pnl_outcome: str
    rag_top5: str

    def __post_init__(self) -> None:
        if not self.period_label or not self.period_label.strip():
            raise ValueError("ReflectionInput.period_label must be non-empty")
        if self.period_start.tzinfo is None:
            raise ValueError(
                "ReflectionInput.period_start must be tz-aware (铁律 41 sustained)"
            )
        if self.period_end.tzinfo is None:
            raise ValueError(
                "ReflectionInput.period_end must be tz-aware (铁律 41 sustained)"
            )
        if self.period_end <= self.period_start:
            raise ValueError(
                f"ReflectionInput.period_end ({self.period_end.isoformat()}) "
                f"must be > period_start ({self.period_start.isoformat()})"
            )


@dataclass(frozen=True)
class ReflectionDimensionOutput:
    """V3 §8.1 line 929-933 单维反思输出.

    Args:
      dimension: ReflectionDimension enum value.
      summary: 维度反思摘要 (≤ 200 字, drives DingTalk push 摘要 per V3 §8.2
        line 946-957). Required.
      findings: 具体发现列表 (e.g. 漏报 clean list / 误报 reason). Free-form
        str list — Reflector V4-Pro may return 0-5 items per dimension.
      candidates: 改进候选列表 (e.g. "RT_RAPID_DROP_5MIN 5% → 5.5%" 阈值调整).
        Free-form str list — 0-5 items. Drives TB-4d user reply approve →
        CC auto PR generate flow.
    """

    dimension: ReflectionDimension
    summary: str
    findings: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.summary or not self.summary.strip():
            raise ValueError(
                f"ReflectionDimensionOutput[{self.dimension}].summary must be non-empty"
            )
        # Soft caps — V4-Pro may exceed, but prompt template targets ≤ 200 字 per dim.
        if len(self.summary) > 500:
            raise ValueError(
                f"ReflectionDimensionOutput[{self.dimension}].summary exceeds "
                f"500-char hard cap (prompt template targets ≤ 200), "
                f"got {len(self.summary)} chars"
            )

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict — drives lesson→risk_memory loop
        embedding text composition (留 TB-4c V4-Flash embed source)."""
        return {
            "dimension": self.dimension.value,
            "summary": self.summary,
            "findings": list(self.findings),
            "candidates": list(self.candidates),
        }


@dataclass(frozen=True)
class ReflectionOutput:
    """V3 §8.1 5 维反思完整输出 — composed by ReflectorAgent.reflect.

    Args:
      period_label: 沿用 ReflectionInput.period_label (for DingTalk header).
      generated_at: tz-aware datetime when V4-Pro completed reflection (铁律 41).
      reflections: list of exactly 5 ReflectionDimensionOutput, one per
        ReflectionDimension enum value (Detection / Threshold / Action /
        Context / Strategy). Order matches enum declaration order.
      overall_summary: ≤ 300 字 综合摘要 — drives `docs/risk_reflections/
        YYYY_WW.md` opening + DingTalk push 摘要 header per V3 §8.2.
      raw_response: V4-Pro raw text response (audit trail per ADR-022 +
        反 retroactive content edit). None pre-persist.
    """

    period_label: str
    generated_at: datetime
    reflections: tuple[ReflectionDimensionOutput, ...]
    overall_summary: str
    raw_response: str | None = None

    def __post_init__(self) -> None:
        if not self.period_label or not self.period_label.strip():
            raise ValueError("ReflectionOutput.period_label must be non-empty")
        if self.generated_at.tzinfo is None:
            raise ValueError(
                "ReflectionOutput.generated_at must be tz-aware (铁律 41 sustained)"
            )
        if len(self.reflections) != 5:
            raise ValueError(
                f"ReflectionOutput.reflections must contain exactly 5 dimensions "
                f"(V3 §8.1 line 927-933 sustained), got {len(self.reflections)}"
            )
        # Verify all 5 dimensions present (反 missing dimension silent skip
        # per LL-157 family).
        seen: set[ReflectionDimension] = set()
        for r in self.reflections:
            if r.dimension in seen:
                raise ValueError(
                    f"ReflectionOutput.reflections duplicate dimension "
                    f"{r.dimension!r} (5 维必各 1 次)"
                )
            seen.add(r.dimension)
        missing = set(ReflectionDimension) - seen
        if missing:
            raise ValueError(
                f"ReflectionOutput.reflections missing dimensions: {sorted(d.value for d in missing)} "
                f"(V3 §8.1 line 927-933 sustained 5 维必全)"
            )
        if not self.overall_summary or not self.overall_summary.strip():
            raise ValueError("ReflectionOutput.overall_summary must be non-empty")
        if len(self.overall_summary) > 600:
            raise ValueError(
                f"ReflectionOutput.overall_summary exceeds 600-char hard cap "
                f"(prompt template targets ≤ 300), got {len(self.overall_summary)} chars"
            )

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize full output for audit trail + lesson→risk_memory loop
        (留 TB-4c V4-Flash embedding source text)."""
        return {
            "period_label": self.period_label,
            "generated_at": self.generated_at.isoformat(),
            "reflections": [r.to_jsonable() for r in self.reflections],
            "overall_summary": self.overall_summary,
        }

    def get_dimension(self, dim: ReflectionDimension) -> ReflectionDimensionOutput:
        """Lookup helper — returns the ReflectionDimensionOutput for given dim.

        Raises:
            KeyError: dimension not present (defensive — should not occur
                given __post_init__ guarantees all 5 dims).
        """
        for r in self.reflections:
            if r.dimension is dim:
                return r
        raise KeyError(f"ReflectionOutput missing dimension: {dim!r}")
