"""Unit + integration tests for report_tasks (Sprint 1.24 closure — iter 30).

Coverage:
  - generate_performance_report task body (mock DB cursor; assert JSON shape)
  - generate_performance_report empty-data path (None/empty rows)
  - generate_performance_report input validation (empty sid / bad mode)
  - latest_report_path resolver (mtime-newest match + None on miss)
  - _atomic_write_json (tmp-rename atomicity + cleanup-on-failure)
  - POST /api/reports/generate dispatches real Celery task_id (mock .delay)
  - GET /api/reports/{sid}/latest reads artifact correctly (404 / 200 / 500)

Conventions:
  - sustained mock-based pattern from iter 11 (correlation-prune) + iter 12
    (pipeline-pause) — no live DB / no live Celery worker required.
  - reports/ dir uses tmp_path fixture for isolation from production reports.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_pg_rows():
    """Sample DB rows for happy-path tests (60d window, latest, 3 trades)."""
    # rolling_stats source: DESC by trade_date — index 0 is newest.
    rolling_rows = [
        (1.05, 0.005),
        (1.04, 0.003),
        (1.037, -0.002),
        (1.039, 0.004),
        (1.035, 0.001),
    ]
    latest_row = (
        date(2026, 4, 28),  # trade_date
        1.05,  # nav
        0.005,  # daily_return
        0.05,  # cumulative_return
        -0.02,  # drawdown
        0.4,  # cash_ratio
        400_000.0,  # cash
        15,  # position_count
        0.15,  # turnover
        1.03,  # benchmark_nav
    )
    trade_rows = [
        (date(2026, 4, 28), "000001.SZ", "buy", 100, 15.5, 15.4, None),
        (date(2026, 4, 27), "600000.SH", "sell", 200, 8.7, 8.75, None),
        (date(2026, 4, 26), "000333.SZ", "buy", 300, 65.2, 65.0, "test_reject"),
    ]
    return rolling_rows, latest_row, trade_rows


@pytest.fixture
def isolated_reports_dir(tmp_path, monkeypatch):
    """Patch REPORTS_DIR to a tmp dir so tests don't pollute production reports/."""
    from app.tasks import report_tasks

    monkeypatch.setattr(report_tasks, "REPORTS_DIR", tmp_path)
    return tmp_path


# ── generate_performance_report task body ──────────────────────────────────


def test_generate_report_happy_path(fake_pg_rows, isolated_reports_dir):
    """Happy path: 60d rolling + latest_nav + 3 trades → JSON written, return dict shape."""
    from app.tasks.report_tasks import generate_performance_report

    rolling_rows, latest_row, trade_rows = fake_pg_rows
    mock_cur = MagicMock()
    # Match the 3 fetch calls in task body: rolling_stats (fetchall), latest_nav (fetchone), trades (fetchall)
    mock_cur.fetchall.side_effect = [rolling_rows, trade_rows]
    mock_cur.fetchone.return_value = latest_row
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch("app.tasks.report_tasks.get_sync_conn", return_value=mock_conn):
        result = generate_performance_report.run("test-sid-123", "paper")

    # Return dict shape
    assert result["ok"] is True
    assert result["strategy_id"] == "test-sid-123"
    assert result["execution_mode"] == "paper"
    assert result["data_available"] is True
    assert result["summary"]["lookback_days"] == 5
    assert "sharpe" in result["summary"]
    assert "mdd" in result["summary"]

    # File written + content shape
    artifact = Path(result["report_path"])
    assert artifact.exists()
    with open(artifact, encoding="utf-8") as f:
        payload = json.load(f)

    assert payload["schema_version"] == "1.0"
    assert payload["strategy_id"] == "test-sid-123"
    assert payload["execution_mode"] == "paper"
    assert payload["data_available"] is True
    assert payload["trades_count"] == 3
    assert len(payload["recent_trades"]) == 3
    assert payload["recent_trades"][0]["code"] == "000001.SZ"
    assert payload["latest_nav"]["position_count"] == 15
    assert payload["summary"]["sharpe"] is not None

    # Connection lifecycle: commit + close called (released-snapshot pattern)
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()
    mock_conn.rollback.assert_not_called()


