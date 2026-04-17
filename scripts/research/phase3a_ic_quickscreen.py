#!/usr/bin/env python3
"""Phase 3A IC Quick-Screen: 对所有新入库因子做快速IC筛选。

方法:
  - 对每个因子，取最近3年数据(2023-2026)做快速IC评估
  - Spearman Rank IC, 20日前瞻超额收益(vs CSI300)
  - 输出: 按|IC|排序的因子列表 + CSV

用法:
  python scripts/research/phase3a_ic_quickscreen.py
  python scripts/research/phase3a_ic_quickscreen.py --all  # 全部因子（含已有的）
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

DB_CONN = "dbname=quantmind_v2 user=xin password=quantmind host=localhost"

# 已在CORE/PASS池中的因子 — 不需要重新筛
KNOWN_FACTORS = {
    "turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm",
    "amihud_20", "reversal_20", "RSQR_20", "QTLU_20",
    "IMAX_20", "IMIN_20", "CORD_20", "RESI_20",
    "a158_cord30", "a158_corr5", "a158_rank5", "a158_std60",
    "a158_vma5", "a158_vstd30", "a158_vsump5", "a158_vsump60",
}


def load_forward_returns(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """加载20日前瞻超额收益。"""
    print("  Loading price data for forward returns...")
    price = pd.read_sql("""
        SELECT code, trade_date, close FROM klines_daily
        WHERE trade_date >= %s AND trade_date <= %s AND volume > 0
        ORDER BY code, trade_date
    """, conn, params=(start_date, end_date))
    price["trade_date"] = pd.to_datetime(price["trade_date"])

    # CSI300 benchmark
    bench = pd.read_sql("""
        SELECT trade_date, close FROM index_daily
        WHERE index_code = '000300.SH' AND trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date
    """, conn, params=(start_date, end_date))
    bench["trade_date"] = pd.to_datetime(bench["trade_date"])
    bench = bench.set_index("trade_date")["close"]

    # 计算20日前瞻收益
    pivot = price.pivot(index="trade_date", columns="code", values="close")
    fwd_ret = pivot.shift(-20) / pivot - 1
    bench_fwd = bench.shift(-20) / bench - 1

    # 超额收益
    fwd_excess = fwd_ret.sub(bench_fwd, axis=0)

    # Melt回长格式
    fwd_long = fwd_excess.stack().reset_index()
    fwd_long.columns = ["trade_date", "code", "fwd_ret"]
    print(f"  Forward returns: {len(fwd_long):,} rows, {fwd_long['code'].nunique()} stocks")
    return fwd_long


def compute_ic_for_factor(factor_df: pd.DataFrame, fwd_df: pd.DataFrame) -> dict:
    """计算单个因子的IC统计。

    factor_df: code, trade_date, raw_value
    fwd_df: code, trade_date, fwd_ret
    """
    merged = pd.merge(factor_df, fwd_df, on=["code", "trade_date"], how="inner")
    if len(merged) < 1000:
        return {"ic_mean": np.nan, "ic_std": np.nan, "ic_ir": np.nan, "t_stat": np.nan, "n_obs": len(merged)}

    # 按日期计算截面IC
    ic_list = []
    for dt, grp in merged.groupby("trade_date"):
        if len(grp) < 30:
            continue
        ic, _ = stats.spearmanr(grp["raw_value"], grp["fwd_ret"])
        if not np.isnan(ic):
            ic_list.append(ic)

    if len(ic_list) < 10:
        return {"ic_mean": np.nan, "ic_std": np.nan, "ic_ir": np.nan, "t_stat": np.nan, "n_dates": len(ic_list)}

    ic_arr = np.array(ic_list)
    ic_mean = ic_arr.mean()
    ic_std = ic_arr.std()
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_arr))) if ic_std > 0 else 0

    return {
        "ic_mean": round(float(ic_mean), 6),
        "ic_std": round(float(ic_std), 6),
        "ic_ir": round(float(ic_ir), 4),
        "t_stat": round(float(t_stat), 4),
        "n_dates": len(ic_list),
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 3A IC Quick-Screen")
    parser.add_argument("--all", action="store_true", help="Screen ALL factors including known ones")
    parser.add_argument("--start", type=str, default="2023-01-01", help="IC计算起始日")
    parser.add_argument("--end", type=str, default="2026-04-01", help="IC计算结束日")
    parser.add_argument("--sample-dates", type=int, default=20, help="每N个交易日采样一次(加速)")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_CONN)
    t_total = time.time()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    print("=" * 70)
    print(f"  Phase 3A IC Quick-Screen ({start_date} ~ {end_date})")
    print(f"  Sampling: every {args.sample_dates} trading days")
    print("=" * 70)

    # Step 1: 获取所有因子名
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT factor_name FROM factor_values")
    all_factors = sorted([r[0] for r in cur.fetchall()])
    print(f"\n  Total factors in DB: {len(all_factors)}")

    if not args.all:
        factors_to_screen = [f for f in all_factors if f not in KNOWN_FACTORS]
        print(f"  New factors to screen: {len(factors_to_screen)}")
    else:
        factors_to_screen = all_factors
        print(f"  Screening ALL {len(factors_to_screen)} factors")

    # Step 2: 加载前瞻收益
    fwd_df = load_forward_returns(conn, start_date, end_date)

    # Step 3: 采样交易日(加速)
    all_dates = sorted(fwd_df["trade_date"].unique())
    sampled_dates = all_dates[::args.sample_dates]
    fwd_df = fwd_df[fwd_df["trade_date"].isin(sampled_dates)]
    print(f"  Sampled dates: {len(sampled_dates)} (from {len(all_dates)})")

    # Step 4: 逐因子计算IC
    results = []
    for i, fname in enumerate(factors_to_screen):
        t0 = time.time()
        try:
            # 加载因子数据（只取采样日期）
            dates_str = ",".join(f"'{d.strftime('%Y-%m-%d')}'" for d in sampled_dates)
            factor_df = pd.read_sql(f"""
                SELECT code, trade_date, raw_value
                FROM factor_values
                WHERE factor_name = %s
                  AND trade_date IN ({dates_str})
                  AND raw_value IS NOT NULL
            """, conn, params=(fname,))

            if factor_df.empty:
                results.append({"factor_name": fname, "ic_mean": np.nan, "note": "no data"})
                continue

            factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"])
            factor_df["raw_value"] = factor_df["raw_value"].astype(float)

            # 铁律29验证: 过滤NaN/Inf
            valid = factor_df["raw_value"].notna() & np.isfinite(factor_df["raw_value"])
            factor_df = factor_df[valid]

            ic_result = compute_ic_for_factor(factor_df, fwd_df)
            ic_result["factor_name"] = fname
            results.append(ic_result)

            elapsed = time.time() - t0
            ic_str = f"IC={ic_result['ic_mean']:+.4f}" if not np.isnan(ic_result.get("ic_mean", np.nan)) else "IC=N/A"
            if (i + 1) % 10 == 0 or i == 0:
                print(f"  [{i+1:>3}/{len(factors_to_screen)}] {fname:>15s}: {ic_str} ({elapsed:.1f}s)")

        except Exception as e:
            results.append({"factor_name": fname, "ic_mean": np.nan, "note": str(e)[:50]})
            if (i + 1) % 10 == 0:
                print(f"  [{i+1:>3}/{len(factors_to_screen)}] {fname:>15s}: ERROR - {e}")

    # Step 5: 汇总
    df = pd.DataFrame(results)
    df["abs_ic"] = df["ic_mean"].abs()
    df = df.sort_values("abs_ic", ascending=False)

    # 保存CSV
    out_path = Path("cache/phase3a_ic_quickscreen.csv")
    out_path.parent.mkdir(exist_ok=True)
    df.to_csv(out_path, index=False)

    # 输出
    total_elapsed = time.time() - t_total
    print("\n" + "=" * 70)
    print(f"  IC Quick-Screen完成 ({total_elapsed:.0f}s)")
    print("=" * 70)

    # Top因子
    valid_df = df[df["ic_mean"].notna()].copy()
    print(f"\n  有效因子: {len(valid_df)}/{len(df)}")

    print("\n── Top 30 by |IC| ──")
    print(f"  {'Factor':>25s} | {'IC_mean':>8s} | {'IC_IR':>7s} | {'t_stat':>7s} | {'n_dates':>7s}")
    print(f"  {'-'*25}-+-{'-'*8}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}")
    for _, r in valid_df.head(30).iterrows():
        print(f"  {r['factor_name']:>25s} | {r['ic_mean']:>+8.4f} | {r.get('ic_ir', 0):>7.3f} | {r.get('t_stat', 0):>7.2f} | {r.get('n_dates', 0):>7.0f}")

    # t > 2.5 count (Harvey Liu Zhu threshold)
    sig_count = len(valid_df[valid_df["t_stat"].abs() > 2.5])
    print(f"\n  t > 2.5 (significant): {sig_count}/{len(valid_df)} factors")

    # 分类统计
    print("\n── 分类统计 ──")
    for prefix, label in [("K", "KBAR"), ("ROC", "ROC"), ("MA", "MA"), ("STD", "STD"),
                           ("CORR", "CORR"), ("CORD", "CORD"), ("BETA", "BETA"),
                           ("RSQR", "RSQR"), ("VMA", "VMA"), ("QTLU", "QTLU"),
                           ("SUMP", "SUMP"), ("CNTP", "CNTP"), ("MIN", "MIN"),
                           ("MAX", "MAX"), ("IMAX", "IMAX"), ("IMIN", "IMIN")]:
        sub = valid_df[valid_df["factor_name"].str.startswith(prefix)]
        if not sub.empty:
            best = sub.iloc[0]
            print(f"  {label:>6s}: {len(sub)} factors, best={best['factor_name']} IC={best['ic_mean']:+.4f}")

    print(f"\n  Output: {out_path}")
    conn.close()


if __name__ == "__main__":
    main()
