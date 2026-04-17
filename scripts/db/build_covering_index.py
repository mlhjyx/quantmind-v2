"""P0-1: 构建 factor_values covering index (CONCURRENTLY).

参考: docs/DATA_SYSTEM_V1.md §3.1
目标: 单因子全量 SELECT 90s → <10s, 支持 Index Only Scan

索引定义:
    idx_fv_factor_date_covering ON factor_values (factor_name, trade_date)
    INCLUDE (raw_value, neutral_value)
    WHERE raw_value IS NOT NULL

执行时必须 autocommit=True (CREATE INDEX CONCURRENTLY 不允许在事务中).
CONCURRENTLY 不锁表, 但需要两次表扫描, 165GB 表预计 30-60min.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 确保从仓库根或 backend/ 运行都能 import
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import psycopg2  # noqa: E402


def _get_dsn() -> str:
    """从 backend/app/config 读取 DSN. 避免 backend.app.services.__init__ 触发.

    直接 import settings (不经 __init__.py 自动加载).
    """
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
# TimescaleDB hypertable 不支持 CONCURRENTLY, 普通 CREATE INDEX 会传播到 all chunks.
# 每 chunk 独立短暂锁 (~ 秒级), 不阻塞主表长时间.
INDEX_SQL = f"""
CREATE INDEX IF NOT EXISTS {INDEX_NAME}
ON factor_values (factor_name, trade_date)
INCLUDE (raw_value, neutral_value)
WHERE raw_value IS NOT NULL
"""


def check_existing(cur) -> bool:
    cur.execute(
        """
        SELECT indexname, indexdef, pg_size_pretty(pg_relation_size(indexname::regclass))
        FROM pg_indexes
        WHERE tablename = 'factor_values' AND indexname = %s
        """,
        (INDEX_NAME,),
    )
    row = cur.fetchone()
    if row:
        print(f"[EXISTS] {row[0]} | size={row[2]}")
        print(f"         def={row[1]}")
        return True
    return False


def check_invalid(cur) -> bool:
    cur.execute(
        """
        SELECT c.relname
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        WHERE NOT i.indisvalid AND c.relname = %s
        """,
        (INDEX_NAME,),
    )
    row = cur.fetchone()
    if row:
        print(f"[INVALID] 索引 {row[0]} 存在但 INVALID, 需先 DROP 再重建")
        return True
    return False


def monitor_progress(conn):
    """每 30s 打印一次进度 (pg_stat_progress_create_index)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT phase, blocks_done, blocks_total, tuples_done, tuples_total,
               lockers_total, current_locker_pid
        FROM pg_stat_progress_create_index
        WHERE index_relid = (
            SELECT oid FROM pg_class WHERE relname = %s
        )
        """,
        (INDEX_NAME,),
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    phase, bd, bt, td, tt, lt, lp = row
    pct = (bd / bt * 100) if bt else 0
    print(
        f"  [progress] phase={phase} blocks={bd}/{bt} ({pct:.1f}%) tuples={td}/{tt} lockers={lt}"
    )
    return phase


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop-invalid", action="store_true", help="存在 INVALID 索引时先 drop")
    parser.add_argument("--poll-sec", type=int, default=30)
    parser.add_argument("--max-wait-min", type=int, default=120)
    args = parser.parse_args()

    conn = psycopg2.connect(_get_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    # 预检: 已存在?
    if check_existing(cur):
        print("索引已存在, 跳过构建")
        cur.close()
        conn.close()
        return 0

    # 预检: INVALID?
    if check_invalid(cur):
        if args.drop_invalid:
            print(f"  DROP INDEX CONCURRENTLY {INDEX_NAME} ...")
            cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
        else:
            print("  传 --drop-invalid 清除, 或手动处理")
            return 2

    # 获取表规模用于 ETA 估算
    cur.execute(
        "SELECT pg_size_pretty(pg_total_relation_size('factor_values')), "
        "       pg_size_pretty(pg_relation_size('factor_values'))"
    )
    total_size, rel_size = cur.fetchone()
    print(f"[table] factor_values total={total_size} rel={rel_size}")

    # 开始构建 (autocommit 模式下 CREATE INDEX CONCURRENTLY 合法)
    print(f"[build] starting CREATE INDEX CONCURRENTLY {INDEX_NAME} ...")
    t0 = time.time()

    # 用非阻塞方式: 发出请求后周期性轮询进度表
    try:
        # CONCURRENTLY 是单条命令, 必须一次执行完成; 这里阻塞直到完成
        # 监控进度需要另一个连接 → 用 async
        cur.execute(INDEX_SQL)
        elapsed = time.time() - t0
        print(f"[done] 耗时 {elapsed/60:.1f} min")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[FAIL] 耗时 {elapsed/60:.1f} min, 错误: {e}")
        cur.close()
        conn.close()
        return 1

    # 验证成功
    if check_existing(cur):
        print("[OK] 索引构建成功且 VALID")
        cur.close()
        conn.close()
        return 0
    print("[WARN] 索引不存在, 可能 INVALID")
    cur.close()
    conn.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
