#!/usr/bin/env python3
"""QMT xtdata能力全面测试 v2 — 历史深度/财务/Level2/本地目录。"""
import sys, os, time
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_xt = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"
if _xt.exists() and str(_xt) not in sys.path:
    sys.path.append(str(_xt))

from xtquant import xtdata

TEST_CODE = "000001.SZ"

# ============================================================
# 1. 分钟数据历史深度测试
# ============================================================
print("=" * 70)
print("1. MINUTE DATA HISTORY DEPTH")
print("=" * 70)

for period in ["1m", "5m", "15m", "30m", "60m"]:
    print(f"\n  --- {period} ---")
    for year_month in ["20260301-20260331", "20250301-20250331", "20240301-20240331",
                       "20230301-20230331", "20220301-20220331", "20210301-20210331"]:
        start, end = year_month.split("-")
        try:
            xtdata.download_history_data(TEST_CODE, period, start_time=start, end_time=end)
            df = xtdata.get_market_data_ex([], [TEST_CODE], period=period,
                                           start_time=start, end_time=end)
            n = len(df[TEST_CODE]) if df and TEST_CODE in df else 0
            rng = ""
            if n > 0:
                d = df[TEST_CODE]
                rng = f"  ({d.index[0]}~{d.index[-1]})"
            print(f"    {start[:4]}-{start[4:6]}: {n:>6} rows{rng}")
        except Exception as e:
            print(f"    {start[:4]}-{start[4:6]}: ERROR {str(e)[:80]}")
        time.sleep(0.1)

# ============================================================
# 2. 日线数据验证(对比Tushare)
# ============================================================
print("\n" + "=" * 70)
print("2. DAILY DATA (compare with DB)")
print("=" * 70)
try:
    xtdata.download_history_data(TEST_CODE, "1d", start_time="20260301", end_time="20260331")
    df = xtdata.get_market_data_ex([], [TEST_CODE], period="1d",
                                   start_time="20260301", end_time="20260331")
    if df and TEST_CODE in df:
        d = df[TEST_CODE]
        print(f"  1d rows: {len(d)}")
        print(f"  Columns: {list(d.columns)}")
        if not d.empty:
            print(f"  Last 3 rows:\n{d.tail(3).to_string()}")
except Exception as e:
    print(f"  ERROR: {e}")

# ============================================================
# 3. 财务数据详情
# ============================================================
print("\n" + "=" * 70)
print("3. FINANCIAL DATA")
print("=" * 70)

all_tables = ["Balance", "Income", "CashFlow", "Capital", "PershareIndex",
              "FinancialIndex", "CapitalStructure", "ShareHolder", "ShareHolderNum"]

try:
    print("  Downloading financial data...")
    xtdata.download_financial_data([TEST_CODE], all_tables)
    fin = xtdata.get_financial_data([TEST_CODE], table_list=all_tables)
    for code, tdata in fin.items():
        print(f"\n  {code}:")
        for tname, records in tdata.items():
            if isinstance(records, list):
                if len(records) > 0:
                    fields = list(records[0].keys())
                    print(f"    {tname}: {len(records)} records, {len(fields)} fields")
                    print(f"      Fields: {fields[:20]}")
                    # Show latest record
                    latest = records[-1] if records else {}
                    sample = {k: v for k, v in list(latest.items())[:8]}
                    print(f"      Latest: {sample}")
                else:
                    print(f"    {tname}: 0 records")
            elif isinstance(records, dict):
                print(f"    {tname}: dict with {len(records)} keys")
except Exception as e:
    print(f"  ERROR: {e}")

# ============================================================
# 4. Level2 数据可用性
# ============================================================
print("\n" + "=" * 70)
print("4. LEVEL2 / TICK DATA")
print("=" * 70)
try:
    # Tick data
    xtdata.download_history_data(TEST_CODE, "tick", start_time="20260401", end_time="20260401")
    df_tick = xtdata.get_market_data_ex([], [TEST_CODE], period="tick",
                                        start_time="20260401", end_time="20260401")
    if df_tick and TEST_CODE in df_tick:
        d = df_tick[TEST_CODE]
        print(f"  Tick data: {len(d)} rows")
        print(f"  Columns: {list(d.columns)}")
        if not d.empty:
            print(f"  First 3:\n{d.head(3).to_string()}")
    else:
        print("  Tick data: empty")
