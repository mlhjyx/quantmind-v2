"""Unit tests for market_indicators_query — V3 §14 mode 9 feed shared helper (HC-2b3 G4).

覆盖:
  - query_limit_down_count: real row → int; None row / NULL count → None;
    SQL params 含 -9.9 跌停阈值
  - query_index_return: real row → fraction (pct_change / 100); None row /
    NULL pct_change → None; SQL params 含 000300.SH index_code
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.risk.market_indicators_query import (
    query_index_return,
    query_limit_down_count,
)


class _MockCursor:
    def __init__(self, conn: _MockConn) -> None:
        self._conn = conn
        self._last_sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._last_sql = sql
        self._conn.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        if "klines_daily" in self._last_sql:
            return self._conn.limit_down_row
        if "index_daily" in self._last_sql:
            return self._conn.index_return_row
        return None

    def close(self) -> None:
        pass


class _MockConn:
    def __init__(
        self,
        *,
        limit_down_row: tuple[Any, ...] | None = None,
        index_return_row: tuple[Any, ...] | None = None,
    ) -> None:
        self.limit_down_row = limit_down_row
        self.index_return_row = index_return_row
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _MockCursor:
        return _MockCursor(self)


# ── query_limit_down_count ──


def test_limit_down_count_real_row_returns_int() -> None:
    count = query_limit_down_count(_MockConn(limit_down_row=(537,)))
    assert count == 537
    assert isinstance(count, int)


def test_limit_down_count_zero_returns_zero() -> None:
    # COUNT(*) over a calm trading day = 0 (合法 "0 跌停" 信号, NOT no-signal)
    assert query_limit_down_count(_MockConn(limit_down_row=(0,))) == 0


def test_limit_down_count_none_row_returns_none() -> None:
    # fetchone None (defensive — COUNT(*) 永不返 NULL row, 但防御性)
    assert query_limit_down_count(_MockConn(limit_down_row=None)) is None


def test_limit_down_count_null_value_returns_none() -> None:
    assert query_limit_down_count(_MockConn(limit_down_row=(None,))) is None


def test_limit_down_count_sql_uses_minus_9_9_threshold() -> None:
    conn = _MockConn(limit_down_row=(10,))
    query_limit_down_count(conn)
    sql, params = conn.executed[0]
    assert "klines_daily" in sql
    assert params == (-9.9,)


# ── query_index_return ──


def test_index_return_real_row_converted_to_fraction() -> None:
    # index_daily.pct_change -6.8 (% units) → index_return -0.068 (fraction)
    ret = query_index_return(_MockConn(index_return_row=(-6.8,)))
    assert ret == pytest.approx(-0.068)


def test_index_return_positive_value() -> None:
    ret = query_index_return(_MockConn(index_return_row=(3.2,)))
    assert ret == pytest.approx(0.032)


def test_index_return_none_row_returns_none() -> None:
    # no index_daily 000300.SH row → no signal
    assert query_index_return(_MockConn(index_return_row=None)) is None


def test_index_return_null_value_returns_none() -> None:
    assert query_index_return(_MockConn(index_return_row=(None,))) is None


def test_index_return_sql_uses_csi300_index_code() -> None:
    conn = _MockConn(index_return_row=(-1.0,))
    query_index_return(conn)
    sql, params = conn.executed[0]
    assert "index_daily" in sql
    assert params == ("000300.SH",)
