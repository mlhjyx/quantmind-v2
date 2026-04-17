"""分钟数据拉取 — Baostock 5 分钟 K 线 → minute_bars 表。

Step 6-B 重构 (2026-04-09): 从 scripts/archive/ 取出, 改造为经 DataPipeline 入库。

变化:
- 直接 INSERT → DataPipeline.ingest() (铁律 17)
- ts_code 列名 → code (DB 已 RENAME COLUMN)
- 存储格式: 带后缀的 Tushare 风格 "600519.SH" / "000001.SZ"
- Baostock API code ("sh.600519") → DB code ("600519.SH") 由 _to_db_code() 转换

用法:
    python scripts/fetch_minute_bars.py
    python scripts/fetch_minute_bars.py --start 2024-01-01
    python scripts/fetch_minute_bars.py --shard 0 --total-shards 4  # 分片并行
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

import baostock as bs
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.data_fetcher.contracts import MINUTE_BARS
from app.data_fetcher.data_loader import get_sync_conn
from app.data_fetcher.pipeline import DataPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

INSERT_BATCH_ROWS = 2000  # 每累积 2000 行调一次 DataPipeline.ingest()


def load_stock_codes() -> list[str]:
    """加载股票列表: 全量 A 股 (无后缀的原始 6 位编码)。"""
    all_file = Path(__file__).resolve().parent.parent / "models" / "all_astock_codes.txt"
    if all_file.exists():
        codes = {c.strip() for c in all_file.read_text().splitlines() if c.strip()}
        return sorted(codes)

    csi_file = Path(__file__).resolve().parent.parent / "models" / "csi500_codes.txt"
    if csi_file.exists():
        return sorted(
            c.strip() for c in csi_file.read_text().splitlines() if c.strip()
        )

    raise FileNotFoundError(
        "缺少 models/all_astock_codes.txt 或 csi500_codes.txt — 请先拉取股票列表"
    )


def _to_bs_code(code6: str) -> str:
    """6 位编码 → Baostock code ("sh.600519" 或 "sz.000001")。"""
    if code6.startswith(("6", "9")):
        return f"sh.{code6}"
    return f"sz.{code6}"


def _to_db_code(code6: str) -> str:
    """6 位编码 → DB code (带后缀, "600519.SH")。

    规则与 Step 1 保持一致:
    - 6/9 开头 → .SH
    - 0/3 开头 → .SZ
    - 4/8 开头 → .BJ (当前 minute_bars 无 BJ, 兼容未来)
    """
    if code6.startswith(("6", "9")):
        return f"{code6}.SH"
    if code6.startswith(("4", "8")):
        return f"{code6}.BJ"
    return f"{code6}.SZ"


def get_latest_date(conn, db_code: str) -> str | None:
    """该股票 minute_bars 最新日期 (断点续传)。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT MAX(trade_date) FROM minute_bars WHERE code = %s", (db_code,)
    )
    r = cur.fetchone()
    if r and r[0]:
        return r[0].strftime("%Y-%m-%d")
    return None


def _query_baostock(bs_code: str, start: str, end: str) -> list[dict]:
    """拉取 Baostock 5 分钟 K 线, 返回 list[dict] 待组装 DataFrame。"""
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,time,open,high,low,close,volume,amount",
        start_date=start,
        end_date=end,
        frequency="5",
        adjustflag="3",  # 不复权
    )
    if rs.error_code != "0":
        logger.warning("%s 查询失败: %s %s", bs_code, rs.error_code, rs.error_msg)
        return []

    rows: list[dict] = []
    while rs.error_code == "0" and rs.next():
        data = rs.get_row_data()
        if len(data) < 8 or not data[0]:
            continue
        trade_date_str = data[0]  # "YYYY-MM-DD"
        trade_time_str = data[1]  # "YYYYMMDDHHMMSSmmm"
        try:
            trade_time = datetime.strptime(trade_time_str[:14], "%Y%m%d%H%M%S")
        except (ValueError, IndexError):
            continue
        rows.append(
            {
                "trade_date": trade_date_str,
                "trade_time": trade_time,
                "open": float(data[2]) if data[2] else None,
                "high": float(data[3]) if data[3] else None,
                "low": float(data[4]) if data[4] else None,
                "close": float(data[5]) if data[5] else None,
                "volume": int(data[6]) if data[6] else 0,
                "amount": float(data[7]) if data[7] else 0.0,
            }
        )
    return rows


