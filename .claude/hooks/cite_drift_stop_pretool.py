"""Harness Hook: cite drift stop pretool — V3 §L5.2 5 类漂移 detect (PreToolUse[Edit|Write]).

触发: PreToolUse[Edit|Write]
功能: V3-context file write 中 cross-reference drift detection — surface SOP cite via
hookSpecificOutput (WARN mode), 反 silent sediment 沿用 stale cite. 互补 iron_law_enforce.py
(铁律 2/4/5/6/8 enforce) + verify_completion.py (Stop matcher cite-source-poststop merge target
per Constitution §L6.2) + cite-source-verifier subagent (independent process evidence-gathering)
+ quantmind-v3-cite-source-lock skill (SOP 知识层 active CC invoke).

scope (Phase 1, V3 step 4 sub-PR 2 sediment, narrowed scope per §4(c) push back):

5 类漂移 (Constitution §L5.2 SSOT) — hook handles SUBSET, others deferred to skill SOP:

| drift type | hook coverage | rationale |
|---|---|---|
| cross-reference drift | ✅ regex-based (this hook) | short-name without v3- prefix detectable via static regex |
| path drift | ✅ regex-based (this hook) | known-wrong path patterns (e.g. `configs/litellm_router.yaml` vs canonical `config/`) |
| 数字漂移 | ❌ deferred to skill | requires SQL / git query for live counts |
| 编号漂移 | ❌ deferred to skill | requires git log for canonical max LL/ADR # |
| 存在漂移 | ❌ deferred to skill | requires filesystem check for cited path existence |
| mtime 漂移 | ❌ deferred to skill | requires git log + fs stat for cite-vs-truth comparison |

Other 4 drift types deferred to `quantmind-v3-cite-source-lock` skill SOP active CC invoke
(沿用 ADR-022 反 abstraction premature — hook does not own state lookup logic).

WARN mode (反 BLOCK exit 2):
- Cross-reference drift heuristic is high-recall, lower-precision (false positive risk on
  legitimate references). WARN surfaces SOP cite to CC for manual review.
- "STOP + 反问" intent (Constitution §L5.2 line 197) preserved via surfaced cite + SOP anchor —
  CC sees warning before proceeding, may address or proceed if intentional.
- BLOCK mode reserved for explicit known-stale patterns only (none currently — Phase 1 0 BLOCK).

path scope filter (反 false positive on non-V3 context):
- `.claude/agents/quantmind-*` (charter files)
- `.claude/skills/quantmind-v3-*/` (V3 skill bodies)
- `docs/V3_*.md` (Constitution + skeleton)
- `docs/audit/v3_orchestration/` (V3 audit reports)
- `C:\\Users\\hd\\.claude\\projects\\D--quantmind-v2\\memory\\project_sprint_state.md`
  (memory handoff sediment)

Hook does NOT fire on non-V3 paths (e.g. backend/, scripts/, root .md files).

bypass 体例 (沿用 redline_pretool_block.py + block_dangerous_git.py allowlist 体例):
- env var QM_DRIFT_BYPASS=1 (session-level override)
- per-content marker `# qm-drift-allow:<reason>` (in content body, sustained block_dangerous_git
  marker convention)

⚠️ **CC self-authorization via bypass marker is X10/LL-098 anti-pattern violation**:
bypass marker MUST come from user-typed prompt content (Constitution §L8.1 (b) user 介入 SSOT).
反 CC self-construct marker silent override.

互补 hook (沿用 Constitution §L6.2 cite-drift-stop-pretool 决议):
- iron_law_enforce.py (PreToolUse[Edit|Write]) — 铁律 2/4/5/6/8/11 enforce (different scope)
- redline_pretool_block.py (PreToolUse[Bash]) — 5/5 红线 mutation pattern detect (different scope)
- verify_completion.py (Stop matcher) — sub-PR closure cite-source-poststop merge target
- cite-source-verifier subagent (Task tool delegation) — independent process evidence-gathering
- quantmind-v3-cite-source-lock skill — SOP 知识层 active CC invoke (full 5 类 coverage)

关联铁律: 33 (fail-loud / fail-safe / silent_ok 三选一; parse error 沿用 fail-soft sys.exit(0)
反 break tool 调用) / 42 (PR 分级审查制 — backend/** 必走 PR + reviewer + AI 自 merge)

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only, 反 hardcoded line#):
- Constitution §L5.2 5 类漂移 detect (hook handles cross-reference + path subset, others deferred)
- Constitution §L6.2 cite-drift-stop-pretool 决议 (4 全新 hook 之一)
- skeleton §3.2 hook 索引 (跟 iron_law_enforce 互补 — iron law 偏铁律, cite_drift 偏 5 类漂移)
- IRONLAWS §13 铁律 33 (fail-loud / fail-safe / silent_ok 三选一)
- LL-117 候选 (atomic sediment+wire 反 sediment-only 4 days 0 catch reverse case)
- LL-119 候选 #1-#7 (跨 PR + cross-row drift cumulative — hook coverage reverse cite)
- LL-124 候选 (hook regex context-agnostic intentional design)
- skill quantmind-v3-cite-source-lock (PR #272, full 5 类 SOP knowledge layer)
"""

from __future__ import annotations

import json
import os
import re
import sys

