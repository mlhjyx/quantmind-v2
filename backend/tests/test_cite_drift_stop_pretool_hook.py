"""V3 step 4 sub-PR 2 — cite_drift_stop_pretool.py hook smoke tests.

scope (V3 step 4 sub-PR 2 atomic sediment+wire 沿用 LL-117 + PR #276 5-09 smoke verify cycle 实证):
- WARN: V3-context cross-reference drift (short-name without v3- prefix on 15 canonical names)
- WARN: V3-context path drift (`configs/litellm_router.yaml` plural vs canonical singular)
- ALLOW: non-V3 path (反 false positive on backend/, scripts/, root .md, etc.)
- ALLOW: canonical V3 names with v3- prefix
- ALLOW: bypass via env var (QM_DRIFT_BYPASS=1)
- ALLOW: bypass via per-content marker (`# qm-drift-allow:<reason>`)
- fail-soft: malformed JSON / empty input

bypass 体例 (沿用 redline_pretool_block.py + block_dangerous_git.py allowlist 体例):
- env QM_DRIFT_BYPASS=1
- per-content marker `# qm-drift-allow:<reason>`

WARN mode: hookSpecificOutput cite + sys.exit(0). 反 BLOCK exit 2 (沿用 Phase 1 narrowed
scope per §4(c) push back — heuristic precision concern + ADR-022 反 abstraction premature).

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §L5.2 5 类漂移 detect (hook handles cross-reference + path subset, others deferred)
- Constitution §L6.2 cite-drift-stop-pretool 决议 (4 全新 hook 之一)
- skeleton §3.2 hook 索引 (跟 iron_law_enforce 互补)
- LL-117 候选 / LL-119 #1-#7 候选 / LL-124 候选 / LL-128 候选
- skill quantmind-v3-cite-source-lock (PR #272, full 5 类 SOP knowledge layer)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "cite_drift_stop_pretool.py"
)


def _run_hook(
    file_path: str,
    content: str,
    env_override: dict | None = None,
) -> tuple[int, str, str]:
    """Run hook with mock Edit|Write tool input.

    Returns (returncode, stdout, stderr). 0=allow (含 WARN-with-PASS via stdout JSON),
    2=block (Phase 1 0 BLOCK case sustained — WARN-only mode).
    """
    payload = json.dumps({"tool_input": {"file_path": file_path, "content": content}})
    env = os.environ.copy()
    env.pop("QM_DRIFT_BYPASS", None)
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


# ── WARN: V3-context cross-reference drift (short-name without v3- prefix) ──


@pytest.mark.parametrize(
    "short_name",
    [
        "fresh-read-sop",
        "cite-source-lock",
        "active-discovery",
        "banned-words",
        "redline-verify",
        "anti-pattern-guard",
        "prompt-design-laws",
        "sprint-closure-gate",
        "sprint-replan",
        "prompt-eval-iteration",
        "llm-cost-monitor",
        "pt-cutover-gate",
        "sprint-orchestrator",
        "sprint-closure-gate-evaluator",
        "tier-a-mvp-gate-evaluator",
    ],
)
def test_cross_ref_drift_warn_in_v3_path(short_name: str) -> None:
    """V3-context cross-reference drift fires WARN — all 15 canonical names."""
    file_path = ".claude/agents/quantmind-test-charter.md"
    content = f"This charter cites legacy `quantmind-{short_name}` skill."
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0, f"expected ALLOW (WARN mode) for {short_name!r}"
    assert "cross_ref_drift" in stdout, f"expected WARN cite for {short_name!r}, stdout={stdout}"
    assert "additionalContext" in stdout


# ── WARN: V3-context path drift (`configs/litellm_router.yaml` vs canonical) ──


def test_path_drift_warn_in_v3_path() -> None:
    """V3-context path drift fires WARN — `configs/litellm_router.yaml` (plural, wrong)."""
    file_path = ".claude/agents/quantmind-test-charter.md"
    content = "Read `configs/litellm_router.yaml` for routing config."
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0
    assert "path_drift" in stdout
    assert "additionalContext" in stdout


# ── ALLOW: non-V3 path (反 false positive) ──


@pytest.mark.parametrize(
    "file_path",
    [
        "backend/app/main.py",
        "scripts/run_paper_trading.py",
        "CLAUDE.md",
        "docs/QUANTMIND_V2_DDL_FINAL.sql",
        "configs/pt_live.yaml",
    ],
)
def test_non_v3_path_allowed(file_path: str) -> None:
    """Non-V3 path 0 hook fire even with drift pattern in content."""
    content = "legacy reference: `quantmind-pt-cutover-gate` and `configs/litellm_router.yaml`"
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0
    # 0 hookSpecificOutput on non-V3 path
    assert "additionalContext" not in stdout


# ── ALLOW: canonical V3 name with v3- prefix ──


@pytest.mark.parametrize(
    "short_name",
    [
        "fresh-read-sop",
        "cite-source-lock",
        "sprint-orchestrator",
        "tier-a-mvp-gate-evaluator",
    ],
)
def test_canonical_v3_name_no_drift(short_name: str) -> None:
    """Canonical `quantmind-v3-<name>` (with v3- prefix) 0 hook fire."""
    file_path = ".claude/agents/quantmind-test-charter.md"
    content = f"This charter complements `quantmind-v3-{short_name}` skill."
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0
    assert "additionalContext" not in stdout


def test_canonical_path_no_drift() -> None:
    """Canonical `config/litellm_router.yaml` (singular) 0 hook fire."""
    file_path = ".claude/agents/quantmind-test-charter.md"
    content = "Read `config/litellm_router.yaml` for routing config."
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0
    assert "additionalContext" not in stdout


# ── BYPASS: env var ──


def test_bypass_env_var_allows_drift_pattern() -> None:
    """QM_DRIFT_BYPASS=1 → ALLOW even drift pattern (user 显式触发 SOP)."""
    file_path = ".claude/agents/quantmind-test-charter.md"
    content = "legacy `quantmind-pt-cutover-gate` reference"
    rc, stdout, _ = _run_hook(
        file_path,
        content,
        env_override={"QM_DRIFT_BYPASS": "1"},
    )
    assert rc == 0
    assert "additionalContext" not in stdout


def test_bypass_env_var_zero_does_not_bypass() -> None:
    """QM_DRIFT_BYPASS=0 → 反 bypass (反 silent override)."""
    file_path = ".claude/agents/quantmind-test-charter.md"
    content = "legacy `quantmind-pt-cutover-gate` reference"
    rc, stdout, _ = _run_hook(
        file_path,
        content,
        env_override={"QM_DRIFT_BYPASS": "0"},
    )
    assert rc == 0  # WARN-with-PASS still exit 0
    assert "cross_ref_drift" in stdout


# ── BYPASS: per-content marker ──


def test_bypass_per_content_marker() -> None:
    """per-content marker `# qm-drift-allow:<reason>` 沿用 ALLOW (user 显式触发 only)."""
    file_path = ".claude/agents/quantmind-test-charter.md"
    content = "legacy `quantmind-pt-cutover-gate` reference  # qm-drift-allow:legacy-charter-archive"
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0
    assert "additionalContext" not in stdout


# ── fail-soft on parse error ──


def test_malformed_json_fail_soft() -> None:
    """malformed JSON stdin → fail-soft sys.exit(0) (沿用 redline_pretool_block 体例)."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0


