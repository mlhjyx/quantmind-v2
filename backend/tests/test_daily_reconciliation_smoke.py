"""iter 167 MVP 4.6 Chunk 3 — daily_reconciliation integration smoke test.

End-to-end exercise of run_reconciliation() in mocked-live mode, verifying both
scheduler_task_log + risk_event_log INSERTs land per Phase J §1.3 wire.

Unit-level helper coverage already exists in test_daily_reconciliation_audit_wire.py
(iter 166, 8 tests for _persist_mismatch_audit). This file covers the orchestration
layer: query_qmt + query_db + mismatch detect + send_alert + persist_audit +
scheduler_task_log INSERT chain.

Mock strategy: full MagicMock conn (no real psycopg2 / no test DB seed needed).
Sibling pattern from test_recon_health_observability.py:265-306 (run_reconciliation
unit tests using MagicMock). 5 test cases @ pytest.mark.smoke for pre-push coverage.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import daily_reconciliation as dr_mod  # noqa: E402


def _build_mock_conn():
    """MagicMock conn with cursor.fetchone returning UUID (for RETURNING id)."""
    cur = MagicMock()
    cur.fetchone.return_value = ("11111111-2222-3333-4444-555555555555",)
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def _collect_inserts(cur) -> dict[str, list]:
    """Group cur.execute calls by INSERT target table for assertion clarity."""
    out: dict[str, list] = {"risk_event_log": [], "scheduler_task_log": [], "other": []}
    for call in cur.execute.call_args_list:
        sql = call.args[0] if call.args else ""
        if "risk_event_log" in sql:
            out["risk_event_log"].append(call)
        elif "scheduler_task_log" in sql:
            out["scheduler_task_log"].append(call)
        else:
            out["other"].append(call)
    return out


@pytest.fixture
def mock_qmt_broker():
    """Patch sys.modules so inline `from engines.broker_qmt import MiniQMTBroker`
    at scripts/daily_reconciliation.py:554 picks up our mock instead of real
    xtquant-dependent broker.
    """
    mock_broker = MagicMock()
    mock_broker.connect.return_value = None
    mock_broker.disconnect.return_value = None
    mock_broker.query_asset.return_value = {
        "total_asset": 1_000_000.0,
        "cash": 100_000.0,
        "market_value": 900_000.0,
    }
    fake_module = MagicMock()
    fake_module.MiniQMTBroker = MagicMock(return_value=mock_broker)

    with patch.dict(sys.modules, {"engines.broker_qmt": fake_module}):
        yield mock_broker


@pytest.fixture
def patched_dependencies(mock_qmt_broker):
    """Patch all run_reconciliation external dependencies for E2E smoke.

    Yields (conn, cur, send_alert_mock) so each test customizes
    qmt/db positions + alert side_effect per scenario.
    """
    from app.config import settings

    conn, cur = _build_mock_conn()
    send_alert_mock = MagicMock()

    with (
        patch.object(settings, "EXECUTION_MODE", "live"),
        patch.object(dr_mod, "get_sync_conn", return_value=conn),
        patch.object(dr_mod, "is_trading_day", return_value=True),
        patch.object(dr_mod, "write_live_snapshot", return_value=900_000.0),
        patch.object(dr_mod, "write_live_performance", return_value=None),
        patch.object(dr_mod, "send_alert", new=send_alert_mock),
    ):
        yield conn, cur, send_alert_mock


def _default_fill_stats():
    return {
        "total_orders": 1,
        "fill_rate": 1.0,
        "partial_fills": 0,
        "rejects": 0,
    }


@pytest.mark.smoke
class TestDailyReconciliationSmoke:
    """Integration smoke: run_reconciliation() end-to-end in mocked-live mode."""

    def test_happy_path_matched_positions_writes_only_scheduler_log(self, patched_dependencies):
        """Matched QMT/DB positions → 0 risk_event_log INSERT, 1 scheduler_task_log."""
        _conn, cur, send_alert_mock = patched_dependencies
        qmt_pos = {"600519": 100}
        db_pos = {"600519": 100}

        with (
            patch.object(dr_mod, "query_qmt_positions", return_value=qmt_pos),
            patch.object(dr_mod, "query_db_positions", return_value=db_pos),
            patch.object(dr_mod, "calc_fill_rate", return_value=_default_fill_stats()),
        ):
            dr_mod.run_reconciliation(date(2026, 5, 27))

        inserts = _collect_inserts(cur)
        assert len(inserts["risk_event_log"]) == 0, (
            f"Expected 0 audit rows for matched positions, got {len(inserts['risk_event_log'])}"
        )
        assert len(inserts["scheduler_task_log"]) == 1
        send_alert_mock.assert_not_called()

    def test_p0_total_mv_breach_inserts_audit_and_scheduler_log(self, patched_dependencies):
        """Total股数 diff > 5% (TOTAL_MV_DIFF_THRESHOLD) → severity='p0' audit + send_alert P0."""
        _conn, cur, send_alert_mock = patched_dependencies
        # QMT total 100股, DB total 700股 → total_diff = 600/100 = 6.0 > 0.05.
        qmt_pos = {"600519": 100}
        db_pos = {"600519": 200, "000001": 500}

        with (
            patch.object(dr_mod, "query_qmt_positions", return_value=qmt_pos),
            patch.object(dr_mod, "query_db_positions", return_value=db_pos),
            patch.object(dr_mod, "calc_fill_rate", return_value=_default_fill_stats()),
        ):
            dr_mod.run_reconciliation(date(2026, 5, 27))

        inserts = _collect_inserts(cur)
        assert len(inserts["risk_event_log"]) == 1
        assert len(inserts["scheduler_task_log"]) == 1

        params = inserts["risk_event_log"][0].args[1]
        assert params[3] == "p0", f"Expected severity='p0' (total_mv breach), got {params[3]!r}"
        assert params[11] == "P0"
        assert params[8] == "ALERT_FIRED"

        send_alert_mock.assert_called_once()
        assert send_alert_mock.call_args.args[1] == "P0"

    def test_p1_significant_single_stock_mismatch_inserts_audit(self, patched_dependencies):
        """Single-stock diff > 1% but total < 5% → severity='p1' audit + send_alert P1."""
        _conn, cur, send_alert_mock = patched_dependencies
        # QMT total 200股, DB total 195股 → total_diff = 5/200 = 0.025 < 0.05.
        # 600519: 100 vs 95 → diff_pct = 5/100 = 0.05 > 0.01 (significant).
        qmt_pos = {"600519": 100, "000001": 100}
        db_pos = {"600519": 95, "000001": 100}

        with (
            patch.object(dr_mod, "query_qmt_positions", return_value=qmt_pos),
            patch.object(dr_mod, "query_db_positions", return_value=db_pos),
            patch.object(dr_mod, "calc_fill_rate", return_value=_default_fill_stats()),
        ):
            dr_mod.run_reconciliation(date(2026, 5, 27))

        inserts = _collect_inserts(cur)
        assert len(inserts["risk_event_log"]) == 1
        assert len(inserts["scheduler_task_log"]) == 1

        params = inserts["risk_event_log"][0].args[1]
        assert params[3] == "p1"
        assert params[11] == "P1"

        send_alert_mock.assert_called_once()
        assert send_alert_mock.call_args.args[1] == "P1"

    def test_audit_only_outcome_when_alert_dispatch_fails(self, patched_dependencies):
        """AlertDispatchError → action_taken='AUDIT_ONLY' + alert_error in context_snapshot,
        scheduler_task_log still written (main flow uninterrupted per batch 3.5 P1.1 contract)."""
        from qm_platform.observability import AlertDispatchError

        _conn, cur, send_alert_mock = patched_dependencies
        send_alert_mock.side_effect = AlertDispatchError("DingTalk 502 Bad Gateway")

        qmt_pos = {"600519": 100}
        db_pos = {"600519": 200, "000001": 500}  # P0 breach

        with (
            patch.object(dr_mod, "query_qmt_positions", return_value=qmt_pos),
            patch.object(dr_mod, "query_db_positions", return_value=db_pos),
            patch.object(dr_mod, "calc_fill_rate", return_value=_default_fill_stats()),
        ):
            dr_mod.run_reconciliation(date(2026, 5, 27))

        inserts = _collect_inserts(cur)
        assert len(inserts["risk_event_log"]) == 1
        assert len(inserts["scheduler_task_log"]) == 1  # main flow continues

        params = inserts["risk_event_log"][0].args[1]
        assert params[8] == "AUDIT_ONLY", (
            f"Expected action_taken='AUDIT_ONLY' on dispatch error, got {params[8]!r}"
        )
        # alert_error string carried in context_snapshot JSON
        ctx_json = params[7]
        ctx = ctx_json.adapted if hasattr(ctx_json, "adapted") else ctx_json
        assert "502" in ctx.get("alert_error", "")

    def test_audit_insert_failure_does_not_block_scheduler_log(self, patched_dependencies):
        """_persist_mismatch_audit raise → scheduler_task_log still written (铁律 33 silent_ok)."""
        import psycopg2

        _conn, cur, send_alert_mock = patched_dependencies
        qmt_pos = {"600519": 100, "000001": 100}
        db_pos = {"600519": 95, "000001": 100}  # P1 mismatch

        with (
            patch.object(dr_mod, "query_qmt_positions", return_value=qmt_pos),
            patch.object(dr_mod, "query_db_positions", return_value=db_pos),
            patch.object(dr_mod, "calc_fill_rate", return_value=_default_fill_stats()),
            patch.object(
                dr_mod,
                "_persist_mismatch_audit",
                side_effect=psycopg2.Error("audit boom"),
            ),
        ):
            # Should NOT raise — exception swallowed in silent_ok try/except (铁律 33)
            dr_mod.run_reconciliation(date(2026, 5, 27))

        inserts = _collect_inserts(cur)
        # _persist_mismatch_audit was called (raised); scheduler_task_log still happened
        assert len(inserts["scheduler_task_log"]) == 1, (
            "scheduler_task_log MUST still write when audit INSERT fails (铁律 33 silent_ok)"
        )
        send_alert_mock.assert_called_once()
