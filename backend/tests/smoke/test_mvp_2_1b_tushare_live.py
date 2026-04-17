"""MVP 2.1b Sub-commit 3 — TushareDataSource 生产入口真启动 smoke (铁律 10b).

subprocess + 真 TUSHARE_TOKEN (env) + 查 1 个最近交易日 klines_daily.
无 TUSHARE_TOKEN 环境变量 → pytest.skip (CI 常见).

真端到端 dual-write 对比验证 留 MVP 2.1c 前置 (regression max_diff=0 × 3 次 + 数据 diff 100%).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SMOKE_CODE = """
import os
if not os.environ.get('TUSHARE_TOKEN'):
    print('SKIP: TUSHARE_TOKEN not set')
    import sys
    sys.exit(2)

from datetime import date, timedelta
from app.data_fetcher.tushare_api import TushareAPI
from backend.platform.data.sources.tushare_source import (
    TushareDataSource,
    KLINES_DAILY_DATA_CONTRACT,
)

# 回溯 10 天, 跨周末找最近交易日
end = date.today()
since = end - timedelta(days=10)

client = TushareAPI()
src = TushareDataSource(client=client, end=end)
df = src.fetch(KLINES_DAILY_DATA_CONTRACT, since=since)

# 近 10 天至少有 1 个交易日
assert not df.empty, f'Tushare 返回空, 期望 >=1 行 (since={since}, end={end})'

required = {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'vol', 'amount', 'pct_chg'}
missing = required - set(df.columns)
assert not missing, f'missing columns: {missing}'

# Tushare ts_code 应带 SH/SZ/BJ 后缀
assert all(df['ts_code'].str.contains(r'\\.(SH|SZ|BJ)$')), \\
    f'ts_code 格式异常: {df["ts_code"].iloc[0]}'

# Validate
result = src.validate(df, KLINES_DAILY_DATA_CONTRACT)
assert result.passed, f'validate failed: {result.issues}'

print(f'OK tushare live: {len(df)} rows, unique_codes={df["ts_code"].nunique()}, unique_dates={df["trade_date"].nunique()}')
"""


@pytest.mark.smoke
def test_tushare_live_klines_fetch() -> None:
    """Live Tushare klines_daily fetch + validate PASS (需 TUSHARE_TOKEN)."""
    if not os.environ.get("TUSHARE_TOKEN"):
        pytest.skip("TUSHARE_TOKEN 未配置 (CI / 新环境), 跳过")
    result = subprocess.run(
        [sys.executable, "-c", _SMOKE_CODE],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 2:
        pytest.skip(f"TUSHARE_TOKEN 缺失 (subprocess 视角): {result.stdout.strip()}")
    if result.returncode != 0:
        pytest.fail(
            f"Tushare live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK tushare live" in result.stdout, result.stdout
