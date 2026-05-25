"""MVP 4.3 sub-iter 1 (iter 66) — CI/CD orchestration entry skeleton.

Per docs/mvp/MVP_4_3_cicd.md §2 spec — extends Framework #9 CI/CD with
multi-phase orchestrator dataclass + Protocol.

Coordinates 5 build-time phases:
  - PRE_COMMIT: ruff check / format / pytest collection / check_llm_imports
  - PRE_PUSH: smoke (铁律 10b) / X10 cutover-bias scan / DataPipeline guard (铁律 17)
  - CI_MATRIX: multi-version Python + PostgreSQL compat
  - REGRESSION: max_diff=0 baseline gate (铁律 15)
  - REVIEW: reviewer agent findings → PR comments (OMC code-reviewer)

Platform 严格隔离 sustained (沿用 MVP 4.1/4.2 体例):
  - 0 import backend.app.* / backend.data.* / backend.engines.*
  - DI via subprocess/shell wrappers (sub-iter 2+ wiring)

铁律对齐:
  - 24 (MVP ≤ 2 页 spec)
  - 31 (Engine 纯计算 — orchestrator skeleton stateless, sub-iter 2+ 才入 subprocess)
  - 33 fail-safe (CIResult.passed=False + details capture vs raise)
  - 38 (Blueprint sustained — QPB v1.16 §Wave 4)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class CIPhase(str, Enum):
    """5 build-time CI phases (per MVP_4_3_cicd.md §2)."""

    PRE_COMMIT = "pre_commit"
    PRE_PUSH = "pre_push"
    CI_MATRIX = "ci_matrix"
    REGRESSION = "regression"
    REVIEW = "review"


@dataclass(frozen=True)
class CIResult:
    """Per-phase CI execution result (frozen — 反 silent mutation).

    All numeric / textual fields immutable after construction. details is a
    dict snapshot of phase-specific output captured at completion time.

    Attributes:
        phase: which CIPhase executed.
        passed: True iff all checks within phase succeeded.
        duration_ms: phase wall-time in milliseconds (int, no fractional).
        details: phase-specific output dict (e.g. {"pytest_summary": "61 PASS"}).
    """

    phase: CIPhase
    passed: bool
    duration_ms: int
    details: dict[str, str] = field(default_factory=dict)


class CIOrchestrator(Protocol):
    """MVP 4.3 CI orchestration interface (iter 66 stub).

    Implementations (iter 67+):
      - PreCommitOrchestrator (ruff + pytest collect + check_llm_imports)
      - PrePushOrchestrator (smoke + X10 + DataPipeline guard)
      - CIMatrixOrchestrator (multi-version compat)
      - RegressionOrchestrator (max_diff=0 baseline gate)
      - ReviewOrchestrator (reviewer findings → PR comments)
    """

    def run_phase(self, phase: CIPhase) -> CIResult:
        """Execute a single phase and return its CIResult."""
        ...

    def run_all(self) -> list[CIResult]:
        """Execute all 5 phases in canonical order; return results list."""
        ...


def all_phases_passed(results: list[CIResult]) -> bool:
    """Return True iff every CIResult.passed is True (铁律 31 pure compute).

    Empty list → True (vacuous pass; orchestrator returning 0 results is
    a separate edge handled by caller).
    """
    return all(r.passed for r in results)


def total_duration_ms(results: list[CIResult]) -> int:
    """Sum of duration_ms across all results (铁律 31 pure compute)."""
    return sum(r.duration_ms for r in results)


def phases_in_canonical_order() -> list[CIPhase]:
    """Canonical execution order for run_all() implementations.

    pre_commit → pre_push → ci_matrix → regression → review

    This order matches git workflow (commit-time → push-time → CI-time →
    regression-time → review-time) — earlier phases catch faster failures.
    """
    return [
        CIPhase.PRE_COMMIT,
        CIPhase.PRE_PUSH,
        CIPhase.CI_MATRIX,
        CIPhase.REGRESSION,
        CIPhase.REVIEW,
    ]


__all__ = [
    "CIOrchestrator",
    "CIPhase",
    "CIResult",
    "all_phases_passed",
    "phases_in_canonical_order",
    "total_duration_ms",
]
