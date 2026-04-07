#!/usr/bin/env python3
"""对比流动性过滤 + 因子扩展的Sharpe影响。"""
import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
logging.basicConfig(level=logging.WARNING)

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from datetime import date

import pandas as pd
from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import generate_report
from engines.signal_engine import (
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from engines.slippage_model import SlippageConfig
from run_backtest import (
    load_benchmark,
    load_factor_values,
    load_industry,
    load_price_data,
    load_universe,
)

from app.services.price_utils import _get_sync_conn


def load_universe_nofilter(trade_date, conn):
    """Universe WITHOUT liquidity filter."""
    df = pd.read_sql(
        """SELECT k.code FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s AND k.volume > 0 AND s.list_status = 'L'
           AND s.name NOT LIKE '%%ST%%'
           AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
           AND COALESCE(db.total_mv, 0) > 100000""",
        conn, params=(trade_date, trade_date),
    )
    return set(df["code"].tolist())


def run_backtest_compare(label, factor_list, start, end, universe_fn, conn):
    cfg = SignalConfig(
        factor_names=factor_list, weight_method="equal", top_n=15,
        rebalance_freq="monthly", turnover_cap=0.50, industry_cap=0.25, cash_buffer=0.03,
    )
    rebal = get_rebalance_dates(start, end, "monthly", conn=conn)
    composer = SignalComposer(cfg)
    builder = PortfolioBuilder(cfg)
    industry = load_industry(conn)

    target_portfolios = {}
    prev_weights = {}
    for td in rebal:
        fv = load_factor_values(td, conn)
        universe = universe_fn(td, conn)
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[td] = target
            prev_weights = target

    price_data = load_price_data(start, end, conn)
    benchmark = load_benchmark(start, end, conn)

    bt = SimpleBacktester(BacktestConfig(
        initial_capital=1_000_000,
        slippage_config=SlippageConfig(),
    ))
    result = bt.run(target_portfolios, price_data, benchmark)
    report = generate_report(result, price_data)

    print(
        f"{label:45s} | {report.sharpe_ratio:6.3f} | "
        f"{report.max_drawdown:8.2%} | {report.annual_return:7.2%} | "
        f"{report.calmar_ratio:5.2f}",
        flush=True,
    )
    return report


def main():
    conn = _get_sync_conn()

    F5 = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    F6 = F5 + ["mf_divergence"]
    F7 = F6 + ["reversal_5"]

    print(f"{'配置':45s} | Sharpe |      MDD |  Annual | Calmar")
    print("-" * 90)

    # Core comparisons: filter impact
    run_backtest_compare("5因子 有过滤 WLS 5yr (基准)",     F5, date(2021,1,1), date(2025,12,31), load_universe, conn)
    run_backtest_compare("5因子 无过滤 WLS 5yr",            F5, date(2021,1,1), date(2025,12,31), load_universe_nofilter, conn)
    run_backtest_compare("5因子 有过滤 WLS 2yr(24-25)",     F5, date(2024,1,1), date(2025,12,31), load_universe, conn)
    run_backtest_compare("5因子 无过滤 WLS 2yr(24-25)",     F5, date(2024,1,1), date(2025,12,31), load_universe_nofilter, conn)

    # Factor expansion
    run_backtest_compare("6因子(+mf) 有过滤 WLS 5yr",      F6, date(2021,1,1), date(2025,12,31), load_universe, conn)
    run_backtest_compare("7因子(+mf+rev5) 有过滤 WLS 5yr", F7, date(2021,1,1), date(2025,12,31), load_universe, conn)

    conn.close()
    print("\n全部完成")


if __name__ == "__main__":
    main()
