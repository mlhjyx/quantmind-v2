"""Step 6-H Part C1: 预处理17因子+target到单个Parquet (float32)。

避免ml_engine.py的LATERAL JOIN OOM:
  - 逐因子从DB加载neutral_value → merge成宽表 (float32)
  - 用pandas shift(-20)计算T+20 excess return (替代LATERAL JOIN)
  - 输出: cache/ml/features_17factor.parquet
  - 峰值内存<2GB

口径对齐: ml_engine.py:760-815
  - stock_return = (close_T20 * adj_T20) / (close_T * adj_T) - 1
  - index_return = close_T20 / close_T - 1 (CSI300 000300.SH)
  - excess_return_20 = ln(1 + stock_return) - ln(1 + index_return)
  - 过滤: volume>0, adj_factor IS NOT NULL, abs(return)<5.0
"""

from __future__ import annotations

import gc
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

PASS_17 = [
    "a158_cord30", "a158_vsump60", "amihud_20", "bp_ratio", "dv_ttm",
    "ep_ratio", "gap_frequency_20", "large_order_ratio", "price_volume_corr_20",
    "relative_volume_20", "reversal_20", "reversal_60", "rsrs_raw_18",
    "turnover_mean_20", "up_days_ratio_20", "volatility_20", "volume_std_20",
]

DATE_START = "2020-07-01"
DATE_END = "2026-03-24"
CACHE_DIR = Path("cache/ml")
OUTPUT = CACHE_DIR / "features_17factor.parquet"


def get_conn():
    return psycopg2.connect(
        host="127.0.0.1", port=5432,
        dbname="quantmind_v2", user="xin", password="quantmind",
    )


def load_factors(conn) -> pd.DataFrame:
    """逐因子加载neutral_value, merge成宽表 (float32)。"""
    all_factors = None
    for i, factor in enumerate(PASS_17):
        t0 = time.time()
        df = pd.read_sql(
            "SELECT code, trade_date, neutral_value "
            "FROM factor_values "
            "WHERE factor_name = %s AND neutral_value IS NOT NULL "
            "AND trade_date BETWEEN %s AND %s",
            conn, params=(factor, DATE_START, DATE_END),
        )
        df = df.rename(columns={"neutral_value": factor})
        df[factor] = df[factor].astype("float32")

        if all_factors is None:
            all_factors = df
        else:
            all_factors = all_factors.merge(df, on=["code", "trade_date"], how="outer")

        mem_mb = all_factors.memory_usage(deep=True).sum() / 1e6
        print(f"  [{i+1}/{len(PASS_17)}] {factor}: {len(df)} rows, "
              f"merged={len(all_factors)} rows, {mem_mb:.0f}MB, {time.time()-t0:.1f}s")
        del df
        gc.collect()

    return all_factors


