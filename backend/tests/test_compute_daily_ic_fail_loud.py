"""iter 181 MVP 4.7 follow-up — compute_daily_ic.py Option A fail-loud tests.

TDD: tests written FIRST against not-yet-implemented helpers:
- _verify_ingest_result(result, factor_count) — Layer 4 silent failure regression guard
- _insert_scheduler_task_log(conn, status, result, error_message) — monitoring sediment

Expected fail: AttributeError on missing helper attributes.

iter 179 LL-211 4-layer diagnostic finding: compute_daily_ic.py log records
"upserted=N>0 valid=N rejected=0" (Layer 3 ✓ application executed) but DB
factor_ic_history max_td stalled (Layer 4 ✗ side-effect surface absent).
Root cause hypothesis: DataPipeline.ingest() returns success-shaped result
without raising on FK constraint / silent rollback.

Option A fix (sibling iter 165 daily_reconciliation env_ssot pattern):
- Post-ingest sanity: if valid_rows > 0 and upserted_rows == 0 → raise
  RuntimeError (catches silent rollback / FK constraint failure mid-batch)
- scheduler_task_log INSERT on success + on exception ('failed' status)
  for monitoring consistency with sibling schtask scripts
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import compute_daily_ic as cdi  # noqa: E402


def _make_ingest_result(*, total=0, valid=0, upserted=0, rejected=0, reasons=None):
    """Build IngestResult-like mock matching compute_and_ingest L376-388 usage."""
    r = MagicMock()
    r.total_rows = total
    r.valid_rows = valid
    r.upserted_rows = upserted
    r.rejected_rows = rejected
    r.reject_reasons = reasons or {}
    r.null_ratio_warnings = {}
    return r


# ─────────────────────────── _verify_ingest_result ───────────────────────────


def test_verify_ingest_result_raises_on_layer_4_silent_failure():
    """iter 181 Option A regression guard for iter 179 LL-211 Layer 4 silent failure:
    valid_rows > 0 but upserted_rows = 0 → must raise (not silent)."""
    result = _make_ingest_result(total=52, valid=52, upserted=0, rejected=0)

    with pytest.raises(RuntimeError) as exc_info:
        cdi._verify_ingest_result(result, factor_count=4)

    err_msg = str(exc_info.value)
    assert "Layer 4 silent failure" in err_msg or "upserted_rows=0" in err_msg, (
        f"Sanity check error must reference Layer 4 silent failure pattern; got: {err_msg!r}"
    )
    # Error message should include diagnostic context
    assert "valid_rows=52" in err_msg
    assert "factor_count=4" in err_msg


def test_verify_ingest_result_no_raise_on_happy_path():
    """Happy path: valid_rows=52, upserted_rows=52 → no exception."""
    result = _make_ingest_result(total=52, valid=52, upserted=52, rejected=0)
    # Should NOT raise
    cdi._verify_ingest_result(result, factor_count=4)


def test_verify_ingest_result_no_raise_when_valid_zero():
    """Edge case: valid_rows=0 (all rejected) → sanity check should NOT fire.

    If 0 valid input rows, expecting 0 upserts is correct — NOT a silent failure.
    """
    result = _make_ingest_result(total=10, valid=0, upserted=0, rejected=10)
    cdi._verify_ingest_result(result, factor_count=2)


def test_verify_ingest_result_no_raise_on_partial_reject():
    """valid_rows=50, upserted_rows=40, rejected_rows=10 → partial reject, no raise.

    Only the 100% silent failure case (valid > 0 + upserted == 0) raises.
    """
    result = _make_ingest_result(
        total=50, valid=50, upserted=40, rejected=10, reasons={"missing_factor": 10}
    )
    cdi._verify_ingest_result(result, factor_count=5)


# ─────────────────────────── _insert_scheduler_task_log ───────────────────────────


def test_insert_scheduler_task_log_writes_daily_ic_row():
    """iter 181 Option A: helper writes 'daily_ic' row to scheduler_task_log."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    cdi._insert_scheduler_task_log(
        conn, status="success", result={"processed_factors": 4, "total_rows": 52}
    )

    cur.execute.assert_called_once()
    sql, params = cur.execute.call_args.args
    assert "INSERT INTO scheduler_task_log" in sql
    assert "daily_ic" in sql
    # params: (status, error_message, result_json)
    assert params[0] == "success"
    assert params[1] is None
    assert "processed_factors" in params[2]


def test_insert_scheduler_task_log_failed_status_carries_error_message():
    """'failed' status row carries error_message for ops triage."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    cdi._insert_scheduler_task_log(
        conn, status="failed", error_message="ingest silent failure: 0 rows landed"
    )

    cur.execute.assert_called_once()
    sql, params = cur.execute.call_args.args
    assert params[0] == "failed"
    assert "ingest silent failure" in params[1]
    assert params[2] is None  # result_json None on failure


def test_insert_scheduler_task_log_truncates_long_error_message():
    """error_message > 500 chars should be truncated to 500 (sibling daily_reconciliation pattern)."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    long_err = "x" * 1000

    cdi._insert_scheduler_task_log(conn, status="failed", error_message=long_err)

    params = cur.execute.call_args.args[1]
    assert len(params[1]) <= 500, f"error_message must be truncated to ≤500, got len={len(params[1])}"
