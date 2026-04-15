#!/usr/bin/env python3
"""Phase 3B Task 2: Factor Characteristics Analysis.

Subtasks:
  2.1a: Fundamental change factors (QoQ delta) → IC
  2.1b: Industry-relative ranking → IC
  2.1c: Fundamental pre-filter backtests (4 configs)
  2.1d: Fundamental negative screening (3 configs)
  2.2:  IC decay curves for 32 significant factors (6 horizons)
  2.3:  Factor usage recommendation table

Usage:
  python scripts/research/phase3b_factor_characteristics.py --all
  python scripts/research/phase3b_factor_characteristics.py --task 2.1a
  python scripts/research/phase3b_factor_characteristics.py --task 2.2
"""

import argparse
import gc
import io
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats as sp_stats

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent.parent / "backend"
CACHE_DIR = SCRIPT_DIR.parent.parent / "cache"
PHASE3B_CACHE = CACHE_DIR / "phase3b"

sys.path.insert(0, str(BACKEND_DIR))

DB_CONN = "dbname=quantmind_v2 user=xin password=quantmind host=localhost"

# CORE4 active factors
CORE4_FACTORS = ["turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm"]
CORE4_DIRECTIONS = {"turnover_mean_20": -1, "volatility_20": -1, "bp_ratio": 1, "dv_ttm": 1}

# 32 significant factors from IC quick-screen
SIGNIFICANT_FACTORS = [
    "high_low_range_20", "volatility_60", "turnover_std_20", "maxret_20",
    "CORD5", "turnover_f", "ivol_20", "gap_frequency_20",
    "atr_norm_20", "turnover_stability_20", "large_order_ratio", "RSQR30",
    "IMIN10", "HIGH0", "price_level_factor", "high_vol_price_ratio_20",
    "CORD20", "kbar_kup", "sp_ttm", "momentum_20",
    "gain_loss_ratio_20", "price_volume_corr_20", "reversal_60", "relative_volume_20",
    "rsrs_raw_18", "mf_divergence", "volume_std_20", "reversal_10",
    "momentum_10", "momentum_5", "reversal_5", "turnover_surge_ratio",
]

# Fundamental factors (level)
FUNDAMENTAL_FACTORS = [
    "roe_dt_q", "roa_q", "gross_margin_q", "net_margin_q",
    "profit_growth_q", "leverage_q",
]

# Change factor definitions
CHANGE_FACTOR_DEFS = {
    "roe_change_q": "roe_dt_q",
    "roa_change_q": "roa_q",
    "margin_change_q": "gross_margin_q",
    "leverage_change_q": "leverage_q",
    "profit_accel_q": "profit_growth_q",
}

# Industry-relative factor definitions
IND_RANK_DEFS = {
    "roe_ind_rank": "roe_dt_q",
    "roa_ind_rank": "roa_q",
    "margin_ind_rank": "gross_margin_q",
    "leverage_ind_rank": "leverage_q",
}

OOS_START = date(2020, 1, 1)
OOS_END = date(2026, 4, 1)


# ─── Utilities ──────────────────────────────────────────────


def get_conn():
    return psycopg2.connect(DB_CONN)


def save_result(result, name: str):
    """Save result to cache/phase3b/{name}.json."""
    def default_ser(obj):
        if isinstance(obj, (date, pd.Timestamp)):
            return str(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Series):
            return obj.to_dict()
        raise TypeError(f"Not serializable: {type(obj)}")

    PHASE3B_CACHE.mkdir(parents=True, exist_ok=True)
    fp = PHASE3B_CACHE / f"{name}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=default_ser)
    print(f"  Saved: {fp}")


def load_price_data(start_year=2020, end_year=2026):
    """Load price + benchmark from Parquet cache."""
    price_parts, bench_parts = [], []
    for y in range(start_year, end_year + 1):
        pf = CACHE_DIR / "backtest" / str(y) / "price_data.parquet"
        bf = CACHE_DIR / "backtest" / str(y) / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))
    price = pd.concat(price_parts, ignore_index=True)
    bench = pd.concat(bench_parts, ignore_index=True)
    price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.date
    bench["trade_date"] = pd.to_datetime(bench["trade_date"]).dt.date
    bench = bench.sort_values("trade_date").drop_duplicates("trade_date")
    print(f"  Price: {len(price):,} rows, Benchmark: {len(bench):,} rows")
    return price, bench


def load_core4_factors(start_year=2020, end_year=2026):
    """Load CORE4 factors from Parquet cache."""
    parts = []
    for y in range(start_year, end_year + 1):
        fp = CACHE_DIR / "backtest" / str(y) / "factor_data.parquet"
        if fp.exists():
            df = pd.read_parquet(fp)
            df = df[df["factor_name"].isin(CORE4_FACTORS)]
            parts.append(df)
    factor_df = pd.concat(parts, ignore_index=True)
    factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"]).dt.date
    print(f"  CORE4 factors: {len(factor_df):,} rows")
    return factor_df


def compute_metrics(nav: pd.Series) -> dict:
    """Sharpe/MDD/annual return."""
    from engines.metrics import TRADING_DAYS_PER_YEAR, calc_max_drawdown, calc_sharpe
    returns = nav.pct_change().dropna()
    n_days = len(nav)
    total_ret = nav.iloc[-1] / nav.iloc[0] - 1.0
    ann_ret = (1 + total_ret) ** (TRADING_DAYS_PER_YEAR / max(n_days, 1)) - 1.0
    return {
        "sharpe": round(float(calc_sharpe(returns)), 4),
        "mdd": round(float(calc_max_drawdown(nav)), 4),
        "annual_return": round(float(ann_ret), 4),
        "total_return": round(float(total_ret), 4),
        "n_days": n_days,
    }


def get_monthly_rebal_dates(trade_dates) -> list:
    """Monthly last trading day."""
    df = pd.DataFrame({"td": sorted(set(trade_dates))})
    df["ym"] = df["td"].apply(lambda d: (d.year, d.month))
    return df.groupby("ym")["td"].max().sort_values().tolist()


