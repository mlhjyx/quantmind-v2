#!/usr/bin/env python3
"""补充实验: X-A~X-E叠加 + IC-A~IC-D行业参数敏感性 + 行业集中度分析。"""
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, PMSConfig, SimpleBacktester
from engines.metrics import generate_report
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from engines.slippage_model import SlippageConfig

from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

START, END = "2021-01-01", "2026-03-31"
CAPITAL = 1_000_000


def load_shared(conn):
    start = datetime.strptime(START, "%Y-%m-%d").date()
    end = datetime.strptime(END, "%Y-%m-%d").date()
    rebalance_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
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
    fc, uc = {}, {}
    for rd in rebalance_dates:
        fc[rd] = pd.read_sql("SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s", conn, params=(rd,))
        uni = pd.read_sql(
            "SELECT k.code FROM klines_daily k JOIN symbols s ON k.code = s.code "
            "LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date "
            "WHERE k.trade_date = %s AND k.volume > 0 AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%' "
            "AND (s.list_date IS NULL OR s.list_date <= %s::date - INTERVAL '60 days') "
            "AND COALESCE(db.total_mv, 0) > 100000", conn, params=(rd, rd))
        uc[rd] = set(uni["code"].tolist())
    return rebalance_dates, industry, price_data, benchmark_data, fc, uc


def run_exp(name, rebalance_dates, industry, price_data, benchmark_data, fc, uc,
            top_n=15, industry_cap=0.25, pms_mode="off", target_vol=0.0):
    t0 = time.time()
    sig_config = SignalConfig(factor_names=PAPER_TRADING_CONFIG.factor_names,
                              top_n=top_n, rebalance_freq="monthly", industry_cap=industry_cap)
    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    daily_ret = None
    if target_vol > 0:
        pdf = price_data.copy()
        pdf["ret"] = (pdf["close"] / pdf["pre_close"] - 1).clip(-0.11, 0.11)
        daily_ret = pdf.groupby("trade_date")["ret"].mean().sort_index()

    targets, prev = {}, {}
    industry_stats = []  # for concentration analysis

    for rd in rebalance_dates:
        fv = fc.get(rd)
        if fv is None or fv.empty:
            continue
        universe = uc.get(rd, set())
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        t = builder.build(scores, industry, prev)
        if not t:
            continue

        # Track industry concentration
        ind_counts = {}
        for code in t:
            ind = industry.get(code, "其他")
            ind_counts[ind] = ind_counts.get(ind, 0) + 1
        max_ind = max(ind_counts.values()) if ind_counts else 0
        max_ind_name = max(ind_counts, key=ind_counts.get) if ind_counts else ""
        industry_stats.append({"date": rd, "max_count": max_ind, "max_industry": max_ind_name,
                                "n_industries": len(ind_counts), "n_stocks": len(t)})

        if target_vol > 0 and daily_ret is not None:
            recent = daily_ret[daily_ret.index <= rd].tail(20)
            if len(recent) >= 10:
                rv = float(recent.std() * np.sqrt(244))
                if rv > 0:
                    scale = min(target_vol / rv, 1.0)
                    t = {c: w * scale for c, w in t.items()}
        targets[rd] = t
        prev = t

    pms_cfg = PMSConfig(enabled=False)
    if pms_mode == "next_open":
        pms_cfg = PMSConfig(enabled=True, exec_mode="next_open")
    elif pms_mode == "same_close":
        pms_cfg = PMSConfig(enabled=True, exec_mode="same_close")

    bt_config = BacktestConfig(initial_capital=CAPITAL, top_n=top_n, rebalance_freq="monthly",
                               slippage_mode="volume_impact", slippage_config=SlippageConfig(), pms=pms_cfg)
    bt = SimpleBacktester(bt_config)
    result = bt.run(targets, price_data, benchmark_data)
    report = generate_report(result, price_data)
    elapsed = time.time() - t0
    return report, elapsed, industry_stats


