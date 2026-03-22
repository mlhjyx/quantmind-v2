#!/usr/bin/env python3
"""拉取申万一级行业指数日线 → index_daily表。

CLAUDE.md原则1: 不靠猜测做技术判断——经验证，Tushare的index_daily不支持.SI后缀的
申万指数，需用sw_daily接口。

关键规则:
  1. 使用Tushare sw_daily接口（不是index_daily）
  2. sw_daily返回字段: ts_code, trade_date, name, open, low, high, close,
     change, pct_change, vol, amount, pe, pb, float_mv, total_mv
  3. vol=手, amount=千元（从sw_daily返回值量级推断，需验证）
  4. 按指数代码逐个拉取
  5. 限速: 200次/分钟 → sleep 0.35s
  6. 写入index_daily表，与沪深300/中证500等共用

申万一级行业指数（31个，SW2021标准）:
  从 index_classify(level='L1', src='SW2021') 获取

用法:
    python scripts/pull_sw_index.py                    # 全量拉取
    python scripts/pull_sw_index.py --start 20250101   # 指定起始
    python scripts/pull_sw_index.py --verify           # 仅验证
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd
import psycopg2
import psycopg2.extras
import tushare as ts
from app.config import settings
from app.services.price_utils import _get_sync_conn

pro = ts.pro_api(settings.TUSHARE_TOKEN)

# 申万一级行业指数代码（SW2021标准，31个行业）
# 来源: pro.index_classify(level='L1', src='SW2021')
SW_INDEX_CODES = [
    "801010.SI",  # 农林牧渔
    "801030.SI",  # 基础化工
    "801040.SI",  # 钢铁
    "801050.SI",  # 有色金属
    "801080.SI",  # 电子
    "801110.SI",  # 家用电器
    "801120.SI",  # 食品饮料
    "801130.SI",  # 纺织服饰
    "801140.SI",  # 轻工制造
    "801150.SI",  # 医药生物
    "801160.SI",  # 公用事业
    "801170.SI",  # 交通运输
    "801180.SI",  # 房地产
    "801200.SI",  # 商贸零售
    "801210.SI",  # 社会服务
    "801230.SI",  # 综合
    "801710.SI",  # 建筑材料
    "801720.SI",  # 建筑装饰
    "801730.SI",  # 电力设备
    "801740.SI",  # 国防军工
    "801750.SI",  # 计算机
    "801760.SI",  # 传媒
    "801770.SI",  # 通信
    "801780.SI",  # 银行
    "801790.SI",  # 非银金融
    "801880.SI",  # 汽车
    "801890.SI",  # 机械设备
    "801950.SI",  # 煤炭
    "801960.SI",  # 石油石化
    "801970.SI",  # 环保
    "801980.SI",  # 美容护理
]

DEFAULT_START = "20200101"
DEFAULT_END = "20260319"


def fetch_sw_daily(ts_code: str, start_date: str, end_date: str, retry: int = 3) -> pd.DataFrame:
    """用sw_daily接口拉取单个申万指数的日线数据。

    Args:
        ts_code: 指数代码如 '801010.SI'
        start_date: YYYYMMDD
        end_date: YYYYMMDD
        retry: 重试次数

    Returns:
        DataFrame
    """
    for attempt in range(retry):
        try:
            df = pro.sw_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            err_msg = str(e)
            if "每分钟" in err_msg or "频次" in err_msg or "too many" in err_msg.lower():
                print(f"  [限频] 等待60s...")
                time.sleep(60)
            elif "权限" in err_msg:
                raise
            else:
                wait = 5 * (attempt + 1)
                print(f"  [重试 {attempt+1}/{retry}] {e}, 等待{wait}s")
                time.sleep(wait)
    print(f"  [失败] {ts_code} 经过{retry}次重试仍失败，跳过")
    return pd.DataFrame()


def upsert_index_daily(conn: psycopg2.extensions.connection, df: pd.DataFrame) -> int:
    """将申万指数日线数据upsert入index_daily表。

    sw_daily字段映射:
      ts_code → index_code
      close/open/high/low → 直接映射
      pct_change → pct_change
      vol → volume (手)
      amount → amount (千元，待验证)

    注意: sw_daily没有pre_close字段，需从change反推。

    Args:
        conn: 数据库连接
        df: sw_daily返回的DataFrame

    Returns:
        写入行数
    """
    if df.empty:
        return 0

    df = df.copy()

    # 字段映射
    df.rename(columns={
        "ts_code": "index_code",
        "vol": "volume",
    }, inplace=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    # sw_daily没有pre_close，用close - change反推
    if "change" in df.columns and "close" in df.columns:
        df["pre_close"] = df["close"] - df["change"]
    else:
        df["pre_close"] = None

    # NaN → None
    for c in ["open", "high", "low", "close", "pre_close", "pct_change", "volume", "amount"]:
        if c in df.columns:
            df[c] = df[c].where(df[c].notna(), None)

    insert_sql = """
    INSERT INTO index_daily (
        index_code, trade_date, open, high, low, close,
        pre_close, pct_change, volume, amount
    ) VALUES (
        %(index_code)s, %(trade_date)s, %(open)s, %(high)s, %(low)s, %(close)s,
        %(pre_close)s, %(pct_change)s, %(volume)s, %(amount)s
    )
    ON CONFLICT (index_code, trade_date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        pre_close = EXCLUDED.pre_close,
        pct_change = EXCLUDED.pct_change,
        volume = EXCLUDED.volume,
        amount = EXCLUDED.amount;
    """

    db_cols = ["index_code", "trade_date", "open", "high", "low", "close",
               "pre_close", "pct_change", "volume", "amount"]

    records = df[db_cols].to_dict("records")
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, insert_sql, records, page_size=1000)
    conn.commit()
    return len(records)


def add_column_comments(conn: psycopg2.extensions.connection) -> None:
    """为index_daily表添加单位注释。"""
    comments = {
        "open": "开盘点位",
        "high": "最高点位",
        "low": "最低点位",
        "close": "收盘点位",
        "pre_close": "昨收点位",
        "pct_change": "涨跌幅（%）",
        "volume": "成交量（手）",
        "amount": "成交额（千元）",
    }
    with conn.cursor() as cur:
        for col, comment in comments.items():
            cur.execute(f"COMMENT ON COLUMN index_daily.{col} IS %s;", (comment,))
    conn.commit()
    print("[注释] index_daily列注释已更新（单位：手/千元）")


def verify(conn: psycopg2.extensions.connection) -> None:
    """验证申万行业指数数据。"""
    with conn.cursor() as cur:
        print(f"\n=== index_daily 申万行业指数验证 ===")

        # 总览
        cur.execute("""
            SELECT index_code, COUNT(*), MIN(trade_date), MAX(trade_date)
            FROM index_daily
            WHERE index_code LIKE '8%'
            GROUP BY index_code
            ORDER BY index_code;
        """)
        rows = cur.fetchall()
        if not rows:
            print("无申万行业指数数据。")
            return

        print(f"共 {len(rows)} 个申万指数:")
        for r in rows:
            print(f"  {r[0]}: {r[1]:,} 条, {r[2]} ~ {r[3]}")

        # 抽样: 食品饮料
        cur.execute("""
            SELECT trade_date, close, pct_change, volume, amount
            FROM index_daily
            WHERE index_code = '801120.SI'
            ORDER BY trade_date DESC LIMIT 3;
        """)
        sample = cur.fetchall()
        if sample:
            print(f"\n食品饮料(801120.SI)最近数据抽样:")
            for r in sample:
                print(f"  {r[0]}: close={r[1]}, pct_chg={r[2]}%, vol={r[3]}, amount={r[4]}")

        # 全部指数数据总量
        cur.execute("SELECT COUNT(*) FROM index_daily;")
        total = cur.fetchone()[0]
        print(f"\nindex_daily总行数: {total:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取申万一级行业指数日线")
    parser.add_argument("--start", type=str, default=DEFAULT_START, help="起始日期YYYYMMDD")
    parser.add_argument("--end", type=str, default=DEFAULT_END, help="结束日期YYYYMMDD")
    parser.add_argument("--verify", action="store_true", help="仅验证")
    args = parser.parse_args()

    conn = _get_sync_conn()

    if args.verify:
        verify(conn)
        conn.close()
        return

    # 添加列注释
    add_column_comments(conn)

    start_date = args.start
    end_date = args.end

    print(f"[开始] 拉取申万一级行业指数 {start_date} ~ {end_date}")
    print(f"[指数] 共 {len(SW_INDEX_CODES)} 个指数代码")
    print(f"[API] 使用sw_daily接口（非index_daily）")

    total_rows = 0
    success_count = 0
    failed_codes = []

    for i, code in enumerate(SW_INDEX_CODES):
        t0 = time.time()

        # 断点续传：检查DB中该指数已有数据的最新日期
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(trade_date) FROM index_daily WHERE index_code = %s;",
                (code,)
            )
            row = cur.fetchone()
            actual_start = start_date
            if row and row[0]:
                next_day = row[0] + timedelta(days=1)
                actual_start = next_day.strftime("%Y%m%d")
                if actual_start > end_date:
                    print(f"  [{i+1}/{len(SW_INDEX_CODES)}] {code} -- 已是最新，跳过")
                    continue

        df = fetch_sw_daily(code, actual_start, end_date)
        if df.empty:
            print(f"  [{i+1}/{len(SW_INDEX_CODES)}] {code} -- 无数据")
            failed_codes.append(code)
            time.sleep(0.35)
            continue

        rows = upsert_index_daily(conn, df)
        elapsed = time.time() - t0
        total_rows += rows
        success_count += 1
        print(f"  [{i+1}/{len(SW_INDEX_CODES)}] {code} -- {rows:,} 行 ({elapsed:.1f}s)")

        # 限速
        sleep_time = max(0.35 - elapsed, 0)
        if sleep_time > 0:
            time.sleep(sleep_time)

    print(f"\n[完成] {success_count}/{len(SW_INDEX_CODES)} 个指数成功, 共写入 {total_rows:,} 行")
    if failed_codes:
        print(f"[警告] 无数据的指数代码: {failed_codes}")

    verify(conn)
    conn.close()


if __name__ == "__main__":
    main()
