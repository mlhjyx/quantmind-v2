"""Harness Hook: sediment poststop — V3 documentation sediment automation reminder (Stop matcher).

触发: Stop event
功能: CC Stop event 后 (sub-PR 闭后 turn 结束) detect recent commits in current session period;
若有 → surface SOP nudge for LL append / ADR row / STATUS_REPORT / memory handoff. WARN mode only
(hookSpecificOutput cite + sys.exit 0). 反 BLOCK exit 2 (BLOCK on Stop event = block CC turn finish
= bad UX, sustained 反向 PR #280 cite_drift_stop_pretool WARN mode 体例).

scope (Phase 1, V3 step 4 sub-PR 3 sediment, narrowed scope per §4(d) push back):

sediment trigger types (4 类) — hook coverage subset, others deferred to skill SOP active CC invoke:

| sediment type | hook coverage | rationale |
|---|---|---|
| recent-commit reminder | ✅ git log --since N min (low-risk runtime query) | static fact: did sub-PR commits happen this session period |
| LL/ADR/STATUS_REPORT/handoff append-candidate detail | ❌ deferred to skill SOP | requires content analysis per sub-PR scope (out of static hook scope) |

→ Hook surfaces "did you remember to sediment?" reminder; skill provides HOW (SOP knowledge layer).
沿用 ADR-022 反 abstraction premature — hook does not own sediment workflow logic.

互补 hook (沿用 §L6.2 sediment-poststop 决议 — Constitution §0.3 layer enumeration + §L6.2 hook 表):
- verify_completion.py (Stop matcher, existing) — doc 同步 reminder (different scope, sustained per skeleton §3.2 line 189 互补)
- sediment_poststop (本 hook, Stop matcher) — sub-PR 闭后 sediment append candidate reminder
- quantmind-v3-doc-sediment-auto skill (本 sub-PR sediment 全新, knowledge layer) — sub-PR 闭后 documentation sediment SOP active CC invoke

WARN mode (反 BLOCK exit 2):
- BLOCK on Stop event = block CC turn finish = bad UX. Stop hook semantics 反 BLOCK 体例.
- WARN surfaces SOP nudge via hookSpecificOutput → CC sees reminder for next-turn action.
- Sustained PR #280 cite_drift_stop_pretool WARN mode 体例 + §4(c) Stop event semantic constraint.

bypass 体例 (沿用 redline_pretool_block.py + cite_drift_stop_pretool.py 体例 — 但 Stop hook
input has no command/content field, only env var bypass applies):
- env var QM_SEDIMENT_BYPASS=1 (session-level)
- per-content marker N/A (Stop hook input = session_id + transcript_path, no command/content body)

stop_hook_active flag (沿用 Anthropic Claude Code Stop hook semantic):
- 若 input.stop_hook_active=true → skip (反 infinite loop, 沿用 Stop hook 体例 standard)

⚠️ **CC self-authorization via env var bypass is X10/LL-098 anti-pattern violation**:
bypass MUST come from user-typed prompt content (Constitution §L8.1 (b) user 介入 SSOT).
反 CC self-construct env override silent skip.

关联铁律: 33 (fail-loud / fail-safe / silent_ok 三选一; parse error fail-soft sys.exit(0)) /
          37 (sub-PR 闭后 memory handoff sediment) /
          42 (PR 分级审查制 — backend/** 必走 PR + reviewer + AI 自 merge)

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only, 反 hardcoded line#):
- Constitution §0.3 layer enumeration table (L7 documentation sediment automation 沿用 §0.3 cite)
- Constitution §L6.2 sediment-poststop hook 决议 (4 全新 hook 之一)
- skeleton §3.2 hook 索引 (跟 verify_completion.py 互补 — verify doc 同步, sediment 偏 LL/ADR append candidate)
- IRONLAWS §13 铁律 33 (fail-loud / fail-safe / silent_ok 三选一)
- IRONLAWS §15 铁律 37 (sub-PR 闭后 memory handoff sediment)
- LL-117 候选 (atomic sediment+wire 反 sediment-only 4 days 0 catch reverse case)
- LL-130 候选 (hook regex coverage scope vs full SOP scope governance — Phase 1 narrowed scope sustained)
- LL-124 候选 (hook regex context-agnostic intentional design)
- skill quantmind-v3-doc-sediment-auto (本 sub-PR sediment, full sediment SOP knowledge layer)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# Lookback window: detect commits made within last N minutes (current session period proxy).
# Sustained Phase 1 narrowed scope — 反 hardcoded session start time / 反 transcript content analysis.
LOOKBACK_MINUTES = 30


def _is_bypassed() -> bool:
    """Check bypass via env var (session-level only — Stop hook input has no command/content).

    沿用 redline_pretool_block.py + cite_drift_stop_pretool.py 体例.
    """
    return os.environ.get("QM_SEDIMENT_BYPASS") == "1"


def _has_recent_commits() -> bool:
    """Check if any commit landed in the current session period (proxy: last N minutes).

    Sustained ADR-022 反 abstraction premature — 反 transcript path content analysis,
    仅 git log --since runtime query (low-risk + fail-soft on git failure).
    """
    try:
        result = subprocess.run(
            ["git", "log", f"--since={LOOKBACK_MINUTES} minutes ago", "--oneline"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _emit_reminder() -> None:
    """WARN mode: surface SOP nudge via hookSpecificOutput, sys.exit(0).

    沿用 cite_drift_stop_pretool.py + protect_critical_files.py WARN-with-PASS 体例.
    """
    result = {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": (
                "REMINDER (sediment_poststop): recent commit(s) detected in last "
                f"{LOOKBACK_MINUTES} min (proxy for sub-PR closure in current session period). "
                "沿用 quantmind-v3-doc-sediment-auto skill SOP — sub-PR 闭后 sediment append "
                "candidate checklist: "
                "(a) LL append candidate (LESSONS_LEARNED.md 沿用 LL # registry SSOT, 沿用 "
                "LL-105 SOP-6 cross-verify) / "
                "(b) ADR row sediment candidate (docs/adr/REGISTRY.md + ADR-DRAFT.md, 沿用 ADR # "
                "registry SSOT) / "
                "(c) STATUS_REPORT sediment (沿用铁律 37 + handoff_template.md §3 cite SOP) / "
                "(d) memory `project_sprint_state.md` handoff sediment (沿用铁律 37 sub-PR 闭后 "
                "handoff). "
                "反 silent skip 沿用 LL-098 X10 反 forward-progress + ADR-022 集中机制. "
                "bypass: env QM_SEDIMENT_BYPASS=1 (session-level only — CC self-authorize is "
                "X10/LL-098 anti-pattern violation, MUST be user-typed)."
            ),
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        # 沿用 protect_critical_files.py + redline_pretool_block.py + cite_drift_stop_pretool.py
        # fail-soft 体例 (反 break Stop event 沿用)
        sys.exit(0)

    # stop_hook_active prevents infinite Stop hook loop (沿用 Anthropic Claude Code Stop hook
    # semantic standard — re-fired Stop hooks should skip if previous fire is still active)
    if input_data.get("stop_hook_active", False):
        sys.exit(0)

    # bypass check 优先 (沿用 user 显式触发 SSOT)
    if _is_bypassed():
        sys.exit(0)

    # Phase 1 narrowed scope: only fire if recent commits detected in current session period.
    # 反 false positive on Stop events without sediment activity.
    if not _has_recent_commits():
        sys.exit(0)

    # WARN mode (反 BLOCK on Stop event) — surface SOP nudge via hookSpecificOutput
    _emit_reminder()


if __name__ == "__main__":
    main()
