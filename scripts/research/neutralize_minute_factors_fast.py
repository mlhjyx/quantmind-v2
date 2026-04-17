"""批量中性化10个minute因子 — 优化版: 共享数据只加载一次/年。

原版: 每因子每年独立加载market_cap+industry → 50次重复IO, ~108min
优化: 每年加载一次共享数据, 10因子共享 → 5次IO, ~30min

预处理流程（铁律不可变）: MAD 5σ → WLS中性化(行业+市值) → z-score clip ±3
"""
import gc
import io
import sys
import time

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2] / "backend"))

import numpy as np
import pandas as pd
from engines.factor_engine.preprocess import (
    preprocess_mad,
    preprocess_neutralize,
    preprocess_zscore,
)

from app.services.db import get_sync_conn

FACTORS = [
    'high_freq_volatility_20', 'volume_concentration_20', 'volume_autocorr_20',
    'smart_money_ratio_20', 'opening_volume_share_20', 'closing_trend_strength_20',
    'vwap_deviation_20', 'order_flow_imbalance_20', 'intraday_momentum_20',
    'volume_price_divergence_20',
]


def load_shared_data(conn, start_date: str, end_date: str):
    """加载行业+市值 (每年只需一次)。"""
    cur = conn.cursor()

    # 行业映射
    cur.execute("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'")
    ind_dict = {r[0]: r[1] if r[1] and r[1] != "nan" else "其他" for r in cur.fetchall()}

    # 市值
    cur.execute(
        "SELECT code, trade_date, total_mv FROM daily_basic "
        "WHERE trade_date BETWEEN %s AND %s AND total_mv IS NOT NULL",
        (start_date, end_date),
    )
    mv_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "total_mv"])
    mv_df["total_mv"] = mv_df["total_mv"].astype(float)
    mv_lookup = mv_df.set_index(["code", "trade_date"])["total_mv"]

    return ind_dict, mv_lookup


def neutralize_factor_year(conn, factor_name: str, start_date: str, end_date: str,
                           ind_dict: dict, mv_lookup: pd.Series) -> int:
    """中性化单因子单年, 使用预加载的共享数据。"""
    cur = conn.cursor()

    # 加载 raw_value
    cur.execute(
        "SELECT code, trade_date, raw_value FROM factor_values "
        "WHERE factor_name = %s AND trade_date BETWEEN %s AND %s AND raw_value IS NOT NULL",
        (factor_name, start_date, end_date),
    )
    rows = cur.fetchall()
    if not rows:
        return 0

    df = pd.DataFrame(rows, columns=["code", "trade_date", "raw_value"])
    df["raw_value"] = df["raw_value"].astype(float)

    # 逐日中性化
    results = []
    for date, day_df in df.groupby("trade_date"):
        codes = day_df["code"].values
        vals = day_df["raw_value"].values.astype(float)

        # MAD去极值
        vals_mad = preprocess_mad(pd.Series(vals), n_sigma=5).values

        # 获取行业和市值
        industries = np.array([ind_dict.get(c, "其他") for c in codes])
        ln_mcap = np.array([
            np.log(mv_lookup.get((c, date), np.nan) + 1e-10)
            for c in codes
        ])

        # WLS中性化
        valid_mask = np.isfinite(vals_mad) & np.isfinite(ln_mcap)
        if valid_mask.sum() < 30:
            # 数据不足, 跳过
            for c, v in zip(codes, vals_mad):
                results.append((c, date, factor_name, float(v) if np.isfinite(v) else None))
            continue

        try:
            neutral = preprocess_neutralize(
                pd.Series(vals_mad, index=codes),
                pd.Series(industries, index=codes),
                pd.Series(ln_mcap, index=codes),
            )
            # z-score clip ±3
            zs = preprocess_zscore(neutral)
            for c, v in zip(codes, zs.values):
                results.append((c, date, factor_name, float(v) if np.isfinite(v) else None))
        except Exception:
            for c, v in zip(codes, vals_mad):
                results.append((c, date, factor_name, float(v) if np.isfinite(v) else None))

    if not results:
        return 0

    # 批量UPDATE (COPY+UPSERT pattern)
    cur.execute("DROP TABLE IF EXISTS _neut_staging")
    cur.execute("""
        CREATE TEMP TABLE _neut_staging (
            code VARCHAR, trade_date DATE, factor_name VARCHAR,
            neutral_value DOUBLE PRECISION
        )
    """)

    buf = io.StringIO()
    for c, d, fn, v in results:
        v_str = "\\N" if v is None else str(v)
        buf.write(f"{c}\t{d}\t{fn}\t{v_str}\n")
    buf.seek(0)
    cur.copy_from(buf, "_neut_staging",
                  columns=("code", "trade_date", "factor_name", "neutral_value"),
                  null="\\N")

    cur.execute("""
        UPDATE factor_values fv
        SET neutral_value = s.neutral_value
        FROM _neut_staging s
        WHERE fv.code = s.code AND fv.trade_date = s.trade_date AND fv.factor_name = s.factor_name
    """)
    conn.commit()
    return len(results)


def main():
    conn = get_sync_conn()
    years = [(2021,), (2022,), (2023,), (2024,), (2025,)]
    grand_total = 0
    t_all = time.time()

    for yr_tuple in years:
        yr = yr_tuple[0]
        sd, ed = f"{yr}-01-01", f"{yr}-12-31"

        print(f"\n=== {yr} ===", flush=True)
        t_shared = time.time()
        ind_dict, mv_lookup = load_shared_data(conn, sd, ed)
        print(f"  Shared data: {len(ind_dict)} industries, {len(mv_lookup):,} mv rows ({time.time()-t_shared:.0f}s)", flush=True)

        for i, f in enumerate(FACTORS):
            t0 = time.time()
            n = neutralize_factor_year(conn, f, sd, ed, ind_dict, mv_lookup)
            print(f"  [{i+1}/10] {f}: {n:,} rows ({time.time()-t0:.0f}s)", flush=True)
            grand_total += n

        del mv_lookup
        gc.collect()

    conn.close()
    elapsed = time.time() - t_all
    print(f"\nTotal neutralized: {grand_total:,} rows in {elapsed/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
