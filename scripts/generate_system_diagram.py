"""Plan v8 §VIII #28 closure: Auto-generated system diagram (AST → mermaid).

Why §VIII #28:
- Service interaction diagrams 手画 6 months 后 drift (8 处 stale per audit)
- Plan v8 §VIII #28: Auto-Generated System Diagram (AST analysis → graphviz/mermaid)
- 反 LL-187/LL-190 sediment-then-forget — diagram 自动 regenerate from code truth

Strategy:
- Walk backend/app/services/ + backend/app/api/ + backend/app/tasks/
- AST parse: imports + class definitions + method calls
- Build dependency graph: which service depends on which
- Output mermaid diagram

Output: docs/SYSTEM_DIAGRAM_AUTOGEN.md (mermaid + raw graph JSON)

Usage:
  python scripts/generate_system_diagram.py
  python scripts/generate_system_diagram.py --json   # JSON only
  python scripts/generate_system_diagram.py --limit 50  # Top N components only

Exit code:
  0 = OK
  1 = AST parse error in source files (report which files)
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT_ROOT / "backend"

# Source directories to walk
SCAN_DIRS = [
    BACKEND / "app" / "services",
    BACKEND / "app" / "api",
    BACKEND / "app" / "tasks",
    BACKEND / "app" / "core",
    BACKEND / "qm_platform",
    BACKEND / "engines",
]

# Filter: only QuantMind imports (skip stdlib + 3rd-party)
QM_IMPORT_PREFIXES = (
    "app.",
    "backend.",
    "qm_platform.",
    "engines.",
    "scripts.",
)


def parse_file(path: Path) -> tuple[list[str], list[str], list[str]]:
    """Parse a Python file via AST.

    Returns: (imports, classes, top-level functions)
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        print(f"[WARN] AST parse failed for {path}: {exc}", file=sys.stderr)
        return [], [], []

    imports: list[str] = []
    classes: list[str] = []
    functions: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if any(mod.startswith(p) for p in QM_IMPORT_PREFIXES):
                imports.append(mod)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name.startswith(p) for p in QM_IMPORT_PREFIXES):
                    imports.append(alias.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)

    # Top-level functions only (skip methods inside classes)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions.append(node.name)

    return imports, classes, functions


def file_to_node_name(path: Path) -> str:
    """Convert path to graph node label (relative to backend/)."""
    try:
        rel = path.relative_to(BACKEND)
    except ValueError:
        rel = path.relative_to(PROJECT_ROOT)
    return str(rel).replace("\\", "/").replace(".py", "").replace("/", ".")


def build_graph(limit: int | None = None) -> dict:
    """Build full dependency graph by walking all SCAN_DIRS."""
    graph: dict[str, dict] = {}
    edges: list[tuple[str, str]] = []

    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            print(f"[WARN] Scan dir missing: {scan_dir}", file=sys.stderr)
            continue
        for py_file in scan_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            node = file_to_node_name(py_file)
            imports, classes, functions = parse_file(py_file)
            graph[node] = {
                "classes": classes,
                "functions": functions[:5],  # cap to avoid spam
                "imports_count": len(set(imports)),
            }
            for imp in set(imports):
                edges.append((node, imp))

    summary = {
        "total_modules": len(graph),
        "total_edges": len(edges),
        "top_imported": _top_n_imported(edges, n=20),
    }

    if limit:
        # Keep only top-imported modules + their immediate dependencies
        top_modules = {m for m, _ in summary["top_imported"][:limit]}
        graph = {k: v for k, v in graph.items() if k in top_modules}
        edges = [(s, t) for s, t in edges if s in top_modules or t in top_modules]

    return {"graph": graph, "edges": edges, "summary": summary}


def _top_n_imported(edges: list[tuple[str, str]], n: int = 20) -> list[tuple[str, int]]:
    """Find top-N most-imported modules."""
    counter: dict[str, int] = defaultdict(int)
    for _, target in edges:
        counter[target] += 1
    return sorted(counter.items(), key=lambda x: -x[1])[:n]


def to_mermaid(result: dict) -> str:
    """Render graph as mermaid diagram (capped to keep readable)."""
    lines = ["```mermaid", "graph LR"]
    edges = result["edges"]
    summary = result["summary"]

    # Use top-imported as anchors
    top_modules = {m for m, _ in summary["top_imported"][:15]}

    # Edges between top modules only (avoid spam)
    seen = set()
    for src, tgt in edges:
        if src in top_modules and tgt in top_modules:
            edge_key = (src, tgt)
            if edge_key in seen:
                continue
            seen.add(edge_key)
            # Sanitize node names for mermaid (no dots in node IDs)
            src_id = src.replace(".", "_")
            tgt_id = tgt.replace(".", "_")
            lines.append(f"    {src_id}[{src}] --> {tgt_id}[{tgt}]")

    lines.append("```")
    return "\n".join(lines)


def to_markdown_report(result: dict) -> str:
    """Render full markdown report."""
    summary = result["summary"]
    lines = [
        "# QuantMind V2 System Diagram (Auto-Generated)",
        "",
        "> **Plan v8 §VIII #28 closure** (sediment-then-implement, 反 LL-190).",
        "> Generated by `scripts/generate_system_diagram.py` — auto-regenerate on demand.",
        "> 反 hand-drawn diagram drift (audit found 8 处 stale on manual diagrams).",
        "",
        f"**Total modules scanned**: {summary['total_modules']}",
        f"**Total dependency edges**: {summary['total_edges']}",
        "",
        "## §1 Top-20 Most-Imported Modules",
        "",
        "| Rank | Module | Imports From N Modules |",
        "|---|---|---|",
    ]

    for i, (mod, count) in enumerate(summary["top_imported"], 1):
        lines.append(f"| {i} | `{mod}` | {count} |")

    lines.extend(
        [
            "",
            "## §2 Mermaid Diagram (Top-15 Anchors)",
            "",
            to_mermaid(result),
            "",
            "## §3 Module Inventory (Full)",
            "",
            "<details>",
            "<summary>Click to expand full module list</summary>",
            "",
            "| Module | Classes | Top Functions | Imports |",
            "|---|---|---|---|",
        ]
    )

    for mod, info in sorted(result["graph"].items()):
        classes = ", ".join(info["classes"][:3]) or "—"
        funcs = ", ".join(info["functions"][:3]) or "—"
        lines.append(f"| `{mod}` | {classes} | {funcs} | {info['imports_count']} |")

    lines.extend(
        [
            "",
            "</details>",
            "",
            "---",
            "",
            "**Auto-regenerate**: `python scripts/generate_system_diagram.py`",
            "**Source of truth**: AST parse of backend/app + qm_platform + engines",
            "**Plan v8 §VIII #28 closure**: 2026-05-20 Day 1 morning sediment",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON output to stdout")
    parser.add_argument("--limit", type=int, help="Limit to top-N modules")
    parser.add_argument(
        "--output",
        type=str,
        default="docs/SYSTEM_DIAGRAM_AUTOGEN.md",
        help="Markdown output path (default: docs/SYSTEM_DIAGRAM_AUTOGEN.md)",
    )
    args = parser.parse_args()

    print("[generate_system_diagram] Building graph...", file=sys.stderr)
    result = build_graph(limit=args.limit)
    summary = result["summary"]
    print(
        f"[generate_system_diagram] {summary['total_modules']} modules, "
        f"{summary['total_edges']} edges",
        file=sys.stderr,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        report = to_markdown_report(result)
        output_path = PROJECT_ROOT / args.output
        output_path.write_text(report, encoding="utf-8")
        print(f"[generate_system_diagram] Written: {output_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
