#!/usr/bin/env python
"""Phase 2.1 Part 4: 对比验证矩阵 #0-#4。

#0: 基线 — SN b=0.50 等权Top-20 (CORE 5因子)
#1: IC加权 — factor_ic_history中IC_IR作权重
#2: MVO — riskfolio-lib MVO on Top-40候选
#3: IC加权+MVO — IC加权选股 + MVO优化权重
#4: 融合MLP — Layer 1 LightGBM + Layer 2 PortfolioNetwork

全部通过 SimpleBacktester.run() 回测 (铁律16)。

Usage:
    cd backend && python ../scripts/research/phase21_comparison_matrix.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"

# ─── 公共函数 ─────────────────────────────────────────

def load_all_data():
    """加载12年price_data + benchmark。"""
    price_parts, bench_parts = [], []
    for y in range(2014, 2027):
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
    return price, bench


def get_monthly_rebalance_dates(trade_dates: list) -> list:
    df = pd.DataFrame({"td": trade_dates})
    df["ym"] = df["td"].apply(lambda d: (d.year, d.month))
    return df.groupby("ym")["td"].max().sort_values().tolist()


def load_factor_data():
    """从DB加载CORE 5因子neutral_value。"""
    import os

    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "quantmind_v2"),
        user=os.getenv("PG_USER", "xin"),
        host=os.getenv("PG_HOST", "localhost"),
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )
    core_factors = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    placeholders = ",".join(["%s"] * len(core_factors))
    query = f"""
        SELECT code, trade_date, factor_name, neutral_value
        FROM factor_values
        WHERE factor_name IN ({placeholders})
          AND neutral_value IS NOT NULL
    """
    df = pd.read_sql(query, conn, params=core_factors)
    conn.close()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


def load_ic_weights():
    """从factor_ic_history读取IC_IR权重。"""
    import os

    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "quantmind_v2"),
        user=os.getenv("PG_USER", "xin"),
        host=os.getenv("PG_HOST", "localhost"),
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT factor_name,
               AVG(ic_20d) / NULLIF(STDDEV(ic_20d), 0) as ic_ir
        FROM factor_ic_history
        WHERE factor_name IN ('turnover_mean_20','volatility_20','reversal_20','amihud_20','bp_ratio')
          AND ic_20d IS NOT NULL
        GROUP BY factor_name
    """)
    rows = cur.fetchall()
    conn.close()
    return {r[0]: float(r[1]) if r[1] else 0 for r in rows}


def build_exclusion_set(price, td):
    day = price[price["trade_date"] == td]
    exclude = set()
    if "is_st" in day.columns:
        exclude |= set(day.loc[day["is_st"], "code"])
    if "is_suspended" in day.columns:
        exclude |= set(day.loc[day["is_suspended"], "code"])
    if "is_new_stock" in day.columns:
        exclude |= set(day.loc[day["is_new_stock"], "code"])
    if "board" in day.columns:
        exclude |= set(day.loc[day["board"] == "bse", "code"])
    return exclude


def run_backtest(name, target_portfolios, price, bench):
    from engines.backtest import BacktestConfig, SimpleBacktester
    from engines.metrics import TRADING_DAYS_PER_YEAR, calc_max_drawdown, calc_sharpe

    config = BacktestConfig(
        initial_capital=1_000_000.0,
        rebalance_freq="monthly",
        historical_stamp_tax=True,
        slippage_mode="volume_impact",
    )
    bt = SimpleBacktester(config)
    result = bt.run(target_portfolios=target_portfolios, price_data=price, benchmark_data=bench)
    nav = result.daily_nav
    rets = result.daily_returns
    sharpe = calc_sharpe(rets) if len(rets) > 1 else 0
    mdd = calc_max_drawdown(nav)
    ann_ret = (nav.iloc[-1] / nav.iloc[0]) ** (TRADING_DAYS_PER_YEAR / len(nav)) - 1 if len(nav) > 1 else 0
    return {"name": name, "sharpe": sharpe, "mdd": mdd, "ann_ret": ann_ret,
            "n_rebal": len(target_portfolios), "final_nav": float(nav.iloc[-1])}


