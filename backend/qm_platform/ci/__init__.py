"""Framework #9 CI/CD & Test — Platform SDK sub-package.

MVP 4.3 (iter 66+) extends the existing test interface (TestRunner /
CoverageGate / SmokeTestSuite / TestSummary) with 5-phase orchestration
(CIPhase / CIResult / CIOrchestrator) per docs/mvp/MVP_4_3_cicd.md.
"""

from .interface import (
    CoverageGate,
    SmokeTestSuite,
    TestRunner,
    TestSummary,
)
from .orchestrator import (
    CIOrchestrator,
    CIPhase,
    CIResult,
    all_phases_passed,
    phases_in_canonical_order,
    total_duration_ms,
)
from .precommit import (
    DEFAULT_TIMEOUT_SECONDS,
    PreCommitCheck,
    PreCommitOrchestrator,
    default_checks,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "CIOrchestrator",
    "CIPhase",
    "CIResult",
    "CoverageGate",
    "PreCommitCheck",
    "PreCommitOrchestrator",
    "SmokeTestSuite",
    "TestRunner",
    "TestSummary",
    "all_phases_passed",
    "default_checks",
    "phases_in_canonical_order",
    "total_duration_ms",
]
