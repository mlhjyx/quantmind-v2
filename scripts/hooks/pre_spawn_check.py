"""Hook: Agent spawn前检查。

触发时机: PreToolUse[Agent]
功能: 提醒Team Lead在spawn agent前检查角色定义和当前上下文。
退出码: 0=通过, 2=阻止并反馈
"""

import json
import sys


def main():
    # Claude Code passes hook context via stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    tool_input = input_data.get("tool_input", {})
    prompt = tool_input.get("prompt", "")

    # 检查spawn prompt是否包含关键上下文
    warnings = []

    # 检查是否提到了角色职责
    role_keywords = ["职责", "你是QuantMind", "你的职责", "核心职能"]
    has_role_def = any(kw in prompt for kw in role_keywords)
    if not has_role_def and len(prompt) > 50:
        warnings.append("Spawn prompt未包含角色定义（参考TEAM_CHARTER附录A）")

    # 检查是否提到了当前Sprint上下文
    context_keywords = ["Sprint", "Paper Trading", "当前"]
    has_context = any(kw in prompt for kw in context_keywords)
    if not has_context and len(prompt) > 50:
        warnings.append("Spawn prompt未包含当前Sprint上下文")

    if warnings:
        # 输出警告但不阻止（exit 0）
        # 用 exit 2 会阻止并发送反馈
        msg = "⚠️ Spawn检查提醒:\n" + "\n".join(f"  - {w}" for w in warnings)
        print(msg, file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
