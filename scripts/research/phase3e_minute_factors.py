"""Phase 3E: Microstructure factor computation from 5-min bars.

Computes 20 intraday microstructure factors from minute_bars Parquet cache,
then writes to factor_values table for IC evaluation.

Usage:
    python scripts/research/phase3e_minute_factors.py --compute          # 计算全部20因子
    python scripts/research/phase3e_minute_factors.py --compute --year 2025  # 单年
    python scripts/research/phase3e_minute_factors.py --ic-screen        # IC快筛
    python scripts/research/phase3e_minute_factors.py --spot-check       # 抽样验算

Architecture:
    1. Load year from Parquet cache (minute_data_loader)
    2. GroupBy (code, trade_date) → compute 20 daily raw metrics
    3. Per-stock 20-day rolling mean → factor values
    4. COPY+UPSERT to factor_values (铁律29: NaN→None)
"""

from __future__ import annotations

import argparse
import gc
import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from minute_data_loader import MinuteDataCache  # noqa: E402

# ============================================================
# Factor Definitions
# ============================================================

ROLLING_WINDOW = 20  # 20-day rolling mean for all factors

ALL_FACTORS = [
    # Category A: Intraday Return Distribution
    "intraday_skewness_20",
    "intraday_kurtosis_20",
    "high_freq_volatility_20",
    "updown_vol_ratio_20",
    "max_intraday_drawdown_20",
    # Category B: Volume Microstructure
    "volume_concentration_20",
    "amihud_intraday_20",
    "volume_autocorr_20",
    "smart_money_ratio_20",
    "volume_return_corr_20",
    # Category C: Auction & Session Patterns
    "open_drive_20",
    "close_drive_20",
    "morning_afternoon_ratio_20",
    "lunch_break_gap_20",
    "last_bar_volume_share_20",
    # Category D: Price Efficiency
    "variance_ratio_20",
    "price_path_efficiency_20",
    "autocorr_5min_20",
    "weighted_price_contribution_20",
    "intraday_reversal_strength_20",
]


# ============================================================
# Daily Metric Computation (per stock-day group of 48 bars)
# ============================================================

