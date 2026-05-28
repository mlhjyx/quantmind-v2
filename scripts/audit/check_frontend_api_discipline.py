"""Check frontend API discipline without comment-only false positives.

Default scope is production frontend source under ``frontend/src``. The only
production file allowed to import axios directly is ``frontend/src/api/client.ts``;
all other production modules should use the apiClient wrapper layer.

Read-only audit script: no filesystem writes, no network, no DB, no broker calls.
Exit codes:
  0 = clean
  1 = raw axios import/require found outside allowlist
  2 = script usage/runtime error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
ALLOWED_PRODUCTION_IMPORTS = {Path("api/client.ts").as_posix()}
SOURCE_SUFFIXES = {".ts", ".tsx", ".mts", ".cts"}

IMPORT_FROM_RE = re.compile(
    r"^\s*import\s+(?:type\s+)?(?:[^;\n]|\n)*?\bfrom\s*['\"]axios['\"]\s*;?",
    re.MULTILINE,
)
SIDE_EFFECT_IMPORT_RE = re.compile(r"^\s*import\s*['\"]axios['\"]\s*;?", re.MULTILINE)
REQUIRE_RE = re.compile(r"\brequire\s*\(\s*['\"]axios['\"]\s*\)")
DYNAMIC_IMPORT_RE = re.compile(r"\bimport\s*\(\s*['\"]axios['\"]\s*\)")


@dataclass(frozen=True)
class Violation:
    """A raw axios usage outside the production allowlist."""

    file: str
    line: int
    kind: str
    snippet: str


def _strip_comments_preserve_lines(text: str) -> str:
    """Remove TS/JS comments while preserving strings and line numbers."""
    out: list[str] = []
    i = 0
    state = "normal"
    quote = ""
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if state == "line_comment":
            if ch == "\n":
                out.append(ch)
                state = "normal"
            else:
                out.append(" ")
            i += 1
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                out.extend("  ")
                state = "normal"
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        if state == "string":
            out.append(ch)
            if ch == "\\":
                if i + 1 < len(text):
                    out.append(text[i + 1])
                    i += 2
                    continue
            elif ch == quote:
                state = "normal"
                quote = ""
            i += 1
            continue

        if ch in ("'", '"', "`"):
            state = "string"
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            out.extend("  ")
            state = "line_comment"
            i += 2
            continue
        if ch == "/" and nxt == "*":
            out.extend("  ")
            state = "block_comment"
            i += 2
            continue
        out.append(ch)
        i += 1

    return "".join(out)


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _snippet_at_line(text: str, line_no: int) -> str:
    lines = text.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()
    return ""


def _is_test_path(path: Path) -> bool:
    return "__tests__" in path.parts or path.name.endswith((".test.ts", ".test.tsx", ".spec.ts"))


def _iter_source_files(frontend_src: Path, include_tests: bool) -> list[Path]:
    files: list[Path] = []
    for path in frontend_src.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        if not include_tests and _is_test_path(path.relative_to(frontend_src)):
            continue
        files.append(path)
    return sorted(files)


def _violations_in_file(path: Path, frontend_src: Path) -> list[Violation]:
    raw = path.read_text(encoding="utf-8")
    text = _strip_comments_preserve_lines(raw)
    rel = path.relative_to(frontend_src).as_posix()
    if rel in ALLOWED_PRODUCTION_IMPORTS:
        return []

    checks = [
        ("import-from", IMPORT_FROM_RE),
        ("side-effect-import", SIDE_EFFECT_IMPORT_RE),
        ("require", REQUIRE_RE),
        ("dynamic-import", DYNAMIC_IMPORT_RE),
    ]
    violations: list[Violation] = []
    seen: set[tuple[int, str]] = set()
    for kind, pattern in checks:
        for match in pattern.finditer(text):
            line = _line_for_offset(text, match.start())
            key = (line, kind)
            if key in seen:
                continue
            seen.add(key)
            violations.append(
                Violation(
                    file=rel,
                    line=line,
                    kind=kind,
                    snippet=_snippet_at_line(raw, line),
                )
            )
    return violations


def scan(frontend_src: Path = DEFAULT_FRONTEND_SRC, include_tests: bool = False) -> list[Violation]:
    """Return raw axios usage violations for frontend production code."""
    if not frontend_src.exists():
        raise FileNotFoundError(f"frontend source not found: {frontend_src}")
    violations: list[Violation] = []
    for path in _iter_source_files(frontend_src, include_tests=include_tests):
        violations.extend(_violations_in_file(path, frontend_src))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check frontend raw axios import discipline.")
    parser.add_argument("--root", default=str(DEFAULT_FRONTEND_SRC), help="frontend src directory")
    parser.add_argument("--include-tests", action="store_true", help="also scan __tests__ files")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    args = parser.parse_args(argv)

    try:
        violations = scan(Path(args.root), include_tests=args.include_tests)
    except Exception as exc:  # noqa: BLE001 - top-level audit script fail-loud
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"violations": [asdict(v) for v in violations]}, indent=2))
    elif violations:
        print("[frontend-api-discipline] BLOCK: raw axios usage outside frontend/src/api/client.ts")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}: {violation.kind}: {violation.snippet}")
        print("  Fix: import apiClient from frontend/src/api/client.ts via the src/api layer.")
    else:
        print("[frontend-api-discipline] PASS: production raw axios imports are SSOT-clean")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