# ─── Strategy #0: Baseline (SN b=0.50 等权) ────────────

def strategy_0_baseline(factor_df, price, rebal_dates):
    """#0 Baseline: 等权Top-20 + SN b=0.50 (复用现有信号路径)。"""
    from engines.signal_engine import FACTOR_DIRECTION

    directions = {f: FACTOR_DIRECTION.get(f, 1)
                  for f in ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]}

    # Build composite score per (code, trade_date)
    close_wide = price.pivot_table(index="trade_date", columns="code", values="close").sort_index()
    ln_mcap_wide = np.log(close_wide + 1e-12)

    target_portfolios = {}
    for rd in rebal_dates:
        # Get latest factor values on or before rd
        day_factors = factor_df[factor_df["trade_date"] <= rd]
        if day_factors.empty:
            continue
        latest = day_factors["trade_date"].max()
        day_factors = day_factors[day_factors["trade_date"] == latest]

        # Pivot: code → {factor_name: value}
        pivot = day_factors.pivot_table(index="code", columns="factor_name", values="neutral_value")

        # Composite score: 等权 with direction
        scores = pd.Series(0.0, index=pivot.index)
        n_factors = 0
        for fn, direction in directions.items():
            if fn in pivot.columns:
                scores += direction * pivot[fn].fillna(0)
                n_factors += 1
        if n_factors > 0:
            scores /= n_factors

        # SN: adj_score = score - 0.50 * zscore(ln_mcap)
        if rd in ln_mcap_wide.index:
            mcap = ln_mcap_wide.loc[rd]
            common = scores.index.intersection(mcap.dropna().index)
            scores = scores.loc[common]
            mcap_z = (mcap.loc[common] - mcap.loc[common].mean()) / (mcap.loc[common].std() + 1e-12)
            scores = scores - 0.50 * mcap_z

        # Exclude
        exclude = build_exclusion_set(price, rd)
        scores = scores.drop(labels=exclude.intersection(scores.index), errors="ignore")
        scores = scores.replace([np.inf, -np.inf], np.nan).dropna()

        if len(scores) >= 20:
            top = scores.nlargest(20).index.tolist()
            w = 1.0 / len(top)
            target_portfolios[rd] = {c: w for c in top}

    return target_portfolios


# ─── Strategy #1: IC加权 ────────────────────────────

def strategy_1_ic_weighted(factor_df, price, rebal_dates, ic_weights):
    """#1 IC加权: composite = Σ(factor × IC_IR) / Σ|IC_IR|。"""
    close_wide = price.pivot_table(index="trade_date", columns="code", values="close").sort_index()
    ln_mcap_wide = np.log(close_wide + 1e-12)

    from engines.signal_engine import FACTOR_DIRECTION
    directions = {f: FACTOR_DIRECTION.get(f, 1)
                  for f in ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]}

    total_abs_ir = sum(abs(v) for v in ic_weights.values()) + 1e-12

    target_portfolios = {}
    for rd in rebal_dates:
        day_factors = factor_df[factor_df["trade_date"] <= rd]
        if day_factors.empty:
            continue
        latest = day_factors["trade_date"].max()
        day_factors = day_factors[day_factors["trade_date"] == latest]
        pivot = day_factors.pivot_table(index="code", columns="factor_name", values="neutral_value")

        scores = pd.Series(0.0, index=pivot.index)
        for fn, direction in directions.items():
            if fn in pivot.columns and fn in ic_weights:
                ir = ic_weights[fn]
                scores += direction * ir * pivot[fn].fillna(0) / total_abs_ir

        # SN
        if rd in ln_mcap_wide.index:
            mcap = ln_mcap_wide.loc[rd]
            common = scores.index.intersection(mcap.dropna().index)
            scores = scores.loc[common]
            mcap_z = (mcap.loc[common] - mcap.loc[common].mean()) / (mcap.loc[common].std() + 1e-12)
            scores = scores - 0.50 * mcap_z

        exclude = build_exclusion_set(price, rd)
        scores = scores.drop(labels=exclude.intersection(scores.index), errors="ignore")
        scores = scores.replace([np.inf, -np.inf], np.nan).dropna()

        if len(scores) >= 20:
            top = scores.nlargest(20).index.tolist()
            w = 1.0 / len(top)
            target_portfolios[rd] = {c: w for c in top}

    return target_portfolios


