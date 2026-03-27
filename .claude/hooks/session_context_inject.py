"""Harness Hook: Session启动/Compaction后上下文恢复 — 信息层核心。

触发: SessionStart
功能: 注入关键上下文，确保新session/compaction后不丢失状态
- 当前Sprint状态
- 关键文件路径
- 铁律摘要
- 恢复协议提醒
"""

import json
import re
import sys
from pathlib import Path


def get_current_sprint(project_root: Path) -> str:
    """从PROGRESS.md提取当前Sprint信息。"""
    progress = project_root / "PROGRESS.md"
    if not progress.exists():
        return "PROGRESS.md not found"
    try:
        content = progress.read_text(encoding="utf-8")[:2000]  # 只读前2000字符
        # 提取Sprint信息
        sprint_match = re.search(r"Sprint\s+(\d+\.\d+)", content)
        sprint = sprint_match.group(0) if sprint_match else "unknown"
        # 提取PT状态
        pt_match = re.search(r"Day\s+(\d+)/60", content)
        pt = f"PT Day {pt_match.group(1)}/60" if pt_match else "PT status unknown"
        return f"{sprint}, {pt}"
    except Exception:
        return "parse error"


def main():
    project_root = Path(__file__).resolve().parent.parent.parent

    sprint_info = get_current_sprint(project_root)

    context = f"""SESSION START CONTEXT (Harness自动注入):
当前状态: {sprint_info}
v1.1配置锁死: 5因子等权Top15月度, 不修改

恢复协议:
1. 读PROGRESS.md确认Sprint进度
2. 读docs/IMPLEMENTATION_MASTER.md了解Sprint任务
3. 如要编码: 先读TEAM_CHARTER_V3.3.md §1 → spawn角色

关键路径:
- 实施总纲: docs/IMPLEMENTATION_MASTER.md (117项/10Sprint)
- 设计审计: docs/DEVELOPMENT_BLUEPRINT.md (62%完成)
- 宪法: TEAM_CHARTER_V3.3.md (8铁律)
- DDL: docs/QUANTMIND_V2_DDL_FINAL.sql
- 研究: docs/research/R1-R7

铁律速查: 1.spawn才算启动 2.因子+中性化 3.SimBroker回测 4.复盘不跳过 5.验代码不信文档 6.更新PROGRESS 7.ML必须OOS 8.因子→策略匹配"""

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
