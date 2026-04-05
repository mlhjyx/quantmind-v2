"""分钟数据拉取 — Baostock 5分钟K线 → minute_bars表。

Top-100市值股票，2021-01-01至2025-12-31。
Baostock免费，无积分限制，串行拉取。

用法:
    python scripts/fetch_minute_bars.py
    python scripts/fetch_minute_bars.py --start 2024-01-01  # 指定起始日
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import baostock as bs
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def load_stock_codes() -> list[str]:
    """加载股票列表：全量A股（排除北交所）。"""
    codes = set()
    # 全量A股
    all_file = Path(__file__).resolve().parent.parent / "models" / "all_astock_codes.txt"
    if all_file.exists():
        codes.update(c.strip() for c in all_file.read_text().splitlines() if c.strip())
        return sorted(codes)
    # Fallback: CSI500
    csi_file = Path(__file__).resolve().parent.parent / "models" / "csi500_codes.txt"
    if csi_file.exists():
        codes.update(c.strip() for c in csi_file.read_text().splitlines() if c.strip())
    # Top-100硬编码（确保大盘覆盖）
    top100 = [
        "601398", "601939", "601288", "601857", "600941", "601988", "600938", "600519",
        "300750", "601318", "601138", "601628", "601088", "600036", "002594", "601899",
        "688981", "600028", "300308", "600900", "601328", "601658", "000333", "601728",
        "688041", "601998", "300502", "688256", "000858", "601166", "603993", "600276",
        "688235", "601601", "002475", "600030", "002379", "600000", "601319", "002371",
        "603259", "300059", "601869", "601211", "002415", "688795", "300394", "600309",
        "300274", "600930", "002714", "601816", "601225", "603288", "688802", "601898",
        "601919", "300476", "600150", "003816", "000338", "000001", "000651", "600989",
        "600406", "601668", "002384", "002142", "600919", "600690", "600188", "601600",
        "300760", "000792", "002352", "601818", "688347", "601336", "600547", "688012",
        "600031", "601985", "600025", "300124", "601766", "601633", "002050", "302132",
        "603986", "600809", "600111", "002460", "600887", "601872", "001280", "601066",
        "002028", "600016", "600104", "601688",
    ]
    codes.update(top100)
    return sorted(codes)


def to_bs_code(code: str) -> str:
    """DB代码 → Baostock代码。"""
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    return f"sz.{code}"


def get_db_conn():
    return psycopg2.connect(dbname="quantmind_v2", user="xin", password="quantmind", host="localhost")


def get_latest_date(conn, ts_code: str) -> str | None:
    """获取该股票已有的最新日期（断点续传）。"""
    cur = conn.cursor()
    cur.execute("SELECT MAX(trade_date) FROM minute_bars WHERE ts_code = %s", (ts_code,))
    r = cur.fetchone()
    if r and r[0]:
        return r[0].strftime("%Y-%m-%d")
    return None


def fetch_stock(bs_code: str, ts_code: str, start: str, end: str, conn) -> int:
    """拉取单只股票的5分钟数据。"""
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,time,open,high,low,close,volume,amount",
        start_date=start, end_date=end,
        frequency="5", adjustflag="3",
    )

    if rs.error_code != "0":
        logger.warning("%s 查询失败: %s %s", ts_code, rs.error_code, rs.error_msg)
        return 0

    rows = []
    while rs.error_code == "0" and rs.next():
        data = rs.get_row_data()
        # data: [date, time, open, high, low, close, volume, amount]
        if len(data) < 8 or not data[0]:
            continue

        trade_date = data[0]  # YYYY-MM-DD
        trade_time_str = data[1]  # YYYYMMDDHHMMSSmmm

        try:
            trade_time = datetime.strptime(trade_time_str[:14], "%Y%m%d%H%M%S")
        except (ValueError, IndexError):
            continue

        rows.append((
            ts_code,
            trade_time,
            trade_date,
            float(data[2]) if data[2] else None,
            float(data[3]) if data[3] else None,
            float(data[4]) if data[4] else None,
            float(data[5]) if data[5] else None,
            int(data[6]) if data[6] else 0,
            float(data[7]) if data[7] else 0,
            "3",  # adjustflag = 不复权
        ))

        if len(rows) >= 500:
            _insert_batch(conn, rows)
            rows = []

    if rows:
        _insert_batch(conn, rows)
        total = len(rows)
    else:
        total = 0

    return total


def _insert_batch(conn, rows):
    cur = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        """INSERT INTO minute_bars (ts_code, trade_time, trade_date, open, high, low, close, volume, amount, adjustflag)
           VALUES %s ON CONFLICT (ts_code, trade_time) DO NOTHING""",
        rows, page_size=500,
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--shard", type=int, default=0, help="分片编号(0-based)")
    parser.add_argument("--total-shards", type=int, default=1, help="总分片数")
    args = parser.parse_args()

    lg = bs.login()
    if lg.error_code != "0":
        logger.error("Baostock登录失败: %s", lg.error_msg)
        return

    conn = get_db_conn()
    total_rows = 0
    skip_list = []
    ALL_CODES = load_stock_codes()
    # 分片支持：并行拉取
    if args.total_shards > 1:
        STOCK_CODES = [c for i, c in enumerate(ALL_CODES) if i % args.total_shards == args.shard]
        logger.info("分片 %d/%d: %d只 (总%d只)", args.shard, args.total_shards, len(STOCK_CODES), len(ALL_CODES))
    else:
        STOCK_CODES = ALL_CODES
        logger.info("股票列表: %d只 (全量)", len(STOCK_CODES))

    for i, code in enumerate(STOCK_CODES):
        bs_code = to_bs_code(code)

        # 断点续传
        latest = get_latest_date(conn, code)
        start = latest if latest and latest > args.start else args.start

        if latest and latest >= args.end:
            logger.info("[%d/%d] %s 已完成，跳过", i + 1, len(STOCK_CODES), code)
            continue

        retries = 0
        fetched = 0
        while retries < 3:
            try:
                fetched = fetch_stock(bs_code, code, start, args.end, conn)
                break
            except Exception as e:
                retries += 1
                logger.warning("[%d/%d] %s 重试%d: %s", i + 1, len(STOCK_CODES), code, retries, str(e)[:60])
                time.sleep(2)

        if retries >= 3:
            skip_list.append(code)
            logger.error("[%d/%d] %s 跳过（3次失败）", i + 1, len(STOCK_CODES), code)
            continue

        total_rows += fetched

        if (i + 1) % 100 == 0:
            import shutil
            free_gb = shutil.disk_usage("D:\\").free / (1024**3)
            logger.info("进度: %d/%d, 累计%.1f万行, 磁盘余%.0fGB", i + 1, len(STOCK_CODES), total_rows / 10000, free_gb)
            if free_gb < 10:
                logger.error("磁盘空间不足10GB，暂停！")
                break

        time.sleep(0.1)

    bs.logout()

    # 验证
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT ts_code), MIN(trade_date), MAX(trade_date) FROM minute_bars")
    r = cur.fetchone()
    logger.info("验证: %d行, %d只股票, %s ~ %s", r[0], r[1], r[2], r[3])

    if skip_list:
        logger.warning("跳过的股票: %s", skip_list)

    conn.close()
    logger.info("完成! 累计拉取%d行", total_rows)


if __name__ == "__main__":
    main()
