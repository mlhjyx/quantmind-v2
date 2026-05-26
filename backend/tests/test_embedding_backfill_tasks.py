"""iter 174 MVP 4.7 Chunk 1 — BGE-M3 embedding backfill Beat task tests.

TDD methodology: tests written FIRST against not-yet-implemented
backfill_risk_memory_embeddings_task() Celery task. Expected initial fail:
AttributeError or ModuleNotFoundError on the new module.

Phase J §1.4 wire: idempotent backfill of risk_memory rows with embedding=NULL
via BGE-M3 EmbeddingService. Self-healing for future NULL sources (reflector
transient failure / manual INSERT / historical 21 rows).

Sibling pattern: risk_reflector_tasks._get_rag() lazy singleton + 3-layer
qm_platform/risk/memory/embedding_service.BGEM3EmbeddingService.encode().
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_embedding_service():
    """Mock BGEM3EmbeddingService returning deterministic 1024-dim vectors."""
    svc = MagicMock()
    # Each encode call returns a list of 1024 floats (mocked).
    svc.encode.side_effect = lambda text: [0.1] * 1024
    return svc


@pytest.fixture
def mock_conn_with_rows():
    """Mock psycopg2 conn whose cursor returns 3 NULL-embedding rows."""
    cur = MagicMock()
    # Cursor SELECT returns (memory_id, lesson) tuples for 3 rows.
    cur.fetchall.return_value = [
        (101, "Lesson text one: limit_down handled by STAGED PENDING_CONFIRM cancel."),
        (102, "Lesson text two: rapid_drop triggered AlertDispatcher P0 within 30s."),
        (103, "Lesson text three: industry_correlated drawdown sized 70% partial close."),
    ]
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


@pytest.fixture
def mock_conn_empty():
    """Mock conn whose cursor returns 0 NULL-embedding rows (matched state)."""
    cur = MagicMock()
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def test_backfill_finds_null_embedding_rows(mock_conn_with_rows, mock_embedding_service):
    """SELECT must filter `WHERE embedding IS NULL` and ORDER BY created_at LIMIT batch_size."""
    from app.tasks.embedding_backfill_tasks import backfill_risk_memory_embeddings

    conn, cur = mock_conn_with_rows

    with (
        patch("app.tasks.embedding_backfill_tasks.get_sync_conn", return_value=conn),
        patch(
            "app.tasks.embedding_backfill_tasks._get_embedding_service",
            return_value=mock_embedding_service,
        ),
    ):
        result = backfill_risk_memory_embeddings(batch_size=100)

    # cursor.execute called at least once with SELECT against risk_memory
    select_calls = [
        c for c in cur.execute.call_args_list
        if c.args and "SELECT" in c.args[0] and "risk_memory" in c.args[0]
    ]
    assert len(select_calls) >= 1, "Expected SELECT against risk_memory"
    select_sql = select_calls[0].args[0]
    assert "embedding IS NULL" in select_sql, (
        f"SELECT must filter NULL embeddings; got: {select_sql}"
    )
    assert "ORDER BY created_at" in select_sql or "ORDER BY memory_id" in select_sql, (
        "SELECT must ORDER BY deterministic key for idempotent batch processing"
    )
    # batch_size param passed as LIMIT bind
    assert result["processed"] == 3


def test_backfill_batch_encodes_via_embedding_service(
    mock_conn_with_rows, mock_embedding_service
):
    """Each row's lesson text passed to embedding_service.encode."""
    from app.tasks.embedding_backfill_tasks import backfill_risk_memory_embeddings

    conn, _cur = mock_conn_with_rows

    with (
        patch("app.tasks.embedding_backfill_tasks.get_sync_conn", return_value=conn),
        patch(
            "app.tasks.embedding_backfill_tasks._get_embedding_service",
            return_value=mock_embedding_service,
        ),
    ):
        backfill_risk_memory_embeddings(batch_size=100)

    # encode called once per row (3 rows)
    assert mock_embedding_service.encode.call_count == 3
    # First call args contain the first lesson text
    first_call = mock_embedding_service.encode.call_args_list[0]
    assert "limit_down" in first_call.args[0] or "limit_down" in first_call.kwargs.get(
        "text", ""
    )


def test_backfill_updates_rows_idempotent(
    mock_conn_with_rows, mock_embedding_service
):
    """UPDATE must include WHERE embedding IS NULL for idempotent re-run safety."""
    from app.tasks.embedding_backfill_tasks import backfill_risk_memory_embeddings

    conn, cur = mock_conn_with_rows

    with (
        patch("app.tasks.embedding_backfill_tasks.get_sync_conn", return_value=conn),
        patch(
            "app.tasks.embedding_backfill_tasks._get_embedding_service",
            return_value=mock_embedding_service,
        ),
    ):
        backfill_risk_memory_embeddings(batch_size=100)

    # cursor.execute called with UPDATE for each row
    update_calls = [
        c for c in cur.execute.call_args_list
        if c.args and "UPDATE" in c.args[0] and "risk_memory" in c.args[0]
    ]
    assert len(update_calls) == 3, f"Expected 3 UPDATE calls, got {len(update_calls)}"
    # Idempotency guard: WHERE embedding IS NULL
    update_sql = update_calls[0].args[0]
    assert "WHERE" in update_sql
    assert "embedding IS NULL" in update_sql, (
        f"UPDATE must include 'WHERE ... embedding IS NULL' for idempotency; got: {update_sql}"
    )
    # conn.commit called once (transaction owner per 铁律 32)
    conn.commit.assert_called_once()


