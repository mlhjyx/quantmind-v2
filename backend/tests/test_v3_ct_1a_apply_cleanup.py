"""Tests for V3 Plan v0.4 CT-1a — DB cleanup apply runner.

Scope (PURE / fixture-driven; 0 production DB hit):
  - Preflight result shape + failure aggregation
  - Snapshot capture JSON shape + atomic write
  - Rollback re-INSERT SQL construction
  - Migration file existence + content invariants
  - CLI mode mutual exclusion

Out of scope (integration-only, exercised by `python scripts/v3_ct_1a_apply_cleanup.py
--dry-run` against live DB):
  - Actual DB SELECT/DELETE execution
  - Live preflight count match

关联铁律: 25 (改什么读什么) / 33 (fail-loud) / 40 (test debt) / 41 (UTC tz-aware)
关联 Plan: V3_PT_CUTOVER_PLAN_v0.1.md §A CT-1a
关联 LL: LL-098 X10 / LL-159 / LL-172
"""

# ruff: noqa: E402 — sys.path.insert(s) precede imports (necessary path setup pattern)

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import pytest
from v3_ct_1a_apply_cleanup import (
    _MIGRATION_PERF_SERIES,
    _MIGRATION_POS_SNAPSHOT,
    _PERFORMANCE_SERIES_DATE_HI,
    _PERFORMANCE_SERIES_DATE_LO,
    _PERFORMANCE_SERIES_EXPECTED,
    _POSITION_SNAPSHOT_DATES,
    _POSITION_SNAPSHOT_EXPECTED,
    _ROLLBACK_SNAPSHOT,
    _STRATEGY_ID,
    _capture_snapshot,
    _PreflightResult,
    _rollback_from_snapshot,
    _verify_preflight,
    _write_snapshot_atomic,
)

# ─────────────────────────────────────────────────────────────
# Constants / configuration invariants
# ─────────────────────────────────────────────────────────────


class TestConstants:
    def test_strategy_id_matches_phase0_finding(self) -> None:
        """Phase 0 SQL verify 2026-05-16: CORE3+dv_ttm WF PASS strategy."""
        assert _STRATEGY_ID == "28fc37e5-2d32-4ada-92e0-41c11a5103d0"

    def test_position_snapshot_dates_are_6_distinct(self) -> None:
        """Plan §A cite drift fix — actual stale = 6 dates, NOT 1."""
        assert len(_POSITION_SNAPSHOT_DATES) == 6
        assert len(set(_POSITION_SNAPSHOT_DATES)) == 6

    def test_position_snapshot_dates_are_pre_29_trading_days(self) -> None:
        """Dates are 4-20, 4-21, 4-22, 4-23, 4-24, 4-27 (4-25/26 weekend)."""
        expected = {
            "2026-04-20",
            "2026-04-21",
            "2026-04-22",
            "2026-04-23",
            "2026-04-24",
            "2026-04-27",
        }
        assert set(_POSITION_SNAPSHOT_DATES) == expected

    def test_expected_counts_match_phase0_findings(self) -> None:
        """SHUTDOWN_NOTICE §3 + Phase 0 verify 2026-05-16."""
        assert _POSITION_SNAPSHOT_EXPECTED == 114  # 6 dates × 19 rows
        assert _PERFORMANCE_SERIES_EXPECTED == 7  # 4-20 ~ 4-28 inclusive

    def test_performance_series_range_covers_4_28(self) -> None:
        """Plan §A cite '4-28 stale' is in performance_series even though
        position_snapshot 4-28 = 0 rows."""
        assert _PERFORMANCE_SERIES_DATE_LO == "2026-04-20"
        assert _PERFORMANCE_SERIES_DATE_HI == "2026-04-28"


# ─────────────────────────────────────────────────────────────
# Migration SQL files
# ─────────────────────────────────────────────────────────────


