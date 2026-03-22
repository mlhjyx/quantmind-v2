#!/usr/bin/env python3
"""候选4多因子升级评估: 大盘低波从单因子升级为2-3因子组合。

当前候选4: 大盘(top 30%市值) + volatility_20排序 → Top10

评估在大盘股宇宙内(total_mv前30%)，以下因子/组合的IC:
1. volatility_20 (基线)
2. dv_ttm (高股息)
3. amihud_20 (流动性)
4. turnover_surge_ratio (换手突变)
5. relative_volume_20 (异常成交量)
6. 各两因子等权合成

用法:
    cd /Users/xin/Documents/quantmind-v2 && python scripts/evaluate_candidate4_multifactor.py
"""

import sys
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

warnings.filterwarnings("ignore")

DB_URI = "postgresql://quantmind:quantmind@localhost:5432/quantmind_v2"


def get_month_end_dates(conn, start: str = "2021-01-01", end: str = "2025-12-31") -> list:
    """获取每月最后一个交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (DATE_TRUNC('month', trade_date))
                  trade_date
           FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date >= %s AND trade_date <= %s
           ORDER BY DATE_TRUNC('month', trade_date) DESC, trade_date DESC""",
        (start, end),
    )
    return sorted([r[0] for r in cur.fetchall()])


def load_large_cap_universe(conn, trade_dates: list) -> dict[date, set]:
    """每个截面日，取total_mv前30%的股票集合。"""
    universe = {}
    for td in trade_dates:
        df = pd.read_sql(
            """SELECT code, total_mv::float
               FROM daily_basic
               WHERE trade_date = %s AND total_mv IS NOT NULL AND total_mv > 0""",
            conn, params=(td,),
        )
        if df.empty:
            continue
        threshold = df["total_mv"].quantile(0.70)  # top 30% = 70th percentile
        large = set(df[df["total_mv"] >= threshold]["code"].tolist())
        universe[td] = large
    return universe


def load_forward_excess_returns(conn, trade_dates: list, horizon: int = 20) -> pd.DataFrame:
    """加载forward excess return (超额CSI300)。返回 DataFrame[trade_date x code]。"""
    min_date = min(trade_dates) - timedelta(days=5)
    max_date = max(trade_dates) + timedelta(days=horizon * 3)

    prices = pd.read_sql(
        """SELECT code, trade_date, close::float * COALESCE(adj_factor::float, 1) AS adj_close
           FROM klines_daily
           WHERE trade_date >= %s AND trade_date <= %s AND volume > 0""",
        conn, params=(min_date, max_date),
    )
    prices_wide = prices.pivot(index="trade_date", columns="code", values="adj_close")

    bench = pd.read_sql(
        """SELECT trade_date, close::float
           FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date >= %s AND trade_date <= %s""",
        conn, params=(min_date, max_date),
    )
    bench = bench.set_index("trade_date")["close"]

    all_dates = sorted(prices_wide.index)
    results = []
    for td in trade_dates:
        if td not in prices_wide.index:
            continue
        future = [d for d in all_dates if d > td]
        if len(future) < horizon:
            continue
        fwd_date = future[horizon - 1]
        stock_ret = prices_wide.loc[fwd_date] / prices_wide.loc[td] - 1
        bench_ret = (bench.loc[fwd_date] / bench.loc[td] - 1) if (td in bench.index and fwd_date in bench.index) else 0
        excess = stock_ret - bench_ret
        excess.name = td
        results.append(excess)

    return pd.DataFrame(results) if results else pd.DataFrame()


def load_volatility_20(conn, trade_dates: list) -> dict[date, pd.Series]:
    """从factor_values加载volatility_20。"""
    df = pd.read_sql(
        """SELECT code, trade_date, zscore::float AS value
           FROM factor_values
           WHERE factor_name = 'volatility_20' AND trade_date IN %s""",
        conn, params=(tuple(trade_dates),),
    )
    result = {}
    for td, grp in df.groupby("trade_date"):
        result[td] = grp.set_index("code")["value"]
    return result


def load_dv_ttm(conn, trade_dates: list) -> dict[date, pd.Series]:
    """从daily_basic加载dv_ttm。"""
    result = {}
    for td in trade_dates:
        df = pd.read_sql(
            """SELECT code, dv_ttm::float
               FROM daily_basic
               WHERE trade_date = %s AND dv_ttm IS NOT NULL AND dv_ttm > 0""",
            conn, params=(td,),
        )
        if not df.empty:
            result[td] = df.set_index("code")["dv_ttm"]
    return result


