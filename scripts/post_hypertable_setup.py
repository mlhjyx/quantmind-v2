"""Post-hypertable setup: convert klines_daily, verify performance, launch minute shards.

Run after factor_values hypertable migration completes.

用法:
    python scripts/post_hypertable_setup.py
"""

import logging
import time

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )


def verify_factor_values_hypertable(conn):
    """验证factor_values hypertable。"""
    cur = conn.cursor()
    cur.execute("""
        SELECT hypertable_name, num_chunks
        FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'factor_values'
    """)
    ht = cur.fetchone()
    if not ht:
        logger.error("factor_values不是hypertable!")
        return False

    logger.info("factor_values: %d chunks", ht[1])

    # 查询性能测试
    cur.execute("EXPLAIN ANALYZE SELECT code, raw_value FROM factor_values "
                "WHERE factor_name = 'turnover_mean_20' AND trade_date = '2025-01-15'")
    plan = [r[0] for r in cur.fetchall()]
    for line in plan:
        logger.info("  %s", line)

    # 表大小
    cur.execute("SELECT pg_size_pretty(pg_total_relation_size('factor_values'))")
    logger.info("  Size: %s", cur.fetchone()[0])

    return True


def convert_klines_daily(conn):
    """转换klines_daily为hypertable。"""
    conn.commit()  # 清除任何未提交的事务
    conn.autocommit = True
    cur = conn.cursor()

    # 先删除FK约束
    cur.execute("""
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'klines_daily'::regclass AND contype = 'f'
    """)
    fks = [r[0] for r in cur.fetchall()]
    for fk in fks:
        logger.info("删除FK: %s", fk)
        cur.execute(f"ALTER TABLE klines_daily DROP CONSTRAINT {fk}")

    # 转换
    logger.info("转换klines_daily为hypertable (7M行)...")
    t0 = time.time()
    cur.execute("""
        SELECT create_hypertable('klines_daily', 'trade_date',
            chunk_time_interval => INTERVAL '3 months',
            migrate_data => true,
            if_not_exists => true
        )
    """)
    result = cur.fetchone()
    elapsed = time.time() - t0
    logger.info("klines_daily: %s (%.1fs)", result, elapsed)

    # 验证
    cur.execute("""
        SELECT hypertable_name, num_chunks
        FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'klines_daily'
    """)
    ht = cur.fetchone()
    logger.info("klines_daily: %d chunks", ht[1])

    # 性能测试
    cur.execute("EXPLAIN ANALYZE SELECT code, close, adj_factor FROM klines_daily "
                "WHERE trade_date = '2025-01-15'")
    plan = [r[0] for r in cur.fetchall()]
    for line in plan:
        logger.info("  %s", line)

    return True


def convert_minute_bars(conn):
    """转换minute_bars为hypertable（如果数据量足够）。"""
    conn.commit()
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM minute_bars")
    n = cur.fetchone()[0]
    if n < 1_000_000:
        logger.info("minute_bars只有%d行，暂不转换", n)
        return False

    logger.info("转换minute_bars为hypertable (%d行)...", n)
    t0 = time.time()

    # minute_bars的PK是id(serial)，需要用trade_date做时间维度
    # 先检查是否有trade_date列
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'minute_bars' AND column_name = 'trade_date'
    """)
    if not cur.fetchone():
        logger.warning("minute_bars没有trade_date列，跳过")
        return False

    cur.execute("""
        SELECT create_hypertable('minute_bars', 'trade_date',
            chunk_time_interval => INTERVAL '1 month',
            migrate_data => true,
            if_not_exists => true
        )
    """)
    result = cur.fetchone()
    elapsed = time.time() - t0
    logger.info("minute_bars: %s (%.1fs)", result, elapsed)

    cur.execute("""
        SELECT hypertable_name, num_chunks
        FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'minute_bars'
    """)
    ht = cur.fetchone()
    logger.info("minute_bars: %d chunks", ht[1])
    return True


def main():
    conn = get_conn()

    # Step 1: 验证factor_values
    logger.info("=== Step 1: 验证factor_values hypertable ===")
    if not verify_factor_values_hypertable(conn):
        logger.error("factor_values验证失败，退出")
        return

    # Step 2: 转换klines_daily
    logger.info("=== Step 2: 转换klines_daily ===")
    convert_klines_daily(conn)

    # Step 3: 转换minute_bars
    logger.info("=== Step 3: 转换minute_bars ===")
    convert_minute_bars(conn)

    # Step 4: 汇总
    logger.info("=== 汇总 ===")
    cur = conn.cursor()
    cur.execute("""
        SELECT hypertable_name, num_chunks
        FROM timescaledb_information.hypertables
        ORDER BY hypertable_name
    """)
    for name, chunks in cur.fetchall():
        cur.execute(f"SELECT pg_size_pretty(pg_total_relation_size('{name}'))")
        size = cur.fetchone()[0]
        logger.info("  %s: %d chunks, %s", name, chunks, size)

    conn.close()
    logger.info("=== 完成 ===")


if __name__ == "__main__":
    main()
