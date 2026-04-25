"""MVP 1.4 DBFailedDirectionDB 单测 — add / check_similar / list_all."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.qm_platform.knowledge.interface import FailedDirectionRecord
from backend.qm_platform.knowledge.registry import (
    DBFailedDirectionDB,
    WriteNotConfigured,
)


def _make_conn_factory() -> tuple[MagicMock, MagicMock, MagicMock]:
    cursor = MagicMock()
    cursor.rowcount = 1
    ctx = MagicMock()
    ctx.__enter__.return_value = cursor
    ctx.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = ctx
    factory = MagicMock(return_value=conn)
    return factory, conn, cursor


def _make_record(
    direction: str = "LightGBM E2E Sharpe > 等权",
    severity: str = "terminal",
) -> FailedDirectionRecord:
    return FailedDirectionRecord(
        direction=direction,
        reason="5 次独立 WF 验证 Sharpe 均 < 基线",
        evidence=["commit:abc123", "docs/research-kb/findings/phase3d.md"],
        recorded_at="2026-04-14T00:00:00Z",
        severity=severity,
    )


# ---------- add ----------


def test_add_success_inserts_with_upsert_sql() -> None:
    factory, conn, cursor = _make_conn_factory()
    r = DBFailedDirectionDB(conn_factory=factory)
    r.add(_make_record())
    cursor.execute.assert_called_once()
    sql = cursor.execute.call_args[0][0]
    assert "INSERT INTO failed_directions" in sql
    assert "ON CONFLICT" in sql
    assert "direction" in sql
    conn.commit.assert_called_once()


def test_add_with_source_and_tags() -> None:
    factory, _, cursor = _make_conn_factory()
    r = DBFailedDirectionDB(conn_factory=factory)
    r.add_with_source(
        _make_record(),
        source="docs/research-kb/failed/ml-e2e.md",
        tags=["ml", "portfolio"],
    )
    params = cursor.execute.call_args[0][1]
    # direction, reason, evidence, severity, source, tags (6)
    assert params[4] == "docs/research-kb/failed/ml-e2e.md"
    assert params[5] == ["ml", "portfolio"]


def test_add_duplicate_direction_goes_through_upsert() -> None:
    """Second add with 同 direction — 幂等 (ON CONFLICT DO UPDATE, 不 raise)."""
    factory, _, cursor = _make_conn_factory()
    r = DBFailedDirectionDB(conn_factory=factory)
    rec1 = _make_record(direction="duplicate_factor")
    rec2 = _make_record(direction="duplicate_factor")
    r.add(rec1)
    r.add(rec2)
    assert cursor.execute.call_count == 2  # 两次 INSERT ... ON CONFLICT, 不 raise


def test_add_write_not_configured() -> None:
    r = DBFailedDirectionDB(conn_factory=None)
    with pytest.raises(WriteNotConfigured):
        r.add(_make_record())


# ---------- check_similar ----------


def test_check_similar_with_keywords_builds_ilike() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBFailedDirectionDB(conn_factory=factory)
    r.check_similar("ML 端到端训练 E2E 微盘", k=3)
    sql, params = cursor.execute.call_args[0]
    assert "ILIKE" in sql
    assert params[-1] == 3


def test_check_similar_empty_direction_returns_latest() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBFailedDirectionDB(conn_factory=factory)
    r.check_similar("", k=5)
    sql = cursor.execute.call_args[0][0]
    assert "WHERE" not in sql


def test_check_similar_parses_row_to_failed_record() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = [
        (
            "双周调仓",
            "Sharpe 0.91→0.73",
            '["G2实验"]',
            "2024-01-01T00:00:00Z",
            "terminal",
        )
    ]
    r = DBFailedDirectionDB(conn_factory=factory)
    results = r.check_similar("双周")
    assert len(results) == 1
    rec = results[0]
    assert rec.direction == "双周调仓"
    assert rec.severity == "terminal"
    assert rec.evidence == ["G2实验"]


# ---------- list_all ----------


def test_list_all_no_filter() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBFailedDirectionDB(conn_factory=factory)
    r.list_all()
    sql = cursor.execute.call_args[0][0]
    assert "WHERE" not in sql
    assert "ORDER BY recorded_at DESC" in sql


def test_list_all_severity_filter() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBFailedDirectionDB(conn_factory=factory)
    r.list_all(severity="conditional")
    sql, params = cursor.execute.call_args[0]
    assert "severity=" in sql
    assert params == ("conditional",)


def test_check_similar_write_not_configured() -> None:
    r = DBFailedDirectionDB(conn_factory=None)
    with pytest.raises(WriteNotConfigured):
        r.check_similar("test")