# ─── Strategy #2: MVO ────────────────────────────────

def strategy_2_mvo(factor_df, price, rebal_dates):
    """#2 MVO: CORE 5等权得分选Top-40, riskfolio MVO优化权重。"""
    try:
        import riskfolio as rp
    except ImportError:
        print("  riskfolio-lib not installed, skipping MVO")
        return {}

    from engines.signal_engine import FACTOR_DIRECTION
    directions = {f: FACTOR_DIRECTION.get(f, 1)
                  for f in ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]}

    close_wide = price.pivot_table(index="trade_date", columns="code", values="close").sort_index()
    daily_ret = close_wide.pct_change(fill_method=None)
    trade_dates_list = sorted(close_wide.index)
    td_idx = {d: i for i, d in enumerate(trade_dates_list)}

    target_portfolios = {}
    for rd in rebal_dates:
        day_factors = factor_df[factor_df["trade_date"] <= rd]
        if day_factors.empty:
            continue
        latest = day_factors["trade_date"].max()
        day_factors = day_factors[day_factors["trade_date"] == latest]
        pivot = day_factors.pivot_table(index="code", columns="factor_name", values="neutral_value")

        scores = pd.Series(0.0, index=pivot.index)
        n_f = 0
        for fn, direction in directions.items():
            if fn in pivot.columns:
                scores += direction * pivot[fn].fillna(0)
                n_f += 1
        if n_f > 0:
            scores /= n_f

        exclude = build_exclusion_set(price, rd)
        scores = scores.drop(labels=exclude.intersection(scores.index), errors="ignore")
        scores = scores.replace([np.inf, -np.inf], np.nan).dropna()

        if len(scores) < 40:
            continue

        candidates = scores.nlargest(40).index.tolist()

        # MVO with riskfolio
        if rd not in td_idx:
            continue
        idx = td_idx[rd]
        lookback = max(idx - 120, 0)
        hist = daily_ret.iloc[lookback:idx][candidates].dropna(axis=1, how="all").dropna()

        if len(hist) < 60 or len(hist.columns) < 10:
            # Fallback: Top-20 equal weight
            top20 = scores.nlargest(20).index.tolist()
            target_portfolios[rd] = {c: 1.0 / len(top20) for c in top20}
            continue

        try:
            port = rp.Portfolio(returns=hist)
            port.assets_stats(method_mu="hist", method_cov="ledoit_wolf")
            port.upperlng = 0.10
            w_df = port.optimization(model="Classic", rm="MV", obj="Sharpe", rf=0, l=0, hist=True)
            if w_df is not None and not w_df.empty:
                weights = w_df["weights"].to_dict()
                weights = {k: v for k, v in weights.items() if v > 0.001}
                if weights:
                    total = sum(weights.values())
                    target_portfolios[rd] = {k: v / total for k, v in weights.items()}
                    continue
        except Exception:
            pass

        top20 = scores.nlargest(20).index.tolist()
        target_portfolios[rd] = {c: 1.0 / len(top20) for c in top20}

    return target_portfolios


# ─── Strategy #3: IC加权 + MVO ────────────────────────

