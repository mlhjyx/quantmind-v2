"""MVP 3.2 Strategy Framework 批 1 — 铁律 10b subprocess smoke test.

subprocess 从生产启动路径真启动, 验证:
- `from backend.qm_platform.strategy import DBStrategyRegistry, EqualWeightAllocator` 不炸
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
        "from backend.qm_platform.strategy import ("
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
    """DDL migration 幂等重跑不报错 (CREATE TABLE IF NOT EXISTS + trigger REPLACE).

    使用 in-process psycopg2 直连, 避免 Windows subprocess pipe deadlock.
    原 subprocess.run(capture_output=True) 在 Windows 上当子进程崩溃时
    pipe reader thread hang 满 timeout=30s — pre-push hook 误报 smoke FAIL.
    """
    import psycopg2  # noqa: PLC0415

    migration_sql = (_REPO / "backend" / "migrations" / "strategy_registry.sql").read_text(
        encoding="utf-8"
    )
    try:
        conn = psycopg2.connect(
            dbname="quantmind_v2",
            user="xin",
            host="127.0.0.1",
            password=os.environ.get("QM_DB_PASSWORD", "quantmind"),
            connect_timeout=5,
        )
    except psycopg2.OperationalError as exc:
        pytest.skip(f"DB unavailable: {exc}")
        return

    try:
        cur = conn.cursor()
        cur.execute(migration_sql)
        conn.commit()  # 1st run (or no-op if already applied)
        cur.execute(migration_sql)
        conn.commit()  # 2nd run — IF NOT EXISTS / CREATE OR REPLACE 必不报错
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables"
            " WHERE table_name = 'strategy_registry'"
        )
        assert cur.fetchone()[0] == 1, "strategy_registry table not found after migration"
    finally:
        conn.close()
