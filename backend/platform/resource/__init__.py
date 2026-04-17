"""Framework #11 Resource Orchestration — Platform SDK sub-package."""
from backend.platform.resource.interface import (
    AdmissionController,
    AdmissionResult,
    BudgetGuard,
    ResourceManager,
    ResourceSnapshot,
    requires_resources,
)

__all__ = [
    "ResourceManager",
    "AdmissionController",
    "BudgetGuard",
    "AdmissionResult",
    "ResourceSnapshot",
    "requires_resources",
]
