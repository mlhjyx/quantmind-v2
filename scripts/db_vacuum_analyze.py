"""DB VACUUM ANALYZE 维护脚本 — Phase G F-S7-008 P0 修复.

背景 (Subagent I supplement audit):
    pg_stat_user_tables 显示 last_vacuum / last_autovacuum / last_analyze 全部 NULL.
    无 VACUUM ANALYZE 导致:
    - planner 决策基于 stale row count → slow query
    - dead tuple 累积 → 表膨胀 + 索引膨胀
    - factor_values (172 GB / 840M rows) 尤其敏感

设计目标:
    - VACUUM ANALYZE 6 重型表 (factor_values + klines_daily + daily_basic +
      factor_ic_history + position_snapshot + trade_log)
    - 单表运行, 不并发 (避免 lock 累积)
    - VACUUM ANALYZE 不锁表 (vs VACUUM FULL 锁表), 安全可定期跑
    - 日志记录 elapsed time + table size before/after

调度 (推荐 schtask 周日 03:00 SH 自动跑):
    schtasks /Create /TN "QuantMind_VacuumAnalyze" /TR "python D:\\quantmind-v2\\scripts\\db_vacuum_analyze.py" /SC WEEKLY /D SUN /ST 03:00 /F

手动执行:
    python scripts/db_vacuum_analyze.py
    python scripts/db_vacuum_analyze.py --tables factor_values  # 单表

关联:
    - V3_AUDIT_S7_ML_COST_HARDWARE_SUPPLEMENT.md F-S7-008 P0
    - LL-186 audit closure 真值升级 (audit findings → code 真闭环)

红线: 0 broker call (这是 DB 维护脚本, 跟交易隔离).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any

# Ensure backend importable (.pth bootstrap)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2 import sql

# 重型表清单 (按数据量 + 维护优先级排序)
HEAVY_TABLES = [
    "factor_values",  # 840M rows / 172 GB (TimescaleDB hypertable)
    "klines_daily",  # 11.8M rows / 4 GB
    "minute_bars",  # 190M rows / 36 GB
    "daily_basic",  # 11.7M rows / 3.7 GB
    "factor_ic_history",  # 145K rows / 36 MB (IC SSOT)
    "position_snapshot",  # 持仓快照 (write-heavy)
    "trade_log",  # 交易流水 (append-only)
    "stock_valuation",  # 估值
    "moneyflow",  # 资金流向
    "stream_outbox",  # event sourcing outbox (write-heavy)
]


def setup_logging() -> logging.Logger:
    log = logging.getLogger("vacuum_analyze")
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(handler)
    return log


def get_table_size(conn: Any, table: str) -> str:
    """获取表 + 索引总大小 (human-readable)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_size_pretty(pg_total_relation_size(%s::regclass))",
            (table,),
        )
        result = cur.fetchone()
        return result[0] if result else "—"


def get_table_stats(conn: Any, table: str) -> dict[str, Any]:
    """获取 pg_stat_user_tables 关键指标."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                n_live_tup,
                n_dead_tup,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze
            FROM pg_stat_user_tables
            WHERE relname = %s
            """,
            (table,),
        )
        row = cur.fetchone()
        if not row:
            return {}
        return {
            "n_live_tup": row[0],
            "n_dead_tup": row[1],
            "last_vacuum": row[2],
            "last_autovacuum": row[3],
            "last_analyze": row[4],
            "last_autoanalyze": row[5],
        }


