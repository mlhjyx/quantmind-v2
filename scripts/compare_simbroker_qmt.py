"""SimBroker vs miniQMT 成交对比框架。

同一组调仓信号分别在SimBroker(回测引擎)和miniQMT(模拟盘)执行，
比对成交价差、滑点偏差、部分成交率等。

用途:
- Paper Trading毕业评估: 滑点偏差<50%是毕业标准之一
- 回测可信度验证: SimBroker假设与真实执行的差距

用法:
    python scripts/compare_simbroker_qmt.py --date 2026-03-26
    python scripts/compare_simbroker_qmt.py --start 2026-03-23 --end 2026-03-26

数据源:
- SimBroker: signals表(信号)+klines_daily(次日开盘价模拟成交)
- miniQMT: 从broker_qmt查询当日成交记录，或从trade_log表读取
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("compare_broker")

DB_CONN = "host=localhost port=5432 dbname=quantmind_v2 user=xin password=quantmind"


def get_simbroker_fills(conn: psycopg2.extensions.connection, trade_date: date) -> pd.DataFrame:
    """从trade_log获取SimBroker(paper)的成交记录。

    Args:
        conn: 数据库连接。
        trade_date: 交易日期。

    Returns:
        DataFrame: code, direction, volume, price, amount, slippage_bps
    """
    sql = """
        SELECT
            tl.symbol_code AS code,
            tl.side AS direction,
            tl.filled_qty AS volume,
            tl.avg_price AS sim_price,
            tl.filled_qty * tl.avg_price AS sim_amount
        FROM trade_log tl
        WHERE tl.trade_date = %s
          AND tl.execution_mode = 'paper'
        ORDER BY tl.symbol_code, tl.side
    """
    return pd.read_sql(sql, conn, params=[trade_date])


def get_qmt_fills(conn: psycopg2.extensions.connection, trade_date: date) -> pd.DataFrame:
    """从trade_log获取miniQMT(live)的成交记录。

    TODO: Phase 1实盘上线后，trade_log会有execution_mode='live'的记录。
    当前阶段从miniQMT实时查询。

    Args:
        conn: 数据库连接。
        trade_date: 交易日期。

    Returns:
        DataFrame: code, direction, volume, price, amount
    """
    sql = """
        SELECT
            tl.symbol_code AS code,
            tl.side AS direction,
            tl.filled_qty AS volume,
            tl.avg_price AS qmt_price,
            tl.filled_qty * tl.avg_price AS qmt_amount
        FROM trade_log tl
        WHERE tl.trade_date = %s
          AND tl.execution_mode = 'live'
        ORDER BY tl.symbol_code, tl.side
    """
    return pd.read_sql(sql, conn, params=[trade_date])


def get_qmt_fills_realtime(broker_or_none: object = None) -> pd.DataFrame:
    """从miniQMT实时查询当日成交。

    Args:
        broker_or_none: MiniQMTBroker实例(已连接)，None则跳过。

    Returns:
        DataFrame: code, direction, volume, qmt_price, qmt_amount
    """
    if broker_or_none is None:
        return pd.DataFrame(columns=["code", "direction", "volume", "qmt_price", "qmt_amount"])

    trades = broker_or_none.query_trades()
    if not trades:
        return pd.DataFrame(columns=["code", "direction", "volume", "qmt_price", "qmt_amount"])

    rows = []
    for t in trades:
        direction = "buy" if t["order_type"] == 23 else "sell"
        rows.append({
            "code": t["stock_code"],
            "direction": direction,
            "volume": t["traded_volume"],
            "qmt_price": t["traded_price"],
            "qmt_amount": t["traded_amount"],
        })
    return pd.DataFrame(rows)


def compare_fills(sim_df: pd.DataFrame, qmt_df: pd.DataFrame) -> pd.DataFrame:
    """逐笔对比SimBroker与miniQMT成交。

    Args:
        sim_df: SimBroker成交(code, direction, volume, sim_price, sim_amount)
        qmt_df: miniQMT成交(code, direction, volume, qmt_price, qmt_amount)

    Returns:
        合并后的对比DataFrame
    """
    if sim_df.empty and qmt_df.empty:
        logger.info("两侧均无成交记录")
        return pd.DataFrame()

    # 按(code, direction)合并
    merged = pd.merge(
        sim_df, qmt_df,
        on=["code", "direction"],
        how="outer",
        suffixes=("_sim", "_qmt"),
    )

    # 计算价差
    merged["price_diff"] = merged["qmt_price"] - merged["sim_price"]
    merged["price_diff_bps"] = (
        merged["price_diff"] / merged["sim_price"] * 10000
    ).round(2)

    # 数量差异
    merged["volume_diff"] = (
        merged.get("volume_qmt", merged.get("volume", 0))
        - merged.get("volume_sim", merged.get("volume", 0))
    )

    return merged


def print_comparison_report(merged: pd.DataFrame, trade_date: date) -> None:
    """打印对比报告。"""
    print(f"\n{'='*70}")
    print(f"  SimBroker vs miniQMT 成交对比报告")
    print(f"  交易日: {trade_date}")
    print(f"{'='*70}")

    if merged.empty:
        print("  无对比数据")
        return

    # 汇总统计
    matched = merged.dropna(subset=["sim_price", "qmt_price"])
    sim_only = merged[merged["qmt_price"].isna()]
    qmt_only = merged[merged["sim_price"].isna()]

    print(f"\n  匹配笔数: {len(matched)}")
    print(f"  SimBroker独有: {len(sim_only)}")
    print(f"  miniQMT独有: {len(qmt_only)}")

    if not matched.empty:
        avg_diff_bps = matched["price_diff_bps"].mean()
        median_diff_bps = matched["price_diff_bps"].median()
        max_diff_bps = matched["price_diff_bps"].abs().max()
        std_diff_bps = matched["price_diff_bps"].std()

        print(f"\n  价差统计(bps):")
        print(f"    平均: {avg_diff_bps:+.2f}")
        print(f"    中位数: {median_diff_bps:+.2f}")
        print(f"    最大绝对值: {max_diff_bps:.2f}")
        print(f"    标准差: {std_diff_bps:.2f}")

        # 毕业标准: 滑点偏差<50%
        sim_slippage_bps = 3.0  # SimBroker默认滑点3bps
        if sim_slippage_bps > 0:
            slippage_deviation = abs(avg_diff_bps) / sim_slippage_bps * 100
            pass_fail = "PASS" if slippage_deviation < 50 else "FAIL"
            print(f"\n  毕业标准评估:")
            print(f"    SimBroker滑点模型: {sim_slippage_bps}bps")
            print(f"    实际偏差: {abs(avg_diff_bps):.2f}bps")
            print(f"    偏差比例: {slippage_deviation:.1f}% (标准: <50%)")
            print(f"    判定: {pass_fail}")

    # 逐笔明细
    print(f"\n  {'代码':<12} {'方向':>4} {'SimBroker':>10} {'miniQMT':>10} {'差异(bps)':>10}")
    print(f"  {'-'*50}")
    for _, row in merged.iterrows():
        code = row["code"]
        direction = row["direction"]
        sim_p = f"{row['sim_price']:.3f}" if pd.notna(row.get("sim_price")) else "N/A"
        qmt_p = f"{row['qmt_price']:.3f}" if pd.notna(row.get("qmt_price")) else "N/A"
        diff = f"{row['price_diff_bps']:+.2f}" if pd.notna(row.get("price_diff_bps")) else "N/A"
        print(f"  {code:<12} {direction:>4} {sim_p:>10} {qmt_p:>10} {diff:>10}")


def main() -> None:
    """主入口。"""
    parser = argparse.ArgumentParser(description="SimBroker vs miniQMT成交对比")
    parser.add_argument("--date", type=str, help="交易日期(YYYY-MM-DD)")
    parser.add_argument("--start", type=str, help="开始日期")
    parser.add_argument("--end", type=str, help="结束日期")
    parser.add_argument("--realtime", action="store_true", help="从miniQMT实时查询(需QMT在线)")
    args = parser.parse_args()

    # 默认今天
    if args.date:
        dates = [datetime.strptime(args.date, "%Y-%m-%d").date()]
    elif args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
        dates = pd.bdate_range(start, end).date.tolist()
    else:
        dates = [date.today()]

    conn = psycopg2.connect(DB_CONN)

    # 可选: 连接miniQMT实时查询
    qmt_broker = None
    if args.realtime:
        try:
            from engines.broker_qmt import MiniQMTBroker
            qmt_broker = MiniQMTBroker(
                qmt_path=r"E:\国金QMT交易端模拟\userdata_mini",
                account_id="81001102",
            )
            qmt_broker.connect()
            logger.info("miniQMT已连接(实时查询模式)")
        except Exception as e:
            logger.warning(f"miniQMT连接失败，将使用DB记录: {e}")

    try:
        for d in dates:
            sim_df = get_simbroker_fills(conn, d)
            if args.realtime and qmt_broker:
                qmt_df = get_qmt_fills_realtime(qmt_broker)
            else:
                qmt_df = get_qmt_fills(conn, d)

            if sim_df.empty and qmt_df.empty:
                logger.info(f"{d}: 两侧均无成交")
                continue

            merged = compare_fills(sim_df, qmt_df)
            print_comparison_report(merged, d)
    finally:
        conn.close()
        if qmt_broker:
            qmt_broker.disconnect()


if __name__ == "__main__":
    main()