def compute_daily_metrics(group: pd.DataFrame) -> dict:
    """Compute all 20 daily raw metrics from a single stock-day (48 bars).

    Args:
        group: DataFrame with 48 rows (one 5-min bar each), columns:
               open, high, low, close, volume, amount, minute_of_day

    Returns:
        dict of {factor_name_without_suffix: raw_daily_value}
    """
    o = group["open"].values.astype(np.float64)
    h = group["high"].values.astype(np.float64)
    lo = group["low"].values.astype(np.float64)
    c = group["close"].values.astype(np.float64)
    v = group["volume"].values.astype(np.float64)
    amt = group["amount"].values.astype(np.float64)
    mod = group["minute_of_day"].values  # 0-47

    n = len(c)
    if n < 10:  # 数据不足
        return {f: np.nan for f in _DAILY_KEYS}

    # 5-min returns (close-to-close)
    ret = np.diff(c) / np.where(c[:-1] != 0, c[:-1], np.nan)  # (n-1,)

    # Bar returns (open-to-close for each bar)
    bar_ret = (c - o) / np.where(o != 0, o, np.nan)  # (n,)

    result = {}

    # ---- Category A: Intraday Return Distribution ----

    # A1: skewness of 5-min returns
    valid_ret = ret[np.isfinite(ret)]
    if len(valid_ret) >= 8:
        result["intraday_skewness"] = float(sp_stats.skew(valid_ret, bias=False))
    else:
        result["intraday_skewness"] = np.nan

    # A2: kurtosis of 5-min returns (excess kurtosis)
    if len(valid_ret) >= 8:
        result["intraday_kurtosis"] = float(sp_stats.kurtosis(valid_ret, bias=False))
    else:
        result["intraday_kurtosis"] = np.nan

    # A3: realized volatility (sum of squared returns)
    result["high_freq_volatility"] = float(np.nansum(ret**2))

    # A4: up/down volatility ratio
    up_ret = valid_ret[valid_ret > 0]
    dn_ret = valid_ret[valid_ret < 0]
    if len(up_ret) >= 3 and len(dn_ret) >= 3:
        up_vol = np.std(up_ret, ddof=1)
        dn_vol = np.std(dn_ret, ddof=1)
        result["updown_vol_ratio"] = float(up_vol / dn_vol) if dn_vol > 1e-10 else np.nan
    else:
        result["updown_vol_ratio"] = np.nan

    # A5: max intraday drawdown
    cum_ret = np.cumprod(1 + np.nan_to_num(ret, nan=0.0))
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / np.where(running_max > 0, running_max, 1.0)
    result["max_intraday_drawdown"] = float(np.min(drawdowns)) if len(drawdowns) > 0 else np.nan

    # ---- Category B: Volume Microstructure ----

    total_vol = v.sum()

    # B1: volume concentration (Herfindahl index)
    if total_vol > 0:
        vol_share = v / total_vol
        result["volume_concentration"] = float(np.sum(vol_share**2))
    else:
        result["volume_concentration"] = np.nan

    # B2: intraday Amihud (mean |return| / amount)
    valid_mask = (amt[1:] > 0) & np.isfinite(ret)
    if valid_mask.sum() >= 5:
        amihud_vals = np.abs(ret[valid_mask]) / amt[1:][valid_mask]
        result["amihud_intraday"] = float(np.mean(amihud_vals))
    else:
        result["amihud_intraday"] = np.nan

    # B3: volume lag-1 autocorrelation
    if len(v) >= 10 and np.std(v) > 0:
        result["volume_autocorr"] = float(np.corrcoef(v[:-1], v[1:])[0, 1])
    else:
        result["volume_autocorr"] = np.nan

    # B4: smart money ratio (last 6 bars vol / first 6 bars vol)
    # Last 6 bars = 14:30-15:00 (minute_of_day 42-47)
    # First 6 bars = 09:35-10:05 (minute_of_day 0-5)
    first_vol = v[mod <= 5].sum()
    last_vol = v[mod >= 42].sum()
    if first_vol > 0:
        result["smart_money_ratio"] = float(last_vol / first_vol)
    else:
        result["smart_money_ratio"] = np.nan

    # B5: volume-return correlation
    if len(v) >= 10 and np.std(v) > 0 and np.std(bar_ret[np.isfinite(bar_ret)]) > 0:
        valid_br = np.where(np.isfinite(bar_ret), bar_ret, 0)
        result["volume_return_corr"] = float(np.corrcoef(v, valid_br)[0, 1])
    else:
        result["volume_return_corr"] = np.nan

    # ---- Category C: Auction & Session Patterns ----

    # C1: open drive (first bar return)
    if o[0] > 0:
        result["open_drive"] = float((c[0] - o[0]) / o[0])
    else:
        result["open_drive"] = np.nan

    # C2: close drive (last bar return)
    last_idx = n - 1
    if o[last_idx] > 0:
        result["close_drive"] = float((c[last_idx] - o[last_idx]) / o[last_idx])
    else:
        result["close_drive"] = np.nan

    # C3: morning/afternoon range ratio
    # Morning: minute_of_day 0-23, Afternoon: 24-47
    morn_mask = mod <= 23
    aftn_mask = mod >= 24
    morn_range = h[morn_mask].max() - lo[morn_mask].min() if morn_mask.sum() > 0 else 0
    aftn_range = h[aftn_mask].max() - lo[aftn_mask].min() if aftn_mask.sum() > 0 else 0
    if aftn_range > 1e-10:
        result["morning_afternoon_ratio"] = float(morn_range / aftn_range)
    else:
        result["morning_afternoon_ratio"] = np.nan

    # C4: lunch break gap
    # Morning close = last bar of morning session (minute_of_day=23)
    # Afternoon open = first bar of afternoon session (minute_of_day=24)
    morn_close_bars = c[mod == 23]
    aftn_open_bars = o[mod == 24]
    if len(morn_close_bars) > 0 and len(aftn_open_bars) > 0 and morn_close_bars[0] > 0:
        result["lunch_break_gap"] = float(
            abs(aftn_open_bars[0] - morn_close_bars[0]) / morn_close_bars[0]
        )
    else:
        result["lunch_break_gap"] = np.nan

    # C5: last bar volume share
    if total_vol > 0:
        result["last_bar_volume_share"] = float(v[last_idx] / total_vol)
    else:
        result["last_bar_volume_share"] = np.nan

    # ---- Category D: Price Efficiency ----

    # D1: variance ratio VR(6) = Var(30min) / (6 * Var(5min))
    if len(ret) >= 30:
        # 30-min returns (every 6 bars)
        ret_30 = np.array([
            np.prod(1 + ret[i:i+6]) - 1
            for i in range(0, len(ret) - 5, 6)
        ])
        var_5 = np.nanvar(ret, ddof=1)
        var_30 = np.nanvar(ret_30, ddof=1)
        if var_5 > 1e-15:
            result["variance_ratio"] = float(var_30 / (6 * var_5))
        else:
            result["variance_ratio"] = np.nan
    else:
        result["variance_ratio"] = np.nan

    # D2: price path efficiency
    abs_total_move = abs(c[-1] - o[0])
    sum_abs_bar_ret = np.nansum(np.abs(bar_ret))
    if sum_abs_bar_ret > 1e-10:
        price_level = o[0] if o[0] > 0 else 1.0
        result["price_path_efficiency"] = float(
            (abs_total_move / price_level) / sum_abs_bar_ret
        )
    else:
        result["price_path_efficiency"] = np.nan

    # D3: 5-min return autocorrelation (lag-1)
    if len(valid_ret) >= 10:
        result["autocorr_5min"] = float(np.corrcoef(valid_ret[:-1], valid_ret[1:])[0, 1])
    else:
        result["autocorr_5min"] = np.nan

    # D4: weighted price contribution (corr of volume and |return|)
    if len(v) >= 10 and np.std(v) > 0:
        abs_br = np.abs(np.where(np.isfinite(bar_ret), bar_ret, 0))
        if np.std(abs_br) > 0:
            result["weighted_price_contribution"] = float(np.corrcoef(v, abs_br)[0, 1])
        else:
            result["weighted_price_contribution"] = np.nan
    else:
        result["weighted_price_contribution"] = np.nan

    # D5: intraday reversal strength
    # corr(first-half return, second-half return)
    half = n // 2
    first_half_ret = bar_ret[:half]
    second_half_ret = bar_ret[half:]
    fh_valid = first_half_ret[np.isfinite(first_half_ret)]
    sh_valid = second_half_ret[np.isfinite(second_half_ret)]
    min_len = min(len(fh_valid), len(sh_valid))
    if min_len >= 8:
        result["intraday_reversal_strength"] = float(
            np.corrcoef(fh_valid[:min_len], sh_valid[:min_len])[0, 1]
        )
    else:
        result["intraday_reversal_strength"] = np.nan

    return result


