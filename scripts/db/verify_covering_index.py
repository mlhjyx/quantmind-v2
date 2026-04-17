"""P0-1: 验证 covering index 是否生效 + benchmark.

输出:
  1. 索引元数据 (size, valid, columns)
  2. EXPLAIN (ANALYZE, BUFFERS) 输出 → 检查 "Index Only Scan using idx_fv_factor_date_covering"
  3. 10 轮 timeit → 单因子全量 SELECT 平均耗时

验收目标 (docs/DATA_SYSTEM_V1.md §1.3):
  - 单因子全量 SELECT < 10s
  - Heap Fetches ≈ 0 (说明走 Index Only Scan)
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import psycopg2  # noqa: E402


def _get_dsn() -> str:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_qm_config", REPO_ROOT / "backend" / "app" / "config.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s = mod.settings
    url = s.DATABASE_URL
    for prefix in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    return url

INDEX_NAME = "idx_fv_factor_date_covering"
TEST_SQL = """
SELECT code, trade_date, raw_value, neutral_value
FROM factor_values
WHERE factor_name = %s
  AND raw_value IS NOT NULL
  AND trade_date BETWEEN %s AND %s
"""


def check_index_meta(cur, verbose=True):
    cur.execute(
        """
        SELECT i.indexname, pg_size_pretty(pg_relation_size(i.indexname::regclass)) AS size,
               i.indexdef,
               (SELECT indisvalid FROM pg_index px
                JOIN pg_class c ON c.oid = px.indexrelid
                WHERE c.relname = %s) AS is_valid
        FROM pg_indexes i
        WHERE i.tablename = 'factor_values' AND i.indexname = %s
        """,
        (INDEX_NAME, INDEX_NAME),
    )
    row = cur.fetchone()
    if not row:
        print(f"[FAIL] 索引 {INDEX_NAME} 不存在, 先跑 build_covering_index.py")
        return False
    name, size, indexdef, is_valid = row
    if verbose:
        print(f"[meta] {name} size={size} valid={is_valid}")
        print(f"       {indexdef}")
    return bool(is_valid)


def explain_query(cur, factor_name, start, end):
    print(f"\n[EXPLAIN] factor={factor_name} range={start}..{end}")
    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {TEST_SQL}", (factor_name, start, end))
    plan_lines = [r[0] for r in cur.fetchall()]
    plan_text = "\n".join(plan_lines)
    print(plan_text)

    # 检查是否命中索引
    index_only = f"Index Only Scan using {INDEX_NAME}" in plan_text
    index_scan = f"Index Scan using {INDEX_NAME}" in plan_text
    heap_fetches_zero = "Heap Fetches: 0" in plan_text

    print("\n[diagnose]")
    print(f"  Index Only Scan: {'✅' if index_only else '❌'}")
    print(f"  Index Scan     : {'✅' if index_scan else '  (not used)'}")
    print(f"  Heap Fetches=0 : {'✅' if heap_fetches_zero else '⚠️  non-zero, 可能 visibility map 未更新'}")
    return index_only or index_scan


def benchmark_query(cur, factor_name, start, end, rounds=10):
    print(f"\n[timeit] factor={factor_name} range={start}..{end} rounds={rounds}")
    timings = []
    for i in range(rounds):
        t0 = time.perf_counter()
        cur.execute(TEST_SQL, (factor_name, start, end))
        rows = cur.fetchall()
        dt = time.perf_counter() - t0
        timings.append(dt)
        if i == 0:
            n_rows = len(rows)
    print(f"  rows={n_rows}")
    print(f"  median={statistics.median(timings)*1000:.1f}ms")
    print(f"  mean  ={statistics.mean(timings)*1000:.1f}ms")
    print(f"  min   ={min(timings)*1000:.1f}ms")
    print(f"  max   ={max(timings)*1000:.1f}ms")
    return statistics.median(timings)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor", default="turnover_mean_20")
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--threshold-sec", type=float, default=10.0, help="验收阈值 (秒)")
    args = parser.parse_args()

    conn = psycopg2.connect(_get_dsn())
    cur = conn.cursor()

    # 1. 索引元数据
    if not check_index_meta(cur):
        return 1

    # 2. EXPLAIN
    if not explain_query(cur, args.factor, args.start, args.end):
        print("\n[FAIL] 查询未命中目标索引")
        return 2

    # 3. Benchmark
    median_sec = benchmark_query(cur, args.factor, args.start, args.end, rounds=args.rounds)

    print("\n[verdict]")
    if median_sec < args.threshold_sec:
        print(f"  ✅ 达标: {median_sec:.2f}s < {args.threshold_sec}s 阈值")
        rc = 0
    else:
        print(f"  ⚠️  未达标: {median_sec:.2f}s ≥ {args.threshold_sec}s")
        rc = 3

    cur.close()
    conn.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
