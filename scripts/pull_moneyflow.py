#!/usr/bin/env python3
"""拉取Tushare moneyflow（个股资金流向）→ moneyflow_daily表。

CLAUDE.md原则2: 数据源接入前必须过checklist。
关键规则:
  1. 金额字段单位=万元（与daily.amount千元差10倍！）
  2. buy_xx_amount是总买入，不是净买入
  3. 按日期逐日拉取（每日一次API，返回全市场当日数据）
  4. 限速: 200次/分钟 → sleep 0.35s
  5. 断点续传: 查DB中MAX(trade_date)，从下一天开始

用法:
    python scripts/pull_moneyflow.py                         # 断点续传（默认2021-01-01起）
    python scripts/pull_moneyflow.py --start 20260301        # 指定起始日期
    python scripts/pull_moneyflow.py --verify                # 仅验证
    python scripts/pull_moneyflow.py --recent                # 仅拉最近1个月（验证用）
"""

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd
import psycopg2
import psycopg2.extras
import tushare as ts

from app.config import settings
from app.services.price_utils import _get_sync_conn

pro = ts.pro_api(settings.TUSHARE_TOKEN)

# Tushare moneyflow 字段
MF_FIELDS = [
    "ts_code", "trade_date",
    "buy_sm_vol", "buy_sm_amount", "sell_sm_vol", "sell_sm_amount",
    "buy_md_vol", "buy_md_amount", "sell_md_vol", "sell_md_amount",
    "buy_lg_vol", "buy_lg_amount", "sell_lg_vol", "sell_lg_amount",
    "buy_elg_vol", "buy_elg_amount", "sell_elg_vol", "sell_elg_amount",
    "net_mf_vol", "net_mf_amount",
]

DEFAULT_START = "20210101"
DEFAULT_END = date.today().strftime("%Y%m%d")


def get_trading_dates(start: str, end: str) -> list[str]:
    """从Tushare获取交易日列表。"""
    df = pro.trade_cal(
        exchange="SSE",
        start_date=start,
        end_date=end,
        fields="cal_date,is_open",
    )
    return sorted(df[df["is_open"] == 1]["cal_date"].tolist())


def get_max_trade_date(conn: psycopg2.extensions.connection) -> str | None:
    """查询moneyflow_daily中最大trade_date，用于断点续传。"""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(trade_date) FROM moneyflow_daily;")
        row = cur.fetchone()
        if row and row[0]:
            return row[0].strftime("%Y%m%d")
    return None


def get_valid_codes(conn: psycopg2.extensions.connection) -> set[str]:
    """获取symbols表中所有有效code（含退市），用于过滤。"""
    with conn.cursor() as cur:
        cur.execute("SELECT code FROM symbols;")
        return {r[0] for r in cur.fetchall()}


def fetch_moneyflow_by_date(trade_date: str, retry: int = 3) -> pd.DataFrame:
    """按日期拉取当日全市场资金流向。

    Args:
        trade_date: YYYYMMDD格式日期
        retry: 重试次数

    Returns:
        DataFrame，可能为空
    """
    for attempt in range(retry):
        try:
            df = pro.moneyflow(
                trade_date=trade_date,
                fields=",".join(MF_FIELDS),
            )
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            err_msg = str(e)
            if "每分钟" in err_msg or "频次" in err_msg or "too many" in err_msg.lower():
                print("  [限频] 等待60s...")
                time.sleep(60)
            elif "权限" in err_msg:
                raise
            else:
                wait = 5 * (attempt + 1)
                print(f"  [重试 {attempt+1}/{retry}] {e}, 等待{wait}s")
                time.sleep(wait)
    print(f"  [失败] {trade_date} 经过{retry}次重试仍失败，跳过")
    return pd.DataFrame()


def upsert_moneyflow(conn: psycopg2.extensions.connection, df: pd.DataFrame, valid_codes: set[str]) -> int:
    """将moneyflow数据upsert入库（通过DataPipeline）。

    Pipeline自动处理: rename(ts_code→code) + 单位转换(万元→元) + 验证 + FK过滤 + upsert。

    Args:
        conn: 数据库连接
        df: Tushare返回的DataFrame
        valid_codes: 不再使用(Pipeline内部做FK过滤)

    Returns:
        实际写入行数
    """
    if df.empty:
        return 0

    from app.data_fetcher.contracts import MONEYFLOW_DAILY
    from app.data_fetcher.pipeline import DataPipeline

    # trade_date确保是date类型
    df = df.copy()
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    pipeline = DataPipeline(conn)
    result = pipeline.ingest(df, MONEYFLOW_DAILY)
    if result.rejected_rows > 0:
        print(
            f"moneyflow: {result.rejected_rows}/{result.total_rows} rows rejected: "
            f"{result.reject_reasons}"
        )
    return result.upserted_rows