# Keys without the _20 suffix (daily raw values)
_DAILY_KEYS = [f.replace("_20", "") for f in ALL_FACTORS]


# ============================================================
# Year Processing Pipeline
# ============================================================

def process_year(year: int, cache: MinuteDataCache) -> pd.DataFrame:
    """Process one year: load minute bars → compute daily metrics → 20-day rolling.

    Returns:
        DataFrame with columns: code, trade_date, factor_name, raw_value
        Ready for DB insertion.
    """
    print(f"\n{'='*60}")
    print(f"Processing {year}")
    print(f"{'='*60}")

    t0 = time.time()
    df = cache.load_year(year)
    print(f"  Loaded: {len(df):,} rows, {df['code'].nunique()} stocks")

    # ---- Step 1: Compute daily raw metrics ----
    print("  Computing daily metrics...", end="", flush=True)
    t1 = time.time()

    # Group by (code, trade_date), compute metrics
    daily_records = []
    grouped = df.groupby(["code", "trade_date"], sort=False)
    total_groups = len(grouped)

    for i, ((code, td), group) in enumerate(grouped):
        metrics = compute_daily_metrics(group)
        for key, val in metrics.items():
            daily_records.append((code, td, key, val))
        if (i + 1) % 50000 == 0:
            print(f" {i+1}/{total_groups}", end="", flush=True)

    print(f" done ({time.time()-t1:.0f}s)")

    # Free minute data
    del df, grouped
    gc.collect()

    # Build daily DataFrame
    daily_df = pd.DataFrame(daily_records, columns=["code", "trade_date", "factor_key", "value"])
    del daily_records
    print(f"  Daily metrics: {len(daily_df):,} rows")

    # ---- Step 2: 20-day rolling mean per stock per factor ----
    print("  Computing 20-day rolling...", end="", flush=True)
    t2 = time.time()

    parts = []
    for factor_key in _DAILY_KEYS:
        factor_name = factor_key + "_20"
        fdf = daily_df[daily_df["factor_key"] == factor_key].copy()
        fdf = fdf.sort_values(["code", "trade_date"])

        # Rolling mean per stock (vectorized)
        fdf["raw_value"] = (
            fdf.groupby("code")["value"]
            .transform(lambda x: x.rolling(ROLLING_WINDOW, min_periods=10).mean())
        )

        # Drop rows where rolling is NaN (first 9 days)
        valid = fdf.dropna(subset=["raw_value"])
        valid = valid[["code", "trade_date", "raw_value"]].copy()
        valid["factor_name"] = factor_name
        parts.append(valid)

    print(f" done ({time.time()-t2:.0f}s)")
    del daily_df
    gc.collect()

    result_df = pd.concat(parts, ignore_index=True)[["code", "trade_date", "factor_name", "raw_value"]]
    del parts

    elapsed = time.time() - t0
    print(f"  Result: {len(result_df):,} rows, {result_df['factor_name'].nunique()} factors, {elapsed:.0f}s total")

    return result_df


