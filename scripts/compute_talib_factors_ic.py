"""
TA-Lib Technical Indicator Factor IC Analysis (5 factors)
=========================================================
Sprint 1.3a — 用ta_wrapper计算5个技术指标的截面IC。

因子列表:
1. RSI_14:           RSI(close, 14)
2. MACD_hist_12_26_9: MACD histogram
3. KDJ_K_9_3_3:      KDJ K线 (STOCH slowK)
4. CCI_14:           CCI(high, low, close, 14)
5. ATR_14_norm:      ATR(14) / close — 归一化ATR

每个因子: ta_wrapper计算 → 截面rank → 与20日超额收益做Spearman IC
数据源: klines_daily (2021-2025)
输出: 月度IC均值/IR/t值/年度分解

DB: postgresql://xin:quantmind@localhost:5432/quantmind_v2
"""

import sys
import time
import warnings
from datetime import date as dt_date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

# ta_wrapper在backend/wrappers/下
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from engines.config_guard import print_config_header
from wrappers.ta_wrapper import calculate_indicator

warnings.filterwarnings("ignore")

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

# IC评估的日期范围
IC_START = dt_date(2021, 1, 1)
IC_END = dt_date(2025, 12, 31)
# 数据加载从2020开始(给滚动指标预热期)
DATA_START = "2020-01-01"


# ── IC computation helper (same pattern as batch4) ──
def compute_monthly_ic(
    factor_wide: pd.DataFrame,
    excess_fwd: pd.DataFrame,
    month_ends: list,
    direction: int = 1,
    date_range: tuple = (IC_START, IC_END),
) -> pd.DataFrame:
    """Compute monthly Spearman IC between factor and forward excess return."""
    fac = factor_wide.copy()
    fac.index = fac.index.astype(str)
    efwd = excess_fwd.copy()
    efwd.index = efwd.index.astype(str)

    ic_records = []
    for d in month_ends:
        d_str = str(d)
        d_date = pd.Timestamp(d_str).date()
        if d_date < date_range[0] or d_date > date_range[1]:
            continue
        if d_str not in fac.index or d_str not in efwd.index:
            continue
        fac_cross = fac.loc[d_str].dropna()
        fwd_cross = efwd.loc[d_str].dropna()
        common = fac_cross.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue
        vals = direction * fac_cross[common].values
        ic, pval = stats.spearmanr(vals, fwd_cross[common].values)
        ic_records.append({"date": d_str, "ic": ic, "pval": pval, "n_stocks": len(common)})
    return pd.DataFrame(ic_records)


def print_ic_report(name: str, formula: str, ic_df: pd.DataFrame) -> dict | None:
    """Print standardized IC report for a factor."""
    if len(ic_df) == 0:
        print(f"\n{'='*70}")
        print(f"  {name}: NO DATA (all months filtered)")
        print(f"{'='*70}")
        return None

    ic_df = ic_df.copy()
    ic_df["date"] = pd.to_datetime(ic_df["date"])
    ic_df["year"] = ic_df["date"].dt.year

    ic_mean = ic_df["ic"].mean()
    ic_std = ic_df["ic"].std()
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_df))) if ic_std > 0 else 0
    pct_pos = (ic_df["ic"] > 0).mean() * 100

    print(f"\n{'='*70}")
    print(f"{name}")
    print(f"Formula: {formula}")
    print(f"{'='*70}")

    print(
        f"\n-- Overall ({ic_df['date'].min().strftime('%Y-%m')} "
        f"~ {ic_df['date'].max().strftime('%Y-%m')}) --"
    )
    print(f"  IC Mean:     {ic_mean:.4f}  ({abs(ic_mean)*100:.2f}%)")
    print(f"  IC Std:      {ic_std:.4f}")
    print(f"  IC_IR:       {ic_ir:.4f}")
    sig = (
        "***" if abs(t_stat) > 2.58
        else "**" if abs(t_stat) > 1.96
        else "*" if abs(t_stat) > 1.64
        else "ns"
    )
    print(f"  t-stat:      {t_stat:.2f}  {sig}")
    print(f"  IC > 0:      {pct_pos:.1f}%")
    print(f"  Months:      {len(ic_df)}")

    # Annual breakdown
    print("\n-- Annual Breakdown --")
    print(f"  {'Year':<6} {'IC_Mean':>8} {'IC_Std':>8} {'IC_IR':>8} {'t-stat':>8} {'IC>0%':>6} {'N':>4}")
    print(f"  {'-'*52}")
    for year, grp in ic_df.groupby("year"):
        ym = grp["ic"].mean()
        ys = grp["ic"].std()
        yir = ym / ys if ys > 0 else 0
        yt = ym / (ys / np.sqrt(len(grp))) if ys > 0 else 0
        yp = (grp["ic"] > 0).mean() * 100
        print(
            f"  {year:<6} {ym:>8.4f} {ys:>8.4f} {yir:>8.4f} "
            f"{yt:>8.2f} {yp:>5.1f}% {len(grp):>4}"
        )

    # Monthly IC series (condensed)
    print("\n-- Monthly IC (condensed) --")
    print(f"  {'Month':<10} {'IC':>8} {'N':>6}")
    print(f"  {'-'*26}")
    for _, row in ic_df.iterrows():
        marker = " *" if abs(row["ic"]) > 0.05 else ""
        print(
            f"  {row['date'].strftime('%Y-%m'):<10} "
            f"{row['ic']:>8.4f} {int(row['n_stocks']):>6}{marker}"
        )

    # Verdict
    print("\n  VERDICT: ", end="")
    if abs(t_stat) > 1.96 and abs(ic_mean) > 0.02:
        print(f"PASS (t={t_stat:.2f}, IC={ic_mean:.4f})")
    elif abs(t_stat) > 1.64 and abs(ic_mean) > 0.015:
        print(f"MARGINAL (t={t_stat:.2f}, IC={ic_mean:.4f})")
    else:
        print(f"FAIL (t={t_stat:.2f}, IC={ic_mean:.4f})")

    return {
        "name": name,
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "ic_ir": ic_ir,
        "t_stat": t_stat,
        "pct_pos": pct_pos,
        "n_months": len(ic_df),
    }


