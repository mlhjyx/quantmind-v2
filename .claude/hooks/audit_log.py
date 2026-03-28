"""Harness Hook: 工具调用审计日志 — 熵管理层。

触发: PostToolUse (所有工具)
功能: 记录关键工具调用到审计日志，用于故障回溯和harness改进
- 只记录Write/Edit/Bash/Agent操作（不记录Read/Grep等只读操作）
- 日志滚动：保留最近500行
"""

import json
import sys
from datetime import datetime
from pathlib import Path


TRACKED_TOOLS = {"Write", "Edit", "Bash", "Agent"}
LOG_MAX_LINES = 500


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")

    if tool_name not in TRACKED_TOOLS:
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 构建日志行
    if tool_name == "Bash":
        detail = tool_input.get("command", "")[:100]
    elif tool_name in ("Write", "Edit"):
        detail = tool_input.get("file_path", "")
    elif tool_name == "Agent":
        subagent_type = tool_input.get("subagent_type", "")
        description = tool_input.get("description", "")[:60]
        detail = f"[{subagent_type}] {description}" if subagent_type else description
    else:
        detail = ""

    log_line = f"{timestamp} | {tool_name:6s} | {detail}\n"

    # 写入日志
    log_file = Path(__file__).resolve().parent / "audit.log"
    try:
        # 追加写入
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_line)

        # 滚动：超过MAX_LINES时截断
        lines = log_file.read_text(encoding="utf-8").splitlines()
        if len(lines) > LOG_MAX_LINES:
            log_file.write_text("\n".join(lines[-LOG_MAX_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        pass  # 日志不应该阻塞工作流

    sys.exit(0)


if __name__ == "__main__":
    main()
