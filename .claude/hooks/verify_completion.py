"""Harness Hook: 完成前综合验证 — 约束层核心。

触发: Stop
功能: Claude尝试停止时，综合检查多条铁律是否被遵守
- 铁律4: Sprint复盘是否完成（检测Sprint结束标志）
- 铁律6: PROGRESS.md是否有变更（git diff检测）
- 交叉审查: 编码任务是否有review记录
- 完成检查清单: TODO/ruff/测试提醒
退出码: 0=允许停止（注入提醒）
"""

import json
import subprocess
import sys
from pathlib import Path


def check_progress_updated(project_root: Path) -> str | None:
    """铁律6: 检查PROGRESS.md是否在本次会话中有变更。"""
    try:
        # 检查PROGRESS.md是否有未提交的变更
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )

        all_changed = (
            result.stdout.strip()
            + "\n"
            + staged.stdout.strip()
            + "\n"
            + unstaged.stdout.strip()
        )

        # 如果有代码变更但PROGRESS.md没更新
        has_code_changes = any(
            f.endswith(".py") or f.endswith(".tsx") or f.endswith(".ts")
            for f in all_changed.split("\n")
            if f.strip()
        )
        progress_updated = "PROGRESS.md" in all_changed

        if has_code_changes and not progress_updated:
            return "铁律6违反: 有代码变更但PROGRESS.md未更新。Sprint结束必更新PROGRESS.md。"
    except Exception:
        pass
    return None


def check_sprint_review(project_root: Path) -> str | None:
    """铁律4: 如果检测到Sprint结束标志，提醒复盘。"""
    try:
        # 检查最近的commit message是否包含Sprint结束标志
        result = subprocess.run(
            ["git", "log", "-5", "--format=%s"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        recent_msgs = result.stdout.lower()
        sprint_end_keywords = ["sprint完成", "sprint结束", "sprint complete", "sprint done"]
        if any(kw in recent_msgs for kw in sprint_end_keywords):
            return (
                "铁律4提醒: 检测到Sprint结束。必须执行复盘流程:\n"
                "  1. 更新PROGRESS.md（铁律6）\n"
                "  2. spawn复盘agent，技术5问+投资人3问\n"
                "  3. 经验教训→LESSONS_LEARNED.md\n"
                "  4. 技术决策→CLAUDE.md快查表\n"
                "  5. 执行记分卡（铁律违规次数）"
            )
    except Exception:
        pass
    return None


def check_cross_review_needed(project_root: Path) -> str | None:
    """交叉审查: 如果有大量代码变更，提醒需要review。"""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "--cached"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        all_stats = result.stdout + unstaged.stdout

        # 统计变更的Python文件数
        py_files_changed = sum(
            1
            for line in all_stats.split("\n")
            if ".py" in line and ("++" in line or "--" in line)
        )

        if py_files_changed >= 3:
            return (
                f"交叉审查提醒: 本次有{py_files_changed}个Python文件变更。\n"
                "  宪法§6.3要求: arch代码→qa+data审查, factor方案→quant+strategy+risk审查\n"
                "  审查方式必须验代码/跑数据，不是读文档同意（铁律5）"
            )
    except Exception:
        pass
    return None


def check_audit_log_for_patterns(project_root: Path) -> str | None:
    """铁律1+5: 从审计日志检测模式违规。"""
    audit_log = project_root / ".claude" / "hooks" / "audit.log"
    if not audit_log.exists():
        return None

    try:
        lines = audit_log.read_text(encoding="utf-8").strip().split("\n")
        # 取最近50行
        recent = lines[-50:] if len(lines) > 50 else lines

        has_agent = any("Agent" in line for line in recent)

        # 铁律1: 有大量编码但没有spawn agent（仅限本session）
        write_count = sum(
            1 for line in recent if "Write" in line or "Edit" in line
        )
        if write_count >= 5 and not has_agent:
            return (
                "铁律1提醒: 本次会话有大量编码操作但未spawn任何agent角色。\n"
                "  宪法要求: spawn了才算启动——非轻量任务应分配给对应领域角色。"
            )
    except Exception:
        pass
    return None


def main():
    try:
        json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        pass

    project_root = Path(__file__).resolve().parent.parent.parent
    issues = []

    # 运行所有检查
    progress_issue = check_progress_updated(project_root)
    if progress_issue:
        issues.append(progress_issue)

    sprint_issue = check_sprint_review(project_root)
    if sprint_issue:
        issues.append(sprint_issue)

    review_issue = check_cross_review_needed(project_root)
    if review_issue:
        issues.append(review_issue)

    audit_issue = check_audit_log_for_patterns(project_root)
    if audit_issue:
        issues.append(audit_issue)

    # 构建检查清单
    checklist = "COMPLETION CHECKLIST (Harness综合验证):\n"

    if issues:
        checklist += "\n⚠️ 检测到以下问题:\n"
        for issue in issues:
            checklist += f"\n{issue}\n"
        checklist += "\n"

    checklist += (
        "标准检查:\n"
        "- [ ] 所有TODO已完成?\n"
        "- [ ] ruff check通过?\n"
        "- [ ] 相关测试运行过?\n"
        "- [ ] PROGRESS.md需要更新? (铁律6)\n"
        "- [ ] 需要交叉审查? (宪法§6.3)\n"
        "如果以上有未完成项，继续工作而不是停止。"
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
