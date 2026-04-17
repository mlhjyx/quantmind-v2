"""MVP 1.4 DBExperimentRegistry 单测 — register / complete / search_similar."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from backend.platform.knowledge.interface import ExperimentRecord
from backend.platform.knowledge.registry import (
    DBExperimentRegistry,
    ExperimentNotFound,
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
    hypothesis: str = "测试假设 LightGBM OOS Sharpe",
    experiment_id: UUID | None = None,
) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment_id or UUID(int=0),
        hypothesis=hypothesis,
        status="running",
        author="test",
        started_at="2026-04-17T10:00:00Z",
        completed_at=None,
        verdict=None,
        artifacts={},
        tags=["ml"],
    )


# ---------- register ----------


def test_register_success_generates_uuid_when_zero() -> None:
    factory, _, cursor = _make_conn_factory()
    r = DBExperimentRegistry(conn_factory=factory)
    rec = _make_record()
    exp_id = r.register(rec)
    assert isinstance(exp_id, UUID)
    assert int(exp_id) != 0
    cursor.execute.assert_called_once()


def test_register_uses_record_uuid_when_provided() -> None:
    factory, _, cursor = _make_conn_factory()
    r = DBExperimentRegistry(conn_factory=factory)
    fixed = uuid4()
    rec = _make_record(experiment_id=fixed)
    exp_id = r.register(rec)
    assert exp_id == fixed
    call_args = cursor.execute.call_args[0][1]
    assert call_args[0] == str(fixed)


def test_register_write_not_configured() -> None:
    r = DBExperimentRegistry(conn_factory=None)
    with pytest.raises(WriteNotConfigured, match="conn_factory"):
        r.register(_make_record())


# ---------- complete ----------


def test_complete_success() -> None:
    factory, conn, cursor = _make_conn_factory()
    cursor.rowcount = 1
    r = DBExperimentRegistry(conn_factory=factory)
    r.complete(
        experiment_id=uuid4(),
        verdict="Sharpe -0.99, NO-GO",
        status="failed",
        artifacts={"report": "path/to/x.md"},
    )
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_complete_not_found_raises() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.rowcount = 0
    r = DBExperimentRegistry(conn_factory=factory)
    with pytest.raises(ExperimentNotFound):
        r.complete(uuid4(), "v", "success", {})


def test_complete_invalid_status_raises_value_error() -> None:
    factory, _, _ = _make_conn_factory()
    r = DBExperimentRegistry(conn_factory=factory)
    with pytest.raises(ValueError, match="success/failed/inconclusive"):
        r.complete(uuid4(), "v", "unknown_status", {})


def test_complete_write_not_configured() -> None:
    r = DBExperimentRegistry(conn_factory=None)
    with pytest.raises(WriteNotConfigured):
        r.complete(uuid4(), "v", "success", {})


# ---------- search_similar ----------


def test_search_similar_with_keywords_builds_ilike() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBExperimentRegistry(conn_factory=factory)
    r.search_similar("LightGBM OOS Sharpe 验证", k=3)
    sql, params = cursor.execute.call_args[0]
    assert "ILIKE" in sql
    assert "ORDER BY started_at DESC" in sql
    assert params[-1] == 3  # k


def test_search_similar_empty_hypothesis_returns_latest() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBExperimentRegistry(conn_factory=factory)
    r.search_similar("", k=5)
    sql = cursor.execute.call_args[0][0]
    assert "WHERE" not in sql  # 空关键词无 WHERE
    assert "ORDER BY started_at DESC" in sql


def test_search_similar_parses_row_to_experiment_record() -> None:
    factory, _, cursor = _make_conn_factory()
    uid = uuid4()
    cursor.fetchall.return_value = [
        (
            uid,
            "LightGBM E2E 测试",
            "failed",
            "test_author",
            "2026-04-10T10:00:00Z",
            "2026-04-10T12:00:00Z",
            "Sharpe 0.54 < 0.87",
            '{"report": "phase3d.md"}',
            ["ml", "wf"],
        )
    ]
    r = DBExperimentRegistry(conn_factory=factory)
    results = r.search_similar("LightGBM", k=5)
    assert len(results) == 1
    rec = results[0]
    assert rec.experiment_id == uid
    assert rec.status == "failed"
    assert rec.verdict is not None
    assert rec.artifacts == {"report": "phase3d.md"}
    assert rec.tags == ["ml", "wf"]


def test_search_similar_respects_limit_k() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBExperimentRegistry(conn_factory=factory)
    r.search_similar("factor research", k=7)
    params = cursor.execute.call_args[0][1]
    assert params[-1] == 7


def test_search_similar_write_not_configured() -> None:
    r = DBExperimentRegistry(conn_factory=None)
    with pytest.raises(WriteNotConfigured):
        r.search_similar("anything")


def test_search_similar_handles_short_keyword_filter() -> None:
    """短词 (长度 ≤ 2) 被过滤掉, 不参与 LIKE."""
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBExperimentRegistry(conn_factory=factory)
    r.search_similar("AI is ok", k=2)  # "is" / "ok" 长度 ≤ 2, 过滤
    sql = cursor.execute.call_args[0][0]
    # 只有 "AI" 长度 2, 被过滤; 结果为空关键词 → 没 WHERE
    # (注: "AI" 长度 2, 过滤条件 > 2 → 也被过滤)
    assert "WHERE" not in sql