def test_empty_file_path_fail_soft() -> None:
    """Empty file_path → fail-soft sys.exit(0)."""
    rc, _, _ = _run_hook("", "some content")
    assert rc == 0


def test_empty_content_fail_soft() -> None:
    """Empty content → fail-soft sys.exit(0)."""
    rc, _, _ = _run_hook(".claude/agents/quantmind-test.md", "")
    assert rc == 0


# ── case variants (沿用 re.IGNORECASE flag) ──


def test_case_insensitive_path_match() -> None:
    """V3 path pattern case-insensitive (Windows compatibility)."""
    file_path = "DOCS/V3_IMPLEMENTATION_CONSTITUTION.md"  # uppercase variant
    content = "legacy `quantmind-pt-cutover-gate` reference"
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0
    assert "cross_ref_drift" in stdout


# ── path scope: memory sprint_state ──


def test_memory_sprint_state_in_v3_scope() -> None:
    """memory `project_sprint_state.md` falls in V3 scope (handoff sediment)."""
    file_path = "C:\\Users\\hd\\.claude\\projects\\D--quantmind-v2\\memory\\project_sprint_state.md"
    content = "legacy `quantmind-sprint-orchestrator` reference"
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0
    assert "cross_ref_drift" in stdout


# ── multi-drift in single content ──


def test_multi_drift_in_single_write() -> None:
    """Multiple drift patterns in single content all surface."""
    file_path = ".claude/agents/quantmind-test.md"
    content = (
        "Cite `quantmind-cite-source-lock` skill + read `configs/litellm_router.yaml`."
    )
    rc, stdout, _ = _run_hook(file_path, content)
    assert rc == 0
    assert "cross_ref_drift" in stdout
    assert "path_drift" in stdout
