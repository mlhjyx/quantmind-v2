"""sub-PR 8a-followup-pre 5-07 — block_dangerous_git.py hook smoke tests.

scope (~80 line, single chunk):
- feature-branch push 真**允许** (5-07 修订 NEW)
- force push 真**block** sustained (--force / -f / --force-with-lease)
- push to main / master 真**block** sustained
- legacy dangerous patterns 真**block** sustained (reset --hard / clean / branch -D /
  checkout . / restore .)
- 普通命令 真**allow** (sanity)

真生产证据沿用 5-07 sub-PR 8a-followup-pre hook governance 修订:
- 反 "git push" 全局 BLOCK 体例
- 改 fine-grained PUSH_DANGEROUS_PATTERNS 检测
- 真生效 ADR-DRAFT row 7 sediment

关联铁律: 33 (fail-loud, parse error 沿用 fail-soft sys.exit(0)) / 42 (PR 分级审查制)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "block_dangerous_git.py"


def _run_hook(command: str) -> int:
    """Run hook with mock Bash tool input; return exit code (0=allow, 2=block)."""
    payload = json.dumps({"tool_input": {"command": command}})
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode


# ── 5-07 修订 NEW: feature-branch push 真**允许** ──


def test_push_feature_branch_explicit_allowed() -> None:
    """git push -u origin sprint2-sub-pr-X-feature → exit 0 (allow)."""
    assert _run_hook("git push -u origin sprint2-sub-pr-8a-followup-a-isfallback-bugfix") == 0


def test_push_no_args_allowed() -> None:
    """git push (current branch HEAD push, ambiguous → allow as feature-branch)."""
    assert _run_hook("git push") == 0


def test_push_origin_feature_branch_allowed() -> None:
    """git push origin <feature-branch> → exit 0 (allow)."""
    assert _run_hook("git push origin sprint2-sub-pr-8a-followup-pre-hook-fix") == 0


def test_gh_pr_create_allowed() -> None:
    """gh pr create 真生产 PR creation 路径 → exit 0 (allow, 反 dangerous pattern)."""
    assert _run_hook("gh pr create --title 'test' --body 'body' --base main") == 0


# ── sustained: force push 真**block** ──


def test_push_force_blocked() -> None:
    """git push --force → exit 2 (block) sustained."""
    assert _run_hook("git push --force origin feature-branch") == 2


def test_push_force_with_lease_blocked() -> None:
    """git push --force-with-lease → exit 2 (block) sustained."""
    assert _run_hook("git push --force-with-lease origin feature-branch") == 2


def test_push_dash_f_blocked() -> None:
    """git push -f → exit 2 (block) sustained."""
    assert _run_hook("git push -f origin feature-branch") == 2


# ── sustained: push to main / master 真**block** ──


def test_push_origin_main_blocked() -> None:
    """git push origin main → exit 2 (block) sustained."""
    assert _run_hook("git push origin main") == 2


def test_push_origin_master_blocked() -> None:
    """git push origin master → exit 2 (block) sustained."""
    assert _run_hook("git push origin master") == 2


def test_push_main_trailing_blocked() -> None:
    """git push <somewhere> main (main as last arg) → exit 2 (block)."""
    assert _run_hook("git push -u origin main") == 2


# ── sustained: legacy dangerous patterns 真**block** ──


@pytest.mark.parametrize(
    "command",
    [
        "git reset --hard HEAD~1",
        "git reset --hard origin/main",
        "git clean -fd",
        "git clean -f",
        "git branch -D feature-branch",
        "git checkout .",
        "git restore .",
    ],
)
def test_legacy_dangerous_patterns_blocked(command: str) -> None:
    """legacy dangerous git ops 真**block** sustained 5-07 修订后."""
    assert _run_hook(command) == 2


# ── sanity: 普通命令 真**allow** ──


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "git status",
        "git log --oneline -5",
        "git diff",
        "git add file.txt",
        "git commit -m 'message'",
        "pytest",
        "ruff check",
    ],
)
def test_safe_commands_allowed(command: str) -> None:
    """普通命令 真**allow** 沿用 fail-soft 体例 sustained."""
    assert _run_hook(command) == 0


def test_empty_command_allowed() -> None:
    """空 command (e.g. malformed input) → fail-soft sys.exit(0)."""
    assert _run_hook("") == 0


# ── P1-4 reviewer adopt: bypass attack vector coverage (5-07 sub-PR 8a-followup-pre) ──
#
# reviewer security finding 真**P0/P1 bypass case** 真**0 cover 5-07 first commit**,
# 沿用 audit Week 2 batch governance 真**detection bug 双向 case 体例** sediment +
# 沿用 reviewer Chunk A P2 PR #222 真**双向 cover SOP** sustained.


@pytest.mark.parametrize(
    "command",
    [
        # P0-1 refspec bypass attack vector (HEAD:main, feature:main, refs/heads/main)
        "git push origin HEAD:main",
        "git push origin HEAD:master",
        "git push origin feature:main",
        "git push origin feature:master",
        "git push origin HEAD:refs/heads/main",
        "git push origin HEAD:refs/heads/master",
    ],
)
def test_refspec_bypass_blocked(command: str) -> None:
    """P0-1 reviewer adopt: refspec syntax (LHS:main / LHS:master) 真**block** sustained.

    git refspec 真**native syntax** push 走任 LHS:main / LHS:master, 反**origin\\s+main**
    pattern 真**仅 catch space-separated** — 5-07 first commit 真**bypass vector**.
    """
    assert _run_hook(command) == 2


@pytest.mark.parametrize(
    "command",
    [
        # P0-2 + prefix force-push bypass attack vector
        "git push origin +feature-branch",
        "git push origin +HEAD:main",  # 真**combine P0-1 + P0-2** 真 worst case
        "git push -u origin +sprint2-branch",
        "git push origin +master",
    ],
)
def test_plus_prefix_force_push_bypass_blocked(command: str) -> None:
    """P0-2 reviewer adopt: + prefix refspec 真**force-push native syntax** 沿用
    git native semantics, 反**仅 --force / -f / --force-with-lease** pattern 真 cover.
    """
    assert _run_hook(command) == 2


@pytest.mark.parametrize(
    "command",
    [
        # P1-1 reviewer adopt: -df reversed flag order
        "git clean -df",
        "git clean -dfx",
        "git clean -fdx",
        # P1-2 reviewer adopt: --delete --force long-form (任 order)
        "git branch --delete --force feature-branch",
        "git branch --force --delete main",
        # P1-3 reviewer adopt: checkout -- . variant
        "git checkout -- .",
        "git checkout HEAD -- .",
        "git checkout origin/main -- .",
    ],
)
def test_pattern_correctness_bypass_blocked(command: str) -> None:
    """P1-1/2/3 reviewer adopt: pattern correctness bypass case 真**block** sustained.

    legacy DANGEROUS_PATTERNS 真**substring 体例** 仅 catch canonical flag order /
    short-form, reviewer 真**catch flag-order reversal + long-form + -- separator
    variant** sediment.
    """
    assert _run_hook(command) == 2
