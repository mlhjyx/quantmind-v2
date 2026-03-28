"""灾备恢复验证脚本 — QuantMind V2 (R6 §6.4 / §6.5)

验证系统可以在 <2小时内从备份完整恢复。
在测试环境运行，不影响生产DB (quantmind_v2)。

恢复验证流程:
  Step 1: 检查备份文件存在性
  Step 2: 验证备份完整性 (pg_restore --list，≥40 TABLE)
  Step 3: 恢复到测试DB (quantmind_v2_dr_test)，如存在先DROP
  Step 4: 验证关键表存在且有数据
  Step 5: 测试DB连接和基本查询
  Step 6: 清理测试DB
  Step 7: 输出恢复时间和验证报告

用法:
    python scripts/disaster_recovery_verify.py
    python scripts/disaster_recovery_verify.py --dry-run          # 只检查文件，不恢复
    python scripts/disaster_recovery_verify.py --skip-restore     # 跳过pg_restore（CI环境）
    python scripts/disaster_recovery_verify.py --backup-file PATH # 指定备份文件
    python scripts/disaster_recovery_verify.py --target-db NAME   # 指定测试DB名
"""

import argparse
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PG_BIN = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\16\bin"))
PG_RESTORE = PG_BIN / "pg_restore.exe"
PSQL = PG_BIN / "psql.exe"
CREATEDB = PG_BIN / "createdb.exe"
DROPDB = PG_BIN / "dropdb.exe"

BACKUP_ROOT = PROJECT_ROOT / "backups"
DAILY_DIR = BACKUP_ROOT / "daily"
MONTHLY_DIR = BACKUP_ROOT / "monthly"

DB_USER = os.environ.get("PG_USER", "xin")
DB_HOST = os.environ.get("PG_HOST", "localhost")
DB_PORT = os.environ.get("PG_PORT", "5432")

DEFAULT_TARGET_DB = "quantmind_v2_dr_test"
MIN_EXPECTED_TABLES = 40

# 关键表行数下限（宽松阈值，满足任何有数据的生产DB）
KEY_TABLE_CHECKS = {
    "klines_daily": 1_000_000,
    "factor_values": 1_000_000,
    "symbols": 3_000,
    "factor_registry": 5,
}


# ── 工具函数 ──────────────────────────────────────────────


def _pg_env() -> dict:
    """构造含PGPASSWORD的环境变量，从.env文件读取。"""
    env = os.environ.copy()
    if "PGPASSWORD" not in env:
        env_file = PROJECT_ROOT / "backend" / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "://" in line and "@" in line and ("DATABASE_URL" in line or "PGPASSWORD" in line):
                    try:
                        creds = line.split("://")[1].split("@")[0]
                        if ":" in creds:
                            env["PGPASSWORD"] = creds.split(":")[1]
                    except Exception:
                        pass
                elif line.startswith("PGPASSWORD="):
                    env["PGPASSWORD"] = line.split("=", 1)[1].strip()
    return env


def _pg_args() -> list[str]:
    return ["-h", DB_HOST, "-p", DB_PORT, "-U", DB_USER]


