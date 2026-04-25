"""MVP 1.4 DBADRRegistry 单测 — register / supersede / get_by_id / list_by_ironlaw."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.qm_platform.knowledge.interface import ADRRecord
from backend.qm_platform.knowledge.registry import (
    ADRNotFound,
    DBADRRegistry,
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
    adr_id: str = "ADR-001",
    related_ironlaws: list[int] | None = None,
) -> ADRRecord:
    return ADRRecord(
        adr_id=adr_id,
        title="Platform 包名 backend.qm_platform",
        status="accepted",
        context="Wave 1 启动前决策包名",
        decision="采用 backend.qm_platform (不加 quantmind namespace)",
        consequences="短路径, Python 命名空间隔离足够",
        related_ironlaws=related_ironlaws or [38],
        recorded_at="2026-04-17T10:00:00Z",
    )


# ---------- register ----------


def test_register_inserts_with_upsert_returns_adr_id() -> None:
    factory, conn, cursor = _make_conn_factory()
    r = DBADRRegistry(conn_factory=factory)
    result = r.register(_make_record())
    assert result == "ADR-001"
    sql = cursor.execute.call_args[0][0]
    assert "INSERT INTO adr_records" in sql
    assert "ON CONFLICT (adr_id)" in sql
    conn.commit.assert_called_once()


def test_register_duplicate_adr_id_goes_through_upsert() -> None:
    """同 adr_id 重复 register — 幂等, 不 raise."""
    factory, _, cursor = _make_conn_factory()
    r = DBADRRegistry(conn_factory=factory)
    r.register(_make_record())
    r.register(_make_record())
    assert cursor.execute.call_count == 2


def test_register_with_file_path_extension() -> None:
    factory, _, cursor = _make_conn_factory()
    r = DBADRRegistry(conn_factory=factory)
    r._register_with_file(_make_record(), file_path="docs/adr/ADR-001-platform.md")
    params = cursor.execute.call_args[0][1]
    # adr_id, title, status, context, decision, consequences, ironlaws, file_path (8)
    assert params[7] == "docs/adr/ADR-001-platform.md"


# ---------- supersede ----------


def test_supersede_updates_status_to_superseded_by() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.rowcount = 1
    r = DBADRRegistry(conn_factory=factory)
    r.supersede("ADR-001", "ADR-010")
    sql, params = cursor.execute.call_args[0]
    assert "UPDATE adr_records" in sql
    assert params == ("superseded_by:ADR-010", "ADR-001")


def test_supersede_not_found_raises() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.rowcount = 0
    r = DBADRRegistry(conn_factory=factory)
    with pytest.raises(ADRNotFound, match="ADR-999"):
        r.supersede("ADR-999", "ADR-100")


# ---------- get_by_id ----------


def test_get_by_id_success() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchone.return_value = (
        "ADR-001",
        "Platform 包名 backend.qm_platform",
        "accepted",
        "context",
        "decision",
        "consequences",
        [38, 22],
        "2026-04-17T10:00:00Z",
    )
    r = DBADRRegistry(conn_factory=factory)
    rec = r.get_by_id("ADR-001")
    assert rec.adr_id == "ADR-001"
    assert rec.related_ironlaws == [38, 22]


def test_get_by_id_not_found_raises() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchone.return_value = None
    r = DBADRRegistry(conn_factory=factory)
    with pytest.raises(ADRNotFound, match="ADR-999"):
        r.get_by_id("ADR-999")


# ---------- list_by_ironlaw ----------


def test_list_by_ironlaw_uses_any_for_psycopg2() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBADRRegistry(conn_factory=factory, paramstyle="%s")
    r.list_by_ironlaw(38)
    sql, params = cursor.execute.call_args[0]
    assert "ANY(related_ironlaws)" in sql
    assert params == (38,)


def test_list_by_ironlaw_uses_like_for_sqlite() -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.fetchall.return_value = []
    r = DBADRRegistry(conn_factory=factory, paramstyle="?")
    r.list_by_ironlaw(38)
    sql, params = cursor.execute.call_args[0]
    assert "related_ironlaws LIKE" in sql
    assert params == ("%38%",)


def test_write_not_configured_register() -> None:
    r = DBADRRegistry(conn_factory=None)
    with pytest.raises(WriteNotConfigured):
        r.register(_make_record())