def compute_talib_factor_wide(
    codes: list[str],
    dates: np.ndarray,
    klines_grouped: dict,
    indicator_name: str,
    indicator_params: dict,
    normalize_by_close: bool = False,
) -> pd.DataFrame:
    """对全市场逐股计算TA-Lib指标，返回wide格式DataFrame。

    Args:
        codes: 股票代码列表
        dates: 交易日期数组
        klines_grouped: {code: DataFrame(trade_date, open, high, low, close, volume)}
        indicator_name: ta_wrapper指标名
        indicator_params: 指标参数
        normalize_by_close: 是否除以close归一化(用于ATR)

    Returns:
        DataFrame(index=trade_date, columns=code)
    """
    result = {}
    n_ok = 0
    n_fail = 0
    for code in codes:
        if code not in klines_grouped:
            continue
        gdf = klines_grouped[code]
        if len(gdf) < 30:
            continue
        try:
            prices = {
                "open": gdf["open_price"].values.astype(np.float64),
                "high": gdf["high_price"].values.astype(np.float64),
                "low": gdf["low_price"].values.astype(np.float64),
                "close": gdf["close_price"].values.astype(np.float64),
                "volume": gdf["volume"].values.astype(np.float64),
            }
            vals = calculate_indicator(indicator_name, prices, **indicator_params)
            if normalize_by_close:
                close_arr = prices["close"]
                vals = vals / np.where(close_arr > 0, close_arr, np.nan)
            s = pd.Series(vals, index=gdf["trade_date"].values, name=code)
            result[code] = s
            n_ok += 1
        except Exception:
            n_fail += 1
            continue

    print(f"  [{indicator_name}] OK: {n_ok}, fail: {n_fail}")
    wide = pd.DataFrame(result)
    # Reindex to common dates
    wide = wide.reindex(dates)
    return wide