def _fmt_elapsed(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes > 0:
        return f"{minutes}分{secs:02d}秒"
    return f"{secs}秒"


def _print_separator() -> None:
    print("=" * 51)


# ── Step 1: 查找备份文件 ──────────────────────────────────


def find_backup_file(backup_file_arg: Path | None) -> Path | None:
    """查找要验证的备份文件。"""
    if backup_file_arg is not None:
        if not backup_file_arg.exists():
            print(f"[ERROR] 指定备份文件不存在: {backup_file_arg}")
            return None
        return backup_file_arg

    # 优先 daily，其次 monthly
    for search_dir in (DAILY_DIR, MONTHLY_DIR):
        if search_dir.exists():
            backups = sorted(search_dir.glob("quantmind_v2_*.dump"))
            if backups:
                return backups[-1]

    print(f"[ERROR] 未找到备份文件，搜索路径: {DAILY_DIR}, {MONTHLY_DIR}")
    return None


# ── Step 2: 验证备份完整性 ────────────────────────────────


def verify_backup_integrity(backup_path: Path) -> tuple[bool, dict]:
    """运行 pg_restore --list 验证备份格式完整性。

    Returns:
        (ok, info) — info含 tables/indexes/total_objects/size_mb
    """
    info: dict = {"tables": 0, "indexes": 0, "total_objects": 0, "size_mb": 0.0, "errors": []}

    size_bytes = backup_path.stat().st_size
    info["size_mb"] = round(size_bytes / (1024 * 1024), 1)

    if not PG_RESTORE.exists():
        info["errors"].append(f"pg_restore不存在: {PG_RESTORE}  设置PG_BIN环境变量")
        return False, info

    try:
        result = subprocess.run(
            [str(PG_RESTORE), "--list", str(backup_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        info["errors"].append("pg_restore --list 超时(>120秒)")
        return False, info

    if result.returncode != 0:
        info["errors"].append(f"pg_restore --list 失败(exit={result.returncode}): {result.stderr.strip()[:200]}")
        return False, info

    counts: Counter = Counter()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        parts = line.split()
        if len(parts) >= 4:
            counts[parts[3]] += 1

    info["tables"] = counts.get("TABLE", 0)
    info["indexes"] = counts.get("INDEX", 0)
    info["total_objects"] = sum(counts.values())
    info["object_types"] = dict(counts)

    if info["tables"] < MIN_EXPECTED_TABLES:
        info["errors"].append(
            f"TABLE数量不足: {info['tables']} < {MIN_EXPECTED_TABLES} (DDL定义43张表)"
        )

    return len(info["errors"]) == 0, info


# ── Step 3: 恢复到测试DB ──────────────────────────────────


def drop_test_db(target_db: str) -> None:
    """如果测试DB存在，先DROP。"""
    env = _pg_env()
    subprocess.run(
        [str(DROPDB)] + _pg_args() + ["--if-exists", target_db],
        env=env,
        capture_output=True,
        text=True,
    )


def restore_to_test_db(backup_path: Path, target_db: str) -> tuple[bool, float]:
    """pg_restore 恢复到测试DB。

    Returns:
        (ok, elapsed_seconds)
    """
    env = _pg_env()

    # 先DROP再CREATE
    drop_test_db(target_db)

    create_result = subprocess.run(
        [str(CREATEDB)] + _pg_args() + [target_db],
        env=env,
        capture_output=True,
        text=True,
    )
    if create_result.returncode != 0:
        print(f"  [ERROR] 创建测试DB失败: {create_result.stderr.strip()[:200]}")
        return False, 0.0

    start = time.monotonic()
    restore_result = subprocess.run(
        [str(PG_RESTORE)]
        + _pg_args()
        + [
            "-d", target_db,
            "--no-owner",
            "--no-privileges",
            "--clean",
            "--if-exists",
            str(backup_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=7200,  # 2小时上限（RTO目标）
    )
    elapsed = time.monotonic() - start

    # pg_restore在有WARNING时也返回非0，区分warning和fatal error
    if restore_result.returncode not in (0, 1):
        print(f"  [ERROR] pg_restore 失败(exit={restore_result.returncode}):")
        print(f"          {restore_result.stderr.strip()[:300]}")
        return False, elapsed

    return True, elapsed


# ── Step 4+5: 验证关键表 ──────────────────────────────────


def verify_restored_tables(target_db: str) -> tuple[bool, dict[str, int]]:
    """连接测试DB，验证关键表行数。

    Returns:
        (all_ok, {table_name: row_count})
    """
    env = _pg_env()
    row_counts: dict[str, int] = {}
    all_ok = True

    for table, min_rows in KEY_TABLE_CHECKS.items():
        sql = f"SELECT COUNT(*) FROM {table};"
        result = subprocess.run(
            [str(PSQL)] + _pg_args() + ["-d", target_db, "-t", "-c", sql],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  [ERROR] 查询 {table} 失败: {result.stderr.strip()[:150]}")
            row_counts[table] = -1
            all_ok = False
            continue

        try:
            count = int(result.stdout.strip())
        except ValueError:
            row_counts[table] = -1
            all_ok = False
            continue

        row_counts[table] = count
        if count < min_rows:
            all_ok = False

    return all_ok, row_counts


# ── Step 6: 清理测试DB ────────────────────────────────────


def cleanup_test_db(target_db: str) -> None:
    """DROP测试DB。"""
    drop_test_db(target_db)


# ── 主验证流程 ────────────────────────────────────────────


def run_verification(
    backup_file_arg: Path | None,
    target_db: str,
    dry_run: bool,
    skip_restore: bool,
) -> int:
    """执行完整灾备恢复验证，返回exit code (0=通过, 1=失败)。"""
    overall_start = time.monotonic()
    print()
    print("[DR-VERIFY] 灾备恢复验证报告")
    _print_separator()

    # Step 1: 查找备份文件
    backup_path = find_backup_file(backup_file_arg)
    if backup_path is None:
        print("整体状态: FAIL — 无备份文件")
        return 1

    print(f"备份文件: {backup_path}")
    print(f"文件大小: {backup_path.stat().st_size / (1024 * 1024):.1f} MB")

    if dry_run:
        print()
        print("[DRY-RUN] 仅检查备份文件存在性，跳过完整性验证和恢复")
        print("整体状态: DRY-RUN — 备份文件存在，跳过实际验证")
        return 0

    # Step 2: 验证备份完整性
    integrity_ok, integrity_info = verify_backup_integrity(backup_path)
    index_count = integrity_info.get("indexes", 0)
    table_label = f"{integrity_info['tables']} TABLE, {index_count} INDEX"
    if integrity_ok:
        print(f"备份完整性: PASS ({table_label})")
    else:
        err = "; ".join(integrity_info["errors"])
        print(f"备份完整性: FAIL — {err}")
        print("整体状态: FAIL — 备份完整性检查未通过，中止恢复验证")
        return 1

    restore_elapsed = 0.0
    tables_ok = False  # default; set inside else branch if skip_restore=False

    if skip_restore:
        print("恢复耗时: 跳过 (--skip-restore)")
        print("关键表验证: 跳过 (--skip-restore)")
    else:
        # Step 3: 恢复到测试DB
        print(f"恢复目标DB: {target_db}")
        print("正在恢复... (大库可能需要10-30分钟)")
        restore_ok, restore_elapsed = restore_to_test_db(backup_path, target_db)
        elapsed_str = _fmt_elapsed(restore_elapsed)

        if not restore_ok:
            print(f"恢复耗时: {elapsed_str}")
            cleanup_test_db(target_db)
            print("整体状态: FAIL — pg_restore 恢复失败")
            return 1

        print(f"恢复耗时: {elapsed_str}")

        # Step 4+5: 验证关键表
        tables_ok, row_counts = verify_restored_tables(target_db)
        print("关键表验证:")
        for table, min_rows in KEY_TABLE_CHECKS.items():
            count = row_counts.get(table, -1)
            if count < 0:
                status = "FAIL (查询失败)"
            elif count >= min_rows:
                status = f"PASS {count:,} 行"
            else:
                status = f"FAIL {count:,} 行 (预期>={min_rows:,})"
            print(f"  {table}: {status}")

        # Step 6: 清理测试DB
        cleanup_test_db(target_db)

    # Step 7: 汇总报告
    overall_elapsed = time.monotonic() - overall_start
    print()
    _print_separator()

    if skip_restore:
        overall_ok = integrity_ok
        status_msg = "备份完整性通过，恢复验证已跳过 (--skip-restore)"
    else:
        overall_ok = integrity_ok and tables_ok
        status_msg = "灾备恢复验证通过" if overall_ok else "关键表行数未达标"

    status_icon = "PASS" if overall_ok else "FAIL"
    print(f"整体状态: {status_icon} — {status_msg}")

    if restore_elapsed > 0:
        # 预计含服务重启的总恢复时间 = restore_elapsed + 5分钟手工操作
        estimated_rto_min = int(restore_elapsed / 60) + 5
        print(f"预计恢复时间: ~{estimated_rto_min}分钟 (含服务重启)")

    print(f"验证总耗时: {_fmt_elapsed(overall_elapsed)}")
    print(f"验证时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return 0 if overall_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QuantMind V2 灾备恢复验证 (R6 §6.4)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查备份文件是否存在，不执行完整性验证或恢复",
    )
    parser.add_argument(
        "--skip-restore",
        action="store_true",
        help="跳过实际pg_restore（用于CI环境，只验证备份完整性）",
    )
    parser.add_argument(
        "--backup-file",
        type=Path,
        default=None,
        help="指定备份文件路径，默认使用最新daily备份",
    )
    parser.add_argument(
        "--target-db",
        default=DEFAULT_TARGET_DB,
        help=f"测试DB名（默认: {DEFAULT_TARGET_DB}）",
    )
    args = parser.parse_args()

    exit_code = run_verification(
        backup_file_arg=args.backup_file,
        target_db=args.target_db,
        dry_run=args.dry_run,
        skip_restore=args.skip_restore,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
