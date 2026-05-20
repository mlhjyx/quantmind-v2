"""Plan v8 P0-9 Phase 0 inventory tool: service-layer conn.commit() violations.

Why P0-9 Phase 0:
- Iron Law 32: Service-layer 不 commit — transaction boundary 由调用方 (Router / Celery / Test) 管
- Plan v8 audit §13 finding: ~30 service-layer commit() violations
- design doc: docs/design/P0_9_SERVICE_LAYER_COMMIT_REFACTOR_DESIGN.md §4.1 calls for "Phase 0: Inventory + tooling"

Strategy (READ-ONLY inventory, autonomous-safe Phase B-1 compatible):
- Walk backend/app/services/*.py + backend/app/services/**/*.py
- AST parse: find conn.commit() / cursor.commit() / .commit() in service methods
- Surface call sites with line numbers + method context
- Categorize by tier:
  - Tier 3 (Utility): notification / audit / cache / pt_qmt_state — LOW risk refactor
  - Tier 2 (Cold): factor_compute / data_orchestrator / news services — MEDIUM risk
  - Tier 1 (Hot): execution / signal / risk core — HIGH risk
- Output: JSON + human readable + suggested refactor order

Usage:
  python scripts/audit_service_commit_violations.py
  python scripts/audit_service_commit_violations.py --json
  python scripts/audit_service_commit_violations.py --tier 3   # Filter

Exit code:
  0 = inventory complete (no breach since this is read-only audit)
  2 = script error
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = PROJECT_ROOT / "backend" / "app" / "services"


# Tier classification (per P0-9 design §2.1)
TIER_3_UTILITY_PATTERNS = (
    "notification",
    "audit",
    "cache",
    "pt_qmt_state",
    "dingtalk_alert",
)
TIER_2_COLD_PATTERNS = (
    "factor_compute",
    "data_orchestrator",
    "news/",
    "factor_onboarding",
    "fundamental_context",
)
# Tier 1 hot: anything else (execution / signal / risk core)


def classify_tier(file_path: str) -> int:
    """Classify service file into refactor tier (1=hot / 2=cold / 3=utility)."""
    file_str = file_path.replace("\\", "/")
    if any(p in file_str for p in TIER_3_UTILITY_PATTERNS):
        return 3
    if any(p in file_str for p in TIER_2_COLD_PATTERNS):
        return 2
    return 1


def find_commit_violations(file_path: Path) -> list[dict]:
    """AST parse file, find conn.commit() / cursor.commit() / .commit() patterns.

    Returns list of dicts: {line, col, method_context}.
    """
    violations = []
    try:
        text = file_path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        print(f"[WARN] AST parse failed for {file_path}: {exc}", file=sys.stderr)
        return violations

    # Track method context (current FunctionDef / AsyncFunctionDef)
    class CommitVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.method_stack: list[str] = []
            self.found: list[dict] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.method_stack.append(node.name)
            self.generic_visit(node)
            self.method_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.method_stack.append(node.name)
            self.generic_visit(node)
            self.method_stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            # Match .commit() pattern
            if isinstance(node.func, ast.Attribute) and node.func.attr == "commit":
                method_ctx = ".".join(self.method_stack) if self.method_stack else "<module>"
                # Get receiver name (conn / cursor / etc)
                receiver = "?"
                if isinstance(node.func.value, ast.Name):
                    receiver = node.func.value.id
                elif isinstance(node.func.value, ast.Attribute):
                    receiver = (
                        f"{node.func.value.value.id}.{node.func.value.attr}"
                        if isinstance(node.func.value.value, ast.Name)
                        else "?"
                    )
                self.found.append(
                    {
                        "line": node.lineno,
                        "col": node.col_offset,
                        "receiver": receiver,
                        "method": method_ctx,
                    }
                )
            self.generic_visit(node)

    visitor = CommitVisitor()
    visitor.visit(tree)
    return visitor.found


def audit() -> dict:
    """Walk services dir, build full violations inventory."""
    files_data = []
    total_violations = 0
    by_tier: dict[int, int] = {1: 0, 2: 0, 3: 0}

    for py_file in SERVICES_DIR.rglob("*.py"):
        if "__pycache__" in str(py_file) or py_file.name.startswith("_"):
            continue
        violations = find_commit_violations(py_file)
        if not violations:
            continue
        rel_path = str(py_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
        tier = classify_tier(rel_path)
        files_data.append(
            {
                "file": rel_path,
                "tier": tier,
                "violation_count": len(violations),
                "violations": violations,
            }
        )
        total_violations += len(violations)
        by_tier[tier] += len(violations)

    # Sort: Tier 3 first (refactor priority), then Tier 2, then Tier 1
    files_data.sort(key=lambda x: (x["tier"], -x["violation_count"]))

    return {
        "summary": {
            "total_files_with_violations": len(files_data),
            "total_violations": total_violations,
            "by_tier": by_tier,
            "tier_3_utility": by_tier[3],
            "tier_2_cold": by_tier[2],
            "tier_1_hot": by_tier[1],
        },
        "files": files_data,
    }


def print_human_report(result: dict, tier_filter: int | None = None) -> None:
    """Human-readable report to stdout."""
    summary = result["summary"]
    print(
        f"[P0-9 inventory] {summary['total_files_with_violations']} files, "
        f"{summary['total_violations']} violations: "
        f"T3 utility={summary['tier_3_utility']} / "
        f"T2 cold={summary['tier_2_cold']} / "
        f"T1 hot={summary['tier_1_hot']}"
    )
    print()
    print("Refactor order (Iron Law 32 enforcement, Phase J Week 4-5+):")
    print()

    for f in result["files"]:
        if tier_filter is not None and f["tier"] != tier_filter:
            continue
        tier_label = {1: "T1 hot   ", 2: "T2 cold  ", 3: "T3 utility"}[f["tier"]]
        print(f"  [{tier_label}] {f['file']} ({f['violation_count']} violations)")
        for v in f["violations"]:
            print(f"      line {v['line']:4d}: {v['receiver']}.commit() in {v['method']}()")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--tier", type=int, choices=[1, 2, 3], help="Filter by tier (1=hot, 2=cold, 3=utility)"
    )
    args = parser.parse_args()

    result = audit()

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_human_report(result, tier_filter=args.tier)

    return 0


if __name__ == "__main__":
    sys.exit(main())
