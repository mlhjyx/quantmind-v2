#!/usr/bin/env python3
"""子任务1: 分市值层回测 — 确认alpha在哪些市值段有效。

实验:
  A: 全市场(基线确认)
  B: 市值>100亿(中大盘)
  C: 市值30-100亿(中盘)
  D: 市值<30亿(小盘)
  E: 市值>50亿(排除微盘)
"""
import logging, os, sys, time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd
from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.signal_engine import (PAPER_TRADING_CONFIG, PortfolioBuilder,
                                   SignalComposer, SignalConfig, get_rebalance_dates)
from engines.slippage_model import SlippageConfig
from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

START, END = "2021-01-01", "2026-03-31"
CAPITAL, TOP_N, FREQ = 1_000_000, 15, "monthly"

EXPERIMENTS = [
    {"name": "A_all_market",  "min_mv": 10,   "max_mv": 99999, "top_n": 15, "desc": "全市场(基线)"},
    {"name": "B_large_100yi", "min_mv": 100,  "max_mv": 99999, "top_n": 15, "desc": "市值>100亿"},
    {"name": "C_mid_30_100",  "min_mv": 30,   "max_mv": 100,   "top_n": 15, "desc": "30-100亿"},
    {"name": "D_small_lt30",  "min_mv": 10,   "max_mv": 30,    "top_n": 15, "desc": "<30亿"},
    {"name": "E_gt50yi",      "min_mv": 50,   "max_mv": 99999, "top_n": 15, "desc": "市值>50亿"},
]


def load_universe_mv(trade_date, conn, min_mv_yi, max_mv_yi):
    """加载指定市值范围的universe。min_mv_yi/max_mv_yi单位=亿元。"""
    min_mv_wan = min_mv_yi * 10000  # 亿→万
    max_mv_wan = max_mv_yi * 10000
    df = pd.read_sql(
        """SELECT k.code
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s AND k.volume > 0
             AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s::date - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) BETWEEN %s AND %s""",
        conn, params=(trade_date, trade_date, min_mv_wan, max_mv_wan))
    return set(df["code"].tolist())


def load_factor_values(trade_date, conn):
    return pd.read_sql(
        "SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
        conn, params=(trade_date,))


def load_industry(conn):
    return pd.read_sql("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
                        conn).set_index("code")["industry_sw1"].fillna("其他")


def load_price_data(start, end, conn):
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount, k.up_limit, k.down_limit, db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
           ORDER BY k.trade_date, k.code""", conn, params=(start, end))


def load_benchmark(start, end, conn):
    return pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""", conn, params=(start, end))


def run_one(exp, rebalance_dates, industry, price_data, benchmark_data, conn):
    name = exp["name"]
    min_mv, max_mv, top_n = exp["min_mv"], exp["max_mv"], exp["top_n"]
    logger.info(f"=== {name}: {exp['desc']} (mv={min_mv}-{max_mv}亿, top{top_n}) ===")

    sig_config = SignalConfig(factor_names=PAPER_TRADING_CONFIG.factor_names,
                              top_n=top_n, rebalance_freq=FREQ)
    bt_config = BacktestConfig(initial_capital=CAPITAL, top_n=top_n, rebalance_freq=FREQ,
                               slippage_mode="volume_impact", slippage_config=SlippageConfig())

    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)
    targets, prev = {}, {}
    universe_sizes = []

    for rd in rebalance_dates:
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe_mv(rd, conn, min_mv, max_mv)
        universe_sizes.append(len(universe))
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        t = builder.build(scores, industry, prev)
        if t:
            targets[rd] = t
            prev = t

    from engines.metrics import generate_report
    bt = SimpleBacktester(bt_config)
    result = bt.run(targets, price_data, benchmark_data)
    report = generate_report(result, price_data)

    avg_uni = sum(universe_sizes) / len(universe_sizes) if universe_sizes else 0
    return report, avg_uni


