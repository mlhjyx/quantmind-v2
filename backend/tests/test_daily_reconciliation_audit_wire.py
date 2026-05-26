"""iter 166 MVP 4.6 Chunk 2 — daily_reconciliation risk_event_log audit wire tests.

Tests _persist_mismatch_audit() helper that inserts a risk_event_log row when
QMT vs DB position mismatch is detected. Per Phase J §1.3 / sibling pattern
from execution_plan_persistence.py:102-127 (MVP 4.5 Chunk 5 canonical
12-column INSERT).

Design contract:
- One risk_event_log row per reconciliation call WITH mismatches (no insert
  when fully matched).
- severity='p0' when total_diff > TOTAL_MV_DIFF_THRESHOLD (5%), else 'p1' on
  significant single-stock mismatches (>1%).
- action_taken='ALERT_FIRED' when DingTalk dispatch succeeded, 'AUDIT_ONLY'
  when AlertDispatchError caught.
- context_snapshot JSON carries mismatches list (capped at 10) + total_diff_pct
  + fill_stats.
- caller owns transaction per 铁律 32 (helper does NOT commit).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import daily_reconciliation as dr_mod  # noqa: E402


def _make_mock_conn(returning_uuid: str = "11111111-2222-3333-4444-555555555555"):
    """Build a mock conn/cursor pair where cur.execute records args and
    cur.fetchone returns the supplied UUID.
    """
    cur = MagicMock()
    cur.fetchone.return_value = (returning_uuid,)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


@pytest.fixture
def recon_date():
    return date(2026, 5, 27)


@pytest.fixture
def sample_mismatches():
    return [
        {"code": "600519", "qmt": 100, "db": 200, "diff_pct": 0.50},
        {"code": "000001", "qmt": 0, "db": 100, "diff_pct": 1.00},
    ]


@pytest.fixture
def sample_fill_stats():
    return {
        "total_orders": 5,
        "fill_rate": 0.95,
        "partial_fills": 1,
        "rejects": 0,
    }


def test_persist_mismatch_audit_p0_severity_inserts_correct_row(
    recon_date, sample_mismatches, sample_fill_stats
):
    """severity='p0' (total_mv breach) inserts row with priority='P0'."""
    conn, cur = _make_mock_conn()

    event_id = dr_mod._persist_mismatch_audit(
        conn=conn,
        recon_date=recon_date,
        severity="p0",
        significant_mismatches=sample_mismatches,
        total_diff_pct=0.08,  # 8% breach
        fill_stats=sample_fill_stats,
        alert_outcome="ALERT_FIRED",
        alert_error=None,
    )

    assert event_id == "11111111-2222-3333-4444-555555555555"
    cur.execute.assert_called_once()
    sql, params = cur.execute.call_args.args
    assert "INSERT INTO risk_event_log" in sql
    assert "RETURNING id" in sql
    # 12 params (canonical sibling shape)
    assert len(params) == 12
    # Param positions per execution_plan_persistence.py:104-127:
    # 0:strategy_id, 1:execution_mode, 2:rule_id, 3:severity, 4:code, 5:shares,
    # 6:reason, 7:context_snapshot, 8:action_taken, 9:action_result,
    # 10:cadence, 11:priority
    assert params[2] == "daily_reconciliation"
    assert params[3] == "p0"
    assert params[8] == "ALERT_FIRED"
    assert params[10] == "daily"  # canonical per migrations/2026_05_11_risk_event_log_realtime.sql:6
    assert params[11] == "P0"


def test_persist_mismatch_audit_p1_severity_inserts_correct_row(
    recon_date, sample_mismatches, sample_fill_stats
):
    """severity='p1' (significant single-stock) inserts row with priority='P1'."""
    conn, cur = _make_mock_conn()

    dr_mod._persist_mismatch_audit(
        conn=conn,
        recon_date=recon_date,
        severity="p1",
        significant_mismatches=sample_mismatches,
        total_diff_pct=0.02,  # under 5% but significant single-stock
        fill_stats=sample_fill_stats,
        alert_outcome="ALERT_FIRED",
        alert_error=None,
    )

    cur.execute.assert_called_once()
    params = cur.execute.call_args.args[1]
    assert params[3] == "p1"
    assert params[11] == "P1"


def test_persist_mismatch_audit_context_snapshot_includes_mismatches(
    recon_date, sample_mismatches, sample_fill_stats
):
    """context_snapshot JSON must carry mismatches list + total_diff_pct + fill_stats."""
    conn, cur = _make_mock_conn()

    dr_mod._persist_mismatch_audit(
        conn=conn,
        recon_date=recon_date,
        severity="p1",
        significant_mismatches=sample_mismatches,
        total_diff_pct=0.03,
        fill_stats=sample_fill_stats,
        alert_outcome="ALERT_FIRED",
        alert_error=None,
    )

    params = cur.execute.call_args.args[1]
    ctx_json = params[7]
    # psycopg2.extras.Json wraps dict; access via .adapted
    ctx_dict = ctx_json.adapted if hasattr(ctx_json, "adapted") else ctx_json
    assert ctx_dict["trade_date"] == "2026-05-27"
    assert ctx_dict["mismatches"] == sample_mismatches
    assert ctx_dict["total_diff_pct"] == 0.03
    assert ctx_dict["fill_stats"] == sample_fill_stats


def test_persist_mismatch_audit_alert_only_outcome_carries_error(
    recon_date, sample_mismatches, sample_fill_stats
):
    """action_taken='AUDIT_ONLY' must include alert_error string in context_snapshot."""
    conn, cur = _make_mock_conn()

    dr_mod._persist_mismatch_audit(
        conn=conn,
        recon_date=recon_date,
        severity="p1",
        significant_mismatches=sample_mismatches,
        total_diff_pct=0.02,
        fill_stats=sample_fill_stats,
        alert_outcome="AUDIT_ONLY",
        alert_error="DingTalk webhook 502 Bad Gateway",
    )

    params = cur.execute.call_args.args[1]
    assert params[8] == "AUDIT_ONLY"
    ctx_json = params[7]
    ctx_dict = ctx_json.adapted if hasattr(ctx_json, "adapted") else ctx_json
    assert ctx_dict["alert_error"] == "DingTalk webhook 502 Bad Gateway"


def test_persist_mismatch_audit_caps_mismatches_to_10(
    recon_date, sample_fill_stats
):
    """context_snapshot.mismatches truncated to 10 entries (防 JSON 巨大)."""
    big_mismatches = [
        {"code": f"60050{i:04d}", "qmt": 100 * i, "db": 50 * i, "diff_pct": 0.5}
        for i in range(25)
    ]
    conn, cur = _make_mock_conn()

    dr_mod._persist_mismatch_audit(
        conn=conn,
        recon_date=recon_date,
        severity="p1",
        significant_mismatches=big_mismatches,
        total_diff_pct=0.04,
        fill_stats=sample_fill_stats,
        alert_outcome="ALERT_FIRED",
        alert_error=None,
    )

    params = cur.execute.call_args.args[1]
    ctx_json = params[7]
    ctx_dict = ctx_json.adapted if hasattr(ctx_json, "adapted") else ctx_json
    assert len(ctx_dict["mismatches"]) == 10
    # action_result still carries total mismatch count
    action_json = params[9]
    action_dict = action_json.adapted if hasattr(action_json, "adapted") else action_json
    assert action_dict["mismatch_count"] == 25


def test_persist_mismatch_audit_representative_code_is_largest_diff(
    recon_date, sample_fill_stats
):
    """`code` column populated from largest diff_pct mismatch (representative for indexed lookup)."""
    mismatches = [
        {"code": "600519", "qmt": 100, "db": 110, "diff_pct": 0.09},
        {"code": "000001", "qmt": 50, "db": 100, "diff_pct": 0.50},  # largest
        {"code": "300999", "qmt": 200, "db": 210, "diff_pct": 0.048},
    ]
    conn, cur = _make_mock_conn()

    dr_mod._persist_mismatch_audit(
        conn=conn,
        recon_date=recon_date,
        severity="p1",
        significant_mismatches=mismatches,
        total_diff_pct=0.04,
        fill_stats=sample_fill_stats,
        alert_outcome="ALERT_FIRED",
        alert_error=None,
    )

    params = cur.execute.call_args.args[1]
    # code (params[4]) should be the largest diff_pct code
    assert params[4] == "000001"
    # shares (params[5]) = qmt - db of the rep
    assert params[5] == -50


def test_persist_mismatch_audit_does_not_commit(
    recon_date, sample_mismatches, sample_fill_stats
):
    """铁律 32: helper does not call conn.commit() — caller owns transaction."""
    conn, _cur = _make_mock_conn()

    dr_mod._persist_mismatch_audit(
        conn=conn,
        recon_date=recon_date,
        severity="p1",
        significant_mismatches=sample_mismatches,
        total_diff_pct=0.02,
        fill_stats=sample_fill_stats,
        alert_outcome="ALERT_FIRED",
        alert_error=None,
    )

    conn.commit.assert_not_called()


def test_persist_mismatch_audit_reason_includes_severity_and_counts(
    recon_date, sample_mismatches, sample_fill_stats
):
    """reason text must include severity label + mismatch count + total_diff."""
    conn, cur = _make_mock_conn()

    dr_mod._persist_mismatch_audit(
        conn=conn,
        recon_date=recon_date,
        severity="p0",
        significant_mismatches=sample_mismatches,
        total_diff_pct=0.08,
        fill_stats=sample_fill_stats,
        alert_outcome="ALERT_FIRED",
        alert_error=None,
    )

    reason = cur.execute.call_args.args[1][6]
    assert "P0" in reason
    assert "2" in reason  # 2 mismatches
    assert "8" in reason  # 8% total diff