def write_copy_upsert(conn, codes, dates, factor_name, values) -> int:
    """COPY+UPSERT batch write to factor_values."""
    if len(codes) == 0:
        return 0
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS _p3b_staging")
    cur.execute("""CREATE TEMP TABLE _p3b_staging (
        code VARCHAR, trade_date DATE, factor_name VARCHAR, raw_value DOUBLE PRECISION
    )""")
    buf = io.StringIO()
    written = 0
    for c, d, v in zip(codes, dates, values, strict=False):
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            continue
        buf.write(f"{c}\t{d}\t{factor_name}\t{v}\n")
        written += 1
    buf.seek(0)
    if written == 0:
        return 0
    cur.copy_from(buf, "_p3b_staging", columns=("code", "trade_date", "factor_name", "raw_value"))
    cur.execute("""
        INSERT INTO factor_values (code, trade_date, factor_name, raw_value)
        SELECT code, trade_date, factor_name, raw_value FROM _p3b_staging
        ON CONFLICT (code, trade_date, factor_name)
        DO UPDATE SET raw_value = EXCLUDED.raw_value
    """)
    conn.commit()
    return written


def compute_ic_for_factor(factor_df, fwd_df) -> dict:
    """Compute Spearman IC for a single factor vs forward returns.

    factor_df: code, trade_date, raw_value
    fwd_df: trade_date x code (pivot of forward excess returns)
    """
    ic_list = []
    for td, grp in factor_df.groupby("trade_date"):
        if len(grp) < 30:
            continue
        if td not in fwd_df.index:
            continue
        fwd_row = fwd_df.loc[td].dropna()
        common = grp.set_index("code")["raw_value"].dropna()
        common = common[common.index.isin(fwd_row.index)]
        fwd_common = fwd_row[common.index]
        if len(common) < 30:
            continue
        result = sp_stats.spearmanr(common.values, fwd_common.values)
        stat = result.statistic if hasattr(result, 'statistic') else result[0]
        arr = np.asarray(stat)
        if arr.ndim == 2:
            ic = float(arr[0, 1])  # off-diagonal = cross-correlation
        elif arr.ndim == 0:
            ic = float(arr)
        else:
            ic = float(arr.flat[0])
        if not np.isnan(ic):
            ic_list.append(ic)

    if len(ic_list) < 5:
        return {"ic_mean": np.nan, "ic_std": np.nan, "ic_ir": np.nan, "t_stat": np.nan, "n_dates": len(ic_list)}

    arr = np.array(ic_list)
    ic_mean = arr.mean()
    ic_std = arr.std()
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(arr))) if ic_std > 0 else 0
    return {
        "ic_mean": round(float(ic_mean), 6),
        "ic_std": round(float(ic_std), 6),
        "ic_ir": round(float(ic_ir), 4),
        "t_stat": round(float(t_stat), 4),
        "n_dates": len(ic_list),
    }


def load_forward_returns_pivot(conn, start_date, end_date, horizon=20):
    """Load forward excess returns as pivot (trade_date x code).

    Uses Parquet cache first (1000x faster), falls back to DB.
    """
    print(f"  Loading {horizon}d forward returns (Parquet cache)...")
    start_year = start_date.year if isinstance(start_date, date) else int(str(start_date)[:4])
    end_year = end_date.year if isinstance(end_date, date) else int(str(end_date)[:4])

    # Try Parquet cache first
    price_parts, bench_parts = [], []
    for y in range(start_year, end_year + 1):
        pf = CACHE_DIR / "backtest" / str(y) / "price_data.parquet"
        bf = CACHE_DIR / "backtest" / str(y) / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))

    if price_parts and bench_parts:
        price = pd.concat(price_parts, ignore_index=True)
        bench = pd.concat(bench_parts, ignore_index=True)
        price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.date
        bench["trade_date"] = pd.to_datetime(bench["trade_date"]).dt.date
        # Filter date range
        sd = start_date if isinstance(start_date, date) else date.fromisoformat(str(start_date))
        ed = end_date if isinstance(end_date, date) else date.fromisoformat(str(end_date))
        price = price[(price["trade_date"] >= sd) & (price["trade_date"] <= ed)]
        bench = bench[(bench["trade_date"] >= sd) & (bench["trade_date"] <= ed)]
        bench = bench.sort_values("trade_date").drop_duplicates("trade_date")
        bench_close = bench.set_index("trade_date")["close"]
        print(f"  Loaded from Parquet: {len(price):,} price rows")
    else:
        # Fallback to DB
        print("  Parquet cache not found, loading from DB...")
        price = pd.read_sql("""
            SELECT code, trade_date, close FROM klines_daily
            WHERE trade_date >= %s AND trade_date <= %s AND volume > 0
            ORDER BY code, trade_date
        """, conn, params=(start_date, end_date))
        price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.date
        bench = pd.read_sql("""
            SELECT trade_date, close FROM index_daily
            WHERE index_code = '000300.SH' AND trade_date >= %s AND trade_date <= %s
            ORDER BY trade_date
        """, conn, params=(start_date, end_date))
        bench["trade_date"] = pd.to_datetime(bench["trade_date"]).dt.date
        bench_close = bench.set_index("trade_date")["close"]

    pivot = price.pivot(index="trade_date", columns="code", values="close")
    fwd_ret = pivot.shift(-horizon) / pivot - 1
    bench_fwd = bench_close.shift(-horizon) / bench_close - 1
    fwd_excess = fwd_ret.sub(bench_fwd, axis=0)
    print(f"  Forward returns: {fwd_excess.shape[0]} dates x {fwd_excess.shape[1]} stocks")
    return fwd_excess


# ═══════════════════════════════════════════════════════════════
# 2.1a: Fundamental Change Factors
# ═══════════════════════════════════════════════════════════════