def strategy_3_ic_mvo(factor_df, price, rebal_dates, ic_weights):
    """#3 IC加权选股 + MVO优化权重。"""
    try:
        import riskfolio as rp
    except ImportError:
        print("  riskfolio-lib not installed, skipping IC+MVO")
        return {}

    from engines.signal_engine import FACTOR_DIRECTION
    directions = {f: FACTOR_DIRECTION.get(f, 1)
                  for f in ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]}
    total_abs_ir = sum(abs(v) for v in ic_weights.values()) + 1e-12

    close_wide = price.pivot_table(index="trade_date", columns="code", values="close").sort_index()
    daily_ret = close_wide.pct_change(fill_method=None)
    trade_dates_list = sorted(close_wide.index)
    td_idx = {d: i for i, d in enumerate(trade_dates_list)}

    target_portfolios = {}
    for rd in rebal_dates:
        day_factors = factor_df[factor_df["trade_date"] <= rd]
        if day_factors.empty:
            continue
        latest = day_factors["trade_date"].max()
        day_factors = day_factors[day_factors["trade_date"] == latest]
        pivot = day_factors.pivot_table(index="code", columns="factor_name", values="neutral_value")

        # IC-weighted scores
        scores = pd.Series(0.0, index=pivot.index)
        for fn, direction in directions.items():
            if fn in pivot.columns and fn in ic_weights:
                ir = ic_weights[fn]
                scores += direction * ir * pivot[fn].fillna(0) / total_abs_ir

        exclude = build_exclusion_set(price, rd)
        scores = scores.drop(labels=exclude.intersection(scores.index), errors="ignore")
        scores = scores.replace([np.inf, -np.inf], np.nan).dropna()

        if len(scores) < 40:
            continue

        candidates = scores.nlargest(40).index.tolist()

        if rd not in td_idx:
            continue
        idx = td_idx[rd]
        lookback = max(idx - 120, 0)
        hist = daily_ret.iloc[lookback:idx][candidates].dropna(axis=1, how="all").dropna()

        if len(hist) < 60 or len(hist.columns) < 10:
            top20 = scores.nlargest(20).index.tolist()
            target_portfolios[rd] = {c: 1.0 / len(top20) for c in top20}
            continue

        try:
            port = rp.Portfolio(returns=hist)
            port.assets_stats(method_mu="hist", method_cov="ledoit_wolf")
            port.upperlng = 0.10
            w_df = port.optimization(model="Classic", rm="MV", obj="Sharpe", rf=0, l=0, hist=True)
            if w_df is not None and not w_df.empty:
                weights = w_df["weights"].to_dict()
                weights = {k: v for k, v in weights.items() if v > 0.001}
                if weights:
                    total = sum(weights.values())
                    target_portfolios[rd] = {k: v / total for k, v in weights.items()}
                    continue
        except Exception:
            pass

        top20 = scores.nlargest(20).index.tolist()
        target_portfolios[rd] = {c: 1.0 / len(top20) for c in top20}

    return target_portfolios


# ─── Strategy #4: 融合MLP (从Part 3结果读取) ─────────

def strategy_4_fusion(exp_key: str = "A"):
    """#4 融合MLP: 读取Part 3保存的结果。"""
    result_path = CACHE_DIR / "phase21" / f"l2_result_exp_{exp_key.lower()}.json"
    if not result_path.exists():
        print(f"  #4 Fusion results not found: {result_path}")
        print(f"  Run Part 3 first: phase21_portfolio_network.py --exp {exp_key}")
        return None
    with open(result_path) as f:
        return json.load(f)


# ─── Main ─────────────────────────────────────────────

