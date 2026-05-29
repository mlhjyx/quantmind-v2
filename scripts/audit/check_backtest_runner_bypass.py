"""Guard against new direct backtest engine calls outside PlatformBacktestRunner.

The legacy engine functions remain public for engine tests and for a bounded set
of historical one-off research scripts. New app/script callers should use
`backend.qm_platform.backtest.runner.PlatformBacktestRunner` so API, CLI, and
research paths do not silently drift again.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_FILE = REPO_ROOT / "scripts" / "audit" / "backtest_runner_bypass_allowlist.txt"
SCAN_ROOTS = ("backend", "scripts")
TARGET_FUNCTIONS = frozenset({"run_hybrid_backtest", "run_composite_backtest"})
EXCLUDED_PREFIXES = (
    "backend/engines/backtest/",
    "backend/tests/",
    "scripts/archive/",
)
EXCLUDED_FILES = frozenset(
    {
        "backend/engines/backtest_engine.py",
        "backend/qm_platform/backtest/runner.py",
    }
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    symbol: str
    kind: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.kind} {self.symbol}"


def _repo_rel(path: Path, repo_root: Path = REPO_ROOT) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def load_allowlist(path: Path = ALLOWLIST_FILE) -> set[str]:
    if not path.exists():
        return set()
    entries: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line.replace("\\", "/"))
    return entries


def should_scan(path: Path, repo_root: Path, allowlist: set[str]) -> bool:
    rel = _repo_rel(path, repo_root)
    if rel in allowlist or rel in EXCLUDED_FILES:
        return False
    return not any(rel.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def iter_python_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if root.exists():
            files.extend(root.rglob("*.py"))
    return sorted(files)


def find_violations(path: Path, repo_root: Path = REPO_ROOT) -> list[Violation]:
    rel = _repo_rel(path, repo_root)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except SyntaxError as exc:
        return [Violation(rel, exc.lineno or 1, "python", "syntax_error")]

    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported = {alias.name for alias in node.names}
            direct_imports = TARGET_FUNCTIONS.intersection(imported)
            if direct_imports:
                for symbol in sorted(direct_imports):
                    violations.append(Violation(rel, node.lineno, symbol, "direct_import"))
        elif isinstance(node, ast.Call):
            symbol = _call_symbol(node.func)
            if symbol in TARGET_FUNCTIONS:
                violations.append(Violation(rel, node.lineno, symbol, "direct_call"))
    return violations


def _call_symbol(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def scan_repo(
    repo_root: Path = REPO_ROOT,
    allowlist_path: Path | None = None,
) -> list[Violation]:
    allowlist = load_allowlist(allowlist_path or repo_root / ALLOWLIST_FILE.relative_to(REPO_ROOT))
    violations: list[Violation] = []
    for path in iter_python_files(repo_root):
        if should_scan(path, repo_root, allowlist):
            violations.extend(find_violations(path, repo_root))
    return violations


def main() -> int:
    violations = scan_repo()
    if violations:
        print("[backtest-runner-bypass] BLOCK: direct engine calls found outside allowlist.")
        print("Use PlatformBacktestRunner, or document a historical-research exception in:")
        print(f"  {ALLOWLIST_FILE.relative_to(REPO_ROOT).as_posix()}")
        for violation in violations:
            print(f"  {violation.format()}")
        return 1
    print("[backtest-runner-bypass] PASS: no unallowlisted direct engine calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
