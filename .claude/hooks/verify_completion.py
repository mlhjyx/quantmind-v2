"""Harness Hook: 完成前综合验证 — 约束层核心。

触发: Stop
功能: Claude尝试停止时，综合检查多条铁律是否被遵守
- 铁律6: PROGRESS.md是否有变更（git diff检测）— **阻断**
- §6.5: 编码agent是否有对应审查agent — **阻断**
- 铁律4: Sprint复盘是否完成（检测Sprint结束标志）— 提醒
- 交叉审查: 编码任务是否有review记录 — 提醒
- 铁律1: 大量编码但没spawn agent — 提醒
- §5.2: 任务复盘提醒 — 提醒
退出码: 0=允许停止, 2=阻断停止（必须修正后才能停止）

升级记录:
- Sprint 1.15: check_progress_updated + check_cross_review_executed 从提醒升级为阻断 (LL-031)
"""

import json
import re
import subprocess
import sys
from pathlib import Path


def check_progress_updated(project_root: Path) -> str | None:
    """铁律6 [阻断]: 检查PROGRESS.md是否在本次会话中有变更。"""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )

        all_changed = result.stdout.strip() + "\n" + unstaged.stdout.strip()

        # 统计代码变更文件数
        code_files = [
            f for f in all_changed.split("\n")
            if f.strip() and (f.endswith(".py") or f.endswith(".tsx") or f.endswith(".ts"))
        ]
        progress_updated = "PROGRESS.md" in all_changed

        # 只有>=3个代码文件变更时才阻断（避免小修改误报）
        if len(code_files) >= 3 and not progress_updated:
            return (
                f"铁律6违反 [阻断]: 有{len(code_files)}个代码文件变更但PROGRESS.md未更新。\n"
                "  修正方法: 编辑PROGRESS.md，更新本次会话的任务状态和进度。\n"
                "  修正后再次尝试停止。"
            )
    except Exception:
        pass
    return None


