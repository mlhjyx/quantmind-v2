"""Hook: 完成前综合验证。

触发: Stop
功能: 提醒更新文档(铁律6)和复盘
退出码: 始终0（仅提醒）
"""

import json
import subprocess
import sys
from pathlib import Path


def check_docs_updated(project_root: Path) -> str | None:
    """铁律6: 重大改动后文档是否更新。"""
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
            docs_updated = any(f in all_changed for f in ["CLAUDE.md", "PROGRESS.md"])
            if not docs_updated:
                return f"铁律6: {len(code_files)}个代码文件变更但CLAUDE.md/PROGRESS.md未更新。"
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

    doc_issue = check_docs_updated(project_root)
    if doc_issue:
        issues.append(doc_issue)

    checklist = "COMPLETION CHECKLIST:\n"
    if issues:
        checklist += "\n".join(f"  - {i}" for i in issues) + "\n\n"
    checklist += (
        "- [ ] ruff check通过?\n"
        "- [ ] 相关测试运行过?\n"
        "- [ ] CLAUDE.md/PROGRESS.md需要更新?\n"
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
