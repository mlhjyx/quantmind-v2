"""Harness Hook: handoff sessionend — V3 long-horizon coherence sediment reminder (SessionEnd matcher).

触发: SessionEnd event (session 关闭前 — exit / interrupt / compaction)
功能: SessionEnd 触发 cross-sub-PR memory handoff sediment append candidate reminder. 反 silent
session close without memory `project_sprint_state.md` handoff sediment (沿用铁律 37 + handoff_template.md
schema). WARN mode only (hookSpecificOutput cite + sys.exit 0). 反 BLOCK exit 2 (BLOCK on SessionEnd =
block session close = bad UX, sustained PR #280/#281 cite_drift / sediment_poststop WARN mode 体例累积).

scope (Phase 1, V3 step 4 sub-PR 4 sediment, narrowed scope per §4(d) push back sustained
PR #280/#281 LL-130 候选体例累积):

handoff sediment trigger types (4 类, sustained 铁律 37 + handoff_template.md schema):

| sediment type | hook coverage | rationale |
|---|---|---|
| recent-session-activity reminder | ✅ git log --since N min (low-risk runtime query) | static fact: did session period have commits / sub-PR closures |
| memory project_sprint_state.md line 0 prepend cite | ❌ deferred to skill SOP | requires content analysis per session scope (out of static hook scope) |
| sub-PR cumulative cite + 5/5 红线 sustained verify | ❌ deferred to skill SOP | requires session transcript analysis |
| LL/ADR candidate cumulative cite | ❌ deferred to skill SOP | requires LL/ADR registry diff per session period |

→ Hook surfaces "did you write SessionEnd handoff?" reminder; skill provides full SOP. 沿用 ADR-022 反
abstraction premature — hook does not own handoff workflow logic; quantmind-v3-doc-sediment-auto skill
(PR #281) is full sediment SOP source for HOW.

互补 hook (沿用 Constitution §0.3 layer enumeration L9 long-horizon coherence + §L6.2 handoff-sessionend
决议 — Constitution §L9 是 §0.3 enumeration cite, NOT body section per §0.3 declaration "本文件仅写
L0 / L1 / L5 / L6 / L8 / L10 六层"):
- sediment_poststop.py (Stop matcher, PR #281) — sub-PR 闭后 sediment append candidate (sub-PR scope)
- 本 hook (SessionEnd matcher) — session 关闭前 cross-sub-PR memory handoff sediment (cross-sub-PR scope)
- verify_completion.py (Stop matcher, existing) — doc 同步 reminder (different scope)
- quantmind-v3-doc-sediment-auto skill (PR #281, knowledge layer) — full sediment SOP active CC invoke

→ 三层 (skill / Stop hook / SessionEnd hook) + sibling hook (verify_completion) 0 scope 重叠. Stop matcher
= sub-PR scope, SessionEnd matcher = cross-sub-PR session-close scope.

WARN mode (反 BLOCK exit 2):
- BLOCK on SessionEnd = block session close = bad UX. SessionEnd hook semantics 反 BLOCK 体例.
- WARN surfaces SOP nudge via hookSpecificOutput → CC sees reminder before / during session close.
- Sustained PR #280 cite_drift_stop_pretool + PR #281 sediment_poststop WARN mode 体例累积.

bypass 体例 (沿用 PR #281 sediment_poststop bypass 体例 — SessionEnd hook input shape similar to
Stop hook, no command/content field, only env var bypass applies):
- env var QM_HANDOFF_BYPASS=1 (session-level)
- per-content marker N/A (SessionEnd hook input = session_id + transcript_path + reason, no command/content body)

⚠️ **CC self-authorization via env var bypass is X10/LL-098 anti-pattern violation**:
bypass MUST come from user-typed prompt content (Constitution §L8.1 (b) user 介入 SSOT).
反 CC self-construct env override silent skip.

audit row 18 真值 (sustained docs/audit/v3_orchestration/claude_dir_audit_report.md): "SessionEnd 类型
0 wire" gap — 本 hook 实施 + settings.json wire delta 是 gap closure delivery (沿用 ADR-022 反 silent
overwrite — 仅 add SessionEnd top-level key, 0 改现 4 wire types).

关联铁律: 33 (fail-loud / fail-safe / silent_ok 三选一; parse error fail-soft sys.exit(0)) /
          37 (Session 关闭前必写 handoff — 本 hook 是该铁律 enforcement layer) /
          42 (PR 分级审查制 — backend/** 必走 PR + reviewer + AI 自 merge)

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only, 反 hardcoded line# + 第 12 项 prompt 升级候选 #1 sustained
fresh re-read §0 scope declaration verify):
- Constitution §0.3 layer enumeration L9 long-horizon coherence (NOT body section per §0.3 scope)
- Constitution §L6.2 handoff-sessionend 决议 (4 全新 hook 之一)
- skeleton §3.2 hook 索引 (跟 sediment_poststop.py Stop matcher 互补)
- docs/audit/v3_orchestration/claude_dir_audit_report.md row 18 SessionEnd 0 wire gap (本 hook gap closure)
- docs/handoff_template.md (4 类 sediment SSOT)
- IRONLAWS §13 铁律 33 / IRONLAWS §15 铁律 37 (Session 关闭前必写 handoff)
- LL-117 候选 (atomic sediment+wire — 本 sub-PR 是第 4 实证累积 PR, promote trigger 满足)
- LL-130 候选 (hook regex coverage scope vs full SOP scope governance — Phase 1 narrowed scope sustained
  PR #280/#281 双 PR 实证累积)
- LL-124 候选 (hook regex context-agnostic intentional design)
- skill quantmind-v3-doc-sediment-auto (PR #281, full sediment SOP knowledge layer)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# Lookback window: detect commits made within current session period (proxy: last N minutes).
# Sustained PR #281 sediment_poststop体例 + Phase 1 narrowed scope per §4(d) push back.
LOOKBACK_MINUTES = 60  # SessionEnd 触发时 session period 通常更长, 60 min 比 Stop 30 min 宽


def _is_bypassed() -> bool:
    """Check bypass via env var (session-level only — SessionEnd hook input has no command/content).

    沿用 PR #281 sediment_poststop bypass 体例 + redline_pretool_block.py session-level 体例.
    """
    return os.environ.get("QM_HANDOFF_BYPASS") == "1"


def _has_session_activity() -> bool:
    """Check if session period had any commits (proxy: last LOOKBACK_MINUTES min).

    Sustained PR #281 sediment_poststop._has_recent_commits 体例 (low-risk runtime query +
    fail-soft on git failure 反 break SessionEnd event).
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