def task_2_1a(conn):
    """Compute QoQ change factors from fundamentals and test IC."""
    print("\n" + "=" * 70)
    print("  2.1a: Fundamental Change Factors (QoQ Delta)")
    print("=" * 70)
    t0 = time.time()

    # Load level factors
    placeholders = ",".join(["%s"] * len(FUNDAMENTAL_FACTORS))
    level_df = pd.read_sql(f"""
        SELECT code, trade_date, factor_name, raw_value
        FROM factor_values
        WHERE factor_name IN ({placeholders})
          AND trade_date >= '2020-01-01' AND trade_date <= '2026-04-15'
          AND raw_value IS NOT NULL
        ORDER BY code, trade_date
    """, conn, params=tuple(FUNDAMENTAL_FACTORS))
    level_df["trade_date"] = pd.to_datetime(level_df["trade_date"]).dt.date
    level_df["raw_value"] = level_df["raw_value"].astype(float)
    print(f"  Loaded {len(level_df):,} fundamental rows")

    # Load forward returns
    fwd_excess = load_forward_returns_pivot(conn, date(2023, 1, 1), date(2026, 4, 1))

    results = {}
    for change_name, source_name in CHANGE_FACTOR_DEFS.items():
        print(f"\n  Computing {change_name} from {source_name}...")

        src = level_df[level_df["factor_name"] == source_name].copy()
        if src.empty:
            print(f"    {change_name}: no source data!")
            results[change_name] = {"ic_mean": np.nan, "note": "no source data"}
            continue

        # For each stock, detect actual value changes (quarterly update days)
        # Then compute diff and forward-fill
        src = src.sort_values(["code", "trade_date"])

        # Detect change points: where raw_value differs from previous day
        src["prev_val"] = src.groupby("code")["raw_value"].shift(1)
        src["is_change"] = (src["raw_value"] != src["prev_val"]) & src["prev_val"].notna()

        # At change points, compute delta
        src["delta"] = np.where(src["is_change"], src["raw_value"] - src["prev_val"], np.nan)

        # Forward-fill delta within each stock
        src["delta_ffill"] = src.groupby("code")["delta"].ffill()

        # Filter valid
        valid = src[src["delta_ffill"].notna() & np.isfinite(src["delta_ffill"])].copy()
        print(f"    {change_name}: {len(valid):,} valid rows ({valid['code'].nunique()} stocks)")

        if len(valid) < 1000:
            results[change_name] = {"ic_mean": np.nan, "note": "insufficient data"}
            continue

        # Write to DB
        n_written = write_copy_upsert(
            conn,
            valid["code"].values,
            valid["trade_date"].values,
            change_name,
            valid["delta_ffill"].values,
        )
        print(f"    Written to DB: {n_written:,} rows")

        # Compute IC (only on 2023+ dates for consistency with quick-screen)
        ic_df = valid[valid["trade_date"] >= date(2023, 1, 1)].copy()
        ic_df = ic_df.rename(columns={"delta_ffill": "raw_value"})[["code", "trade_date", "raw_value"]]

        # Sample every 20th trading date
        all_dates = sorted(ic_df["trade_date"].unique())
        sampled = all_dates[::20]
        ic_df = ic_df[ic_df["trade_date"].isin(sampled)]

        ic_result = compute_ic_for_factor(ic_df, fwd_excess)
        ic_result["factor_name"] = change_name
        ic_result["source"] = source_name
        results[change_name] = ic_result

        ic_str = f"IC={ic_result['ic_mean']:+.4f}, t={ic_result.get('t_stat', 0):.2f}" if not np.isnan(ic_result.get("ic_mean", np.nan)) else "N/A"
        print(f"    IC: {ic_str}")

    # Compare with level factors
    print("\n── Change vs Level IC Comparison ──")
    print(f"  {'Factor':>20s} | {'Level IC':>10s} | {'Change IC':>10s} | {'Improve?':>10s}")
    print(f"  {'-'*20}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")

    # Load level ICs from quick-screen CSV
    qs = pd.read_csv(CACHE_DIR / "phase3a_ic_quickscreen.csv")
    level_ics = qs.set_index("factor_name")["ic_mean"].to_dict()

    for change_name, source_name in CHANGE_FACTOR_DEFS.items():
        level_ic = level_ics.get(source_name, np.nan)
        change_ic = results.get(change_name, {}).get("ic_mean", np.nan)
        if np.isnan(level_ic) or np.isnan(change_ic):
            improve = "N/A"
        elif abs(change_ic) > abs(level_ic):
            improve = "YES"
        else:
            improve = "no"
        l_str = f"{level_ic:+.4f}" if not np.isnan(level_ic) else "N/A"
        c_str = f"{change_ic:+.4f}" if not np.isnan(change_ic) else "N/A"
        print(f"  {change_name:>20s} | {l_str:>10s} | {c_str:>10s} | {improve:>10s}")

    elapsed = time.time() - t0
    save_result(results, "task_2_1a_change_factors")
    print(f"\n  2.1a complete ({elapsed:.0f}s)")
    return results


# ═══════════════════════════════════════════════════════════════
# 2.1b: Industry-Relative Ranking
# ═══════════════════════════════════════════════════════════════


