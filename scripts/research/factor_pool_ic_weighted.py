#!/usr/bin/env python3
"""因子池扩展 + IC_IR加权联合实验。

等权扩池稀释alpha(Sharpe 1.27→0.80)。IC_IR加权让强因子主导、弱因子边际分散。
回测矩阵: 6组因子 × 2种加权(等权/IC_IR) + lookback敏感性。

用法:
    python scripts/research/factor_pool_ic_weighted.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from app.services.price_utils import _get_sync_conn

# ── 配置 ─────────────────────────────────────────────
BT_START = date(2021, 1, 1)
BT_END = date(2025, 12, 31)
TOP_N = 20
RF_ANNUAL = 0.02

CORE_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]

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

EXCLUDE_FACTORS = {"ln_market_cap", "mf_divergence", "beta_market_20"}

MV_BINS = [0, 50, 100, 300, float("inf")]
MV_LABELS = ["<50亿", "50-100亿", "100-300亿", ">300亿"]

LOOKBACKS = [6, 12, 24, 0]  # 0 = expanding


# ═══════════════════════════════════════════════════════
# 数据加载（一次性加载全部共享数据）
# ═══════════════════════════════════════════════════════
def load_shared_data(conn) -> dict:
    """加载所有回测需要的共享数据。"""
    print("[数据加载]")
    cur = conn.cursor()

    # 月末调仓日
    cur.execute("""
        SELECT DISTINCT ON (EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date))
            trade_date
        FROM klines_daily WHERE trade_date >= %s AND trade_date <= %s
        ORDER BY EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date), trade_date DESC
    """, (BT_START, BT_END))
    rebal_dates = sorted([r[0] for r in cur.fetchall()])
    print(f"  调仓日: {len(rebal_dates)}个")

    # 候选因子（T1, |t|>2.5, 非北向/排除列表）
    cur.execute("""
        SELECT factor_name, AVG(ic_20d) as avg_ic
        FROM factor_ic_history
        WHERE factor_name NOT LIKE 'nb_%%' AND factor_name NOT LIKE 'sue_%%'
          AND factor_name NOT LIKE 'mkt_%%' AND ic_20d IS NOT NULL
        GROUP BY factor_name
        HAVING COUNT(*) >= 10
           AND ABS(AVG(ic_20d) / (STDDEV(ic_20d) / SQRT(COUNT(*)))) >= 2.5
    """)
    candidates = {}
    for fname, avg_ic in cur.fetchall():
        if fname in EXCLUDE_FACTORS or fname.startswith("nb_"):
            continue
        d = KNOWN_DIRECTIONS.get(fname)
        if d is None:
            d = 1 if float(avg_ic) > 0 else -1
        candidates[fname] = d
    print(f"  T1候选: {len(candidates)}个因子")

    # 因子相关性排序（与CORE 5的平均|corr|）
    sample_dates = rebal_dates[::3][:15]  # 每3个月抽1个，最多15个
    sample_factors = pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = ANY(%s) AND factor_name = ANY(%s) AND neutral_value IS NOT NULL""",
        conn, params=(sample_dates, list(candidates.keys())),
    )

    avg_corrs = {}
    for fname in candidates:
        if fname in CORE_FACTORS:
            avg_corrs[fname] = 0.0
            continue
        corrs = []
        for sd in sample_dates:
            sd_data = sample_factors[sample_factors["trade_date"] == sd]
            f_vals = sd_data[sd_data["factor_name"] == fname].set_index("code")["neutral_value"]
            for cf in CORE_FACTORS:
                cf_vals = sd_data[sd_data["factor_name"] == cf].set_index("code")["neutral_value"]
                common = f_vals.index.intersection(cf_vals.index)
                if len(common) > 50:
                    c, _ = spearmanr(f_vals[common], cf_vals[common])
                    if np.isfinite(c):
                        corrs.append(abs(c))
        avg_corrs[fname] = np.mean(corrs) if corrs else 1.0

    non_core = sorted(
        [f for f in candidates if f not in CORE_FACTORS],
        key=lambda f: avg_corrs.get(f, 1.0),
    )
    print(f"  非CORE排序完成: {len(non_core)}个")

    # 因子组定义
    groups = [
        ("A", CORE_FACTORS),
        ("B", CORE_FACTORS + non_core[:3]),
        ("C", CORE_FACTORS + non_core[:5]),
        ("D", CORE_FACTORS + non_core[:10]),
        ("E", CORE_FACTORS + non_core[:15]),
        ("F", CORE_FACTORS + non_core),
    ]

    # 全部因子数据（月末截面）
    all_fnames = list(candidates.keys())
    factor_data = pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = ANY(%s) AND factor_name = ANY(%s) AND neutral_value IS NOT NULL""",
        conn, params=(rebal_dates, all_fnames),
    )
    print(f"  因子数据: {len(factor_data):,}行")

    # 价格
    prices = pd.read_sql(
        """SELECT code, trade_date, close * COALESCE(adj_factor, 1) AS adj_close
           FROM klines_daily WHERE trade_date >= %s AND trade_date <= %s AND volume > 0""",
        conn, params=(BT_START, BT_END),
    )
    price_pivot = prices.pivot(index="trade_date", columns="code", values="adj_close").sort_index()
    daily_ret = price_pivot.pct_change(fill_method=None)
    print(f"  价格: {len(price_pivot)}天")

    # 市值
    mv_data = pd.read_sql(
        """SELECT code, trade_date, total_mv FROM daily_basic
           WHERE trade_date = ANY(%s) AND total_mv > 0""",
        conn, params=(rebal_dates,),
    )

    # 月度IC（用于IC_IR加权）——在每个月末对前月截面算rank IC
    # 用adj_close的月度forward return
    print("  计算月度截面IC...")
    all_dates_sorted = sorted(price_pivot.index)
    all_dates_ts = [pd.Timestamp(d) for d in all_dates_sorted]

    monthly_ics: dict[str, dict] = {f: {} for f in all_fnames}
    for i, rd in enumerate(rebal_dates[:-1]):
        rd_ts = pd.Timestamp(rd)
        # 下月末
        next_rd_ts = pd.Timestamp(rebal_dates[i + 1])
        # forward return: 从rd+1到next_rd
        start_idx = next((j for j, d in enumerate(all_dates_ts) if d > rd_ts), None)
        end_idx = next((j for j, d in enumerate(all_dates_ts) if d > next_rd_ts), None)
        if start_idx is None or end_idx is None or end_idx <= start_idx:
            continue

        start_date = all_dates_sorted[start_idx]
        end_date = all_dates_sorted[min(end_idx - 1, len(all_dates_sorted) - 1)]

        fwd_ret = (price_pivot.loc[end_date] / price_pivot.loc[start_date] - 1).dropna()

        # 当月因子截面
        rd_factors = factor_data[factor_data["trade_date"] == rd]
        for fname in all_fnames:
            fv = rd_factors[rd_factors["factor_name"] == fname].set_index("code")["neutral_value"]
            direction = candidates[fname]
            fv = fv * direction  # 方向对齐
            common = fv.index.intersection(fwd_ret.index)
            if len(common) < 50:
                continue
            ic, _ = spearmanr(fv[common], fwd_ret[common])
            if np.isfinite(ic):
                monthly_ics[fname][rd] = float(ic)

    print(f"  月度IC计算完成: {sum(len(v) for v in monthly_ics.values())}条")

    return {
        "rebal_dates": rebal_dates,
        "groups": groups,
        "candidates": candidates,
        "factor_data": factor_data,
        "price_pivot": price_pivot,
        "daily_ret": daily_ret,
        "mv_data": mv_data,
        "monthly_ics": monthly_ics,
        "non_core": non_core,
        "avg_corrs": avg_corrs,
    }


# ═══════════════════════════════════════════════════════
# IC_IR加权计算
# ═══════════════════════════════════════════════════════
def calc_ic_ir_weights(
    monthly_ics: dict[str, dict],
    factor_list: list[str],
    current_date,
    lookback: int,
) -> dict[str, float]:
    """计算IC_IR加权权重。lookback=0表示expanding。"""

    weights = {}
    for fname in factor_list:
        ic_dict = monthly_ics.get(fname, {})
        # 过滤到current_date之前的IC
        past_ics = [v for d, v in sorted(ic_dict.items()) if d < current_date]

        if lookback > 0:
            past_ics = past_ics[-lookback:]

        if len(past_ics) < 6:
            weights[fname] = 0.0
            continue

        ic_arr = np.array(past_ics)
        ic_mean = np.mean(ic_arr)
        ic_std = np.std(ic_arr, ddof=1)
        if ic_std < 1e-6:
            weights[fname] = 0.0
            continue

        ir = abs(ic_mean) / ic_std
        weights[fname] = ir

    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    else:
        # fallback等权
        n = len(factor_list)
        weights = {k: 1.0 / n for k in factor_list}

    return weights


# ═══════════════════════════════════════════════════════
# 统一回测函数
# ═══════════════════════════════════════════════════════
def run_backtest(
    factor_list: list[str],
    directions: dict[str, int],
    data: dict,
    weight_mode: str = "equal",
    lookback: int = 12,
) -> dict:
    """运行回测。weight_mode: 'equal' 或 'ic_ir'。"""
    factor_data = data["factor_data"]
    price_pivot = data["price_pivot"]
    daily_ret = data["daily_ret"]
    mv_data = data["mv_data"]
    rebal_dates = data["rebal_dates"]
    monthly_ics = data["monthly_ics"]

    all_dates = sorted(price_pivot.index)
    all_dates_ts = [pd.Timestamp(d) for d in all_dates]

    portfolio_returns = []
    monthly_holdings = {}
    monthly_turnover = []
    weight_history = []
    prev_codes = set()

    for i, rd in enumerate(rebal_dates):
        df = factor_data[factor_data["trade_date"] == rd]
        if df.empty:
            continue

        pivot = df[df["factor_name"].isin(factor_list)].pivot(
            index="code", columns="factor_name", values="neutral_value"
        )

        # 计算权重
        if weight_mode == "ic_ir":
            weights = calc_ic_ir_weights(monthly_ics, factor_list, rd, lookback)
        else:
            weights = {f: 1.0 / len(factor_list) for f in factor_list}

        weight_history.append({"date": rd, **weights})

        # 加权合成
        score = pd.Series(0.0, index=pivot.index)
        total_w = 0
        for f in factor_list:
            if f not in pivot.columns:
                continue
            w = weights.get(f, 0)
            if w < 1e-8:
                continue
            vals = pivot[f].dropna()
            d = directions.get(f, 1)
            score[vals.index] += vals * d * w
            total_w += w

        top_codes = score.dropna().sort_values(ascending=False).head(TOP_N).index.tolist()
        monthly_holdings[rd] = top_codes

        new_codes = set(top_codes)
        if prev_codes:
            monthly_turnover.append(1 - len(new_codes & prev_codes) / max(len(new_codes | prev_codes), 1))
        prev_codes = new_codes

        # 持有期
        rd_ts = pd.Timestamp(rd)
        start_idx = next((j for j, d in enumerate(all_dates_ts) if d > rd_ts), None)
        if start_idx is None:
            continue
        if i + 1 < len(rebal_dates):
            next_rd = pd.Timestamp(rebal_dates[i + 1])
            end_idx = next((j for j, d in enumerate(all_dates_ts) if d > next_rd), len(all_dates_ts))
        else:
            end_idx = len(all_dates_ts)

        valid_codes = [c for c in top_codes if c in daily_ret.columns]
        for d in all_dates[start_idx:end_idx]:
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

    # 市值分布
    mv_dist = {l: 0 for l in MV_LABELS}
    mv_median_list = []
    for rd in sorted(monthly_holdings.keys())[-6:]:
        for code in monthly_holdings.get(rd, []):
            mv_row = mv_data[(mv_data["code"] == code) & (mv_data["trade_date"] == rd)]
            if not mv_row.empty:
                mv_val = float(mv_row.iloc[0]["total_mv"]) / 10000
                mv_median_list.append(mv_val)
                for j in range(len(MV_BINS) - 1):
                    if MV_BINS[j] <= mv_val < MV_BINS[j + 1]:
                        mv_dist[MV_LABELS[j]] += 1
                        break
    total_mv = sum(mv_dist.values())
    mv_pct = {k: v / max(total_mv, 1) for k, v in mv_dist.items()}

    # 年度分解
    yearly = {}
    for year in range(BT_START.year, BT_END.year + 1):
        yr_dates = pd.Series(
            [d.year if hasattr(d, "year") else pd.Timestamp(d).year for d in port_ret.index],
            index=port_ret.index,
        )
        mask = yr_dates == year
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
        "sharpe": sharpe, "mdd": mdd, "calmar": calmar, "cagr": cagr,
        "avg_turnover": avg_turnover, "mv_pct": mv_pct,
        "mv_median": np.median(mv_median_list) if mv_median_list else 0,
        "yearly": yearly, "holdings": monthly_holdings,
        "weight_history": weight_history,
    }


# ═══════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════
def print_report(data: dict, eq_results: list, ic_results: list, lb_results: dict) -> None:
    groups = data["groups"]

    print("\n" + "═" * 100)
    print("  因子池扩展 + IC_IR加权联合实验")
    print("═" * 100)

    # 回测矩阵
    print("\n  回测矩阵:")
    print(
        f"  {'组':<4s} {'因子':>4s}  │ {'等权Sharpe':>10s} {'等权MDD':>8s} {'等权Calmar':>10s}"
        f"  │ {'IC_IR Sharpe':>11s} {'IC_IR MDD':>9s} {'IC_IR Calmar':>11s}  │ {'判定':>6s}"
    )
    print(f"  {'─'*4} {'─'*4}  ┼ {'─'*10} {'─'*8} {'─'*10}  ┼ {'─'*11} {'─'*9} {'─'*11}  ┼ {'─'*6}")

    for (label, flist), eq, ic in zip(groups, eq_results, ic_results, strict=False):
        mark = ""
        if ic["sharpe"] >= 1.15 and ic["mdd"] > eq_results[0]["mdd"]:
            mark = " ★"
        print(
            f"  {label:<4s} {len(flist):>4d}  │ "
            f"{eq['sharpe']:>+10.2f} {eq['mdd']*100:>+8.1f} {eq['calmar']:>10.2f}  │ "
            f"{ic['sharpe']:>+11.2f} {ic['mdd']*100:>+9.1f} {ic['calmar']:>11.2f}  │{mark}"
        )

    # 最优IC_IR组
    best_ic = max(ic_results, key=lambda x: x["calmar"])
    best_idx = ic_results.index(best_ic)
    best_label = groups[best_idx][0]
    best_flist = groups[best_idx][1]

    # 权重分布分析
    if best_ic["weight_history"]:
        wh = pd.DataFrame(best_ic["weight_history"]).set_index("date")
        avg_w = wh.mean()
        core_w = sum(avg_w.get(f, 0) for f in CORE_FACTORS)
        sorted_w = avg_w.sort_values(ascending=False)

        print(f"\n  IC_IR加权 最优组({best_label}, {len(best_flist)}因子) 权重分布:")
        print(f"    CORE 5因子合计权重: {core_w*100:.1f}%")
        print("    权重Top-5:")
        for fname, w in sorted_w.head(5).items():
            is_core = "●" if fname in CORE_FACTORS else " "
            print(f"      {is_core} {fname:<30s}: {w*100:.1f}%")
        if len(sorted_w) > 5:
            print("    权重Bottom-3:")
            for fname, w in sorted_w.tail(3).items():
                print(f"        {fname:<30s}: {w*100:.1f}%")

    # 持仓风格对比
    print("\n  持仓风格对比:")
    print(f"  {'':>20s}  {'CORE等权':>10s}  {'最优等权':>10s}  {'最优IC_IR':>10s}")
    best_eq = eq_results[best_idx]
    core_eq = eq_results[0]
    small_core = (core_eq["mv_pct"].get("<50亿", 0) + core_eq["mv_pct"].get("50-100亿", 0)) * 100
    small_beq = (best_eq["mv_pct"].get("<50亿", 0) + best_eq["mv_pct"].get("50-100亿", 0)) * 100
    small_bic = (best_ic["mv_pct"].get("<50亿", 0) + best_ic["mv_pct"].get("50-100亿", 0)) * 100
    print(f"  {'<100亿占比':>20s}  {small_core:>9.0f}%  {small_beq:>9.0f}%  {small_bic:>9.0f}%")
    print(f"  {'市值中位数(亿)':>20s}  {core_eq['mv_median']:>10.0f}  {best_eq['mv_median']:>10.0f}  {best_ic['mv_median']:>10.0f}")
    print(f"  {'月均换手率':>20s}  {core_eq['avg_turnover']*100:>9.0f}%  {best_eq['avg_turnover']*100:>9.0f}%  {best_ic['avg_turnover']*100:>9.0f}%")

    # lookback敏感性
    if lb_results:
        print(f"\n  lookback敏感性（{best_label}组, IC_IR加权）:")
        for lb, r in sorted(lb_results.items()):
            lb_label = f"{lb}月" if lb > 0 else "expanding"
            print(f"    {lb_label:<12s}: Sharpe={r['sharpe']:+.2f}  MDD={r['mdd']*100:+.1f}%  Calmar={r['calmar']:.2f}")

    # 年度分解
    print(f"\n  年度分解 (CORE等权A vs 最优IC_IR {best_label}):")
    print(f"  {'年份':>6s}  {'A Sharpe':>9s}  {'A MDD%':>8s}  {best_label+' Sharpe':>12s}  {best_label+' MDD%':>10s}")
    for year in sorted(set(list(core_eq["yearly"].keys()) + list(best_ic["yearly"].keys()))):
        bs, bm = core_eq["yearly"].get(year, (0, 0))
        ms, mm = best_ic["yearly"].get(year, (0, 0))
        print(f"  {year:>6d}  {bs:>+9.2f}  {bm:>+8.1f}  {ms:>+12.2f}  {mm:>+10.1f}")

    # 结论
    print("\n  结论:")
    core_sharpe = core_eq["sharpe"]
    core_mdd = core_eq["mdd"]

    if best_ic["sharpe"] >= core_sharpe * 0.9 and best_ic["mdd"] > core_mdd:
        delta_mdd = (best_ic["mdd"] - core_mdd) * 100
        print(f"    ✅ IC_IR加权 {best_label}({len(best_flist)}因子): Sharpe={best_ic['sharpe']:.2f} MDD={best_ic['mdd']*100:.1f}%")
        print(f"       vs CORE等权: Sharpe变化{(best_ic['sharpe']/core_sharpe-1)*100:+.0f}%, MDD改善{delta_mdd:+.1f}pp")
        print("       IC_IR加权解决了等权稀释问题")
    else:
        print("    IC_IR加权未能兼得Sharpe和MDD改善")
        print(f"    最优IC_IR: Sharpe={best_ic['sharpe']:.2f} (CORE={core_sharpe:.2f}), MDD={best_ic['mdd']*100:.1f}% (CORE={core_mdd*100:.1f}%)")

    # 等权vs IC_IR提升幅度
    print(f"\n    等权 vs IC_IR对比（{best_label}组）:")
    print(f"      等权:   Sharpe={best_eq['sharpe']:.2f}  MDD={best_eq['mdd']*100:.1f}%")
    print(f"      IC_IR:  Sharpe={best_ic['sharpe']:.2f}  MDD={best_ic['mdd']*100:.1f}%")
    if best_ic["sharpe"] > best_eq["sharpe"]:
        print(f"      IC_IR加权恢复了{(best_ic['sharpe']-best_eq['sharpe']):.2f} Sharpe")

    print(f"\n{'═' * 100}\n")


# ═══════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════
def main() -> None:
    conn = _get_sync_conn()
    data = load_shared_data(conn)
    groups = data["groups"]
    candidates = data["candidates"]

    # 等权回测（6组）
    print("\n[等权回测]")
    eq_results = []
    for label, flist in groups:
        print(f"  {label}({len(flist)}因子)...", end=" ", flush=True)
        r = run_backtest(flist, candidates, data, weight_mode="equal")
        print(f"Sharpe={r['sharpe']:.2f} MDD={r['mdd']*100:.1f}%")
        eq_results.append(r)

    # IC_IR加权回测（6组, lookback=12）
    print("\n[IC_IR加权回测 (lookback=12)]")
    ic_results = []
    for label, flist in groups:
        print(f"  {label}({len(flist)}因子)...", end=" ", flush=True)
        r = run_backtest(flist, candidates, data, weight_mode="ic_ir", lookback=12)
        print(f"Sharpe={r['sharpe']:.2f} MDD={r['mdd']*100:.1f}%")
        ic_results.append(r)

    # lookback敏感性（最优IC_IR组）
    best_idx = max(range(len(ic_results)), key=lambda i: ic_results[i]["calmar"])
    best_label, best_flist = groups[best_idx]
    print(f"\n[lookback敏感性 ({best_label}组)]")
    lb_results = {}
    for lb in LOOKBACKS:
        lb_name = f"{lb}月" if lb > 0 else "expanding"
        print(f"  lookback={lb_name}...", end=" ", flush=True)
        r = run_backtest(best_flist, candidates, data, weight_mode="ic_ir", lookback=lb)
        print(f"Sharpe={r['sharpe']:.2f} MDD={r['mdd']*100:.1f}%")
        lb_results[lb] = r

    # 报告
    print_report(data, eq_results, ic_results, lb_results)

    conn.close()


if __name__ == "__main__":
    main()
