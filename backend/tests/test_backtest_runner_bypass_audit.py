from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.audit import check_backtest_runner_bypass as scanner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "audit" / "check_backtest_runner_bypass.py"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_blocks_new_direct_backtest_engine_call(tmp_path):
    target = tmp_path / "scripts" / "new_research.py"
    _write(
        target,
        "\n".join(
            [
                "from engines.backtest_engine import run_hybrid_backtest",
                "def run():",
                "    return run_hybrid_backtest(None, {}, None, None)",
            ]
        ),
    )

    violations = scanner.scan_repo(tmp_path, allowlist_path=tmp_path / "missing.txt")

    assert [v.symbol for v in violations] == ["run_hybrid_backtest", "run_hybrid_backtest"]
    assert {v.kind for v in violations} == {"direct_import", "direct_call"}
    assert violations[0].path == "scripts/new_research.py"


def test_allows_documented_historical_research_exception(tmp_path):
    target = tmp_path / "scripts" / "research" / "old_experiment.py"
    _write(
        target,
        "from engines.backtest.runner import run_composite_backtest\n"
        "result = run_composite_backtest(None, {}, None, None)\n",
    )
    allowlist = tmp_path / "scripts" / "audit" / "backtest_runner_bypass_allowlist.txt"
    _write(allowlist, "scripts/research/old_experiment.py\n")

    violations = scanner.scan_repo(tmp_path, allowlist_path=allowlist)

    assert violations == []


def test_ignores_comments_and_engine_wrapper(tmp_path):
    _write(
        tmp_path / "scripts" / "comment_only.py",
        "# run_hybrid_backtest(None, {}, None, None)\n",
    )
    _write(
        tmp_path / "backend" / "qm_platform" / "backtest" / "runner.py",
        "from engines.backtest.runner import run_hybrid_backtest\n"
        "def run():\n"
        "    return run_hybrid_backtest(None, {}, None, None)\n",
    )

    violations = scanner.scan_repo(tmp_path, allowlist_path=tmp_path / "missing.txt")

    assert violations == []


def test_current_repo_backtest_bypass_guard_passes():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout
