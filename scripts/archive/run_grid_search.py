#!/usr/bin/env python3
"""路线A: 组合构建参数敏感性分析。

18种配置: Top-N(20/30/50) × 频率(biweekly/monthly) × 行业约束(20%/25%/30%)
全部+Beta对冲, 5因子等权。
"""

import gc
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import warnings

warnings.filterwarnings("ignore")

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.signal_engine import (
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from run_backtest import (
    load_benchmark,
    load_factor_values,
    load_industry,
    load_price_data,
    load_universe,
)

from app.services.price_utils import _get_sync_conn


def beta_hedge_returns(strat_ret: pd.Series, bench_ret: pd.Series, window: int = 60) -> pd.Series:
    """Rolling Beta对冲: hedged_r = strat_r - beta * bench_r。"""
    ci = strat_ret.index.intersection(bench_ret.index)
    sr = strat_ret.reindex(ci)
    br = bench_ret.reindex(ci)

    hedged = np.empty(len(sr))
    sr_vals = sr.values
    br_vals = br.values

    for i in range(len(sr_vals)):
        s = max(0, i - window)
        _s = sr_vals[s:i+1]
        _b = br_vals[s:i+1]
        if len(_s) > 5:
            cov_matrix = np.cov(_s, _b)
            beta = cov_matrix[0, 1] / max(cov_matrix[1, 1], 1e-10)
            beta = np.clip(beta, -2, 2)
        else:
            beta = 0
        hedged[i] = sr_vals[i] - beta * br_vals[i]

    return pd.Series(hedged, index=ci)


def calc_yearly_sharpe(returns: pd.Series) -> dict[int, float]:
    """计算各年度Sharpe。"""
    result = {}
    for y in range(2021, 2026):
        yr = returns[returns.index.map(lambda d: d.year == y)]
        if len(yr) > 20 and yr.std() > 0:
            result[y] = float(yr.mean() / yr.std() * np.sqrt(252))
        else:
            result[y] = 0.0
    return result


def bootstrap_ci(returns: pd.Series, n_boot: int = 1000, seed: int = 42) -> float:
    """Bootstrap Sharpe 95% CI下界。"""
    rng = np.random.RandomState(seed)
    n = len(returns)
    vals = returns.values
    sharpes = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, size=n)
        sample = vals[idx]
        std = sample.std()
        sharpes[i] = sample.mean() / std * np.sqrt(252) if std > 0 else 0
    return float(np.percentile(sharpes, 2.5))