def main():
    t_start = time.time()

    print("=" * 70)
    print("Phase 2.1 Part 4: Comparison Matrix")
    print("=" * 70)

    # Load data
    print("\n[1] Loading data...")
    price, bench = load_all_data()
    trade_dates = sorted(price["trade_date"].unique())
    rebal_dates = get_monthly_rebalance_dates(trade_dates)
    rebal_dates = [d for d in rebal_dates if d <= date(2026, 3, 1)]
    print(f"    {len(price):,} price rows, {len(rebal_dates)} rebal dates")

    print("\n[2] Loading factor data...")
    factor_df = load_factor_data()
    print(f"    {len(factor_df):,} factor rows")

    print("\n[3] Loading IC weights...")
    ic_weights = load_ic_weights()
    print(f"    IC_IR: {ic_weights}")

    # Run strategies
    results = []

    # #0 Baseline
    print("\n[#0] Baseline: SN b=0.50 等权 Top-20...")
    tp0 = strategy_0_baseline(factor_df, price, rebal_dates)
    results.append(run_backtest("#0 Baseline (SN+EW)", tp0, price, bench))

    # #1 IC-weighted
    print("\n[#1] IC加权...")
    tp1 = strategy_1_ic_weighted(factor_df, price, rebal_dates, ic_weights)
    results.append(run_backtest("#1 IC-Weighted", tp1, price, bench))

    # #2 MVO
    print("\n[#2] MVO (riskfolio-lib)...")
    tp2 = strategy_2_mvo(factor_df, price, rebal_dates)
    if tp2:
        results.append(run_backtest("#2 MVO", tp2, price, bench))
    else:
        results.append({"name": "#2 MVO", "sharpe": 0, "mdd": 0, "ann_ret": 0, "n_rebal": 0, "final_nav": 0})

    # #3 IC+MVO
    print("\n[#3] IC加权 + MVO...")
    tp3 = strategy_3_ic_mvo(factor_df, price, rebal_dates, ic_weights)
    if tp3:
        results.append(run_backtest("#3 IC+MVO", tp3, price, bench))
    else:
        results.append({"name": "#3 IC+MVO", "sharpe": 0, "mdd": 0, "ann_ret": 0, "n_rebal": 0, "final_nav": 0})

    # #4 Fusion MLP (from Part 3)
    print("\n[#4] Fusion MLP (from Part 3)...")
    fusion = strategy_4_fusion("A")
    if fusion:
        results.append({
            "name": "#4 Fusion MLP",
            "sharpe": fusion.get("sharpe", 0),
            "mdd": fusion.get("mdd", 0),
            "ann_ret": fusion.get("ann_ret", 0),
            "n_rebal": fusion.get("n_portfolios", 0),
            "final_nav": 0,
        })
    else:
        results.append({"name": "#4 Fusion MLP", "sharpe": 0, "mdd": 0, "ann_ret": 0, "n_rebal": 0, "final_nav": 0})

    # Summary table
    print(f"\n{'='*80}")
    print("COMPARISON MATRIX: Phase 2.1")
    print(f"{'='*80}")
    print(f"{'Strategy':<30} {'Sharpe':>8} {'MDD':>10} {'Ann Ret':>10} {'Rebal':>7}")
    print("-" * 80)
    for r in results:
        print(f"{r['name']:<30} {r['sharpe']:>8.4f} {r['mdd']:>10.2%} "
              f"{r['ann_ret']:>10.2%} {r['n_rebal']:>7}")

    # Go condition
    baseline_sharpe = 0.6521
    print(f"\n  Go condition: OOS Sharpe > {baseline_sharpe * 1.1:.4f} (1.1× baseline)")
    for r in results:
        if r["sharpe"] > baseline_sharpe * 1.1:
            print(f"  ✅ {r['name']}: Sharpe={r['sharpe']:.4f} > {baseline_sharpe * 1.1:.4f}")
        else:
            print(f"  ❌ {r['name']}: Sharpe={r['sharpe']:.4f} ≤ {baseline_sharpe * 1.1:.4f}")

    # Save
    out_path = CACHE_DIR / "phase21" / "comparison_matrix.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Saved: {out_path}")

    elapsed = time.time() - t_start
    print(f"\nTotal elapsed: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