def write_to_db(result_df: pd.DataFrame, conn) -> int:
    """Write factor values to DB using COPY+UPSERT pattern.

    铁律29: NaN → None (SQL NULL), 不写float NaN到DB。
    """
    if result_df.empty:
        return 0

    cur = conn.cursor()

    # 1. Create staging table
    cur.execute("DROP TABLE IF EXISTS _minute_factor_staging")
    cur.execute("""
        CREATE TEMP TABLE _minute_factor_staging (
            code VARCHAR, trade_date DATE, factor_name VARCHAR,
            raw_value DOUBLE PRECISION
        )
    """)

    # 2. COPY data (vectorized, 铁律29: NaN → \N for NULL)
    tmp = result_df.copy()
    # Replace NaN/Inf with None for proper \N handling
    mask = ~np.isfinite(tmp["raw_value"].values)
    tmp.loc[mask, "raw_value"] = None

    buf = io.StringIO()
    for code, td, fname, val in zip(tmp["code"], tmp["trade_date"], tmp["factor_name"], tmp["raw_value"]):
        val_str = "\\N" if val is None or pd.isna(val) else str(val)
        buf.write(f"{code}\t{td}\t{fname}\t{val_str}\n")
    written = len(tmp)
    del tmp

    buf.seek(0)
    cur.copy_from(buf, "_minute_factor_staging",
                  columns=("code", "trade_date", "factor_name", "raw_value"),
                  null="\\N")

    # 3. UPSERT
    cur.execute("""
        INSERT INTO factor_values (code, trade_date, factor_name, raw_value)
        SELECT code, trade_date, factor_name, raw_value FROM _minute_factor_staging
        ON CONFLICT (code, trade_date, factor_name)
        DO UPDATE SET raw_value = EXCLUDED.raw_value
    """)

    conn.commit()
    return written


