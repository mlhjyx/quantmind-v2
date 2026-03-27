"""Harness Hook: 编辑后自动lint — 即时反馈。

触发: PostToolUse[Edit|Write]
功能: Python文件编辑后自动ruff check，错误信息注入context供Claude自动修复
退出码: 始终0（PostToolUse不能阻止，但输出会注入context）
"""

import json
import subprocess
import sys
from pathlib import Path


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or not file_path.endswith(".py"):
        sys.exit(0)

    # ruff check单文件
    try:
        result = subprocess.run(
            ["ruff", "check", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 and result.stdout.strip():
            errors = result.stdout.strip().split("\n")[:3]
            print(
                f"ruff lint issues in {Path(file_path).name}:\n"
                + "\n".join(f"  {e}" for e in errors)
                + "\nFix these before committing.",
                file=sys.stderr,
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