def compute_target(conn, start_date: str, end_date: str) -> pd.DataFrame:
    """用pandas shift(-20)计算T+20 log excess return，替代LATERAL JOIN。

    口径对齐ml_engine.py:760-815:
      stock_return = (close_T20 * adj_T20) / (close_T * adj_T) - 1
      index_return = close_T20 / close_T - 1
      excess = ln(1+stock) - ln(1+index)
    """
    print("\n[Target] Loading klines_daily...")
    t0 = time.time()

    # 加载stock数据 — 只读需要的列, 扩展date范围以覆盖T+20
    df_stock = pd.read_sql(
        "SELECT code, trade_date, close, adj_factor, volume "
        "FROM klines_daily "
        "WHERE trade_date >= %s AND adj_factor IS NOT NULL AND volume > 0 "
        "ORDER BY code, trade_date",
        conn, params=(start_date,),
    )
    print(f"  Stock data: {len(df_stock)} rows, {time.time()-t0:.1f}s")

    # 计算 adj_price = close * adj_factor
    df_stock["adj_price"] = (df_stock["close"] * df_stock["adj_factor"]).astype("float64")

    # 按stock分组, shift(-20) 得到T+20的adj_price
    df_stock["adj_price_t20"] = df_stock.groupby("code")["adj_price"].shift(-20)

    # stock_return = adj_price_t20 / adj_price - 1
    df_stock["stock_return_20"] = df_stock["adj_price_t20"] / df_stock["adj_price"] - 1

    # 过滤: 只保留目标日期范围内, 且return有效
    df_stock["trade_date"] = pd.to_datetime(df_stock["trade_date"])
    mask = (
        (df_stock["trade_date"] >= pd.Timestamp(start_date))
        & (df_stock["trade_date"] <= pd.Timestamp(end_date))
        & df_stock["stock_return_20"].notna()
        & (df_stock["stock_return_20"].abs() < 5.0)
    )
    df_stock = df_stock.loc[mask, ["code", "trade_date", "stock_return_20"]].copy()
    print(f"  Stock returns: {len(df_stock)} rows")

    # 释放中间数据
    gc.collect()

    # 加载CSI300 index
    print("  Loading index_daily (CSI300)...")
    df_index = pd.read_sql(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code = '000300.SH' AND trade_date >= %s "
        "ORDER BY trade_date",
        conn, params=(start_date,),
    )
    df_index["trade_date"] = pd.to_datetime(df_index["trade_date"])
    df_index["close_t20"] = df_index["close"].shift(-20)
    df_index["index_return_20"] = df_index["close_t20"] / df_index["close"] - 1

    idx_mask = (
        (df_index["trade_date"] >= pd.Timestamp(start_date))
        & (df_index["trade_date"] <= pd.Timestamp(end_date))
        & df_index["index_return_20"].notna()
        & (df_index["index_return_20"].abs() < 5.0)
    )
    df_index = df_index.loc[idx_mask, ["trade_date", "index_return_20"]].copy()
    print(f"  Index returns: {len(df_index)} rows")

    # merge + compute excess
    merged = df_stock.merge(df_index, on="trade_date", how="inner")
    merged["label"] = (
        np.log1p(merged["stock_return_20"]) - np.log1p(merged["index_return_20"])
    ).astype("float32")

    result = merged[["code", "trade_date", "label"]].copy()
    print(f"  Target computed: {len(result)} rows, {time.time()-t0:.1f}s")

    del df_stock, df_index, merged
    gc.collect()
    return result


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Prepare ML Features: 17 PASS factors + T+20 excess return")
    print(f"Date range: {DATE_START} ~ {DATE_END}")
    print("=" * 60)

    conn = get_conn()
    t_start = time.time()

    # Step 1: 加载因子
    print("\n[Step 1] Loading 17 factors (sequential, float32)...")
    factors_df = load_factors(conn)
    print(f"  Factor matrix: {factors_df.shape}")

    # Step 2: 计算target
    print("\n[Step 2] Computing target (T+20 log excess return)...")
    target_df = compute_target(conn, DATE_START, DATE_END)

    conn.close()

    # Step 3: merge + save
    print("\n[Step 3] Merging factors + target...")
    factors_df["trade_date"] = pd.to_datetime(factors_df["trade_date"])
    merged = factors_df.merge(target_df, on=["code", "trade_date"], how="inner")
    merged = merged.dropna(subset=["label"])

    # 确保trade_date是date对象 (ml_engine._load_from_parquet期望)
    merged["trade_date"] = merged["trade_date"].dt.date

    print(f"  Final: {merged.shape}, {merged['code'].nunique()} stocks, "
          f"{merged['trade_date'].nunique()} days")
    print(f"  Memory: {merged.memory_usage(deep=True).sum()/1e6:.0f}MB")

    # 检查列完整性
    missing = [f for f in PASS_17 if f not in merged.columns]
    if missing:
        print(f"  WARNING: missing factors: {missing}")

    merged.to_parquet(OUTPUT, index=False)
    file_size = OUTPUT.stat().st_size / 1e6
    print(f"\n  Saved to {OUTPUT} ({file_size:.0f}MB)")
    print(f"  Total elapsed: {time.time()-t_start:.0f}s")

    del factors_df, target_df, merged
    gc.collect()


if __name__ == "__main__":
    main()
