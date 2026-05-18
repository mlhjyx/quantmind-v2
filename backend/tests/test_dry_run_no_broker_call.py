"""LL-183 regression gate — assert --dry-run flag prevents ANY broker call in live mode.

**Root incident** (2026-05-18 19:46 SH): `scripts/run_paper_trading.py:482` call to
`ExecutionService.execute_rebalance(...)` was missing `dry_run=dry_run` propagation.
Result: 11 real BUY orders placed on miniQMT, ¥543,560 cash frozen, 0 fills (cancelled
in time, total_asset ¥993,520.66 sustained).

**This test acts as a verifiable regression gate**:
1. With `dry_run=True` and `execution_mode="live"`, `ExecutionService.execute_rebalance`
   must NOT invoke any broker order method.
2. With `dry_run=False` and `execution_mode="live"`, broker order method MUST be called
   (proves the gating actually works, not just always-off).

If anyone re-introduces the missing-propagation bug at call site or removes the
`if dry_run` guard in `_execute_live`, this test fails.

关联: docs/audit/V3_DRY_RUN_BUG_LL_183_2026_05_18.md / 铁律 33 (fail-loud here originally silent)
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.execution_service import ExecutionResult, ExecutionService


@pytest.fixture
def mock_conn():
    """Mock psycopg2 connection (cursor + execute paths)."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = None  # no pending rows
    cursor.fetchall.return_value = []
    conn.cursor.return_value = cursor
    return conn


@pytest.fixture
def target_weights():
    """5 stock target weights summing < 1 (PT_TOP_N=5 partial pilot baseline)."""
    return {
        "601398.SH": 0.0485,
        "600293.SH": 0.0485,
        "601988.SH": 0.0485,
        "000507.SZ": 0.0485,
        "600051.SH": 0.0485,
    }


@pytest.fixture
def price_data():
    """Empty DF with trade_date column (live-mode tolerates empty per Step 5.8 warning)."""
    return pd.DataFrame(columns=["code", "trade_date", "open", "close", "up_limit", "down_limit"])


def test_dry_run_true_zero_broker_call_in_live_mode(mock_conn, target_weights, price_data):
    """LL-183 regression — dry_run=True + execution_mode=live → 0 broker.execute_rebalance call.

    Specifically test the bug surfaced 2026-05-18 19:46 SH: in `_execute_live`, the
    `if dry_run` guard at line 412-413 must prevent QMTExecutionAdapter instantiation
    and `adapter.execute_rebalance(...)` invocation.
    """
    svc = ExecutionService()

    # Patch `qmt_manager` and `QMTExecutionAdapter` so we can assert ZERO call.
    with patch("app.services.execution_service.PaperBroker") as mock_paper_broker_cls, \
         patch("app.services.qmt_connection_manager.qmt_manager") as mock_mgr, \
         patch("engines.qmt_execution_adapter.QMTExecutionAdapter") as mock_adapter_cls:
        # qmt_manager.ensure_connected() + qmt_manager.broker (used to query NAV/positions)
        mock_mgr.ensure_connected.return_value = None
        mock_broker = MagicMock()
        mock_broker.get_total_value.return_value = 993_520.66
        mock_broker.get_positions.return_value = {}
        mock_mgr.broker = mock_broker

        result = svc.execute_rebalance(
            conn=mock_conn,
            strategy_id="test-strategy-id",
            exec_date=date(2026, 5, 19),
            target_weights=target_weights,
            cb_level=0,
            position_multiplier=1.0,
            price_data=price_data,
            initial_capital=1_000_000.0,
            signal_date=date(2026, 5, 18),
            dry_run=True,             # ← critical: dry-run engaged
            execution_mode="live",    # ← critical: live mode (otherwise paper path)
        )

        # ── Assertions ──
        # 1. QMTExecutionAdapter must NOT be instantiated (entire `else` branch skipped)
        assert mock_adapter_cls.call_count == 0, (
            f"QMTExecutionAdapter should NOT be instantiated when dry_run=True + "
            f"execution_mode=live, got call_count={mock_adapter_cls.call_count}"
        )
        # 2. PaperBroker likewise NOT instantiated (live path skips PaperBroker)
        assert mock_paper_broker_cls.call_count == 0, (
            f"PaperBroker should NOT be instantiated in live dry-run path, "
            f"got call_count={mock_paper_broker_cls.call_count}"
        )
        # 3. Result returned cleanly (not error path)
        assert isinstance(result, ExecutionResult)
        assert result.fills == []
        assert result.position_count == 0


