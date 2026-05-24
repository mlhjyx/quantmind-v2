"""Tests for GET /api/reports/{sid}/list endpoint + list_reports_for helper.

Iter 32 — extends iter 30 (/latest single-fetch) with historical listing.
Coverage:
  - list_reports_for helper:
    - empty / non-existent REPORTS_DIR → []
    - non-matching files in dir (different sid / non-pattern) → [] for our sid
    - mtime DESC sort
    - limit cap
    - execution_mode filter (None / paper / live)
    - bad-input validation (limit<1, bad mode)
    - corrupt JSON entry → INCLUDE with _corrupt=True (反 silent skip)
  - GET /{sid}/list endpoint:
    - 200 empty list when no artifacts
    - 200 with multi-row payload + mtime ordering
    - 400 on bad execution_mode query
    - limit query param honored
    - mode filter query param honored
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_reports_dir(tmp_path, monkeypatch):
    """Patch REPORTS_DIR so tests can't pollute production reports/."""
    from app.tasks import report_tasks

    monkeypatch.setattr(report_tasks, "REPORTS_DIR", tmp_path)
    return tmp_path


def _write_artifact(
    dir_path: Path,
    sid: str,
    date_iso: str,
    mode: str,
    summary: dict | None = None,
    mtime: float | None = None,
    body_override: str | None = None,
) -> Path:
    """Create a sample artifact JSON file with optional mtime override."""
    p = dir_path / f"{sid}_{date_iso}_{mode}.json"
    if body_override is not None:
        p.write_text(body_override, encoding="utf-8")
    else:
        payload = {
            "schema_version": "1.0",
            "strategy_id": sid,
            "execution_mode": mode,
            "target_date_shanghai": date_iso,
            "summary": summary,
            "trades_count": 0,
        }
        p.write_text(json.dumps(payload), encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


# ── list_reports_for helper ─────────────────────────────────────────────────


def test_list_reports_for_empty_dir(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    assert list_reports_for("sid-empty") == []


def test_list_reports_for_missing_dir(tmp_path, monkeypatch):
    from app.tasks import report_tasks

    missing = tmp_path / "does_not_exist"
    monkeypatch.setattr(report_tasks, "REPORTS_DIR", missing)
    assert report_tasks.list_reports_for("sid-x") == []


def test_list_reports_for_filters_other_sids(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    _write_artifact(isolated_reports_dir, "sid-A", "2026-05-20", "paper")
    _write_artifact(isolated_reports_dir, "sid-B", "2026-05-20", "paper")
    _write_artifact(isolated_reports_dir, "sid-B", "2026-05-21", "paper")

    result = list_reports_for("sid-A")
    assert len(result) == 1
    assert result[0]["strategy_id"] == "sid-A"
    assert result[0]["target_date"] == "2026-05-20"


def test_list_reports_for_mtime_desc_sort(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    older = _write_artifact(
        isolated_reports_dir, "sid-X", "2026-05-20", "paper", mtime=time.time() - 1000
    )
    newer = _write_artifact(
        isolated_reports_dir, "sid-X", "2026-05-21", "paper", mtime=time.time() - 10
    )

    result = list_reports_for("sid-X")
    assert len(result) == 2
    # Newest first
    assert result[0]["artifact_path"] == str(newer)
    assert result[1]["artifact_path"] == str(older)


def test_list_reports_for_limit_cap(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    base = time.time() - 10_000
    for i in range(5):
        _write_artifact(
            isolated_reports_dir, "sid-L", f"2026-05-{10 + i:02d}", "paper", mtime=base + i
        )

    result = list_reports_for("sid-L", limit=3)
    assert len(result) == 3
    # Limit applied AFTER sort: newest 3 retained
    dates = [r["target_date"] for r in result]
    assert dates == ["2026-05-14", "2026-05-13", "2026-05-12"]


def test_list_reports_for_mode_filter(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    _write_artifact(isolated_reports_dir, "sid-M", "2026-05-20", "paper")
    _write_artifact(isolated_reports_dir, "sid-M", "2026-05-20", "live")
    _write_artifact(isolated_reports_dir, "sid-M", "2026-05-21", "paper")

    paper_only = list_reports_for("sid-M", execution_mode="paper")
    assert len(paper_only) == 2
    assert all(r["execution_mode"] == "paper" for r in paper_only)

    live_only = list_reports_for("sid-M", execution_mode="live")
    assert len(live_only) == 1
    assert live_only[0]["execution_mode"] == "live"

    both = list_reports_for("sid-M", execution_mode=None)
    assert len(both) == 3


def test_list_reports_for_summary_preview_extracted(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    summary = {"sharpe": 1.5, "mdd": -0.08, "days": 60, "total_return": 0.12}
    _write_artifact(isolated_reports_dir, "sid-S", "2026-05-20", "paper", summary=summary)

    result = list_reports_for("sid-S")
    assert len(result) == 1
    assert result[0]["summary"] == summary
    assert result[0]["_corrupt"] is False


def test_list_reports_for_corrupt_artifact_included(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    # 1 good + 1 corrupt
    _write_artifact(isolated_reports_dir, "sid-C", "2026-05-20", "paper", summary={"sharpe": 1.0})
    _write_artifact(
        isolated_reports_dir, "sid-C", "2026-05-21", "paper", body_override="{not valid json"
    )

    result = list_reports_for("sid-C")
    assert len(result) == 2
    corrupt_entries = [r for r in result if r["_corrupt"]]
    assert len(corrupt_entries) == 1
    assert corrupt_entries[0]["summary"] is None
    assert "_corrupt_reason" in corrupt_entries[0]
    assert "JSONDecodeError" in corrupt_entries[0]["_corrupt_reason"]


def test_list_reports_for_validates_bad_limit(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    with pytest.raises(ValueError, match="limit must be >= 1"):
        list_reports_for("sid-x", limit=0)


def test_list_reports_for_validates_bad_mode(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    with pytest.raises(ValueError, match="execution_mode must be"):
        list_reports_for("sid-x", execution_mode="shadow")


def test_list_reports_for_ignores_non_pattern_files(isolated_reports_dir):
    """Pre-existing reports/ residents (DATA_SYSTEM_V1_COMPLETION.md etc) MUST be ignored."""
    from app.tasks.report_tasks import list_reports_for

    legacy = [
        "DATA_SYSTEM_V1_COMPLETION.md",
        "p0_minute_neutral_ic_20260417_042139.json",
        "sid-Z_invalid-mode.json",
        "sid-Z_2026-05-20_invalid.json",
    ]
    for name in legacy:
        (isolated_reports_dir / name).write_text("{}", encoding="utf-8")
    # 1 real artifact for sid-Z
    _write_artifact(isolated_reports_dir, "sid-Z", "2026-05-20", "paper")

    result = list_reports_for("sid-Z")
    assert len(result) == 1
    assert result[0]["target_date"] == "2026-05-20"


def test_list_reports_for_mtime_utc_iso_format(isolated_reports_dir):
    from app.tasks.report_tasks import list_reports_for

    fixed_mtime = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC).timestamp()
    _write_artifact(isolated_reports_dir, "sid-T", "2026-05-20", "paper", mtime=fixed_mtime)

    result = list_reports_for("sid-T")
    assert len(result) == 1
    # ISO format with timezone offset (UTC)
    assert "T" in result[0]["mtime_utc"]
    assert "2026-05-20" in result[0]["mtime_utc"]


# ── GET /{strategy_id}/list endpoint ────────────────────────────────────────


def test_get_list_endpoint_empty_returns_200(isolated_reports_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/reports/sid-none/list")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_list_endpoint_returns_multi_row(isolated_reports_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    base = time.time() - 5000
    _write_artifact(
        isolated_reports_dir, "sid-API", "2026-05-19", "paper", mtime=base, summary={"sharpe": 1.1}
    )
    _write_artifact(
        isolated_reports_dir,
        "sid-API",
        "2026-05-20",
        "paper",
        mtime=base + 1000,
        summary={"sharpe": 1.2},
    )

    client = TestClient(app)
    resp = client.get("/api/reports/sid-API/list")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # mtime DESC
    assert body[0]["target_date"] == "2026-05-20"
    assert body[1]["target_date"] == "2026-05-19"
    assert body[0]["summary"]["sharpe"] == 1.2


def test_get_list_endpoint_400_on_bad_mode():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/reports/sid-x/list", params={"execution_mode": "shadow"})
    assert resp.status_code == 400
    assert "execution_mode must be" in resp.json()["detail"]


def test_get_list_endpoint_mode_filter(isolated_reports_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    _write_artifact(isolated_reports_dir, "sid-MF", "2026-05-20", "paper")
    _write_artifact(isolated_reports_dir, "sid-MF", "2026-05-20", "live")

    client = TestClient(app)
    resp = client.get("/api/reports/sid-MF/list", params={"execution_mode": "live"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["execution_mode"] == "live"


def test_get_list_endpoint_limit_query(isolated_reports_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    base = time.time() - 10_000
    for i in range(5):
        _write_artifact(
            isolated_reports_dir, "sid-LIM", f"2026-05-{10 + i:02d}", "paper", mtime=base + i
        )

    client = TestClient(app)
    resp = client.get("/api/reports/sid-LIM/list", params={"limit": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["target_date"] == "2026-05-14"
    assert body[1]["target_date"] == "2026-05-13"


def test_get_list_endpoint_corrupt_artifact_marked(isolated_reports_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    _write_artifact(isolated_reports_dir, "sid-CR", "2026-05-20", "paper", summary={"sharpe": 1.0})
    _write_artifact(
        isolated_reports_dir, "sid-CR", "2026-05-21", "paper", body_override="{not valid"
    )

    client = TestClient(app)
    resp = client.get("/api/reports/sid-CR/list")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    corrupt = [r for r in body if r["_corrupt"]]
    assert len(corrupt) == 1
    assert corrupt[0]["summary"] is None
