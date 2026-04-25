"""Smoke test — MVP 2.1c Sub1 DAL 7 新方法 live PG 端到端 (铁律 10b).

subprocess 启动 + live PG + 真查 klines_daily / symbols / factor_values / stock_status_daily,
验证:
  1. PlatformDataAccessLayer(conn_factory=get_sync_conn) 可构造
  2. read_calendar(start, end) 返 list[date] 非空 (近 30 天)
  3. read_universe(today) 返 list[str] 非空 (生产 A 股 ≥ 1000)
  4. read_freshness(['klines_daily','factor_values']) 两表 MAX(trade_date) 非 None
  5. read_factor_names() 返 list[str] 非空 (生产 ≥ 10 因子)
  6. read_pead_announcements(today, 365) 可调 (返 DF schema 对齐, 行数任意)
  7. UnsupportedTable 对非白名单表正确 raise

失败意味: DAL 扩 7 方法签名/SQL 破坏, 或生产数据空.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SMOKE_CODE = """
from datetime import date, timedelta

from app.services.db import get_sync_conn
from backend.qm_platform.data.access_layer import (
    PlatformDataAccessLayer, UnsupportedTable,
)

dal = PlatformDataAccessLayer(conn_factory=get_sync_conn, paramstyle='%s')

today = date.today()
since = today - timedelta(days=30)

# 1. read_calendar
cal = dal.read_calendar(start=since, end=today)
assert isinstance(cal, list), f'calendar type: {type(cal)}'
assert len(cal) > 0, 'calendar empty in last 30 days'
assert all(isinstance(d, date) for d in cal), 'non-date items in calendar'

# 2. read_universe
uni = dal.read_universe(as_of=today)
assert isinstance(uni, list), f'universe type: {type(uni)}'
assert len(uni) > 1000, f'universe suspiciously small: {len(uni)} < 1000'
assert all(isinstance(c, str) for c in uni), 'non-str in universe'

# 3. read_freshness
fresh = dal.read_freshness(tables=['klines_daily', 'factor_values'])
assert fresh['klines_daily'] is not None, 'klines_daily fresh is None'
assert fresh['factor_values'] is not None, 'factor_values fresh is None'
assert isinstance(fresh['klines_daily'], date), f'klines_daily type: {type(fresh["klines_daily"])}'

# 4. read_factor_names
fnames = dal.read_factor_names()
assert isinstance(fnames, list), f'factor_names type: {type(fnames)}'
assert len(fnames) > 10, f'factor_names suspiciously small: {len(fnames)}'
assert all(isinstance(n, str) for n in fnames), 'non-str factor_name'

# 5. read_pead_announcements (schema sanity, 行数任意)
ann = dal.read_pead_announcements(trade_date=today, lookback_days=365)
assert set(ann.columns) == {'ts_code', 'eps_surprise_pct', 'ann_td'}, \\
    f'pead columns: {list(ann.columns)}'

# 6. read_reconcile_counts (用最新日期避免 0-count)
as_of = fresh['klines_daily']
recon = dal.read_reconcile_counts(
    tables=['klines_daily', 'factor_values'], as_of=as_of,
)
assert recon['klines_daily'] > 0, f'klines_daily count 0 at {as_of}'
assert isinstance(recon['factor_values'], int), 'count not int'

# 7. UnsupportedTable guard
try:
    dal.read_freshness(tables=['user_accounts'])
    raise AssertionError('UnsupportedTable should have raised')
except UnsupportedTable:
    pass

# 8. read_stock_status (empty codes fallback)
empty_status = dal.read_stock_status(codes=[], as_of=today)
assert empty_status.empty, 'empty codes should return empty DF'
assert list(empty_status.columns) == [
    'code', 'is_st', 'is_suspended', 'is_new_stock',
    'board', 'list_date', 'delist_date',
], f'empty df columns: {list(empty_status.columns)}'

print(
    f'OK 2.1c dal live: calendar={len(cal)}, universe={len(uni)}, '
    f'fresh={fresh}, factor_names={len(fnames)}, pead_rows={len(ann)}'
)
"""


@pytest.mark.smoke
def test_dal_extended_live_all_new_methods() -> None:
    """DAL 7 新方法 live PG 端到端 (铁律 10b)."""
    result = subprocess.run(
        [sys.executable, "-c", _SMOKE_CODE],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"MVP 2.1c DAL live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK 2.1c dal live" in result.stdout, result.stdout