def check_sprint_review(project_root: Path) -> str | None:
    """铁律4 [提醒]: 如果检测到Sprint结束标志，提醒复盘。"""
    try:
        result = subprocess.run(
            ["git", "log", "-5", "--format=%s"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        recent_msgs = result.stdout.lower()
        sprint_end_keywords = ["sprint完成", "sprint结束", "sprint complete", "sprint done"]
        if any(kw in recent_msgs for kw in sprint_end_keywords):
            return (
                "铁律4提醒: 检测到Sprint结束。必须执行复盘流程:\n"
                "  1. 更新PROGRESS.md（铁律6）\n"
                "  2. spawn复盘agent，技术5问+投资人3问\n"
                "  3. 经验教训→LESSONS_LEARNED.md\n"
                "  4. 技术决策→TECH_DECISIONS.md\n"
                "  5. 执行记分卡（铁律违规次数）"
            )
    except Exception:
        pass
    return None


def check_cross_review_needed(project_root: Path) -> str | None:
    """交叉审查 [提醒]: 如果有大量代码变更，提醒需要review。"""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "--cached"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        all_stats = result.stdout + unstaged.stdout

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
    """铁律1+5 [提醒]: 从审计日志检测模式违规。"""
    audit_log = project_root / ".claude" / "hooks" / "audit.log"
    if not audit_log.exists():
        return None

    try:
        lines = audit_log.read_text(encoding="utf-8").strip().split("\n")
        # 只扫描当前session（从最后一个SESSION_START开始）
        session_start_idx = 0
        for i in range(len(lines) - 1, -1, -1):
            if "SESSION_START" in lines[i]:
                session_start_idx = i + 1
                break
        recent = lines[session_start_idx:]

        has_agent = any("Agent" in line for line in recent)

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


def check_cross_review_executed(project_root: Path) -> str | None:
    """§6.5 Generator-Evaluator分离 [阻断]: 有编码agent但没有审查agent。"""
    audit_log = project_root / ".claude" / "hooks" / "audit.log"
    if not audit_log.exists():
        return None

    try:
        lines = audit_log.read_text(encoding="utf-8").strip().split("\n")

        # 只扫描当前session的条目（从最后一个SESSION_START标记开始）
        session_start_idx = 0
        for i in range(len(lines) - 1, -1, -1):
            if "SESSION_START" in lines[i]:
                session_start_idx = i + 1
                break
        recent = lines[session_start_idx:]

        # 项目专用编码角色（精确匹配，排除OMC通用agent）
        coding_agent_types = {"arch", "frontend-dev", "alpha-miner", "ml-engineer", "data-engineer"}
        review_agent_types = {"qa-tester", "quant-reviewer", "risk-guardian"}
        # OMC通用agent不算编码角色（architect/executor/explore等）
        omc_exclude_patterns = {
            "oh-my-claudecode", "omc", "architect", "executor",
            "explore", "planner", "designer", "writer", "verifier",
            "code-reviewer", "code-simplifier", "feature-dev",
        }

        agent_lines = [line for line in recent if "Agent" in line]

        spawned_coding = False
        spawned_review = False

        for line in agent_lines:
            line_lower = line.lower()

            # 排除OMC通用agent
            is_omc = any(pat in line_lower for pat in omc_exclude_patterns)
            if is_omc:
                continue

            # 匹配 [subagent_type] 格式（audit_log.py升级后）
            for agent in coding_agent_types:
                if f"[{agent}]" in line_lower or f":{agent}]" in line_lower:
                    spawned_coding = True
                    break
            for agent in review_agent_types:
                if f"[{agent}]" in line_lower or f":{agent}]" in line_lower:
                    spawned_review = True
                    break
            # 兼容旧格式（description中包含角色名，用词边界匹配避免arch匹配architect）
            if not spawned_coding:
                for agent in coding_agent_types:
                    # 精确匹配：前后必须是非字母字符

                    if re.search(rf'\b{re.escape(agent)}\b', line_lower) and "Agent" in line:
                        spawned_coding = True
                        break
            if not spawned_review:
                for agent in review_agent_types:

                    if re.search(rf'\b{re.escape(agent)}\b', line_lower) and "Agent" in line:
                        spawned_review = True
                        break

        if spawned_coding and not spawned_review:
            return (
                "§6.5违反 [阻断]: 有编码agent被spawn但未spawn审查agent。\n"
                "  宪法要求: 产出方≠审查方。编码完成后必须由交叉审查角色review:\n"
                "  arch→qa+data, factor→quant+strategy+risk, alpha_miner→factor+quant\n"
                "  修正方法: spawn对应的审查agent（qa-tester/quant-reviewer/risk-guardian）完成交叉审查。\n"
                "  修正后再次尝试停止。"
            )
    except Exception:
        pass
    return None


def check_task_retrospective(project_root: Path) -> str | None:
    """任务/Sprint完成时 [提醒]: 必须有复盘总结+改善建议。"""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        all_changed = result.stdout.strip() + "\n" + unstaged.stdout.strip()
        py_changes = sum(1 for f in all_changed.split("\n")
                         if f.strip() and f.endswith(".py"))

        if py_changes >= 3:
            return (
                "任务复盘提醒(§5.2): 本次会话有实质性编码工作，停止前请完成:\n"
                "  1. 设计对照: 实现是否符合DEV文档规格？偏差列表\n"
                "  2. 质量总结: 测试通过率/ruff状态/已知问题\n"
                "  3. 改善建议: 发现的流程/工具/规范可改进项\n"
                "  4. 经验教训: 值得记入LESSONS_LEARNED的发现\n"
                "  5. 下一步: 后续任务的依赖/阻塞/建议\n"
                "  如果是Sprint结束，还须按§5.6模板输出Sprint完成报告给用户:\n"
                "  计划vs实际 / 交付物清单 / 关键指标 / 质量与风险 / 经验教训 / 改善建议 / 下一步\n"
                "  如已完成复盘输出，可以忽略此提醒。"
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

    # 分离阻断检查和提醒检查
    blocking_issues = []
    advisory_issues = []

    # === 阻断检查（exit 2）===
    progress_issue = check_progress_updated(project_root)
    if progress_issue:
        blocking_issues.append(progress_issue)

    cross_review_issue = check_cross_review_executed(project_root)
    if cross_review_issue:
        blocking_issues.append(cross_review_issue)

    # === 提醒检查（exit 0）===
    sprint_issue = check_sprint_review(project_root)
    if sprint_issue:
        advisory_issues.append(sprint_issue)

    review_issue = check_cross_review_needed(project_root)
    if review_issue:
        advisory_issues.append(review_issue)

    audit_issue = check_audit_log_for_patterns(project_root)
    if audit_issue:
        advisory_issues.append(audit_issue)

    retro_issue = check_task_retrospective(project_root)
    if retro_issue:
        advisory_issues.append(retro_issue)

    # === 阻断路径: 有阻断问题时 exit(2) 阻止停止 ===
    if blocking_issues:
        block_msg = "BLOCKED — 停止被阻断，必须修正以下问题:\n\n"
        for i, issue in enumerate(blocking_issues, 1):
            block_msg += f"[{i}] {issue}\n\n"

        if advisory_issues:
            block_msg += "另外还有以下提醒:\n"
            for issue in advisory_issues:
                block_msg += f"  - {issue}\n"

        # exit(2) 阻断: 输出到stderr让Claude看到
        print(block_msg, file=sys.stderr)
        sys.exit(2)

    # === 提醒路径: 无阻断问题时 exit(0) 允许停止但注入提醒 ===
    checklist = "COMPLETION CHECKLIST (Harness综合验证):\n"

    if advisory_issues:
        checklist += "\n⚠️ 检测到以下提醒:\n"
        for issue in advisory_issues:
            checklist += f"\n{issue}\n"
        checklist += "\n"

    checklist += (
        "标准检查:\n"
        "- [ ] 所有TODO已完成?\n"
        "- [ ] ruff check通过?\n"
        "- [ ] 相关测试运行过?\n"
        "- [ ] PROGRESS.md需要更新? (铁律6)\n"
        "- [ ] 需要交叉审查? (宪法§6.3)\n"
        "- [ ] 设计对照+复盘总结已输出? (§5.2)\n"
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
