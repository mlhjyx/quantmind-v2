"""MVP 2.1b Sub-commit 1 — BaostockDataSource 生产入口真启动 smoke (铁律 10b).

subprocess + 真 Baostock 网络 + 查 1 支股最近 15 天 5min bars.
断言: 返 DataFrame 含核心列, validate.passed=True.

无网络 / Baostock 不可达时 pytest.skip (CI 环境兜底).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SMOKE_CODE = """
import socket
try:
    socket.create_connection(('www.baostock.com', 443), timeout=5).close()
except Exception as e:
    print('SKIP: baostock network unreachable:', e)
    import sys
    sys.exit(2)

from datetime import date, timedelta
from backend.qm_platform.data.sources.baostock_source import (
    BaostockDataSource,
    MINUTE_BARS_DATA_CONTRACT,
)

src = BaostockDataSource(codes=['600519'])
# 回溯 15 天, 避开周末 + 假期空窗
since = date.today() - timedelta(days=15)
df = src.fetch(MINUTE_BARS_DATA_CONTRACT, since=since)

# 近 15 天至少应有 1 个交易日数据
assert not df.empty, f'Baostock 返回空, 期望 >=1 行 (since={since})'

required = {'code', 'trade_date', 'trade_time', 'open', 'high', 'low', 'close', 'volume'}
missing = required - set(df.columns)
assert not missing, f'missing columns: {missing}'

# code 格式验证 — 应带后缀
assert all(df['code'].str.endswith(('.SH', '.SZ', '.BJ'))), \\
    f'code 列后缀异常, 首行: {df["code"].iloc[0]}'

# validate 再跑一次 (fetch 已跑, 但显式再 assert 保留验证链路)
result = src.validate(df, MINUTE_BARS_DATA_CONTRACT)
assert result.passed, f'validate failed: {result.issues}'

print(f'OK baostock live: {len(df)} rows, codes={df["code"].unique().tolist()}')
"""


@pytest.mark.smoke
def test_baostock_live_one_stock_fetch() -> None:
    """Live Baostock fetch 贵州茅台 5min bars, validate PASS."""
    result = subprocess.run(
        [sys.executable, "-c", _SMOKE_CODE],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,  # Baostock 网络查询较慢
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 2:
        pytest.skip(f"Baostock unreachable (CI/无网环境): {result.stdout.strip()}")
    if result.returncode != 0:
        pytest.fail(
            f"Baostock live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK baostock live" in result.stdout, result.stdout
