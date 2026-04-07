"""盈利公告数据拉取 — Tushare fina_indicator → earnings_announcements表。

用法:
    python scripts/fetch_earnings.py
    python scripts/fetch_earnings.py --start 20200101  # 断点续传
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
import tushare as ts
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])

# 所有季度末日期 (2015Q1 ~ 2025Q4)
PERIODS = []
for y in range(2015, 2027):
    for m in ["0331", "0630", "0930", "1231"]:
        p = f"{y}{m}"
        if int(p) <= 20251231:
            PERIODS.append(p)

REPORT_TYPE_MAP = {"0331": "Q1", "0630": "H1", "0930": "Q3", "1231": "Y"}


def get_db_conn():
    """获取数据库连接。"""
    return psycopg2.connect(dbname="quantmind_v2", user="xin", password="quantmind", host="localhost")


def get_trading_dates(conn) -> set:
    """从trading_calendar获取所有交易日集合。"""
    cur = conn.cursor()
    cur.execute("SELECT trade_date FROM trading_calendar WHERE market='astock' AND is_trading_day=TRUE")
    return {r[0] for r in cur.fetchall()}


def next_trading_day(dt: date, trading_dates: set) -> date:
    """找到dt当天或之后的第一个交易日。"""
    from datetime import timedelta

    for i in range(10):  # 最多往后找10天（长假）
        candidate = dt + timedelta(days=i)
        if candidate in trading_dates:
            return candidate
    return dt  # fallback


def get_done_periods(conn) -> set:
    """查询已拉取的period（断点续传）。"""
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT TO_CHAR(end_date, 'YYYYMMDD') FROM earnings_announcements")
    return {r[0] for r in cur.fetchall()}


def fetch_period(period: str, trading_dates: set) -> pd.DataFrame:
    """拉取单个季度的income_vip数据（支持按period批量拉）。"""
    try:
        # income_vip: 支持按period批量拉，含f_ann_date和basic_eps
        df = pro.income_vip(
            period=period,
            fields="ts_code,ann_date,f_ann_date,end_date,basic_eps",
        )
        time.sleep(0.35)

        if df is None or df.empty:
            return pd.DataFrame()

        # 去重：同一(ts_code, end_date)保留f_ann_date最早的（市场首次获悉）
        df = df.sort_values("f_ann_date").drop_duplicates(subset=["ts_code", "end_date"], keep="first")

        # 过滤无公告日的
        merged = df[["ts_code", "end_date", "ann_date", "f_ann_date", "basic_eps"]].copy()
        merged = merged.dropna(subset=["f_ann_date"])
        merged = merged.rename(columns={"ann_date": "ann_date_raw"})

        # 日期转换
        for col in ["f_ann_date", "ann_date_raw"]:
            merged[col] = pd.to_datetime(merged[col], errors="coerce")
        merged["end_date"] = pd.to_datetime(merged["end_date"], format="%Y%m%d", errors="coerce")

        merged = merged.dropna(subset=["f_ann_date", "end_date"])

        # 非交易日对齐
        merged["trade_date"] = merged["f_ann_date"].apply(
            lambda d: next_trading_day(d.date(), trading_dates) if pd.notna(d) else None
        )

        # report_type
        merged["report_type"] = merged["end_date"].apply(
            lambda d: REPORT_TYPE_MAP.get(d.strftime("%m%d"), "?") if pd.notna(d) else "?"
        )

        return merged

    except Exception as e:
        logger.warning("拉取 %s 失败: %s", period, e)
        return pd.DataFrame()


def compute_surprise(conn):
    """计算EPS Surprise（同比：当季 - 4季度前）。"""
    cur = conn.cursor()
    cur.execute("""
        UPDATE earnings_announcements ea
        SET eps_q4_ago = prev.basic_eps,
            eps_surprise = ea.basic_eps - prev.basic_eps,
            eps_surprise_pct = CASE
                WHEN ABS(prev.basic_eps) > 0.001 THEN (ea.basic_eps - prev.basic_eps) / ABS(prev.basic_eps)
                ELSE NULL
            END
        FROM earnings_announcements prev
        WHERE ea.ts_code = prev.ts_code
          AND prev.end_date = ea.end_date - INTERVAL '1 year'
          AND ea.basic_eps IS NOT NULL
          AND prev.basic_eps IS NOT NULL
    """)
    updated = cur.rowcount
    conn.commit()
    logger.info("Surprise计算完成: %d行更新", updated)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="20150331", help="起始period")
    args = parser.parse_args()

    conn = get_db_conn()
    trading_dates = get_trading_dates(conn)
    done_periods = get_done_periods(conn)
    logger.info("交易日: %d个, 已完成period: %d个", len(trading_dates), len(done_periods))

    # 补充2015-2018交易日历（如果缺失）
    if not any(d.year < 2019 for d in trading_dates):
        logger.info("补充2015-2018交易日历...")
        try:
            cal = pro.trade_cal(exchange="SSE", start_date="20150101", end_date="20181231")
            if cal is not None and not cal.empty:
                cur = conn.cursor()
                for _, r in cal.iterrows():
                    td = datetime.strptime(r["cal_date"], "%Y%m%d").date()
                    is_open = r["is_open"] == 1
                    cur.execute(
                        "INSERT INTO trading_calendar (trade_date, market, is_trading_day) "
                        "VALUES (%s, 'astock', %s) ON CONFLICT DO NOTHING",
                        (td, is_open),
                    )
                conn.commit()
                trading_dates = get_trading_dates(conn)
                logger.info("交易日历补充完成: %d个", len(trading_dates))
        except Exception as e:
            logger.warning("交易日历补充失败: %s", e)

    # 拉取
    todo = [p for p in PERIODS if p not in done_periods and p >= args.start]
    logger.info("待拉取: %d个period", len(todo))

    cur = conn.cursor()
    total_inserted = 0
    null_f_ann = 0

    for i, period in enumerate(todo):
        df = fetch_period(period, trading_dates)
        if df.empty:
            time.sleep(0.35)
            continue

        # 统计f_ann_date空值比例
        original_len = len(df)
        null_count = df["f_ann_date"].isna().sum()
        if original_len > 0:
            null_f_ann += null_count

        rows = []
        for _, r in df.iterrows():
            rows.append((
                r["ts_code"],
                r["end_date"].date() if pd.notna(r["end_date"]) else None,
                r["ann_date_raw"].date() if pd.notna(r.get("ann_date_raw")) else None,
                r["f_ann_date"].date() if pd.notna(r["f_ann_date"]) else None,
                r["trade_date"],
                float(r["basic_eps"]) if pd.notna(r.get("basic_eps")) else None,
                None,  # eps_q4_ago (后面批量算)
                None,  # eps_surprise
                None,  # eps_surprise_pct
                r["report_type"],
                "tushare",
            ))

        if rows:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO earnings_announcements
                    (ts_code, end_date, ann_date, f_ann_date, trade_date, basic_eps,
                     eps_q4_ago, eps_surprise, eps_surprise_pct, report_type, source)
                   VALUES %s
                   ON CONFLICT (ts_code, end_date) DO UPDATE
                   SET f_ann_date = EXCLUDED.f_ann_date,
                       trade_date = EXCLUDED.trade_date,
                       basic_eps = EXCLUDED.basic_eps,
                       report_type = EXCLUDED.report_type""",
                rows,
                page_size=500,
            )
            conn.commit()
            total_inserted += len(rows)

        if (i + 1) % 10 == 0:
            logger.info("进度: %d/%d periods, 累计 %d行", i + 1, len(todo), total_inserted)
        time.sleep(0.35)

    logger.info("拉取完成: %d行, f_ann_date空值: %d", total_inserted, null_f_ann)

    # 计算Surprise
    compute_surprise(conn)
    conn.close()
    logger.info("全部完成")


if __name__ == "__main__":
    main()