def main():
    t_total = time.time()
    conn = _get_sync_conn()
    start = datetime.strptime("2021-01-01", "%Y-%m-%d").date()
    end = datetime.strptime("2025-12-31", "%Y-%m-%d").date()

    factors = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]

    # ── 1. 加载共享数据 ──
    print("=" * 80, flush=True)
    print("路线A: 18种组合构建参数敏感性分析", flush=True)
    print("5因子等权 + Rolling 60d Beta对冲", flush=True)
    print("=" * 80, flush=True)

    print("\n[1/4] 加载行业+价格+基准数据...", flush=True)
    t0 = time.time()
    industry = load_industry(conn)
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    print(f"  完成 ({time.time()-t0:.1f}s), price_data={len(price_data)} rows", flush=True)

    # ── 2. 预加载调仓日因子+universe ──
    print("\n[2/4] 预加载调仓日因子数据...", flush=True)
    t0 = time.time()
    all_rebal_dates = {}
    for freq in ["biweekly", "monthly"]:
        all_rebal_dates[freq] = get_rebalance_dates(start, end, freq=freq, conn=conn)
        print(f"  {freq}: {len(all_rebal_dates[freq])} 调仓日", flush=True)

    all_dates = set()
    for dates in all_rebal_dates.values():
        all_dates.update(dates)

    fv_cache = {}
    uni_cache = {}
    for i, rd in enumerate(sorted(all_dates)):
        fv_cache[rd] = load_factor_values(rd, conn)
        uni_cache[rd] = load_universe(rd, conn)
        if (i + 1) % 50 == 0:
            print(f"  已缓存 {i+1}/{len(all_dates)} 日...", flush=True)

    print(f"  完成: 缓存 {len(fv_cache)} 日 ({time.time()-t0:.1f}s)", flush=True)

    # ── 3. 网格搜索 ──
    print("\n[3/4] 运行18种配置回测...", flush=True)
    top_ns = [20, 30, 50]
    freqs = ["biweekly", "monthly"]
    ind_caps = [0.20, 0.25, 0.30]

    header = (
        f"{'#':>2} {'Top-N':>5} {'Freq':>8} {'IndCap':>6} | "
        f"{'Sharpe':>6} {'Ret%':>6} {'MDD%':>6} {'CIlo':>5} {'Turn%':>5} | "
        f"{'2021':>6} {'2022':>6} {'2023':>6} {'2024':>6} {'2025':>6} | {'Time':>5}"
    )
    print(header, flush=True)
    print("-" * len(header), flush=True)

    results = []
    config_idx = 0

    for top_n in top_ns:
        for freq in freqs:
            for ind_cap in ind_caps:
                config_idx += 1
                t1 = time.time()
                try:
                    sig_config = SignalConfig(
                        factor_names=factors,
                        top_n=top_n,
                        rebalance_freq=freq,
                        industry_cap=ind_cap,
                    )
                    bt_config = BacktestConfig(initial_capital=1_000_000)

                    composer = SignalComposer(sig_config)
                    builder = PortfolioBuilder(sig_config)

                    rebal_dates = all_rebal_dates[freq]
                    tp = {}
                    pw = {}
                    for rd in rebal_dates:
                        fv = fv_cache[rd]
                        if fv.empty:
                            continue
                        uni = uni_cache[rd]
                        scores = composer.compose(fv, uni)
                        if scores.empty:
                            continue
                        target = builder.build(scores, industry, pw)
                        if target:
                            tp[rd] = target
                            pw = target

                    result = SimpleBacktester(bt_config).run(tp, price_data, benchmark_data)
                    nav = result.daily_nav
                    bnav = result.benchmark_nav

                    sr = nav.pct_change().dropna()
                    br = bnav.pct_change().dropna()

                    # Beta hedge
                    hr = beta_hedge_returns(sr, br, window=60)
                    hn = (1 + hr).cumprod() * 1e6

                    ann = float((hn.iloc[-1] / hn.iloc[0]) ** (252 / len(hn)) - 1)
                    sh = float(hr.mean() / hr.std() * np.sqrt(252)) if hr.std() > 0 else 0
                    md = float(((hn - hn.expanding().max()) / hn.expanding().max()).min())

                    turn = result.turnover_series
                    avg_turn = float(turn.mean() * 100) if len(turn) > 0 else 0

                    cilo = bootstrap_ci(hr)
                    yr_sh = calc_yearly_sharpe(hr)

                    elapsed = time.time() - t1
                    freq_label = "biweek" if freq == "biweekly" else "month"
                    print(
                        f"{config_idx:>2} {top_n:>5} {freq_label:>8} {ind_cap:>5.0%} | "
                        f"{sh:>6.2f} {ann*100:>5.1f}% {md*100:>5.1f}% {cilo:>5.2f} {avg_turn:>4.1f}% | "
                        f"{yr_sh[2021]:>6.2f} {yr_sh[2022]:>6.2f} {yr_sh[2023]:>6.2f} "
                        f"{yr_sh[2024]:>6.2f} {yr_sh[2025]:>6.2f} | {elapsed:>4.0f}s",
                        flush=True,
                    )

                    results.append({
                        "top_n": top_n, "freq": freq, "ind_cap": ind_cap,
                        "sharpe": sh, "ann_ret": ann, "mdd": md, "ci_lo": cilo,
                        "turnover": avg_turn, "yr_sharpes": yr_sh,
                    })

                except Exception as e:
                    print(f"{config_idx:>2} Top{top_n} {freq} IndCap={ind_cap:.0%} ERROR: {e}", flush=True)
                    traceback.print_exc()

                gc.collect()

    # ── 4. 汇总分析 ──
    print(f"\n{'='*80}", flush=True)
    print("[4/4] 汇总分析", flush=True)
    print(f"{'='*80}", flush=True)

    if not results:
        print("ERROR: 无有效结果!", flush=True)
        conn.close()
        return

    results.sort(key=lambda x: x["sharpe"], reverse=True)

    # Top 5
    print("\n📊 Top 5 配置 (by Sharpe):")
    for i, r in enumerate(results[:5]):
        fl = "biweek" if r["freq"] == "biweekly" else "month"
        print(
            f"  #{i+1}: Top{r['top_n']} {fl} IndCap={r['ind_cap']:.0%} → "
            f"Sharpe={r['sharpe']:.2f}, Ret={r['ann_ret']*100:.1f}%, "
            f"MDD={r['mdd']*100:.1f}%, Turn={r['turnover']:.1f}%, CI_lo={r['ci_lo']:.2f}"
        )

    # 稳健性
    all_sharpes = [r["sharpe"] for r in results]
    print("\n📊 稳健性分析:")
    print(f"  全部{len(results)}种配置Sharpe: min={min(all_sharpes):.2f}, max={max(all_sharpes):.2f}, median={np.median(all_sharpes):.2f}")
    print(f"  Sharpe > 1.0: {sum(1 for s in all_sharpes if s > 1.0)}/{len(results)}")
    print(f"  Sharpe > 1.2: {sum(1 for s in all_sharpes if s > 1.2)}/{len(results)}")
    print(f"  Sharpe > 1.3: {sum(1 for s in all_sharpes if s > 1.3)}/{len(results)}")
    print(f"  Sharpe > 1.4: {sum(1 for s in all_sharpes if s > 1.4)}/{len(results)}")

    # 各维度边际效应
    print("\n📊 各维度边际效应 (avg Sharpe):")
    for tn in top_ns:
        avg = np.mean([r["sharpe"] for r in results if r["top_n"] == tn])
        print(f"  Top-N={tn}: {avg:.3f}")
    for freq in freqs:
        avg = np.mean([r["sharpe"] for r in results if r["freq"] == freq])
        fl = "biweekly" if freq == "biweekly" else "monthly"
        print(f"  Freq={fl}: {avg:.3f}")
    for ic in ind_caps:
        avg = np.mean([r["sharpe"] for r in results if r["ind_cap"] == ic])
        print(f"  IndCap={ic:.0%}: {avg:.3f}")

    # 各维度MDD边际效应
    print("\n📊 各维度边际效应 (avg MDD%):")
    for tn in top_ns:
        avg = np.mean([r["mdd"] * 100 for r in results if r["top_n"] == tn])
        print(f"  Top-N={tn}: {avg:.1f}%")
    for freq in freqs:
        avg = np.mean([r["mdd"] * 100 for r in results if r["freq"] == freq])
        fl = "biweekly" if freq == "biweekly" else "monthly"
        print(f"  Freq={fl}: {avg:.1f}%")
    for ic in ind_caps:
        avg = np.mean([r["mdd"] * 100 for r in results if r["ind_cap"] == ic])
        print(f"  IndCap={ic:.0%}: {avg:.1f}%")

    # 门禁评估
    best = results[0]
    print(f"\n{'='*80}")
    fl = "biweek" if best["freq"] == "biweekly" else "month"
    print("📋 门禁评估:")
    print(f"  最优配置: Top{best['top_n']} {fl} IndCap={best['ind_cap']:.0%}")
    print(f"  Sharpe = {best['sharpe']:.2f} (门禁: >1.4→更新基线)")
    print("  当前基线: Sharpe 1.28 (Top20 biweek IndCap=25%)")
    if best["sharpe"] > 1.4:
        print("  → ✅ 超过1.4门禁，建议更新基线再进Paper Trading")
    elif best["sharpe"] > 1.28:
        print("  → ⚠️ 小幅提升但未超1.4，需讨论是否更新基线")
    else:
        print("  → 保持当前基线不变")

    # 保存JSON
    out_path = Path(__file__).resolve().parent / "grid_search_results.json"
    save_results = []
    for r in results:
        sr = dict(r)
        sr["yr_sharpes"] = {str(k): v for k, v in sr["yr_sharpes"].items()}
        save_results.append(sr)
    with open(out_path, "w") as f:
        json.dump(save_results, f, indent=2)
    print(f"\n结果已保存: {out_path}")

    total_time = time.time() - t_total
    print(f"\n总耗时: {total_time/60:.1f} 分钟")
    print("=== 路线A完成 ===")

    conn.close()


if __name__ == "__main__":
    main()
