"""Backtest detail API contract regression tests.

These tests guard the live schema drift found in governance Batch 21:
detail endpoints must use the actual DDL columns and return JSON-friendly
values instead of leaking Decimal/date objects.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.api import backtest


class _Result:
    """Small SQLAlchemy AsyncResult stand-in for endpoint unit tests."""

    def __init__(self, rows: list[dict] | None = None, scalar_value: int | None = None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def mappings(self):
        mapped = MagicMock()
        mapped.all.return_value = self._rows
        mapped.first.return_value = self._rows[0] if self._rows else None
        return mapped

    def scalar(self):
        return self._scalar_value


def _completed_run(**overrides):
    run = {
        "run_id": str(uuid4()),
        "status": "completed",
        "annual_return": Decimal("0.1234"),
        "sharpe_ratio": Decimal("1.2345"),
        "max_drawdown": Decimal("-0.0567"),
        "calmar_ratio": Decimal("2.1764"),
    }
    run.update(overrides)
    return run


@pytest.mark.asyncio
async def test_safe_query_reraises_undefined_column_errors():
    """Undefined columns are schema drift and must fail loud, not empty-list."""
    session = AsyncMock()
    session.execute.side_effect = RuntimeError('column "benchmark_return" does not exist')

    with pytest.raises(RuntimeError, match="benchmark_return"):
        await backtest._safe_query(
            session,
            "SELECT benchmark_return FROM backtest_daily_nav WHERE run_id = :rid",
            {"rid": str(uuid4())},
        )


@pytest.mark.asyncio
async def test_safe_query_still_tolerates_missing_relation():
    """Missing optional result tables keep the original fail-safe behavior."""
    session = AsyncMock()
    session.execute.side_effect = RuntimeError('relation "backtest_daily_nav" does not exist')

    rows = await backtest._safe_query(
        session,
        "SELECT nav FROM backtest_daily_nav WHERE run_id = :rid",
        {"rid": str(uuid4())},
    )

    assert rows == []


def test_jsonable_row_converts_decimal_dates_and_uuid_recursively():
    """Detail endpoints must return JSON-friendly values for frontend consumers."""
    row_id = uuid4()

    converted = backtest._jsonable_row(
        {
            "id": row_id,
            "trade_date": date(2026, 6, 1),
            "created_at": datetime(2026, 6, 1, 9, 30, 0),
            "metrics": {"sharpe": Decimal("1.2300")},
            "series": [Decimal("0.1000")],
        }
    )

    assert converted == {
        "id": str(row_id),
        "trade_date": "2026-06-01",
        "created_at": "2026-06-01T09:30:00",
        "metrics": {"sharpe": 1.23},
        "series": [0.1],
    }


def test_backtest_detail_sql_uses_current_ddl_columns():
    """Source-level guard for columns verified against QUANTMIND_V2_DDL_FINAL.sql."""
    source = Path("backend/app/api/backtest.py").read_text(encoding="utf-8")

    assert "LAG(benchmark_nav)" in source
    assert "benchmark_return FROM backtest_daily_nav" not in source
    assert "trade_id AS id" in source
    assert "SELECT id, signal_date" not in source
    assert "CAST(NULL AS NUMERIC) AS target_price" in source
    assert "NULL::numeric" not in source
    assert "shares * market_price AS market_value" in source
    assert "(market_price - cost_basis) * shares" in source
    assert "AVG(pnl)" not in source


@pytest.mark.asyncio
async def test_trade_endpoint_returns_uuid_id_and_numeric_values_as_jsonable():
    """Trades endpoint mirrors DDL trade_id and converts Decimal/date fields."""
    run_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _Result(scalar_value=1),
            _Result(
                [
                    {
                        "id": uuid4(),
                        "signal_date": date(2026, 1, 2),
                        "exec_date": date(2026, 1, 3),
                        "stock_code": "600000",
                        "side": "buy",
                        "shares": Decimal("100.0"),
                        "target_price": None,
                        "exec_price": Decimal("10.50"),
                        "slippage_bps": Decimal("1.25"),
                        "commission": Decimal("5.00"),
                        "stamp_tax": Decimal("0"),
                        "transfer_fee": None,
                        "total_cost": Decimal("5.00"),
                        "reject_reason": None,
                    }
                ]
            ),
        ]
    )

    with patch("app.api.backtest._require_completed", new=AsyncMock(return_value=_completed_run())):
        payload = await backtest.get_trades(run_id, page=1, page_size=100, session=session)

    item = payload["items"][0]
    assert isinstance(item["id"], str)
    assert item["exec_date"] == "2026-01-03"
    assert item["exec_price"] == 10.5
    assert item["shares"] == 100.0


@pytest.mark.asyncio
async def test_cost_sensitivity_accepts_decimal_run_metrics():
    """Decimal run metrics must not break cost sensitivity arithmetic."""
    run_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _Result([{"trade_date": date(2026, 1, 2), "daily_return": Decimal("0.01"), "nav": 1}]),
            _Result([{"total_cost": Decimal("12.50"), "trade_count": 2}]),
        ]
    )

    with patch(
        "app.api.backtest._require_completed",
        new=AsyncMock(return_value=_completed_run()),
    ):
        payload = await backtest.get_cost_sensitivity(run_id, session=session)

    assert payload["total_cost_base"] == 12.5
    base_row = next(r for r in payload["rows"] if r["cost_multiplier"] == 1.0)
    assert base_row["annual_return"] == 0.1234
    assert isinstance(payload["rows"][2]["sharpe_ratio"], float)


@pytest.mark.asyncio
async def test_live_compare_returns_numeric_backtest_metrics():
    """Live compare phase-0 payload should be JSON numeric, not Decimal objects."""
    run_id = UUID("00000000-0000-0000-0000-000000000001")

    with patch(
        "app.api.backtest._get_run_or_404",
        new=AsyncMock(return_value=_completed_run()),
    ):
        payload = await backtest.get_live_compare(run_id, session=AsyncMock())

    assert payload["backtest"] == {
        "annual_return": 0.1234,
        "sharpe_ratio": 1.2345,
        "max_drawdown": -0.0567,
    }