def main():
    print_config_header()
    t0 = time.time()

    # ════════════════════════════════════════════════════════════════
    # SHARED DATA LOADING
    # ════════════════════════════════════════════════════════════════
    conn = psycopg2.connect(DB_URI)

    print("[DATA] Loading klines_daily (OHLCV + adj)...")
    klines = pd.read_sql(
        """
        SELECT code, trade_date,
               open::float  AS open_price,
               high::float  AS high_price,
               low::float   AS low_price,
               close::float AS close_price,
               close::float * adj_factor::float AS adj_close,
               volume::float AS volume,
               pct_change::float / 100 AS ret
        FROM klines_daily
        WHERE trade_date >= %s AND volume > 0
        ORDER BY code, trade_date
        """,
        conn,
        params=(DATA_START,),
    )
    print(f"  Rows: {len(klines):,}, codes: {klines['code'].nunique()}")

    print("[DATA] Loading CSI300 benchmark...")
    bench = pd.read_sql(
        """
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= %s
        ORDER BY trade_date
        """,
        conn,
        params=(DATA_START,),
    )

    # Existing factors for correlation
    print("[DATA] Loading existing factors for correlation...")
    existing_factors = pd.read_sql(
        """
        SELECT code, trade_date, factor_name, zscore::float AS value
        FROM factor_values
        WHERE factor_name IN ('volatility_20', 'ln_market_cap', 'momentum_20',
                              'turnover_mean_20', 'bp_ratio', 'reversal_20',
                              'idiosyncratic_volatility', 'dv_ttm')
          AND trade_date >= '2021-01-01'
        ORDER BY trade_date, code
        """,
        conn,
    )
    conn.close()
    print(f"  Existing factor rows: {len(existing_factors):,}")

    # ── Pivot adj_close for forward returns ──
    print("[DATA] Pivoting adj_close...")
    adj_close_wide = klines.pivot(index="trade_date", columns="code", values="adj_close")
    dates_all = adj_close_wide.index.sort_values()

    bench_close = bench.set_index("trade_date")["close"].reindex(dates_all)

    # ── Forward 20-day excess return ──
    print("[DATA] Computing 20-day forward excess return...")
    fwd_ret_20 = adj_close_wide.shift(-20) / adj_close_wide - 1
    bench_fwd_20 = bench_close.shift(-20) / bench_close - 1
    excess_fwd_20 = fwd_ret_20.sub(bench_fwd_20, axis=0)

    # ── Month-end dates ──
    dates_series = pd.Series(dates_all)
    dates_dt = pd.to_datetime(dates_series)
    month_ends = dates_series.groupby(dates_dt.dt.to_period("M")).last().values
    month_ends = [str(d) for d in month_ends]

    print(f"[DATA] {len(dates_all)} trading days, month-ends: {len(month_ends)}")

    # ── Group klines by code for per-stock TA-Lib ──
    print("[DATA] Grouping klines by code...")
    klines_grouped = {code: gdf for code, gdf in klines.groupby("code")}
    codes = sorted(klines_grouped.keys())
    print(f"  {len(codes)} codes grouped")

    print(f"[DATA] Total load time: {time.time()-t0:.1f}s\n")

    # ════════════════════════════════════════════════════════════════
    # FACTOR COMPUTATION via ta_wrapper
    # ════════════════════════════════════════════════════════════════
    results = []

    factor_defs = [
        {
            "name": "RSI_14",
            "formula": "RSI(close, 14)",
            "indicator": "RSI",
            "params": {"period": 14},
            "normalize_by_close": False,
        },
        {
            "name": "MACD_HIST_12_26_9",
            "formula": "MACD_histogram(close, 12, 26, 9)",
            "indicator": "MACD",
            "params": {"fastperiod": 12, "slowperiod": 26, "signalperiod": 9},
            "normalize_by_close": False,
        },
        {
            "name": "KDJ_K_9_3_3",
            "formula": "KDJ_K(high, low, close, 9, 3, 3)",
            "indicator": "KDJ",
            "params": {"fastk_period": 9, "slowk_period": 3, "slowd_period": 3, "output": "K"},
            "normalize_by_close": False,
        },
        {
            "name": "CCI_14",
            "formula": "CCI(high, low, close, 14)",
            "indicator": "CCI",
            "params": {"period": 14},
            "normalize_by_close": False,
        },
        {
            "name": "ATR_14_NORM",
            "formula": "ATR(high, low, close, 14) / close",
            "indicator": "ATR",
            "params": {"period": 14},
            "normalize_by_close": True,
        },
    ]

    factor_wides = {}

    for fdef in factor_defs:
        print(f"\n{'#'*70}")
        print(f"# {fdef['name']}")
        print(f"{'#'*70}")

        fwide = compute_talib_factor_wide(
            codes,
            dates_all,
            klines_grouped,
            fdef["indicator"],
            fdef["params"],
            normalize_by_close=fdef["normalize_by_close"],
        )
        factor_wides[fdef["name"]] = fwide

        # Test both directions
        ic_pos = compute_monthly_ic(fwide, excess_fwd_20, month_ends, direction=+1)
        ic_neg = compute_monthly_ic(fwide, excess_fwd_20, month_ends, direction=-1)

        mean_pos = ic_pos["ic"].mean() if len(ic_pos) > 0 else 0
        mean_neg = ic_neg["ic"].mean() if len(ic_neg) > 0 else 0

        if abs(mean_neg) >= abs(mean_pos):
            ic_best = ic_neg
            dir_label = f"-1 (high {fdef['name']} => underperform)"
        else:
            ic_best = ic_pos
            dir_label = f"+1 (high {fdef['name']} => outperform)"

        r = print_ic_report(
            fdef["name"],
            f"{fdef['formula']}, direction={dir_label}",
            ic_best,
        )
        if r:
            results.append(r)

    # ════════════════════════════════════════════════════════════════
    # CROSS-FACTOR CORRELATION CHECK
    # ════════════════════════════════════════════════════════════════
    print(f"\n{'#'*70}")
    print("# CROSS-FACTOR CORRELATION CHECK")
    print(f"{'#'*70}")

    # Normalize index to str
    new_factors = {}
    for k, v in factor_wides.items():
        nf = v.copy()
        nf.index = nf.index.astype(str)
        new_factors[k] = nf

    # Sample dates for correlation (every 6th month-end)
    sample_dates_corr = [month_ends[i] for i in range(0, len(month_ends), 6)][:10]

    # 1. New factors pairwise
    new_names = list(new_factors.keys())
    print("\n-- New TA-Lib Factors Pairwise Correlation (Spearman, avg) --")
    print(f"  {'':>20}", end="")
    for n in new_names:
        print(f" {n[:16]:>16}", end="")
    print()

    for i, n1 in enumerate(new_names):
        print(f"  {n1:>20}", end="")
        for j, n2 in enumerate(new_names):
            if j <= i:
                if i == j:
                    print(f" {'1.000':>16}", end="")
                else:
                    print(f" {'':>16}", end="")
                continue
            corrs = []
            for d in sample_dates_corr:
                d_str = str(d)
                if d_str in new_factors[n1].index and d_str in new_factors[n2].index:
                    f1 = new_factors[n1].loc[d_str].dropna()
                    f2 = new_factors[n2].loc[d_str].dropna()
                    common_codes = f1.index.intersection(f2.index)
                    if len(common_codes) > 100:
                        c, _ = stats.spearmanr(f1[common_codes].values, f2[common_codes].values)
                        corrs.append(c)
            avg_c = np.mean(corrs) if corrs else np.nan
            flag = " !" if abs(avg_c) > 0.5 else ""
            print(f" {avg_c:>15.4f}{flag}", end="")
        print()

    # 2. New factors vs existing passed factors
    if len(existing_factors) > 0:
        print("\n-- New TA-Lib Factors vs Existing Factors --")
        existing_pivots = {}
        for fname, fgrp in existing_factors.groupby("factor_name"):
            fp = fgrp.pivot(index="trade_date", columns="code", values="value")
            fp.index = fp.index.astype(str)
            existing_pivots[fname] = fp

        ex_names = sorted(existing_pivots.keys())
        print(f"  {'New \\ Existing':>20}", end="")
        for en in ex_names:
            print(f" {en[:16]:>16}", end="")
        print()

        for nn in new_names:
            print(f"  {nn:>20}", end="")
            for en in ex_names:
                corrs = []
                for d in sample_dates_corr:
                    d_str = str(d)
                    if d_str in new_factors[nn].index and d_str in existing_pivots[en].index:
                        f1 = new_factors[nn].loc[d_str].dropna()
                        f2 = existing_pivots[en].loc[d_str].dropna()
                        common_codes = f1.index.intersection(f2.index)
                        if len(common_codes) > 100:
                            c, _ = stats.spearmanr(
                                f1[common_codes].values, f2[common_codes].values
                            )
                            corrs.append(c)
                avg_c = np.mean(corrs) if corrs else np.nan
                flag = " !" if abs(avg_c) > 0.5 else ""
                print(f" {avg_c:>15.4f}{flag}", end="")
            print()

    # ════════════════════════════════════════════════════════════════
    # SUMMARY TABLE
    # ════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("TA-LIB FACTORS IC SUMMARY (5 factors, 20d fwd excess return)")
    print(f"{'='*80}")
    print(
        f"  {'Factor':<25} {'IC_Mean':>8} {'t-stat':>8} {'IC_IR':>8} "
        f"{'IC>0%':>6} {'Months':>6} {'Verdict':>10}"
    )
    print(f"  {'-'*73}")

    for r in results:
        verdict = (
            "PASS" if abs(r["t_stat"]) > 1.96 and abs(r["ic_mean"]) > 0.02 else
            "MARGINAL" if abs(r["t_stat"]) > 1.64 and abs(r["ic_mean"]) > 0.015 else
            "FAIL"
        )
        print(
            f"  {r['name']:<25} {r['ic_mean']:>8.4f} {r['t_stat']:>8.2f} "
            f"{r['ic_ir']:>8.4f} {r['pct_pos']:>5.1f}% {r['n_months']:>6} {verdict:>10}"
        )

    print(f"\nTotal time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
