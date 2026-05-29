"""iter 174 MVP 4.7 Chunk 1 — BGE-M3 embedding backfill Celery task + Beat-driven cron.

Phase J §1.4 wire: idempotent backfill of risk_memory rows with embedding=NULL
via BGE-M3 EmbeddingService. Self-healing for any future NULL embedding source
(reflector transient failure / manual INSERT / historical 21-row backfill from
pre-embedding-service era).

Cadence per MVP 4.7 design: every 6h via Beat schedule entry
`embedding-backfill-every-6h` in beat_schedule.py.

Idempotent contract:
- SELECT: WHERE embedding IS NULL ORDER BY created_at LIMIT batch_size
- UPDATE: SET embedding=... WHERE memory_id=X AND embedding IS NULL
- Safe to re-run mid-flight (partial completion handled by NULL guard on UPDATE)

Sibling pattern (sustained):
- risk_reflector_tasks._get_rag() L143-168 lazy singleton (share BGE-M3
  ~2.5GB model load across Beat invocations within one worker)
- 3-layer separation: qm_platform/risk/memory/embedding_service = Engine pure,
  本 module = app/tasks Beat dispatch layer
- 铁律 32: caller owns transaction (explicit conn.commit + finally close)
- 铁律 33: failures propagate (Celery retry handles transient)
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.db import get_sync_conn
from app.tasks.celery_app import celery_app

# Reviewer P0 fix (iter 174): pgvector adaptation — BGEM3EmbeddingService.encode
# returns tuple[float, ...] which psycopg2 cannot adapt to pgvector column.
# Use canonical helper from repository.py + %s::vector cast (sibling pattern
# persist_risk_memory at backend/qm_platform/risk/memory/repository.py:69+86).
from backend.qm_platform.risk.memory.repository import _embedding_to_pgvector_str

logger = logging.getLogger("celery.embedding_backfill_tasks")

# Lazy singleton — shared BGE-M3 model load across Beat invocations.
_embedding_service: Any = None


def _get_embedding_service() -> Any:
    """Lazy singleton BGEM3EmbeddingService.

    Sibling pattern: `app/tasks/risk_reflector_tasks._get_rag()` L146-168.
    First call loads BGE-M3 ~2.5GB model (~3-5s warm cache, longer cold);
    subsequent calls O(1) read.
    """
    global _embedding_service
    if _embedding_service is None:
        from backend.qm_platform.risk.memory.embedding_service import (  # noqa: PLC0415
            BGEM3EmbeddingService,
        )

        _embedding_service = BGEM3EmbeddingService()
        logger.info("[embedding-backfill] initialized BGEM3EmbeddingService singleton")
    return _embedding_service


def backfill_risk_memory_embeddings(*, batch_size: int = 100) -> dict:
    """Backfill risk_memory rows where embedding IS NULL via BGE-M3.

    Idempotent — safe to re-run; partial completion handled by NULL guards
    on both SELECT and UPDATE. Caller owns transaction (铁律 32) via explicit
    commit + finally close.

    Args:
        batch_size: max rows per invocation (default 100). Beat schedule fires
            every 6h; batch_size limits worst-case GPU+DB time per run.
            21 historical NULL rows + future trickle should fit batch_size=100
            comfortably with sub-second BGE-M3 encode + UPDATE.

    Returns:
        dict — {processed: int, batch_size: int, embedding_dim: int | None}

    Raises:
        psycopg2.Error: caller propagates (Celery retry policy applies on task).
    """
    conn = get_sync_conn()
    embedding_svc = _get_embedding_service()

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT memory_id, lesson FROM risk_memory
            WHERE embedding IS NULL
            ORDER BY created_at
            LIMIT %s
            """,
            (batch_size,),
        )
        rows = cur.fetchall()

        if not rows:
            logger.info("[embedding-backfill] 0 NULL rows found; nothing to do (idempotent no-op).")
            return {"processed": 0, "batch_size": batch_size, "embedding_dim": None}

        embedding_dim: int | None = None
        for memory_id, lesson in rows:
            embedding = embedding_svc.encode(lesson)
            if embedding_dim is None:
                embedding_dim = len(embedding)
            # Reviewer P0 fix: tuple[float,...] → pgvector text literal + ::vector cast.
            embedding_str = _embedding_to_pgvector_str(embedding)
            cur.execute(
                """
                UPDATE risk_memory
                SET embedding = %s::vector
                WHERE memory_id = %s AND embedding IS NULL
                """,
                (embedding_str, memory_id),
            )

        conn.commit()
        logger.info(
            "[embedding-backfill] processed=%d batch_size=%d embedding_dim=%s",
            len(rows),
            batch_size,
            embedding_dim,
        )

        return {
            "processed": len(rows),
            "batch_size": batch_size,
            "embedding_dim": embedding_dim,
        }
    finally:
        conn.close()


@celery_app.task(name="embedding.backfill")
def backfill_risk_memory_embeddings_task(*, batch_size: int = 100) -> dict:
    """Celery task wrapper for `backfill_risk_memory_embeddings`.

    Beat schedule: `embedding-backfill-every-6h` (see beat_schedule.py).
    Retries: handled by Celery default policy (worker propagates psycopg2.Error
    after `finally conn.close`).
    """
    return backfill_risk_memory_embeddings(batch_size=batch_size)
