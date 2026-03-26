"""pg_dump 自动备份脚本 — 每日凌晨 Task Scheduler 调用。

功能:
- pg_dump ���出全库到 D:\pg_backups\quantmind_v2_YYYYMMDD.dump
- 保留最近7天，自动清理旧备份
- 备份完成后验证文件大小(>100MB视为正常)
- 失败时发送钉钉P0告警

用法:
    python scripts/pg_backup.py              # 正常备份
    python scripts/pg_backup.py --dry-run    # 仅打印命令不执行
    python scripts/pg_backup.py --verify     # 验证最新备份可恢复
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 项目根目录加入sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

logger = logging.getLogger("pg_backup")

# ── 配置 ──────────────────────────────────────────────
BACKUP_DIR = Path(r"D:\pg_backups")
PG_DUMP = Path(r"D:\pgsql\bin\pg_dump.exe")
PG_RESTORE = Path(r"D:\pgsql\bin\pg_restore.exe")
DB_NAME = "quantmind_v2"
DB_USER = "xin"
DB_HOST = "localhost"
DB_PORT = "5432"
RETENTION_DAYS = 7
MIN_BACKUP_SIZE_MB = 100  # 正常备份应>100MB(当前数据~2.8GB)


def setup_logging() -> None:
    """配置日志输出。"""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "pg_backup.log", encoding="utf-8"),
        ],
    )


def send_alert(title: str, content: str) -> None:
    """发送钉钉告警(尽力而为，不因告警失败阻塞备份流程)。"""
    try:
        from app.services.notification_service import send_alert as _send
        _send("P0", title, content, category="system")
    except Exception as e:
        logger.warning(f"钉钉告警发送失败(不影响备份): {e}")


def run_backup(dry_run: bool = False) -> Path | None:
    """执行pg_dump备份。

    Args:
        dry_run: 仅打印命令不执行。

    Returns:
        备份文件路径，失败返回None。
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    backup_file = BACKUP_DIR / f"quantmind_v2_{date_str}.dump"

    cmd = [
        str(PG_DUMP),
        "-h", DB_HOST,
        "-p", DB_PORT,
        "-U", DB_USER,
        "-d", DB_NAME,
        "-Fc",              # custom格式(支持pg_restore选择性恢复)
        "-Z", "5",          # 压缩级别5(平衡速度和大小)
        "-f", str(backup_file),
    ]

    logger.info(f"备份命令: {' '.join(cmd)}")

    if dry_run:
        logger.info("[DRY-RUN] 跳过实际执行")
        return None

    env = os.environ.copy()
    env["PGPASSWORD"] = "quantmind"  # 与.env中DATABASE_URL一致

    start = datetime.now()
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        logger.error("pg_dump超时(>10分钟)")
        send_alert("pg_dump备份超时", "pg_dump执行超过10分钟，已终止。请检查数据库状态。")
        return None

    elapsed = (datetime.now() - start).total_seconds()

    if result.returncode != 0:
        logger.error(f"pg_dump失败(exit={result.returncode}): {result.stderr}")
        send_alert("pg_dump备份失败", f"exit={result.returncode}\n```\n{result.stderr[:500]}\n```")
        return None

    # 验证文件大小
    if not backup_file.exists():
        logger.error("备份文件不存在")
        send_alert("pg_dump备份失败", "备份命令执行成功但文件不存在")
        return None

    size_mb = backup_file.stat().st_size / (1024 * 1024)
    logger.info(f"备份完成: {backup_file} ({size_mb:.1f}MB, {elapsed:.0f}秒)")

    if size_mb < MIN_BACKUP_SIZE_MB:
        logger.warning(f"备份文件偏小({size_mb:.1f}MB < {MIN_BACKUP_SIZE_MB}MB)，可能不完整")
        send_alert(
            "pg_dump备份文件偏小",
            f"文件: {backup_file}\n大小: {size_mb:.1f}MB (预期>{MIN_BACKUP_SIZE_MB}MB)\n可能备份不完整。",
        )

    return backup_file


def cleanup_old_backups() -> int:
    """清理超过保留期的旧备份。

    Returns:
        删除的文件数。
    """
    if not BACKUP_DIR.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    deleted = 0

    for f in sorted(BACKUP_DIR.glob("quantmind_v2_*.dump")):
        # 从文件名提取日期
        try:
            date_str = f.stem.split("_")[-1]  # quantmind_v2_20260326 → 20260326
            file_date = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            continue

        if file_date < cutoff:
            f.unlink()
            logger.info(f"已删除旧备份: {f.name}")
            deleted += 1

    return deleted


def verify_backup() -> bool:
    """验证最新备份文件可被pg_restore读取。

    Returns:
        True=验证通过。
    """
    backups = sorted(BACKUP_DIR.glob("quantmind_v2_*.dump"))
    if not backups:
        logger.error("无备份文件可验证")
        return False

    latest = backups[-1]
    logger.info(f"验证备份: {latest}")

    cmd = [
        str(PG_RESTORE),
        "--list",  # 仅列出目录，不实际恢复
        str(latest),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        logger.error("pg_restore --list 超时")
        return False

    if result.returncode != 0:
        logger.error(f"备份验证失败: {result.stderr}")
        return False

    # 统计表数量
    table_count = sum(1 for line in result.stdout.splitlines() if " TABLE " in line)
    logger.info(f"验证通过: {latest.name} 包含 {table_count} 个TABLE条目")

    if table_count < 40:  # 当前46张表，低于40说明有遗漏
        logger.warning(f"TABLE数量偏少({table_count} < 40)，可能有表遗漏")
        return False

    return True


def main() -> None:
    """主入口。"""
    setup_logging()

    parser = argparse.ArgumentParser(description="QuantMind V2 PostgreSQL备份")
    parser.add_argument("--dry-run", action="store_true", help="仅打印命令不执行")
    parser.add_argument("--verify", action="store_true", help="验证最新备份")
    args = parser.parse_args()

    if args.verify:
        ok = verify_backup()
        sys.exit(0 if ok else 1)

    # 1. 执行备份
    logger.info("=" * 60)
    logger.info("开始每日备份")
    backup_file = run_backup(dry_run=args.dry_run)

    if not args.dry_run and backup_file is None:
        logger.error("备份失败，跳过清理")
        sys.exit(1)

    # 2. 清理旧备份
    deleted = cleanup_old_backups()
    if deleted:
        logger.info(f"清理了 {deleted} 个旧备份(保留{RETENTION_DAYS}天)")

    # 3. 列出当前备份
    if BACKUP_DIR.exists():
        backups = sorted(BACKUP_DIR.glob("quantmind_v2_*.dump"))
        logger.info(f"当前备份({len(backups)}个):")
        for f in backups:
            size_mb = f.stat().st_size / (1024 * 1024)
            logger.info(f"  {f.name} ({size_mb:.1f}MB)")

    logger.info("备份流程完成")


if __name__ == "__main__":
    main()