def task_2_1b(conn):
    """Compute industry-relative percentile rankings and test IC."""
    print("\n" + "=" * 70)
    print("  2.1b: Industry-Relative Ranking Factors")
    print("=" * 70)
    t0 = time.time()

    # Load industry mapping (SW1)
    from app.services.industry_utils import apply_sw2_to_sw1
    cur = conn.cursor()
    cur.execute("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'")
    ind_raw = {r[0]: r[1] if r[1] and r[1] != "nan" else "other" for r in cur.fetchall()}
    ind_map = apply_sw2_to_sw1(ind_raw, conn)
    print(f"  Industry map: {len(ind_map)} stocks, {len(set(ind_map.values()))} industries")

    # Load fundamental factors
    placeholders = ",".join(["%s"] * len(FUNDAMENTAL_FACTORS))
    fund_df = pd.read_sql(f"""
        SELECT code, trade_date, factor_name, raw_value
        FROM factor_values
        WHERE factor_name IN ({placeholders})
          AND trade_date >= '2020-01-01' AND trade_date <= '2026-04-15'
          AND raw_value IS NOT NULL
        ORDER BY trade_date, code
    """, conn, params=tuple(FUNDAMENTAL_FACTORS))
    fund_df["trade_date"] = pd.to_datetime(fund_df["trade_date"]).dt.date
    fund_df["raw_value"] = fund_df["raw_value"].astype(float)
    fund_df["industry"] = fund_df["code"].map(ind_map).fillna("other")
    print(f"  Loaded {len(fund_df):,} fundamental rows")

    # Load forward returns
    fwd_excess = load_forward_returns_pivot(conn, date(2023, 1, 1), date(2026, 4, 1))

    results = {}
    for rank_name, source_name in IND_RANK_DEFS.items():
        print(f"\n  Computing {rank_name} from {source_name}...")

        src = fund_df[fund_df["factor_name"] == source_name].copy()
        if src.empty:
            results[rank_name] = {"ic_mean": np.nan, "note": "no data"}
            continue

        # Compute percentile rank within industry on each date
        src["ind_rank"] = src.groupby(["trade_date", "industry"])["raw_value"].rank(pct=True)

        valid = src[src["ind_rank"].notna()].copy()
        print(f"    {rank_name}: {len(valid):,} valid rows")

        if len(valid) < 1000:
            results[rank_name] = {"ic_mean": np.nan, "note": "insufficient data"}
            continue

        # Write to DB
        n_written = write_copy_upsert(
            conn,
            valid["code"].values,
            valid["trade_date"].values,
            rank_name,
            valid["ind_rank"].values,
        )
        print(f"    Written to DB: {n_written:,} rows")

        # Compute IC (2023+ sampled)
        ic_df = valid[valid["trade_date"] >= date(2023, 1, 1)].copy()
        ic_df = ic_df.rename(columns={"ind_rank": "raw_value"})[["code", "trade_date", "raw_value"]]
        all_dates = sorted(ic_df["trade_date"].unique())
        sampled = all_dates[::20]
        ic_df = ic_df[ic_df["trade_date"].isin(sampled)]

        ic_result = compute_ic_for_factor(ic_df, fwd_excess)
        ic_result["factor_name"] = rank_name
        ic_result["source"] = source_name
        results[rank_name] = ic_result

        ic_str = f"IC={ic_result['ic_mean']:+.4f}, t={ic_result.get('t_stat', 0):.2f}" if not np.isnan(ic_result.get("ic_mean", np.nan)) else "N/A"
        print(f"    IC: {ic_str}")

    elapsed = time.time() - t0
    save_result(results, "task_2_1b_industry_ranking")
    print(f"\n  2.1b complete ({elapsed:.0f}s)")
    return results


# ═══════════════════════════════════════════════════════════════
# 2.1c: Fundamental Pre-Filter Backtests
# ═══════════════════════════════════════════════════════════════


def task_2_1c(conn):
    """Test fundamental pre-filters on CORE4+SN backtest."""
    print("\n" + "=" * 70)
    print("  2.1c: Fundamental Pre-Filter Backtests")
    print("=" * 70)
    t0 = time.time()

    from engines.backtest.config import BacktestConfig
    from engines.backtest.runner import run_hybrid_backtest
    from engines.signal_engine import SignalConfig

    price, bench = load_price_data()
    core4_df = load_core4_factors()

    # Load fundamentals for filtering
    fund_df = pd.read_sql("""
        SELECT code, trade_date, factor_name, raw_value
        FROM factor_values
        WHERE factor_name IN ('roe_dt_q', 'leverage_q', 'gross_margin_q')
          AND trade_date >= '2020-01-01' AND trade_date <= '2026-04-15'
          AND raw_value IS NOT NULL
    """, conn)
    fund_df["trade_date"] = pd.to_datetime(fund_df["trade_date"]).dt.date
    fund_df["raw_value"] = fund_df["raw_value"].astype(float)

    # Pivot fundamentals for easy lookup
    roe_pivot = fund_df[fund_df["factor_name"] == "roe_dt_q"].pivot(
        index="trade_date", columns="code", values="raw_value"
    )
    leverage_pivot = fund_df[fund_df["factor_name"] == "leverage_q"].pivot(
        index="trade_date", columns="code", values="raw_value"
    )
    margin_pivot = fund_df[fund_df["factor_name"] == "gross_margin_q"].pivot(
        index="trade_date", columns="code", values="raw_value"
    )

    # Load industry map for Filter D (median comparison)
    from app.services.industry_utils import apply_sw2_to_sw1
    cur = conn.cursor()
    cur.execute("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'")
    ind_raw = {r[0]: r[1] if r[1] and r[1] != "nan" else "other" for r in cur.fetchall()}
    ind_map = apply_sw2_to_sw1(ind_raw, conn)

    # Filter functions: return set of allowed codes for a given date
    def filter_a(td):
        """ROE > 0"""
        if td not in roe_pivot.index:
            return None
        row = roe_pivot.loc[td].dropna()
        return set(row[row > 0].index)

    def filter_b(td):
        """Leverage < 70%"""
        if td not in leverage_pivot.index:
            return None
        row = leverage_pivot.loc[td].dropna()
        return set(row[row < 70].index)

    def filter_c(td):
        """ROE > 0 AND Leverage < 70%"""
        a = filter_a(td)
        b = filter_b(td)
        if a is None or b is None:
            return a or b
        return a & b

    def filter_d(td):
        """Gross margin > industry median"""
        if td not in margin_pivot.index:
            return None
        row = margin_pivot.loc[td].dropna()
        ind_series = pd.Series({c: ind_map.get(c, "other") for c in row.index})
        medians = row.groupby(ind_series).transform("median")
        return set(row[row > medians].index)

    filters = {
        "baseline (no filter)": None,
        "Filter A: ROE > 0": filter_a,
        "Filter B: Leverage < 70%": filter_b,
        "Filter C: ROE>0 & Lev<70%": filter_c,
        "Filter D: Margin > ind median": filter_d,
    }

    results = {}
    for label, filter_fn in filters.items():
        print(f"\n  Running: {label}")

        if filter_fn is None:
            # Baseline: no filter
            filtered_df = core4_df
        else:
            # Apply filter per date
            filtered_parts = []
            for td, grp in core4_df.groupby("trade_date"):
                allowed = filter_fn(td)
                if allowed is None:
                    filtered_parts.append(grp)
                else:
                    filtered_parts.append(grp[grp["code"].isin(allowed)])
            filtered_df = pd.concat(filtered_parts, ignore_index=True)

        n_orig = len(core4_df)
        n_filtered = len(filtered_df)
        pct = n_filtered / n_orig * 100 if n_orig > 0 else 0
        print(f"    Universe: {n_filtered:,}/{n_orig:,} rows ({pct:.1f}%)")

        bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)
        sig_config = SignalConfig(
            factor_names=list(CORE4_DIRECTIONS.keys()),
            top_n=20, weight_method="equal", rebalance_freq="monthly",
            size_neutral_beta=0.50,
        )

        try:
            result = run_hybrid_backtest(
                factor_df=filtered_df,
                directions=CORE4_DIRECTIONS,
                price_data=price,
                config=bt_config,
                benchmark_data=bench,
                signal_config=sig_config,
                conn=conn,
            )
            metrics = compute_metrics(result.daily_nav)
            metrics["label"] = label
            metrics["universe_pct"] = round(pct, 1)
            results[label] = metrics
            print(f"    Sharpe={metrics['sharpe']:.4f}, MDD={metrics['mdd']:.2%}, AnnRet={metrics['annual_return']:.2%}")
        except Exception as e:
            print(f"    FAILED: {e}")
            results[label] = {"label": label, "error": str(e)[:100]}

    # Summary table
    print("\n── Pre-Filter Summary ──")
    print(f"  {'Config':>30s} | {'Sharpe':>8s} | {'MDD':>8s} | {'AnnRet':>8s} | {'Univ%':>6s}")
    print(f"  {'-'*30}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}")
    for label, r in results.items():
        if "error" in r:
            print(f"  {label:>30s} | {'ERROR':>8s}")
        else:
            print(f"  {label:>30s} | {r['sharpe']:>8.4f} | {r['mdd']:>8.2%} | {r['annual_return']:>8.2%} | {r.get('universe_pct', 100):>6.1f}")

    elapsed = time.time() - t0
    save_result(results, "task_2_1c_prefilter")
    print(f"\n  2.1c complete ({elapsed:.0f}s)")
    return results


