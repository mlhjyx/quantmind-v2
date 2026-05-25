"""Framework #9 CI/CD & Test — Platform SDK sub-package.

MVP 4.3 (iter 66+) extends the existing test interface (TestRunner /
CoverageGate / SmokeTestSuite / TestSummary) with 5-phase orchestration
(CIPhase / CIResult / CIOrchestrator) per docs/mvp/MVP_4_3_cicd.md.
"""

from .ci_matrix import (
    DEFAULT_CELL_TIMEOUT_SECONDS,
    CIMatrixOrchestrator,
    MatrixCell,
    default_matrix,
)
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
from .prepush import (
    DEFAULT_DATAPIPELINE_TIMEOUT_SECONDS,
    DEFAULT_SMOKE_TIMEOUT_SECONDS,
    X10_HARD_PATTERNS,
    PrePushCheck,
    PrePushOrchestrator,
    default_subprocess_checks,
    x10_scan,
)

__all__ = [
    "CIMatrixOrchestrator",
    "CIOrchestrator",
    "CIPhase",
    "CIResult",
    "CoverageGate",
    "DEFAULT_CELL_TIMEOUT_SECONDS",
    "DEFAULT_DATAPIPELINE_TIMEOUT_SECONDS",
    "DEFAULT_SMOKE_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "MatrixCell",
    "PreCommitCheck",
    "PreCommitOrchestrator",
    "PrePushCheck",
    "PrePushOrchestrator",
    "SmokeTestSuite",
    "TestRunner",
    "TestSummary",
    "X10_HARD_PATTERNS",
    "all_phases_passed",
    "default_checks",
    "default_matrix",
    "default_subprocess_checks",
    "phases_in_canonical_order",
    "total_duration_ms",
    "x10_scan",
]
