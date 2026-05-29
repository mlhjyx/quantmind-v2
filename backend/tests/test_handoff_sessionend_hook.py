"""Codex hook governance — SessionEnd handoff hook remains intentionally retired.

Codex current layer is `.codex/hooks.json` + `.codex/hooks/*.py`. The historical
Claude SessionEnd handoff hook may still exist under `.claude/`, but the Codex
governance decision is explicit: do not wire SessionEnd until a Codex-native
handoff flow is designed and accepted.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_HOOKS_JSON = REPO_ROOT / ".codex" / "hooks.json"
CODEX_HANDOFF_HOOK = REPO_ROOT / ".codex" / "hooks" / "handoff_sessionend.py"


def test_codex_sessionend_not_wired() -> None:
    """Codex hooks.json must not wire SessionEnd while the hook is retired."""
    config = json.loads(CODEX_HOOKS_JSON.read_text(encoding="utf-8"))
    hooks = config.get("hooks", {})

    assert "SessionEnd" not in hooks


def test_codex_handoff_sessionend_hook_not_present() -> None:
    """No retired SessionEnd hook should linger in the active Codex hook layer."""
    assert not CODEX_HANDOFF_HOOK.exists()