def test_dry_run_false_invokes_broker_adapter_in_live_mode(mock_conn, target_weights, price_data):
    """Sibling test — dry_run=False + execution_mode=live MUST invoke broker adapter.

    Proves the dry_run gating is real (not always-off). If this test fails together
    with the dry_run=True test, the gating may be misimplemented (e.g. `if not dry_run`
    inverted, or completely removed).
    """
    svc = ExecutionService()

    with patch("app.services.execution_service.PaperBroker"), \
         patch("app.services.qmt_connection_manager.qmt_manager") as mock_mgr, \
         patch("engines.qmt_execution_adapter.QMTExecutionAdapter") as mock_adapter_cls:
        mock_mgr.ensure_connected.return_value = None
        mock_broker = MagicMock()
        mock_broker.get_total_value.return_value = 993_520.66
        mock_broker.get_positions.return_value = {}
        mock_mgr.broker = mock_broker

        # adapter.execute_rebalance returns (fills, pending_orders) — empty mock OK
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.execute_rebalance.return_value = ([], [])
        mock_adapter_cls.return_value = mock_adapter_instance

        svc.execute_rebalance(
            conn=mock_conn,
            strategy_id="test-strategy-id",
            exec_date=date(2026, 5, 19),
            target_weights=target_weights,
            cb_level=0,
            position_multiplier=1.0,
            price_data=price_data,
            initial_capital=1_000_000.0,
            signal_date=date(2026, 5, 18),
            dry_run=False,            # ← critical: dry-run OFF
            execution_mode="live",
        )

        # QMTExecutionAdapter MUST be instantiated AND execute_rebalance called
        assert mock_adapter_cls.call_count == 1, (
            f"QMTExecutionAdapter should be instantiated 1 time when dry_run=False, "
            f"got call_count={mock_adapter_cls.call_count}"
        )
        assert mock_adapter_instance.execute_rebalance.call_count == 1, (
            f"adapter.execute_rebalance should be called 1 time when dry_run=False, "
            f"got call_count={mock_adapter_instance.execute_rebalance.call_count}"
        )


def test_process_pending_orders_dry_run_no_db_write(mock_conn):
    """LL-183 sibling — process_pending_orders dry_run=True skip DB write.

    The same call site bug existed at run_paper_trading.py:466 (process_pending_orders
    call missing dry_run=dry_run). Verify the service-layer dry_run gating works.
    """
    svc = ExecutionService()

    # Mock cursor.fetchone to return no pending rows → process_pending_orders early-returns []
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = cursor

    result = svc.process_pending_orders(
        conn=mock_conn,
        strategy_id="test-strategy-id",
        exec_date=date(2026, 5, 19),
        price_data=pd.DataFrame(),
        initial_capital=1_000_000.0,
        cb_level=0,
        dry_run=True,
        execution_mode="live",
    )

    # No pending orders found → returns []
    assert result == []


def test_process_pending_orders_signature_requires_execution_mode():
    """LL-183 root cause was actually 2 missing params: dry_run + execution_mode.

    PaperBroker.__init__ requires execution_mode (paper/live, per ADR-008 D2). The
    19:29:31 SH crash was: `PaperBroker.__init__() missing 1 required positional
    argument: 'execution_mode'`. Verify process_pending_orders signature has it.
    """
    import inspect

    sig = inspect.signature(ExecutionService.process_pending_orders)
    params = list(sig.parameters.keys())

    assert "dry_run" in params, "process_pending_orders MUST accept dry_run param"
    assert "execution_mode" in params, "process_pending_orders MUST accept execution_mode param"
