"""Unit tests for daily_aggregator — V3 §13.2 元监控 (S10).

覆盖:
  - aggregate_daily_metrics: all metric specs run, missing table → default 0
  - upsert_daily_metrics: INSERT path / UPSERT on conflict path
  - DailyMetricsResult dataclass defaults
  - 反 silent: per-query failure does NOT abort the entire rollup
  - 铁律 32 sustained: aggregator does NOT call conn.commit / conn.rollback
    except for the silent-rollback-after-query-error reset (which is required
    to avoid "transaction aborted" cascading failures, NOT a transaction
    boundary write)

铁律 31 not strictly invoked (SQL is IO-adjacent, but PURE compute on results).
铁律 33: missing source tables → default value, NOT raise.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import psycopg2

from backend.qm_platform.risk.metrics.daily_aggregator import (
    DailyMetricsResult,
    DailyMetricsSpec,
    aggregate_daily_metrics,
    upsert_daily_metrics,
)

# ── Mock conn helper ──


class _MockConn:
    """Lightweight mock: each execute call returns a pre-staged scalar."""

    def __init__(self) -> None:
        self._results: list[Any] = []  # list of (single-row scalar | Exception)
        self._idx = 0
        self.commit_called = False
        self.rollback_count = 0

    def stage_scalar(self, value: Any) -> None:
        self._results.append(value)

    def stage_error(self, exc: Exception) -> None:
        self._results.append(exc)

    def cursor(self) -> MagicMock:
        cur = MagicMock()

        def execute(sql: str, params: tuple) -> None:  # noqa: ARG001
            if self._idx >= len(self._results):
                cur.fetchone = MagicMock(return_value=(0,))
                return
            staged = self._results[self._idx]
            self._idx += 1
            if isinstance(staged, Exception):
                raise staged
            cur.fetchone = MagicMock(return_value=(staged,))

        cur.execute = MagicMock(side_effect=execute)
        cur.close = MagicMock()
        return cur

    def commit(self) -> None:
        self.commit_called = True

    def rollback(self) -> None:
        self.rollback_count += 1


# ── aggregate_daily_metrics ──


class TestAggregate:
    def test_happy_path_all_metrics_populated(self):
        """All specs return scalar; result fields match staged values."""
        conn = _MockConn()
        # Default specs has 9 entries; stage 9 values
        for v in [12, 34, 56, 7, 5, 1, 1, 0, 3.14]:
            conn.stage_scalar(v)

        result = aggregate_daily_metrics(conn, date(2026, 5, 13))
        assert isinstance(result, DailyMetricsResult)
        assert result.date == date(2026, 5, 13)
        assert result.alerts_p0_count == 12
        assert result.alerts_p1_count == 34
        assert result.alerts_p2_count == 56
        assert result.staged_plans_count == 7
        assert result.staged_executed_count == 5
        assert result.staged_cancelled_count == 1
        assert result.staged_timeout_executed_count == 1
        assert result.auto_triggered_count == 0
        assert result.llm_cost_total == 3.14

    def test_missing_table_returns_default(self):
        """psycopg2 UndefinedTable → query returns default_on_missing (0)."""
        conn = _MockConn()
        # Stage error for all 9 queries
        for _ in range(9):
            conn.stage_error(psycopg2.errors.UndefinedTable("table missing"))

        result = aggregate_daily_metrics(conn, date(2026, 5, 13))
        assert result.alerts_p0_count == 0
        assert result.alerts_p1_count == 0
        assert result.llm_cost_total == 0.0
        # All errors triggered rollback (反 silent cascading transaction abort)
        assert conn.rollback_count == 9

    def test_partial_failure_other_queries_continue(self):
        """1 failed query doesn't abort the rest — partial result returned."""
        conn = _MockConn()
        # Stage: P0 ok, P1 error, P2 ok, ... staged_plans ok, ... (mix)
        conn.stage_scalar(10)  # P0
        conn.stage_error(Exception("oops"))  # P1
        for v in [20, 5, 5, 0, 0, 0, 1.0]:  # remaining 7
            conn.stage_scalar(v)

        result = aggregate_daily_metrics(conn, date(2026, 5, 13))
        assert result.alerts_p0_count == 10
        assert result.alerts_p1_count == 0  # defaulted from error
        assert result.alerts_p2_count == 20
        assert result.llm_cost_total == 1.0
        assert conn.rollback_count == 1  # only P1 query rolled back

    def test_none_result_treated_as_default(self):
        """SELECT returning NULL → use default."""
        conn = _MockConn()
        conn.stage_scalar(None)  # P0
        for _ in range(8):
            conn.stage_scalar(0)
        result = aggregate_daily_metrics(conn, date(2026, 5, 13))
        assert result.alerts_p0_count == 0  # None → default 0


# ── upsert_daily_metrics ──


class TestUpsert:
    def test_upsert_returns_rowcount(self):
        result = DailyMetricsResult(
            date=date(2026, 5, 13),
            alerts_p0_count=3,
            staged_plans_count=2,
            llm_cost_total=1.5,
        )
        cur = MagicMock()
        cur.rowcount = 1
        cur.close = MagicMock()
        conn = MagicMock()
        conn.cursor = MagicMock(return_value=cur)

        rc = upsert_daily_metrics(conn, result)
        assert rc == 1
        cur.execute.assert_called_once()
        # Verify INSERT ... ON CONFLICT (date) DO UPDATE SET pattern
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO risk_metrics_daily" in sql
        assert "ON CONFLICT (date) DO UPDATE SET" in sql
        # date is first param
        assert params[0] == date(2026, 5, 13)

    def test_upsert_does_not_commit(self):
        """铁律 32 sustained: caller owns commit."""
        cur = MagicMock()
        cur.rowcount = 1
        cur.close = MagicMock()
        conn = MagicMock()
        conn.cursor = MagicMock(return_value=cur)
        conn.commit = MagicMock()
        conn.rollback = MagicMock()

        upsert_daily_metrics(conn, DailyMetricsResult(date=date(2026, 5, 13)))
        conn.commit.assert_not_called()
        conn.rollback.assert_not_called()


# ── Custom spec override ──


class TestSpecOverride:
    def test_custom_spec_used(self):
        """Caller can override individual metric specs (e.g. for tests / schema changes)."""
        custom = {
            "alerts_p0_count": DailyMetricsSpec(
                column="alerts_p0_count",
                sql="SELECT 999 WHERE 'x' = %s",  # contrived but valid
            ),
        }
        conn = _MockConn()
        conn.stage_scalar(999)
        result = aggregate_daily_metrics(conn, date(2026, 5, 13), specs=custom)
        assert result.alerts_p0_count == 999