# ═══════════════════════════════════════════════════════════════
# 2.1d: Fundamental Negative Screening
# ═══════════════════════════════════════════════════════════════


def task_2_1d(conn):
    """Top-30 by CORE4 → remove worst-10 by fundamentals → keep Top-20."""
    print("\n" + "=" * 70)
    print("  2.1d: Fundamental Negative Screening Backtests")
    print("=" * 70)
    t0 = time.time()

    from engines.backtest import BacktestConfig, SimpleBacktester
    from engines.size_neutral import apply_size_neutral

    price, bench = load_price_data()
    core4_df = load_core4_factors()

    # Load fundamentals
    fund_df = pd.read_sql("""
        SELECT code, trade_date, factor_name, raw_value
        FROM factor_values
        WHERE factor_name IN ('roe_dt_q', 'gross_margin_q', 'leverage_q', 'profit_growth_q')
          AND trade_date >= '2020-01-01' AND trade_date <= '2026-04-15'
          AND raw_value IS NOT NULL
    """, conn)
    fund_df["trade_date"] = pd.to_datetime(fund_df["trade_date"]).dt.date
    fund_df["raw_value"] = fund_df["raw_value"].astype(float)

    # Pivot fundamentals
    fund_pivots = {}
    for fn in ["roe_dt_q", "gross_margin_q", "leverage_q", "profit_growth_q"]:
        sub = fund_df[fund_df["factor_name"] == fn]
        fund_pivots[fn] = sub.pivot(index="trade_date", columns="code", values="raw_value")

    # Load ln_mcap for size-neutral
    mcap_df = pd.read_sql("""
        SELECT code, trade_date, total_mv FROM daily_basic
        WHERE trade_date >= '2020-01-01' AND trade_date <= '2026-04-15' AND total_mv > 0
    """, conn)
    mcap_df["trade_date"] = pd.to_datetime(mcap_df["trade_date"]).dt.date
    mcap_df["total_mv"] = mcap_df["total_mv"].astype(float)
    mcap_df["ln_mcap"] = np.log(mcap_df["total_mv"] + 1)
    ln_mcap_pivot = mcap_df.pivot(index="trade_date", columns="code", values="ln_mcap")

    # Build composite scores per date
    print("  Computing composite scores...")
    trade_dates = sorted(set(core4_df["trade_date"].unique()))
    rebal_dates = get_monthly_rebal_dates(trade_dates)
    rebal_dates = [d for d in rebal_dates if OOS_START <= d <= OOS_END]
    print(f"  Rebalance dates: {len(rebal_dates)}")

    # Pre-group core4
    core4_by_date = {td: grp for td, grp in core4_df.groupby("trade_date")}

    def build_composite_scores(td):
        """Compute composite scores for a given date."""
        if td not in core4_by_date:
            return pd.Series(dtype=float)
        grp = core4_by_date[td]
        # Pivot to wide
        wide = grp.pivot(index="code", columns="factor_name", values="raw_value")
        scores = pd.Series(0.0, index=wide.index)
        for fname, direction in CORE4_DIRECTIONS.items():
            if fname in wide.columns:
                col = wide[fname].fillna(0)
                # z-score within cross-section
                std = col.std()
                if std > 1e-12:
                    z = (col - col.mean()) / std
                else:
                    z = col * 0
                scores += z * direction
        scores /= len(CORE4_DIRECTIONS)
        # Apply SN
        if td in ln_mcap_pivot.index:
            scores = apply_size_neutral(scores, ln_mcap_pivot.loc[td], 0.50)
        return scores

    # Screen functions
    def screen_a(top30_codes, td):
        """Remove worst 10 by ROE (lowest)."""
        if td not in fund_pivots["roe_dt_q"].index:
            return top30_codes[:20]
        roe = fund_pivots["roe_dt_q"].loc[td].reindex(top30_codes).dropna()
        if len(roe) < 20:
            return top30_codes[:20]
        worst10 = set(roe.nsmallest(min(10, len(roe) - 20)).index)
        return [c for c in top30_codes if c not in worst10][:20]

    def screen_b(top30_codes, td):
        """Remove worst 10 by composite quality (ROE + margin - leverage)."""
        roe = fund_pivots["roe_dt_q"].loc[td].reindex(top30_codes) if td in fund_pivots["roe_dt_q"].index else pd.Series(dtype=float)
        margin = fund_pivots["gross_margin_q"].loc[td].reindex(top30_codes) if td in fund_pivots["gross_margin_q"].index else pd.Series(dtype=float)
        lev = fund_pivots["leverage_q"].loc[td].reindex(top30_codes) if td in fund_pivots["leverage_q"].index else pd.Series(dtype=float)

        quality = pd.DataFrame({"roe": roe, "margin": margin, "lev": lev})
        quality = quality.dropna(how="all")
        if len(quality) < 20:
            return top30_codes[:20]

        # z-score each, combine
        for col in ["roe", "margin", "lev"]:
            s = quality[col]
            std = s.std()
            quality[col] = (s - s.mean()) / std if std > 1e-12 else 0

        quality["score"] = quality["roe"] + quality["margin"] - quality["lev"]
        worst10 = set(quality.nsmallest(min(10, len(quality) - 20), "score").index)
        return [c for c in top30_codes if c not in worst10][:20]

    def screen_c(top30_codes, td):
        """Remove worst 10 by profit_growth_q (declining)."""
        if td not in fund_pivots["profit_growth_q"].index:
            return top30_codes[:20]
        pg = fund_pivots["profit_growth_q"].loc[td].reindex(top30_codes).dropna()
        if len(pg) < 20:
            return top30_codes[:20]
        worst10 = set(pg.nsmallest(min(10, len(pg) - 20)).index)
        return [c for c in top30_codes if c not in worst10][:20]

    screens = {
        "baseline (Top-20 direct)": None,
        "Screen A: Remove worst ROE": screen_a,
        "Screen B: Remove worst quality": screen_b,
        "Screen C: Remove worst growth": screen_c,
    }

    results = {}
    for label, screen_fn in screens.items():
        print(f"\n  Running: {label}")
        target_portfolios = {}

        for td in rebal_dates:
            scores = build_composite_scores(td)
            if scores.empty:
                continue

            if screen_fn is None:
                # Baseline: just take top 20
                top = scores.nlargest(20)
            else:
                # Take top 30, apply screen
                top30 = scores.nlargest(30)
                top30_codes = list(top30.index)
                kept_codes = screen_fn(top30_codes, td)
                top = scores.reindex(kept_codes).dropna()

            if len(top) == 0:
                continue
            w = 1.0 / len(top)
            target_portfolios[td] = {code: w for code in top.index}

        if not target_portfolios:
            print("    No portfolios built!")
            results[label] = {"label": label, "error": "no portfolios"}
            continue

        bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)
        tester = SimpleBacktester(bt_config)
        result = tester.run(target_portfolios, price, bench)
        metrics = compute_metrics(result.daily_nav)
        metrics["label"] = label
        metrics["n_rebal"] = len(target_portfolios)
        results[label] = metrics
        print(f"    Sharpe={metrics['sharpe']:.4f}, MDD={metrics['mdd']:.2%}, n_rebal={len(target_portfolios)}")

    # Summary
    print("\n── Negative Screening Summary ──")
    print(f"  {'Config':>30s} | {'Sharpe':>8s} | {'MDD':>8s} | {'AnnRet':>8s}")
    print(f"  {'-'*30}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")
    for label, r in results.items():
        if "error" in r:
            print(f"  {label:>30s} | {'ERROR':>8s}")
        else:
            print(f"  {label:>30s} | {r['sharpe']:>8.4f} | {r['mdd']:>8.2%} | {r['annual_return']:>8.2%}")

    elapsed = time.time() - t0
    save_result(results, "task_2_1d_negative_screening")
    print(f"\n  2.1d complete ({elapsed:.0f}s)")
    return results


