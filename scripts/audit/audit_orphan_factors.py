#!/usr/bin/env python3
"""Audit factor_registry orphan rows (registry 有 / factor_values 无).

Session 27 Task B (2026-04-24): 第一次实战识别出 11 orphan (1 INVALIDATED +
10 PEAD/earnings). 后续周期性审计防 registry / factor_values drift.

用法:
    python scripts/audit/audit_orphan_factors.py                  # 表格输出
    python scripts/audit/audit_orphan_factors.py --json           # JSON 输出 (机器可读)
    python scripts/audit/audit_orphan_factors.py --only-active    # 仅列 status IN (active,warning)
    python scripts/audit/audit_orphan_factors.py --strict         # 有 orphan 时 exit 1 (CI 用)

原理: SELECT DISTINCT factor_name FROM factor_values (fast, uses index) ← set
       minus factor_registry.name → diff = orphan. 单次 query pair, 不走相关子查询.

铁律:
  33-d — 异常 stderr + 退出非零 (audit 用, 可容忍转发到 schtask / CI)
  43   — 本脚本非 schtask 触发, 不强制完整 4 项清单 (ad-hoc / CI)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

# Reviewer P2 (python + database) 采纳: 提 const 对齐项目风格 (pull_moneyflow.py
# STATEMENT_TIMEOUT_MS = 60_000 / fast_ic_recompute 300_000). audit 属"batch 性
# 读扫描"而非每日增量, 300s (5 min) 对齐铁律 43-a batch tier. factor_values
# 839M 行 hypertable 冷 cache 全扫实测 30-60s, 180s→300s 给 CI runner 预热不足
# 的场景额外 safety margin, 绝大多数 warm-cache 实际 <5s 不受影响.
_STATEMENT_TIMEOUT_MS = 300_000

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

import psycopg2  # noqa: E402


def _get_conn() -> psycopg2.extensions.connection:
    """Load DATABASE_URL + return psycopg2 conn with _STATEMENT_TIMEOUT_MS.

    SELECT DISTINCT factor_name 在 factor_values hypertable (839M rows, 151 chunks)
    冷 cache 首次扫 30-60s. 实测 Session 27 连续 audit 第二次因 psql 连接 churn
    evict shared_buffers 可达 >120s. 300s 对 warm 场景 >60x 余量 + CI 冷 cache 兜底.
    """
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(
        url, options=f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}"
    )


def find_orphans(conn, only_active: bool = False) -> list[dict]:
    """Return list of orphan registry rows.

    Orphan = factor_registry.name 不在 SELECT DISTINCT factor_name FROM factor_values.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT factor_name FROM factor_values")
        fv_names = {r[0] for r in cur.fetchall()}

        sql = (
            "SELECT name, status, pool, direction, category, updated_at::date "
            "FROM factor_registry "
        )
        if only_active:
            sql += "WHERE status IN ('active', 'warning') "
        sql += "ORDER BY name"
        # Reviewer P3 (python) 采纳: 删空 params 占位, 此查询无用户参数.
        # only_active 影响 SQL 结构 (可静态拼接), 非参数绑定 → 无注入面.
        cur.execute(sql)
        cols = ["name", "status", "pool", "direction", "category", "updated_at"]
        registry = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    return [r for r in registry if r["name"] not in fv_names]


def _print_table(orphans: list[dict]) -> None:
    """Pretty-print orphan list (table + by-pool summary)."""
    if not orphans:
        print("[audit] 0 orphan — factor_registry / factor_values 全对齐 ✓")
        return
    print(f"[audit] Orphan count: {len(orphans)}\n")
    print(f"  {'name':<44} {'status':<12} {'pool':<14} {'dir':<5} {'category':<15} updated_at")
    print(f"  {'-'*44} {'-'*12} {'-'*14} {'-'*5} {'-'*15} {'-'*10}")
    for r in orphans:
        pool = r["pool"] or "NULL"
        cat = r["category"] or "NULL"
        print(
            f"  {r['name']:<44} {r['status']:<12} {pool:<14} "
            f"{r['direction']!s:<5} {cat:<15} {r['updated_at']}"
        )

    # by-pool summary
    by_pool: dict[str, int] = {}
    for r in orphans:
        by_pool[r["pool"] or "NULL"] = by_pool.get(r["pool"] or "NULL", 0) + 1
    print("\n  by-pool:")
    for pool, count in sorted(by_pool.items()):
        print(f"    {pool:<16} {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument(
        "--only-active",
        action="store_true",
        help="仅列 status IN (active,warning)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="有 orphan 时 exit 1 (CI gate)",
    )
    args = parser.parse_args()

    try:
        conn = _get_conn()
        try:
            orphans = find_orphans(conn, only_active=args.only_active)
        finally:
            conn.close()
    except Exception as e:
        # Reviewer P1 (python) 采纳: 补完整 traceback 对齐 compute_daily_ic/
        # pull_moneyflow main() pattern. CI `--strict` 失败时 ad-hoc 调试
        # 需要 psycopg2 OperationalError 深层嵌套, 仅摘要不够.
        print(f"[audit] FATAL: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "orphan_count": len(orphans),
                    "only_active": args.only_active,
                    "orphans": [
                        {**r, "updated_at": r["updated_at"].isoformat()}
                        for r in orphans
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        _print_table(orphans)

    if args.strict and orphans:
        print(f"\n[audit] STRICT fail: {len(orphans)} orphan(s) present", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
