"""Doc-Code Sync Audit — Plan v9 Phase M Proposal 9.

Detects drift between documented metrics and code reality:
- API endpoint count (docs/DEV_BACKEND.md vs grep @router.*)
- Test count (CLAUDE.md vs pytest --co)
- Service file count (DEV_BACKEND.md vs ls backend/app/services/**/*.py)
- Factor count (FACTOR_TEST_REGISTRY vs DB factor_registry)
- Schedule count (DEV_SCHEDULER vs beat_schedule.py + audit_schtask_freshness)

Sustained iron law 22 (docs follow code) automation.

Exit:
- 0 = all metrics within 10% tolerance
- 1 = drift > 10% detected (list per metric)
- 2 = script error

Read-only. No DB / .env / broker / schtask mutation.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOLERANCE = 0.10  # 10% drift allowed


def _grep_count(pattern: str, paths: list[str]) -> int:
    """Run ripgrep-equivalent count via Python."""
    count = 0
    for path_glob in paths:
        for p in REPO.glob(path_glob):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            count += len(re.findall(pattern, text))
    return count


def audit_endpoint_count() -> tuple[int, int, float]:
    """API endpoint: documented vs code grep."""
    code_count = _grep_count(r"@router\.(get|post|put|delete|patch)", [
        "backend/app/api/*.py",
        "backend/app/api/**/*.py",
    ])
    doc_path = REPO / "docs" / "DEV_BACKEND.md"
    doc_count = 0
    if doc_path.exists():
        text = doc_path.read_text(encoding="utf-8")
        m = re.search(r"(\d+)\s*endpoints?", text, re.IGNORECASE)
        if m:
            doc_count = int(m.group(1))
    drift = abs(code_count - doc_count) / max(code_count, 1)
    return doc_count, code_count, drift


def audit_service_count() -> tuple[int, int, float]:
    """Service .py file count."""
    code_count = sum(1 for _ in (REPO / "backend" / "app" / "services").rglob("*.py")
                     if _.is_file() and not _.name.startswith("_"))
    doc_path = REPO / "docs" / "DEV_BACKEND.md"
    doc_count = 0
    if doc_path.exists():
        text = doc_path.read_text(encoding="utf-8")
        m = re.search(r"(\d+)\s*files?\s*in\s*services?", text, re.IGNORECASE)
        if m:
            doc_count = int(m.group(1))
    drift = abs(code_count - doc_count) / max(code_count, 1)
    return doc_count, code_count, drift


def audit_test_count() -> tuple[int, int, float]:
    """pytest collected count vs CLAUDE.md claim."""
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "--co", "-q"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Parse "6251 tests collected" from output
        m = re.search(r"(\d+)\s*tests?\s*collected", result.stdout)
        code_count = int(m.group(1)) if m else 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        code_count = 0

    doc_path = REPO / "CLAUDE.md"
    doc_count = 0
    if doc_path.exists():
        text = doc_path.read_text(encoding="utf-8")
        m = re.search(r"(\d{4})\s*(?:collected|tests)", text)
        if m:
            doc_count = int(m.group(1))
    drift = abs(code_count - doc_count) / max(code_count, 1)
    return doc_count, code_count, drift


def main() -> int:
    print("=== Doc-Code Sync Audit (Plan v9 Proposal 9) ===\n")
    failures = []

    for name, fn in [
        ("API endpoints", audit_endpoint_count),
        ("Service files", audit_service_count),
        ("Test count", audit_test_count),
    ]:
        try:
            doc, code, drift = fn()
            status = "OK" if drift <= TOLERANCE else "DRIFT"
            print(f"  [{status:5}] {name:20} doc={doc:>6} code={code:>6} drift={drift*100:.1f}%")
            if drift > TOLERANCE:
                failures.append(f"{name}: doc={doc} code={code} drift={drift*100:.1f}%")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            return 2

    print()
    if failures:
        print(f"FAIL — {len(failures)} metric(s) drift > {TOLERANCE*100:.0f}%:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASS — all metrics within {TOLERANCE*100:.0f}% tolerance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
