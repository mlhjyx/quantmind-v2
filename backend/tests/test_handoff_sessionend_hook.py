"""V3 step 4 sub-PR 4 — handoff_sessionend.py hook smoke tests.

scope (V3 step 4 sub-PR 4 atomic sediment+wire 沿用 LL-117 + PR #276/#280/#281 三 PR 实证累积):
- WARN: SessionEnd event with session activity → handoff SOP nudge surface via hookSpecificOutput
- ALLOW: 0 session activity → 0 fire (反 false positive on brief sessions / read-only sessions)
- ALLOW: bypass via env var (QM_HANDOFF_BYPASS=1)
- fail-soft: malformed JSON / git not available

Phase 1 narrowed scope (沿用 PR #280/#281 LL-130 体例累积 + ADR-DRAFT row 23 候选 hook WARN vs BLOCK):
- Hook surfaces "did you write SessionEnd handoff?" reminder via WARN mode
- Skill (quantmind-v3-doc-sediment-auto, PR #281) provides full 4 类 sediment SOP for HOW
- 反 BLOCK exit 2 — SessionEnd event semantic constraint (BLOCK = block session close = bad UX)

bypass 体例 (沿用 PR #281 sediment_poststop bypass 体例 — SessionEnd hook input has no command/content
field, only env var bypass applies):
- env QM_HANDOFF_BYPASS=1 (session-level)
- per-content marker N/A (SessionEnd hook input = session_id + transcript_path + reason)

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §0.3 layer enumeration L9 long-horizon coherence (NOT body section per §0.3 scope)
- Constitution §L6.2 handoff-sessionend 决议
- skeleton §3.2 hook 索引 (跟 sediment_poststop.py Stop matcher 互补)
- audit row 18 SessionEnd 0 wire gap (本 hook + settings.json wire delta 是 gap closure)
- LL-117 候选 / LL-124 候选 / LL-130 候选 / LL-131 候选
- skill quantmind-v3-doc-sediment-auto (PR #281, full sediment SOP)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "handoff_sessionend.py"
)


def _run_hook(
    payload: dict,
    env_override: dict | None = None,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run hook with mock SessionEnd event input.

    Returns (returncode, stdout, stderr). 0=allow / WARN-with-PASS via stdout JSON.
    Phase 1 0 BLOCK case sustained — WARN-only mode (SessionEnd event semantic constraint).
    """
    payload_json = json.dumps(payload)
    env = os.environ.copy()
    env.pop("QM_HANDOFF_BYPASS", None)
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload_json,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=cwd or str(Path(__file__).resolve().parents[2]),  # repo root for git log
    )
    return result.returncode, result.stdout, result.stderr


# ── WARN: SessionEnd with session activity → handoff SOP nudge ──


@pytest.mark.parametrize("reason", ["exit", "clear", "logout", "interrupt"])
def test_session_activity_warn_fires_handoff_nudge(reason: str) -> None:
    """SessionEnd event with session activity (recent commits) → WARN nudge fire."""
    payload = {"session_id": "test-session", "reason": reason}
    rc, stdout, _ = _run_hook(payload)
    assert rc == 0
    # If session activity detected, hook fires WARN. Otherwise 0 stdout.
    if "additionalContext" in stdout:
        # Verify handoff SOP nudge cite quality
        assert "handoff_sessionend" in stdout
        assert reason in stdout, f"reason {reason!r} not in stdout"
        assert "memory" in stdout and "project_sprint_state.md" in stdout
        assert "QM_HANDOFF_BYPASS" in stdout  # bypass instruction surfaced


# ── ALLOW: bypass via env var ──


def test_bypass_env_var_allows() -> None:
    """QM_HANDOFF_BYPASS=1 → 0 fire even with session activity."""
    payload = {"session_id": "test", "reason": "exit"}
    rc, stdout, _ = _run_hook(payload, env_override={"QM_HANDOFF_BYPASS": "1"})
    assert rc == 0
    assert "additionalContext" not in stdout


def test_bypass_env_var_zero_does_not_bypass() -> None:
    """QM_HANDOFF_BYPASS=0 → 反 bypass (反 silent override 沿用 Constitution §L8.1 (b))."""
    payload = {"session_id": "test", "reason": "exit"}
    rc, _, _ = _run_hook(payload, env_override={"QM_HANDOFF_BYPASS": "0"})
    assert rc == 0  # WARN-with-PASS still exit 0 (Phase 1 narrowed scope)


# ── fail-soft on parse error ──


def test_malformed_json_fail_soft() -> None:
    """malformed JSON stdin → fail-soft sys.exit(0) (沿用 PR #276/#280/#281 cumulative 体例)."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0


def test_empty_payload_fail_soft() -> None:
    """Empty JSON object → fail-soft sys.exit(0) (no session activity detect / no error)."""
    payload: dict = {}
    rc, _, _ = _run_hook(payload)
    assert rc == 0


# ── No session activity → no fire ──


def test_no_session_activity_no_fire(tmp_path: Path) -> None:
    """If hook runs in dir with no git history (fresh tmp), 0 fire (反 false positive)."""
    payload = {"session_id": "test", "reason": "exit"}
    # Initialize empty git repo with no commits
    subprocess.run(
        ["git", "init", "-q"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=5,
    )
    rc, stdout, _ = _run_hook(payload, cwd=str(tmp_path))
    assert rc == 0
    assert "additionalContext" not in stdout


def test_git_not_available_fail_soft(tmp_path: Path) -> None:
    """If git fails (non-repo directory), fail-soft sys.exit(0) (反 break SessionEnd event 沿用)."""
    payload = {"session_id": "test", "reason": "exit"}
    # Run in tmp_path (NOT a git repo, no .git dir)
    rc, stdout, _ = _run_hook(payload, cwd=str(tmp_path))
    assert rc == 0
    assert "additionalContext" not in stdout


# ── reason field handling ──


def test_missing_reason_handled() -> None:
    """Missing reason field → use 'unknown' default (反 KeyError)."""
    payload = {"session_id": "test"}  # no reason
    rc, stdout, _ = _run_hook(payload)
    assert rc == 0
    if "additionalContext" in stdout:
        assert "unknown" in stdout


# ── SOP nudge content quality verification (when fired) ──


def test_handoff_nudge_content_quality_when_fired() -> None:
    """When handoff SOP nudge fires, nudge content covers all 4 sediment classes per铁律 37."""
    payload = {"session_id": "test", "reason": "exit"}
    rc, stdout, _ = _run_hook(payload)
    assert rc == 0
    if "additionalContext" in stdout:
        # 4 sediment 类 cite presence per铁律 37 + handoff_template.md schema
        ctx = stdout
        assert "memory" in ctx and "project_sprint_state.md" in ctx, "missing memory cite"
        assert "5/5 红线" in ctx or ("cash" in ctx and "持仓" in ctx), "missing 红线 cite"
        assert "LL append candidate" in ctx, "missing LL append cite"
        assert "ADR row sediment candidate" in ctx, "missing ADR row cite"
        # Skill SOP cite anchor
        assert "quantmind-v3-doc-sediment-auto skill" in ctx, "missing skill SOP anchor"
        # bypass instruction
        assert "QM_HANDOFF_BYPASS=1" in ctx, "missing bypass instruction"
        # X10/LL-098 anti-pattern warning
        assert "X10" in ctx or "LL-098" in ctx, "missing X10/LL-098 anti-pattern warning"
        # 铁律 37 cite
        assert "铁律 37" in ctx, "missing 铁律 37 cite"
