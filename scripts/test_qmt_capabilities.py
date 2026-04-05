#!/usr/bin/env python3
"""QMT xtdata能力探索 — 历史深度/分钟数据/因子/指数成分。"""
import sys, os
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_xt = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"
if _xt.exists() and str(_xt) not in sys.path:
    sys.path.append(str(_xt))

from xtquant import xtdata

# 1. History depth test
print("=== HISTORY DEPTH (000001.SZ) ===")
for period, start, end in [
    ("1m",  "20260301", "20260331"),
    ("1m",  "20250301", "20250331"),
    ("1m",  "20240301", "20240331"),
    ("1m",  "20230301", "20230331"),
    ("5m",  "20260301", "20260331"),
    ("5m",  "20250301", "20250331"),
    ("5m",  "20240301", "20240331"),
    ("15m", "20260301", "20260331"),
    ("30m", "20260301", "20260331"),
    ("60m", "20260301", "20260331"),
]:
    try:
        xtdata.download_history_data("000001.SZ", period, start_time=start, end_time=end)
        df = xtdata.get_market_data_ex([], ["000001.SZ"], period=period,
                                       start_time=start, end_time=end)
        n = len(df["000001.SZ"]) if df and "000001.SZ" in df else 0
        print(f"  {period:4s} {start[:4]}-{start[4:6]}: {n:>6} rows")
    except Exception as e:
        print(f"  {period:4s} {start[:4]}-{start[4:6]}: ERROR {e}")

# 2. Index weight - try date parameter
print("\n=== INDEX WEIGHT ===")
try:
    w = xtdata.get_index_weight("000300.SH")
    print(f"  Default (current): {len(w)} stocks")
    # Check if date param works
    import inspect
    sig = inspect.signature(xtdata.get_index_weight)
    print(f"  Signature: {sig}")
except Exception as e:
    print(f"  Error: {e}")

# 3. Financial data detail
print("\n=== FINANCIAL DATA (000001.SZ) ===")
try:
    tables = ["Balance", "Income", "CashFlow", "Capital", "PershareIndex",
              "FinancialIndex", "CapitalStructure", "ShareHolder", "ShareHolderNum"]
    xtdata.download_financial_data(["000001.SZ"], tables)
    fin = xtdata.get_financial_data(["000001.SZ"], table_list=tables)
    for code, tdata in fin.items():
        for tname, records in tdata.items():
            if isinstance(records, list) and len(records) > 0:
                fields = list(records[0].keys())
                print(f"  {tname}: {len(records)} records, {len(fields)} fields")
                print(f"    Fields: {fields[:15]}...")
            elif isinstance(records, dict):
                print(f"  {tname}: dict")
except Exception as e:
    print(f"  Financial error: {e}")

# 4. Local data directory
print("\n=== LOCAL DATA DIRECTORY ===")
for base in ["C:/国金QMT实盘", "C:/国金QMT", "D:/国金QMT", "C:/MiniQmt"]:
    p = Path(base)
    if p.exists():
        print(f"  Found: {p}")
        for d in sorted(p.iterdir())[:10]:
            if d.is_dir():
                try:
                    files = list(d.rglob("*"))
                    size = sum(f.stat().st_size for f in files if f.is_file())
                    print(f"    {d.name}/: {len(files)} files, {size/1024/1024:.0f} MB")
                except:
                    print(f"    {d.name}/: (access error)")
            else:
                print(f"    {d.name}: {d.stat().st_size/1024:.0f} KB")
        break
else:
    # Search for xtdata data path
    print("  Standard paths not found. Checking userdata_mini...")
    for drive in ["C:", "D:"]:
        for pattern in ["*QMT*", "*qmt*", "*MiniQmt*"]:
            for p in Path(drive + "/").glob(pattern):
                print(f"  Found: {p}")

# 5. Baostock test
print("\n=== BAOSTOCK TEST ===")
try:
    import baostock as bs
    lg = bs.login()
    print(f"  Login: {lg.error_code} {lg.error_msg}")
    rs = bs.query_history_k_data_plus(
        "sz.000001", "date,time,open,high,low,close,volume,amount",
        start_date="2026-03-01", end_date="2026-03-31", frequency="5")
    data = []
    while (rs.error_code == "0") and rs.next():
        data.append(rs.get_row_data())
    print(f"  5m data (000001, 2026-03): {len(data)} rows")
    if data:
        print(f"  Sample: {data[0]}")

    # Test 2021 depth
    rs2 = bs.query_history_k_data_plus(
        "sz.000001", "date,time,open,high,low,close,volume",
        start_date="2021-01-04", end_date="2021-01-31", frequency="5")
    data2 = []
    while (rs2.error_code == "0") and rs2.next():
        data2.append(rs2.get_row_data())
    print(f"  5m data (000001, 2021-01): {len(data2)} rows")

    bs.logout()
except ImportError:
    print("  baostock not installed")
except Exception as e:
    print(f"  Baostock error: {e}")

print("\nDone.")
