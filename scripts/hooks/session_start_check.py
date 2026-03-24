"""Hook: 新会话开始时检查PROGRESS.md是否过期。

触发时机: 可作为用户prompt提交时的hook
功能: 检查PROGRESS.md的Last updated日期，超过3天则提醒更新。
"""

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


def main():
    progress_file = Path(__file__).resolve().parent.parent.parent / "PROGRESS.md"

    if not progress_file.exists():
        print("⚠️ PROGRESS.md不存在！需要创建。", file=sys.stderr)
        sys.exit(0)

    content = progress_file.read_text(encoding="utf-8")

    # 提取 Last updated 日期
    match = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", content)
    if not match:
        print("⚠️ PROGRESS.md缺少 'Last updated' 日期。", file=sys.stderr)
        sys.exit(0)

    last_updated = datetime.strptime(match.group(1), "%Y-%m-%d").date()
    days_since = (date.today() - last_updated).days

    if days_since > 3:
        print(
            f"⚠️ PROGRESS.md已{days_since}天未更新（上次: {last_updated}）。"
            f"宪法V3.2 §7.3要求：超过3天需先更新再干活。",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
