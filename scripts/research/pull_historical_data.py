#!/usr/bin/env python3
"""补拉2014-2019历史数据 — klines_daily + daily_basic + index_daily + adj_factor + stk_limit + moneyflow。

用法:
    python scripts/research/pull_historical_data.py
    python scripts/research/pull_historical_data.py --start 2014-01-01 --end 2019-12-31
    python scripts/research/pull_historical_data.py --table klines  # 只拉行情
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd
import tushare as ts

from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

pro = ts.pro_api()


def get_trading_dates(start: str, end: str) -> list[str]:
    """获取交易日历。"""
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end)
    return sorted(cal[cal["is_open"] == 1]["cal_date"].tolist())


def pull_klines(trading_dates: list[str], conn):
    """拉取日线行情(daily + adj_factor + stk_limit)。"""
    cur = conn.cursor()
    total = len(trading_dates)
    for i, td in enumerate(trading_dates):
        # 检查是否已存在
        cur.execute("SELECT COUNT(*) FROM klines_daily WHERE trade_date = %s", (td,))
        if cur.fetchone()[0] > 100:
            if (i + 1) % 100 == 0:
                logger.info("[klines] %d/%d %s 已存在, 跳过", i + 1, total, td)
            continue

        try:
            # daily
            df = pro.daily(trade_date=td)
            time.sleep(0.15)
            if df is None or df.empty:
                continue

            # adj_factor
            adj = pro.adj_factor(trade_date=td)
            time.sleep(0.15)

            # stk_limit
            lmt = pro.stk_limit(trade_date=td)
            time.sleep(0.15)

            # 合并
            df = df.rename(columns={"ts_code": "code", "vol": "volume"})
            if adj is not None and not adj.empty:
                adj = adj.rename(columns={"ts_code": "code"})
                df = df.merge(adj[["code", "adj_factor"]], on="code", how="left")
            else:
                df["adj_factor"] = 1.0

            if lmt is not None and not lmt.empty:
                lmt = lmt.rename(columns={"ts_code": "code"})
                df = df.merge(lmt[["code", "up_limit", "down_limit"]], on="code", how="left")

            # 写入
            for _, row in df.iterrows():
                cur.execute(
                    """INSERT INTO klines_daily
                       (code, trade_date, open, high, low, close, pre_close, volume, amount,
                        adj_factor, up_limit, down_limit)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (code, trade_date) DO UPDATE SET
                        open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                        close=EXCLUDED.close, pre_close=EXCLUDED.pre_close,
                        volume=EXCLUDED.volume, amount=EXCLUDED.amount,
                        adj_factor=EXCLUDED.adj_factor,
                        up_limit=EXCLUDED.up_limit, down_limit=EXCLUDED.down_limit""",
                    (
                        row.get("code"), td,
                        row.get("open"), row.get("high"), row.get("low"), row.get("close"),
                        row.get("pre_close"), row.get("volume"), row.get("amount"),
                        row.get("adj_factor"), row.get("up_limit"), row.get("down_limit"),
                    ),
                )
            conn.commit()

            if (i + 1) % 20 == 0:
                logger.info("[klines] %d/%d %s: %d行", i + 1, total, td, len(df))

        except Exception as e:
            logger.warning("[klines] %s 失败: %s", td, e)
            conn.rollback()
            time.sleep(2)


def pull_daily_basic(trading_dates: list[str], conn):
    """拉取每日基本面指标。"""
    cur = conn.cursor()
    fields = "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv"
    total = len(trading_dates)

    for i, td in enumerate(trading_dates):
        cur.execute("SELECT COUNT(*) FROM daily_basic WHERE trade_date = %s", (td,))
        if cur.fetchone()[0] > 100:
            if (i + 1) % 100 == 0:
                logger.info("[basic] %d/%d %s 已存在", i + 1, total, td)
            continue

        try:
            df = pro.daily_basic(trade_date=td, fields=fields)
            time.sleep(0.3)  # daily_basic限速更严
            if df is None or df.empty:
                continue

            df = df.rename(columns={"ts_code": "code"})
            skipped = 0
            for _, row in df.iterrows():
                try:
                    cur.execute("SAVEPOINT sp_row")
                    cur.execute(
                        """INSERT INTO daily_basic
                           (code, trade_date, turnover_rate, volume_ratio, pe_ttm, pb, dv_ttm,
                            total_mv, circ_mv)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (code, trade_date) DO UPDATE SET
                            turnover_rate=EXCLUDED.turnover_rate, pe_ttm=EXCLUDED.pe_ttm,
                            pb=EXCLUDED.pb, dv_ttm=EXCLUDED.dv_ttm,
                            total_mv=EXCLUDED.total_mv, circ_mv=EXCLUDED.circ_mv""",
                        (
                            row.get("code"), td,
                            row.get("turnover_rate"), row.get("volume_ratio"),
                            row.get("pe_ttm"), row.get("pb"), row.get("dv_ttm"),
                            row.get("total_mv"), row.get("circ_mv"),
                        ),
                    )
                    cur.execute("RELEASE SAVEPOINT sp_row")
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_row")
                    skipped += 1
            conn.commit()

            if (i + 1) % 20 == 0:
                logger.info("[basic] %d/%d %s: %d行", i + 1, total, td, len(df))

        except Exception as e:
            logger.warning("[basic] %s 失败: %s", td, e)
            conn.rollback()
            time.sleep(2)


def pull_index_daily(start: str, end: str, conn):
    """拉取指数日线(CSI300/CSI500/上证综指)。"""
    cur = conn.cursor()
    indices = ["000300.SH", "000905.SH", "000001.SH"]
    for idx_code in indices:
        try:
            df = pro.index_daily(ts_code=idx_code, start_date=start, end_date=end)
            time.sleep(0.3)
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                cur.execute(
                    """INSERT INTO index_daily
                       (index_code, trade_date, open, high, low, close, volume, amount, pct_change)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (index_code, trade_date) DO UPDATE SET
                        close=EXCLUDED.close, pct_change=EXCLUDED.pct_change""",
                    (
                        idx_code, row.get("trade_date"),
                        row.get("open"), row.get("high"), row.get("low"), row.get("close"),
                        row.get("vol"), row.get("amount"), row.get("pct_chg"),
                    ),
                )
            conn.commit()
            logger.info("[index] %s: %d行", idx_code, len(df))
        except Exception as e:
            logger.warning("[index] %s 失败: %s", idx_code, e)
            conn.rollback()


def pull_moneyflow(trading_dates: list[str], conn):
    """拉取资金流向(尽量补，可能部分日期无数据)。"""
    cur = conn.cursor()
    total = len(trading_dates)
    for i, td in enumerate(trading_dates):
        cur.execute("SELECT COUNT(*) FROM moneyflow_daily WHERE trade_date = %s", (td,))
        if cur.fetchone()[0] > 100:
            continue

        try:
            df = pro.moneyflow(trade_date=td)
            time.sleep(0.3)
            if df is None or df.empty:
                continue
            df = df.rename(columns={"ts_code": "code"})
            skipped = 0
            for _, row in df.iterrows():
                try:
                    cur.execute("SAVEPOINT sp_mf")
                    cur.execute(
                        """INSERT INTO moneyflow_daily
                           (code, trade_date, net_mf_amount, buy_lg_amount, sell_lg_amount,
                            buy_elg_amount, sell_elg_amount, buy_md_amount, sell_md_amount,
                            buy_sm_amount, sell_sm_amount)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (code, trade_date) DO NOTHING""",
                        (
                            row.get("code"), td,
                            row.get("net_mf_amount"), row.get("buy_lg_amount"), row.get("sell_lg_amount"),
                            row.get("buy_elg_amount"), row.get("sell_elg_amount"),
                            row.get("buy_md_amount"), row.get("sell_md_amount"),
                            row.get("buy_sm_amount"), row.get("sell_sm_amount"),
                        ),
                    )
                    cur.execute("RELEASE SAVEPOINT sp_mf")
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_mf")
                    skipped += 1
            conn.commit()
            if (i + 1) % 50 == 0:
                logger.info("[moneyflow] %d/%d %s: %d行", i + 1, total, td, len(df))
        except Exception as e:
            logger.warning("[moneyflow] %s 失败: %s", td, e)
            conn.rollback()
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description="补拉2014-2019历史数据")
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--end", default="2019-12-31")
    parser.add_argument("--table", default="all", choices=["all", "klines", "basic", "index", "moneyflow"])
    args = parser.parse_args()

    start_str = args.start.replace("-", "")
    end_str = args.end.replace("-", "")

    conn = _get_sync_conn()

    logger.info("=" * 60)
    logger.info("补拉历史数据: %s ~ %s (table=%s)", args.start, args.end, args.table)
    logger.info("=" * 60)

    t0 = time.time()

    # 交易日历
    trading_dates = get_trading_dates(start_str, end_str)
    logger.info("交易日: %d天 (%s ~ %s)", len(trading_dates), trading_dates[0], trading_dates[-1])

    if args.table in ("all", "index"):
        pull_index_daily(start_str, end_str, conn)

    if args.table in ("all", "klines"):
        pull_klines(trading_dates, conn)

    if args.table in ("all", "basic"):
        pull_daily_basic(trading_dates, conn)

    if args.table in ("all", "moneyflow"):
        pull_moneyflow(trading_dates, conn)

    elapsed = time.time() - t0
    logger.info("完成! 总耗时 %.0f分钟", elapsed / 60)

    # 验证
    cur = conn.cursor()
    for table in ["klines_daily", "daily_basic", "index_daily", "moneyflow_daily"]:
        cur.execute(f"SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) FROM {table}")
        r = cur.fetchone()
        logger.info("  %s: %s ~ %s (%s天)", table, r[0], r[1], r[2])

    conn.close()


if __name__ == "__main__":
    main()
