"""MVP 3.2 Strategy Framework 批 1 — 铁律 10b subprocess smoke test.

subprocess 从生产启动路径真启动, 验证:
- `from platform.strategy import DBStrategyRegistry, EqualWeightAllocator` 不炸
- DDL migration 幂等 (可重跑不报错)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

_REPO = Path(__file__).resolve().parents[3]


def test_platform_strategy_batch_1_imports_clean():
    """subprocess: 从 project root 启 python 验 Platform strategy batch 1 imports OK."""
    code = (
        "import sys, platform as _stdlib_platform; "
        "_ = _stdlib_platform.python_implementation(); "
        "from backend.platform.strategy import ("
        "  DBStrategyRegistry, EqualWeightAllocator, StrategyNotFound,"
        "  StrategyRegistryIntegrityError, RebalanceFreq, StrategyStatus"
        "); "
        "print('IMPORT_OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, (
        f"Platform strategy batch 1 import failed:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "IMPORT_OK" in result.stdout


def test_migration_idempotent_rerun():
    """DDL migration 幂等重跑不报错 (CREATE TABLE IF NOT EXISTS + trigger REPLACE 设计)."""
    migration_sql = (_REPO / "backend" / "migrations" / "strategy_registry.sql").read_text(
        encoding="utf-8"
    )
    # 主动跑 2 次 via in-proc psycopg2, 验证 IF NOT EXISTS / CREATE OR REPLACE 生效
    code = (
        "import sys, platform as _stdlib_platform; "
        "_ = _stdlib_platform.python_implementation(); "
        "import psycopg2, os; "
        "conn = psycopg2.connect(dbname='quantmind_v2', user='xin', host='127.0.0.1',"
        " password=os.environ.get('QM_DB_PASSWORD', 'quantmind')); "
        "cur = conn.cursor(); "
        f"sql = {migration_sql!r}; "
        "cur.execute(sql); conn.commit(); "  # 1st run (or no-op if already applied)
        "cur.execute(sql); conn.commit(); "  # 2nd run — 必须不报错
        "cur.execute(\"SELECT COUNT(*) FROM information_schema.tables WHERE table_name='strategy_registry'\"); "
        "assert cur.fetchone()[0] == 1; "
        "print('MIGRATION_IDEMPOTENT_OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    # 若 DB 不可用跳过 (本地 dev 环境容许; CI 须 DB 在线)
    if "could not connect" in result.stderr or "authentication failed" in result.stderr:
        pytest.skip(f"DB unavailable: {result.stderr[:200]}")
    assert result.returncode == 0, (
        f"Migration idempotent rerun failed:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "MIGRATION_IDEMPOTENT_OK" in result.stdout
