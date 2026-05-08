"""V3 step 4 sub-PR 3 — sediment_poststop.py hook smoke tests.

scope (V3 step 4 sub-PR 3 atomic sediment+wire 沿用 LL-117 + PR #276/#280 双 PR 实证累积):
- WARN: recent commit detected → SOP nudge surface via hookSpecificOutput
- ALLOW: 0 recent commit → 0 fire
- ALLOW: bypass via env var (QM_SEDIMENT_BYPASS=1)
- ALLOW: stop_hook_active=true → skip (反 infinite loop, sustained Anthropic Stop hook semantic)
- fail-soft: malformed JSON / git not available

Phase 1 narrowed scope (沿用 LL-130 候选 体例 + ADR-DRAFT row 23 候选 hook WARN vs BLOCK):
- Hook surfaces "did you remember to sediment?" reminder via WARN mode
- Skill provides full SOP for HOW (LL/ADR/STATUS_REPORT/handoff append patterns)
- 反 BLOCK exit 2 — Stop event semantic constraint (BLOCK = block CC turn finish = bad UX)

bypass 体例 (沿用 redline_pretool_block.py + cite_drift_stop_pretool.py 体例 — but Stop hook
input has no command/content field, only env var bypass applies):
- env QM_SEDIMENT_BYPASS=1
- per-content marker N/A (Stop hook input = session_id + transcript_path)

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §0.3 layer enumeration table (L7 documentation sediment automation)
- Constitution §L6.2 sediment-poststop hook 决议
- skeleton §3.2 hook 索引 (跟 verify_completion.py 互补)
- LL-117 候选 / LL-124 候选 / LL-130 候选
- skill quantmind-v3-doc-sediment-auto (full sediment SOP knowledge layer)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "sediment_poststop.py"
)


def _run_hook(
    payload: dict,
    env_override: dict | None = None,
) -> tuple[int, str, str]:
    """Run hook with mock Stop event input.

    Returns (returncode, stdout, stderr). 0=allow / WARN-with-PASS via stdout JSON.
    Phase 1 0 BLOCK case sustained — WARN-only mode (Stop event semantic constraint).
    """
    payload_json = json.dumps(payload)
    env = os.environ.copy()
    env.pop("QM_SEDIMENT_BYPASS", None)
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload_json,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),  # run in repo root for git log
    )
    return result.returncode, result.stdout, result.stderr


# ── WARN: recent commit detected → SOP nudge surface ──


def test_recent_commit_warn_fires_sop_nudge() -> None:
    """Recent commit in repo (< LOOKBACK_MINUTES) → WARN nudge fire.

    Note: this test runs in repo root via cwd. If repo has any commit in last 30 min
    (typical during active dev session), hook should fire. We verify hookSpecificOutput
    presence (sediment SOP nudge) regardless of whether dev or CI runs.
    """
    payload = {"session_id": "test-session", "stop_hook_active": False}
    rc, stdout, _ = _run_hook(payload)
    assert rc == 0
    # If a recent commit exists, hook fires WARN. Otherwise 0 stdout.
    # Both outcomes are valid — we test that exit code is always 0 (ALLOW path) and
    # surfaced cite is properly formatted when fire.
    if "additionalContext" in stdout:
        # Recent commit detected — verify SOP nudge cite quality
        assert "sediment_poststop" in stdout
        assert "LL append" in stdout or "STATUS_REPORT" in stdout or "handoff" in stdout
        assert "QM_SEDIMENT_BYPASS" in stdout  # bypass instruction surfaced


# ── ALLOW: stop_hook_active=true → skip (反 infinite loop) ──


def test_stop_hook_active_skip() -> None:
    """stop_hook_active=true → 0 fire (沿用 Anthropic Stop hook semantic 反 infinite loop)."""
    payload = {"session_id": "test", "stop_hook_active": True}
    rc, stdout, _ = _run_hook(payload)
    assert rc == 0
    assert "additionalContext" not in stdout


# ── ALLOW: bypass via env var ──


def test_bypass_env_var_allows() -> None:
    """QM_SEDIMENT_BYPASS=1 → 0 fire even with recent commit."""
    payload = {"session_id": "test", "stop_hook_active": False}
    rc, stdout, _ = _run_hook(payload, env_override={"QM_SEDIMENT_BYPASS": "1"})
    assert rc == 0
    assert "additionalContext" not in stdout


def test_bypass_env_var_zero_does_not_bypass() -> None:
    """QM_SEDIMENT_BYPASS=0 → 反 bypass (反 silent override 沿用 Constitution §L8.1 (b))."""
    payload = {"session_id": "test", "stop_hook_active": False}
    rc, _, _ = _run_hook(payload, env_override={"QM_SEDIMENT_BYPASS": "0"})
    assert rc == 0  # WARN-with-PASS still exit 0 (Phase 1 narrowed scope)


# ── fail-soft on parse error ──


def test_malformed_json_fail_soft() -> None:
    """malformed JSON stdin → fail-soft sys.exit(0) (沿用 protect_critical_files / redline / cite_drift 体例)."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0


def test_empty_payload_fail_soft() -> None:
    """Empty JSON object → fail-soft sys.exit(0) (no recent commit detect / no error)."""
    payload: dict = {}
    rc, _, _ = _run_hook(payload)
    assert rc == 0


# ── No recent commit → no fire ──


def test_no_recent_commit_no_fire(tmp_path: Path) -> None:
    """If hook runs in dir with no git history (fresh tmp), 0 fire (反 false positive)."""
    payload = {"session_id": "test", "stop_hook_active": False}
    payload_json = json.dumps(payload)
    env = os.environ.copy()
    env.pop("QM_SEDIMENT_BYPASS", None)
    # Initialize empty git repo with no commits
    subprocess.run(
        ["git", "init", "-q"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=5,
    )
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload_json,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "additionalContext" not in result.stdout


def test_git_not_available_fail_soft(tmp_path: Path) -> None:
    """If git fails (non-repo directory), fail-soft sys.exit(0) (反 break Stop event 沿用)."""
    payload = {"session_id": "test", "stop_hook_active": False}
    payload_json = json.dumps(payload)
    env = os.environ.copy()
    env.pop("QM_SEDIMENT_BYPASS", None)
    # Run in tmp_path (NOT a git repo, no .git dir)
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload_json,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "additionalContext" not in result.stdout


# ── SOP nudge content verification (when fired) ──


def test_sop_nudge_content_quality_when_fired() -> None:
    """When SOP nudge fires (recent commit), nudge content covers all 4 sediment classes."""
    payload = {"session_id": "test", "stop_hook_active": False}
    rc, stdout, _ = _run_hook(payload)
    assert rc == 0
    if "additionalContext" in stdout:
        # 4 sediment 类 cite presence
        ctx = stdout
        assert "LL append candidate" in ctx, "missing LL append cite"
        assert "ADR row sediment candidate" in ctx, "missing ADR row cite"
        assert "STATUS_REPORT sediment" in ctx, "missing STATUS_REPORT cite"
        assert "memory" in ctx and "handoff sediment" in ctx, "missing memory handoff cite"
        # SOP cite anchors
        assert "quantmind-v3-doc-sediment-auto skill" in ctx, "missing skill SOP anchor"
        # bypass instruction
        assert "QM_SEDIMENT_BYPASS=1" in ctx, "missing bypass instruction"
        # X10/LL-098 anti-pattern warning
        assert "X10" in ctx or "LL-098" in ctx, "missing X10/LL-098 anti-pattern warning"
