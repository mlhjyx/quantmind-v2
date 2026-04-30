#!/usr/bin/env python3
"""F-D3A-1 验证: alembic + raw migrations 同步检查 (read-only).

用途:
    检查 backend/migrations/*.sql 标准 + alembic versions 应用状态, 验证 D3-A
    Step 1 spike F-D3A-1 P0 阻塞 (alert_dedup / platform_metrics /
    strategy_evaluations 3 missing migrations) 是否仍 missing.

trigger 条件 (event-driven):
    - 任何 backend/migrations/*.sql 加 / apply 后立刻跑
    - 批 2 P0 修 PR (apply 3 missing migrations) merged 后立刻跑
    - PT 重启 gate prerequisite check 时跑

退出码语义:
    0 = 全部 expected migrations 已 applied (DB 表存在)
    1 = 1+ migrations missing (DB 表不存在), F-D3A-1 仍 P0 阻塞
    2 = 脚本自身错 (DB 连接 / 配置)

禁止:
    - 任何 mutating SQL (DELETE/UPDATE/INSERT/TRUNCATE/CREATE/ALTER/DROP)
    - alembic upgrade / downgrade
    - 改 backend/migrations/ 文件
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 期望存在的表 (D3-A Step 1 F-D3A-1 P0 阻塞清单)
EXPECTED_TABLES = [
    "alert_dedup",
    "platform_metrics",
    "strategy_evaluations",
]

# 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _connect_db():
    """sync psycopg2, read-only (autocommit=False, 不 commit)."""
    import psycopg2

    pwd = os.environ.get("PGPASSWORD") or "quantmind"
    return psycopg2.connect(
        host="localhost",
        user="xin",
        password=pwd,
        dbname="quantmind_v2",
    )


def _check_table_exists(cur, table_name: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        (table_name,),
    )
    return bool(cur.fetchone()[0])


def _list_migration_files() -> list[Path]:
    migrations_dir = PROJECT_ROOT / "backend" / "migrations"
    if not migrations_dir.exists():
        return []
    return sorted(
        f
        for f in migrations_dir.glob("*.sql")
        if not f.name.endswith("_rollback.sql")
    )


def main() -> int:
    print("=" * 80)
    print("  check_alembic_sync — F-D3A-1 missing migrations verifier")
    print("=" * 80)

    # 1. 列 backend/migrations/*.sql files
    migration_files = _list_migration_files()
    print(f"\n  backend/migrations/ files: {len(migration_files)}")
    for f in migration_files:
        print(f"    {f.relative_to(PROJECT_ROOT)}")

    # 2. 连 DB + 检查 expected tables
    try:
        conn = _connect_db()
        cur = conn.cursor()
    except Exception as e:
        print(f"\n❌ DB connect failed: {e}", file=sys.stderr)
        return 2

    print("\n  Expected tables (F-D3A-1 P0 阻塞清单):")
    print(f"  {'Table':30} {'Status':10}")
    print("  " + "-" * 40)

    missing = []
    for table in EXPECTED_TABLES:
        exists = _check_table_exists(cur, table)
        status = "✅ EXISTS" if exists else "❌ MISSING"
        print(f"  {table:30} {status:10}")
        if not exists:
            missing.append(table)

    cur.close()
    conn.close()

    print("\n" + "=" * 80)
    if missing:
        print(f"  ❌ FAIL — {len(missing)} table(s) missing: {', '.join(missing)}")
        print("     F-D3A-1 P0 阻塞**仍未修**, PT 重启 gate 阻塞.")
        print("     修法: 批 2 P0 修 PR apply 3 missing migrations.")
        print("=" * 80)
        return 1

    print(f"  ✅ PASS — 全部 {len(EXPECTED_TABLES)} expected tables 已 applied.")
    print("     F-D3A-1 P0 阻塞已修.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback

        print(f"\n❌ FATAL: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(2)
