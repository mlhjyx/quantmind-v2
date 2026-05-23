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
        timeout=60,  # Plan v8 fix (5-20): bump from 30s — DB lock contention during Phase B-1 caused 30s timeout false-fail
        # PYTHONPATH 同时含 repo root (backend namespace pkg) + backend/ (顶层
        # engines/app/qm_platform) — qm_platform import 链两种风格都触发.
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": os.pathsep.join([str(_REPO), str(_REPO / "backend")]),
        },
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
    # F-XS-3 hardening (iter 19, 2026-05-24): fail-fast on lock contention + connect timeout.
    # Root cause (iter 17 smoke gate block): pytest --timeout=60 killing the parent left the
    # subprocess holding strategy_registry table-level locks indefinitely (PG backend stuck on
    # `relation` wait), every subsequent smoke run stacked another zombie waiter, the gate
    # required manual pg_terminate_backend cleanup. lock_timeout='5s' forces PG itself to
    # abort lock-wait fast on contention so the connection closes cleanly when child dies.
    code = (
        "import sys, platform as _stdlib_platform; "
        "_ = _stdlib_platform.python_implementation(); "
        "import psycopg2, os; "
        "conn = psycopg2.connect(dbname='quantmind_v2', user='xin', host='127.0.0.1',"
        " password=os.environ.get('QM_DB_PASSWORD', 'quantmind'), connect_timeout=10); "
        "cur = conn.cursor(); "
        # F-XS-3: session-level lock_timeout — see block comment above test_migration_idempotent_rerun.
        "cur.execute(\"SET lock_timeout = '5s'\"); conn.commit(); "
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
        timeout=60,  # Plan v8 fix (5-20) bump from 30s; F-XS-3 (iter 19) lock_timeout=5s now caps DDL lock-wait so we no longer hit this ceiling on contention.
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    # 若 DB 不可用 / lock 长时被持 → skip (本地 dev 容许; CI 须 DB clean + 0 持锁旧 backend)
    if "could not connect" in result.stderr or "authentication failed" in result.stderr:
        pytest.skip(f"DB unavailable: {result.stderr[:200]}")
    if "lock_timeout" in result.stderr or "canceling statement due to lock timeout" in result.stderr:
        pytest.skip(f"DDL lock held by other connection >5s (likely concurrent dev process): {result.stderr[:200]}")
    assert result.returncode == 0, (
        f"Migration idempotent rerun failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "MIGRATION_IDEMPOTENT_OK" in result.stdout