def compute_amihud_20(conn, trade_dates: list) -> dict[date, pd.Series]:
    """计算Amihud非流动性: mean(|ret| / amount, 20d)。

    amount单位: 千元 (klines_daily)。
    """
    min_date = min(trade_dates) - timedelta(days=60)
    max_date = max(trade_dates)

    df = pd.read_sql(
        """SELECT code, trade_date,
                  close::float * COALESCE(adj_factor::float, 1) AS adj_close,
                  amount::float AS amount
           FROM klines_daily
           WHERE trade_date >= %s AND trade_date <= %s AND volume > 0 AND amount > 0""",
        conn, params=(min_date, max_date),
    )

    close_wide = df.pivot(index="trade_date", columns="code", values="adj_close")
    amount_wide = df.pivot(index="trade_date", columns="code", values="amount")

    daily_ret = close_wide.pct_change().abs()
    # Amihud = |ret| / amount (千元)
    illiq = daily_ret / amount_wide
    illiq = illiq.replace([np.inf, -np.inf], np.nan)

    amihud_20 = illiq.rolling(window=20, min_periods=10).mean()

    result = {}
    for td in trade_dates:
        if td in amihud_20.index:
            s = amihud_20.loc[td].dropna()
            if len(s) > 0:
                result[td] = s
    return result


def compute_turnover_surge(conn, trade_dates: list) -> dict[date, pd.Series]:
    """计算换手突变: mean(turnover, 5d) / mean(turnover, 20d)。"""
    min_date = min(trade_dates) - timedelta(days=60)
    max_date = max(trade_dates)

    df = pd.read_sql(
        """SELECT code, trade_date, turnover_rate::float
           FROM daily_basic
           WHERE trade_date >= %s AND trade_date <= %s
             AND turnover_rate IS NOT NULL AND turnover_rate > 0""",
        conn, params=(min_date, max_date),
    )

    turn_wide = df.pivot(index="trade_date", columns="code", values="turnover_rate")
    ma5 = turn_wide.rolling(window=5, min_periods=3).mean()
    ma20 = turn_wide.rolling(window=20, min_periods=10).mean()
    surge = ma5 / ma20
    surge = surge.replace([np.inf, -np.inf], np.nan).clip(0.1, 5.0)

    result = {}
    for td in trade_dates:
        if td in surge.index:
            s = surge.loc[td].dropna()
            if len(s) > 0:
                result[td] = s
    return result


def compute_relative_volume_20(conn, trade_dates: list) -> dict[date, pd.Series]:
    """计算异常成交量: volume_today / mean(volume, 20d)。"""
    min_date = min(trade_dates) - timedelta(days=60)
    max_date = max(trade_dates)

    df = pd.read_sql(
        """SELECT code, trade_date, volume::float
           FROM klines_daily
           WHERE trade_date >= %s AND trade_date <= %s AND volume > 0""",
        conn, params=(min_date, max_date),
    )

    vol_wide = df.pivot(index="trade_date", columns="code", values="volume")
    ma20 = vol_wide.rolling(window=20, min_periods=10).mean()
    rel_vol = vol_wide / ma20
    rel_vol = rel_vol.replace([np.inf, -np.inf], np.nan).clip(0.05, 20.0)

    result = {}
    for td in trade_dates:
        if td in rel_vol.index:
            s = rel_vol.loc[td].dropna()
            if len(s) > 0:
                result[td] = s
    return result


def cs_zscore(s: pd.Series) -> pd.Series:
    """截面zscore标准化（去极值后）。"""
    median = s.median()
    mad = (s - median).abs().median()
    upper = median + 5 * 1.4826 * mad
    lower = median - 5 * 1.4826 * mad
    clipped = s.clip(lower, upper)
    mean = clipped.mean()
    std = clipped.std()
    if std < 1e-10:
        return clipped * 0
    return (clipped - mean) / std


def calc_ic(factor: pd.Series, fwd_ret: pd.Series, min_count: int = 30) -> float:
    """截面Spearman IC。"""
    common = factor.dropna().index.intersection(fwd_ret.dropna().index)
    if len(common) < min_count:
        return np.nan
    ic, _ = stats.spearmanr(factor[common], fwd_ret[common])
    return ic if np.isfinite(ic) else np.nan


