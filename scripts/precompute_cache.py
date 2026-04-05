"""预计算Parquet缓存 — 消除_load_shared_data的30分钟瓶颈。

生成文件:
  cache/close_pivot.parquet        — 复权价宽表 (1300天 × 5600股票)
  cache/csi300_close.parquet       — CSI300收盘价序列
  cache/fwd_excess_{h}d.parquet    — 超额forward return (h=1,5,10,20,60,120)
  cache/csi_monthly.parquet        — CSI300月收益(regime分类用)
  cache/industry_map.parquet       — 行业映射
  cache/factor_values.parquet      — 全量因子值(研究脚本用)
  cache/daily_basic.parquet        — 基本面(市值/换手率)
  cache/cache_meta.json            — 缓存元数据(时间戳+行数)

用法:
    python scripts/precompute_cache.py           # 全量导出
    python scripts/precompute_cache.py --quick    # 只导出profiler共享数据(快速)
"""

import argparse
import json
import logging
import os
import time
from datetime import date, datetime

import pandas as pd
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = "D:/quantmind-v2/cache"
HORIZONS = [1, 5, 10, 20, 60, 120]
START_DATE = date(2020, 7, 1)  # 给120d warmup留余量
END_DATE = date(2026, 6, 30)  # 支持120d forward return


def get_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )


def export_profiler_shared(conn):
    """导出factor_profiler._load_shared_data需要的全部数据。"""
    meta = {}

    # 1. close_pivot
    logger.info("导出 close_pivot...")
    t0 = time.time()
    close_df = pd.read_sql(
        "SELECT code, trade_date, close * adj_factor as adj_close "
        "FROM klines_daily WHERE trade_date BETWEEN %s AND %s AND volume > 0",
        conn, params=(START_DATE, END_DATE),
    )
    close_pivot = close_df.pivot(
        index="trade_date", columns="code", values="adj_close"
    ).sort_index()
    close_pivot.to_parquet(f"{CACHE_DIR}/close_pivot.parquet")
    meta["close_pivot"] = {"shape": list(close_pivot.shape), "rows": len(close_df)}
    logger.info("  close_pivot: %s (%.1fs)", close_pivot.shape, time.time() - t0)

    # 2. CSI300
    logger.info("导出 CSI300...")
    csi = pd.read_sql(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code='000300.SH' AND trade_date BETWEEN %s AND %s",
        conn, params=(START_DATE, END_DATE),
    )
    csi_close = csi.set_index("trade_date")["close"].sort_index().astype(float)
    csi_close.to_frame().to_parquet(f"{CACHE_DIR}/csi300_close.parquet")

    # 3. Forward excess returns
    logger.info("计算 forward excess returns...")
    for h in HORIZONS:
        t1 = time.time()
        entry = close_pivot.shift(-1)
        exit_p = close_pivot.shift(-h)
        stock_ret = exit_p / entry - 1
        csi_entry = csi_close.shift(-1)
        csi_exit = csi_close.shift(-h)
        idx_ret = csi_exit / csi_entry - 1
        fwd_excess = stock_ret.sub(idx_ret, axis=0)
        fwd_excess.to_parquet(f"{CACHE_DIR}/fwd_excess_{h}d.parquet")
        nonnull = int(fwd_excess.notna().sum().sum())
        meta[f"fwd_excess_{h}d"] = {"shape": list(fwd_excess.shape), "nonnull": nonnull}
        logger.info("  fwd_excess_%dd: %s, %d非空 (%.1fs)", h, fwd_excess.shape, nonnull, time.time() - t1)

    # 4. CSI monthly
    csi_dt = csi_close.copy()
    csi_dt.index = pd.to_datetime(csi_dt.index)
    csi_monthly = csi_dt.resample("ME").last().pct_change().dropna()
    csi_monthly.to_frame("monthly_ret").to_parquet(f"{CACHE_DIR}/csi_monthly.parquet")

    # 5. Industry map
    industry = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market='astock'", conn
    )
    industry.to_parquet(f"{CACHE_DIR}/industry_map.parquet", index=False)
    meta["industry_map"] = {"rows": len(industry)}

    return meta


def export_research_data(conn):
    """导出研究脚本需要的大表。"""
    meta = {}

    # factor_values — 分因子导出避免OOM
    logger.info("导出 factor_values（分因子）...")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")
    factor_names = [r[0] for r in cur.fetchall()]

    all_chunks = []
    for i, fname in enumerate(factor_names):
        df = pd.read_sql(
            "SELECT code, trade_date, factor_name, raw_value, neutral_value "
            "FROM factor_values WHERE factor_name = %s",
            conn, params=(fname,),
        )
        all_chunks.append(df)
        if (i + 1) % 10 == 0:
            logger.info("  %d/%d因子加载完成", i + 1, len(factor_names))

    fv_all = pd.concat(all_chunks, ignore_index=True)
    fv_all.to_parquet(f"{CACHE_DIR}/factor_values.parquet", index=False)
    meta["factor_values"] = {"rows": len(fv_all), "factors": len(factor_names)}
    logger.info("  factor_values: %d行, %d因子", len(fv_all), len(factor_names))

    # daily_basic
    logger.info("导出 daily_basic...")
    db = pd.read_sql(
        "SELECT code, trade_date, close, total_mv, circ_mv, float_share, turnover_rate, pe_ttm "
        "FROM daily_basic WHERE trade_date >= '2020-01-01'",
        conn,
    )
    db.to_parquet(f"{CACHE_DIR}/daily_basic.parquet", index=False)
    meta["daily_basic"] = {"rows": len(db)}
    logger.info("  daily_basic: %d行", len(db))

    return meta


def main():
    parser = argparse.ArgumentParser(description="预计算Parquet缓存")
    parser.add_argument("--quick", action="store_true", help="只导出profiler共享数据")
    args = parser.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    conn = get_conn()

    t_start = time.time()
    meta = {"generated_at": datetime.now().isoformat(), "cache_dir": CACHE_DIR}

    # 始终导出profiler共享数据
    profiler_meta = export_profiler_shared(conn)
    meta.update(profiler_meta)

    if not args.quick:
        research_meta = export_research_data(conn)
        meta.update(research_meta)

    conn.close()

    # 写元数据
    with open(f"{CACHE_DIR}/cache_meta.json", "w") as f:
        json.dump(meta, f, indent=2, default=str)

    total = time.time() - t_start
    logger.info("=== 缓存导出完成: %.1f分钟 ===", total / 60)

    # 列出文件大小
    for fname in sorted(os.listdir(CACHE_DIR)):
        fpath = os.path.join(CACHE_DIR, fname)
        if os.path.isfile(fpath):
            size_mb = os.path.getsize(fpath) / 1e6
            logger.info("  %s: %.1fMB", fname, size_mb)


if __name__ == "__main__":
    main()
