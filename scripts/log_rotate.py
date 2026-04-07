#!/usr/bin/env python3
"""日志清理脚本 — 清理>30天的旧日志文件。

R6 §7.4: RotatingFileHandler处理单文件rotation，
本脚本负责清理整个logs/目录中过期的日志文件。

用法:
    python scripts/log_rotate.py              # 清理>30天
    python scripts/log_rotate.py --days 7     # 清理>7天
    python scripts/log_rotate.py --dry-run    # 仅列出待清理文件

调度: Task Scheduler 每日 06:00
"""

import argparse
import logging
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("log_rotate")

# 保护文件: 不删除这些
PROTECTED_FILES = {
    "pt_heartbeat.json",  # watchdog心跳文件
}

# 清理的文件扩展名
CLEANABLE_EXTENSIONS = {".log", ".log.1", ".log.2", ".log.3", ".log.4", ".log.5",
                         ".log.6", ".log.7", ".log.8", ".log.9", ".log.10"}


def should_clean(path: Path, max_age_days: int) -> bool:
    """判断文件是否应清理。"""
    if path.name in PROTECTED_FILES:
        return False
    if path.suffix not in CLEANABLE_EXTENSIONS and not path.name.endswith(".log"):
        return False
    age_days = (time.time() - path.stat().st_mtime) / 86400
    return age_days > max_age_days


def rotate_logs(max_age_days: int = 30, dry_run: bool = False) -> int:
    """清理过期日志文件。

    Args:
        max_age_days: 保留天数阈值。
        dry_run: 仅列出不删除。

    Returns:
        清理的文件数量。
    """
    if not LOG_DIR.exists():
        logger.warning(f"日志目录不存在: {LOG_DIR}")
        return 0

    cleaned = 0
    total_bytes = 0

    for f in sorted(LOG_DIR.iterdir()):
        if not f.is_file():
            continue
        if should_clean(f, max_age_days):
            size = f.stat().st_size
            age = (time.time() - f.stat().st_mtime) / 86400
            if dry_run:
                logger.info(f"[DRY-RUN] 待清理: {f.name} ({size/1024:.0f}KB, {age:.0f}天)")
            else:
                try:
                    f.unlink()
                    logger.info(f"已清理: {f.name} ({size/1024:.0f}KB, {age:.0f}天)")
                except OSError as e:
                    logger.error(f"清理失败: {f.name} — {e}")
                    continue
            cleaned += 1
            total_bytes += size

    if cleaned > 0:
        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}共清理 {cleaned} 个文件, "
            f"释放 {total_bytes/1024/1024:.1f}MB"
        )
    else:
        logger.info(f"无需清理 (>{max_age_days}天的日志文件)")

    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser(description="QuantMind V2 日志清理")
    parser.add_argument("--days", type=int, default=30, help="保留天数(默认30)")
    parser.add_argument("--dry-run", action="store_true", help="仅列出不删除")
    args = parser.parse_args()

    logger.info(f"日志清理启动: 目录={LOG_DIR}, 保留>{args.days}天, dry_run={args.dry_run}")
    rotate_logs(max_age_days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
