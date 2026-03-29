"""备份完整性验证脚本 — QuantMind V2 (R6 §6.4)

用 pg_restore --list 验证备份可读性，输出:
  - 对象数量（表/索引/序列等分类统计）
  - TABLE 数量（对照43张表基线）
  - 文件大小
  - 验证结论

不执行真正的数据库恢复，仅验证备份文件格式完整性。

用法:
    python scripts/verify_backup.py                    # 验证最新daily备份
    python scripts/verify_backup.py --file PATH        # 验证指定备份文件
    python scripts/verify_backup.py --all              # 验证所有daily备份
    python scripts/verify_backup.py --monthly          # 验证最新monthly备份
"""

import argparse
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PG_BIN = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\16\bin"))
PG_RESTORE = PG_BIN / "pg_restore.exe"

BACKUP_ROOT = PROJECT_ROOT / "backups"
DAILY_DIR = BACKUP_ROOT / "daily"
MONTHLY_DIR = BACKUP_ROOT / "monthly"

# 当前DDL定义43张表，验证阈值设40（允许少量差异）
MIN_EXPECTED_TABLES = 40
# 正常备份应>100MB
MIN_EXPECTED_SIZE_MB = 100.0


def _pg_restore_list(backup_path: Path, timeout: int = 120) -> str | None:
    """运行 pg_restore --list，返回输出文本，失败返回 None。"""
    if not backup_path.exists():
        print(f"[ERROR] 文件不存在: {backup_path}")
        return None

    try:
        result = subprocess.run(
            [str(PG_RESTORE), "--list", str(backup_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"[ERROR] pg_restore --list 超时(>{timeout}秒): {backup_path.name}")
        return None
    except FileNotFoundError:
        print(f"[ERROR] pg_restore 不存在: {PG_RESTORE}")
        print("       请设置环境变量 PG_BIN 指向 PostgreSQL bin 目录")
        return None

    if result.returncode != 0:
        print(f"[ERROR] pg_restore --list 失败(exit={result.returncode}):")
        print(f"        {result.stderr.strip()}")
        return None

    return result.stdout


def _parse_object_types(list_output: str) -> Counter:
    """解析 pg_restore --list 输出，统计对象类型分布。

    pg_restore --list 输出格式示例:
        ; Archive created at 2026-03-28 02:00:00 UTC
        ;     dbname: quantmind_v2
        1234; 2200 16384 TABLE public klines_daily xin
        1235; 2200 16385 TABLE DATA public klines_daily xin
        1236; 2200 16386 INDEX public klines_daily_symbol_id_idx xin
    """
    counts: Counter = Counter()
    for line in list_output.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        # 格式: <oid>; <space_oid> <obj_oid> <TYPE> [SCHEMA] <name> <owner>
        parts = line.split()
        if len(parts) >= 4:
            obj_type = parts[3]
            counts[obj_type] += 1
    return counts


def verify_single(backup_path: Path, verbose: bool = True) -> dict:
    """验证单个备份文件。

    Returns:
        结果字典: {ok: bool, tables: int, total_objects: int, size_mb: float, errors: list[str]}
    """
    errors = []
    result = {
        "file": backup_path.name,
        "ok": False,
        "tables": 0,
        "total_objects": 0,
        "size_mb": 0.0,
        "object_types": {},
        "errors": errors,
    }

    # 文件大小检查
    if not backup_path.exists():
        errors.append(f"文件不存在: {backup_path}")
        return result

    size_bytes = backup_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    result["size_mb"] = round(size_mb, 2)

    if size_mb < MIN_EXPECTED_SIZE_MB:
        errors.append(f"文件过小: {size_mb:.1f}MB < {MIN_EXPECTED_SIZE_MB}MB（可能备份不完整）")

    # pg_restore --list
    list_output = _pg_restore_list(backup_path)
    if list_output is None:
        errors.append("pg_restore --list 失败")
        return result

    counts = _parse_object_types(list_output)
    result["object_types"] = dict(counts)

    # TABLE（不含 TABLE DATA）
    table_count = counts.get("TABLE", 0)
    total_objects = sum(counts.values())
    result["tables"] = table_count
    result["total_objects"] = total_objects

    if table_count < MIN_EXPECTED_TABLES:
        errors.append(f"TABLE数量不足: {table_count} < {MIN_EXPECTED_TABLES}（当前DDL定义43张表）")

    result["ok"] = len(errors) == 0

    if verbose:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"\n[{status}] {backup_path.name}")
        print(f"  文件大小  : {size_mb:.2f} MB")
        print(f"  总对象数  : {total_objects}")
        print(f"  TABLE数量 : {table_count}  (基线 {MIN_EXPECTED_TABLES}+)")

        # 对象类型分布
        if counts:
            print("  对象类型分布:")
            for obj_type, cnt in sorted(counts.items(), key=lambda x: -x[1]):
                print(f"    {obj_type:<25} {cnt:>6}")

        if errors:
            print("  错误:")
            for err in errors:
                print(f"    - {err}")

    return result


def get_latest_backup(backup_dir: Path) -> Path | None:
    """返回目录中最新的备份文件（按文件名日期排序）。"""
    if not backup_dir.exists():
        return None
    backups = sorted(backup_dir.glob("quantmind_v2_*.dump"))
    return backups[-1] if backups else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="QuantMind V2 备份完整性验证 (pg_restore --list)"
    )
    parser.add_argument("--file", type=Path, help="指定备份文件路径")
    parser.add_argument("--all", action="store_true", help="验证所有daily备份")
    parser.add_argument("--monthly", action="store_true", help="验证最新monthly备份")
    parser.add_argument("--quiet", action="store_true", help="仅输出最终结论")
    args = parser.parse_args()

    verbose = not args.quiet
    all_ok = True

    if args.file:
        # 指定文件
        result = verify_single(args.file, verbose=verbose)
        all_ok = result["ok"]

    elif args.all:
        # 所有daily备份
        if not DAILY_DIR.exists():
            print(f"[ERROR] daily备份目录不存在: {DAILY_DIR}")
            return 1
        backups = sorted(DAILY_DIR.glob("quantmind_v2_*.dump"))
        if not backups:
            print("[ERROR] 无daily备份文件")
            return 1
        print(f"验证 {len(backups)} 个daily备份...\n")
        results = []
        for bp in backups:
            r = verify_single(bp, verbose=verbose)
            results.append(r)
            if not r["ok"]:
                all_ok = False
        # 汇总
        passed = sum(1 for r in results if r["ok"])
        print(f"\n{'='*50}")
        print(f"汇总: {passed}/{len(results)} 通过")
        for r in results:
            status = "PASS" if r["ok"] else "FAIL"
            print(f"  [{status}] {r['file']}  {r['size_mb']:.1f}MB  TABLE={r['tables']}")

    elif args.monthly:
        latest = get_latest_backup(MONTHLY_DIR)
        if latest is None:
            print(f"[ERROR] 无monthly备份文件: {MONTHLY_DIR}")
            return 1
        result = verify_single(latest, verbose=verbose)
        all_ok = result["ok"]

    else:
        # 默认：最新daily备份
        latest = get_latest_backup(DAILY_DIR)
        if latest is None:
            print(f"[ERROR] 无daily备份文件: {DAILY_DIR}")
            print(f"       备份目录: {DAILY_DIR}")
            return 1
        result = verify_single(latest, verbose=verbose)
        all_ok = result["ok"]

    print()
    if all_ok:
        print("验证结论: PASS — 备份完整性检查通过")
        return 0
    else:
        print("验证结论: FAIL — 备份存在问题，请检查上方错误信息")
        return 1


if __name__ == "__main__":
    sys.exit(main())
