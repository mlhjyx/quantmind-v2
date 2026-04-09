"""构建stock_status_daily表 — PIT安全的每日股票状态。

数据来源:
- is_st: Tushare namechange API (name含ST的时间段)
- is_suspended: klines_daily WHERE volume=0
- is_new_stock: trade_date在list_date后60自然日内
- board: symbols表或code后缀推断

用法:
    python scripts/build_stock_status.py              # 全量回填
    python scripts/build_stock_status.py --verify     # 只验证不写入
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.data_fetcher.tushare_api import TushareAPI  # noqa: E402


def get_conn():
    from app.data_fetcher.data_loader import get_sync_conn

    return get_sync_conn()


# ── Step 1: Namechange → ST时间段 ────────────────────────


def fetch_st_periods(api: TushareAPI) -> pd.DataFrame:
    """从Tushare namechange批量拉取ST时间段。返回(code, st_start, st_end)。"""
    print("[1/4] Fetching namechange for ST periods...")
    all_nc = []
    for offset in range(0, 200000, 10000):
        df = api.query(
            "namechange",
            fields="ts_code,name,start_date,end_date",
            limit=10000,
            offset=offset,
        )
        if df is None or df.empty:
            break
        all_nc.append(df)
        print(f"  offset={offset}: {len(df)} rows")
        if len(df) < 10000:
            break

    if not all_nc:
        print("  WARNING: no namechange data!")
        return pd.DataFrame(columns=["code", "st_start", "st_end"])

    nc = pd.concat(all_nc).drop_duplicates(subset=["ts_code", "name", "start_date", "end_date"])
    # 找name含ST的记录
    st_mask = nc["name"].str.contains("ST", case=False, na=False)
    st_rows = nc[st_mask].copy()
    st_rows["code"] = st_rows["ts_code"]  # 已是带后缀格式
    st_rows["st_start"] = pd.to_datetime(st_rows["start_date"]).dt.date
    st_rows["st_end"] = st_rows["end_date"].apply(
        lambda x: pd.to_datetime(x).date() if pd.notna(x) else date(2099, 12, 31)
    )
    result = st_rows[["code", "st_start", "st_end"]].reset_index(drop=True)
    print(f"  Found {len(result)} ST periods for {result['code'].nunique()} stocks")
    return result


def build_st_lookup(st_periods: pd.DataFrame) -> dict[str, list[tuple[date, date]]]:
    """构建 {code: [(start, end), ...]} 查找表。"""
    lookup: dict[str, list[tuple[date, date]]] = {}
    for _, row in st_periods.iterrows():
        code = row["code"]
        if code not in lookup:
            lookup[code] = []
        lookup[code].append((row["st_start"], row["st_end"]))
    return lookup


def is_st_on_date(lookup: dict, code: str, td: date) -> bool:
    """PIT安全的ST判断。"""
    periods = lookup.get(code)
    if not periods:
        return False
    return any(start <= td <= end for start, end in periods)


# ── Step 2: 构建并写入 ──────────────────────────────────


def build_and_insert(conn, st_lookup: dict, verify_only: bool = False):
    """分月构建stock_status_daily并写入。"""
    cur = conn.cursor()

    # 获取symbols信息
    print("[2/4] Loading symbols + klines metadata...")
    cur.execute("SELECT code, list_date, delist_date, board FROM symbols")
    symbols = {
        row[0]: {"list_date": row[1], "delist_date": row[2], "board": row[3]}
        for row in cur.fetchall()
    }
    print(f"  {len(symbols)} symbols loaded")

    # 获取所有(code, trade_date)组合 + volume
    cur.execute(
        "SELECT code, trade_date, volume FROM klines_daily ORDER BY trade_date, code"
    )
    rows = cur.fetchall()
    total = len(rows)
    print(f"  {total:,} klines rows to process")

    if verify_only:
        # 只做验证抽样
        _verify_st(st_lookup, rows[:10000])
        return

    # 分批处理(每10万行一批)
    print("[3/4] Building stock_status_daily...")
    batch_size = 100000
    total_inserted = 0

    for i in range(0, total, batch_size):
        batch = rows[i : i + batch_size]
        records = []

        for code, td, volume in batch:
            sym = symbols.get(code, {})
            list_dt = sym.get("list_date")
            delist_dt = sym.get("delist_date")
            board = sym.get("board") or _infer_board(code)

            is_st = is_st_on_date(st_lookup, code, td)
            is_suspended = volume is not None and int(volume) == 0
            is_new = (
                list_dt is not None
                and (td - list_dt).days < 60
                and (td - list_dt).days >= 0
            )

            records.append((code, td, is_st, is_suspended, is_new, board, list_dt, delist_dt))

        execute_values(
            cur,
            """INSERT INTO stock_status_daily
               (code, trade_date, is_st, is_suspended, is_new_stock, board, list_date, delist_date)
               VALUES %s
               ON CONFLICT (code, trade_date) DO UPDATE SET
                 is_st = EXCLUDED.is_st,
                 is_suspended = EXCLUDED.is_suspended,
                 is_new_stock = EXCLUDED.is_new_stock,
                 board = EXCLUDED.board,
                 list_date = EXCLUDED.list_date,
                 delist_date = EXCLUDED.delist_date""",
            records,
            page_size=10000,
        )
        conn.commit()
        total_inserted += len(records)

        if (i // batch_size) % 10 == 0:
            print(f"  {total_inserted:,}/{total:,} rows ({total_inserted / total * 100:.0f}%)")

    print(f"  Total inserted: {total_inserted:,}")


def _infer_board(code: str) -> str:
    """从code推断板块。"""
    if code.startswith("68"):
        return "star"  # 科创板
    if code.startswith("30"):
        return "gem"  # 创业板
    if code.endswith(".BJ") or code.startswith(("8", "4", "92")):
        return "bse"  # 北交所
    return "main"


def _verify_st(st_lookup: dict, sample_rows):
    """抽样验证ST标记。"""
    st_count = sum(1 for code, td, _ in sample_rows if is_st_on_date(st_lookup, code, td))
    print(f"  Verify: {st_count}/{len(sample_rows)} ST in sample")


# ── Step 3: 验证 ────────────────────────────────────────


def verify(conn):
    """验证stock_status_daily数据质量。"""
    cur = conn.cursor()
    print("[4/4] Verification...")

    cur.execute("SELECT COUNT(*) FROM stock_status_daily")
    total = cur.fetchone()[0]
    print(f"  Total rows: {total:,}")

    cur.execute("SELECT COUNT(*) FROM klines_daily")
    klines_total = cur.fetchone()[0]
    print(f"  klines_daily rows: {klines_total:,}")
    print(f"  Coverage: {total / klines_total * 100:.1f}%")

    cur.execute("SELECT COUNT(*) FROM stock_status_daily WHERE is_st = TRUE")
    st_count = cur.fetchone()[0]
    print(f"  is_st=TRUE: {st_count:,} ({st_count / total * 100:.2f}%)")

    cur.execute("SELECT COUNT(*) FROM stock_status_daily WHERE is_suspended = TRUE")
    susp = cur.fetchone()[0]
    print(f"  is_suspended=TRUE: {susp:,} ({susp / total * 100:.2f}%)")

    cur.execute("SELECT COUNT(*) FROM stock_status_daily WHERE is_new_stock = TRUE")
    new_cnt = cur.fetchone()[0]
    print(f"  is_new_stock=TRUE: {new_cnt:,} ({new_cnt / total * 100:.2f}%)")

    # ST抽查: 000511.SZ (*ST烯碳 2016-05-04 ~ 2018-06-04)
    cur.execute(
        """SELECT COUNT(*) FROM stock_status_daily
           WHERE code = '000511.SZ' AND is_st = TRUE
             AND trade_date BETWEEN '2016-05-04' AND '2018-06-04'"""
    )
    st_511 = cur.fetchone()[0]
    print(f"  ST抽查 000511.SZ (2016-05~2018-06): {st_511} days marked ST")

    # BJ股数量
    cur.execute(
        "SELECT COUNT(DISTINCT code) FROM stock_status_daily WHERE board = 'bse'"
    )
    bj_count = cur.fetchone()[0]
    print(f"  BJ(北交所)股: {bj_count} codes")


def main():
    parser = argparse.ArgumentParser(description="构建stock_status_daily表")
    parser.add_argument("--verify", action="store_true", help="只验证不写入")
    args = parser.parse_args()

    api = TushareAPI()
    conn = get_conn()

    t0 = time.time()

    if args.verify:
        verify(conn)
    else:
        st_periods = fetch_st_periods(api)
        st_lookup = build_st_lookup(st_periods)
        build_and_insert(conn, st_lookup)
        verify(conn)

    print(f"\nTotal time: {time.time() - t0:.0f}s")
    conn.close()


if __name__ == "__main__":
    main()
