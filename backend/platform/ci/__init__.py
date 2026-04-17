"""Framework #9 CI/CD & Test — Platform SDK sub-package."""
from .interface import (
    CoverageGate,
    SmokeTestSuite,
    TestRunner,
    TestSummary,
)

__all__ = [
    "TestRunner",
    "CoverageGate",
    "SmokeTestSuite",
    "TestSummary",
]
