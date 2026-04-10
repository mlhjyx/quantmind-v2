#!/usr/bin/env python3
"""Phase 2 前置调研: 新因子IC快速验证 (2.4/2.5/2.6/2.7)。

从Parquet cache加载数据，计算IC，不改任何生产代码/表/cache。
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from engines.ic_calculator import (
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "backtest"
YEARS = [2023, 2024, 2025]


def load_parquet_cache(years=None):
    """加载Parquet缓存。"""
    years = years or YEARS
    price_dfs, bench_dfs = [], []
    for y in years:
        ydir = CACHE_DIR / str(y)
        if not ydir.exists():
            continue
        p = pd.read_parquet(ydir / "price_data.parquet")
        b = pd.read_parquet(ydir / "benchmark.parquet")
        price_dfs.append(p)
        bench_dfs.append(b)

    price = pd.concat(price_dfs, ignore_index=True)
    bench = pd.concat(bench_dfs, ignore_index=True)

    # 标准化日期
    price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.date
    bench["trade_date"] = pd.to_datetime(bench["trade_date"]).dt.date

    # 过滤BJ/ST/停牌/新股
    if "board" in price.columns:
        price = price[price["board"] != "bse"]
    for col in ["is_st", "is_suspended", "is_new_stock"]:
        if col in price.columns:
            price = price[price[col] != True]  # noqa: E712

    return price, bench


def compute_fwd_returns(price, bench, horizon=20):
    """计算前瞻超额收益。"""
    # ic_calculator expects long format: (code, trade_date, adj_close)
    price_long = price[["code", "trade_date", "adj_close"]].copy()
    bench_long = bench[["trade_date", "close"]].drop_duplicates("trade_date").copy()
    fwd = compute_forward_excess_returns(price_long, bench_long, horizon=horizon)
    return fwd


def evaluate_ic(factor_wide, fwd_returns, name="factor"):
    """评估IC。"""
    common_dates = factor_wide.index.intersection(fwd_returns.index)
    common_codes = factor_wide.columns.intersection(fwd_returns.columns)
    f = factor_wide.loc[common_dates, common_codes]
    r = fwd_returns.loc[common_dates, common_codes]
    ic = compute_ic_series(f, r)
    stats_dict = summarize_ic_stats(ic)
    return stats_dict, ic


def compute_24_high_vol_price(price):
    """2.4 高低位放量因子。"""
    print("\n[2.4] Computing high_vol_price factors...")
    t0 = time.time()

    # 准备宽表
    close_wide = price.pivot_table(index="trade_date", columns="code", values="close")
    high_wide = price.pivot_table(index="trade_date", columns="code", values="high")
    low_wide = price.pivot_table(index="trade_date", columns="code", values="low")
    open_wide = price.pivot_table(index="trade_date", columns="code", values="open")

    # 日内波动率
    intravol_wide = (high_wide - low_wide) / (open_wide + 1e-12)

    close_wide = close_wide.sort_index()
    intravol_wide = intravol_wide.sort_index()

    window = 20
    top_k = 4  # top 20%

    dates = close_wide.index[window - 1 :]
    codes = close_wide.columns

    hvpr = pd.DataFrame(index=dates, columns=codes, dtype=float)  # high_vol_price_ratio
    hpvr = pd.DataFrame(index=dates, columns=codes, dtype=float)  # high_price_vol_ratio

    close_arr = close_wide.values
    intravol_arr = intravol_wide.values

    for i in range(window - 1, len(close_wide)):
        c_win = close_arr[i - window + 1 : i + 1]  # (20, n_codes)
        v_win = intravol_arr[i - window + 1 : i + 1]

        # Factor a: top-4 days by intraday_vol → mean(close) / overall mean(close)
        v_ranks = np.argsort(np.argsort(-v_win, axis=0), axis=0)  # rank descending
        top_v_mask = v_ranks < top_k  # (20, n_codes) bool
        c_mean_all = np.nanmean(c_win, axis=0)
        c_top_v = np.where(top_v_mask, c_win, np.nan)
        c_mean_top_v = np.nanmean(c_top_v, axis=0)
        hvpr_row = c_mean_top_v / (c_mean_all + 1e-12)

        # Factor b: top-4 days by close → sum(intraday_vol) / total sum(intraday_vol)
        c_ranks = np.argsort(np.argsort(-c_win, axis=0), axis=0)
        top_c_mask = c_ranks < top_k
        v_top_c = np.where(top_c_mask, v_win, 0)
        v_sum_top_c = np.nansum(v_top_c, axis=0)
        v_sum_all = np.nansum(v_win, axis=0)
        hpvr_row = v_sum_top_c / (v_sum_all + 1e-12)

        hvpr.iloc[i - window + 1] = hvpr_row
        hpvr.iloc[i - window + 1] = hpvr_row

    hvpr = hvpr.astype(float)
    hpvr = hpvr.astype(float)
    composite = (hvpr + hpvr) / 2

    print(f"  Done in {time.time() - t0:.1f}s")
    return {
        "high_vol_price_ratio_20": hvpr,
        "high_price_vol_ratio_20": hpvr,
        "composite_hvp_20": composite,
    }


def compute_25_cgo(price):
    """2.5 CGO资本利得突出量(近似)。"""
    print("\n[2.5] Computing CGO approximation...")
    t0 = time.time()

    close_wide = price.pivot_table(index="trade_date", columns="code", values="close")
    amount_wide = price.pivot_table(index="trade_date", columns="code", values="amount")
    volume_wide = price.pivot_table(index="trade_date", columns="code", values="volume")

    close_wide = close_wide.sort_index()
    amount_wide = amount_wide.sort_index()
    volume_wide = volume_wide.sort_index()

    # VWAP_60 = sum(amount, 60) / (sum(volume, 60) * 100)
    # volume is in 手(lots), ×100 = shares; amount is in 元
    amount_sum60 = amount_wide.rolling(60, min_periods=30).sum()
    volume_sum60 = volume_wide.rolling(60, min_periods=30).sum() * 100

    vwap_60 = amount_sum60 / (volume_sum60 + 1e-12)
    cgo = (close_wide - vwap_60) / (vwap_60 + 1e-12)

    print(f"  Done in {time.time() - t0:.1f}s")
    return {"cgo_approx_60": cgo}


def compute_26_str(price):
    """2.6 STR凸显性收益。"""
    print("\n[2.6] Computing STR salience returns...")
    t0 = time.time()

    adj_close_wide = price.pivot_table(index="trade_date", columns="code", values="adj_close")
    adj_close_wide = adj_close_wide.sort_index()
    ret_wide = adj_close_wide.pct_change()

    window = 20
    top_k = 3
    dates = ret_wide.index[window:]
    codes = ret_wide.columns
    str_df = pd.DataFrame(index=dates, columns=codes, dtype=float)
    ret_arr = ret_wide.values

    for i in range(window, len(ret_wide)):
        r_win = ret_arr[i - window : i]  # (20, n_codes)
        abs_r = np.abs(r_win)
        # top-3 by |return|
        ranks = np.argsort(np.argsort(-abs_r, axis=0), axis=0)
        top_mask = ranks < top_k
        r_top = np.where(top_mask, r_win, np.nan)
        str_row = np.nanmean(r_top, axis=0)
        str_df.iloc[i - window] = str_row

    str_df = str_df.astype(float)
    print(f"  Done in {time.time() - t0:.1f}s")
    return {"str_20": str_df}


def compute_27_grouped_ic(price, bench, fwd_returns):
    """2.7 局部化IC分析: CORE 5 × 3 market cap groups。"""
    print("\n[2.7] Computing grouped IC (CORE 5 × 3 cap groups)...")
    t0 = time.time()

    import psycopg2

    conn = psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )

    # Load CORE 5 factors
    core5 = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    placeholders = ",".join(["%s"] * len(core5))
    factor_df = pd.read_sql(
        f"SELECT code, trade_date, factor_name, raw_value FROM factor_values "
        f"WHERE factor_name IN ({placeholders}) "
        f"AND trade_date BETWEEN '2023-01-01' AND '2025-12-31' "
        f"AND raw_value IS NOT NULL",
        conn,
        params=core5,
    )
    factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"]).dt.date

    # Load market cap
    mv_df = pd.read_sql(
        "SELECT code, trade_date, total_mv FROM daily_basic "
        "WHERE trade_date BETWEEN '2023-01-01' AND '2025-12-31' AND total_mv IS NOT NULL",
        conn,
    )
    mv_df["trade_date"] = pd.to_datetime(mv_df["trade_date"]).dt.date
    conn.close()

    # Assign cap group by median market cap
    mv_median = mv_df.groupby("code")["total_mv"].median()

    results = {}
    for fname in core5:
        fdata = factor_df[factor_df["factor_name"] == fname]
        f_wide = fdata.pivot_table(index="trade_date", columns="code", values="raw_value")

        for grp_name, low, high in [
            ("小盘(<50亿)", 0, 500000),
            ("中盘(50-200亿)", 500000, 2000000),
            ("大盘(>200亿)", 2000000, float("inf")),
        ]:
            grp_codes = mv_median[(mv_median >= low) & (mv_median < high)].index
            common_codes = f_wide.columns.intersection(grp_codes).intersection(fwd_returns.columns)
            if len(common_codes) < 50:
                results[(fname, grp_name)] = {"mean": np.nan, "t_stat": np.nan, "n_days": 0}
                continue

            common_dates = f_wide.index.intersection(fwd_returns.index)
            f_grp = f_wide.loc[common_dates, common_codes]
            r_grp = fwd_returns.loc[common_dates, common_codes]
            ic = compute_ic_series(f_grp, r_grp)
            s = summarize_ic_stats(ic)
            results[(fname, grp_name)] = s

    print(f"  Done in {time.time() - t0:.1f}s")
    return results


def load_core5_ic(fwd_returns):
    """加载CORE 5 IC时序(用于相关性对比)。"""
    import psycopg2

    conn = psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )
    core5 = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    placeholders = ",".join(["%s"] * len(core5))
    factor_df = pd.read_sql(
        f"SELECT code, trade_date, factor_name, raw_value FROM factor_values "
        f"WHERE factor_name IN ({placeholders}) "
        f"AND trade_date BETWEEN '2023-01-01' AND '2025-12-31' "
        f"AND raw_value IS NOT NULL",
        conn,
        params=core5,
    )
    factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"]).dt.date
    conn.close()

    ic_dict = {}
    for fname in core5:
        fdata = factor_df[factor_df["factor_name"] == fname]
        f_wide = fdata.pivot_table(index="trade_date", columns="code", values="raw_value")
        common_dates = f_wide.index.intersection(fwd_returns.index)
        common_codes = f_wide.columns.intersection(fwd_returns.columns)
        f = f_wide.loc[common_dates, common_codes]
        r = fwd_returns.loc[common_dates, common_codes]
        ic = compute_ic_series(f, r)
        ic_dict[fname] = ic
    return ic_dict


def main():
    t_start = time.time()
    print("=" * 70)
    print("Phase 2 Signal Feasibility: IC Quick Verification (2023-2025)")
    print("=" * 70)

    # Load data
    print("\nLoading Parquet cache...")
    price, bench = load_parquet_cache()
    print(f"  Price: {len(price)} rows, {price['code'].nunique()} stocks")
    print(f"  Date range: {price['trade_date'].min()} ~ {price['trade_date'].max()}")

    # Forward returns
    print("\nComputing forward excess returns (T+1 to T+20)...")
    fwd = compute_fwd_returns(price, bench, horizon=20)
    print(f"  Shape: {fwd.shape}")

    # 2.4 High-vol-price
    factors_24 = compute_24_high_vol_price(price)

    # 2.5 CGO
    factors_25 = compute_25_cgo(price)

    # 2.6 STR
    factors_26 = compute_26_str(price)

    # Evaluate IC for all new factors
    all_new = {**factors_24, **factors_25, **factors_26}
    print("\n" + "=" * 70)
    print("IC Results (horizon=20, Spearman rank IC)")
    print("=" * 70)

    new_ic_series = {}
    for name, factor_wide in all_new.items():
        s, ic = evaluate_ic(factor_wide, fwd)
        new_ic_series[name] = ic
        print(
            f"  {name:30s}: IC={s['mean']:+.4f}  IR={s['ir']:.3f}  "
            f"t={s['t_stat']:.2f}  hit={s['hit_rate']:.1%}  n={s['n_days']}"
        )

    # Load CORE 5 IC for correlation
    print("\nLoading CORE 5 IC time series...")
    core5_ic = load_core5_ic(fwd)
    print("  CORE 5 IC benchmark:")
    for fname, ic in core5_ic.items():
        s = summarize_ic_stats(ic)
        print(f"    {fname:30s}: IC={s['mean']:+.4f}  IR={s['ir']:.3f}  t={s['t_stat']:.2f}")

    # IC time-series correlation
    print("\n" + "-" * 70)
    print("IC Time-Series Correlation (new vs CORE 5)")
    print("-" * 70)

    for new_name, new_ic in new_ic_series.items():
        max_corr = 0
        max_core = ""
        for core_name, core_ic in core5_ic.items():
            common = new_ic.dropna().index.intersection(core_ic.dropna().index)
            if len(common) < 30:
                continue
            corr = new_ic.loc[common].corr(core_ic.loc[common])
            if abs(corr) > abs(max_corr):
                max_corr = corr
                max_core = core_name
        redundant = "REDUNDANT" if abs(max_corr) > 0.5 else "OK"
        print(f"  {new_name:30s}: max_corr={max_corr:+.3f} (vs {max_core}) -> {redundant}")

    # 2.6 specific: STR vs volatility detail
    print("\n  STR redundancy detail:")
    if "str_20" in new_ic_series:
        str_ic = new_ic_series["str_20"]
        for cname in ["volatility_20", "reversal_20"]:
            if cname in core5_ic:
                common = str_ic.dropna().index.intersection(core5_ic[cname].dropna().index)
                if len(common) > 0:
                    corr = str_ic.loc[common].corr(core5_ic[cname].loc[common])
                    print(f"    str_20 vs {cname}: corr={corr:+.3f}")

    # 2.7 Grouped IC
    grouped_results = compute_27_grouped_ic(price, bench, fwd)
    print("\n" + "=" * 70)
    print("2.7 Localized IC Analysis (CORE 5 x Market Cap)")
    print("=" * 70)
    print(f"  {'Factor':<25s} {'小盘(<50亿)':>18s} {'中盘(50-200亿)':>18s} {'大盘(>200亿)':>18s}")
    print("  " + "-" * 79)
    core5_names = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    for fname in core5_names:
        row = f"  {fname:<25s}"
        for grp in ["小盘(<50亿)", "中盘(50-200亿)", "大盘(>200亿)"]:
            s = grouped_results.get((fname, grp), {})
            if isinstance(s, dict) and "mean" in s and not np.isnan(s.get("mean", np.nan)):
                row += f"  {s['mean']:+.4f}(t={s['t_stat']:5.1f})"
            else:
                row += f"  {'N/A':>17s}"
        print(row)

    total = time.time() - t_start
    print(f"\nTotal time: {total:.0f}s ({total / 60:.1f}min)")
    print("=" * 70)


if __name__ == "__main__":
    main()
