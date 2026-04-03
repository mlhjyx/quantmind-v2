"""Hook: Session启动上下文恢复。

触发: SessionStart
功能: 注入当前状态、关键路径、铁律速查
"""

import json
import re
import sys
from pathlib import Path


def get_current_state(project_root: Path) -> str:
    """从PROGRESS.md提取当前状态。"""
    progress = project_root / "PROGRESS.md"
    if not progress.exists():
        return "PROGRESS.md not found"
    try:
        content = progress.read_text(encoding="utf-8")[:2000]
        sprint_match = re.search(r"Sprint\s+(\d+\.\d+)", content)
        sprint = sprint_match.group(0) if sprint_match else "unknown"
        pt_match = re.search(r"Day\s+(\d+)/60", content)
        pt = f"PT Day {pt_match.group(1)}/60" if pt_match else ""
        nav_match = re.search(r"NAV[=:]\s*[¥￥]?([\d,.]+)", content)
        nav = f"NAV=¥{nav_match.group(1)}" if nav_match else ""
        return f"{sprint}, {pt} {nav}".strip()
    except Exception:
        return "parse error"


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    state = get_current_state(project_root)

    context = f"""SESSION START CONTEXT:
当前状态: {state}

关键路径:
- CLAUDE.md (硬规则+铁律+配置)
- SYSTEM_RUNBOOK.md (运行手册)
- docs/IMPLEMENTATION_MASTER.md (实施总纲)
- docs/QUANTMIND_V2_DDL_FINAL.sql (建表唯一来源)

铁律速查: 1.因子+中性化 2.回测验证 3.验代码不信文档 4.ML必须OOS 5.因子→策略匹配 6.改动后更新文档"""

    from datetime import datetime
    audit_log = project_root / ".claude" / "hooks" / "audit.log"
    try:
        with open(audit_log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | SESSION_START\n")
    except Exception:
        pass

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