def add_column_comments(conn: psycopg2.extensions.connection) -> None:
    """为moneyflow_daily表添加单位注释（万元/手）。"""
    comments = {
        "buy_sm_amount": "小单买入金额（万元）",
        "sell_sm_amount": "小单卖出金额（万元）",
        "buy_md_amount": "中单买入金额（万元）",
        "sell_md_amount": "中单卖出金额（万元）",
        "buy_lg_amount": "大单买入金额（万元）",
        "sell_lg_amount": "大单卖出金额（万元）",
        "buy_elg_amount": "特大单买入金额（万元）",
        "sell_elg_amount": "特大单卖出金额（万元）",
        "net_mf_amount": "净流入额（万元）",
        "buy_sm_vol": "小单买入量（手，1手=100股）",
        "sell_sm_vol": "小单卖出量（手）",
        "buy_md_vol": "中单买入量（手）",
        "sell_md_vol": "中单卖出量（手）",
        "buy_lg_vol": "大单买入量（手）",
        "sell_lg_vol": "大单卖出量（手）",
        "buy_elg_vol": "特大单买入量（手）",
        "sell_elg_vol": "特大单卖出量（手）",
        "net_mf_vol": "净流入量（手）",
    }
    with conn.cursor() as cur:
        for col, comment in comments.items():
            cur.execute(f"COMMENT ON COLUMN moneyflow_daily.{col} IS %s;", (comment,))
    conn.commit()
    print("[注释] moneyflow_daily列注释已更新（单位：万元/手）")