def test_generate_report_empty_data(isolated_reports_dir):
    """0 rows in performance_series + trade_log → JSON written with data_available=False."""
    from app.tasks.report_tasks import generate_performance_report

    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [[], []]  # rolling empty, trades empty
    mock_cur.fetchone.return_value = None  # latest empty
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch("app.tasks.report_tasks.get_sync_conn", return_value=mock_conn):
        result = generate_performance_report.run("empty-sid", "paper")

    assert result["ok"] is True
    assert result["data_available"] is False
    assert result["summary"] is None

    artifact = Path(result["report_path"])
    with open(artifact, encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["data_available"] is False
    assert payload["summary"] is None
    assert payload["latest_nav"] is None
    assert payload["recent_trades"] == []
    assert payload["trades_count"] == 0


def test_generate_report_validates_empty_sid():
    """Empty strategy_id → ValueError (caller-side default expected)."""
    from app.tasks.report_tasks import generate_performance_report

    with pytest.raises(ValueError, match="strategy_id required"):
        generate_performance_report.run("", "paper")


def test_generate_report_validates_bad_mode():
    """Invalid execution_mode → ValueError (反 silent ingest of bad enum)."""
    from app.tasks.report_tasks import generate_performance_report

    with pytest.raises(ValueError, match="execution_mode must be"):
        generate_performance_report.run("sid", "shadow")


def test_generate_report_db_error_propagates(isolated_reports_dir):
    """DB error during fetch → rollback + close called + exception propagates (Celery retry)."""
    from app.tasks.report_tasks import generate_performance_report

    mock_conn = MagicMock()
    mock_conn.cursor.side_effect = RuntimeError("simulated PG outage")

    with patch("app.tasks.report_tasks.get_sync_conn", return_value=mock_conn):
        with pytest.raises(RuntimeError, match="simulated PG outage"):
            generate_performance_report.run("sid", "paper")

    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()
    mock_conn.commit.assert_not_called()


# ── latest_report_path resolver ─────────────────────────────────────────────


def test_latest_report_path_none_on_empty(isolated_reports_dir):
    """0 artifacts in dir → returns None."""
    from app.tasks.report_tasks import latest_report_path

    assert latest_report_path("sid-x", "paper") is None


def test_latest_report_path_returns_mtime_newest(isolated_reports_dir):
    """Multiple matching artifacts → returns mtime-newest."""
    import os
    import time

    from app.tasks.report_tasks import latest_report_path

    older = isolated_reports_dir / "sid-y_2026-04-26_paper.json"
    newer = isolated_reports_dir / "sid-y_2026-04-28_paper.json"
    older.write_text('{"x": 1}')
    time.sleep(0.05)  # ensure distinct mtime granularity on Windows
    newer.write_text('{"x": 2}')
    # Force mtime ordering on filesystems where write order != mtime
    old_time = time.time() - 1000
    os.utime(older, (old_time, old_time))

    result = latest_report_path("sid-y", "paper")
    assert result == newer


def test_latest_report_path_filters_by_mode(isolated_reports_dir):
    """Only matching execution_mode artifacts considered."""
    from app.tasks.report_tasks import latest_report_path

    (isolated_reports_dir / "sid-z_2026-04-28_paper.json").write_text('{"m": "p"}')
    (isolated_reports_dir / "sid-z_2026-04-28_live.json").write_text('{"m": "l"}')

    paper_result = latest_report_path("sid-z", "paper")
    live_result = latest_report_path("sid-z", "live")

    assert paper_result is not None
    assert paper_result.name.endswith("_paper.json")
    assert live_result is not None
    assert live_result.name.endswith("_live.json")


def test_latest_report_path_filters_by_sid(isolated_reports_dir):
    """Different strategy_id artifacts excluded."""
    from app.tasks.report_tasks import latest_report_path

    (isolated_reports_dir / "sid-A_2026-04-28_paper.json").write_text('{"s": "A"}')
    (isolated_reports_dir / "sid-B_2026-04-28_paper.json").write_text('{"s": "B"}')

    result = latest_report_path("sid-A", "paper")
    assert result is not None
    assert "sid-A" in result.name
    assert "sid-B" not in result.name


# ── _atomic_write_json ──────────────────────────────────────────────────────


def test_atomic_write_json_writes_complete_file(tmp_path):
    """Successful write produces a complete JSON file at dest."""
    from app.tasks.report_tasks import _atomic_write_json

    dest = tmp_path / "out.json"
    payload = {"a": 1, "b": [1, 2, 3], "c": "中文 OK"}
    _atomic_write_json(dest, payload)

    assert dest.exists()
    with open(dest, encoding="utf-8") as f:
        assert json.load(f) == payload
    # No tmp residue
    assert not any(p.name.startswith(".out.json.") for p in tmp_path.iterdir())


def test_atomic_write_json_cleans_tmp_on_serialize_failure(tmp_path):
    """Unserializable payload raises but cleans up tmp file."""
    from app.tasks.report_tasks import _atomic_write_json

    dest = tmp_path / "out.json"
    bad_payload = {"obj": object()}  # not JSON-serializable

    # json.dump's default=str will stringify object() to its repr, NOT raise.
    # Force a failure by using a custom non-stringifiable object via a Mock raising on str.
    class _Unserializable:
        def __str__(self):
            raise TypeError("forced for test")

        def __repr__(self):
            raise TypeError("forced for test")

    bad_payload = {"obj": _Unserializable()}
    with pytest.raises(TypeError):
        _atomic_write_json(dest, bad_payload)

    # dest not created on failure
    assert not dest.exists()
    # tmp cleaned up
    leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".out.json.")]
    assert leftover == [], f"tmp residue not cleaned: {leftover}"