class TestMigrationFiles:
    def test_position_snapshot_migration_exists(self) -> None:
        assert _MIGRATION_POS_SNAPSHOT.exists()

    def test_performance_series_migration_exists(self) -> None:
        assert _MIGRATION_PERF_SERIES.exists()

    def test_position_snapshot_migration_has_safety_assertions(self) -> None:
        """Migration must include pre + post DO block assertions.

        Code-reviewer P1 fix (2026-05-16): BEGIN/COMMIT removed from SQL
        files — runner manages transaction boundary so position_snapshot
        + performance_series commit atomically. Pre/post DO block
        assertions remain (the real safety net).
        """
        sql = _MIGRATION_POS_SNAPSHOT.read_text(encoding="utf-8")
        assert "DO $$" in sql
        assert "RAISE EXCEPTION" in sql
        # P1 fix sustained: BEGIN/COMMIT NOT in file (runner manages txn).
        assert "BEGIN;" not in sql
        assert "COMMIT;" not in sql
        assert "pre_count" in sql.lower() or "expected 114" in sql.lower()

    def test_performance_series_migration_has_position_count_19_guard(self) -> None:
        """Extra safety — position_count=19 filter ensures never touches non-stale."""
        sql = _MIGRATION_PERF_SERIES.read_text(encoding="utf-8")
        assert "position_count = 19" in sql
        assert "execution_mode = 'live'" in sql
        assert _STRATEGY_ID in sql

    def test_rollback_files_exist(self) -> None:
        """Both rollback SQL companion files must exist (ADR-022 reversibility)."""
        rollback_ps = _MIGRATION_POS_SNAPSHOT.with_name(
            _MIGRATION_POS_SNAPSHOT.stem + "_rollback.sql"
        )
        rollback_prf = _MIGRATION_PERF_SERIES.with_name(
            _MIGRATION_PERF_SERIES.stem + "_rollback.sql"
        )
        assert rollback_ps.exists()
        assert rollback_prf.exists()


# ─────────────────────────────────────────────────────────────
# Preflight result aggregation
# ─────────────────────────────────────────────────────────────


class TestPreflightResult:
    def test_ok_true_when_no_failures(self) -> None:
        r = _PreflightResult()
        assert r.ok is True

    def test_ok_false_when_any_failure(self) -> None:
        r = _PreflightResult(failures=["count drift"])
        assert r.ok is False

    def test_default_values_sustained(self) -> None:
        r = _PreflightResult()
        assert r.position_snapshot_count == 0
        assert r.performance_series_count == 0
        assert r.cb_state_live_nav is None
        assert r.failures == []


# ─────────────────────────────────────────────────────────────
# _verify_preflight with mock cursor
# ─────────────────────────────────────────────────────────────


class _MockCursor:
    """Mock cursor with scripted fetch responses keyed by SQL substring."""

    def __init__(self, responses: dict[str, list[tuple]]) -> None:
        self.responses = responses
        self.executions: list[tuple[str, Any]] = []
        self._current_rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        self.executions.append((sql, params))
        # Match by first SQL substring key found.
        for key, rows in self.responses.items():
            if key in sql:
                self._current_rows = list(rows)
                return
        self._current_rows = []

    def fetchone(self):
        if not self._current_rows:
            return None
        return self._current_rows[0]

    def fetchall(self):
        return list(self._current_rows)


class _MockConn:
    """Mock connection wrapping a _MockCursor (single-cursor scope)."""

    def __init__(self, cur: _MockCursor) -> None:
        self._cur = cur
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return self._cur

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        pass


