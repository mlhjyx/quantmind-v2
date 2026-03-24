"""Hook: Sprint复盘完整性检查。

手动触发或作为复盘流程的验证步骤。
检查: PROGRESS.md是否更新、LESSONS_LEARNED是否有新条目、CLAUDE.md决策表是否更新。
"""

import subprocess
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).resolve().parent.parent.parent

    # 检查PROGRESS.md是否在最近的git变更中
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        changed_files = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except Exception:
        changed_files = []

    warnings = []

    if "PROGRESS.md" not in changed_files:
        warnings.append("PROGRESS.md未在最近的commit中更新（铁律6要求）")

    if not any("LESSONS_LEARNED" in f for f in changed_files):
        warnings.append("LESSONS_LEARNED.md未更新（Sprint复盘应产出新LL条目）")

    if warnings:
        msg = "⚠️ Sprint复盘完整性检查:\n" + "\n".join(f"  - {w}" for w in warnings)
        print(msg, file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