def main():
    t0 = time.time()
    start = datetime.strptime(START, "%Y-%m-%d").date()
    end = datetime.strptime(END, "%Y-%m-%d").date()
    conn = _get_sync_conn()

    logger.info("加载共享数据...")
    rebalance_dates = get_rebalance_dates(start, end, freq=FREQ, conn=conn)
    industry = load_industry(conn)
    price_data = load_price_data(START, END, conn)
    benchmark_data = load_benchmark(START, END, conn)
    logger.info(f"共享数据就绪: {len(rebalance_dates)}调仓日")

    results = []
    for exp in EXPERIMENTS:
        exp_t0 = time.time()
        report, avg_uni = run_one(exp, rebalance_dates, industry, price_data, benchmark_data, conn)
        elapsed = time.time() - exp_t0
        results.append((exp, report, avg_uni))
        logger.info(f"  {exp['name']}: Sharpe={report.sharpe_ratio:.2f}, "
                     f"MDD={report.max_drawdown*100:.1f}%, CAGR={report.annual_return*100:.1f}%, "
                     f"universe={avg_uni:.0f}, 耗时={elapsed:.0f}s")

    conn.close()

    # Report
    print("\n" + "=" * 110)
    print("分市值层回测 — Alpha在哪些市值段有效?")
    print("=" * 110)
    print(f"回测: {START}~{END} | 5因子等权 | volume_impact | 资金{CAPITAL:,.0f}")

    header = f"{'实验':<20} {'说明':<15} {'Sharpe':>8} {'AdjSh':>8} {'CAGR':>8} {'MDD':>8} {'Calmar':>8} {'换手率':>8} {'Uni均':>8}"
    print(f"\n{header}\n{'-'*len(header)}")
    for exp, rpt, uni in results:
        print(f"{exp['name']:<20} {exp['desc']:<15} {rpt.sharpe_ratio:>8.2f} "
              f"{rpt.autocorr_adjusted_sharpe_ratio:>8.2f} {rpt.annual_return*100:>7.1f}% "
              f"{rpt.max_drawdown*100:>7.1f}% {rpt.calmar_ratio:>8.2f} "
              f"{rpt.annual_turnover:>8.2f} {uni:>8.0f}")

    # Annual breakdown
    years = sorted(results[0][1].annual_breakdown.index)
    print(f"\n--- 年度Sharpe ---")
    hdr = f"{'实验':<20} " + " ".join(f"{y:>8}" for y in years)
    print(f"{hdr}\n{'-'*len(hdr)}")
    for exp, rpt, _ in results:
        vals = " ".join(f"{rpt.annual_breakdown.loc[y,'sharpe']:>8.2f}" if y in rpt.annual_breakdown.index else f"{'N/A':>8}" for y in years)
        print(f"{exp['name']:<20} {vals}")

    print(f"\n--- 年度MDD ---")
    print(f"{hdr}\n{'-'*len(hdr)}")
    for exp, rpt, _ in results:
        vals = " ".join(f"{rpt.annual_breakdown.loc[y,'mdd']:>7.1f}%" if y in rpt.annual_breakdown.index else f"{'N/A':>8}" for y in years)
        print(f"{exp['name']:<20} {vals}")

    print(f"\n--- 年度收益 ---")
    print(f"{hdr}\n{'-'*len(hdr)}")
    for exp, rpt, _ in results:
        vals = " ".join(f"{rpt.annual_breakdown.loc[y,'return']:>7.1f}%" if y in rpt.annual_breakdown.index else f"{'N/A':>8}" for y in years)
        print(f"{exp['name']:<20} {vals}")

    # Interpretation
    print(f"\n{'='*60}")
    print("INTERPRETATION")
    print(f"{'='*60}")
    sharpes = {exp['name']: rpt.sharpe_ratio for exp, rpt, _ in results}
    b_sh = sharpes.get("B_large_100yi", 0)
    c_sh = sharpes.get("C_mid_30_100", 0)
    d_sh = sharpes.get("D_small_lt30", 0)
    if b_sh > 0.5 and c_sh > 0.5:
        print("  ✅ Alpha跨市值有效 — B(大盘)和C(中盘)Sharpe都>0.5")
        print("     → G1应加市值中性化约束,减少SMB暴露")
    elif d_sh > 0.5 and b_sh < 0.3:
        print("  ⚠️ Alpha仅在小盘有效 — 只有D(小盘)Sharpe>0.5")
        print("     → G1不加市值约束,MDD靠多策略解决")
    else:
        print(f"  混合结果: B={b_sh:.2f}, C={c_sh:.2f}, D={d_sh:.2f}")

    elapsed = time.time() - t0
    logger.info(f"\n总耗时: {elapsed:.0f}s ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