def spot_check(cache: MinuteDataCache) -> None:
    """Spot-check: manually verify 3 factors for 1 stock on 1 day."""
    df = cache.load_year(2025)

    # Pick a recent day, first stock
    latest_date = sorted(df["trade_date"].unique())[-10]
    codes = sorted(df["code"].unique())
    test_code = codes[0]

    group = df[(df["code"] == test_code) & (df["trade_date"] == latest_date)]
    print(f"\n=== Spot Check: {test_code} on {latest_date} ({len(group)} bars) ===")

    if len(group) == 0:
        print("No data for this combination")
        return

    metrics = compute_daily_metrics(group)

    print("\nDaily raw metrics (before 20-day rolling):")
    for k, v in sorted(metrics.items()):
        print(f"  {k}: {v:.6f}" if np.isfinite(v) else f"  {k}: NaN")

    # Manual verification of a few
    c = group["close"].values.astype(np.float64)
    v = group["volume"].values.astype(np.float64)
    ret = np.diff(c) / c[:-1]

    print("\n--- Manual checks ---")
    print(f"  Bars: {len(group)}")
    print(f"  Returns: {len(ret)} values, mean={np.mean(ret):.6f}, std={np.std(ret):.6f}")
    print(f"  scipy.skew(ret): {sp_stats.skew(ret, bias=False):.6f} vs factor: {metrics.get('intraday_skewness', 'N/A')}")
    print(f"  Realized vol (sum r²): {np.sum(ret**2):.8f} vs factor: {metrics.get('high_freq_volatility', 'N/A')}")
    print(f"  Volume HHI: {np.sum((v/v.sum())**2):.6f} vs factor: {metrics.get('volume_concentration', 'N/A')}")

    del df


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Phase 3E: Microstructure factors")
    parser.add_argument("--compute", action="store_true", help="Compute all 20 factors")
    parser.add_argument("--year", type=int, help="Process single year (default: all available)")
    parser.add_argument("--spot-check", action="store_true", help="Spot-check verification")
    parser.add_argument("--no-db-write", action="store_true", help="Compute but don't write to DB")
    parser.add_argument("--save-parquet", action="store_true", help="Save results as Parquet too")
    args = parser.parse_args()

    cache = MinuteDataCache()
    available = cache.years_available()
    print(f"Available years: {available}")

    if args.spot_check:
        spot_check(cache)
        return

    if args.compute:
        years = [args.year] if args.year else available
        if not years:
            print("No cached minute data. Run minute_data_loader.py --build first.")
            return

        from app.services.db import get_sync_conn

        grand_total = 0
        for year in years:
            result_df = process_year(year, cache)

            if args.save_parquet:
                out_dir = Path("cache/phase3e")
                out_dir.mkdir(parents=True, exist_ok=True)
                result_df.to_parquet(out_dir / f"factors_{year}.parquet", index=False)
                print(f"  Saved Parquet: cache/phase3e/factors_{year}.parquet")

            if not args.no_db_write:
                print("  Writing to DB...", end="", flush=True)
                conn = get_sync_conn()
                try:
                    n = write_to_db(result_df, conn)
                    print(f" {n:,} rows written")
                    grand_total += n
                finally:
                    conn.close()

            del result_df
            gc.collect()

        print(f"\n{'='*60}")
        print(f"DONE: {grand_total:,} total rows written to factor_values")
        print(f"Factors: {len(ALL_FACTORS)}")
        print(f"Years: {years}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
