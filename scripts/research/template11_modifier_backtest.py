#!/usr/bin/env python3
"""模板11: 北向MODIFIER仓位调节回测（Top-20组合）。

在Top-20等权月度策略上叠加MODIFIER仓位调节，
验证MDD能否从-35.1%降到-25%~-30%，Calmar能否提升。

核心逻辑:
  modified_return = base_return * coeff + (1-coeff) * rf_daily
  仓位变化时额外交易成本: |delta_coeff| * 30bps

用法:
    python scripts/research/template11_modifier_backtest.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import numpy as np
import pandas as pd

from app.services.price_utils import _get_sync_conn

# ── 配置 ─────────────────────────────────────────────
BT_START = date(2021, 1, 1)
BT_END = date(2025, 12, 31)
DATA_START = date(2020, 1, 1)  # 北向rolling需要lookback

CORE_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
FACTOR_DIRECTIONS = {"turnover_mean_20": -1, "volatility_20": -1, "reversal_20": -1, "amihud_20": 1, "bp_ratio": 1}
TOP_N = 20
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252
EXTRA_COST_BPS = 30  # 仓位变化单边成本

# V2研究中OOS通过的8个因子（方向从V2报告取）
OOS_FACTORS = [
    ("nb_asymmetry", -1),
    ("nb_contrarian_market_5d", -1),
    ("nb_active_share", 1),
    ("nb_sh_sz_divergence", -1),
    ("nb_vol_change", -1),
    ("nb_industry_rotation", 1),
    ("nb_turnover", -1),
    ("nb_buy_concentration", -1),
]


# ═══════════════════════════════════════════════════════
# Part 1: 构建Top-20基线日收益
# ═══════════════════════════════════════════════════════
def build_top20_daily_returns(conn) -> pd.Series:
    """从factor_values+klines_daily构建Top-20等权月度策略日收益。

    步骤:
      1. 加载5核心因子neutral_value
      2. 月末截面等权合成 → 选Top-20
      3. 下月每日等权组合收益
    """
    print("[Part 1] 构建Top-20基线日收益...")

    # 1. 月末交易日
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

    # 2. 批量加载因子值（所有月末截面一次性查询）
    all_factors = pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = ANY(%s) AND factor_name = ANY(%s)
             AND neutral_value IS NOT NULL""",
        conn,
        params=(rebal_dates, CORE_FACTORS),
    )
    print(f"  因子数据: {len(all_factors):,}行")

    factor_dfs = []
    for rd in rebal_dates:
        df = all_factors[all_factors["trade_date"] == rd]
        if df.empty:
            continue
        pivot = df.pivot(index="code", columns="factor_name", values="neutral_value")
        score = pd.Series(0.0, index=pivot.index)
        n_factors = 0
        for f in CORE_FACTORS:
            if f in pivot.columns:
                vals = pivot[f].dropna()
                score[vals.index] += vals * FACTOR_DIRECTIONS[f]
                n_factors += 1
        if n_factors > 0:
            score /= n_factors
        score = score.dropna().sort_values(ascending=False)
        top_codes = score.head(TOP_N).index.tolist()
        factor_dfs.append((rd, top_codes))

    print(f"  有效调仓月: {len(factor_dfs)}")

    # 3. 加载复权价格
    prices = pd.read_sql(
        """SELECT code, trade_date, close * COALESCE(adj_factor, 1) AS adj_close
           FROM klines_daily
           WHERE trade_date >= %s AND trade_date <= %s
             AND volume > 0""",
        conn,
        params=(BT_START, BT_END),
    )
    price_pivot = prices.pivot(index="trade_date", columns="code", values="adj_close").sort_index()
    daily_ret = price_pivot.pct_change()
    all_dates = sorted(price_pivot.index)
    print(f"  价格数据: {len(all_dates)}天, {len(price_pivot.columns)}只")

    # 4. 计算组合日收益
    # 统一为Timestamp比较
    all_dates_ts = [pd.Timestamp(d) for d in all_dates]
    portfolio_returns = []
    for i, (rd, top_codes) in enumerate(factor_dfs):
        rd_ts = pd.Timestamp(rd)
        start_idx = next((j for j, d in enumerate(all_dates_ts) if d > rd_ts), None)
        if start_idx is None:
            continue

        if i + 1 < len(factor_dfs):
            next_rd = pd.Timestamp(factor_dfs[i + 1][0])
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

    # 基线指标
    nav = (1 + port_ret).cumprod()
    n_years = len(port_ret) / 252
    cagr = (float(nav.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 else 0
    vol = float(port_ret.std() * np.sqrt(252))
    sharpe = (cagr - RF_ANNUAL) / vol if vol > 0 else 0
    mdd = float(((nav - nav.cummax()) / nav.cummax()).min())
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    print(f"  基线: CAGR={cagr*100:.1f}%, Sharpe={sharpe:.2f}, MDD={mdd*100:.1f}%, Calmar={calmar:.2f}")
    print(f"  日收益序列: {len(port_ret)}天, {port_ret.index[0]} ~ {port_ret.index[-1]}")

    return port_ret


# ═══════════════════════════════════════════════════════
# Part 2: 计算MODIFIER信号 (复用V2逻辑)
# ═══════════════════════════════════════════════════════
def build_modifier_panel(conn) -> pd.DataFrame:
    """构建北向市场级MODIFIER面板（复用V2逻辑）。"""
    print("\n[Part 2] 计算MODIFIER信号面板...")

    cur = conn.cursor()

    # 北向持仓
    cur.execute("""
        SELECT code, trade_date, hold_vol FROM northbound_holdings
        WHERE trade_date >= %s AND trade_date <= %s AND hold_vol IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, BT_END))
    nb_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "hold_vol"])
    nb_df["trade_date"] = pd.to_datetime(nb_df["trade_date"])
    nb_df["hold_vol"] = nb_df["hold_vol"].astype(float)
    print(f"  北向: {len(nb_df):,}行, {nb_df['code'].nunique()}只")

    # 价格
    cur.execute("""
        SELECT code, trade_date, close * adj_factor as adj_close
        FROM klines_daily
        WHERE trade_date >= %s AND trade_date <= %s
          AND close IS NOT NULL AND adj_factor IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, BT_END))
    price_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "adj_close"])
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
    price_df["adj_close"] = price_df["adj_close"].astype(float)
    print(f"  价格: {len(price_df):,}行")

    # 市值
    cur.execute("""
        SELECT code, trade_date, circ_mv FROM daily_basic
        WHERE trade_date >= %s AND trade_date <= %s AND circ_mv IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, BT_END))
    mv_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "circ_mv"])
    mv_df["trade_date"] = pd.to_datetime(mv_df["trade_date"])
    mv_df["circ_mv"] = mv_df["circ_mv"].astype(float)

    # CSI300日收益
    cur.execute("""
        SELECT trade_date, pct_change FROM index_daily
        WHERE index_code = '000300.SH' AND trade_date >= %s ORDER BY trade_date
    """, (DATA_START,))
    idx = pd.DataFrame(cur.fetchall(), columns=["trade_date", "pct_change"])
    idx["trade_date"] = pd.to_datetime(idx["trade_date"])
    idx["ret"] = idx["pct_change"].astype(float) / 100
    csi300_ret = idx.set_index("trade_date")["ret"]

    # 行业
    cur.execute("SELECT code, industry_sw_l1 FROM symbols WHERE market='astock' AND industry_sw_l1 IS NOT NULL")
    ind_map = dict(cur.fetchall())

    # Pivots
    nb_pivot = nb_df.pivot(index="trade_date", columns="code", values="hold_vol").ffill()
    price_pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close")
    mv_pivot = mv_df.pivot(index="trade_date", columns="code", values="circ_mv").ffill()

    common_dates = nb_pivot.index.intersection(price_pivot.index)
    common_codes = nb_pivot.columns.intersection(price_pivot.columns)
    nb = nb_pivot.loc[common_dates, common_codes]
    price = price_pivot.reindex(index=common_dates, columns=common_codes)
    mv = mv_pivot.reindex(index=common_dates, columns=common_codes).ffill()

    hold_diff = nb.diff(1)
    net_buy_amount = hold_diff * price

    print(f"  面板: {len(common_dates)}天 × {len(common_codes)}只")

    # ── 逐天计算因子 ──
    records = []
    for i, dt in enumerate(common_dates):
        if i == 0:
            continue

        diff_row = hold_diff.loc[dt]
        nb_row = nb.loc[dt]
        nba_row = net_buy_amount.loc[dt]
        valid = diff_row.dropna()
        if len(valid) < 50:
            continue

        increasing = valid[valid > 0]
        decreasing = valid[valid < 0]
        rec = {"trade_date": dt}

        # nb_breadth_ratio
        rec["nb_breadth_ratio"] = len(increasing) / max(len(decreasing), 1)

        # nb_buy_concentration (HHI)
        pos_amounts = nba_row[nba_row > 0].dropna()
        if len(pos_amounts) > 0 and pos_amounts.sum() > 0:
            shares = pos_amounts / pos_amounts.sum()
            rec["nb_buy_concentration"] = float((shares ** 2).sum())
        else:
            rec["nb_buy_concentration"] = np.nan

        # nb_asymmetry
        if len(increasing) > 0 and len(decreasing) > 0:
            nb_prev = nb.iloc[i - 1].reindex(valid.index)
            inc_pct = (increasing / nb_prev.reindex(increasing.index).replace(0, np.nan)).dropna()
            dec_pct = (decreasing.abs() / nb_prev.reindex(decreasing.index).replace(0, np.nan)).dropna()
            if len(inc_pct) > 0 and len(dec_pct) > 0:
                rec["nb_asymmetry"] = inc_pct.mean() / max(dec_pct.mean(), 1e-10)
            else:
                rec["nb_asymmetry"] = np.nan
        else:
            rec["nb_asymmetry"] = np.nan

        # nb_turnover
        total_abs_diff = valid.abs().sum()
        net_diff = abs(valid.sum())
        prev_total = nb.iloc[i - 1].sum()
        rec["nb_turnover"] = (total_abs_diff - net_diff) / 2 / prev_total if prev_total > 0 else np.nan

        # 汇总
        rec["daily_net_flow"] = valid.sum()

        # 沪深拆分
        sh_codes = [c for c in valid.index if c.startswith("6")]
        sz_codes = [c for c in valid.index if c.startswith("0") or c.startswith("3")]
        rec["sh_net"] = nba_row.reindex(sh_codes).dropna().sum()
        rec["sz_net"] = nba_row.reindex(sz_codes).dropna().sum()

        # 行业分布
        ind_amounts = {}
        for code in nba_row.dropna().index:
            ind = ind_map.get(code, "其他")
            ind_amounts[ind] = ind_amounts.get(ind, 0) + nba_row[code]
        rec["_ind_amounts"] = ind_amounts

        # nb_active_share_raw
        nb_total_mv = 0
        nb_stock_mv = {}
        for code in nb_row.dropna().index:
            if nb_row[code] > 0 and code in price.columns:
                p = price.loc[dt, code]
                if not np.isnan(p):
                    smv = nb_row[code] * p
                    nb_stock_mv[code] = smv
                    nb_total_mv += smv
        rec["nb_active_share_raw"] = np.nan  # simplified — skip CSI weight calc

        # nb_size_median
        wm_values = []
        for code in increasing.index:
            if code in mv.columns:
                m = mv.loc[dt, code]
                if not np.isnan(m):
                    wm_values.append(m)
        rec["nb_size_median"] = np.median(wm_values) if wm_values else np.nan

        records.append(rec)

    panel = pd.DataFrame(records).set_index("trade_date").sort_index()

    # Rolling因子
    net = panel["daily_net_flow"]
    csi_aligned = csi300_ret.reindex(panel.index)

    # nb_contrarian_market_5d
    panel["nb_contrarian_market_5d"] = (net * (-csi_aligned)).rolling(5).sum()

    # nb_size_shift_20d
    sm = panel["nb_size_median"]
    panel["nb_size_shift_20d"] = sm / sm.shift(20).replace(0, np.nan) - 1

    # nb_vol_change
    panel["nb_vol_change"] = net.rolling(5).std() / net.rolling(60).std().replace(0, np.nan)

    # nb_sh_sz_divergence
    sh = panel["sh_net"]
    sz = panel["sz_net"]
    panel["nb_sh_sz_divergence"] = ((sh - sz) / (sh.abs() + sz.abs() + 1e-10)).rolling(5).mean()

    # nb_industry_rotation
    ind_history = []
    for _, row in panel.iterrows():
        ia = row.get("_ind_amounts", {})
        if isinstance(ia, dict) and ia:
            total = sum(abs(v) for v in ia.values()) + 1e-10
            ind_history.append({k: v / total for k, v in ia.items()})
        else:
            ind_history.append({})
    ind_df = pd.DataFrame(ind_history, index=panel.index).fillna(0)
    panel["nb_industry_rotation"] = ind_df.diff(20).std(axis=1).rolling(5).mean()

    # nb_active_share (use rolling on raw)
    panel["nb_active_share"] = panel["nb_active_share_raw"].rolling(5).mean()

    # 清理
    panel = panel.drop(
        columns=["daily_net_flow", "sh_net", "sz_net", "nb_size_median",
                 "nb_active_share_raw", "_ind_amounts"],
        errors="ignore",
    )

    valid_factors = [f for f, _ in OOS_FACTORS if f in panel.columns]
    print(f"  计算完成: {len(valid_factors)}/{len(OOS_FACTORS)} 因子可用")
    for f in valid_factors:
        v = panel[f].dropna()
        print(f"    {f:<35s}: {len(v)}天, mean={v.mean():.4f}")

    return panel


# ═══════════════════════════════════════════════════════
# Part 3: 仓位系数计算
# ═══════════════════════════════════════════════════════
def compute_coefficients(panel: pd.DataFrame, factor_name: str, direction: int) -> pd.Series:
    """因子值→百分位→仓位系数(0.2~1.0)，5日平滑。

    复用V2 backtest_modifier_factor逻辑:
      P>0.7 → 1.0 (满仓)
      P0.3-0.7 → 0.8
      P0.1-0.3 → 0.5
      P<0.1 → 0.3 (大幅减仓)
    """
    f = panel[factor_name].dropna()
    pct = f.rolling(252, min_periods=60).apply(
        lambda x: np.sum(x[:-1] < x[-1]) / max(len(x) - 1, 1), raw=True
    )
    if direction == -1:
        pct = 1 - pct

    coeff = pd.Series(0.8, index=pct.index)
    coeff[pct > 0.7] = 1.0
    coeff[(pct > 0.1) & (pct <= 0.3)] = 0.5
    coeff[pct <= 0.1] = 0.3
    coeff = coeff.rolling(5, min_periods=1).mean().clip(0.2, 1.0)

    return coeff


# ═══════════════════════════════════════════════════════
# Part 4: 叠加回测
# ═══════════════════════════════════════════════════════
@dataclass
class BacktestResult:
    label: str
    cagr: float
    vol: float
    sharpe: float
    mdd: float
    calmar: float
    reduce_pct: float  # 减仓天占比
    extra_cost: float  # 额外交易成本累计
    yearly: dict  # {year: (sharpe, mdd)}


def run_overlay_backtest(
    base_ret: pd.Series,
    coeff: pd.Series,
    label: str,
) -> BacktestResult:
    """在基线上叠加仓位系数。"""
    # 统一index为date类型再对齐
    br = base_ret.copy()
    br.index = pd.Index([d.date() if hasattr(d, 'date') and callable(d.date) else d for d in br.index])
    cf = coeff.copy()
    cf.index = pd.Index([d.date() if hasattr(d, 'date') and callable(d.date) else d for d in cf.index])
    common = br.index.intersection(cf.index)
    br = br.loc[common]
    cf = cf.loc[common]

    # 叠加
    modified_ret = br * cf + (1 - cf) * RF_DAILY

    # 额外交易成本
    delta_coeff = cf.diff().abs().fillna(0)
    extra_cost_series = delta_coeff * (EXTRA_COST_BPS / 10000)
    modified_ret = modified_ret - extra_cost_series
    total_extra_cost = float(extra_cost_series.sum())

    # 指标
    nav = (1 + modified_ret).cumprod()
    n_years = len(modified_ret) / 252
    cagr = (float(nav.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 else 0
    vol = float(modified_ret.std() * np.sqrt(252))
    sharpe = (cagr - RF_ANNUAL) / vol if vol > 0 else 0
    mdd = float(((nav - nav.cummax()) / nav.cummax()).min())
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0
    reduce_pct = float((cf < 0.95).mean())

    # 年度分解
    yearly = {}
    for year in range(BT_START.year, BT_END.year + 1):
        mask = pd.Series([d.year if hasattr(d, 'year') else pd.Timestamp(d).year for d in modified_ret.index], index=modified_ret.index) == year
        yr = modified_ret[mask]
        if len(yr) < 20:
            continue
        yr_nav = (1 + yr).cumprod()
        yr_cagr = float(yr_nav.iloc[-1]) ** (252 / len(yr)) - 1
        yr_vol = float(yr.std() * np.sqrt(252))
        yr_sharpe = (yr_cagr - RF_ANNUAL) / yr_vol if yr_vol > 0 else 0
        yr_mdd = float(((yr_nav - yr_nav.cummax()) / yr_nav.cummax()).min())
        yearly[year] = (round(yr_sharpe, 2), round(yr_mdd * 100, 1))

    return BacktestResult(
        label=label, cagr=cagr, vol=vol, sharpe=sharpe, mdd=mdd,
        calmar=calmar, reduce_pct=reduce_pct, extra_cost=total_extra_cost,
        yearly=yearly,
    )


# ═══════════════════════════════════════════════════════
# Part 5: 报告
# ═══════════════════════════════════════════════════════
def print_report(baseline: BacktestResult, results: list[BacktestResult]) -> None:
    print("\n")
    print("═" * 90)
    print("  模板11: 北向MODIFIER仓位调节回测")
    print(f"  基准: Top-{TOP_N}等权月度 | {BT_START} ~ {BT_END}")
    print("═" * 90)

    header = (
        f"  {'策略':<30s} │ {'CAGR%':>7s} │ {'Sharpe':>7s} │ {'MDD%':>7s} │ "
        f"{'Calmar':>7s} │ {'减仓天%':>7s} │ {'额外成本%':>8s}"
    )
    print(header)
    print(f"  {'─' * 30}─┼─{'─' * 7}─┼─{'─' * 7}─┼─{'─' * 7}─┼─{'─' * 7}─┼─{'─' * 7}─┼─{'─' * 8}")

    all_results = [baseline] + results
    for r in all_results:
        # 判定标记
        if r.label != baseline.label:
            calmar_improve = (r.calmar - baseline.calmar) / abs(baseline.calmar) if baseline.calmar != 0 else 0
            sharpe_ratio = r.sharpe / baseline.sharpe if baseline.sharpe != 0 else 0
            if calmar_improve > 0.2 and sharpe_ratio >= 0.9:
                mark = " ★"
            elif r.reduce_pct > 0.4:
                mark = " ⚠️"
            else:
                mark = ""
        else:
            mark = ""

        print(
            f"  {r.label:<30s} │ {r.cagr*100:>+7.1f} │ {r.sharpe:>7.2f} │ "
            f"{r.mdd*100:>+7.1f} │ {r.calmar:>7.2f} │ {r.reduce_pct*100:>6.1f}% │ "
            f"{r.extra_cost*100:>7.2f}%{mark}"
        )

    # 最佳信号
    if results:
        best = max(results, key=lambda r: r.calmar)
        print(f"\n  最佳Calmar: {best.label} (Calmar={best.calmar:.2f} vs 基线{baseline.calmar:.2f})")

    # 年度分解（基线 + 最佳）
    if results:
        best = max(results, key=lambda r: r.calmar)
        print(f"\n  年度分解 (基线 vs {best.label}):")
        print(f"  {'年份':>6s}  {'基线Sharpe':>10s}  {'基线MDD%':>9s}  {'MODIFIER Sharpe':>15s}  {'MODIFIER MDD%':>13s}")
        for year in sorted(set(list(baseline.yearly.keys()) + list(best.yearly.keys()))):
            b_s, b_m = baseline.yearly.get(year, (0, 0))
            m_s, m_m = best.yearly.get(year, (0, 0))
            print(f"  {year:>6d}  {b_s:>+10.2f}  {b_m:>+9.1f}  {m_s:>+15.2f}  {m_m:>+13.1f}")

    # 结论
    print("\n  结论:")
    improved = [r for r in results if r.calmar > baseline.calmar * 1.1 and r.sharpe >= baseline.sharpe * 0.85]
    if improved:
        print(f"  {len(improved)}个信号改善Calmar(>10%)且保持Sharpe(>85%基线):")
        for r in sorted(improved, key=lambda x: -x.calmar):
            delta_mdd = (r.mdd - baseline.mdd) * 100
            print(f"    {r.label}: Calmar={r.calmar:.2f}, MDD改善{delta_mdd:+.1f}pp, 减仓{r.reduce_pct*100:.0f}%天")
        print(f"  推荐: {improved[0].label}")
    else:
        print("  无信号能有效改善Calmar且保持Sharpe")
        mdd_improved = [r for r in results if r.mdd > baseline.mdd]
        if mdd_improved:
            best_mdd = min(mdd_improved, key=lambda r: abs(r.mdd))
            print(f"  MDD最优: {best_mdd.label} (MDD={best_mdd.mdd*100:.1f}% vs 基线{baseline.mdd*100:.1f}%)")
            print(f"    但Sharpe={best_mdd.sharpe:.2f} vs 基线{baseline.sharpe:.2f}")
        print("  北向MODIFIER降级为G1特征池备选")

    print(f"\n{'═' * 90}\n")


# ═══════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════
def main() -> None:
    conn = _get_sync_conn()

    # Part 1: 基线
    base_ret = build_top20_daily_returns(conn)
    baseline = run_overlay_backtest(
        base_ret, pd.Series(1.0, index=base_ret.index), f"基线(Top-{TOP_N}满仓)"
    )

    # Part 2: MODIFIER面板
    panel = build_modifier_panel(conn)

    # Part 3+4: 逐因子叠加回测
    print("\n[Part 3+4] MODIFIER叠加回测...")
    results = []
    for fname, direction in OOS_FACTORS:
        if fname not in panel.columns:
            print(f"  {fname}: 不在面板中, 跳过")
            continue

        coeff = compute_coefficients(panel, fname, direction)
        r = run_overlay_backtest(base_ret, coeff, f"+ {fname}")
        results.append(r)
        print(f"  {fname:<35s}: Sharpe={r.sharpe:.2f} MDD={r.mdd*100:.1f}% Calmar={r.calmar:.2f} 减仓{r.reduce_pct*100:.0f}%")

    # Part 5: 报告
    print_report(baseline, results)

    conn.close()


if __name__ == "__main__":
    main()
