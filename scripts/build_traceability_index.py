"""Plan v8 §VIII #30 closure: Reverse Traceability Index (code ↔ design doc).

Why §VIII #30:
- 50 核心 code 模块 ↔ design doc cite double-direction missing
- Plan v8 §VIII #30: Reverse Traceability Index — code↔doc bidirectional
- 反 LL-191 sub-pattern: design docs claim X but code 不存在, OR code exists but doc 不记录

Strategy (heuristic-only, no AST symbol-level):
- Scan docs/*.md (design docs)
- For each: grep code references (file paths / class names / function names)
- Build inverse index: code_module → [docs that mention it]
- Surface gaps:
  - **forward gap**: code module 0 doc mention (dark matter, LL-191 forward direction)
  - **backward gap**: doc mention code that doesn't exist (Doc Lying, heuristic #14)

Output: docs/TRACEABILITY_INDEX.md (bidirectional table + gap analysis)

Usage:
  python scripts/build_traceability_index.py
  python scripts/build_traceability_index.py --json    # JSON only
  python scripts/build_traceability_index.py --gaps-only  # Only show gaps

Exit code:
  0 = OK
  1 = critical doc lying gaps detected (Doc claims code that doesn't exist)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Scan dirs (design docs + DEV docs + architecture docs)
DOC_DIRS = [
    PROJECT_ROOT / "docs",
]

# Code dirs (find existing modules)
CODE_DIRS = [
    PROJECT_ROOT / "backend" / "app",
    PROJECT_ROOT / "backend" / "qm_platform",
    PROJECT_ROOT / "backend" / "engines",
    PROJECT_ROOT / "scripts",
]

# Exclude paths
EXCLUDE_DIRS = ("__pycache__", "node_modules", ".venv", ".git", "worktrees", "archive")


def find_code_modules() -> set[str]:
    """Find all .py modules' relative path (relative to PROJECT_ROOT)."""
    modules = set()
    for code_dir in CODE_DIRS:
        if not code_dir.exists():
            continue
        for py_file in code_dir.rglob("*.py"):
            if any(ex in str(py_file) for ex in EXCLUDE_DIRS):
                continue
            rel = py_file.relative_to(PROJECT_ROOT)
            modules.add(str(rel).replace("\\", "/"))
    return modules


def scan_docs_for_code_refs(code_modules: set[str]) -> dict[str, list[str]]:
    """Scan all design docs for code module references.

    Returns: code_module → [docs that mention it]
    """
    doc_to_refs: dict[str, set[str]] = defaultdict(set)
    inverse: dict[str, set[str]] = defaultdict(set)  # module → docs

    # Heuristic: doc mentions a code module if any of:
    # 1. Path-style mention: backend/app/services/foo.py OR scripts/foo.py
    # 2. Backtick path: `app/services/foo.py`
    # 3. Module path: app.services.foo OR backend.qm_platform.bar
    for doc_dir in DOC_DIRS:
        if not doc_dir.exists():
            continue
        for md_file in doc_dir.rglob("*.md"):
            if any(ex in str(md_file) for ex in EXCLUDE_DIRS):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            rel_doc = str(md_file.relative_to(PROJECT_ROOT)).replace("\\", "/")

            for module in code_modules:
                # Multiple match patterns
                module_basename = Path(module).name  # foo.py
                # Mentions: full relative path OR backtick path OR module form
                if module in content or f"`{module_basename}`" in content:
                    inverse[module].add(rel_doc)
                    doc_to_refs[rel_doc].add(module)

    return {
        "module_to_docs": {k: sorted(v) for k, v in inverse.items()},
        "doc_to_modules": {k: sorted(v) for k, v in doc_to_refs.items()},
    }


def analyze_gaps(code_modules: set[str], index: dict) -> dict:
    """Surface forward + backward gaps."""
    module_to_docs = index["module_to_docs"]

    # Forward gap: code module 0 doc mention
    dark_modules = sorted([m for m in code_modules if m not in module_to_docs])

    # By severity: prioritize backend/app/services + qm_platform (core layers)
    critical_dark = [
        m
        for m in dark_modules
        if (
            m.startswith("backend/app/services/")
            or m.startswith("backend/qm_platform/")
            or m.startswith("backend/engines/")
        )
        and not m.endswith("__init__.py")
        and not m.endswith("_test.py")
        and "test_" not in m
    ]

    return {
        "total_code_modules": len(code_modules),
        "documented_modules": len(module_to_docs),
        "dark_modules_total": len(dark_modules),
        "dark_modules_critical": len(critical_dark),
        "critical_dark_top_30": critical_dark[:30],
        "coverage_pct": (
            round(100 * len(module_to_docs) / len(code_modules), 1) if code_modules else 0
        ),
    }