def verify(conn: psycopg2.extensions.connection) -> None:
    """验证已入库数据。"""
    with conn.cursor() as cur:
        # 总行数
        cur.execute("SELECT COUNT(*) FROM moneyflow_daily;")
        total = cur.fetchone()[0]
        print("\n=== moneyflow_daily 验证 ===")
        print(f"总行数: {total:,}")

        if total == 0:
            print("表为空，无法验证。")
            return

        # 日期范围
        cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM moneyflow_daily;")
        min_d, max_d = cur.fetchone()
        print(f"日期范围: {min_d} ~ {max_d}")

        # 每日覆盖率（最近5个交易日）
        cur.execute("""
            SELECT trade_date, COUNT(*)
            FROM moneyflow_daily
            WHERE trade_date >= (SELECT MAX(trade_date) - interval '10 days' FROM moneyflow_daily)
            GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5;
        """)
        print("\n最近5个交易日覆盖率:")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]:,} 只")

        # 注意: Tushare的net_mf_amount是基于主动买卖方向的净流入，
        # 不等于 sum(buy_xx_amount) - sum(sell_xx_amount)（后者按订单大小分类，买卖各自平衡≈0）。
        # 因此不做 net_mf_amount vs 分项之和的一致性检查。
        # 改为检查: 各size的buy+sell金额应为正数（不应有负值）
        cur.execute("""
            SELECT COUNT(*) FROM moneyflow_daily
            WHERE buy_sm_amount < 0 OR sell_sm_amount < 0
               OR buy_md_amount < 0 OR sell_md_amount < 0
               OR buy_lg_amount < 0 OR sell_lg_amount < 0
               OR buy_elg_amount < 0 OR sell_elg_amount < 0;
        """)
        negative = cur.fetchone()[0]
        print(f"\n数据合理性检查（买卖金额出现负值的行数）: {negative:,} 条")

        # 茅台抽样
        cur.execute("""
            SELECT trade_date, buy_elg_amount, sell_elg_amount, net_mf_amount
            FROM moneyflow_daily
            WHERE code = '600519'
            ORDER BY trade_date DESC LIMIT 3;
        """)
        rows = cur.fetchall()
        if rows:
            print("\n茅台(600519)最近资金流向抽样（金额单位：万元）:")
            for r in rows:
                print(f"  {r[0]}: 特大单买={r[1]}, 特大单卖={r[2]}, 净流入={r[3]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取moneyflow数据")
    parser.add_argument("--start", type=str, default=None, help="起始日期YYYYMMDD")
    parser.add_argument("--end", type=str, default=DEFAULT_END, help="结束日期YYYYMMDD")
    parser.add_argument("--verify", action="store_true", help="仅验证")
    parser.add_argument("--recent", action="store_true", help="仅拉最近1个月")
    args = parser.parse_args()

    conn = _get_sync_conn()

    if args.verify:
        verify(conn)
        conn.close()
        return

    # 添加列注释
    add_column_comments(conn)

    # 确定起始日期
    if args.recent:
        start_date = (date.today() - timedelta(days=35)).strftime("%Y%m%d")
        end_date = args.end
        print(f"[模式] 仅拉最近1个月: {start_date} ~ {end_date}")
    elif args.start:
        start_date = args.start
        end_date = args.end
    else:
        # 断点续传
        max_date = get_max_trade_date(conn)
        if max_date:
            # 从max_date的下一天开始
            next_day = datetime.strptime(max_date, "%Y%m%d") + timedelta(days=1)
            start_date = next_day.strftime("%Y%m%d")
            print(f"[断点续传] DB最新日期={max_date}, 从{start_date}开始")
        else:
            start_date = DEFAULT_START
        end_date = args.end

    if start_date > end_date:
        print(f"[完成] 起始日期{start_date} > 结束日期{end_date}，无需拉取")
        verify(conn)
        conn.close()
        return

    # 获取交易日列表
    print(f"[准备] 获取交易日历 {start_date} ~ {end_date}")
    trading_dates = get_trading_dates(start_date, end_date)
    print(f"[准备] 共 {len(trading_dates)} 个交易日待拉取")

    # 获取合法代码集合
    valid_codes = get_valid_codes(conn)
    print(f"[准备] symbols表共 {len(valid_codes)} 个代码")

    total_rows = 0
    failed_dates = []

    # 最近日期（当天或昨天）需要重试，Tushare可能延迟入库
    MAX_RETRY = 5
    RETRY_WAIT = 120  # 2分钟（17:00→17:02→17:04→17:06→17:08）

    for i, td in enumerate(trading_dates):
        t0 = time.time()
        df = fetch_moneyflow_by_date(td)

        # 对最近日期(今天/昨天)的空数据做重试
        is_recent = td >= (date.today() - timedelta(days=1)).strftime("%Y%m%d")
        if df.empty and is_recent:
            for attempt in range(1, MAX_RETRY + 1):
                print(f"  [{i+1}/{len(trading_dates)}] {td} — 空数据，重试 {attempt}/{MAX_RETRY}（等待{RETRY_WAIT}s）")
                time.sleep(RETRY_WAIT)
                df = fetch_moneyflow_by_date(td)
                if not df.empty:
                    break
            if df.empty:
                print(f"  [{i+1}/{len(trading_dates)}] {td} — {MAX_RETRY}次重试后仍为空，发送告警")
                failed_dates.append(td)
                try:
                    from app.services.dispatchers.dingtalk import send_markdown_sync
                    send_markdown_sync(
                        title=f"moneyflow数据延迟 {td}",
                        text=f"**[P0] moneyflow_daily** {td} 数据经{MAX_RETRY}次重试(间隔{RETRY_WAIT}s)仍为空\n\nTushare可能延迟入库，请手动检查",
                    )
                except Exception:
                    print("  [告警] DingTalk发送失败")
                continue
        elif df.empty:
            print(f"  [{i+1}/{len(trading_dates)}] {td} — 空数据（非近期，跳过）")
            time.sleep(0.35)
            continue

        rows = upsert_moneyflow(conn, df, valid_codes)
        elapsed = time.time() - t0
        total_rows += rows
        print(f"  [{i+1}/{len(trading_dates)}] {td} — {rows:,} 行 ({elapsed:.1f}s)")

        # 限速: 200次/分钟 → 0.35s间隔
        sleep_time = max(0.35 - elapsed, 0)
        if sleep_time > 0:
            time.sleep(sleep_time)

    print(f"\n[完成] 共写入 {total_rows:,} 行")
    if failed_dates:
        print(f"[警告] 失败日期: {failed_dates}")

    # 验证
    verify(conn)
    conn.close()


if __name__ == "__main__":
    # 交易日历检查（非交易日跳过，DailyBackup除外）
    try:
        conn_check = _get_sync_conn()
        cur_check = conn_check.cursor()
        cur_check.execute(
            """SELECT is_trading_day FROM trading_calendar
               WHERE market = 'astock' AND trade_date = %s""",
            (date.today(),),
        )
        row_check = cur_check.fetchone()
        conn_check.close()
        if row_check and not row_check[0]:
            print(f"[{datetime.now()}] 非交易日，跳过moneyflow拉取")
            sys.exit(0)
    except Exception:
        pass  # trading_calendar不可用时不阻塞
    main()
