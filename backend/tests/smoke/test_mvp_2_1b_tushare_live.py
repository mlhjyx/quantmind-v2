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
# MVP 2.1c Sub3-prep: +3 字段 (adj_factor + up_limit + down_limit)
required |= {'adj_factor', 'up_limit', 'down_limit'}
missing = required - set(df.columns)
assert not missing, f'missing columns: {missing}'

# Tushare ts_code 应带 SH/SZ/BJ 后缀
assert all(df['ts_code'].str.contains(r'\\.(SH|SZ|BJ)$')), \\
    f'ts_code 格式异常: {df["ts_code"].iloc[0]}'

# MVP 2.1c Sub3-prep: 真 Tushare adj_factor / stk_limit 非空比例验证
# adj_factor fallback 1.0 保证 100% 非 NaN
adj_nan_ratio = df['adj_factor'].isna().sum() / len(df)
assert adj_nan_ratio == 0.0, f'adj_factor NaN={adj_nan_ratio:.2%}, expected 0 (fallback 1.0 保证)'
# up_limit / down_limit: 真生产数据 ST/新股/停牌偶缺, 允许 <10%
up_nan_ratio = df['up_limit'].isna().sum() / len(df)
dn_nan_ratio = df['down_limit'].isna().sum() / len(df)
assert up_nan_ratio < 0.10, f'up_limit NaN={up_nan_ratio:.2%} 超 10%, 异常'
assert dn_nan_ratio < 0.10, f'down_limit NaN={dn_nan_ratio:.2%} 超 10%, 异常'

# Validate
result = src.validate(df, KLINES_DAILY_DATA_CONTRACT)
assert result.passed, f'validate failed: {result.issues}'

print(
    f'OK tushare live: {len(df)} rows, '
    f'unique_codes={df["ts_code"].nunique()}, '
    f'unique_dates={df["trade_date"].nunique()}, '
    f'adj_factor_median={df["adj_factor"].median():.3f}, '
    f'up_limit_coverage={(1-up_nan_ratio):.2%}, '
    f'down_limit_coverage={(1-dn_nan_ratio):.2%}'
)
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