except Exception as e:
    print(f"  Tick ERROR: {e}")

# ============================================================
# 5. 板块/行业数据
# ============================================================
print("\n" + "=" * 70)
print("5. SECTOR / INDUSTRY DATA")
print("=" * 70)
try:
    sectors = xtdata.get_sector_list()
    print(f"  Total sectors: {len(sectors)}")
    for s in sectors:
        stocks = xtdata.get_stock_list_in_sector(s)
        print(f"    {s}: {len(stocks)} stocks")
except Exception as e:
    print(f"  ERROR: {e}")

# ============================================================
# 6. Index weight历史
# ============================================================
print("\n" + "=" * 70)
print("6. INDEX WEIGHT")
print("=" * 70)
try:
    import inspect
    sig = inspect.signature(xtdata.get_index_weight)
    print(f"  Signature: {sig}")

    xtdata.download_index_weight()
    for idx in ["000300.SH", "000905.SH", "000016.SH"]:
        w = xtdata.get_index_weight(idx)
        print(f"  {idx}: {len(w)} stocks")
        if w:
            sample = dict(list(w.items())[:3])
            print(f"    Sample: {sample}")
except Exception as e:
    print(f"  ERROR: {e}")

# ============================================================
# 7. 复权因子
# ============================================================
print("\n" + "=" * 70)
print("7. DIVIDEND / ADJUSTMENT FACTORS")
print("=" * 70)
try:
    divid = xtdata.get_divid_factors(TEST_CODE, start_time="20250101", end_time="20260401")
    print(f"  Divid factors: type={type(divid)}")
    if isinstance(divid, dict):
        print(f"  Keys: {list(divid.keys())[:10]}")
        if divid:
            k = list(divid.keys())[0]
            print(f"  Sample [{k}]: {divid[k]}")
    elif hasattr(divid, '__len__'):
        print(f"  Length: {len(divid)}")
except Exception as e:
    print(f"  ERROR: {e}")

# ============================================================
# 8. 本地数据目录
# ============================================================
print("\n" + "=" * 70)
print("8. LOCAL DATA DIRECTORY")
print("=" * 70)
for base in [r"C:\国金QMT实盘", r"C:\国金QMT", r"D:\国金QMT",
             r"C:\MiniQmt", r"D:\MiniQmt", r"C:\国金QMT实盘\userdata_mini"]:
    p = Path(base)
    if p.exists():
        print(f"  FOUND: {p}")
        try:
            for d in sorted(p.iterdir())[:15]:
                if d.is_dir():
                    n_files = sum(1 for _ in d.rglob("*") if _.is_file())
                    size_mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024 / 1024
                    print(f"    {d.name}/: {n_files} files, {size_mb:.0f} MB")
                else:
                    print(f"    {d.name}: {d.stat().st_size / 1024:.0f} KB")
        except PermissionError:
            print("    (permission denied)")
        break
else:
    print("  No QMT directory found in standard paths")

# ============================================================
# 9. Baostock分钟数据测试
# ============================================================
print("\n" + "=" * 70)
print("9. BAOSTOCK MINUTE DATA")
print("=" * 70)
try:
    import baostock as bs
    lg = bs.login()
    print(f"  Login: {lg.error_code} {lg.error_msg}")

    for freq, label in [("5", "5m"), ("15", "15m"), ("30", "30m"), ("60", "60m")]:
        for start, end in [("2026-03-01", "2026-03-31"), ("2021-01-04", "2021-01-31")]:
            rs = bs.query_history_k_data_plus(
                "sz.000001", "date,time,open,high,low,close,volume,amount",
                start_date=start, end_date=end, frequency=freq)
            data = []
            while (rs.error_code == "0") and rs.next():
                data.append(rs.get_row_data())
            yr = start[:4]
            print(f"  {label} {yr}-{start[5:7]}: {len(data)} rows")

    bs.logout()
except ImportError:
    print("  baostock NOT installed")
    print("  Install: pip install baostock")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
