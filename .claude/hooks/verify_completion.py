"""Hook: 完成前综合验证 (v2 2026-05-09 V3 实施期扩展).

触发: Stop
功能: 提醒更新文档 (铁律 6) + 复盘 + V3 实施期扩展 (4 元素 cite source 锁定 reminder + 真+词 reject)

v2 扩展 (V3 step 4 sub-PR 5, sustained Constitution v0.2 §L5.1 cite source 锁定 SOP + §L6.2 line
278-279 决议 — cite-source-poststop + banned-words-poststop 合并到 verify_completion.py 现有
扩展, 沿用 ADR-022 反 silent overwrite + 反 abstraction premature):
  - 4 元素 cite source 锁定 reminder (path + line# + section + timestamp, 沿用 quantmind-v3-cite-
    source-lock skill SOP) — Phase 1 narrowed scope: surface reminder via hookSpecificOutput,
    full cite verify deferred to skill SOP active CC invoke
  - 真+词 / sustained 中文滥用 detect (memory #25 HARD BLOCK whitelist: 真账户 / 真发单 / 真生产 /
    真测 / 真值; banned: anything else 沿用 quantmind-v3-banned-words skill SOP) — Phase 1 narrowed
    scope: regex-based detect via git diff staged content, surface WARN; auto-rewrite deferred to
    skill SOP

v1 sustained (反 silent overwrite):
  - 检 docs updated (铁律 6) reminder

退出码: 始终 0 (反 BLOCK 沿用 PR #280/#281/#282 三 PR WARN mode 体例累积; Stop event semantic
constraint — BLOCK on Stop = block CC turn finish = bad UX)

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §L5.1 cite source 锁定 SOP (4 元素体例)
- Constitution §L6.2 line 278-279 cite-source-poststop + banned-words-poststop 合并决议
- skeleton §3.2 现有 hook 扩展真值
- LL-130 候选 (hook regex coverage scope vs full SOP scope governance — Phase 1 narrowed scope)
- skill quantmind-v3-cite-source-lock (PR #272, full 4 元素 cite SOP knowledge layer)
- skill quantmind-v3-banned-words (PR #273, full 真+词 SOP knowledge layer)
- memory #25 HARD BLOCK (真+词 whitelist 5 forms only)
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# v2 扩展: banned 真+词 regex (memory #25 HARD BLOCK whitelist sustained quantmind-v3-banned-words skill).
# whitelist: 真账户 / 真发单 / 真生产 / 真测 / 真值 (5 forms only, 沿用 .claude/skills/quantmind-v3-
# banned-words/SKILL.md 规定). banned scope: 真 + Chinese-char-NOT-in-whitelist (反 meta-syntax
# `真+词` 自检 false positive — exclude non-Chinese chars per Chinese compound form intent of #25).
BANNED_ZHEN_PATTERN = re.compile(r"真(?![账发生测值])[一-鿿]")


def check_docs_updated(project_root: Path) -> str | None:
    """铁律 6: 重大改动后文档是否更新 (v1 sustained)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(project_root), capture_output=True, text=True, timeout=5,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(project_root), capture_output=True, text=True, timeout=5,
        )
        all_changed = result.stdout.strip() + "\n" + unstaged.stdout.strip()
        code_files = [f for f in all_changed.split("\n")
                      if f.strip() and (f.endswith(".py") or f.endswith(".tsx") or f.endswith(".ts"))]

        if len(code_files) >= 3:
            docs_updated = any(f in all_changed for f in ["CLAUDE.md", "SYSTEM_STATUS.md", "SYSTEM_RUNBOOK.md"])
            if not docs_updated:
                return f"铁律 15/重构原则: {len(code_files)} 个代码文件变更但 CLAUDE.md/SYSTEM_STATUS.md/SYSTEM_RUNBOOK.md 未更新."
    except Exception:
        pass
    return None


def check_banned_zhen_in_staged(project_root: Path) -> str | None:
    """v2 扩展: detect banned 真+词 in staged content (Phase 1 narrowed scope, WARN-only).

    沿用 memory #25 HARD BLOCK + quantmind-v3-banned-words skill SOP. Whitelist 5 forms only:
    真账户 / 真发单 / 真生产 / 真测 / 真值. Anything else outside whitelist → WARN surface.

    fail-soft on git failure (反 break Stop event 沿用).
    """
    try:
        # Read staged diff content (git diff --cached for staged, fall back to HEAD diff)
        result = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=str(project_root), capture_output=True, text=True, timeout=5,
        )
        staged_content = result.stdout
        if not staged_content:
            # Fallback: check unstaged + HEAD diff
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=str(project_root), capture_output=True, text=True, timeout=5,
            )
            staged_content = result.stdout
        if not staged_content:
            return None

        # Filter to lines starting with `+` (added/modified content)
        added_lines = [ln for ln in staged_content.split("\n") if ln.startswith("+") and not ln.startswith("+++")]
        added_text = "\n".join(added_lines)

        matches = BANNED_ZHEN_PATTERN.findall(added_text)
        if matches:
            unique_matches = list(set(matches))[:5]  # cap at 5 unique for nudge brevity
            return (
                f"⚠️ 真+词 detect (memory #25 HARD BLOCK + quantmind-v3-banned-words skill SOP): "
                f"staged content 含 banned 真+词 (whitelist: 真账户/真发单/真生产/真测/真值). "
                f"matched samples: {unique_matches!r}. 沿用 quantmind-v3-banned-words skill SOP "
                f"reject + auto-rewrite (Phase 1 hook = WARN surface only, full reject deferred to "
                f"skill SOP active CC invoke)."
            )
    except Exception:
        pass  # silent_ok: fail-soft 反 break Stop event
    return None


def cite_source_lock_reminder() -> str:
    """v2 扩展: 4 元素 cite source 锁定 reminder (Phase 1 narrowed scope, surface only).

    沿用 Constitution §L5.1 cite source 锁定 SOP + quantmind-v3-cite-source-lock skill SOP.
    Phase 1 hook = surface reminder; full 4 元素 verify deferred to skill SOP active CC invoke.
    """
    return (
        "📋 4 元素 cite source 锁定 (沿用 Constitution §L5.1 + quantmind-v3-cite-source-lock skill SOP): "
        "任 cite (数字 / 编号 / 路径 / audit / Constitution / V3 / IRONLAWS / SESSION_PROTOCOL / LL / "
        "ADR / 铁律) 必含 4 元素: (a) path / (b) line# (单行或范围) / (c) section anchor / "
        "(d) fresh verify timestamp. Phase 1 hook = reminder, full verify deferred to skill SOP."
    )


def main():
    try:
        json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        pass

    project_root = Path(__file__).resolve().parent.parent.parent
    issues = []

    doc_issue = check_docs_updated(project_root)
    if doc_issue:
        issues.append(doc_issue)

    # v2 扩展: 真+词 detect (memory #25 HARD BLOCK)
    zhen_issue = check_banned_zhen_in_staged(project_root)
    if zhen_issue:
        issues.append(zhen_issue)

    checklist = "COMPLETION CHECKLIST:\n"
    if issues:
        checklist += "\n".join(f"  - {i}" for i in issues) + "\n\n"
    checklist += (
        "- [ ] ruff check 通过?\n"
        "- [ ] 相关测试运行过?\n"
        "- [ ] CLAUDE.md/SYSTEM_STATUS.md 需要更新?\n"
        "\n"
        # v2 扩展: 4 元素 cite source 锁定 reminder (always surfaced)
        f"{cite_source_lock_reminder()}\n"
    )

    result = {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": checklist,
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
