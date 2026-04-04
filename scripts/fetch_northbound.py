"""北向资金数据拉取 — Tushare hk_hold → northbound_holdings表。

用法:
    python scripts/fetch_northbound.py
    python scripts/fetch_northbound.py --start 20240801  # 指定起始日
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras
import tushare as ts
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])


def get_db_conn():
    return psycopg2.connect(dbname="quantmind_v2", user="xin", password="quantmind", host="localhost")


def get_trading_dates(conn, start, end):
    """获取交易日列表。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT trade_date FROM trading_calendar WHERE market='astock' AND is_trading_day=TRUE "
        "AND trade_date BETWEEN %s AND %s ORDER BY trade_date",
        (start, end),
    )
    return [r[0] for r in cur.fetchall()]


def get_latest_date(conn):
    """获取已有数据的最新日期。"""
    cur = conn.cursor()
    cur.execute("SELECT MAX(trade_date) FROM northbound_holdings")
    r = cur.fetchone()
    return r[0] if r and r[0] else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=None, help="起始日期 YYYYMMDD")
    args = parser.parse_args()

    conn = get_db_conn()
    latest = get_latest_date(conn)
    logger.info("当前最新数据: %s", latest)

    if args.start:
        start = datetime.strptime(args.start, "%Y%m%d").date()
    elif latest:
        start = latest + timedelta(days=1)
    else:
        start = date(2020, 1, 1)  # 从2020年开始全量拉

    end = date(2026, 4, 5)
    trading_dates = get_trading_dates(conn, start, end)
    logger.info("拉取范围: %s ~ %s, 交易日: %d个", start, end, len(trading_dates))

    cur = conn.cursor()
    total = 0
    errors = 0

    for i, td in enumerate(trading_dates):
        td_str = td.strftime("%Y%m%d")
        try:
            df = pro.hk_hold(trade_date=td_str)
            if df is None or df.empty:
                time.sleep(0.3)
                continue

            rows = []
            for _, r in df.iterrows():
                ts_code = r.get("ts_code", "")
                code = ts_code.split(".")[0] if "." in str(ts_code) else str(r.get("code", ""))
                rows.append((
                    code,
                    td,
                    int(r["vol"]) if r["vol"] and r["vol"] == r["vol"] else 0,
                    float(r["ratio"]) if r["ratio"] and r["ratio"] == r["ratio"] else None,
                    None,  # hold_mv (hk_hold没有市值字段，后续可补算)
                    None,  # net_buy_vol (需要T-1数据差分计算)
                ))

            if rows:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO northbound_holdings (code, trade_date, hold_vol, hold_ratio, hold_mv, net_buy_vol)
                       VALUES %s ON CONFLICT DO NOTHING""",
                    rows, page_size=5000,
                )
                conn.commit()
                total += len(rows)

        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.warning("%s 拉取失败: %s", td_str, str(e)[:80])
            if "每分钟" in str(e) or "频率" in str(e):
                time.sleep(15)

        if (i + 1) % 50 == 0:
            logger.info("进度: %d/%d天, 累计%d行, 错误%d", i + 1, len(trading_dates), total, errors)
        time.sleep(0.35)

    logger.info("拉取完成: %d行, 错误%d", total, errors)

    # 验证
    cur.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*), COUNT(DISTINCT trade_date) FROM northbound_holdings")
    r = cur.fetchone()
    logger.info("验证: %s ~ %s, %d行, %d交易日", r[0], r[1], r[2], r[3])

    conn.close()


if __name__ == "__main__":
    main()
