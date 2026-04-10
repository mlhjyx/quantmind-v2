"""Task 2.7: Localized IC Analysis (CORE 5 x 3 Market Cap Groups)

READ-ONLY research script. Does not modify any production data.

Morgan Stanley quant: "Localize research - reconstruct factors for different stock categories."
"""

import sys

sys.path.insert(0, "backend")

import warnings

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats as scipy_stats

warnings.filterwarnings("ignore")

CORE_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
CAP_GROUPS = ["small", "mid", "large"]
HORIZON = 20
MIN_CROSS = 30


def main():
    print("=" * 80)
    print("TASK 2.7: Localized IC Analysis (CORE 5 x 3 Market Cap Groups)")
    print("=" * 80)

    # 1. Load factor_values
    print("\n[1/6] Loading factor_values from DB...")
    conn = psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )
    factor_df = pd.read_sql(
        """
        SELECT code, trade_date, factor_name, raw_value
        FROM factor_values
        WHERE factor_name IN ('turnover_mean_20','volatility_20','reversal_20','amihud_20','bp_ratio')
        AND trade_date BETWEEN '2023-01-01' AND '2025-12-31'
        """,
        conn,
    )
    print(f"  factor_values: {len(factor_df):,} rows, {factor_df['factor_name'].nunique()} factors")

    # 2. Load daily_basic total_mv
    print("[2/6] Loading daily_basic total_mv...")
    mv_df = pd.read_sql(
        """
        SELECT code, trade_date, total_mv
        FROM daily_basic
        WHERE trade_date BETWEEN '2023-01-01' AND '2025-12-31'
        AND total_mv IS NOT NULL
        """,
        conn,
    )
    print(f"  daily_basic: {len(mv_df):,} rows")

    # 3. Load CSI300 benchmark
    print("[3/6] Loading CSI300 benchmark...")
    bench_df = pd.read_sql(
        """
        SELECT trade_date, close
        FROM index_daily
        WHERE index_code = '000300.SH'
        AND trade_date BETWEEN '2022-12-01' AND '2026-06-30'
        ORDER BY trade_date
        """,
        conn,
    )
    print(f"  CSI300: {len(bench_df)} rows")
    conn.close()

    # 4. Load price_data from Parquet
    print("[4/6] Loading price_data from Parquet cache...")
    price_frames = []
    for year in [2023, 2024, 2025]:
        df = pd.read_parquet(f"cache/backtest/{year}/price_data.parquet")
        df = df[
            ~df["is_st"].astype(bool) & ~df["is_suspended"].astype(bool) & (df["board"] != "bse")
        ]
        price_frames.append(df[["code", "trade_date", "adj_close"]])
    price_df = pd.concat(price_frames, ignore_index=True)
    print(f"  price_data: {len(price_df):,} rows (after ST/suspended/BJ filter)")

    # 5. Assign market cap groups
    # NOTE: total_mv in DB is in YUAN (元), not 万元 as documented
    # Maotai = 1.77e12 yuan = 1.77万亿, p50 = 5.76e9 = 57.6亿
    # Thresholds: small < 50亿(5e9), mid 50-200亿(5e9-2e10), large >= 200亿(2e10)
    print("[5/6] Assigning market cap groups...")
    mv_df["cap_group"] = pd.cut(
        mv_df["total_mv"].astype(float),
        bins=[0, 5e9, 2e10, float("inf")],
        labels=["small", "mid", "large"],
    )
    mv_df["trade_date"] = pd.to_datetime(mv_df["trade_date"])

    cap_counts = mv_df.groupby("cap_group")["code"].nunique()
    for cg in CAP_GROUPS:
        print(f"  {cg}: {cap_counts.get(cg, 0)} unique stocks")

    # Per-date average counts
    date_counts = mv_df.groupby(["trade_date", "cap_group"]).size().unstack(fill_value=0)
    print(
        f"  Avg stocks per date: small={date_counts['small'].mean():.0f}, mid={date_counts['mid'].mean():.0f}, large={date_counts['large'].mean():.0f}"
    )

    # 6. Compute IC
    print("[6/6] Computing localized IC (15 combinations)...")

    # Ensure datetime
    factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"])
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
    bench_df["trade_date"] = pd.to_datetime(bench_df["trade_date"])

    # Build forward excess returns
    price_wide = price_df.pivot_table(
        index="trade_date", columns="code", values="adj_close", aggfunc="last"
    ).sort_index()
    bench_series = bench_df.set_index("trade_date")["close"].sort_index().astype(float)

    entry = price_wide.shift(-1)
    exit_p = price_wide.shift(-HORIZON)
    stock_ret = exit_p / entry - 1

    bench_entry = bench_series.shift(-1)
    bench_exit = bench_series.shift(-HORIZON)
    bench_ret = bench_exit / bench_entry - 1

    fwd_excess = stock_ret.sub(bench_ret, axis=0)
    print(f"  Forward excess returns shape: {fwd_excess.shape}")

    results = []

    for fname in CORE_FACTORS:
        fdata = factor_df[factor_df["factor_name"] == fname][
            ["code", "trade_date", "raw_value"]
        ].copy()
        fdata = fdata.merge(
            mv_df[["code", "trade_date", "cap_group"]],
            on=["code", "trade_date"],
            how="inner",
        )

        for cg in CAP_GROUPS:
            group_data = fdata[fdata["cap_group"] == cg]

            fac_wide = group_data.pivot_table(
                index="trade_date", columns="code", values="raw_value", aggfunc="first"
            ).sort_index()

            common_dates = fac_wide.index.intersection(fwd_excess.index)
            common_codes = fac_wide.columns.intersection(fwd_excess.columns)

            if len(common_codes) < MIN_CROSS:
                results.append(
                    {
                        "factor": fname,
                        "cap_group": cg,
                        "ic_mean": np.nan,
                        "ic_std": np.nan,
                        "ir": np.nan,
                        "t_stat": np.nan,
                        "hit_rate": np.nan,
                        "n_days": 0,
                        "n_stocks_avg": 0,
                    }
                )
                continue

            fac_slice = fac_wide.loc[common_dates, common_codes]
            ret_slice = fwd_excess.loc[common_dates, common_codes]

            ic_list = []
            for td in common_dates:
                f_row = fac_slice.loc[td].dropna()
                r_row = ret_slice.loc[td].dropna()
                common = f_row.index.intersection(r_row.index)
                if len(common) < MIN_CROSS:
                    continue
                corr, _ = scipy_stats.spearmanr(f_row[common].values, r_row[common].values)
                if not np.isnan(corr):
                    ic_list.append(corr)

            if len(ic_list) < 10:
                results.append(
                    {
                        "factor": fname,
                        "cap_group": cg,
                        "ic_mean": np.nan,
                        "ic_std": np.nan,
                        "ir": np.nan,
                        "t_stat": np.nan,
                        "hit_rate": np.nan,
                        "n_days": len(ic_list),
                        "n_stocks_avg": 0,
                    }
                )
                continue

            ic_arr = np.array(ic_list)
            mean_ic = ic_arr.mean()
            std_ic = ic_arr.std(ddof=1)
            ir = mean_ic / std_ic if std_ic > 0 else 0
            t_stat = ir * np.sqrt(len(ic_arr))
            hit_rate = (ic_arr > 0).sum() / len(ic_arr)
            n_stocks_avg = int(fac_slice.notna().sum(axis=1).mean())

            results.append(
                {
                    "factor": fname,
                    "cap_group": cg,
                    "ic_mean": round(mean_ic, 4),
                    "ic_std": round(std_ic, 4),
                    "ir": round(ir, 4),
                    "t_stat": round(t_stat, 2),
                    "hit_rate": round(hit_rate, 4),
                    "n_days": len(ic_arr),
                    "n_stocks_avg": n_stocks_avg,
                }
            )
        print(f"  {fname} done")

    # ============================================================
    # OUTPUT
    # ============================================================
    res_df = pd.DataFrame(results)

    print()
    print("=" * 110)
    print("RESULTS: Localized IC (CORE 5 x 3 Market Cap Groups, horizon=20d, 2023-2025)")
    print("Using raw_value (not neutralized) to preserve size-related signal differences")
    print("=" * 110)
    print()

    header = (
        f"{'Factor':<22} | {'Small (<50B)':>14} | {'Mid (50-200B)':>14} | "
        f"{'Large (>200B)':>14} | {'Small t':>8} | {'Mid t':>8} | {'Large t':>8}"
    )
    print(header)
    print("-" * 110)

    for fname in CORE_FACTORS:
        row_data = {}
        for cg in CAP_GROUPS:
            match = res_df[(res_df["factor"] == fname) & (res_df["cap_group"] == cg)]
            if len(match) > 0:
                r = match.iloc[0]
                row_data[cg] = (r["ic_mean"], r["t_stat"])
            else:
                row_data[cg] = (np.nan, np.nan)

        s_ic, s_t = row_data["small"]
        m_ic, m_t = row_data["mid"]
        l_ic, l_t = row_data["large"]

        print(
            f"{fname:<22} | {s_ic:>14.4f} | {m_ic:>14.4f} | {l_ic:>14.4f} | "
            f"{s_t:>8.2f} | {m_t:>8.2f} | {l_t:>8.2f}"
        )

    print()
    print("Detailed stats:")
    print(res_df.to_string(index=False))

    print()
    print("--- Small/Large IC Ratio Analysis ---")
    for fname in CORE_FACTORS:
        s = res_df[(res_df["factor"] == fname) & (res_df["cap_group"] == "small")]
        l = res_df[(res_df["factor"] == fname) & (res_df["cap_group"] == "large")]
        if len(s) == 0 or len(l) == 0:
            continue
        s_ic = abs(s.iloc[0]["ic_mean"]) if not pd.isna(s.iloc[0]["ic_mean"]) else 0
        l_ic = abs(l.iloc[0]["ic_mean"]) if not pd.isna(l.iloc[0]["ic_mean"]) else 0
        ratio = s_ic / l_ic if l_ic > 0 else float("inf")
        direction = (
            "small >> large"
            if ratio > 1.5
            else ("large >> small" if ratio < 0.67 else "comparable")
        )
        print(
            f"  {fname}: |small IC|={s_ic:.4f}, |large IC|={l_ic:.4f}, ratio={ratio:.2f}x -> {direction}"
        )

    print()
    print("--- Conclusion ---")
    ratios = []
    for fname in CORE_FACTORS:
        s = res_df[(res_df["factor"] == fname) & (res_df["cap_group"] == "small")]
        l = res_df[(res_df["factor"] == fname) & (res_df["cap_group"] == "large")]
        if len(s) > 0 and len(l) > 0:
            s_ic = abs(s.iloc[0]["ic_mean"]) if not pd.isna(s.iloc[0]["ic_mean"]) else 0
            l_ic = abs(l.iloc[0]["ic_mean"]) if not pd.isna(l.iloc[0]["ic_mean"]) else 0
            if l_ic > 0:
                ratios.append(s_ic / l_ic)
    if ratios:
        avg_ratio = np.mean(ratios)
        if avg_ratio > 1.5:
            print(
                f"  AVG |small IC|/|large IC| = {avg_ratio:.2f}x -> V4 grouped modeling HAS VALUE"
            )
            print("  Recommendation: Build separate signal models for small/mid/large cap stocks")
        elif avg_ratio > 1.2:
            print(f"  AVG |small IC|/|large IC| = {avg_ratio:.2f}x -> MODERATE differentiation")
            print("  Recommendation: Consider cap-group interaction features in ML model")
        else:
            print(
                f"  AVG |small IC|/|large IC| = {avg_ratio:.2f}x -> IC relatively uniform across cap groups"
            )
            print("  Recommendation: Grouped modeling may not add significant value")


if __name__ == "__main__":
    main()
