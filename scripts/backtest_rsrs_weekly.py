#!/usr/bin/env python3
"""RSRS事件型策略SimBroker回测 — Sprint 1.12验证(R1)。

验证目标:
- RSRS单因子(rsrs_raw_18, t=-4.35) 在weekly调仓下的SimBroker表现
- 对比v1.1月度基线(volume-impact下Sharpe=0.91)
- 铁律3: 因子入组合前SimBroker回测
- 铁律8: strategy确定匹配策略(ic_decay→weekly频率)

用法:
    python scripts/backtest_rsrs_weekly.py
    python scripts/backtest_rsrs_weekly.py --freq monthly  # 对比月度
    python scripts/backtest_rsrs_weekly.py --slippage-mode fixed --slippage 10
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.slippage_model import SlippageConfig
from engines.metrics import generate_report, print_report
from engines.signal_engine import (
    PortfolioBuilder,
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

# RSRS因子方向 (Sprint 1.6确认: -1, 低RSRS beta→支撑强)
RSRS_DIRECTION = -1


def load_rsrs_factor(trade_date, conn) -> pd.DataFrame:
    """加载RSRS单因子(中性化值)。"""
    return pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = %s
             AND factor_name = 'rsrs_raw_18'""",
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
    """加载回测价格数据(含total_mv和volatility_20用于volume-impact滑点)。"""
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount,
                  k.up_limit, k.down_limit,
                  db.turnover_rate,
                  db.total_mv,
                  fv.raw_value AS volatility_20
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           LEFT JOIN factor_values fv ON k.code = fv.code AND k.trade_date = fv.trade_date
                                         AND fv.factor_name = 'volatility_20'
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


def compose_rsrs_scores(factor_df: pd.DataFrame, universe: set[str]) -> pd.Series:
    """RSRS单因子排序: 方向调整后直接排名。

    不经过SignalComposer(那是多因子等权), 直接用中性化值排序。
    """
    if factor_df.empty:
        return pd.Series(dtype=float)

    # 过滤universe
    df = factor_df[factor_df["code"].isin(universe)].copy()
    if df.empty:
        return pd.Series(dtype=float)

    # 取neutral_value, 方向调整
    scores = df.set_index("code")["neutral_value"]
    scores = scores.dropna()

    # 方向: -1 → 乘以-1后从高到低排 (低RSRS beta排前面)
    scores = scores * RSRS_DIRECTION

    return scores.sort_values(ascending=False)


def run_rsrs_backtest(args):
    """运行RSRS回测。"""
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    conn = _get_sync_conn()
    t0 = time.time()

    # 配置
    sig_config = SignalConfig(
        factor_names=["rsrs_raw_18"],
        top_n=args.top_n,
        weight_method="equal",
        rebalance_freq=args.freq,
        industry_cap=0.25,
        turnover_cap=0.50,
        cash_buffer=0.03,
    )
    bt_config = BacktestConfig(
        initial_capital=args.capital,
        top_n=args.top_n,
        rebalance_freq=args.freq,
        slippage_bps=args.slippage,
        slippage_mode=args.slippage_mode,
        slippage_config=SlippageConfig(),
    )

    print("=" * 70)
    print("RSRS事件型策略SimBroker回测")
    print("=" * 70)
    print(f"因子: rsrs_raw_18 (t=-4.35, direction={RSRS_DIRECTION})")
    print(f"调仓: {args.freq} | Top-{args.top_n} | 行业25% | 换手50%")
    print(f"滑点: {args.slippage_mode}")
    print(f"区间: {start} ~ {end}")
    print(f"资金: {args.capital:,.0f}")
    print("=" * 70)

    # 获取调仓日历
    logger.info("获取调仓日历...")
    rebalance_dates = get_rebalance_dates(start, end, freq=args.freq, conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个 ({args.freq})")

    # 加载行业分类
    industry = load_industry(conn)

    # 逐调仓日生成目标持仓
    logger.info("RSRS信号生成...")
    builder = PortfolioBuilder(sig_config)
    target_portfolios = {}
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        # 加载RSRS因子
        fv = load_rsrs_factor(rd, conn)
        if fv.empty:
            logger.warning(f"[{rd}] 无RSRS因子数据, 跳过")
            continue

        # 加载Universe
        universe = load_universe(rd, conn)

        # RSRS单因子排序
        scores = compose_rsrs_scores(fv, universe)
        if scores.empty:
            continue

        # 构建目标持仓 (等权Top-N + 行业约束 + 换手约束)
        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

        if (i + 1) % 20 == 0:
            logger.info(f"  信号 [{i + 1}/{len(rebalance_dates)}] {rd}: {len(target)}只")

    logger.info(f"信号生成完成: {len(target_portfolios)}个调仓日")

    if not target_portfolios:
        logger.error("无有效信号, 退出")
        conn.close()
        return None

    # 加载价格数据(含total_mv用于volume-impact)
    logger.info("加载价格数据...")
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

    # 检查total_mv覆盖率
    mv_coverage = price_data["total_mv"].notna().mean()
    logger.info(f"total_mv覆盖率: {mv_coverage:.1%}")

    # 运行SimBroker回测
    logger.info("运行SimBroker回测...")
    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    # 生成报告
    logger.info("生成绩效报告...")
    report = generate_report(result, price_data)
    print_report(report)

    # 额外: 年度分解
    print_yearly_breakdown(result)

    # 额外: 与v1.1基线对比提示
    print("\n" + "=" * 70)
    print("对比参考 (v1.1月度基线, volume-impact):")
    print("  Sharpe: 0.91 (σ校准后)")
    print("  MDD: -58.4%")
    print("  年化: 21.55%")
    print("=" * 70)

    elapsed = time.time() - t0
    logger.info(f"回测完成, 总耗时 {elapsed:.0f}s")

    conn.close()
    return result


def print_yearly_breakdown(result):
    """年度分解: 每年Sharpe/收益/MDD。"""
    nav = result.daily_nav
    if nav.empty:
        return

    print("\n--- 年度分解 ---")
    print(f"{'年份':>6} {'收益率':>10} {'Sharpe':>8} {'MDD':>10}")
    print("-" * 40)

    for year in sorted(set(d.year for d in nav.index)):
        year_nav = nav[nav.index.map(lambda d: d.year == year)]
        if len(year_nav) < 20:
            continue

        year_ret = year_nav.pct_change().dropna()
        annual_return = (year_nav.iloc[-1] / year_nav.iloc[0] - 1)
        sharpe = year_ret.mean() / year_ret.std() * np.sqrt(252) if year_ret.std() > 0 else 0

        # MDD
        peak = year_nav.expanding().max()
        dd = (year_nav - peak) / peak
        mdd = dd.min()

        marker = " ⚠️" if sharpe < 0 else ""
        print(f"{year:>6} {annual_return:>9.2%} {sharpe:>8.3f} {mdd:>9.2%}{marker}")


def main():
    parser = argparse.ArgumentParser(description="RSRS事件型策略SimBroker回测")
    parser.add_argument("--start", type=str, default="2021-01-01")
    parser.add_argument("--end", type=str, default="2025-12-31")
    parser.add_argument("--top-n", type=int, default=15)
    parser.add_argument(
        "--freq",
        choices=["weekly", "biweekly", "monthly"],
        default="weekly",
    )
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--slippage", type=float, default=10.0)
    parser.add_argument("--slippage-mode", choices=["volume_impact", "fixed"],
                        default="volume_impact")
    args = parser.parse_args()
    run_rsrs_backtest(args)


if __name__ == "__main__":
    main()