def vacuum_analyze_table(conn: Any, table: str, log: logging.Logger) -> dict[str, Any]:
    """对单表执行 VACUUM ANALYZE.

    返回 {table, size_before, size_after, dead_tup_before, dead_tup_after, elapsed_s}.
    """
    log.info(f"开始 VACUUM ANALYZE: {table}")
    size_before = get_table_size(conn, table)
    stats_before = get_table_stats(conn, table)
    log.info(
        f"  before: size={size_before}, live={stats_before.get('n_live_tup')}, "
        f"dead={stats_before.get('n_dead_tup')}, "
        f"last_vacuum={stats_before.get('last_vacuum')}, "
        f"last_analyze={stats_before.get('last_analyze')}"
    )

    start = time.time()
    # VACUUM 不能在 transaction 内运行, 必须 autocommit
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        # 反 SQL injection: 用 sql.Identifier 严格 escape (虽然 table 是固定 list)
        cur.execute(sql.SQL("VACUUM (VERBOSE, ANALYZE) {tbl}").format(tbl=sql.Identifier(table)))

    elapsed = time.time() - start
    size_after = get_table_size(conn, table)
    stats_after = get_table_stats(conn, table)
    log.info(
        f"  after: size={size_after}, live={stats_after.get('n_live_tup')}, "
        f"dead={stats_after.get('n_dead_tup')}, elapsed={elapsed:.1f}s"
    )
    return {
        "table": table,
        "size_before": size_before,
        "size_after": size_after,
        "dead_tup_before": stats_before.get("n_dead_tup"),
        "dead_tup_after": stats_after.get("n_dead_tup"),
        "elapsed_s": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DB VACUUM ANALYZE 维护")
    parser.add_argument(
        "--tables",
        nargs="*",
        default=HEAVY_TABLES,
        help="目标表列表 (默认 HEAVY_TABLES). 可只指定单表 e.g. --tables factor_values",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="PG 连接串 (默认从 DATABASE_URL 环境变量或 backend.app.config 推导)",
    )
    args = parser.parse_args()

    log = setup_logging()

    # P2 fix (security-reviewer Session 57+1 2026-05-19): whitelist validation 反
    # 调用方 inject 任意 table name (e.g. pg_authid system catalog → privilege abuse
    # if DB user 是 superuser). sql.Identifier 防 SQL injection 但不防 semantic abuse.
    _heavy_set = set(HEAVY_TABLES)
    invalid = [t for t in args.tables if t not in _heavy_set]
    if invalid:
        log.error(f"非法表名 (不在 HEAVY_TABLES whitelist): {invalid}. 允许的表: {HEAVY_TABLES}")
        return 1

    # P1 fix (python-reviewer + security-reviewer): 反 credential fallback (铁律 35)
    # + 反 password-in-string DSN. 单一来源: --dsn 参数 OR DATABASE_URL env.
    dsn = args.dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        log.error(
            "DSN 未配置 — 走 --dsn 参数 OR DATABASE_URL env. "
            "反 silent credential fallback (铁律 35)."
        )
        return 1

    log.info(f"目标表: {args.tables}")
    log.info(f"开始 VACUUM ANALYZE 维护周期, 共 {len(args.tables)} 张表")

    # P2 fix (python-reviewer): try/finally conn — 反 outer exception path conn 泄漏.
    conn = psycopg2.connect(dsn)
    try:
        results = []
        failures = []
        overall_start = time.time()

        for table in args.tables:
            try:
                result = vacuum_analyze_table(conn, table, log)
                results.append(result)
            except Exception as exc:
                log.exception(f"VACUUM ANALYZE 失败 {table}: {exc}")
                failures.append({"table": table, "error": str(exc)})
    finally:
        conn.close()

    overall_elapsed = time.time() - overall_start
    log.info(f"\n{'=' * 60}")
    log.info(f"VACUUM ANALYZE 完成 elapsed={overall_elapsed:.1f}s")
    log.info(f"成功: {len(results)} / {len(args.tables)}")
    log.info(f"失败: {len(failures)}")
    for r in results:
        delta = (r["dead_tup_before"] or 0) - (r["dead_tup_after"] or 0)
        log.info(
            f"  {r['table']:30s} {r['elapsed_s']:6.1f}s "
            f"dead_tup {r['dead_tup_before']} → {r['dead_tup_after']} (-{delta})"
        )
    for f in failures:
        log.error(f"  FAILED: {f['table']} → {f['error']}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
