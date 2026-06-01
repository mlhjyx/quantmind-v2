"""MVP 4.3 sub-iter 5 (iter 70) — RegressionOrchestrator.

Fourth concrete CIOrchestrator enforcing 铁律 15 max_diff=0 regression gate.
Pure-Python validation of committed regression result artifacts, with
baseline-vs-actual comparison support for callers that provide paired files.
Mirrors `cache/baseline/` existing convention.

Per 铁律 15: every backtest must be exactly reproducible — `(config_yaml_hash,
git_commit) + max_diff=0` is the hard gate. Any non-zero numeric difference
between baseline and actual blocks merge.

沿用 precommit/prepush/ci_matrix 体例: DI hook (file_loader) + frozen check
spec + 铁律 33 fail-soft tier-2.

Platform 严格隔离 sustained: 0 import backend.app.* (file I/O only).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.qm_platform.ci.orchestrator import CIPhase, CIResult

MAX_DIFF_THRESHOLD: float = 0.0  # 铁律 15 hard: any non-zero diff blocks merge

# DI hook: load file → return list-of-dicts (CSV rows) or generic dict (JSON).
# Tests inject in-memory data to avoid filesystem dependency.
FileLoader = Callable[[Path], dict | list]


def _default_file_loader(path: Path) -> dict | list:
    """Default loader — reads JSON file via stdlib (CSV not handled by default).

    Production deployments using CSV regression dumps can pass a custom loader
    that wraps csv.DictReader. The default JSON-only loader keeps the orchestrator
    dependency-free (no pandas) while still covering the most common case.
    """
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@dataclass(frozen=True)
class RegressionPair:
    """A single regression baseline/actual pair (frozen — 反 silent mutation).

    Attributes:
        label: human-readable identifier (used in CIResult.details key).
        baseline_path: Path to baseline file (JSON by default).
        actual_path: Path to actual / fresh-run file (same format).
    """

    label: str
    baseline_path: Path
    actual_path: Path


def default_pairs() -> list[RegressionPair]:
    """Canonical regression artifacts (per 铁律 15 — 5yr + 12yr backtests).

    The committed `regression_result_*.json` files already contain run-level
    `max_diff` evidence. Pointing baseline and actual to the same artifact makes
    GitHub CI blocking-capable without relying on uncommitted fresh-run dumps.
    """
    cache_root = Path("cache") / "baseline"
    five_year = cache_root / "regression_result_5yr.json"
    twelve_year = cache_root / "regression_result_12yr.json"
    return [
        RegressionPair(
            label="backtest_5yr",
            baseline_path=five_year,
            actual_path=five_year,
        ),
        RegressionPair(
            label="backtest_12yr",
            baseline_path=twelve_year,
            actual_path=twelve_year,
        ),
    ]


def _flatten_numeric(obj: dict | list, prefix: str = "") -> dict[str, float]:
    """Recursively flatten dict/list → flat dict of numeric leaves.

    Non-numeric leaves are silently dropped (regression compares numeric metrics
    only; string fields like git_commit are out-of-scope here).
    """
    out: dict[str, float] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict | list):
                out.update(_flatten_numeric(v, key))
            elif isinstance(v, int | float) and not isinstance(v, bool):
                out[key] = float(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}[{i}]"
            if isinstance(v, dict | list):
                out.update(_flatten_numeric(v, key))
            elif isinstance(v, int | float) and not isinstance(v, bool):
                out[key] = float(v)
    return out


def compute_max_diff(baseline: dict | list, actual: dict | list) -> tuple[float, str | None]:
    """Compute max(|baseline - actual|) across all numeric leaves.

    Returns:
        (max_diff, offending_key). offending_key is None when diff == 0.0.
        Missing keys on either side count as INF diff (mismatched shape).
    """
    b_flat = _flatten_numeric(baseline)
    a_flat = _flatten_numeric(actual)

    keys = set(b_flat) | set(a_flat)
    if not keys:
        return 0.0, None  # both empty → vacuous match

    max_diff = 0.0
    offending: str | None = None
    for key in keys:
        if key not in b_flat or key not in a_flat:
            # Shape mismatch — return early with infinite diff
            return float("inf"), key
        d = abs(b_flat[key] - a_flat[key])
        if d > max_diff:
            max_diff = d
            offending = key
    return max_diff, offending if max_diff > 0 else None


def recorded_max_diff(artifact: dict | list) -> tuple[float, str | None]:
    """Read recorded max_diff evidence from a committed regression artifact."""
    flat = _flatten_numeric(artifact)
    candidates = {
        key: value
        for key, value in flat.items()
        if key.split(".")[-1] == "max_diff" or key.split(".")[-1].endswith("_max_diff")
    }
    if not candidates:
        return float("inf"), "max_diff"

    offending, value = max(candidates.items(), key=lambda item: abs(item[1]))
    max_diff = abs(value)
    return max_diff, offending if max_diff > 0 else None


class RegressionOrchestrator:
    """Enforces 铁律 15 max_diff=0 baseline gate.

    Args:
        pairs: regression pair list (default = default_pairs()).
        file_loader: FileLoader DI hook (default reads JSON via stdlib).
        threshold: float gate (default = MAX_DIFF_THRESHOLD = 0.0).
    """

    def __init__(
        self,
        pairs: list[RegressionPair] | None = None,
        file_loader: FileLoader | None = None,
        threshold: float = MAX_DIFF_THRESHOLD,
    ) -> None:
        self.pairs = pairs if pairs is not None else default_pairs()
        self.file_loader = file_loader if file_loader is not None else _default_file_loader
        self.threshold = threshold

    def run_phase(self, phase: CIPhase) -> CIResult:
        """Iterate regression pairs; aggregate max_diff per pair.

        Only CIPhase.REGRESSION is processed; other phases return skip result.
        """
        if phase != CIPhase.REGRESSION:
            return CIResult(
                phase=phase,
                passed=True,
                duration_ms=0,
                details={"skipped": phase.value},
            )

        start = time.monotonic()
        details: dict[str, str] = {
            "pair_count": str(len(self.pairs)),
            "threshold": str(self.threshold),
        }
        all_passed = True

        for pair in self.pairs:
            pair_start = time.monotonic()
            try:
                if pair.baseline_path == pair.actual_path:
                    artifact = self.file_loader(pair.baseline_path)
                    max_diff, offending = recorded_max_diff(artifact)
                else:
                    baseline = self.file_loader(pair.baseline_path)
                    actual = self.file_loader(pair.actual_path)
                    max_diff, offending = compute_max_diff(baseline, actual)
                pair_passed = max_diff <= self.threshold
                parts = [f"max_diff={max_diff}"]
                if offending is not None:
                    parts.append(f"key={offending}")
                details[pair.label] = " ".join(parts)
                if not pair_passed:
                    all_passed = False
            except FileNotFoundError as e:
                details[pair.label] = f"FILE_MISSING: {e.filename or str(e)}"
                all_passed = False
            except (OSError, json.JSONDecodeError, ValueError) as e:
                # silent_ok: IO / decode error captured (铁律 33)
                details[pair.label] = f"LOAD_ERROR: {e}"
                all_passed = False
            pair_elapsed_ms = int((time.monotonic() - pair_start) * 1000)
            details[f"{pair.label}_duration_ms"] = str(pair_elapsed_ms)

        total_ms = int((time.monotonic() - start) * 1000)
        return CIResult(
            phase=CIPhase.REGRESSION,
            passed=all_passed,
            duration_ms=total_ms,
            details=details,
        )

    def run_all(self) -> list[CIResult]:
        """Single-phase orchestrator — list of length 1."""
        return [self.run_phase(CIPhase.REGRESSION)]


__all__ = [
    "FileLoader",
    "MAX_DIFF_THRESHOLD",
    "RegressionOrchestrator",
    "RegressionPair",
    "compute_max_diff",
    "default_pairs",
    "recorded_max_diff",
]
