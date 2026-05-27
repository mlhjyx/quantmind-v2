"""iter 110 — Verify conftest mock_conn / mock_conn_factory_builder / assert_no_db_writes fixtures.

Self-tests for the iter 110 fixture infrastructure landed per
`docs/audit/MAKE_MOCK_CONN_REFACTOR_BLUEPRINT_2026_05_25.md` §6 (Option A pilot).

These tests verify:
T1: mock_conn yields fresh MagicMock per test (no shared state across tests)
T2: mock_conn cursor supports both bare and context-manager usage
T3: mock_conn has NO default fetchone return (test must opt-in, cures LL-198 B1)
T4: mock_conn_factory_builder produces callable factory with fetchone queue
T5: mock_conn_factory_builder factory has _conn / _cursor attrs for assertion
T6: assert_no_db_writes PASSES when only SELECT executed
T7: assert_no_db_writes FAILS when INSERT executed
T8: assert_no_db_writes FAILS when UPDATE executed
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ─────────────────────────────────────────────────────────────
# mock_conn fixture tests
# ─────────────────────────────────────────────────────────────


class TestMockConn:
    """Verify mock_conn fixture canonical behavior."""

    def test_yields_magic_mock(self, mock_conn: MagicMock) -> None:
        assert isinstance(mock_conn, MagicMock)

    def test_cursor_supports_bare_usage(self, mock_conn: MagicMock) -> None:
        """Common pattern: cursor = conn.cursor(); cursor.execute(...)."""
        cursor = mock_conn.cursor()
        cursor.execute("SELECT 1")
        assert cursor.execute.call_count == 1

    def test_cursor_supports_context_manager(self, mock_conn: MagicMock) -> None:
        """Alt pattern: with conn.cursor() as cur: cur.execute(...) (cures B4)."""
        with mock_conn.cursor() as cur:
            cur.execute("SELECT 2")
        assert cur.execute.call_count == 1

    def test_no_default_fetchone(self, mock_conn: MagicMock) -> None:
        """B1 cure: no implicit (0,) default — test must opt-in.

        Fetching without setup returns a MagicMock (truthy) — but NOT a tuple-like
        sentinel that misleads prod code into success path. Test must explicitly
        set `mock_conn.cursor().fetchone.return_value = (...)` for meaningful data.
        """
        cursor = mock_conn.cursor()
        result = cursor.fetchone()
        # Result is a MagicMock, NOT the (0,) tuple from LL-198 anti-pattern
        assert not isinstance(result, tuple)
        assert isinstance(result, MagicMock)


class TestMockConnFreshness:
    """B3 + B5 cure: each test invocation gets a fresh mock with no leakage."""

    def test_first_call_records_execute(self, mock_conn: MagicMock) -> None:
        cursor = mock_conn.cursor()
        cursor.execute("SELECT 'first test'")
        assert cursor.execute.call_count == 1

    def test_second_call_starts_at_zero(self, mock_conn: MagicMock) -> None:
        """If state leaked from prev test, call_count would be 2."""
        cursor = mock_conn.cursor()
        assert cursor.execute.call_count == 0
        cursor.execute("SELECT 'second test'")
        assert cursor.execute.call_count == 1


# ─────────────────────────────────────────────────────────────
# mock_conn_factory_builder tests
# ─────────────────────────────────────────────────────────────


class TestMockConnFactoryBuilder:
    """Verify factory-shaped fixture for prod code taking conn_factory callable."""

    def test_yields_callable_factory(self, mock_conn_factory_builder) -> None:
        factory = mock_conn_factory_builder(fetchone_queue=[None])
        assert callable(factory)
        conn = factory()
        assert isinstance(conn, MagicMock)

    def test_fetchone_queue_consumed_iter_style(self, mock_conn_factory_builder) -> None:
        factory = mock_conn_factory_builder(fetchone_queue=[("draft",), ("live",), None])
        conn = factory()
        cursor = conn.cursor()
        assert cursor.fetchone() == ("draft",)
        assert cursor.fetchone() == ("live",)
        assert cursor.fetchone() is None

    def test_factory_exposes_conn_and_cursor_attrs(self, mock_conn_factory_builder) -> None:
        """Sustained sibling pattern from test_strategy_registry.py."""
        factory = mock_conn_factory_builder()
        assert hasattr(factory, "_conn")
        assert hasattr(factory, "_cursor")
        assert isinstance(factory._conn, MagicMock)
        assert isinstance(factory._cursor, MagicMock)

    def test_rowcounts_queue_consumed_iter_style(self, mock_conn_factory_builder) -> None:
        factory = mock_conn_factory_builder(rowcounts=[1, 1, 0])
        conn = factory()
        cursor = conn.cursor()
        assert cursor.rowcount == 1
        assert cursor.rowcount == 1
        assert cursor.rowcount == 0

    def test_default_rowcount_is_one(self, mock_conn_factory_builder) -> None:
        """Default to typical UPSERT success when no override."""
        factory = mock_conn_factory_builder()
        conn = factory()
        cursor = conn.cursor()
        assert cursor.rowcount == 1

    def test_default_fetchall_is_empty_list(self, mock_conn_factory_builder) -> None:
        """iter 120 enhancement (blueprint §9.4): default fetchall=[] sustained.

        Unblocks future migration of test_strategy_evaluation_required.py +
        test_strategy_registry.py whose local defs set `cursor.fetchall.return_value = []`.
        """
        factory = mock_conn_factory_builder()
        conn = factory()
        cursor = conn.cursor()
        assert cursor.fetchall() == []
        # Override still works post-build (test can opt-in to non-empty rows)
        cursor.fetchall.return_value = [("row1",), ("row2",)]
        assert cursor.fetchall() == [("row1",), ("row2",)]


# ─────────────────────────────────────────────────────────────
# assert_no_db_writes helper tests
# ─────────────────────────────────────────────────────────────


class TestAssertNoDbWrites:
    """Codifies LL-198 fix point 2: SELECT-read NOT a write side effect."""

    def test_passes_when_only_select_executed(
        self, mock_conn: MagicMock, assert_no_db_writes
    ) -> None:
        cursor = mock_conn.cursor()
        cursor.execute("SELECT * FROM strategy")
        cursor.execute("  SELECT 1")  # leading whitespace OK
        cursor.execute("WITH cte AS (SELECT 1) SELECT * FROM cte")
        # Must not raise
        assert_no_db_writes(mock_conn)

    def test_fails_on_insert(self, mock_conn: MagicMock, assert_no_db_writes) -> None:
        cursor = mock_conn.cursor()
        cursor.execute("INSERT INTO strategy (name) VALUES ('foo')")
        with pytest.raises(AssertionError, match="no DB writes"):
            assert_no_db_writes(mock_conn)

    def test_fails_on_update(self, mock_conn: MagicMock, assert_no_db_writes) -> None:
        cursor = mock_conn.cursor()
        cursor.execute("UPDATE strategy SET status='live'")
        with pytest.raises(AssertionError, match="no DB writes"):
            assert_no_db_writes(mock_conn)

    def test_fails_on_delete(self, mock_conn: MagicMock, assert_no_db_writes) -> None:
        cursor = mock_conn.cursor()
        cursor.execute("DELETE FROM strategy WHERE id = 1")
        with pytest.raises(AssertionError, match="no DB writes"):
            assert_no_db_writes(mock_conn)

    def test_passes_on_zero_execute_calls(self, mock_conn: MagicMock, assert_no_db_writes) -> None:
        # No execute at all → no writes by vacuous truth
        assert_no_db_writes(mock_conn)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
