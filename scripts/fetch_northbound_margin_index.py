#!/usr/bin/env python3
"""子任务3+4: 拉取index_components + margin_data + moneyflow_hsgt。

确认的API:
- index_components: Tushare index_weight ✅ (2100行/次)
- margin_data: Tushare margin_detail ✅ (4332行/次)
- northbound聚合: Tushare moneyflow_hsgt ✅ (日度, 非个股)
- northbound个股: hk_hold 返回0行(积分不够), AKShare备选

策略: 先拉index_components和margin(最重要), northbound个股留TODO。
"""
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def get_pro():
    import tushare as ts

    from app.config import settings
    return ts.pro_api(settings.TUSHARE_TOKEN)


def fetch_index_components(conn):
    """拉取CSI300和CSI500历史成分股权重(每月一个快照)。"""
    pro = get_pro()
    cur = conn.cursor()
    total = 0

    for idx_code, idx_name in [("399300.SZ", "CSI300"), ("000905.SH", "CSI500")]:
        logger.info(f"拉取{idx_name}成分股...")
        for year in range(2020, 2027):
            for month in range(1, 13):
                td = f"{year}{month:02d}01"
                if int(td) > 20260403:
                    break
                try:
                    df = pro.index_weight(index_code=idx_code, start_date=td, end_date=td)
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            w = float(row["weight"])
                            if w > 1:
                                w = w / 100  # percent to decimal
                            # Strip .SZ/.SH suffix to match symbols.code format
                            con_code = str(row["con_code"]).split(".")[0]
                            cur.execute(
                                """INSERT INTO index_components (index_code, code, trade_date, weight)
                                   VALUES (%s, %s, %s, %s)
                                   ON CONFLICT (index_code, code, trade_date)
                                   DO UPDATE SET weight = EXCLUDED.weight""",
                                (row["index_code"], con_code,
                                 datetime.strptime(str(row["trade_date"]), "%Y%m%d").date(), w))
                            total += 1
                        conn.commit()
                    time.sleep(0.15)
                except Exception as e:
                    conn.rollback()
                    logger.debug(f"  {idx_name} {td}: {e}")
                    time.sleep(0.5)

        logger.info(f"  {idx_name}: 累计{total}行")

    # Verify
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT index_code), COUNT(DISTINCT trade_date), MIN(trade_date), MAX(trade_date) FROM index_components")
    r = cur.fetchone()
    logger.info(f"  验证: {r[0]}行, {r[1]}指数, {r[2]}日期, {r[3]}~{r[4]}")
    return r[0]


def fetch_margin(conn):
    """拉取融资融券明细(每月一天, 覆盖2021-2026)。"""
    pro = get_pro()
    cur = conn.cursor()

    # 获取月末交易日
    cur.execute("""SELECT MAX(trade_date) FROM klines_daily
                   WHERE volume > 0 AND trade_date >= '2021-01-01'
                   GROUP BY DATE_TRUNC('month', trade_date)
                   ORDER BY 1""")
    month_ends = [r[0] for r in cur.fetchall()]
    logger.info(f"margin: 拉取{len(month_ends)}个月末日期")

    total = 0
    for td in month_ends:
        td_str = td.strftime("%Y%m%d")
        try:
            df = pro.margin_detail(trade_date=td_str)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    raw_code = row.get("ts_code", "")
                    if not raw_code:
                        continue
                    code = str(raw_code).split(".")[0]  # Strip .SZ/.SH
                    # Skip ETFs/funds (5xxxxx/1xxxxx) — only keep stocks (0/3/6/8/9 prefix)
                    if code.startswith("5") or code.startswith("1"):
                        continue
                    try:
                        cur.execute(
                            """INSERT INTO margin_data (code, trade_date, margin_balance, margin_buy, short_balance, short_vol)
                               VALUES (%s, %s, %s, %s, %s, %s)
                               ON CONFLICT (code, trade_date) DO UPDATE
                               SET margin_balance = EXCLUDED.margin_balance, margin_buy = EXCLUDED.margin_buy,
                                   short_balance = EXCLUDED.short_balance, short_vol = EXCLUDED.short_vol""",
                            (code, td,
                             float(row.get("rzye", 0) or 0),
                             float(row.get("rzmre", 0) or 0),
                             float(row.get("rqye", 0) or 0),
                             int(row.get("rqyl", 0) or 0)))
                        total += 1
                    except Exception:
                        conn.rollback()
                conn.commit()
                logger.info(f"  {td}: {len(df)}行")
            time.sleep(0.3)
        except Exception as e:
            conn.rollback()
            logger.warning(f"  margin {td_str}: {e}")
            time.sleep(1)

    # Verify
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT code), MIN(trade_date), MAX(trade_date) FROM margin_data")
    r = cur.fetchone()
    logger.info(f"  验证: {r[0]}行, {r[1]}股票, {r[2]}~{r[3]}")
    return r[0]


def main():
    t0 = time.time()
    conn = _get_sync_conn()

    # 1. index_components (最重要: 修复IC前瞻偏差)
    print("=" * 60)
    print("SUB-TASK 4: INDEX COMPONENTS (CSI300/500)")
    print("=" * 60)
    n_idx = fetch_index_components(conn)

    # 2. margin_data
    print("\n" + "=" * 60)
    print("SUB-TASK 3: MARGIN DATA")
    print("=" * 60)
    n_margin = fetch_margin(conn)

    conn.close()

    print(f"\n{'='*50}")
    print("DATA PULL SUMMARY")
    print(f"{'='*50}")
    print(f"  index_components: {n_idx} rows")
    print(f"  margin_data:      {n_margin} rows")
    print("  northbound:       SKIPPED (hk_hold需更高积分, TODO: AKShare)")

    elapsed = time.time() - t0
    print(f"\n总耗时: {elapsed:.0f}s ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
