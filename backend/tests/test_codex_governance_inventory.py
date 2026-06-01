"""Codex governance inventory guards.

These tests keep the active Codex layer auditable from code, not just from
documentation:
- `.codex/hooks.json` may only wire existing `.codex/hooks/*.py` files.
- active `.codex/hooks/*.py` files should not become unwired dead weight.
- `.agents/skills/*` entries must have `SKILL.md`.
- AGENTS/V3 map skill references must resolve to versioned project skills.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_HOOK_DIR = REPO_ROOT / ".codex" / "hooks"
CODEX_HOOKS_JSON = REPO_ROOT / ".codex" / "hooks.json"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"


def _codex_hook_commands() -> list[str]:
    config = json.loads(CODEX_HOOKS_JSON.read_text(encoding="utf-8"))
    commands: list[str] = []
    for hook_entries in config["hooks"].values():
        for entry in hook_entries:
            for hook in entry.get("hooks", []):
                command = hook.get("command")
                if command:
                    commands.append(command)
    return commands


def _hook_paths_from_commands() -> set[Path]:
    paths: set[Path] = set()
    for command in _codex_hook_commands():
        match = re.search(r"['\"]([^'\"]+\.py)['\"]", command)
        assert match, f"hook command does not contain a quoted .py path: {command}"
        paths.add(Path(match.group(1)).resolve())
    return paths


def test_codex_hooks_json_references_existing_codex_hooks() -> None:
    """Every hooks.json command must point at an existing active Codex hook."""
    hook_paths = _hook_paths_from_commands()

    assert hook_paths, "hooks.json should wire at least one hook"
    for path in hook_paths:
        assert path.exists(), f"wired hook missing: {path}"
        assert CODEX_HOOK_DIR.resolve() in path.parents, f"hook not under .codex/hooks: {path}"


def test_codex_hook_python_files_are_all_wired() -> None:
    """No active `.codex/hooks/*.py` file should linger as 0-wire dead weight."""
    wired = _hook_paths_from_commands()
    hook_files = {path.resolve() for path in CODEX_HOOK_DIR.glob("*.py")}

    assert hook_files == wired


def test_codex_sessionend_remains_unwired_by_decision() -> None:
    """Codex-first governance intentionally has no SessionEnd hook today."""
    config = json.loads(CODEX_HOOKS_JSON.read_text(encoding="utf-8"))

    assert "SessionEnd" not in config["hooks"]
    assert not (CODEX_HOOK_DIR / "handoff_sessionend.py").exists()


def test_project_skill_directories_have_skill_md() -> None:
    """Every versioned project skill directory must be loadable by Codex."""
    skill_dirs = [path for path in SKILLS_DIR.iterdir() if path.is_dir()]

    assert skill_dirs, "expected versioned project skills"
    missing = [path.name for path in skill_dirs if not (path / "SKILL.md").is_file()]
    assert missing == []


def test_agents_mandatory_v3_skills_resolve_to_project_skill_files() -> None:
    """AGENTS.md mandatory V3 skill names must exist under `.agents/skills`."""
    agents_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    names = set(re.findall(r"`(quantmind-v3-[A-Za-z0-9-]+)`", agents_text))

    assert names, "expected mandatory quantmind-v3 skill names in AGENTS.md"
    missing = sorted(name for name in names if not (SKILLS_DIR / name / "SKILL.md").is_file())
    assert missing == []


def test_explicit_project_skill_path_references_resolve() -> None:
    """Docs that cite `.agents/skills/<name>/SKILL.md` must point at real files."""
    docs = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "docs" / "V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md",
    ]
    refs: set[str] = set()
    for path in docs:
        text = path.read_text(encoding="utf-8")
        refs.update(re.findall(r"\.agents/skills/([^/\s`|)]+)/SKILL\.md", text))

    assert refs, "expected explicit project skill path references"
    missing = sorted(ref for ref in refs if not (SKILLS_DIR / ref / "SKILL.md").is_file())
    assert missing == []


def test_hook_behavior_tests_target_active_codex_layer() -> None:
    """Hook behavior tests must execute `.codex/hooks`, not the historical `.claude` mirror."""
    hook_tests = [
        REPO_ROOT / "backend" / "tests" / "test_iron_law_enforce_hook.py",
        REPO_ROOT / "backend" / "tests" / "test_protect_critical_files_hook.py",
    ]

    for path in hook_tests:
        text = path.read_text(encoding="utf-8")
        assert '".codex" / "hooks"' in text, f"{path.name} should target active Codex hooks"
        assert '".claude" / "hooks"' not in text, f"{path.name} still targets historical mirror"