def _emit_handoff_reminder(reason: str) -> None:
    """WARN mode: surface SOP nudge via hookSpecificOutput, sys.exit(0).

    沿用 PR #281 sediment_poststop._emit_reminder + cite_drift_stop_pretool._emit_warn_and_pass 体例累积.
    """
    result = {
        "hookSpecificOutput": {
            "hookEventName": "SessionEnd",
            "additionalContext": (
                f"REMINDER (handoff_sessionend): SessionEnd event reason={reason!r} with session "
                f"activity in last {LOOKBACK_MINUTES} min. "
                "沿用铁律 37 (Session 关闭前必写 handoff) + handoff_template.md schema — "
                "session 关闭前 cross-sub-PR memory handoff sediment 4 类 append candidate checklist: "
                "(a) memory `project_sprint_state.md` line 0 prepend cite (沿用铁律 37 sub-PR 闭后 "
                "handoff sediment 体例) / "
                "(b) sub-PR cumulative cite + 5/5 红线 sustained verify (cash / 0 持仓 / "
                "LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID) / "
                "(c) LL append candidate cumulative cite (LESSONS_LEARNED.md 沿用 LL-105 SOP-6 cross-verify) / "
                "(d) ADR row sediment candidate cumulative cite (docs/adr/REGISTRY.md + ADR-DRAFT.md). "
                "沿用 quantmind-v3-doc-sediment-auto skill SOP (PR #281, full 4 类 sediment SOP knowledge "
                "layer) for HOW. 反 silent skip 沿用 LL-098 X10 反 forward-progress + ADR-022 集中机制. "
                "bypass: env QM_HANDOFF_BYPASS=1 (session-level only — CC self-authorize is "
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
        # 沿用 protect_critical_files.py + redline_pretool_block.py + cite_drift_stop_pretool.py +
        # sediment_poststop.py fail-soft 体例累积 (反 break SessionEnd event 沿用)
        sys.exit(0)

    # bypass check 优先 (沿用 user 显式触发 SSOT)
    if _is_bypassed():
        sys.exit(0)

    # Phase 1 narrowed scope: only fire if session activity detected in lookback period.
    # 反 false positive on SessionEnd events without sediment-worthy activity (e.g. brief
    # session, only read operations, or empty repo).
    if not _has_session_activity():
        sys.exit(0)

    # Extract reason for cite (Anthropic SessionEnd input semantic standard:
    # session_id / transcript_path / reason {"exit", "clear", "logout", etc.})
    reason = input_data.get("reason", "unknown")

    # WARN mode (反 BLOCK on SessionEnd) — surface SOP nudge via hookSpecificOutput
    _emit_handoff_reminder(reason)


if __name__ == "__main__":
    main()
