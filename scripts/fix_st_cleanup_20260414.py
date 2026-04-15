"""一次性修复脚本: 清理ST股+补建stock_status_daily+重新生成信号。

背景: 2026-04-14 执行买入了688184.SH(ST帕瓦),因stock_status_daily数据缺失
导致ST过滤失效。本脚本在收盘后(17:15 DailySignal之后)运行。

用法:
    python scripts/fix_st_cleanup_20260414.py          # 执行
    python scripts/fix_st_cleanup_20260414.py --dry-run # 只检查不写入

执行后明天09:31 DailyExecute会自动清理ST持仓。
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from app.data_fetcher.tushare_api import TushareAPI
from app.services.db import get_sync_conn


def step1_rebuild_stock_status(conn, trade_date: date, dry_run: bool):
    """补建当日stock_status_daily。"""
    print(f"\n[Step 1] 补建 stock_status_daily for {trade_date}")
    cur = conn.cursor()

    # 检查是否已存在
    cur.execute(
        "SELECT COUNT(*) FROM stock_status_daily WHERE trade_date = %s",
        (trade_date,),
    )
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"  已存在 {existing} 行，跳过")
        return

    # 检查klines是否存在
    cur.execute("SELECT COUNT(*) FROM klines_daily WHERE trade_date = %s", (trade_date,))
    klines_count = cur.fetchone()[0]
    if klines_count == 0:
        print(f"  klines_daily 无 {trade_date} 数据，跳过")
        return

    # Fetch ST periods
    api = TushareAPI()
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
        if len(df) < 10000:
            break

    nc = pd.concat(all_nc).drop_duplicates(
        subset=["ts_code", "name", "start_date", "end_date"]
    )
    st_mask = nc["name"].str.contains("ST", case=False, na=False)
    st_rows = nc[st_mask].copy()
    st_rows["code"] = st_rows["ts_code"]
    st_rows["st_start"] = pd.to_datetime(st_rows["start_date"]).dt.date
    st_rows["st_end"] = st_rows["end_date"].apply(
        lambda x: pd.to_datetime(x).date() if pd.notna(x) else date(2099, 12, 31)
    )

    st_lookup = {}
    for _, row in st_rows.iterrows():
        code = row["code"]
        if code not in st_lookup:
            st_lookup[code] = []
        st_lookup[code].append((row["st_start"], row["st_end"]))

    def is_st(code, td):
        periods = st_lookup.get(code)
        if not periods:
            return False
        return any(s <= td <= e for s, e in periods)

    def infer_board(code):
        if code.startswith("68"):
            return "star"
        if code.startswith("30"):
            return "gem"
        if code.endswith(".BJ") or code.startswith(("8", "4", "92")):
            return "bse"
        return "main"

    # Load symbols
    cur.execute("SELECT code, list_date, delist_date, board FROM symbols")
    symbols = {
        r[0]: {"list_date": r[1], "delist_date": r[2], "board": r[3]}
        for r in cur.fetchall()
    }

    # Process
    cur.execute(
        "SELECT code, volume FROM klines_daily WHERE trade_date = %s", (trade_date,)
    )
    klines = cur.fetchall()

    records = []
    st_count = 0
    for code, volume in klines:
        sym = symbols.get(code, {})
        list_dt = sym.get("list_date")
        delist_dt = sym.get("delist_date")
        board = sym.get("board") or infer_board(code)
        _is_st = is_st(code, trade_date)
        is_suspended = volume is not None and int(volume) == 0
        is_new = list_dt is not None and 0 <= (trade_date - list_dt).days < 60
        records.append(
            (code, trade_date, _is_st, is_suspended, is_new, board, list_dt, delist_dt)
        )
        if _is_st:
            st_count += 1

    if dry_run:
        print(f"  [DRY-RUN] 将插入 {len(records)} 行, {st_count} ST")
        return

    execute_values(
        cur,
        """INSERT INTO stock_status_daily
           (code, trade_date, is_st, is_suspended, is_new_stock, board, list_date, delist_date)
           VALUES %s
           ON CONFLICT (code, trade_date) DO UPDATE SET
             is_st = EXCLUDED.is_st, is_suspended = EXCLUDED.is_suspended,
             is_new_stock = EXCLUDED.is_new_stock, board = EXCLUDED.board""",
        records,
        page_size=5000,
    )
    conn.commit()
    print(f"  插入 {len(records)} 行, {st_count} ST stocks")


def step2_regenerate_signals(trade_date: date, dry_run: bool):
    """重新生成信号(force-rebalance)。"""
    print(f"\n[Step 2] 重新生成信号 --force-rebalance for {trade_date}")

    import subprocess

    cmd = [
        sys.executable,
        "scripts/run_paper_trading.py",
        "signal",
        "--date",
        str(trade_date),
        "--force-rebalance",
        "--skip-fetch",  # 数据已在17:15拉取
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"  CMD: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    print(result.stdout[-500:] if result.stdout else "")
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[-500:]}")
        return False
    return True


def step3_verify(conn, trade_date: date):
    """验证信号中无ST股。"""
    print(f"\n[Step 3] 验证 {trade_date} 信号")
    cur = conn.cursor()

    # 获取最近stock_status日期
    cur.execute(
        "SELECT MAX(trade_date) FROM stock_status_daily WHERE trade_date <= %s",
        (trade_date,),
    )
    status_date = cur.fetchone()[0]

    cur.execute(
        """SELECT s.code, s.action, s.alpha_score, ss.is_st, sym.name
           FROM signals s
           LEFT JOIN stock_status_daily ss ON s.code = ss.code AND ss.trade_date = %s
           LEFT JOIN symbols sym ON s.code = sym.code
           WHERE s.trade_date = %s
           ORDER BY s.alpha_score DESC""",
        (status_date, trade_date),
    )
    rows = cur.fetchall()

    st_in_signal = []
    print(f"  信号日={trade_date}, status_date={status_date}, 目标={len(rows)}只")
    for code, action, score, is_st, name in rows:
        if is_st:
            st_in_signal.append((code, name))
            print(f"  ⚠️  ST股仍在信号中: {code} {name}")

    if not st_in_signal:
        print("  ✅ 无ST股在信号中")
    else:
        print(f"  ❌ {len(st_in_signal)} 只ST股仍在信号中!")

    cur.close()
    return len(st_in_signal) == 0


def main():
    parser = argparse.ArgumentParser(description="ST清理修复脚本")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    trade_date = date(2026, 4, 14)
    print("=" * 60)
    print(f"ST清理修复 — trade_date={trade_date}")
    print(f"模式: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    conn = get_sync_conn()
    t0 = time.time()

    # Step 1: 补建stock_status_daily
    step1_rebuild_stock_status(conn, trade_date, args.dry_run)

    # Step 2: 重新生成信号
    step2_regenerate_signals(trade_date, args.dry_run)

    # Step 3: 验证
    ok = step3_verify(conn, trade_date)

    conn.close()
    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"完成: {elapsed:.0f}s, 状态: {'✅ PASS' if ok else '❌ FAIL'}")
    if ok and not args.dry_run:
        print("明天09:31 DailyExecute 将自动卖出ST帕瓦+买入替补")
    print("=" * 60)


if __name__ == "__main__":
    main()
