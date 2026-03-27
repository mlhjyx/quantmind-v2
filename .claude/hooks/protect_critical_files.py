"""Harness Hook: 关键文件保护 — 防止误改。

触发: PreToolUse[Edit|Write]
功能: 阻止对受保护文件的直接修改
退出码: 0=通过, 2=阻止
"""

import json
import re
import sys


# 完全禁止修改的文件
BLOCKED_PATTERNS = [
    r"\.env$",
    r"\.env\.local$",
    r"\.env\.production$",
    r"credentials",
    r"\.git/",
]

# 需要警告但不阻止的文件（输出提醒到context）
WARN_PATTERNS = [
    r"TEAM_CHARTER_V3\.3\.md",  # 宪法文件，只有用户能改
    r"docs/QUANTMIND_V2_DDL_FINAL\.sql",  # DDL唯一来源
    r"docs/QUANTMIND_V2_DESIGN_V5\.md",  # 设计圣经
]


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        sys.exit(0)

    # 规范化路径
    normalized = file_path.replace("\\", "/")

    # 检查完全阻止的文件
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            print(f"BLOCKED: {file_path} 是受保护文件，不允许通过Claude Code修改。", file=sys.stderr)
            sys.exit(2)

    # 检查需要警告的文件
    for pattern in WARN_PATTERNS:
        if re.search(pattern, normalized):
            # 输出warning到context（不阻止）
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": f"WARNING: 你正在修改关键文件 {file_path}。确保这是用户明确要求的变更，不要自行决定范围外的改动（工作原则5）。"
                }
            }
            print(json.dumps(result))
            sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
