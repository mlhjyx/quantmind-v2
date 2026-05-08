"""V3 step 4 sub-PR 5 — session_context_inject.py v3 扩展 hook smoke tests.

scope (V3 step 4 sub-PR 5 atomic sediment+wire 沿用 LL-117 候选 promote trigger 现满足 + PR
#276/#280/#281/#282 四 PR 实证累积):
- inject context contains v3 marker (hook v3, 2026-05-09)
- inject context contains 4 V3 doc cite (Constitution v0.2 / Skeleton v0.1 / V3 Design / ADR REGISTRY)
- inject context preserves v2 sustained content (Sprint state + Blueprint + Cold start required reading)
- fail-soft on git unavailable / non-repo dir (反 break SessionStart event)

Phase 1 narrowed scope (沿用 PR #280/#281/#282 LL-130 体例累积 + Constitution §L0.3 step (3) +
§L1.1 8 doc fresh read SOP + §L6.2 line 277 fresh-read-sessionstart 合并决议):
- v3 hook adds 4 V3 doc cite to inject scope (静态可达)
- dynamic content extraction (e.g. Constitution v0.2 frontmatter) deferred to skill SOP active CC invoke

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §L0.3 step (3) SessionStart hook fire 决议 (V3 doc fresh read trigger)
- Constitution §L1.1 8 doc fresh read SOP
- Constitution §L6.2 line 277 fresh-read-sessionstart 合并决议
- skeleton §3.2 现有 hook 扩展真值
- LL-130 候选 / 铁律 45 (4 doc fresh read SOP enforcement)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK_PATH = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "session_context_inject.py"
)


def _run_hook(payload: dict | None = None) -> tuple[int, str, str]:
    """Run hook with mock SessionStart event input.

    Returns (returncode, stdout, stderr). 0=allow / inject context via stdout JSON.
    """
    payload_json = json.dumps(payload or {})
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload_json,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(Path(__file__).resolve().parents[2]),  # repo root
    )
    return result.returncode, result.stdout, result.stderr


def test_v3_marker_present() -> None:
    """v3 hook context must contain v3 marker (hook v3, 2026-05-09)."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    assert "additionalContext" in stdout
    assert "hook v3" in stdout, "missing v3 marker"
    assert "V3 实施期 doc 扩展" in stdout, "missing v3 doc 扩展 cite"


def test_v3_doc_cite_present() -> None:
    """v3 扩展 must cite all 4 V3 docs in inject scope."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    # 4 V3 doc cite (path) — sustained Constitution §L1.1 8 doc fresh read SOP
    assert "V3_IMPLEMENTATION_CONSTITUTION.md" in stdout, "missing Constitution v0.2 cite"
    assert "V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md" in stdout, "missing skeleton v0.1 cite"
    assert "QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md" in stdout, "missing V3 spec cite"
    assert "docs/adr/REGISTRY.md" in stdout, "missing ADR REGISTRY cite"
    # SOP cite anchors
    assert "Constitution v0.2 §L0.3" in stdout, "missing §L0.3 anchor"
    assert "§L1.1" in stdout, "missing §L1.1 anchor"
    assert "铁律 45" in stdout, "missing 铁律 45 anchor"


def test_v2_sustained_content_present() -> None:
    """v3 must preserve v2 sustained content (反 silent overwrite, sustained ADR-022)."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    # v2 sustained: Sprint state + Blueprint + Cold start required reading + Iron law top 12
    assert "Sprint 状态" in stdout, "missing Sprint state cite"
    assert "Blueprint" in stdout, "missing Blueprint cite"
    assert "新 Session 冷启动必读" in stdout, "missing cold start reading cite"
    assert "铁律速查 TOP" in stdout, "missing 铁律 top 12 cite"


def test_session_start_event_handled() -> None:
    """SessionStart event payload handled correctly."""
    payload = {"session_id": "test-session", "source": "test"}
    rc, stdout, _ = _run_hook(payload)
    assert rc == 0
    # Verify hookSpecificOutput structure
    parsed = json.loads(stdout)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "additionalContext" in parsed["hookSpecificOutput"]


def test_malformed_json_fail_soft() -> None:
    """malformed JSON stdin → fail-soft sys.exit(0) (反 break SessionStart event 沿用)."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )
    # Hook always emits inject context regardless of input parse (SessionStart hook semantic)
    assert result.returncode == 0


def test_v3_doc_status_format() -> None:
    """v3 doc status uses ✅/⚠️ markers per file existence."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    # All 4 V3 docs exist post-PR #271/#282 — should all show ✅
    assert "✅ exists" in stdout, "missing exists status marker"


def test_v2_inject_scope_4_root_doc_sustained() -> None:
    """v2 sustained: cold start required reading 4 root doc cite preserved."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    # 4 root doc cite from v2 cold start required reading
    assert "QUANTMIND_PLATFORM_BLUEPRINT.md" in stdout, "missing Blueprint cite"
    assert "memory/project_sprint_state.md" in stdout, "missing memory cite"
    assert "CLAUDE.md" in stdout, "missing CLAUDE.md cite"