# ═══════════════════════════════════════════════════════════════
# 2.2: IC Decay Curves
# ═══════════════════════════════════════════════════════════════


def task_2_2(conn):
    """IC decay curves for 32 significant factors using factor_profiler."""
    print("\n" + "=" * 70)
    print("  2.2: IC Decay Curves (32 Factors x 6 Horizons)")
    print("=" * 70)
    t0 = time.time()

    from engines.factor_profiler import _load_shared_data, profile_factor

    print("  Loading shared data for factor_profiler...")
    close_pivot, fwd_excess, csi_monthly, industry_map, trading_dates = _load_shared_data(conn)
    print(f"  Shared data loaded: {len(trading_dates)} dates")

    # Get all factor names for redundancy check
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT factor_name FROM factor_values")
    all_factor_names = sorted([r[0] for r in cur.fetchall()])

    results = {}
    for i, fname in enumerate(SIGNIFICANT_FACTORS):
        t1 = time.time()
        print(f"\n  [{i+1:>2}/{len(SIGNIFICANT_FACTORS)}] Profiling {fname}...")

        try:
            profile = profile_factor(
                fname, close_pivot, fwd_excess, csi_monthly,
                industry_map, trading_dates, conn=conn,
                all_factor_names=all_factor_names,
            )

            if "error" in profile:
                print(f"    {fname}: {profile['error']}")
                results[fname] = {"factor_name": fname, "error": profile["error"]}
                continue

            # Extract IC decay data
            decay = {}
            for h in [1, 5, 10, 20, 60, 120]:
                ic_key = f"ic_{h}d"
                t_key = f"ic_{h}d_tstat"
                decay[f"ic_{h}d"] = profile.get(ic_key, None)
                decay[f"t_{h}d"] = profile.get(t_key, None)

            decay["optimal_horizon"] = profile.get("optimal_horizon")
            decay["ic_halflife"] = profile.get("ic_halflife")
            decay["monotonicity"] = profile.get("monotonicity")
            decay["rank_autocorr_5d"] = profile.get("rank_autocorr_5d")
            decay["regime_sensitivity"] = profile.get("regime_sensitivity")
            decay["ic_bull"] = profile.get("ic_bull")
            decay["ic_bear"] = profile.get("ic_bear")
            decay["cost_feasible"] = profile.get("cost_feasible")
            decay["max_corr_factor"] = profile.get("max_corr_factor")
            decay["max_corr_value"] = profile.get("max_corr_value")
            decay["top_q_turnover_monthly"] = profile.get("top_q_turnover_monthly")
            decay["factor_name"] = fname

            # Classify decay type
            ic_20 = abs(decay.get("ic_20d") or 0)
            ic_5 = abs(decay.get("ic_5d") or 0)
            ic_60 = abs(decay.get("ic_60d") or 0)
            ic_120 = abs(decay.get("ic_120d") or 0)

            if ic_20 > 0:
                if ic_5 > 0 and ic_5 / ic_20 > 1.5:
                    decay["decay_type"] = "FAST"
                elif ic_60 > 0 and ic_60 / ic_20 > 0.7:
                    decay["decay_type"] = "SLOW"
                else:
                    decay["decay_type"] = "MEDIUM"
            else:
                decay["decay_type"] = "WEAK"

            # Check sign flip
            ic_20_signed = decay.get("ic_20d") or 0
            ic_120_signed = decay.get("ic_120d") or 0
            if ic_20_signed != 0 and ic_120_signed != 0:
                if (ic_20_signed > 0) != (ic_120_signed > 0):
                    decay["decay_type"] = "INVERTED"

            results[fname] = decay
            elapsed_f = time.time() - t1
            ic20_str = f"IC_20d={decay.get('ic_20d', 'N/A')}"
            print(f"    {ic20_str}, halflife={decay.get('ic_halflife')}, "
                  f"decay={decay['decay_type']}, mono={decay.get('monotonicity', 'N/A')} ({elapsed_f:.1f}s)")

        except Exception as e:
            print(f"    {fname}: FAILED - {e}")
            results[fname] = {"factor_name": fname, "error": str(e)[:100]}

        gc.collect()

    # Summary table
    print("\n" + "=" * 70)
    print("  IC Decay Summary")
    print("=" * 70)
    print(f"  {'Factor':>25s} | {'IC_1d':>7s} | {'IC_5d':>7s} | {'IC_20d':>7s} | {'IC_60d':>7s} | {'IC_120d':>7s} | {'Half':>5s} | {'Type':>8s}")
    print(f"  {'-'*25}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*5}-+-{'-'*8}")

    for fname in SIGNIFICANT_FACTORS:
        r = results.get(fname, {})
        if "error" in r:
            print(f"  {fname:>25s} | {'ERROR':>7s}")
            continue

        def fmt(v):
            return f"{v:+.3f}" if v is not None else "  N/A"

        hl = r.get("ic_halflife")
        hl_str = f"{hl:>5.0f}" if hl is not None else "  N/A"

        print(f"  {fname:>25s} | {fmt(r.get('ic_1d')):>7s} | {fmt(r.get('ic_5d')):>7s} | "
              f"{fmt(r.get('ic_20d')):>7s} | {fmt(r.get('ic_60d')):>7s} | {fmt(r.get('ic_120d')):>7s} | "
              f"{hl_str} | {r.get('decay_type', 'N/A'):>8s}")

    # Decay type distribution
    decay_counts = {}
    for r in results.values():
        dt = r.get("decay_type", "ERROR")
        decay_counts[dt] = decay_counts.get(dt, 0) + 1
    print(f"\n  Decay distribution: {decay_counts}")

    elapsed = time.time() - t0
    save_result(results, "task_2_2_ic_decay")
    print(f"\n  2.2 complete ({elapsed:.0f}s)")
    return results


