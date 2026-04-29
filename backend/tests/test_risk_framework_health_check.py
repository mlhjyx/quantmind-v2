"""Tests for scripts/risk_framework_health_check.py (Phase 0a, Session 44).

覆盖 _check_task 纯逻辑 (DB 用 mock psycopg2 cursor):
  1. Missing — 窗口 0 runs → P0 finding
  2. Errored — error/retry rows → P1 finding
  3. Stale — last success > max_gap → P1 finding
  4. Under-count — runs < min_per_day → P1 finding
  5. All-green — 期望 row 数 + 全 success + last_success 新鲜 → 0 findings

不测 DingTalk send / argparse / main entrypoint (dry-run 已端到端验证).
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from risk_framework_health_check import (  # noqa: E402
    EXPECTED_SCHEDULE,
    _check_task,
)


def _mk_conn(status_counts: dict, last_success: datetime | None):
    """构造 mock psycopg2 conn: cursor.fetchall 返 status counts, fetchone 返 last_success."""
    conn = MagicMock()
    cur = MagicMock()
    # __enter__/__exit__ for cursor context manager (not used in script — uses conn.cursor())
    conn.cursor.return_value = cur

    # 第一次 fetchall (status counts) + 第二次 fetchone (last_success)
    cur.fetchall.return_value = list(status_counts.items())
    cur.fetchone.return_value = (last_success,)
    cur.execute = MagicMock()
    cur.close = MagicMock()
    return conn


def test_missing_returns_p0_finding():
    """窗口 0 runs → P0 missing finding."""
    conn = _mk_conn({}, last_success=None)
    spec = EXPECTED_SCHEDULE["risk_daily_check"]
    findings = _check_task(
        conn, "risk_daily_check", spec,
        datetime.now(UTC), window_hours=24,
    )
    assert len(findings) == 1
    assert findings[0].severity == "P0"
    assert findings[0].kind == "missing"
    assert findings[0].task_name == "risk_daily_check"


def test_errored_returns_p1_finding():
    """status in (error, retry) → P1 errored finding."""
    last_ok = datetime.now(UTC) - timedelta(minutes=10)
    conn = _mk_conn(
        {"success": 1, "error": 2, "retry": 1},
        last_success=last_ok,
    )
    spec = EXPECTED_SCHEDULE["risk_daily_check"]
    findings = _check_task(
        conn, "risk_daily_check", spec,
        datetime.now(UTC), window_hours=24,
    )
    # missing 不报 (有 4 runs), errored 报 P1
    assert any(f.severity == "P1" and f.kind == "errored" for f in findings)


def test_stale_returns_p1_finding():
    """last success 早于 max_gap → P1 stale finding."""
    spec = EXPECTED_SCHEDULE["intraday_risk_check"]  # max_gap=30min
    very_old = datetime.now(UTC) - timedelta(hours=2)
    conn = _mk_conn(
        {"success": 60},  # min_per_day satisfied
        last_success=very_old,
    )
    findings = _check_task(
        conn, "intraday_risk_check", spec,
        datetime.now(UTC), window_hours=24,
    )
    assert any(f.severity == "P1" and f.kind == "stale" for f in findings)


def test_under_count_returns_p1_finding():
    """intraday runs < min_per_day=60 → P1 under_count."""
    last_ok = datetime.now(UTC) - timedelta(minutes=5)
    conn = _mk_conn(
        {"success": 30},  # 30 < 60
        last_success=last_ok,
    )
    spec = EXPECTED_SCHEDULE["intraday_risk_check"]
    findings = _check_task(
        conn, "intraday_risk_check", spec,
        datetime.now(UTC), window_hours=24,
    )
    assert any(f.severity == "P1" and f.kind == "under_count" for f in findings)


def test_all_green_returns_no_findings():
    """期望 row 数 + 全 success + 新鲜 → 0 findings."""
    last_ok = datetime.now(UTC) - timedelta(minutes=5)  # 新鲜
    conn = _mk_conn(
        {"success": 1},  # daily 期望 1
        last_success=last_ok,
    )
    spec = EXPECTED_SCHEDULE["risk_daily_check"]
    findings = _check_task(
        conn, "risk_daily_check", spec,
        datetime.now(UTC), window_hours=24,
    )
    assert findings == []


def test_intraday_all_green_returns_no_findings():
    """intraday 60+ runs + 全 success + 新鲜 → 0 findings."""
    last_ok = datetime.now(UTC) - timedelta(minutes=5)
    conn = _mk_conn(
        {"success": 70, "skipped": 2},  # 72 ≥ 60 min
        last_success=last_ok,
    )
    spec = EXPECTED_SCHEDULE["intraday_risk_check"]
    findings = _check_task(
        conn, "intraday_risk_check", spec,
        datetime.now(UTC), window_hours=24,
    )
    assert findings == []


def test_naive_last_success_handled():
    """last_success 无 tzinfo 时, 内部应补 UTC 不 raise."""
    naive = datetime.now() - timedelta(minutes=5)  # no tzinfo
    conn = _mk_conn({"success": 1}, last_success=naive)
    spec = EXPECTED_SCHEDULE["risk_daily_check"]
    # 不应 raise (内部 if last_success.tzinfo is None: 补 UTC)
    findings = _check_task(
        conn, "risk_daily_check", spec,
        datetime.now(UTC), window_hours=24,
    )
    # 期望不 raise + 结果合理 (1 success / 5min ago, max_gap 25h → 不 stale)
    assert all(f.kind != "stale" for f in findings)
