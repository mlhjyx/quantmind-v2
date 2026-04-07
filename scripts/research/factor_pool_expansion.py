#!/usr/bin/env python3
"""因子池扩展实验: 5→10→15→20→33因子等权回测。

核心问题: 把等权因子从5个扩展到10-15个低相关因子，
MDD会不会改善？小盘集中度会不会降低？

方法:
  1. 从factor_ic_history筛选T1因子(|t|>2.5, 非北向)
  2. 按与CORE 5因子的平均相关性排序（低相关优先加入）
  3. 逐步扩展回测: 5→8→10→15→20→全部
  4. 评估Sharpe/MDD/Calmar/市值分布/选股重叠度

用法:
    python scripts/research/factor_pool_expansion.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import numpy as np
import pandas as pd

from app.services.price_utils import _get_sync_conn

# ── 配置 ─────────────────────────────────────────────
BT_START = date(2021, 1, 1)
BT_END = date(2025, 12, 31)
TOP_N = 20
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252

CORE_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]

# 已知方向（signal_engine.py FACTOR_DIRECTION + IC符号推断）
KNOWN_DIRECTIONS = {
    "momentum_5": 1, "momentum_10": 1, "momentum_20": 1,
    "reversal_5": 1, "reversal_10": 1, "reversal_20": 1, "reversal_60": 1,
    "volatility_20": -1, "volatility_60": -1,
    "volume_std_20": -1, "turnover_mean_20": -1, "turnover_std_20": -1,
    "amihud_20": 1, "bp_ratio": 1, "ep_ratio": 1, "dv_ttm": 1,
    "price_volume_corr_20": -1, "high_low_range_20": -1,
    "price_level_factor": -1, "relative_volume_20": -1,
    "turnover_surge_ratio": -1, "ln_market_cap": -1,
}

# 排除列表
EXCLUDE_FACTORS = {
    "ln_market_cap",     # 风险因子，不是alpha
    "mf_divergence",     # 已证伪 IC=-2.27%
    "beta_market_20",    # |t|=2.18 < 2.5阈值
}

# 市值分档阈值（亿元，daily_basic.total_mv单位=万元）
MV_BINS = [0, 50, 100, 300, float("inf")]  # 亿元
MV_LABELS = ["<50亿", "50-100亿", "100-300亿", ">300亿"]


# ═══════════════════════════════════════════════════════
# Step 1: 候选因子准备
# ═══════════════════════════════════════════════════════
def prepare_candidates(conn) -> pd.DataFrame:
    """从factor_ic_history筛选T1因子，计算与CORE的相关性。"""
    print("[Step 1] 候选因子准备...")
    cur = conn.cursor()

    # 获取所有因子IC统计
    cur.execute("""
        SELECT factor_name,
               AVG(ic_20d) as avg_ic,
               COUNT(*) as n,
               AVG(ic_20d) / (STDDEV(ic_20d) / SQRT(COUNT(*))) as t_stat
        FROM factor_ic_history
        WHERE factor_name NOT LIKE 'nb_%%'
          AND factor_name NOT LIKE 'sue_%%'
          AND factor_name NOT LIKE 'mkt_%%'
          AND ic_20d IS NOT NULL
        GROUP BY factor_name
        HAVING COUNT(*) >= 10
           AND ABS(AVG(ic_20d) / (STDDEV(ic_20d) / SQRT(COUNT(*)))) >= 2.5
        ORDER BY factor_name
    """)
    ic_rows = cur.fetchall()

    candidates = []
    for fname, avg_ic, n, t_stat in ic_rows:
        if fname in EXCLUDE_FACTORS:
            continue
        # 确认factor_values有数据
        if fname.startswith("nb_"):
            continue
        direction = KNOWN_DIRECTIONS.get(fname)
        if direction is None:
            # 从IC符号推断: IC负→选低的(direction=-1), IC正→选高的(direction=1)
            direction = 1 if float(avg_ic) > 0 else -1
        candidates.append({
            "factor_name": fname,
            "ic": float(avg_ic),
            "t_stat": float(t_stat),
            "direction": direction,
            "is_core": fname in CORE_FACTORS,
        })

    cand_df = pd.DataFrame(candidates)
    print(f"  T1候选因子: {len(cand_df)} (含{cand_df['is_core'].sum()}个CORE)")

    # 计算与CORE 5的截面相关性（月末抽样，避免全量计算）
    # 取10个月末日期做抽样
    cur.execute("""
        SELECT DISTINCT ON (EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date))
            trade_date
        FROM klines_daily
        WHERE trade_date >= '2023-01-01' AND trade_date <= '2025-12-31'
        ORDER BY EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date),
                 trade_date DESC
    """)
    sample_dates = sorted([r[0] for r in cur.fetchall()])
    # 取偶数月（约18个样本，足够估计相关性）
    sample_dates = sample_dates[::2][:12]
    print(f"  相关性抽样日期: {len(sample_dates)}个")

    # 加载样本日因子值
    all_factor_names = cand_df["factor_name"].tolist()
    sample_data = pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = ANY(%s) AND factor_name = ANY(%s)
             AND neutral_value IS NOT NULL""",
        conn,
        params=(sample_dates, all_factor_names),
    )
    print(f"  样本因子数据: {len(sample_data):,}行")

    # 计算每个因子与CORE 5的平均绝对相关性
    avg_corrs = {}
    for fname in all_factor_names:
        if fname in CORE_FACTORS:
            avg_corrs[fname] = 0.0  # CORE因子自身
            continue

        corrs_with_core = []
        for sd in sample_dates:
            sd_data = sample_data[sample_data["trade_date"] == sd]
            f_vals = sd_data[sd_data["factor_name"] == fname].set_index("code")["neutral_value"]
            for cf in CORE_FACTORS:
                cf_vals = sd_data[sd_data["factor_name"] == cf].set_index("code")["neutral_value"]
                common = f_vals.index.intersection(cf_vals.index)
                if len(common) > 50:
                    from scipy.stats import spearmanr
                    c, _ = spearmanr(f_vals[common], cf_vals[common])
                    if np.isfinite(c):
                        corrs_with_core.append(abs(c))

        avg_corrs[fname] = np.mean(corrs_with_core) if corrs_with_core else 1.0

    cand_df["avg_corr_core5"] = cand_df["factor_name"].map(avg_corrs)

    # 非CORE按相关性排序（低相关优先）
    core_df = cand_df[cand_df["is_core"]].copy()
    non_core_df = cand_df[~cand_df["is_core"]].sort_values("avg_corr_core5").copy()
    non_core_df["add_order"] = range(6, 6 + len(non_core_df))

    result = pd.concat([core_df, non_core_df], ignore_index=True)
    return result