# ═══════════════════════════════════════════════════════════════
# 2.3: Factor Usage Recommendation Table
# ═══════════════════════════════════════════════════════════════


def task_2_3(conn, decay_results=None):
    """Compile factor recommendation table from all previous results."""
    print("\n" + "=" * 70)
    print("  2.3: Factor Usage Recommendation Table")
    print("=" * 70)

    # Load decay results if not passed
    if decay_results is None:
        fp = PHASE3B_CACHE / "task_2_2_ic_decay.json"
        if fp.exists():
            with open(fp, encoding="utf-8") as f:
                decay_results = json.load(f)
        else:
            print("  ERROR: No IC decay results found! Run --task 2.2 first.")
            return {}

    # Load IC quick-screen for t-stats
    qs = pd.read_csv(CACHE_DIR / "phase3a_ic_quickscreen.csv")
    qs_dict = qs.set_index("factor_name").to_dict("index")

    # Compute correlations with CORE4
    print("  Computing correlations with CORE4...")
    cur = conn.cursor()

    # Sample dates for cross-sectional correlation
    cur.execute("""
        SELECT DISTINCT trade_date FROM factor_values
        WHERE factor_name = 'turnover_mean_20'
          AND trade_date >= '2023-01-01' AND trade_date <= '2026-04-01'
          AND neutral_value IS NOT NULL
        ORDER BY trade_date
    """)
    all_dates = [r[0] for r in cur.fetchall()]
    sample_dates = all_dates[::20]  # every 20th date

    corr_with_core4 = {}
    for fname in SIGNIFICANT_FACTORS:
        max_corr = 0
        max_corr_factor = ""

        for core_fname in CORE4_FACTORS:
            corrs = []
            for td in sample_dates:
                # Load both factors on this date
                cur.execute("""
                    SELECT code, COALESCE(neutral_value, raw_value) AS val
                    FROM factor_values
                    WHERE factor_name = %s AND trade_date = %s AND raw_value IS NOT NULL
                """, (fname, td))
                f1 = {r[0]: float(r[1]) for r in cur.fetchall()}

                cur.execute("""
                    SELECT code, COALESCE(neutral_value, raw_value) AS val
                    FROM factor_values
                    WHERE factor_name = %s AND trade_date = %s AND raw_value IS NOT NULL
                """, (core_fname, td))
                f2 = {r[0]: float(r[1]) for r in cur.fetchall()}

                common = set(f1.keys()) & set(f2.keys())
                if len(common) < 30:
                    continue
                v1 = np.array([f1[c] for c in common])
                v2 = np.array([f2[c] for c in common])
                rho, _ = sp_stats.spearmanr(v1, v2)
                if not np.isnan(rho):
                    corrs.append(abs(rho))

            if corrs:
                avg_corr = np.mean(corrs)
                if avg_corr > max_corr:
                    max_corr = avg_corr
                    max_corr_factor = core_fname

        corr_with_core4[fname] = {"max_corr": round(max_corr, 3), "max_corr_factor": max_corr_factor}
        if (SIGNIFICANT_FACTORS.index(fname) + 1) % 8 == 0:
            print(f"    Correlation progress: {SIGNIFICANT_FACTORS.index(fname)+1}/{len(SIGNIFICANT_FACTORS)}")

    # Build recommendation table
    recommendations = []
    for fname in SIGNIFICANT_FACTORS:
        qs_info = qs_dict.get(fname, {})
        decay_info = decay_results.get(fname, {})
        corr_info = corr_with_core4.get(fname, {})

        ic_20d = decay_info.get("ic_20d")
        t_stat = qs_info.get("t_stat", 0)
        mono = decay_info.get("monotonicity")
        decay_type = decay_info.get("decay_type", "UNKNOWN")
        max_corr = corr_info.get("max_corr", 0)
        max_corr_f = corr_info.get("max_corr_factor", "")
        cost_ok = decay_info.get("cost_feasible", True)

        # Decision tree for layer assignment
        layer = "Monitor Only"
        priority = "P4"

        if abs(t_stat) > 2.5 and max_corr < 0.5 and decay_type in ("SLOW", "MEDIUM"):
            if mono is not None and abs(mono) > 0.5 and cost_ok:
                layer = "CORE Candidate"
                priority = "P1"
            elif mono is not None and abs(mono) > 0.3:
                layer = "CORE Candidate"
                priority = "P2"
            else:
                layer = "ML Feature"
                priority = "P3"
        elif abs(t_stat) > 2.5 and max_corr < 0.7:
            if decay_type in ("FAST", "INVERTED"):
                layer = "ML Feature"
                priority = "P3"
            else:
                layer = "Modifier"
                priority = "P3"
        elif abs(t_stat) > 2.0 and max_corr >= 0.7:
            layer = "Monitor Only (redundant)"
            priority = "P4"
        elif abs(t_stat) > 2.5:
            layer = "ML Feature"
            priority = "P3"

        rec = {
            "factor": fname,
            "ic_20d": round(ic_20d, 4) if ic_20d is not None else None,
            "t_stat": round(t_stat, 2),
            "max_corr_core4": max_corr,
            "corr_with": max_corr_f,
            "decay_type": decay_type,
            "monotonicity": round(mono, 3) if mono is not None else None,
            "cost_feasible": cost_ok,
            "layer": layer,
            "priority": priority,
        }
        recommendations.append(rec)

    # Sort by priority then |t_stat|
    priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    recommendations.sort(key=lambda r: (priority_order.get(r["priority"], 9), -abs(r["t_stat"])))

    # Display
    print("\n" + "=" * 70)
    print("  Factor Usage Recommendation Table")
    print("=" * 70)
    print(f"  {'Factor':>25s} | {'IC_20d':>7s} | {'t':>6s} | {'Corr':>5s} | {'Decay':>8s} | {'Mono':>5s} | {'Layer':>22s} | {'Pri':>3s}")
    print(f"  {'-'*25}-+-{'-'*7}-+-{'-'*6}-+-{'-'*5}-+-{'-'*8}-+-{'-'*5}-+-{'-'*22}-+-{'-'*3}")

    for r in recommendations:
        ic_str = f"{r['ic_20d']:+.4f}" if r["ic_20d"] is not None else "  N/A"
        mono_str = f"{r['monotonicity']:.2f}" if r["monotonicity"] is not None else " N/A"
        print(f"  {r['factor']:>25s} | {ic_str:>7s} | {r['t_stat']:>6.2f} | {r['max_corr_core4']:>5.2f} | "
              f"{r['decay_type']:>8s} | {mono_str:>5s} | {r['layer']:>22s} | {r['priority']:>3s}")

    # Priority distribution
    pri_counts = {}
    layer_counts = {}
    for r in recommendations:
        pri_counts[r["priority"]] = pri_counts.get(r["priority"], 0) + 1
        layer_counts[r["layer"]] = layer_counts.get(r["layer"], 0) + 1

    print(f"\n  Priority distribution: {pri_counts}")
    print(f"  Layer distribution: {layer_counts}")

    # Save CSV
    rec_df = pd.DataFrame(recommendations)
    csv_path = PHASE3B_CACHE / "factor_recommendations.csv"
    rec_df.to_csv(csv_path, index=False)
    print(f"  CSV saved: {csv_path}")

    save_result({"recommendations": recommendations, "corr_with_core4": corr_with_core4}, "task_2_3_recommendations")
    return recommendations


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Phase 3B: Factor Characteristics Analysis")
    parser.add_argument("--task", type=str, default="all",
                        help="Task to run: 2.1a/2.1b/2.1c/2.1d/2.2/2.3/all")
    parser.add_argument("--all", action="store_true", help="Run all tasks")
    args = parser.parse_args()

    conn = get_conn()
    t_total = time.time()

    task = args.task if not args.all else "all"

    PHASE3B_CACHE.mkdir(parents=True, exist_ok=True)

    if task in ("2.1a", "all"):
        task_2_1a(conn)
        gc.collect()

    if task in ("2.1b", "all"):
        task_2_1b(conn)
        gc.collect()

    if task in ("2.1c", "all"):
        task_2_1c(conn)
        gc.collect()

    if task in ("2.1d", "all"):
        task_2_1d(conn)
        gc.collect()

    decay_results = None
    if task in ("2.2", "all"):
        decay_results = task_2_2(conn)
        gc.collect()

    if task in ("2.3", "all"):
        task_2_3(conn, decay_results)

    total_elapsed = time.time() - t_total
    print(f"\n{'='*70}")
    print(f"  Phase 3B complete ({total_elapsed:.0f}s)")
    print(f"  Results in: {PHASE3B_CACHE}")
    print(f"{'='*70}")

    conn.close()


if __name__ == "__main__":
    main()
