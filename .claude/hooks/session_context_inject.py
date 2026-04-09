"""Hook: Session启动上下文恢复。

触发: SessionStart
功能: 注入当前状态、关键路径、铁律速查
"""

import json
import re
import sys
from pathlib import Path


def get_current_state(project_root: Path) -> str:
    """从 SYSTEM_STATUS.md §0 提取当前状态 (Step 6-B 更新: PROGRESS.md 已废弃)。"""
    status = project_root / "SYSTEM_STATUS.md"
    if not status.exists():
        return "SYSTEM_STATUS.md not found"
    try:
        content = status.read_text(encoding="utf-8")[:4000]
        # Match "Step 0→6-B" or latest Step marker
        step_match = re.search(r"Step\s+[0-9a-zA-Z\-→\s]+(?=重构|完成|窗口|进行)", content)
        step = step_match.group(0).strip() if step_match else "unknown"
        # Match baseline Sharpe
        sharpe_match = re.search(r"Sharpe[=:\s]*(\d+\.\d+)", content)
        sharpe = f"Sharpe={sharpe_match.group(1)}" if sharpe_match else ""
        return f"{step}, {sharpe}".strip().rstrip(",")
    except Exception:
        return "parse error"


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    state = get_current_state(project_root)

    context = f"""SESSION START CONTEXT:
当前状态: {state}

关键路径:
- CLAUDE.md (硬规则+18条铁律+配置)
- SYSTEM_STATUS.md (系统现状 §0含重构完成状态)
- SYSTEM_RUNBOOK.md (运行手册)
- docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (总路线图 §第四部分含Step 0→6-B重构)
- docs/QUANTMIND_V2_DDL_FINAL.sql (建表唯一来源)

铁律速查: 2.验代码不信文档 4.因子+中性化 5.paired bootstrap 7.数据地基 8.ML必须OOS 9.重数据串行 14.引擎不清洗 15.可复现 16.信号路径唯一 17.DataPipeline入库"""

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
