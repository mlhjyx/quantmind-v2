"""L1/L2 unit tests for PositionSource 实现 (QMTPositionSource + DBPositionSource).

覆盖:
  - QMTPositionSource: connected+positions / disconnected / empty portfolio
  - DBPositionSource: snapshot rows / no rows (raise)
  - _enricher.build_positions 纯函数 (0 shares skip)
"""
from __future__ import annotations

import contextlib
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.risk.interface import PositionSourceError
from backend.qm_platform.risk.sources._enricher import build_positions
from backend.qm_platform.risk.sources.db_snapshot import DBPositionSource
from backend.qm_platform.risk.sources.qmt_realtime import QMTPositionSource


def _mock_conn_with_rows(rows: list[tuple]) -> MagicMock:
    """Mock psycopg2 conn, cursor.fetchall returns rows, cursor.fetchone returns None."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.fetchone.return_value = None  # no entry_date / peak for simple tests
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = False
    return mock_conn


def _conn_factory(mock_conn: MagicMock):
    @contextlib.contextmanager
    def factory():
        yield mock_conn
    return factory


# ---------- _enricher.build_positions pure fn ----------


class TestBuildPositions:
    def test_skip_zero_shares(self):
        """shares <= 0 跳过 (已平仓)."""
        shares = {"A.SH": 100, "B.SZ": 0, "C.SH": -10}
        result = build_positions(shares, {"A.SH": 10.0, "B.SZ": 20.0, "C.SH": 30.0}, {}, {})
        assert len(result) == 1
        assert result[0].code == "A.SH"

    def test_fallback_peak_to_entry(self):
        """peak_prices 缺失 → fallback 到 entry_price."""
        result = build_positions(
            shares_dict={"A.SH": 100},
            entry_prices={"A.SH": 10.0},
            peak_prices={},  # 缺失
            current_prices={"A.SH": 12.0},
        )
        assert len(result) == 1
        assert result[0].peak_price == 10.0  # fallback

    def test_missing_current_as_zero(self):
        """current_prices 缺失 → 0.0 (规则层 skip)."""
        result = build_positions(
            shares_dict={"A.SH": 100},
            entry_prices={"A.SH": 10.0},
            peak_prices={"A.SH": 15.0},
            current_prices={},  # 缺失
        )
        assert result[0].current_price == 0.0

    # Phase 1.5a (Session 44): entry_date contract tests
    def test_entry_date_from_dict(self):
        """entry_dates 提供 → Position.entry_date 填入."""
        from datetime import date as date_t

        ed = date_t(2026, 4, 15)
        result = build_positions(
            shares_dict={"A.SH": 100},
            entry_prices={"A.SH": 10.0},
            peak_prices={"A.SH": 12.0},
            current_prices={"A.SH": 11.0},
            entry_dates={"A.SH": ed},
        )
        assert result[0].entry_date == ed

    def test_entry_date_missing_in_dict_returns_none(self):
        """entry_dates 缺该 code → Position.entry_date=None (rule 应 skip)."""
        result = build_positions(
            shares_dict={"A.SH": 100},
            entry_prices={"A.SH": 10.0},
            peak_prices={"A.SH": 12.0},
            current_prices={"A.SH": 11.0},
            entry_dates={"OTHER.SZ": __import__("datetime").date(2026, 1, 1)},
        )
        assert result[0].entry_date is None

    def test_entry_date_param_omitted_returns_none(self):
        """entry_dates 参数省略 (旧调用方) → 全部 Position.entry_date=None 向后兼容."""
        result = build_positions(
            shares_dict={"A.SH": 100, "B.SZ": 200},
            entry_prices={"A.SH": 10.0, "B.SZ": 20.0},
            peak_prices={"A.SH": 12.0, "B.SZ": 22.0},
            current_prices={"A.SH": 11.0, "B.SZ": 21.0},
            # entry_dates omitted → defaults to None
        )
        assert all(p.entry_date is None for p in result)


# ---------- QMTPositionSource ----------


class TestQMTPositionSource:
    def test_disconnected_raises(self):
        reader = MagicMock()
        reader.is_connected.return_value = False

        source = QMTPositionSource(reader=reader, conn_factory=lambda: _mock_conn_with_rows([]))
        with pytest.raises(PositionSourceError, match="disconnected"):
            source.load(strategy_id="x", execution_mode="paper")

    def test_empty_portfolio_returns_empty_list(self):
        """reviewer P1-1 采纳: is_connected=True + 空 dict = 合法空仓, 返 [] 非 raise."""
        reader = MagicMock()
        reader.is_connected.return_value = True
        reader.get_positions.return_value = {}

        source = QMTPositionSource(reader=reader, conn_factory=lambda: _mock_conn_with_rows([]))
        positions = source.load(strategy_id="x", execution_mode="paper")
        assert positions == []

    def test_success_returns_enriched_positions(self):
        reader = MagicMock()
        reader.is_connected.return_value = True
        reader.get_positions.return_value = {"600519.SH": 100}
        reader.get_prices.return_value = {"600519.SH": 120.0}

        mock_conn = _mock_conn_with_rows([])  # trade_log empty → entry=0
        source = QMTPositionSource(reader=reader, conn_factory=_conn_factory(mock_conn))
        positions = source.load(strategy_id="x", execution_mode="paper")

        assert len(positions) == 1
        assert positions[0].code == "600519.SH"
        assert positions[0].shares == 100
        assert positions[0].current_price == 120.0
        # entry_price=0 because trade_log empty (mock_cursor.fetchall returns [] for buys)


# ---------- DBPositionSource ----------


class TestDBPositionSource:
    def test_empty_snapshot_raises(self):
        """position_snapshot 无行 → raise."""
        mock_conn = _mock_conn_with_rows([])
        price_reader = MagicMock()
        price_reader.get_prices.return_value = {}

        source = DBPositionSource(
            conn_factory=_conn_factory(mock_conn),
            price_reader=price_reader,
        )
        with pytest.raises(PositionSourceError, match="no rows"):
            source.load(strategy_id="x", execution_mode="paper")

    def test_success_returns_positions(self):
        """position_snapshot 有行 → 拼装 Position 列表.

        Mock fetchall sequence:
            1st: position_snapshot SELECT → [("600519.SH", 100)]
            2nd: trade_log buys SELECT (entry_prices) → [] (entry=0)
        """
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [("600519.SH", 100)],  # position_snapshot rows
            [],                    # load_entry_prices trade_log buys (empty → entry=0)
        ]
        mock_cursor.fetchone.return_value = None  # load_peak_prices entry_date None → no peak
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = False

        price_reader = MagicMock()
        price_reader.get_prices.return_value = {"600519.SH": 150.0}

        source = DBPositionSource(
            conn_factory=_conn_factory(mock_conn),
            price_reader=price_reader,
        )
        positions = source.load(strategy_id="x", execution_mode="paper")
        assert len(positions) == 1
        assert positions[0].code == "600519.SH"
        assert positions[0].shares == 100
        assert positions[0].current_price == 150.0
