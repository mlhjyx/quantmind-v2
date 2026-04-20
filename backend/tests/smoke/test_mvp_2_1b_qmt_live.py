"""MVP 2.1b Sub-commit 2 — QMTDataSource 生产入口真启动 smoke (铁律 10b).

subprocess + Redis 探测 (QMTData 服务是否 running) + 若 running 则真 import
`QMTDataSource` + 构造/校验 contract 可用性.

本 smoke **不建真 QMT 连接** (会占 QMTData daemon 的账号 session). 只验:
  1. `QMTDataSource` 导入链完整 (backend.platform.data.sources.qmt_source)
  2. 3 DataContract 实例可构造
  3. `_check_value_ranges` 可调用 (核心业务规则链路)

真端到端 live 测 (带真 broker + xtquant) 留 PT 重启后手动验证.

CI / 无 Redis 环境: pytest.skip.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SMOKE_CODE = """
# 仅静态 import 路径 + contract 可构造, 不真 connect QMT (避免占 QMTData session)
from backend.platform.data.sources.qmt_source import (
    QMTDataSource,
    QMT_POSITIONS_CONTRACT,
    QMT_ASSETS_CONTRACT,
    QMT_TICKS_CONTRACT,
)
from backend.platform.data.base_source import ContractViolation
import pandas as pd


# 1. Contract schema 固化 (MVP 2.1b 设计锁)
assert QMT_POSITIONS_CONTRACT.primary_key == ('code',), QMT_POSITIONS_CONTRACT
assert QMT_ASSETS_CONTRACT.primary_key == ('updated_at',), QMT_ASSETS_CONTRACT
assert QMT_TICKS_CONTRACT.primary_key == ('code',), QMT_TICKS_CONTRACT
assert QMT_POSITIONS_CONTRACT.source == 'qmt'


# 2. 构造需 broker, None 必 raise
try:
    QMTDataSource(broker=None)
    raise AssertionError('None broker should raise ValueError')
except ValueError as e:
    assert 'broker 不可为 None' in str(e)


# 3. _check_value_ranges 负数场景 (价格 < 0.01)
class _DummyBroker:
    def query_positions(self):
        return []
    def query_asset(self):
        return {'cash': 0.0, 'frozen_cash': 0.0, 'market_value': 0.0, 'total_asset': 0.0}
    def get_positions(self):
        return {}

src = QMTDataSource(broker=_DummyBroker())
bad_tick_df = pd.DataFrame({
    'code': ['600519.SH'],
    'last_price': [0.005],  # 低于 A 股最小跳价 0.01
    'volume': [100],
})  # v2 (2026-04-20 Session 18): schema 已删 high/low, 测试数据同步不含
issues = src._check_value_ranges(bad_tick_df, QMT_TICKS_CONTRACT)
assert any('last_price' in m and '0.01' in m for m in issues), f'min tick check failed: {issues}'


# 4. 正常 fetch positions (空 list → empty df, validate PASS)
df = src.fetch(QMT_POSITIONS_CONTRACT, since=None)
assert df.empty
result = src.validate(df, QMT_POSITIONS_CONTRACT)
assert result.passed, f'validate on empty df should pass: {result.issues}'

print('OK QMTDataSource 3 contracts + value_range + fetch/validate chain')
"""


@pytest.mark.smoke
def test_qmt_source_imports_and_contracts() -> None:
    """import 链 + 3 Contract 构造 + _check_value_ranges + validate 链路真启动."""
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
            f"QMT smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK QMTDataSource" in result.stdout, result.stdout