class TestVerifyPreflight:
    def test_all_counts_match_returns_ok(self) -> None:
        cur = _MockCursor(
            {
                "FROM position_snapshot": [(114,)],
                "FROM performance_series WHERE trade_date BETWEEN": [(7,)],
                "FROM circuit_breaker_state": [("993520.16", "2026-04-30 19:48:20+08")],
                "ORDER BY trade_date DESC": [("2026-05-15", "993520.66")],
            }
        )
        conn = _MockConn(cur)
        r = _verify_preflight(conn, env_check=False)
        assert r.ok is True
        assert r.position_snapshot_count == 114
        assert r.performance_series_count == 7
        assert r.cb_state_live_nav == pytest.approx(993520.16)
        assert r.perf_series_latest_date == "2026-05-15"

    def test_position_snapshot_count_drift_fails(self) -> None:
        cur = _MockCursor(
            {
                "FROM position_snapshot": [(113,)],
                "FROM performance_series WHERE trade_date BETWEEN": [(7,)],
                "FROM circuit_breaker_state": [("993520.16", "x")],
                "ORDER BY trade_date DESC": [("2026-05-15", "993520.66")],
            }
        )
        r = _verify_preflight(_MockConn(cur), env_check=False)
        assert r.ok is False
        assert any("position_snapshot stale count drift" in f for f in r.failures)

    def test_cb_state_nav_drift_fails(self) -> None:
        cur = _MockCursor(
            {
                "FROM position_snapshot": [(114,)],
                "FROM performance_series WHERE trade_date BETWEEN": [(7,)],
                "FROM circuit_breaker_state": [("123.45", "x")],
                "ORDER BY trade_date DESC": [("2026-05-15", "993520.66")],
            }
        )
        r = _verify_preflight(_MockConn(cur), env_check=False)
        assert r.ok is False
        assert any("circuit_breaker_state.live nav drift" in f for f in r.failures)

    def _passing_cursor(self) -> _MockCursor:
        return _MockCursor(
            {
                "FROM position_snapshot": [(114,)],
                "FROM performance_series WHERE trade_date BETWEEN": [(7,)],
                "FROM circuit_breaker_state": [("993520.16", "x")],
                "ORDER BY trade_date DESC": [("2026-05-15", "993520.66")],
            }
        )

    def test_env_check_blocks_when_live_trading_enabled(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("LIVE_TRADING_DISABLED", "false")
        monkeypatch.setenv("EXECUTION_MODE", "paper")
        r = _verify_preflight(_MockConn(self._passing_cursor()), env_check=True)
        assert r.ok is False
        assert any("LIVE_TRADING_DISABLED" in f for f in r.failures)

    def test_env_check_blocks_when_unset_strict_gate(self, monkeypatch: Any) -> None:
        """P2 reviewer fix (2026-05-16): unset env var FAILS, NOT silently passes.

        Previous gate `if x and x != 'true'` allowed empty-string env through
        (defensive-but-permissive). New strict gate requires explicit "true".
        """
        monkeypatch.delenv("LIVE_TRADING_DISABLED", raising=False)
        monkeypatch.delenv("EXECUTION_MODE", raising=False)
        r = _verify_preflight(_MockConn(self._passing_cursor()), env_check=True)
        assert r.ok is False
        assert any("LIVE_TRADING_DISABLED" in f for f in r.failures)
        assert any("EXECUTION_MODE" in f for f in r.failures)

    def test_performance_series_count_drift_fails(self) -> None:
        """P2 reviewer fix (2026-05-16): missing drift test (parity with
        position_snapshot drift coverage)."""
        cur = _MockCursor(
            {
                "FROM position_snapshot": [(114,)],
                "FROM performance_series WHERE trade_date BETWEEN": [(6,)],
                "FROM circuit_breaker_state": [("993520.16", "x")],
                "ORDER BY trade_date DESC": [("2026-05-15", "993520.66")],
            }
        )
        r = _verify_preflight(_MockConn(cur), env_check=False)
        assert r.ok is False
        assert any("performance_series stale count drift" in f for f in r.failures)


# ─────────────────────────────────────────────────────────────
# Snapshot capture + atomic write
# ─────────────────────────────────────────────────────────────


class TestSnapshotCaptureAndWrite:
    def test_capture_emits_expected_shape(self) -> None:
        cur = _MockCursor(
            {
                "table_name = 'position_snapshot'": [
                    ("code",),
                    ("trade_date",),
                    ("quantity",),
                ],
                "FROM position_snapshot WHERE trade_date = ANY": [
                    ("600519.SH", "2026-04-27", 100),
                ],
                "table_name = 'performance_series'": [
                    ("trade_date",),
                    ("nav",),
                ],
                "FROM performance_series WHERE trade_date BETWEEN": [
                    ("2026-04-27", "1014180.08"),
                ],
            }
        )
        snapshot = _capture_snapshot(_MockConn(cur))
        assert "captured_at_utc" in snapshot
        assert snapshot["strategy_id"] == _STRATEGY_ID
        assert len(snapshot["position_snapshot_rows"]) == 1
        assert snapshot["position_snapshot_rows"][0]["code"] == "600519.SH"
        assert len(snapshot["performance_series_rows"]) == 1

    def test_atomic_write_roundtrips_via_tmp(self, tmp_path: Path) -> None:
        out = tmp_path / "snap.json"
        snap = {"a": 1, "rows": [{"x": "y"}]}
        _write_snapshot_atomic(snap, out)
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded == snap
        # No tmp residue.
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("snap_") and p.suffix == ".tmp"]
        assert leftovers == []

    def test_atomic_write_creates_parent_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "dir" / "snap.json"
        _write_snapshot_atomic({"k": "v"}, out)
        assert out.exists()


# ─────────────────────────────────────────────────────────────
# Rollback re-INSERT semantics
# ─────────────────────────────────────────────────────────────