def test_backfill_empty_when_no_null_rows(mock_conn_empty, mock_embedding_service):
    """When no NULL rows exist, encode is NOT called and processed=0."""
    from app.tasks.embedding_backfill_tasks import backfill_risk_memory_embeddings

    conn, cur = mock_conn_empty

    with (
        patch("app.tasks.embedding_backfill_tasks.get_sync_conn", return_value=conn),
        patch(
            "app.tasks.embedding_backfill_tasks._get_embedding_service",
            return_value=mock_embedding_service,
        ),
    ):
        result = backfill_risk_memory_embeddings(batch_size=100)

    assert result["processed"] == 0
    mock_embedding_service.encode.assert_not_called()
    # No UPDATE calls
    update_calls = [
        c for c in cur.execute.call_args_list
        if c.args and "UPDATE" in c.args[0]
    ]
    assert len(update_calls) == 0


def test_backfill_returns_metadata_dict(mock_conn_with_rows, mock_embedding_service):
    """Return value must include processed count + batch_size + embedding_dim for ops visibility."""
    from app.tasks.embedding_backfill_tasks import backfill_risk_memory_embeddings

    conn, _cur = mock_conn_with_rows

    with (
        patch("app.tasks.embedding_backfill_tasks.get_sync_conn", return_value=conn),
        patch(
            "app.tasks.embedding_backfill_tasks._get_embedding_service",
            return_value=mock_embedding_service,
        ),
    ):
        result = backfill_risk_memory_embeddings(batch_size=100)

    assert isinstance(result, dict)
    assert result["processed"] == 3
    assert result["batch_size"] == 100
    # embedding_dim from mock service output (1024)
    assert result.get("embedding_dim") == 1024


def test_backfill_closes_connection_on_success(
    mock_conn_with_rows, mock_embedding_service
):
    """conn.close called once after successful backfill (resource cleanup)."""
    from app.tasks.embedding_backfill_tasks import backfill_risk_memory_embeddings

    conn, _cur = mock_conn_with_rows

    with (
        patch("app.tasks.embedding_backfill_tasks.get_sync_conn", return_value=conn),
        patch(
            "app.tasks.embedding_backfill_tasks._get_embedding_service",
            return_value=mock_embedding_service,
        ),
    ):
        backfill_risk_memory_embeddings(batch_size=100)

    conn.close.assert_called_once()


def test_backfill_uses_pgvector_cast_and_text_literal(
    mock_conn_with_rows, mock_embedding_service
):
    """Reviewer P0 regression guard (iter 174): UPDATE must use `%s::vector` cast +
    bind value must be a pgvector text literal (str starting with `[`), NOT a raw
    tuple. psycopg2 cannot adapt tuple → pgvector; canonical pattern from
    `backend/qm_platform/risk/memory/repository.py:_embedding_to_pgvector_str`
    converts tuple → `[v1,v2,...]` text + `::vector` cast.

    This test prevents the original P0 from regressing: tests 3 + 4 mock execute
    so they don't catch SQL adapter failure; this assertion locks the contract.
    """
    from app.tasks.embedding_backfill_tasks import backfill_risk_memory_embeddings

    conn, cur = mock_conn_with_rows

    with (
        patch("app.tasks.embedding_backfill_tasks.get_sync_conn", return_value=conn),
        patch(
            "app.tasks.embedding_backfill_tasks._get_embedding_service",
            return_value=mock_embedding_service,
        ),
    ):
        backfill_risk_memory_embeddings(batch_size=100)

    update_calls = [
        c for c in cur.execute.call_args_list
        if c.args and "UPDATE" in c.args[0] and "risk_memory" in c.args[0]
    ]
    assert len(update_calls) == 3
    # SQL must contain `::vector` cast (P0 regression guard)
    update_sql = update_calls[0].args[0]
    assert "::vector" in update_sql, (
        f"UPDATE must use ::vector cast for pgvector adaptation; got: {update_sql!r}"
    )
    # Bind value 0 must be str (pgvector text literal), NOT tuple
    bind_embedding = update_calls[0].args[1][0]
    assert isinstance(bind_embedding, str), (
        f"Embedding bind must be str (pgvector text literal), got {type(bind_embedding).__name__}"
    )
    assert bind_embedding.startswith("["), (
        f"pgvector text literal must start with '['; got: {bind_embedding[:20]!r}"
    )
    assert bind_embedding.endswith("]"), (
        f"pgvector text literal must end with ']'; got: ...{bind_embedding[-20:]!r}"
    )