# Canonical V3 short names — every quantmind-v3-* skill / charter has the v3- prefix.
# Drift form: `quantmind-<name>` (without v3-) when content references the V3 entity.
# Sustained Constitution §L6.2 + skeleton §3.3 canonical naming convention.
CANONICAL_V3_SHORT_NAMES: list[str] = [
    # Skills (12)
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
    # Charters (3 borrow OMC extend, batch b)
    "sprint-orchestrator",
    "sprint-closure-gate-evaluator",
    "tier-a-mvp-gate-evaluator",
]

# Cross-reference drift patterns — `quantmind-<name>` without v3- prefix in V3 context.
# Compiled with re.IGNORECASE 沿用 redline_pretool_block.py 体例 (反 case-variant silent bypass).
CROSS_REF_DRIFT_PATTERNS: list[str] = [
    rf"\bquantmind-{re.escape(name)}\b" for name in CANONICAL_V3_SHORT_NAMES
]

# Path drift patterns — known-wrong filesystem path cites.
# (a) `configs/litellm_router.yaml` (plural, wrong) — canonical SSOT is `config/litellm_router.yaml`
#     (singular, FS truth verified). Per LL-119 #7 / LL-128 candidate — charter internal cite drift.
PATH_DRIFT_PATTERNS: list[str] = [
    r"\bconfigs/litellm_router\.yaml\b",
]

# V3 path scope filter — hook fires only on these paths.
# 反 false positive on non-V3 context (backend/, scripts/, root .md, etc.).
V3_PATH_PATTERNS: list[str] = [
    r"\.claude[/\\]agents[/\\]quantmind-",
    r"\.claude[/\\]skills[/\\]quantmind-v3-",
    r"docs[/\\]V3_",
    r"docs[/\\]audit[/\\]v3_orchestration[/\\]",
    r"project_sprint_state\.md",
]

# bypass marker (沿用 block_dangerous_git.py + redline_pretool_block.py 体例)
BYPASS_MARKER_RE = re.compile(r"#\s*qm-drift-allow:[^\n]*", re.IGNORECASE)


def _is_bypassed(content: str) -> bool:
    """Check bypass via env var or per-content marker.

    沿用 redline_pretool_block.py + quantmind-v3-redline-verify skill §3 user 显式触发 SSOT.
    """
    if os.environ.get("QM_DRIFT_BYPASS") == "1":
        return True
    if content and BYPASS_MARKER_RE.search(content):
        return True
    return False


def _is_v3_path(file_path: str) -> bool:
    """Check whether file_path falls in V3 scope (反 false positive non-V3 context).

    Path patterns are case-insensitive (Windows compatibility) + accept both `/` and `\\`.
    """
    if not file_path:
        return False
    for pattern in V3_PATH_PATTERNS:
        if re.search(pattern, file_path, re.IGNORECASE):
            return True
    return False


def _check_cross_ref_drift(content: str) -> list[tuple[str, str]]:
    """Return list of (drift_type, pattern) for matched cross-reference drift."""
    hits: list[tuple[str, str]] = []
    for pattern in CROSS_REF_DRIFT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            hits.append(("cross_ref_drift", pattern))
    return hits


def _check_path_drift(content: str) -> list[tuple[str, str]]:
    """Return list of (drift_type, pattern) for matched path drift."""
    hits: list[tuple[str, str]] = []
    for pattern in PATH_DRIFT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            hits.append(("path_drift", pattern))
    return hits


def _emit_warn_and_pass(file_path: str, hits: list[tuple[str, str]]) -> None:
    """WARN mode: surface SOP cite via hookSpecificOutput, sys.exit(0).

    沿用 protect_critical_files.py + redline_pretool_block.py WARN-with-PASS 体例.
    """
    findings = "; ".join(f"{cat} (pattern: {pat!r})" for cat, pat in hits)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"WARN (cite_drift_stop_pretool): V3-context file write {file_path!r} contains "
                f"likely cite drift — {findings}. "
                f"沿用 Constitution §L5.2 5 类漂移 detect SOP — verify cross-reference: short-name "
                f"应含 v3- prefix (canonical 沿用 §L6.2 + skeleton §3.3) / path 应 cite filesystem "
                f"truth SSOT. 沿用 quantmind-v3-cite-source-lock skill §3 cite source 4 元素 verify. "
                f"反 silent sediment stale cite. bypass: env QM_DRIFT_BYPASS=1 OR per-content marker "
                f"`# qm-drift-allow:<reason>` (user 显式触发 only — CC self-authorize via marker is "
                f"X10/LL-098 anti-pattern violation)."
            ),
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        # 沿用 protect_critical_files.py + redline_pretool_block.py fail-soft 体例
        # (反 break Edit|Write tool 调用)
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    # Edit tool uses new_string; Write tool uses content. Either is the post-write content.
    content = tool_input.get("content", "") or tool_input.get("new_string", "")

    if not file_path or not content:
        sys.exit(0)

    # V3 path scope filter (反 false positive on non-V3 context)
    if not _is_v3_path(file_path):
        sys.exit(0)

    # bypass check 优先 (沿用 user 显式触发 SSOT)
    if _is_bypassed(content):
        sys.exit(0)

    # Cross-reference drift + path drift detection
    hits: list[tuple[str, str]] = []
    hits.extend(_check_cross_ref_drift(content))
    hits.extend(_check_path_drift(content))

    if not hits:
        sys.exit(0)

    # WARN mode (反 BLOCK) — surface SOP cite via hookSpecificOutput
    _emit_warn_and_pass(file_path, hits)


if __name__ == "__main__":
    main()