class TestRollback:
    def test_rollback_calls_insert_for_each_row(self) -> None:
        cur = MagicMock()
        cur.__enter__ = lambda self: self
        cur.__exit__ = lambda *a: None
        conn = MagicMock()
        conn.cursor.return_value = cur

        snapshot = {
            "position_snapshot_rows": [
                {"code": "600519.SH", "trade_date": "2026-04-27", "quantity": 100},
                {"code": "601138.SH", "trade_date": "2026-04-27", "quantity": 800},
            ],
            "performance_series_rows": [
                {"trade_date": "2026-04-27", "nav": "1014180.08", "position_count": 19},
            ],
        }
        ps, prf = _rollback_from_snapshot(conn, snapshot)
        assert ps == 2
        assert prf == 1
        # 3 INSERT calls total.
        assert cur.execute.call_count == 3

    def test_rollback_empty_snapshot_no_op(self) -> None:
        cur = MagicMock()
        cur.__enter__ = lambda self: self
        cur.__exit__ = lambda *a: None
        conn = MagicMock()
        conn.cursor.return_value = cur

        snapshot = {"position_snapshot_rows": [], "performance_series_rows": []}
        ps, prf = _rollback_from_snapshot(conn, snapshot)
        assert ps == 0
        assert prf == 0
        assert cur.execute.call_count == 0

    def test_rollback_blocks_unsafe_column_name(self) -> None:
        """P1 reviewer fix (2026-05-16): SQL identifier injection guard.

        Corrupted/crafted snapshot with unsafe column names must be rejected
        BEFORE any INSERT is constructed. Defense-in-depth — column names
        cannot be parameterized in SQL, so identifier validation is the
        only protection.
        """
        cur = MagicMock()
        cur.__enter__ = lambda self: self
        cur.__exit__ = lambda *a: None
        conn = MagicMock()
        conn.cursor.return_value = cur

        bad_snapshot = {
            "position_snapshot_rows": [
                {"code; DROP TABLE position_snapshot--": "x", "trade_date": "2026-04-27"},
            ],
            "performance_series_rows": [],
        }
        with pytest.raises(ValueError, match="Unsafe column name"):
            _rollback_from_snapshot(conn, bad_snapshot)
        # 0 SQL executed (guard fires BEFORE INSERT construction).
        assert cur.execute.call_count == 0


# ─────────────────────────────────────────────────────────────
# _json_default — JSON-native pass-through (P2 fix: None→"None" corruption)
# ─────────────────────────────────────────────────────────────


class TestJsonDefaultPassThrough:
    """P2 reviewer fix (2026-05-16): _json_default must preserve None / bool /
    int / float / str as-is. Previous str() fallback converted None to the
    string 'None', corrupting NULL columns in rollback re-INSERT.

    Test verifies snapshot capture preserves NULLs correctly via _capture_snapshot.
    """

    def test_none_preserved_as_none_in_snapshot(self) -> None:
        cur = _MockCursor(
            {
                "table_name = 'position_snapshot'": [
                    ("code",), ("turnover",),
                ],
                "FROM position_snapshot WHERE trade_date = ANY": [
                    ("600519.SH", None),  # turnover is NULL
                ],
                "table_name = 'performance_series'": [("trade_date",)],
                "FROM performance_series WHERE trade_date BETWEEN": [],
            }
        )
        snap = _capture_snapshot(_MockConn(cur))
        assert len(snap["position_snapshot_rows"]) == 1
        row = snap["position_snapshot_rows"][0]
        # P2 fix: None preserved as None (NOT the string "None").
        assert row["turnover"] is None

    def test_int_and_float_preserved_natively(self) -> None:
        cur = _MockCursor(
            {
                "table_name = 'position_snapshot'": [
                    ("code",), ("quantity",), ("ratio",),
                ],
                "FROM position_snapshot WHERE trade_date = ANY": [
                    ("600519.SH", 10700, 0.5),
                ],
                "table_name = 'performance_series'": [("trade_date",)],
                "FROM performance_series WHERE trade_date BETWEEN": [],
            }
        )
        snap = _capture_snapshot(_MockConn(cur))
        row = snap["position_snapshot_rows"][0]
        assert row["quantity"] == 10700  # int preserved
        assert isinstance(row["quantity"], int)
        assert row["ratio"] == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────
# Phase 0 preflight invariants (sustained LL-172 lesson 1)
# ─────────────────────────────────────────────────────────────


class TestPhase0Invariants:
    def test_rollback_snapshot_path_in_audit_dir(self) -> None:
        """Sustained docs/audit/ for sediment artifacts (沿用 CT-1a closure 体例)."""
        assert "docs" in _ROLLBACK_SNAPSHOT.parts
        assert "audit" in _ROLLBACK_SNAPSHOT.parts
        assert _ROLLBACK_SNAPSHOT.suffix == ".json"

    def test_strategy_id_matches_circuit_breaker_state_invariant(self) -> None:
        """Strategy must match cb_state.live row (Phase 0 verify 2026-05-16)."""
        # Sustained from Phase 0 SQL verify output.
        assert _STRATEGY_ID == "28fc37e5-2d32-4ada-92e0-41c11a5103d0"

    def test_migration_files_are_in_backend_migrations(self) -> None:
        """Sustained `backend/migrations/` location convention."""
        assert _MIGRATION_POS_SNAPSHOT.parent.name == "migrations"
        assert _MIGRATION_PERF_SERIES.parent.name == "migrations"