# ═══════════════════════════════════════════════════════
# Step 2: 回测框架
# ═══════════════════════════════════════════════════════
def run_expansion_backtest(
    factor_list: list[str],
    directions: dict[str, int],
    factor_data: pd.DataFrame,
    price_pivot: pd.DataFrame,
    daily_ret: pd.DataFrame,
    mv_data: pd.DataFrame,
    rebal_dates: list,
    label: str,
) -> dict:
    """等权合成 → Top-20选股 → 月度调仓回测。"""
    # 月末选股
    all_dates = sorted(price_pivot.index)
    all_dates_ts = [pd.Timestamp(d) for d in all_dates]

    portfolio_returns = []
    monthly_holdings = {}  # {rebal_date: [codes]}
    monthly_turnover = []

    prev_codes = set()

    for i, rd in enumerate(rebal_dates):
        df = factor_data[factor_data["trade_date"] == rd]
        if df.empty:
            continue

        pivot = df[df["factor_name"].isin(factor_list)].pivot(
            index="code", columns="factor_name", values="neutral_value"
        )

        # 等权合成（乘方向）
        score = pd.Series(0.0, index=pivot.index)
        n_valid = pd.Series(0, index=pivot.index)
        for f in factor_list:
            if f in pivot.columns:
                vals = pivot[f].dropna()
                d = directions.get(f, 1)
                score[vals.index] += vals * d
                n_valid[vals.index] += 1

        # 只保留至少有一半因子有值的股票
        min_factors = max(len(factor_list) // 2, 1)
        valid_mask = n_valid >= min_factors
        score = score[valid_mask]
        if n_valid[valid_mask].max() > 0:
            score = score / n_valid[valid_mask]  # 归一化

        top_codes = score.dropna().sort_values(ascending=False).head(TOP_N).index.tolist()
        monthly_holdings[rd] = top_codes

        # 换手率
        new_codes = set(top_codes)
        if prev_codes:
            turnover = 1 - len(new_codes & prev_codes) / max(len(new_codes | prev_codes), 1)
            monthly_turnover.append(turnover)
        prev_codes = new_codes

        # 持有期日收益
        rd_ts = pd.Timestamp(rd)
        start_idx = next((j for j, d in enumerate(all_dates_ts) if d > rd_ts), None)
        if start_idx is None:
            continue

        if i + 1 < len(rebal_dates):
            next_rd = pd.Timestamp(rebal_dates[i + 1])
            end_idx = next((j for j, d in enumerate(all_dates_ts) if d > next_rd), len(all_dates_ts))
        else:
            end_idx = len(all_dates_ts)

        hold_dates = all_dates[start_idx:end_idx]
        valid_codes = [c for c in top_codes if c in daily_ret.columns]

        for d in hold_dates:
            rets = daily_ret.loc[d, valid_codes].dropna()
            if len(rets) > 0:
                portfolio_returns.append({"trade_date": d, "ret": rets.mean()})

    port_ret = pd.DataFrame(portfolio_returns).set_index("trade_date")["ret"].sort_index()
    port_ret = port_ret[~port_ret.index.duplicated(keep="first")]

    # 指标
    nav = (1 + port_ret).cumprod()
    n_years = len(port_ret) / 252
    cagr = (float(nav.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 else 0
    vol = float(port_ret.std() * np.sqrt(252))
    sharpe = (cagr - RF_ANNUAL) / vol if vol > 0 else 0
    mdd = float(((nav - nav.cummax()) / nav.cummax()).min())
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0
    avg_turnover = np.mean(monthly_turnover) if monthly_turnover else 0

    # 市值分布（取最近6个月的持仓做统计）
    mv_dist = {l: 0 for l in MV_LABELS}
    mv_median_list = []
    recent_dates = sorted(monthly_holdings.keys())[-6:]
    for rd in recent_dates:
        codes = monthly_holdings.get(rd, [])
        for code in codes:
            mv_row = mv_data[(mv_data["code"] == code) & (mv_data["trade_date"] == rd)]
            if not mv_row.empty:
                mv_val = float(mv_row.iloc[0]["total_mv"]) / 10000  # 万元→亿元
                mv_median_list.append(mv_val)
                for j in range(len(MV_BINS) - 1):
                    if MV_BINS[j] <= mv_val < MV_BINS[j + 1]:
                        mv_dist[MV_LABELS[j]] += 1
                        break

    total_mv_count = sum(mv_dist.values())
    mv_pct = {k: v / max(total_mv_count, 1) for k, v in mv_dist.items()}
    mv_median = np.median(mv_median_list) if mv_median_list else 0

    # 年度分解
    yearly = {}
    for year in range(BT_START.year, BT_END.year + 1):
        dates_year = pd.Series([d.year if hasattr(d, "year") else pd.Timestamp(d).year for d in port_ret.index], index=port_ret.index)
        mask = dates_year == year
        yr = port_ret[mask]
        if len(yr) < 20:
            continue
        yr_nav = (1 + yr).cumprod()
        yr_cagr = float(yr_nav.iloc[-1]) ** (252 / len(yr)) - 1
        yr_vol = float(yr.std() * np.sqrt(252))
        yr_sharpe = (yr_cagr - RF_ANNUAL) / yr_vol if yr_vol > 0 else 0
        yr_mdd = float(((yr_nav - yr_nav.cummax()) / yr_nav.cummax()).min())
        yearly[year] = (round(yr_sharpe, 2), round(yr_mdd * 100, 1))

    return {
        "label": label,
        "n_factors": len(factor_list),
        "cagr": cagr,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "avg_turnover": avg_turnover,
        "mv_median": mv_median,
        "mv_pct": mv_pct,
        "yearly": yearly,
        "holdings": monthly_holdings,
    }


# ═══════════════════════════════════════════════════════
# Step 3: 选股重叠度
# ═══════════════════════════════════════════════════════
def compute_overlap(holdings_a: dict, holdings_b: dict) -> float:
    """两个策略的平均月度选股重叠度。"""
    overlaps = []
    common_dates = set(holdings_a.keys()) & set(holdings_b.keys())
    for d in common_dates:
        a = set(holdings_a[d])
        b = set(holdings_b[d])
        if a and b:
            overlaps.append(len(a & b) / TOP_N)
    return np.mean(overlaps) if overlaps else 0


# ═══════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════
def print_report(candidates: pd.DataFrame, results: list[dict]) -> None:
    print("\n" + "═" * 95)
    print("  因子池扩展实验")
    print("═" * 95)

    # 候选因子表
    non_core = candidates[~candidates["is_core"]].head(30)
    print("\n  候选因子池（按与CORE相关性排序, 前20）:")
    print(f"  {'#':>3s}  {'因子':<30s}  {'IC':>8s}  {'t-stat':>8s}  {'corr_core5':>10s}  {'方向':>4s}")
    print(f"  {'─'*3}  {'─'*30}  {'─'*8}  {'─'*8}  {'─'*10}  {'─'*4}")
    for i, (_, r) in enumerate(non_core.head(20).iterrows()):
        print(
            f"  {i+6:>3d}  {r['factor_name']:<30s}  {r['ic']:>+8.4f}  "
            f"{r['t_stat']:>+8.1f}  {r['avg_corr_core5']:>10.3f}  {r['direction']:>+4d}"
        )

    # 回测结果表
    print("\n  回测结果:")
    print(
        f"  {'组':<6s}  {'因子数':>6s}  {'CAGR%':>7s}  {'Sharpe':>7s}  {'MDD%':>7s}  "
        f"{'Calmar':>7s}  {'换手率':>6s}  {'市值中位(亿)':>10s}  {'<100亿%':>8s}"
    )
    print(f"  {'─'*6}  {'─'*6}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*10}  {'─'*8}")

    for r in results:
        small_pct = r["mv_pct"].get("<50亿", 0) + r["mv_pct"].get("50-100亿", 0)
        print(
            f"  {r['label']:<6s}  {r['n_factors']:>6d}  {r['cagr']*100:>+7.1f}  "
            f"{r['sharpe']:>7.2f}  {r['mdd']*100:>+7.1f}  {r['calmar']:>7.2f}  "
            f"{r['avg_turnover']:>5.0f}%  {r['mv_median']:>10.0f}  {small_pct*100:>7.0f}%"
        )

    # 选股重叠度
    if len(results) >= 2:
        base_holdings = results[0]["holdings"]
        print("\n  选股重叠度 (vs 基线CORE 5因子):")
        for r in results[1:]:
            overlap = compute_overlap(base_holdings, r["holdings"])
            print(f"    {r['label']} ({r['n_factors']}因子) vs CORE: {overlap*100:.0f}%重叠")

    # 年度分解（基线 + 最优Calmar组）
    if results:
        best = max(results, key=lambda x: x["calmar"])
        base = results[0]
        print(f"\n  年度分解 (基线A vs 最优{best['label']}):")
        print(f"  {'年份':>6s}  {'A Sharpe':>9s}  {'A MDD%':>8s}  {best['label']+' Sharpe':>12s}  {best['label']+' MDD%':>10s}")
        for year in sorted(set(list(base["yearly"].keys()) + list(best["yearly"].keys()))):
            bs, bm = base["yearly"].get(year, (0, 0))
            ms, mm = best["yearly"].get(year, (0, 0))
            print(f"  {year:>6d}  {bs:>+9.2f}  {bm:>+8.1f}  {ms:>+12.2f}  {mm:>+10.1f}")

    # 结论
    print("\n  结论:")
    [(r["label"], r["n_factors"], r["sharpe"]) for r in results]
    [(r["label"], r["n_factors"], r["mdd"]) for r in results]
    max(results, key=lambda x: x["sharpe"])
    max(results, key=lambda x: x["mdd"])  # mdd is negative, max = least negative
    best_calmar = max(results, key=lambda x: x["calmar"])

    print("    Sharpe趋势: " + " → ".join(f"{r['n_factors']}f={r['sharpe']:.2f}" for r in results))
    print("    MDD趋势:    " + " → ".join(f"{r['n_factors']}f={r['mdd']*100:.1f}%" for r in results))

    base = results[0]
    if best_calmar["calmar"] > base["calmar"] * 1.1:
        print(f"    最优: {best_calmar['label']}({best_calmar['n_factors']}因子) Calmar={best_calmar['calmar']:.2f} vs 基线{base['calmar']:.2f}")
        small_pct = best_calmar["mv_pct"].get("<50亿", 0) + best_calmar["mv_pct"].get("50-100亿", 0)
        base_small = base["mv_pct"].get("<50亿", 0) + base["mv_pct"].get("50-100亿", 0)
        if small_pct < base_small - 0.05:
            print(f"    小盘集中度降低: {base_small*100:.0f}% → {small_pct*100:.0f}%")
        else:
            print(f"    小盘集中度未显著变化: {base_small*100:.0f}% → {small_pct*100:.0f}%")
    else:
        print("    扩展因子未显著改善Calmar")

    print(f"\n{'═' * 95}\n")


# ═══════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════
def main() -> None:
    conn = _get_sync_conn()

    # Step 1: 候选因子
    candidates = prepare_candidates(conn)

    # 定义组
    non_core = candidates[~candidates["is_core"]].sort_values("avg_corr_core5")
    non_core_names = non_core["factor_name"].tolist()

    groups = [
        ("A", CORE_FACTORS),
        ("B", CORE_FACTORS + non_core_names[:3]),
        ("C", CORE_FACTORS + non_core_names[:5]),
        ("D", CORE_FACTORS + non_core_names[:10]),
        ("E", CORE_FACTORS + non_core_names[:15]),
        ("F", CORE_FACTORS + non_core_names),  # 全部
    ]

    # 方向映射
    directions = {}
    for _, r in candidates.iterrows():
        directions[r["factor_name"]] = int(r["direction"])

    # 加载共享数据
    print("\n[Step 2] 加载共享数据...")

    # 月末调仓日
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date))
            trade_date
        FROM klines_daily
        WHERE trade_date >= %s AND trade_date <= %s
        ORDER BY EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date),
                 trade_date DESC
    """, (BT_START, BT_END))
    rebal_dates = sorted([r[0] for r in cur.fetchall()])
    print(f"  月末调仓日: {len(rebal_dates)}个")

    # 因子值（所有月末截面）
    all_factor_names = list(set(f for _, fl in groups for f in fl))
    factor_data = pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = ANY(%s) AND factor_name = ANY(%s)
             AND neutral_value IS NOT NULL""",
        conn,
        params=(rebal_dates, all_factor_names),
    )
    print(f"  因子数据: {len(factor_data):,}行, {factor_data['factor_name'].nunique()}个因子")

    # 价格
    prices = pd.read_sql(
        """SELECT code, trade_date, close * COALESCE(adj_factor, 1) AS adj_close
           FROM klines_daily
           WHERE trade_date >= %s AND trade_date <= %s AND volume > 0""",
        conn,
        params=(BT_START, BT_END),
    )
    price_pivot = prices.pivot(index="trade_date", columns="code", values="adj_close").sort_index()
    daily_ret = price_pivot.pct_change(fill_method=None)
    print(f"  价格: {len(price_pivot)}天, {len(price_pivot.columns)}只")

    # 市值
    mv_data = pd.read_sql(
        """SELECT code, trade_date, total_mv FROM daily_basic
           WHERE trade_date = ANY(%s) AND total_mv > 0""",
        conn,
        params=(rebal_dates,),
    )
    print(f"  市值数据: {len(mv_data):,}行")

    # Step 2: 逐组回测
    print("\n[Step 3] 逐组回测...")
    results = []
    for label, factor_list in groups:
        print(f"  {label}组 ({len(factor_list)}因子)...", end=" ", flush=True)
        r = run_expansion_backtest(
            factor_list, directions, factor_data, price_pivot, daily_ret,
            mv_data, rebal_dates, label,
        )
        print(f"Sharpe={r['sharpe']:.2f} MDD={r['mdd']*100:.1f}% Calmar={r['calmar']:.2f}")
        results.append(r)

    # 报告
    print_report(candidates, results)

    conn.close()


if __name__ == "__main__":
    main()
