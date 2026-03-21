#!/usr/bin/env python3
"""Paper Trading 状态查询CLI。

用法:
    python scripts/paper_trading_status.py          # 最新状态
    python scripts/paper_trading_status.py --days 5  # 最近5天
    python scripts/paper_trading_status.py --holdings # 当前持仓明细
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd
from app.config import settings
from app.services.price_utils import _get_sync_conn


def show_performance(conn, days: int = 10):
    """显示最近N天绩效。"""
    sid = settings.PAPER_STRATEGY_ID
    df = pd.read_sql(
        """SELECT trade_date, nav::float, daily_return::float,
                  cumulative_return::float, drawdown::float,
                  position_count, cash_ratio::float, turnover::float
           FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
           ORDER BY trade_date DESC LIMIT %s""",
        conn,
        params=(sid, days),
    )

    if df.empty:
        print("⚠️  无Paper Trading记录")
        return

    df = df.sort_values("trade_date")
    latest = df.iloc[-1]

    print("=" * 65)
    print(f"  QuantMind Paper Trading 状态  (策略: {sid[:8]}...)")
    print("=" * 65)
    print(f"  最新日期:   {latest['trade_date']}")
    print(f"  NAV:        ¥{latest['nav']:,.0f}")
    print(f"  累计收益:   {latest['cumulative_return']:+.2%}")
    print(f"  最大回撤:   {df['drawdown'].min():+.2%}")
    print(f"  持仓数量:   {int(latest['position_count'])}只")
    print(f"  现金比例:   {latest['cash_ratio']:.1%}")
    print()

    # 每日表格
    print(f"{'日期':>12} {'NAV':>10} {'日收益':>8} {'累计':>8} {'回撤':>8} {'持仓':>4} {'换手':>6}")
    print("-" * 65)
    for _, r in df.iterrows():
        print(
            f"{str(r['trade_date']):>12} "
            f"{r['nav']:>10,.0f} "
            f"{r['daily_return']:>+7.2%} "
            f"{r['cumulative_return']:>+7.2%} "
            f"{r['drawdown']:>+7.2%} "
            f"{int(r['position_count']):>4} "
            f"{r['turnover']:>5.1%}"
        )

    # 运行天数统计
    total_days = len(df)
    if total_days >= 2:
        rets = df["daily_return"].values
        import numpy as np
        sharpe = float(np.mean(rets) / np.std(rets) * (252**0.5)) if np.std(rets) > 0 else 0
        print(f"\n  运行: {total_days}个交易日 | 滚动Sharpe: {sharpe:.2f}")
        print(f"  毕业标准: 60天, Sharpe ≥ 0.90 (回测1.28×70%)")


def show_holdings(conn):
    """显示当前持仓明细。"""
    sid = settings.PAPER_STRATEGY_ID
    df = pd.read_sql(
        """SELECT ps.code, s.name, ps.quantity, ps.market_value::float,
                  ps.weight::float
           FROM position_snapshot ps
           JOIN symbols s ON ps.code = s.code
           WHERE ps.strategy_id = %s AND ps.execution_mode = 'paper'
             AND ps.trade_date = (
               SELECT MAX(trade_date) FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = 'paper'
             )
           ORDER BY ps.market_value DESC""",
        conn,
        params=(sid, sid),
    )

    if df.empty:
        print("⚠️  无持仓记录")
        return

    print(f"\n{'#':>3} {'代码':>8} {'名称':>10} {'数量':>6} {'市值':>10} {'权重':>6}")
    print("-" * 50)
    for i, (_, r) in enumerate(df.iterrows(), 1):
        name = r["name"][:8] if len(r["name"]) > 8 else r["name"]
        print(
            f"{i:>3} {r['code']:>8} {name:>10} "
            f"{int(r['quantity']):>6} "
            f"{r['market_value']:>10,.0f} "
            f"{r['weight']:>5.1%}"
        )
    print("-" * 50)
    print(f"    合计: {df['market_value'].sum():,.0f}  ({df['weight'].sum():.1%})")


def show_recent_trades(conn, days: int = 5):
    """显示最近成交。"""
    sid = settings.PAPER_STRATEGY_ID
    df = pd.read_sql(
        """SELECT trade_date, code, direction, quantity,
                  fill_price::float, total_cost::float
           FROM trade_log
           WHERE strategy_id = %s AND execution_mode = 'paper'
           ORDER BY trade_date DESC, direction, code
           LIMIT %s""",
        conn,
        params=(sid, days * 40),
    )

    if df.empty:
        print("\n⚠️  无成交记录")
        return

    dates = df["trade_date"].unique()
    for td in sorted(dates, reverse=True)[:days]:
        day_df = df[df["trade_date"] == td]
        buys = day_df[day_df["direction"] == "buy"]
        sells = day_df[day_df["direction"] == "sell"]
        print(f"\n  {td}: 买入{len(buys)}笔 卖出{len(sells)}笔")
        for _, r in day_df.iterrows():
            arrow = "↑" if r["direction"] == "buy" else "↓"
            print(
                f"    {arrow} {r['code']} ×{int(r['quantity'])} "
                f"@{r['fill_price']:.2f} 费用={r['total_cost']:.1f}"
            )


def show_pipeline_status(conn):
    """显示今日管道状态。"""
    df = pd.read_sql(
        """SELECT task_name, status, error_message,
                  created_at AT TIME ZONE 'Asia/Shanghai' as created_at
           FROM scheduler_task_log
           WHERE created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC""",
        conn,
    )

    if df.empty:
        print("\n⚠️  今日无管道记录")
        return

    print(f"\n  最近24h管道状态:")
    for _, r in df.iterrows():
        icon = "✅" if r["status"] == "success" else "❌"
        t = r["created_at"].strftime("%H:%M:%S") if r["created_at"] else "?"
        err = f" ({r['error_message'][:40]})" if r["error_message"] else ""
        print(f"    {icon} {t} {r['task_name']}{err}")


def main():
    parser = argparse.ArgumentParser(description="Paper Trading 状态查询")
    parser.add_argument("--days", type=int, default=10, help="显示最近N天")
    parser.add_argument("--holdings", action="store_true", help="显示持仓明细")
    parser.add_argument("--trades", action="store_true", help="显示近期成交")
    parser.add_argument("--pipeline", action="store_true", help="显示管道状态")
    parser.add_argument("--all", action="store_true", help="显示全部信息")
    args = parser.parse_args()

    if not settings.PAPER_STRATEGY_ID:
        print("❌ PAPER_STRATEGY_ID未配置")
        sys.exit(1)

    conn = _get_sync_conn()

    try:
        show_performance(conn, args.days)

        if args.holdings or args.all:
            show_holdings(conn)

        if args.trades or args.all:
            show_recent_trades(conn, args.days)

        if args.pipeline or args.all:
            show_pipeline_status(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