def main() -> None:
    t0 = time.time()
    conn = psycopg2.connect(DB_URI)

    # 1. 分析日期
    trade_dates = get_month_end_dates(conn)
    print(f"分析期间: {trade_dates[0]} ~ {trade_dates[-1]}, {len(trade_dates)}个月")

    # 2. 大盘股宇宙
    print("\n加载大盘股宇宙 (top 30% total_mv)...")
    universe = load_large_cap_universe(conn, trade_dates)
    avg_n = np.mean([len(v) for v in universe.values()])
    print(f"  平均每期大盘股数量: {avg_n:.0f}")

    # 3. Forward returns
    print("\n加载Forward Excess Returns (20日)...")
    fwd_rets = load_forward_excess_returns(conn, trade_dates, horizon=20)
    print(f"  Forward returns: {fwd_rets.shape}")

    # 4. 加载/计算各因子
    print("\n加载因子数据...")

    print("  volatility_20 (from factor_values)...")
    vol_20 = load_volatility_20(conn, trade_dates)
    print(f"    {len(vol_20)}个月")

    print("  dv_ttm (from daily_basic)...")
    dv_ttm = load_dv_ttm(conn, trade_dates)
    print(f"    {len(dv_ttm)}个月")

    print("  amihud_20 (计算中)...")
    amihud = compute_amihud_20(conn, trade_dates)
    print(f"    {len(amihud)}个月")

    print("  turnover_surge_ratio (计算中)...")
    surge = compute_turnover_surge(conn, trade_dates)
    print(f"    {len(surge)}个月")

    print("  relative_volume_20 (计算中)...")
    rel_vol = compute_relative_volume_20(conn, trade_dates)
    print(f"    {len(rel_vol)}个月")

    conn.close()

    # ======================================================================
    # 5. 大盘股内各因子单独IC
    # ======================================================================
    # 因子方向定义:
    #   volatility_20: -1 (低波好)
    #   dv_ttm: +1 (高股息好)
    #   amihud_20: +1 在大盘内 (更高非流动性=被低估? 存疑, 先测两个方向)
    #   turnover_surge: -1 (换手突变=追涨, 后续差)
    #   relative_volume: -1 (异常放量=过热)

    factor_configs = {
        "volatility_20": {"data": vol_20, "direction": -1, "desc": "低波"},
        "dv_ttm": {"data": dv_ttm, "direction": +1, "desc": "高股息"},
        "amihud_20": {"data": amihud, "direction": +1, "desc": "低流动性(高Amihud)"},
        "turnover_surge": {"data": surge, "direction": -1, "desc": "低换手突变"},
        "relative_volume_20": {"data": rel_vol, "direction": -1, "desc": "低异常成交量"},
    }

    print("\n" + "=" * 75)
    print("大盘股内(top 30%市值)各因子单独IC分析 (20日超额)")
    print("=" * 75)

    factor_ics: dict[str, list[float]] = {}
    factor_zscores_by_date: dict[str, dict[date, pd.Series]] = {}

    for fname, cfg in factor_configs.items():
        ics = []
        zscores_dict = {}
        direction = cfg["direction"]
        data = cfg["data"]

        for td in fwd_rets.index:
            if td not in universe or td not in data:
                continue
            large_set = universe[td]
            fr = fwd_rets.loc[td].dropna()

            # 限制到大盘股
            raw = data[td]
            large_factor = raw.reindex([c for c in raw.index if c in large_set]).dropna()
            if len(large_factor) < 30:
                continue

            # 截面zscore
            z = cs_zscore(large_factor) * direction
            zscores_dict[td] = z

            # IC (在大盘内)
            ic = calc_ic(z, fr, min_count=30)
            if not np.isnan(ic):
                ics.append(ic)

        factor_ics[fname] = ics
        factor_zscores_by_date[fname] = zscores_dict

        if ics:
            ic_mean = np.mean(ics)
            ic_std = np.std(ics)
            ic_ir = ic_mean / ic_std if ic_std > 0 else 0
            t_stat = ic_mean / (ic_std / np.sqrt(len(ics))) if ic_std > 0 else 0
            pct_pos = np.mean([1 for x in ics if x > 0]) / len(ics) * 100
            sig = "***" if abs(t_stat) > 2.58 else "**" if abs(t_stat) > 1.96 else "*" if abs(t_stat) > 1.64 else "ns"
            print(f"\n  {fname} ({cfg['desc']}, dir={direction:+d}):")
            print(f"    IC Mean: {ic_mean:+.4f}  Std: {ic_std:.4f}  IR: {ic_ir:.3f}")
            print(f"    t-stat:  {t_stat:.2f} {sig}   IC>0: {pct_pos:.0f}%   N_months: {len(ics)}")
        else:
            print(f"\n  {fname}: 数据不足")

    # ======================================================================
    # 6. 大盘股内因子间截面相关性
    # ======================================================================
    print("\n\n" + "=" * 75)
    print("大盘股内因子间截面Spearman相关性 (方向调整后)")
    print("=" * 75)

    factor_names = list(factor_configs.keys())
    corr_matrix = pd.DataFrame(np.nan, index=factor_names, columns=factor_names)

    for i, f1 in enumerate(factor_names):
        for j, f2 in enumerate(factor_names):
            if i >= j:
                continue
            z1_dict = factor_zscores_by_date.get(f1, {})
            z2_dict = factor_zscores_by_date.get(f2, {})
            corrs = []
            common_dates = set(z1_dict.keys()) & set(z2_dict.keys())
            for td in common_dates:
                z1 = z1_dict[td]
                z2 = z2_dict[td]
                common_codes = z1.dropna().index.intersection(z2.dropna().index)
                if len(common_codes) >= 30:
                    c, _ = stats.spearmanr(z1[common_codes], z2[common_codes])
                    if np.isfinite(c):
                        corrs.append(c)
            if corrs:
                corr_matrix.loc[f1, f2] = np.mean(corrs)
                corr_matrix.loc[f2, f1] = np.mean(corrs)

    for f in factor_names:
        corr_matrix.loc[f, f] = 1.0

    print(f"\n  {'':25s}", end="")
    for f in factor_names:
        print(f"{f[:12]:>13s}", end="")
    print()
    for f1 in factor_names:
        print(f"  {f1:25s}", end="")
        for f2 in factor_names:
            v = corr_matrix.loc[f1, f2]
            if np.isnan(v):
                print(f"{'--':>13s}", end="")
            else:
                print(f"{v:>13.3f}", end="")
        print()

    # ======================================================================
    # 7. 两因子等权合成IC
    # ======================================================================
    print("\n\n" + "=" * 75)
    print("两因子等权合成IC (大盘股内)")
    print("=" * 75)

    combo_results = []

    for i, f1 in enumerate(factor_names):
        for j, f2 in enumerate(factor_names):
            if i >= j:
                continue
            z1_dict = factor_zscores_by_date.get(f1, {})
            z2_dict = factor_zscores_by_date.get(f2, {})

            ics_combo = []
            common_dates = set(z1_dict.keys()) & set(z2_dict.keys()) & set(fwd_rets.index)
            for td in common_dates:
                z1 = z1_dict[td]
                z2 = z2_dict[td]
                fr = fwd_rets.loc[td].dropna()
                common_codes = z1.dropna().index.intersection(z2.dropna().index).intersection(fr.index)
                if len(common_codes) < 30:
                    continue
                composite = (z1[common_codes] + z2[common_codes]) / 2.0
                ic = calc_ic(composite, fr[common_codes], min_count=30)
                if not np.isnan(ic):
                    ics_combo.append(ic)

            if ics_combo:
                ic_mean = np.mean(ics_combo)
                ic_std = np.std(ics_combo)
                ic_ir = ic_mean / ic_std if ic_std > 0 else 0
                t_stat = ic_mean / (ic_std / np.sqrt(len(ics_combo))) if ic_std > 0 else 0
                combo_results.append({
                    "combo": f"{f1} + {f2}",
                    "ic_mean": ic_mean,
                    "ic_std": ic_std,
                    "ic_ir": ic_ir,
                    "t_stat": t_stat,
                    "n": len(ics_combo),
                })

    # 按IC_IR排序
    combo_results.sort(key=lambda x: x["ic_ir"], reverse=True)

    print(f"\n  {'Combination':<45s} {'IC_Mean':>8s} {'IC_Std':>8s} {'IC_IR':>8s} {'t-stat':>8s} {'N':>4s}")
    print(f"  {'-' * 85}")
    for r in combo_results:
        sig = "***" if abs(r["t_stat"]) > 2.58 else "**" if abs(r["t_stat"]) > 1.96 else "*" if abs(r["t_stat"]) > 1.64 else "ns"
        print(f"  {r['combo']:<45s} {r['ic_mean']:>+8.4f} {r['ic_std']:>8.4f} {r['ic_ir']:>8.3f} {r['t_stat']:>7.2f}{sig} {r['n']:>4d}")

    # ======================================================================
    # 8. 三因子等权合成IC (Top-3组合)
    # ======================================================================
    print("\n\n" + "=" * 75)
    print("三因子等权合成IC (大盘股内, 含volatility_20的组合)")
    print("=" * 75)

    triple_results = []
    # 只测包含vol_20的三因子组合
    other_factors = [f for f in factor_names if f != "volatility_20"]
    from itertools import combinations
    for f2, f3 in combinations(other_factors, 2):
        f1 = "volatility_20"
        z1_dict = factor_zscores_by_date.get(f1, {})
        z2_dict = factor_zscores_by_date.get(f2, {})
        z3_dict = factor_zscores_by_date.get(f3, {})

        ics_triple = []
        common_dates = set(z1_dict.keys()) & set(z2_dict.keys()) & set(z3_dict.keys()) & set(fwd_rets.index)
        for td in common_dates:
            z1 = z1_dict[td]
            z2 = z2_dict[td]
            z3 = z3_dict[td]
            fr = fwd_rets.loc[td].dropna()
            common_codes = (
                z1.dropna().index
                .intersection(z2.dropna().index)
                .intersection(z3.dropna().index)
                .intersection(fr.index)
            )
            if len(common_codes) < 30:
                continue
            composite = (z1[common_codes] + z2[common_codes] + z3[common_codes]) / 3.0
            ic = calc_ic(composite, fr[common_codes], min_count=30)
            if not np.isnan(ic):
                ics_triple.append(ic)

        if ics_triple:
            ic_mean = np.mean(ics_triple)
            ic_std = np.std(ics_triple)
            ic_ir = ic_mean / ic_std if ic_std > 0 else 0
            t_stat = ic_mean / (ic_std / np.sqrt(len(ics_triple))) if ic_std > 0 else 0
            triple_results.append({
                "combo": f"{f1} + {f2} + {f3}",
                "ic_mean": ic_mean,
                "ic_std": ic_std,
                "ic_ir": ic_ir,
                "t_stat": t_stat,
                "n": len(ics_triple),
            })

    triple_results.sort(key=lambda x: x["ic_ir"], reverse=True)

    print(f"\n  {'Combination':<60s} {'IC_Mean':>8s} {'IC_Std':>8s} {'IC_IR':>8s} {'t-stat':>8s} {'N':>4s}")
    print(f"  {'-' * 95}")
    for r in triple_results:
        sig = "***" if abs(r["t_stat"]) > 2.58 else "**" if abs(r["t_stat"]) > 1.96 else "*" if abs(r["t_stat"]) > 1.64 else "ns"
        print(f"  {r['combo']:<60s} {r['ic_mean']:>+8.4f} {r['ic_std']:>8.4f} {r['ic_ir']:>8.3f} {r['t_stat']:>7.2f}{sig} {r['n']:>4d}")

    # ======================================================================
    # 9. 年度拆解 (Top-2组合 vs 单因子基线)
    # ======================================================================
    if combo_results:
        best_combo = combo_results[0]
        best_pair = best_combo["combo"].split(" + ")
        print(f"\n\n{'=' * 75}")
        print(f"年度拆解: 最优两因子组合 [{best_combo['combo']}] vs 单因子vol_20")
        print(f"{'=' * 75}")

        # 按年计算IC
        vol_z = factor_zscores_by_date.get("volatility_20", {})
        f2_z = factor_zscores_by_date.get(best_pair[1] if best_pair[0] == "volatility_20" else best_pair[0], {})

        yearly_single = {}
        yearly_combo = {}

        for td in fwd_rets.index:
            if td not in vol_z:
                continue
            yr = td.year
            fr = fwd_rets.loc[td].dropna()

            # 单因子
            z1 = vol_z[td]
            common = z1.dropna().index.intersection(fr.index)
            if len(common) >= 30:
                ic = calc_ic(z1[common], fr[common], min_count=30)
                if not np.isnan(ic):
                    yearly_single.setdefault(yr, []).append(ic)

            # 两因子
            if td in f2_z:
                z2 = f2_z[td]
                common2 = z1.dropna().index.intersection(z2.dropna().index).intersection(fr.index)
                if len(common2) >= 30:
                    composite = (z1[common2] + z2[common2]) / 2.0
                    ic2 = calc_ic(composite, fr[common2], min_count=30)
                    if not np.isnan(ic2):
                        yearly_combo.setdefault(yr, []).append(ic2)

        print(f"\n  {'Year':<6s} {'vol_20 IC':>10s} {'combo IC':>10s} {'Delta':>8s}")
        print(f"  {'-' * 38}")
        for yr in sorted(set(list(yearly_single.keys()) + list(yearly_combo.keys()))):
            s_ic = np.mean(yearly_single.get(yr, [np.nan]))
            c_ic = np.mean(yearly_combo.get(yr, [np.nan]))
            delta = c_ic - s_ic if not (np.isnan(s_ic) or np.isnan(c_ic)) else np.nan
            s_str = f"{s_ic:+.4f}" if not np.isnan(s_ic) else "N/A"
            c_str = f"{c_ic:+.4f}" if not np.isnan(c_ic) else "N/A"
            d_str = f"{delta:+.4f}" if not np.isnan(delta) else "N/A"
            print(f"  {yr:<6d} {s_str:>10s} {c_str:>10s} {d_str:>8s}")

    # ======================================================================
    # 10. 结论与推荐
    # ======================================================================
    print(f"\n\n{'=' * 75}")
    print("结论与推荐")
    print(f"{'=' * 75}")

    # 单因子基线
    vol_ics = factor_ics.get("volatility_20", [])
    vol_ic_mean = np.mean(vol_ics) if vol_ics else np.nan
    print(f"\n  单因子基线 (volatility_20): IC = {vol_ic_mean:+.4f}")

    # 最优两因子
    if combo_results:
        best = combo_results[0]
        print(f"\n  最优两因子: {best['combo']}")
        print(f"    IC = {best['ic_mean']:+.4f}, IR = {best['ic_ir']:.3f}, t = {best['t_stat']:.2f}")
        improvement = best["ic_mean"] - vol_ic_mean if not np.isnan(vol_ic_mean) else np.nan
        if not np.isnan(improvement):
            print(f"    vs 单因子IC改善: {improvement:+.4f}")

    # 最优三因子
    if triple_results:
        best3 = triple_results[0]
        print(f"\n  最优三因子: {best3['combo']}")
        print(f"    IC = {best3['ic_mean']:+.4f}, IR = {best3['ic_ir']:.3f}, t = {best3['t_stat']:.2f}")

    # 推荐逻辑
    print(f"\n  推荐:")
    if combo_results:
        best = combo_results[0]
        # 检查是否显著优于单因子
        if best["ic_ir"] > 0.15 and abs(best["t_stat"]) > 1.64:
            print(f"    升级到两因子: {best['combo']}")
            print(f"    理由: IC_IR={best['ic_ir']:.3f}, 合成后IC稳定性提升")
            # 检查三因子是否更好
            if triple_results and triple_results[0]["ic_ir"] > best["ic_ir"] * 1.1:
                best3 = triple_results[0]
                print(f"    可考虑三因子: {best3['combo']} (IC_IR={best3['ic_ir']:.3f})")
            else:
                print(f"    三因子未带来显著提升, 建议维持两因子")
        else:
            print(f"    多因子合成未带来显著提升, 建议维持单因子vol_20")
            print(f"    最优合成IC_IR={best['ic_ir']:.3f}, t={best['t_stat']:.2f}")

    # 冗余因子提醒
    print(f"\n  冗余因子检查:")
    for i, f1 in enumerate(factor_names):
        for j, f2 in enumerate(factor_names):
            if i >= j:
                continue
            c = corr_matrix.loc[f1, f2]
            if not np.isnan(c) and abs(c) > 0.5:
                print(f"    WARNING: {f1} vs {f2} 相关性 {c:.3f} > 0.5, 组合可能冗余")

    elapsed = time.time() - t0
    print(f"\n总耗时: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