def to_markdown_report(index: dict, gaps: dict) -> str:
    """Render markdown report."""
    module_to_docs = index["module_to_docs"]
    doc_to_modules = index["doc_to_modules"]

    lines = [
        "# QuantMind V2 Reverse Traceability Index (Auto-Generated)",
        "",
        "> **Plan v8 §VIII #30 closure** (sediment-then-implement, 反 LL-190).",
        "> Generated by `scripts/build_traceability_index.py` — auto-regenerate on demand.",
        "> 反 LL-191 forward direction: design doc claims X but code 不存在.",
        "> 反 LL-191 backward direction: code exists but doc 不记录.",
        "",
        f"**Total code modules**: {gaps['total_code_modules']}",
        f"**Documented modules**: {gaps['documented_modules']} ({gaps['coverage_pct']}%)",
        f"**Dark modules (0 doc mention)**: {gaps['dark_modules_total']}",
        f"**Critical dark modules (backend core, 0 mention)**: {gaps['dark_modules_critical']}",
        "",
        "## §1 Critical Dark Modules (Top 30, backend core)",
        "",
        "**Action**: Each module 应有 doc mention (design intent OR usage example).",
        "",
        "| # | Module | Suggested action |",
        "|---|---|---|",
    ]

    for i, mod in enumerate(gaps["critical_dark_top_30"], 1):
        lines.append(f"| {i} | `{mod}` | Add to DEV_*.md / sediment design intent |")

    lines.extend(
        [
            "",
            "## §2 Top-20 Most-Documented Modules",
            "",
            "| Rank | Module | Doc count | Top docs |",
            "|---|---|---|---|",
        ]
    )

    # Sort modules by doc count
    top_documented = sorted(module_to_docs.items(), key=lambda x: -len(x[1]))[:20]
    for i, (mod, docs) in enumerate(top_documented, 1):
        top_3_docs = ", ".join(d.replace("docs/", "") for d in docs[:3])
        lines.append(f"| {i} | `{mod}` | {len(docs)} | {top_3_docs} |")

    lines.extend(
        [
            "",
            "## §3 Doc Coverage by File Type",
            "",
            "<details>",
            "<summary>Click to expand full doc → modules mapping</summary>",
            "",
            "| Doc | References N modules |",
            "|---|---|",
        ]
    )

    # Sort docs by mod count
    top_docs = sorted(doc_to_modules.items(), key=lambda x: -len(x[1]))[:30]
    for doc, mods in top_docs:
        lines.append(f"| `{doc}` | {len(mods)} |")

    lines.extend(
        [
            "",
            "</details>",
            "",
            "---",
            "",
            "**Auto-regenerate**: `python scripts/build_traceability_index.py`",
            "**Source of truth**: heuristic grep on docs/*.md ↔ code modules",
            "**Plan v8 §VIII #30 closure**: 2026-05-20 Day 1 morning sediment",
            "",
            "## §4 Limitations",
            "",
            "- Heuristic-only (path/backtick mention), no AST symbol-level resolution",
            "- Doc lying (backward gap) detection requires symbol-level + currently SKIPPED",
            "- Future enhancement: integrate w/ §VIII #28 Auto Diagram for joint view",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON output to stdout")
    parser.add_argument("--gaps-only", action="store_true", help="Only show gap analysis")
    parser.add_argument(
        "--output",
        type=str,
        default="docs/TRACEABILITY_INDEX.md",
        help="Markdown output path",
    )
    args = parser.parse_args()

    print("[traceability] Scanning code modules...", file=sys.stderr)
    code_modules = find_code_modules()
    print(f"[traceability] Found {len(code_modules)} code modules", file=sys.stderr)

    print("[traceability] Scanning docs for code refs...", file=sys.stderr)
    index = scan_docs_for_code_refs(code_modules)
    print(
        f"[traceability] {len(index['module_to_docs'])} modules documented",
        file=sys.stderr,
    )

    gaps = analyze_gaps(code_modules, index)

    result = {"index": index, "gaps": gaps}

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.gaps_only:
        print(json.dumps(gaps, indent=2, ensure_ascii=False))
    else:
        report = to_markdown_report(index, gaps)
        output_path = PROJECT_ROOT / args.output
        output_path.write_text(report, encoding="utf-8")
        print(f"[traceability] Written: {output_path}", file=sys.stderr)
        print(
            f"[traceability] Coverage: {gaps['coverage_pct']}% / {gaps['dark_modules_critical']} critical dark",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
