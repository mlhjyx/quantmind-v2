"""Hook: 新会话开始时强制检查（§13.2升级：文档→代码）。

触发时机: SessionStart hook
功能:
1. 检查PROGRESS.md是否过期（>3天）
2. 提醒读记忆文件
3. 强制提醒：读宪法§1 + 建团队 + 附录A（LL-027）
"""

import re
import sys
from datetime import date, datetime
from pathlib import Path


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    progress_file = project_root / "PROGRESS.md"

    # --- 1. PROGRESS.md过期检查 ---
    if not progress_file.exists():
        print("⚠️ PROGRESS.md不存在！需要创建。", file=sys.stderr)
    else:
        content = progress_file.read_text(encoding="utf-8")
        match = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", content)
        if match:
            last_updated = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            days_since = (date.today() - last_updated).days
            if days_since > 3:
                print(
                    f"⚠️ PROGRESS.md已{days_since}天未更新（上次: {last_updated}）。"
                    f"宪法§7.3: 超过3天需先更新再干活。",
                    file=sys.stderr,
                )

    # --- 2. 记忆文件提醒 ---
    memory_dir = Path.home() / ".claude" / "memory"
    if memory_dir.exists():
        memory_files = list(memory_dir.glob("*.md"))
        if memory_files:
            print(
                f"📋 记忆文件：{len(memory_files)}个，请读取 current_state.md 恢复上下文。",
                file=sys.stderr,
            )

    # --- 3. LL-027强制提醒：团队管理规范 ---
    print(
        "\n🚨 LL-027强制提醒（§13.2升级执行）：\n"
        "   1. 读 TEAM_CHARTER_V3.md §1全文（不只是CLAUDE.md摘要）\n"
        "   2. 用 TeamCreate 建持久化团队\n"
        "   3. Spawn前复制附录A的角色Prompt + §1.3四项信息\n"
        "   4. 用户给的计划有N个角色 → 必须spawn N个角色，不能跳过\n"
        "   5. 你是合伙人（§1.5），不是任务分配器\n",
        file=sys.stderr,
    )

    # --- 4. 检查是否有活跃团队 ---
    teams_dir = Path.home() / ".claude" / "teams"
    if teams_dir.exists():
        active_teams = [d.name for d in teams_dir.iterdir() if d.is_dir()]
        if active_teams:
            print(
                f"📋 活跃团队: {', '.join(active_teams)}",
                file=sys.stderr,
            )
        else:
            print(
                "⚠️ 无活跃团队。如果要开始Sprint，先用TeamCreate建团队。",
                file=sys.stderr,
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