# ── API endpoint integration (mocked Celery / mocked filesystem) ────────────


def test_post_generate_returns_real_task_id():
    """POST /generate dispatches Celery task + returns AsyncResult.id (not random uuid)."""
    from fastapi.testclient import TestClient

    from app.main import app

    fake_async_result = MagicMock()
    fake_async_result.id = "celery-task-id-abc-123"

    with patch(
        "app.api.report.generate_performance_report.delay",
        return_value=fake_async_result,
    ) as mock_delay:
        client = TestClient(app)
        resp = client.post(
            "/api/reports/generate",
            params={"strategy_id": "sid-foo", "execution_mode": "paper"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "celery-task-id-abc-123"
    assert body["status"] == "dispatched"
    assert body["strategy_id"] == "sid-foo"
    mock_delay.assert_called_once_with("sid-foo", "paper")


def test_post_generate_rejects_bad_mode():
    """POST /generate with execution_mode != paper/live → 400."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/reports/generate",
        params={"strategy_id": "sid-foo", "execution_mode": "shadow"},
    )
    assert resp.status_code == 400
    assert "execution_mode must be" in resp.json()["detail"]


def test_get_latest_404_when_no_artifact(isolated_reports_dir):
    """GET /{sid}/latest with 0 matching artifacts → 404."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/reports/nonexistent-sid/latest")
    assert resp.status_code == 404
    assert "no report artifact found" in resp.json()["detail"]


def test_get_latest_200_returns_payload(isolated_reports_dir):
    """GET /{sid}/latest with a matching artifact → 200 + payload + _artifact_path injected."""
    from fastapi.testclient import TestClient

    from app.main import app

    artifact = isolated_reports_dir / "sid-ok_2026-04-28_paper.json"
    sample = {
        "schema_version": "1.0",
        "strategy_id": "sid-ok",
        "execution_mode": "paper",
        "data_available": True,
        "summary": {"sharpe": 1.5, "mdd": -0.08},
        "trades_count": 0,
    }
    artifact.write_text(json.dumps(sample), encoding="utf-8")

    client = TestClient(app)
    resp = client.get("/api/reports/sid-ok/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == "1.0"
    assert body["summary"]["sharpe"] == 1.5
    assert "_artifact_path" in body
    assert "sid-ok_2026-04-28_paper.json" in body["_artifact_path"]


def test_get_latest_400_on_bad_mode():
    """GET /{sid}/latest with execution_mode != paper/live → 400."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get(
        "/api/reports/sid-x/latest",
        params={"execution_mode": "shadow"},
    )
    assert resp.status_code == 400


def test_get_latest_500_on_corrupt_json(isolated_reports_dir):
    """Corrupt JSON artifact → 500 (反 silent return of partial/garbage payload)."""
    from fastapi.testclient import TestClient

    from app.main import app

    (isolated_reports_dir / "sid-corrupt_2026-04-28_paper.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    client = TestClient(app)
    resp = client.get("/api/reports/sid-corrupt/latest")
    assert resp.status_code == 500
    assert "unreadable" in resp.json()["detail"]