def main():
    t0 = time.time()
    conn = _get_sync_conn()
    logger.info("Loading shared data...")
    rd, ind, pd_, bd, fc, uc = load_shared(conn)
    conn.close()
    logger.info(f"Loaded: {len(rd)} dates, {len(pd_):,} prices")

    all_results = []

    def do(name, **kw):
        report, elapsed, ind_stats = run_exp(name, rd, ind, pd_, bd, fc, uc, **kw)
        all_results.append((name, report, ind_stats))
        logger.info(f"  {name:40s}: Sharpe={report.sharpe_ratio:.2f} MDD={report.max_drawdown*100:.1f}% "
                     f"CAGR={report.annual_return*100:.1f}% Calmar={report.calmar_ratio:.2f} ({elapsed:.0f}s)")

    # === X experiments: no industry constraint + PMS + Top20 + TV ===
    logger.info("\n=== X EXPERIMENTS ===")
    do("X-A: noInd+top20",                top_n=20, industry_cap=1.0)
    do("X-B: noInd+PMS_T1+top20",         top_n=20, industry_cap=1.0, pms_mode="next_open")
    do("X-C: noInd+PMS_T1+top20+tv20",    top_n=20, industry_cap=1.0, pms_mode="next_open", target_vol=0.20)
    do("X-D: noInd+PMS_close+top20",      top_n=20, industry_cap=1.0, pms_mode="same_close")
    do("X-E: noInd+PMS_close+top20+tv20", top_n=20, industry_cap=1.0, pms_mode="same_close", target_vol=0.20)

    # === IC experiments: industry_cap sensitivity at Top-20 ===
    logger.info("\n=== IC SENSITIVITY (Top-20) ===")
    do("IC-A: cap=0.25 (5/ind)",  top_n=20, industry_cap=0.25)
    do("IC-B: cap=0.40 (8/ind)",  top_n=20, industry_cap=0.40)
    do("IC-C: cap=0.60 (12/ind)", top_n=20, industry_cap=0.60)
    do("IC-D: cap=1.00 (none)",   top_n=20, industry_cap=1.0)

    # === Report ===
    print("\n" + "=" * 110)
    print("补充实验: 无行业约束叠加 + 行业参数敏感性")
    print("=" * 110)

    header = f"{'Experiment':<42} {'Sharpe':>8} {'MDD':>8} {'CAGR':>8} {'Calmar':>8} {'Turnover':>8}"
    print(f"\n{header}\n{'-'*len(header)}")
    for name, rpt, _ in all_results:
        print(f"{name:<42} {rpt.sharpe_ratio:>8.2f} {rpt.max_drawdown*100:>7.1f}% "
              f"{rpt.annual_return*100:>7.1f}% {rpt.calmar_ratio:>8.2f} {rpt.annual_turnover:>8.2f}")

    # Annual
    years = sorted(all_results[0][1].annual_breakdown.index)
    print("\n--- Annual Sharpe ---")
    hdr = f"{'Experiment':<42} " + " ".join(f"{y:>8}" for y in years)
    print(f"{hdr}\n{'-'*len(hdr)}")
    for name, rpt, _ in all_results:
        ab = rpt.annual_breakdown
        vals = " ".join(f"{ab.loc[y,'sharpe']:>8.2f}" if y in ab.index else f"{'N/A':>8}" for y in years)
        print(f"{name:<42} {vals}")

    print("\n--- Annual MDD ---")
    print(f"{hdr}\n{'-'*len(hdr)}")
    for name, rpt, _ in all_results:
        ab = rpt.annual_breakdown
        vals = " ".join(f"{ab.loc[y,'mdd']:>7.1f}%" if y in ab.index else f"{'N/A':>8}" for y in years)
        print(f"{name:<42} {vals}")

    # Industry concentration analysis (from IC-D: no constraint)
    print("\n--- Industry Concentration (no constraint, Top-20) ---")
    ic_d_stats = [s for n, _, s in all_results if "IC-D" in n][0]
    if ic_d_stats:
        max_counts = [s["max_count"] for s in ic_d_stats]
        print("  Max same-industry count per rebalance:")
        print(f"    Mean: {np.mean(max_counts):.1f}, Max: {max(max_counts)}, Min: {min(max_counts)}")
        print("    Distribution: " + ", ".join(f"{c}只={sum(1 for x in max_counts if x==c)}月" for c in sorted(set(max_counts))))
        # Most common max industry
        from collections import Counter
        top_inds = Counter(s["max_industry"] for s in ic_d_stats).most_common(5)
        print(f"  Most concentrated industries: {top_inds}")

    # Comparison
    print("\n--- vs Baselines ---")
    print("  Original baseline (ind=0.25, top15, noPMS):     Sharpe=0.91  MDD=-43.0%  Calmar=0.54")
    print("  Previous best C-E (ind=0.13, top20, PMS, tv20): Sharpe=1.05  MDD=-38.6%  Calmar=0.61")
    for name, rpt, _ in all_results:
        if name.startswith("X-"):
            print(f"  {name:<42} Sharpe={rpt.sharpe_ratio:.2f}  MDD={rpt.max_drawdown*100:.1f}%  Calmar={rpt.calmar_ratio:.2f}")

    elapsed = time.time() - t0
    logger.info(f"\nTotal: {elapsed:.0f}s ({elapsed/60:.1f}min)")


if __name__ == "__main__":
    main()
