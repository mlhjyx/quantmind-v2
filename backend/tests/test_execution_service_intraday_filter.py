"""P0-3 Intraday tradability filter — unit tests.

Tests `ExecutionService._filter_nontradable_codes` and the re-normalization
logic inside `execute_rebalance` (added 2026-05-17 to mitigate 0→20 initial
build risk where涨停/停牌 codes would partial-fill and leave capital idle).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from backend.app.services.execution_service import ExecutionService


def _make_conn(status_rows: list[tuple], klines_rows: list[tuple]) -> MagicMock:
    """Build a psycopg2-style mock conn whose cursor.execute returns 2 separate
    fetchall() payloads (1st = stock_status query, 2nd = klines query).

    Cursor is wrapped to support `with conn.cursor() as cur:` context manager
    pattern used by ExecutionService._filter_nontradable_codes (PR #379 reviewer P1 fix).
    """
    cur = MagicMock()
    cur.fetchall.side_effect = [status_rows, klines_rows]
    # Make `with cur:` return the same cur (default MagicMock returns a child).
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


class TestFilterNontradableCodes:
    EXEC = date(2026, 5, 18)

    def test_empty_codes_returns_empty(self):
        assert ExecutionService._filter_nontradable_codes(MagicMock(), self.EXEC, []) == {}

    def test_all_tradable_returns_empty(self):
        conn = _make_conn(status_rows=[], klines_rows=[])
        result = ExecutionService._filter_nontradable_codes(
            conn, self.EXEC, ["600000.SH", "000001.SZ"]
        )
        assert result == {}

    def test_suspended_detected(self):
        conn = _make_conn(status_rows=[("600001.SH", "suspended")], klines_rows=[])
        result = ExecutionService._filter_nontradable_codes(
            conn, self.EXEC, ["600000.SH", "600001.SH"]
        )
        assert result == {"600001.SH": "suspended"}

    def test_new_stock_detected(self):
        conn = _make_conn(status_rows=[("688999.SH", "new_stock")], klines_rows=[])
        result = ExecutionService._filter_nontradable_codes(conn, self.EXEC, ["688999.SH"])
        assert result == {"688999.SH": "new_stock"}

    def test_limit_up_detected(self):
        conn = _make_conn(status_rows=[], klines_rows=[("688001.SH",)])
        result = ExecutionService._filter_nontradable_codes(conn, self.EXEC, ["688001.SH"])
        assert result == {"688001.SH": "limit_up_T-1"}

    def test_suspended_precedence_over_limit_up(self):
        """Same code in BOTH queries → suspended wins (more severe)."""
        conn = _make_conn(
            status_rows=[("600001.SH", "suspended")],
            klines_rows=[("600001.SH",)],
        )
        result = ExecutionService._filter_nontradable_codes(conn, self.EXEC, ["600001.SH"])
        assert result == {"600001.SH": "suspended"}

    def test_mixed_reasons(self):
        conn = _make_conn(
            status_rows=[("600001.SH", "suspended"), ("688999.SH", "new_stock")],
            klines_rows=[("000003.SZ",)],
        )
        result = ExecutionService._filter_nontradable_codes(
            conn,
            self.EXEC,
            ["600000.SH", "600001.SH", "688999.SH", "000003.SZ", "000001.SZ"],
        )
        assert result == {
            "600001.SH": "suspended",
            "688999.SH": "new_stock",
            "000003.SZ": "limit_up_T-1",
        }


class TestRenormalizationMath:
    """Sanity-check the re-normalize formula inline in execute_rebalance.

    20 codes × 0.0485 = 0.97 total. Drop 5 → 15 remaining sum to 0.7275.
    Scale factor = 0.97 / 0.7275 = 1.333... Each remaining → 0.0485 * 1.333 = 0.0647.
    """

    def test_re_normalize_preserves_total(self):
        original = {f"C{i:03d}.SH": 0.0485 for i in range(20)}
        dropped = {f"C{i:03d}.SH" for i in range(5)}
        filtered = {k: v for k, v in original.items() if k not in dropped}
        original_total = sum(original.values())
        new_total = sum(filtered.values())
        scale = original_total / new_total
        rebalanced = {k: v * scale for k, v in filtered.items()}
        assert abs(sum(rebalanced.values()) - original_total) < 1e-9
        assert len(rebalanced) == 15
        assert abs(rebalanced[next(iter(rebalanced))] - 0.0647) < 1e-3

    def test_all_dropped_returns_empty(self):
        original = {"C001.SH": 0.5, "C002.SH": 0.5}
        dropped = {"C001.SH", "C002.SH"}
        filtered = {k: v for k, v in original.items() if k not in dropped}
        new_total = sum(filtered.values())
        # 实际 execute_rebalance: new_total==0 → hedged_target={}, is_rebalance=False
        assert new_total == 0
        assert filtered == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
