#!/usr/bin/env python3
"""叠加回测: 等权15因子 + MODIFIER nb_sh_sz_divergence。

4组统一回测:
  基线: CORE 5等权
  D组:  15因子等权
  M组:  CORE 5 + MODIFIER
  叠加: 15因子 + MODIFIER

用法:
    python scripts/research/strategy_overlay_backtest.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import numpy as np
import pandas as pd

from app.services.price_utils import _get_sync_conn

# ── 配置 ─────────────────────────────────────────────
BT_START = date(2021, 1, 1)
BT_END = date(2025, 12, 31)
DATA_START = date(2020, 1, 1)
TOP_N = 20
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252
EXTRA_COST_BPS = 30

CORE_5 = [
    ("turnover_mean_20", -1), ("volatility_20", -1), ("reversal_20", 1),
    ("amihud_20", 1), ("bp_ratio", 1),
]

FACTORS_15 = CORE_5 + [
    ("money_flow_strength", 1), ("a158_vsump5", -1), ("a158_vma5", 1),
    ("kbar_kmid", -1), ("a158_rank5", -1), ("kbar_ksft", -1),
    ("vwap_bias_1d", -1), ("a158_corr5", -1), ("turnover_surge_ratio", -1),
    ("chmom_60_20", -1),
]

# MODIFIER首选参数
MOD_THRESHOLD = 0.20
MOD_COEFF = 0.3
MOD_SMOOTH = 10
MOD_DEAD_ZONE = 5

MV_BINS = [0, 50, 100, 300, float("inf")]
MV_LABELS = ["<50亿", "50-100亿", "100-300亿", ">300亿"]


# ═══════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════
def load_data(conn) -> dict:
    """一次性加载全部共享数据。"""
    print("[数据加载]")
    cur = conn.cursor()

    # 月末调仓日
    cur.execute("""
        SELECT DISTINCT ON (EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date))
            trade_date FROM klines_daily
        WHERE trade_date >= %s AND trade_date <= %s
        ORDER BY EXTRACT(YEAR FROM trade_date), EXTRACT(MONTH FROM trade_date), trade_date DESC
    """, (BT_START, BT_END))
    rebal_dates = sorted([r[0] for r in cur.fetchall()])
    print(f"  调仓日: {len(rebal_dates)}个")

    # 因子数据
    all_fnames = list(set(f for f, _ in FACTORS_15))
    factor_data = pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = ANY(%s) AND factor_name = ANY(%s) AND neutral_value IS NOT NULL""",
        conn, params=(rebal_dates, all_fnames),
    )
    print(f"  因子: {len(factor_data):,}行, {factor_data['factor_name'].nunique()}个")

    # 价格
    prices = pd.read_sql(
        """SELECT code, trade_date, close * COALESCE(adj_factor, 1) AS adj_close
           FROM klines_daily WHERE trade_date >= %s AND trade_date <= %s AND volume > 0""",
        conn, params=(BT_START, BT_END),
    )
    price_pivot = prices.pivot(index="trade_date", columns="code", values="adj_close").sort_index()
    daily_ret = price_pivot.pct_change(fill_method=None)
    all_dates = sorted(price_pivot.index)
    all_dates_ts = [pd.Timestamp(d) for d in all_dates]
    print(f"  价格: {len(all_dates)}天, {len(price_pivot.columns)}只")

    # 市值
    mv_data = pd.read_sql(
        """SELECT code, trade_date, total_mv FROM daily_basic
           WHERE trade_date = ANY(%s) AND total_mv > 0""",
        conn, params=(rebal_dates,),
    )

    # MODIFIER信号面板（nb_sh_sz_divergence）
    print("  构建MODIFIER面板...")
    cur.execute("""
        SELECT code, trade_date, hold_vol FROM northbound_holdings
        WHERE trade_date >= %s AND trade_date <= %s AND hold_vol IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, BT_END))
    nb_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "hold_vol"])
    nb_df["trade_date"] = pd.to_datetime(nb_df["trade_date"])
    nb_df["hold_vol"] = nb_df["hold_vol"].astype(float)

    nb_price = pd.read_sql(
        """SELECT code, trade_date, close * adj_factor as adj_close
           FROM klines_daily WHERE trade_date >= %s AND trade_date <= %s
             AND close IS NOT NULL AND adj_factor IS NOT NULL""",
        conn, params=(DATA_START, BT_END),
    )
    nb_price["trade_date"] = pd.to_datetime(nb_price["trade_date"])
    nb_price["adj_close"] = nb_price["adj_close"].astype(float)

    # 构建nb_sh_sz_divergence
    nb_pivot = nb_df.pivot(index="trade_date", columns="code", values="hold_vol").ffill()
    p_pivot = nb_price.pivot(index="trade_date", columns="code", values="adj_close")
    common_dates = nb_pivot.index.intersection(p_pivot.index)
    common_codes = nb_pivot.columns.intersection(p_pivot.columns)
    nb = nb_pivot.loc[common_dates, common_codes]
    hold_diff = nb.diff(1)
    net_buy = hold_diff * p_pivot.reindex(index=common_dates, columns=common_codes)

    sh_sz_records = []
    for i, dt in enumerate(common_dates):
        if i == 0:
            continue
        nba = net_buy.loc[dt].dropna()
        if len(nba) < 50:
            continue
        sh_codes = [c for c in nba.index if c.startswith("6")]
        sz_codes = [c for c in nba.index if c.startswith("0") or c.startswith("3")]
        sh_net = nba.reindex(sh_codes).dropna().sum()
        sz_net = nba.reindex(sz_codes).dropna().sum()
        denom = abs(sh_net) + abs(sz_net) + 1e-10
        sh_sz_records.append({"trade_date": dt, "raw": (sh_net - sz_net) / denom})

    sh_sz_df = pd.DataFrame(sh_sz_records).set_index("trade_date").sort_index()
    sh_sz_signal = sh_sz_df["raw"].rolling(5).mean()  # 5d rolling for raw divergence
    print(f"  MODIFIER信号: {len(sh_sz_signal.dropna())}天")

    return {
        "rebal_dates": rebal_dates,
        "factor_data": factor_data,
        "price_pivot": price_pivot,
        "daily_ret": daily_ret,
        "all_dates": all_dates,
        "all_dates_ts": all_dates_ts,
        "mv_data": mv_data,
        "sh_sz_signal": sh_sz_signal,
    }


# ═══════════════════════════════════════════════════════
# MODIFIER系数计算
# ═══════════════════════════════════════════════════════
def compute_modifier_coeff(signal: pd.Series) -> pd.Series:
    """nb_sh_sz_divergence → position coefficient。

    参数: P<0.20, coeff=0.3, 10dMA平滑, dead=5d, direction=-1
    """
    f = signal.dropna()
    if len(f) < 60:
        return pd.Series(1.0, index=signal.index)

    # 10dMA平滑
    f = f.rolling(MOD_SMOOTH, min_periods=1).mean()

    # expanding百分位
    pct = f.expanding(min_periods=60).apply(
        lambda x: np.sum(x[:-1] < x[-1]) / max(len(x) - 1, 1), raw=True
    )
    # direction=-1: 反转百分位
    pct = 1 - pct

    # 阈值映射
    raw_coeff = pd.Series(1.0, index=pct.index)
    raw_coeff[pct <= MOD_THRESHOLD] = MOD_COEFF

    # 死区: 连续dead_zone天才触发
    is_reduce = (raw_coeff < 1.0).astype(int)
    consecutive = pd.Series(0, index=is_reduce.index)
    count = 0
    for i in range(len(is_reduce)):
        count = count + 1 if is_reduce.iloc[i] else 0
        consecutive.iloc[i] = count

    coeff = pd.Series(1.0, index=raw_coeff.index)
    coeff[consecutive >= MOD_DEAD_ZONE] = MOD_COEFF

    # 恢复满仓也需死区
    is_full = (coeff >= 1.0).astype(int)
    consec_full = pd.Series(0, index=is_full.index)
    count = 0
    for i in range(len(is_full)):
        count = count + 1 if is_full.iloc[i] else 0
        consec_full.iloc[i] = count

    final = coeff.copy()
    prev = 1.0
    for i in range(len(final)):
        if coeff.iloc[i] < 1.0:
            prev = coeff.iloc[i]
        elif consec_full.iloc[i] < MOD_DEAD_ZONE:
            final.iloc[i] = prev
        else:
            prev = 1.0

    return final


# ═══════════════════════════════════════════════════════
# 统一回测
# ═══════════════════════════════════════════════════════
@dataclass
class Result:
    label: str
    cagr: float = 0
    sharpe: float = 0
    mdd: float = 0
    calmar: float = 0
    mv_median: float = 0
    small_pct: float = 0
    avg_turnover: float = 0
    reduce_pct: float = 0
    extra_cost: float = 0
    yearly: dict = field(default_factory=dict)


def run_backtest(
    factor_list: list[tuple[str, int]],
    data: dict,
    modifier_coeff: pd.Series | None,
    label: str,
) -> Result:
    """统一回测。"""
    factor_data = data["factor_data"]
    daily_ret = data["daily_ret"]
    all_dates = data["all_dates"]
    all_dates_ts = data["all_dates_ts"]
    mv_data = data["mv_data"]
    rebal_dates = data["rebal_dates"]

    fnames = [f for f, _ in factor_list]
    directions = {f: d for f, d in factor_list}

    portfolio_returns = []
    prev_codes = set()
    turnovers = []
    mv_samples = []

    for i, rd in enumerate(rebal_dates):
        df = factor_data[(factor_data["trade_date"] == rd) & (factor_data["factor_name"].isin(fnames))]
        if df.empty:
            continue

        pivot = df.pivot(index="code", columns="factor_name", values="neutral_value")
        score = pd.Series(0.0, index=pivot.index)
        n_valid = 0
        for f in fnames:
            if f in pivot.columns:
                vals = pivot[f].dropna()
                score[vals.index] += vals * directions[f]
                n_valid += 1

        if n_valid > 0:
            score = score / n_valid

        top_codes = score.dropna().sort_values(ascending=False).head(TOP_N).index.tolist()

        # 换手率
        new_set = set(top_codes)
        if prev_codes:
            turnovers.append(1 - len(new_set & prev_codes) / max(len(new_set | prev_codes), 1))
        prev_codes = new_set

        # 市值采样
        for code in top_codes:
            mv_row = mv_data[(mv_data["code"] == code) & (mv_data["trade_date"] == rd)]
            if not mv_row.empty:
                mv_samples.append(float(mv_row.iloc[0]["total_mv"]) / 10000)

        # 持有期
        rd_ts = pd.Timestamp(rd)
        start_idx = next((j for j, d in enumerate(all_dates_ts) if d > rd_ts), None)
        if start_idx is None:
            continue
        if i + 1 < len(rebal_dates):
            next_rd_ts = pd.Timestamp(rebal_dates[i + 1])
            end_idx = next((j for j, d in enumerate(all_dates_ts) if d > next_rd_ts), len(all_dates_ts))
        else:
            end_idx = len(all_dates_ts)

        valid_codes = [c for c in top_codes if c in daily_ret.columns]
        for d in all_dates[start_idx:end_idx]:
            rets = daily_ret.loc[d, valid_codes].dropna()
            if len(rets) > 0:
                portfolio_returns.append({"trade_date": d, "ret": rets.mean()})

    base_ret = pd.DataFrame(portfolio_returns).set_index("trade_date")["ret"].sort_index()
    base_ret = base_ret[~base_ret.index.duplicated(keep="first")]

    # MODIFIER叠加
    reduce_pct = 0.0
    total_extra = 0.0
    if modifier_coeff is not None:
        # 对齐index → date
        br = base_ret.copy()
        br.index = pd.Index([d.date() if hasattr(d, "date") and callable(d.date) else d for d in br.index])
        mc = modifier_coeff.copy()
        mc.index = pd.Index([d.date() if hasattr(d, "date") and callable(d.date) else d for d in mc.index])
        common = br.index.intersection(mc.index)
        br = br.loc[common]
        cf = mc.loc[common]

        modified = br * cf + (1 - cf) * RF_DAILY
        delta = cf.diff().abs().fillna(0)
        cost = delta * (EXTRA_COST_BPS / 10000)
        modified = modified - cost
        total_extra = float(cost.sum())
        reduce_pct = float((cf < 0.95).mean())
        final_ret = modified
    else:
        final_ret = base_ret

    # 指标
    nav = (1 + final_ret).cumprod()
    n_years = len(final_ret) / 252
    cagr = (float(nav.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 else 0
    vol = float(final_ret.std() * np.sqrt(252))
    sharpe = (cagr - RF_ANNUAL) / vol if vol > 0 else 0
    mdd = float(((nav - nav.cummax()) / nav.cummax()).min())
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    # 市值分布
    mv_dist = {l: 0 for l in MV_LABELS}
    for mv in mv_samples[-120:]:  # 最近6个月
        for j in range(len(MV_BINS) - 1):
            if MV_BINS[j] <= mv < MV_BINS[j + 1]:
                mv_dist[MV_LABELS[j]] += 1
                break
    total_mv = sum(mv_dist.values())
    small_pct = (mv_dist["<50亿"] + mv_dist["50-100亿"]) / max(total_mv, 1)

    # 年度分解
    yearly = {}
    for year in range(BT_START.year, BT_END.year + 1):
        yr_dates = pd.Series(
            [d.year if hasattr(d, "year") else pd.Timestamp(d).year for d in final_ret.index],
            index=final_ret.index,
        )
        mask = yr_dates == year
        yr = final_ret[mask]
        if len(yr) < 20:
            continue
        yr_nav = (1 + yr).cumprod()
        yr_cagr = float(yr_nav.iloc[-1]) ** (252 / len(yr)) - 1
        yr_vol = float(yr.std() * np.sqrt(252))
        yr_sharpe = (yr_cagr - RF_ANNUAL) / yr_vol if yr_vol > 0 else 0
        yr_mdd = float(((yr_nav - yr_nav.cummax()) / yr_nav.cummax()).min())
        yearly[year] = (round(yr_sharpe, 2), round(yr_mdd * 100, 1))

    return Result(
        label=label, cagr=cagr, sharpe=sharpe, mdd=mdd, calmar=calmar,
        mv_median=np.median(mv_samples) if mv_samples else 0,
        small_pct=small_pct,
        avg_turnover=np.mean(turnovers) if turnovers else 0,
        reduce_pct=reduce_pct,
        extra_cost=total_extra / n_years if n_years > 0 else 0,
        yearly=yearly,
    )


# ═══════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════
def print_report(results: list[Result]) -> None:
    base, d_grp, m_grp, overlay = results

    print("\n" + "═" * 95)
    print("  叠加回测: 等权15因子 + MODIFIER nb_sh_sz_divergence")
    print(f"  回测期: {BT_START} ~ {BT_END} | Top-{TOP_N} | 月度调仓")
    print("═" * 95)

    # 框架验证
    print(f"\n  框架验证: 基线Sharpe={base.sharpe:.2f} (期望≈1.27, 偏差{(base.sharpe/1.27-1)*100:+.0f}%)")

    # 核心结果
    print("\n  核心结果:")
    print(
        f"  {'策略':<24s} │ {'CAGR%':>7s} │ {'Sharpe':>7s} │ {'MDD%':>7s} │ "
        f"{'Calmar':>7s} │ {'<100亿%':>7s} │ {'减仓天%':>7s} │ {'额外成本%':>8s}"
    )
    print(f"  {'─'*24}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*8}")

    for r in results:
        mark = " ★" if r.calmar > 1.0 and r.sharpe > 1.0 else ""
        print(
            f"  {r.label:<24s} │ {r.cagr*100:>+7.1f} │ {r.sharpe:>7.2f} │ "
            f"{r.mdd*100:>+7.1f} │ {r.calmar:>7.2f} │ {r.small_pct*100:>6.0f}% │ "
            f"{r.reduce_pct*100:>6.1f}% │ {r.extra_cost*100:>7.2f}%{mark}"
        )

    # 年度分解
    print("\n  年度分解:")
    print(
        f"  {'年':>6s}  │ {'基线':>14s} │ {'D组(15因子)':>14s} │ "
        f"{'M组(MODIFIER)':>14s} │ {'叠加':>14s}"
    )
    print(f"  {'─'*6}  ┼ {'─'*14} ┼ {'─'*14} ┼ {'─'*14} ┼ {'─'*14}")
    for year in range(BT_START.year, BT_END.year + 1):
        parts = []
        for r in results:
            s, m = r.yearly.get(year, (0, 0))
            parts.append(f"{s:>+5.2f}/{m:>+6.1f}")
        print(f"  {year:>6d}  │ {parts[0]:>14s} │ {parts[1]:>14s} │ {parts[2]:>14s} │ {parts[3]:>14s}")

    # MDD改善分解
    print("\n  MDD改善分解:")
    base_mdd = base.mdd * 100
    d_improve = (d_grp.mdd - base.mdd) * 100
    m_improve = (m_grp.mdd - base.mdd) * 100
    o_improve = (overlay.mdd - base.mdd) * 100
    print(f"    基线 MDD = {base_mdd:+.1f}%")
    print(f"    基线 → D组: 因子分散化 {d_improve:+.1f}pp")
    print(f"    基线 → M组: MODIFIER   {m_improve:+.1f}pp")
    print(f"    基线 → 叠加: 总改善     {o_improve:+.1f}pp")
    additive = d_improve + m_improve
    if abs(additive) > 0:
        overlap = 1 - o_improve / additive
        print(f"    正交性: 期望{additive:+.1f}pp, 实际{o_improve:+.1f}pp, 重叠{overlap*100:.0f}%")

    # 结论
    print("\n  结论:")
    print(f"    D组Sharpe验证: {d_grp.sharpe:.2f}")

    if overlay.mdd * 100 > -30:
        print(f"    ✅ 叠加MDD={overlay.mdd*100:.1f}% (< -30%目标)")
    elif overlay.mdd * 100 > -35:
        print(f"    ⚠️ 叠加MDD={overlay.mdd*100:.1f}% (接近-30%目标)")
    else:
        print(f"    ❌ 叠加MDD={overlay.mdd*100:.1f}% (未达-30%目标)")

    if overlay.sharpe > 1.0:
        print(f"    ✅ 叠加Sharpe={overlay.sharpe:.2f} (> 1.0)")
    else:
        print(f"    ❌ 叠加Sharpe={overlay.sharpe:.2f} (< 1.0)")

    if overlay.calmar > 1.0:
        print(f"    ✅ 叠加Calmar={overlay.calmar:.2f} (> 1.0)")

    best = max(results, key=lambda r: r.calmar)
    print(f"\n    最优策略: {best.label} (Calmar={best.calmar:.2f})")
    if best.label != "基线(CORE 5)":
        print(f"    vs基线: Sharpe {base.sharpe:.2f}→{best.sharpe:.2f}, MDD {base.mdd*100:.1f}%→{best.mdd*100:.1f}%")

    print(f"\n{'═' * 95}\n")


# ═══════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════
def main() -> None:
    conn = _get_sync_conn()
    data = load_data(conn)

    # MODIFIER系数
    mod_coeff = compute_modifier_coeff(data["sh_sz_signal"])
    reduce_days = (mod_coeff < 0.95).sum()
    total_days = mod_coeff.notna().sum()
    print(f"  MODIFIER系数: 减仓{reduce_days}/{total_days}天 ({reduce_days/max(total_days,1)*100:.1f}%)")

    # 4组统一回测
    print("\n[回测]")
    configs = [
        ("基线(CORE 5)", CORE_5, None),
        ("D组(15因子)", FACTORS_15, None),
        ("M组(CORE 5+MOD)", CORE_5, mod_coeff),
        ("叠加(15因子+MOD)", FACTORS_15, mod_coeff),
    ]

    results = []
    for label, factors, mod in configs:
        print(f"  {label}...", end=" ", flush=True)
        r = run_backtest(factors, data, mod, label)
        print(f"Sharpe={r.sharpe:.2f} MDD={r.mdd*100:.1f}% Calmar={r.calmar:.2f}")
        results.append(r)

    print_report(results)
    conn.close()


if __name__ == "__main__":
    main()
