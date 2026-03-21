#!/usr/bin/env python3
"""回测运行脚本 — 端到端因子→信号→回测→报告。

用法:
    python scripts/run_backtest.py --start 2021-01-01 --end 2025-12-31
    python scripts/run_backtest.py --start 2021-01-01 --end 2025-12-31 --top-n 30
    python scripts/run_backtest.py --start 2021-01-01 --end 2025-12-31 --freq monthly
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import generate_report, print_report
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_factor_values(trade_date, conn) -> pd.DataFrame:
    """加载单日因子值。"""
    return pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values WHERE trade_date = %s""",
        conn,
        params=(trade_date,),
    )


def load_universe(trade_date, conn) -> set[str]:
    """加载Universe（排除ST/新股/停牌/低流动性）。"""
    df = pd.read_sql(
        """SELECT k.code
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000
        """,
        conn,
        params=(trade_date, trade_date),
    )
    return set(df["code"].tolist())


def load_industry(conn) -> pd.Series:
    """加载行业分类。"""
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
        conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


def load_price_data(start_date, end_date, conn) -> pd.DataFrame:
    """加载回测用价格数据（含涨跌停限制）。"""
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount,
                  k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s
             AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn,
        params=(start_date, end_date),
    )


def load_benchmark(start_date, end_date, conn) -> pd.DataFrame:
    """加载基准数据(CSI300)。"""
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )


def main():
    parser = argparse.ArgumentParser(description="QuantMind V2 回测")
    parser.add_argument("--start", type=str, required=True)
    parser.add_argument("--end", type=str, required=True)
    parser.add_argument("--top-n", type=int, default=PAPER_TRADING_CONFIG.top_n)
    parser.add_argument(
        "--freq",
        choices=["weekly", "biweekly", "monthly"],
        default=PAPER_TRADING_CONFIG.rebalance_freq,
    )
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--slippage", type=float, default=10.0, help="滑点(bps)")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    conn = _get_sync_conn()
    t0 = time.time()

    # 1. 配置
    sig_config = SignalConfig(
        factor_names=PAPER_TRADING_CONFIG.factor_names,
        top_n=args.top_n,
        rebalance_freq=args.freq,
    )
    bt_config = BacktestConfig(
        initial_capital=args.capital,
        top_n=args.top_n,
        rebalance_freq=args.freq,
        slippage_bps=args.slippage,
    )

    # 2. 获取调仓日历
    logger.info("获取调仓日历...")
    rebalance_dates = get_rebalance_dates(start, end, freq=args.freq, conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    # 3. 加载行业分类
    industry = load_industry(conn)

    # 4. 逐日生成目标持仓
    logger.info("生成目标持仓信号...")
    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    target_portfolios = {}
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        # 加载因子值
        fv = load_factor_values(rd, conn)
        if fv.empty:
            logger.warning(f"[{rd}] 无因子数据, 跳过")
            continue

        # 加载Universe
        universe = load_universe(rd, conn)

        # 合成信号
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue

        # 构建目标持仓
        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

        if (i + 1) % 20 == 0:
            logger.info(f"  信号 [{i + 1}/{len(rebalance_dates)}] {rd}: {len(target)}只")

    logger.info(f"信号生成完成: {len(target_portfolios)}个调仓日")

    # 5. 加载价格数据
    logger.info("加载价格数据...")
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

    # 6. 运行回测
    logger.info("运行回测...")
    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    # 7. 生成报告
    logger.info("生成绩效报告...")
    report = generate_report(result, price_data)
    print_report(report)

    elapsed = time.time() - t0
    logger.info(f"回测完成, 总耗时 {elapsed:.0f}s")

    conn.close()


if __name__ == "__main__":
    main()