def _ingest_rows(pipeline: DataPipeline, rows: list[dict], db_code: str) -> int:
    """拼 DataFrame 后调 DataPipeline.ingest()。返回入库行数。"""
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    df["code"] = db_code
    df["adjustflag"] = "3"
    result = pipeline.ingest(df, MINUTE_BARS)
    if result.rejected_rows > 0:
        logger.warning(
            "%s 拒绝 %d 行: %s",
            db_code,
            result.rejected_rows,
            result.reject_reasons,
        )
    return result.upserted_rows


def fetch_stock(
    pipeline: DataPipeline, code6: str, start: str, end: str
) -> int:
    """拉取单只股票并入库, 返回入库行数。"""
    bs_code = _to_bs_code(code6)
    db_code = _to_db_code(code6)

    rows = _query_baostock(bs_code, start, end)
    if not rows:
        return 0

    # 分批入库 (降低单次 Ingest 的内存压力)
    upserted = 0
    buf: list[dict] = []
    for r in rows:
        buf.append(r)
        if len(buf) >= INSERT_BATCH_ROWS:
            upserted += _ingest_rows(pipeline, buf, db_code)
            buf = []
    if buf:
        upserted += _ingest_rows(pipeline, buf, db_code)
    return upserted


def main():
    parser = argparse.ArgumentParser(description="Baostock 分钟数据拉取")
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default=date.today().strftime("%Y-%m-%d"))
    parser.add_argument("--shard", type=int, default=0, help="分片编号 (0-based)")
    parser.add_argument("--total-shards", type=int, default=1, help="总分片数")
    args = parser.parse_args()

    lg = bs.login()
    if lg.error_code != "0":
        logger.error("Baostock 登录失败: %s", lg.error_msg)
        sys.exit(1)

    conn = get_sync_conn()
    pipeline = DataPipeline(conn=conn)

    all_codes = load_stock_codes()
    if args.total_shards > 1:
        stock_codes = [
            c for i, c in enumerate(all_codes) if i % args.total_shards == args.shard
        ]
        logger.info(
            "分片 %d/%d: %d 只 (总 %d 只)",
            args.shard,
            args.total_shards,
            len(stock_codes),
            len(all_codes),
        )
    else:
        stock_codes = all_codes
        logger.info("全量 A 股: %d 只", len(stock_codes))

    total_rows = 0
    skip_list: list[str] = []

    for i, code6 in enumerate(stock_codes):
        db_code = _to_db_code(code6)

        # 断点续传
        latest = get_latest_date(conn, db_code)
        start = latest if latest and latest > args.start else args.start
        if latest and latest >= args.end:
            logger.info("[%d/%d] %s 已完成", i + 1, len(stock_codes), db_code)
            continue

        retries = 0
        fetched = 0
        while retries < 3:
            try:
                fetched = fetch_stock(pipeline, code6, start, args.end)
                break
            except Exception as e:
                retries += 1
                logger.warning(
                    "[%d/%d] %s 重试 %d: %s",
                    i + 1,
                    len(stock_codes),
                    db_code,
                    retries,
                    str(e)[:80],
                )
                time.sleep(2)

        if retries >= 3:
            skip_list.append(code6)
            logger.error("[%d/%d] %s 跳过 (3 次失败)", i + 1, len(stock_codes), db_code)
            continue

        total_rows += fetched

        if (i + 1) % 100 == 0:
            import shutil
            free_gb = shutil.disk_usage("D:\\").free / (1024**3)
            logger.info(
                "进度: %d/%d, 累计 %.1f 万行, 磁盘余 %.0f GB",
                i + 1,
                len(stock_codes),
                total_rows / 10000,
                free_gb,
            )
            if free_gb < 10:
                logger.error("磁盘空间不足 10 GB, 暂停")
                break
        time.sleep(0.1)

    bs.logout()

    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT code), MIN(trade_date), MAX(trade_date) FROM minute_bars"
    )
    r = cur.fetchone()
    logger.info("验证: %d 行, %d 只股票, %s ~ %s", r[0], r[1], r[2], r[3])

    if skip_list:
        logger.warning("跳过的股票: %s", skip_list)

    pipeline.close()
    logger.info("完成! 本次累计拉取 %d 行", total_rows)


if __name__ == "__main__":
    main()
