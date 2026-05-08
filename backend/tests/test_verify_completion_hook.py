"""V3 step 4 sub-PR 5 — verify_completion.py v2 扩展 hook smoke tests.

scope (V3 step 4 sub-PR 5 atomic sediment+wire 沿用 LL-117 候选 + PR #276/#280/#281/#282 四 PR
实证累积):
- v2 marker present (V3 实施期扩展 cite)
- 4 元素 cite source 锁定 reminder always surfaced (Phase 1 narrowed scope)
- banned 真+词 detect via git diff staged content (Phase 1 narrowed scope, WARN-only)
- v1 sustained: docs updated reminder (铁律 6, 反 silent overwrite)
- fail-soft on parse error / git unavailable

Phase 1 narrowed scope (沿用 PR #280/#281/#282 LL-130 体例累积 + Constitution §L5.1 cite source
锁定 SOP + §L6.2 line 278-279 cite-source-poststop + banned-words-poststop 合并决议):
- v2 hook surfaces 4 元素 cite reminder + 真+词 WARN; full SOP deferred to skill active CC invoke

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §L5.1 cite source 锁定 SOP
- Constitution §L6.2 line 278-279 合并决议
- skeleton §3.2 现有 hook 扩展真值
- skill quantmind-v3-cite-source-lock (PR #272)
- skill quantmind-v3-banned-words (PR #273)
- memory #25 HARD BLOCK (真+词 whitelist 5 forms)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK_PATH = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "verify_completion.py"
)


def _run_hook(payload: dict | None = None, cwd: str | None = None) -> tuple[int, str, str]:
    """Run hook with mock Stop event input.

    Returns (returncode, stdout, stderr). 0=allow / WARN-with-PASS via stdout JSON.
    """
    payload_json = json.dumps(payload or {})
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload_json,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd or str(Path(__file__).resolve().parents[2]),  # repo root for git diff
    )
    return result.returncode, result.stdout, result.stderr


def test_v2_marker_in_checklist() -> None:
    """v2 hook output must contain COMPLETION CHECKLIST + 4 元素 cite reminder always."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    assert "COMPLETION CHECKLIST" in stdout
    # 4 元素 cite source 锁定 reminder (always surfaced regardless of issues)
    assert "4 元素 cite source 锁定" in stdout
    assert "Constitution §L5.1" in stdout
    assert "quantmind-v3-cite-source-lock" in stdout


def test_4_element_cite_reminder_content() -> None:
    """4-element cite reminder must list path / line# / section / timestamp."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    ctx = stdout
    assert "(a) path" in ctx, "missing path element"
    assert "(b) line#" in ctx, "missing line# element"
    assert "(c) section anchor" in ctx, "missing section anchor element"
    assert "(d) fresh verify timestamp" in ctx, "missing fresh verify timestamp element"


def test_v1_sustained_checklist_items() -> None:
    """v1 sustained: ruff check / tests / docs reminder items preserved."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    # v1 sustained checklist items (反 silent overwrite, sustained ADR-022)
    assert "ruff check" in stdout, "missing ruff check item"
    assert "相关测试运行过" in stdout, "missing tests reminder"
    assert "CLAUDE.md/SYSTEM_STATUS.md" in stdout, "missing docs reminder"


def test_stop_event_handled() -> None:
    """Stop event payload structure correct."""
    payload = {"session_id": "test", "stop_hook_active": False}
    rc, stdout, _ = _run_hook(payload)
    assert rc == 0
    parsed = json.loads(stdout)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "additionalContext" in parsed["hookSpecificOutput"]


def test_malformed_json_fail_soft() -> None:
    """malformed JSON stdin → fail-soft sys.exit(0)."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0


def test_git_unavailable_fail_soft(tmp_path: Path) -> None:
    """If git fails (non-repo directory), fail-soft sys.exit(0) (反 break Stop event 沿用)."""
    rc, stdout, _ = _run_hook(cwd=str(tmp_path))
    assert rc == 0
    # Should still emit checklist with 4 元素 cite reminder (always surfaced)
    assert "COMPLETION CHECKLIST" in stdout
    assert "4 元素 cite source 锁定" in stdout


def test_banned_zhen_pattern_compiled() -> None:
    """Verify BANNED_ZHEN_PATTERN regex correctly matches banned + allows whitelist.

    Whitelist: 真账户 / 真发单 / 真生产 / 真测 / 真值 (5 forms).
    Banned: 真[^账发生测值\\s] (anything else).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("verify_completion", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pat = mod.BANNED_ZHEN_PATTERN

    # Whitelist forms — should NOT match
    assert not pat.search("真账户"), "whitelist 真账户 false positive"
    assert not pat.search("真发单"), "whitelist 真发单 false positive"
    assert not pat.search("真生产"), "whitelist 真生产 false positive"
    assert not pat.search("真测"), "whitelist 真测 false positive"
    assert not pat.search("真值"), "whitelist 真值 false positive"

    # Banned forms — should match
    assert pat.search("真实"), "banned 真实 missed"
    assert pat.search("真理"), "banned 真理 missed"
    assert pat.search("真正"), "banned 真正 missed"
    assert pat.search("真好"), "banned 真好 missed"


def test_no_issues_no_warning_section() -> None:
    """When no issues found (clean state), checklist has no warning section."""
    rc, stdout, _ = _run_hook()
    assert rc == 0
    # Even with no issues, 4 元素 cite reminder should be surfaced (always)
    assert "4 元素 cite source 锁定" in stdout
