#!/usr/bin/env python3
"""回撤控制三层叠加验证 — 行业分散/Top-N/TargetVol/PMS叠加。

内存安全: 单进程运行, 共享数据加载一次。
"""
import logging, os, sys, time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, PMSConfig, SimpleBacktester
from engines.signal_engine import (PAPER_TRADING_CONFIG, PortfolioBuilder,
                                   SignalComposer, SignalConfig, get_rebalance_dates)
from engines.slippage_model import SlippageConfig
from engines.metrics import generate_report
from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

START, END = "2021-01-01", "2026-03-31"
CAPITAL = 1_000_000


# ============================================================
# Data Loading (once, shared across all experiments)
# ============================================================
def load_shared_data(conn):
    logger.info("Loading shared data...")
    rebalance_dates = get_rebalance_dates(
        datetime.strptime(START, "%Y-%m-%d").date(),
        datetime.strptime(END, "%Y-%m-%d").date(),
        freq="monthly", conn=conn)
    industry = pd.read_sql("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
                            conn).set_index("code")["industry_sw1"].fillna("其他")
    price_data = pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount, k.up_limit, k.down_limit, db.turnover_rate
           FROM klines_daily k LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
           ORDER BY k.trade_date, k.code""", conn, params=(START, END))
    benchmark_data = pd.read_sql(
        "SELECT trade_date, close FROM index_daily WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s ORDER BY trade_date",
        conn, params=(START, END))

    # Preload all factor values for rebalance dates
    factor_cache = {}
    for rd in rebalance_dates:
        fv = pd.read_sql("SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
                          conn, params=(rd,))
        factor_cache[rd] = fv

    # Preload universe for each rebalance date
    universe_cache = {}
    for rd in rebalance_dates:
        uni = pd.read_sql(
            "SELECT k.code FROM klines_daily k JOIN symbols s ON k.code = s.code "
            "LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date "
            "WHERE k.trade_date = %s AND k.volume > 0 AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%' "
            "AND (s.list_date IS NULL OR s.list_date <= %s::date - INTERVAL '60 days') "
            "AND COALESCE(db.total_mv, 0) > 100000", conn, params=(rd, rd))
        universe_cache[rd] = set(uni["code"].tolist())

    logger.info(f"Shared data: {len(rebalance_dates)} rebal dates, {len(price_data):,} price rows")
    return rebalance_dates, industry, price_data, benchmark_data, factor_cache, universe_cache


# ============================================================
# Signal Generation with configurable constraints
# ============================================================
def generate_targets(rebalance_dates, industry, factor_cache, universe_cache,
                     top_n=15, industry_cap=0.25, target_vol=0.0, vol_window=20,
                     price_data=None):
    """Generate target portfolios with optional Target Vol scaling."""
    sig_config = SignalConfig(
        factor_names=PAPER_TRADING_CONFIG.factor_names,
        top_n=top_n, rebalance_freq="monthly", industry_cap=industry_cap)
    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    # Pre-compute daily portfolio returns for Target Vol
    daily_returns = None
    if target_vol > 0 and price_data is not None:
        # Use equal-weight market return as proxy for portfolio vol
        pdf = price_data.copy()
        pdf["ret"] = pdf["close"] / pdf["pre_close"] - 1
        pdf["ret"] = pdf["ret"].clip(-0.11, 0.11)
        daily_returns = pdf.groupby("trade_date")["ret"].mean().sort_index()

    targets = {}
    prev = {}
    for rd in rebalance_dates:
        fv = factor_cache.get(rd)
        if fv is None or fv.empty:
            continue
        universe = universe_cache.get(rd, set())
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        t = builder.build(scores, industry, prev)
        if not t:
            continue

        # Apply Target Vol scaling
        if target_vol > 0 and daily_returns is not None:
            recent = daily_returns[daily_returns.index <= rd].tail(vol_window)
            if len(recent) >= vol_window // 2:
                realized_vol = float(recent.std() * np.sqrt(244))
                if realized_vol > 0:
                    scale = min(target_vol / realized_vol, 1.0)
                    t = {c: w * scale for c, w in t.items()}

        targets[rd] = t
        prev = t

    return targets


def run_backtest(targets, price_data, benchmark_data, top_n=15, pms_enabled=False):
    """Run backtest with optional PMS."""
    pms = PMSConfig(enabled=pms_enabled, exec_mode="next_open") if pms_enabled else PMSConfig()
    bt_config = BacktestConfig(
        initial_capital=CAPITAL, top_n=top_n, rebalance_freq="monthly",
        slippage_mode="volume_impact", slippage_config=SlippageConfig(), pms=pms)
    bt = SimpleBacktester(bt_config)
    result = bt.run(targets, price_data, benchmark_data)
    report = generate_report(result, price_data)
    return report


# ============================================================
# Main
# ============================================================
def main():
    t0 = time.time()
    conn = _get_sync_conn()
    rebalance_dates, industry, price_data, benchmark_data, factor_cache, universe_cache = load_shared_data(conn)
    conn.close()

    all_results = []  # [(name, report)]

    def run_exp(name, top_n=15, industry_cap=0.25, target_vol=0.0, vol_window=20, pms=False):
        exp_t0 = time.time()
        targets = generate_targets(rebalance_dates, industry, factor_cache, universe_cache,
                                   top_n=top_n, industry_cap=industry_cap,
                                   target_vol=target_vol, vol_window=vol_window,
                                   price_data=price_data)
        report = run_backtest(targets, price_data, benchmark_data, top_n=top_n, pms_enabled=pms)
        elapsed = time.time() - exp_t0
        all_results.append((name, report))
        logger.info(f"  {name:30s}: Sharpe={report.sharpe_ratio:.2f} MDD={report.max_drawdown*100:.1f}% "
                     f"CAGR={report.annual_return*100:.1f}% Calmar={report.calmar_ratio:.2f} ({elapsed:.0f}s)")
        return report

    # =========================================================
    # Experiment 1: Industry Constraints
    # =========================================================
    logger.info("\n=== EXPERIMENT 1: INDUSTRY CONSTRAINTS ===")
    # Current: industry_cap=0.25 → max 3 per industry for top-15
    # Note: int(15*0.25)=3, int(15*0.13)=1, int(15*0.20)=2 (need ~0.133 for ≤2, ~0.067 for ≤1)
    run_exp("I-A: no_constraint",    industry_cap=1.0)
    run_exp("I-B: max3(baseline)",   industry_cap=0.25)   # current default
    run_exp("I-C: max2",            industry_cap=0.133)
    run_exp("I-D: max1",            industry_cap=0.067)

    # =========================================================
    # Experiment 2: Top-N Sensitivity
    # =========================================================
    logger.info("\n=== EXPERIMENT 2: TOP-N SENSITIVITY ===")
    run_exp("N-A: top10",  top_n=10)
    run_exp("N-B: top15",  top_n=15)  # baseline
    run_exp("N-C: top20",  top_n=20)
    run_exp("N-D: top25",  top_n=25)
    run_exp("N-E: top30",  top_n=30)

    # =========================================================
    # Experiment 3: Target Vol
    # =========================================================
    logger.info("\n=== EXPERIMENT 3: TARGET VOL ===")
    run_exp("TV-A: no_tv(baseline)")
    run_exp("TV-B: tv15%", target_vol=0.15)
    run_exp("TV-C: tv20%", target_vol=0.20)
    run_exp("TV-D: tv25%", target_vol=0.25)
    run_exp("TV-E: tv30%", target_vol=0.30)
    # Window sensitivity
    run_exp("TV-F: tv20%_40d", target_vol=0.20, vol_window=40)
    run_exp("TV-G: tv20%_60d", target_vol=0.20, vol_window=60)

    # =========================================================
    # Experiment 4: Stacked Combinations
    # =========================================================
    logger.info("\n=== EXPERIMENT 4: STACKED COMBINATIONS ===")
    # Find best from each experiment
    # Start with baseline, add layers one by one
    run_exp("C-A: baseline",         top_n=15, industry_cap=0.25)
    run_exp("C-B: +PMS",            top_n=15, industry_cap=0.25, pms=True)
    run_exp("C-C: +PMS+ind_max2",   top_n=15, industry_cap=0.133, pms=True)
    run_exp("C-D: +PMS+ind+top20",  top_n=20, industry_cap=0.133, pms=True)
    run_exp("C-E: +PMS+ind+top20+tv20", top_n=20, industry_cap=0.133, pms=True, target_vol=0.20)
    # Also test without PMS but with other layers
    run_exp("C-F: ind+top20+tv20",  top_n=20, industry_cap=0.133, target_vol=0.20)

    # =========================================================
    # Report
    # =========================================================
    print("\n" + "=" * 120)
    print("回撤控制三层叠加验证")
    print("=" * 120)
    print(f"回测: {START}~{END} | 5因子等权 | volume_impact | 资金{CAPITAL:,.0f}")

    header = f"{'实验':<30} {'Sharpe':>8} {'AdjSh':>8} {'CAGR':>8} {'MDD':>8} {'Calmar':>8} {'换手率':>8}"
    print(f"\n{header}\n{'-'*len(header)}")
    for name, rpt in all_results:
        print(f"{name:<30} {rpt.sharpe_ratio:>8.2f} {rpt.autocorr_adjusted_sharpe_ratio:>8.2f} "
              f"{rpt.annual_return*100:>7.1f}% {rpt.max_drawdown*100:>7.1f}% "
              f"{rpt.calmar_ratio:>8.2f} {rpt.annual_turnover:>8.2f}")

    # Annual Sharpe for key experiments
    key_exps = ["I-A: no_constraint", "I-B: max3(baseline)", "I-C: max2", "I-D: max1",
                "N-A: top10", "N-B: top15", "N-C: top20", "N-E: top30",
                "TV-A: no_tv(baseline)", "TV-C: tv20%",
                "C-A: baseline", "C-B: +PMS", "C-C: +PMS+ind_max2",
                "C-D: +PMS+ind+top20", "C-E: +PMS+ind+top20+tv20"]

    years = sorted(all_results[0][1].annual_breakdown.index)
    print(f"\n--- 年度Sharpe (关键实验) ---")
    hdr = f"{'实验':<30} " + " ".join(f"{y:>8}" for y in years)
    print(f"{hdr}\n{'-'*len(hdr)}")
    for name, rpt in all_results:
        if name in key_exps:
            ab = rpt.annual_breakdown
            vals = " ".join(f"{ab.loc[y,'sharpe']:>8.2f}" if y in ab.index else f"{'N/A':>8}" for y in years)
            print(f"{name:<30} {vals}")

    print(f"\n--- 年度MDD (关键实验) ---")
    print(f"{hdr}\n{'-'*len(hdr)}")
    for name, rpt in all_results:
        if name in key_exps:
            ab = rpt.annual_breakdown
            vals = " ".join(f"{ab.loc[y,'mdd']:>7.1f}%" if y in ab.index else f"{'N/A':>8}" for y in years)
            print(f"{name:<30} {vals}")

    # MDD Waterfall
    print(f"\n--- MDD改善瀑布 ---")
    waterfall = [(n, r) for n, r in all_results if n.startswith("C-")]
    for name, rpt in waterfall:
        print(f"  {name:<30} MDD={rpt.max_drawdown*100:>7.1f}%  Sharpe={rpt.sharpe_ratio:.2f}  Calmar={rpt.calmar_ratio:.2f}")

    elapsed = time.time() - t0
    logger.info(f"\n总耗时: {elapsed:.0f}s ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
