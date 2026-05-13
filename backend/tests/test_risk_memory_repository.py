"""V3 §5.4 risk_memory repository — TB-3a unit + real-PG SAVEPOINT smoke tests.

Coverage:
  - ActionTaken Enum + str-subclass behavior (6 values match DDL CHECK)
  - RiskMemoryOutcome frozen + retrospective_correctness vocab validation
  - RiskMemory frozen + __post_init__ (event_type non-empty / tz-aware /
    lesson 500-char cap / embedding 1024-dim)
  - SimilarMemoryHit frozen
  - persist_risk_memory: full row insert + NULL embedding path
  - retrieve_similar: top-k cosine ordering + event_type filter +
    min_cosine_similarity floor + empty result (no embeddings yet)
  - DDL CHECK constraints: chk_event_type_non_empty + chk_action_taken_vocab

关联铁律: 17 (DataPipeline) / 31 (Engine PURE) / 33 (fail-loud) / 40 / 41 (timezone)
关联 V3: §5.4 / ADR-064 / ADR-067 / ADR-068 候选
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg2
import psycopg2.errors
import pytest

from backend.qm_platform.risk.memory import (
    ActionTaken,
    RiskMemory,
    RiskMemoryOutcome,
    persist_risk_memory,
    retrieve_similar,
)
from backend.qm_platform.risk.memory.interface import SimilarMemoryHit

# ─────────────────────────────────────────────────────────────
# ActionTaken Enum
# ─────────────────────────────────────────────────────────────


class TestActionTakenEnum:
    def test_six_values_match_ddl_check(self) -> None:
        """All 6 vocab values match DDL chk_action_taken_vocab."""
        assert ActionTaken.STAGED_EXECUTED.value == "STAGED_executed"
        assert ActionTaken.STAGED_CANCELLED.value == "STAGED_cancelled"
        assert ActionTaken.STAGED_TIMEOUT_EXECUTED.value == "STAGED_timeout_executed"
        assert ActionTaken.MANUAL_SELL.value == "manual_sell"
        assert ActionTaken.NO_ACTION.value == "no_action"
        assert ActionTaken.REENTRY.value == "reentry"

    def test_str_subclass_natural_serialization(self) -> None:
        assert isinstance(ActionTaken.STAGED_EXECUTED, str)
        assert ActionTaken.STAGED_EXECUTED == "STAGED_executed"


# ─────────────────────────────────────────────────────────────
# RiskMemoryOutcome
# ─────────────────────────────────────────────────────────────


class TestRiskMemoryOutcome:
    def test_minimal_all_none_accepted(self) -> None:
        """All None fields allowed — pre-evaluation state."""
        oc = RiskMemoryOutcome()
        assert oc.pnl_1d is None
        assert oc.retrospective_correctness is None

    def test_valid_correctness_values(self) -> None:
        for c in ("correct", "incorrect", "ambiguous", "pending"):
            oc = RiskMemoryOutcome(retrospective_correctness=c)
            assert oc.retrospective_correctness == c

    def test_invalid_correctness_raises(self) -> None:
        with pytest.raises(ValueError, match="retrospective_correctness"):
            RiskMemoryOutcome(retrospective_correctness="maybe")

    def test_to_jsonable(self) -> None:
        oc = RiskMemoryOutcome(
            pnl_1d=-0.03,
            pnl_5d=-0.05,
            pnl_30d=0.02,
            retrospective_correctness="ambiguous",
        )
        j = oc.to_jsonable()
        assert j["pnl_1d"] == -0.03
        assert j["retrospective_correctness"] == "ambiguous"
        import json  # noqa: PLC0415

        json.dumps(j)  # round-trip JSON-safe


# ─────────────────────────────────────────────────────────────
# RiskMemory dataclass
# ─────────────────────────────────────────────────────────────


def _make_minimal_memory(
    **kwargs: Any,
) -> RiskMemory:
    base: dict[str, Any] = {
        "event_type": "LimitDown",
        "event_timestamp": datetime(2026, 5, 14, 9, 0, 0, tzinfo=UTC),
        "context_snapshot": {"trigger": "test"},
    }
    base.update(kwargs)
    return RiskMemory(**base)


class TestRiskMemoryDataclass:
    def test_minimal_valid(self) -> None:
        m = _make_minimal_memory()
        assert m.event_type == "LimitDown"
        assert m.symbol_id is None
        assert m.embedding is None
        assert m.memory_id is None

    def test_event_type_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="event_type must be non-empty"):
            _make_minimal_memory(event_type="")
        with pytest.raises(ValueError, match="event_type must be non-empty"):
            _make_minimal_memory(event_type="   ")

    def test_naive_timestamp_raises(self) -> None:
        with pytest.raises(ValueError, match="tz-aware"):
            _make_minimal_memory(event_timestamp=datetime(2026, 5, 14, 9, 0, 0))

    def test_lesson_500_char_cap(self) -> None:
        long_lesson = "x" * 501
        with pytest.raises(ValueError, match="500-char soft limit"):
            _make_minimal_memory(lesson=long_lesson)
        # 500 exactly accepted
        _make_minimal_memory(lesson="x" * 500)

    def test_embedding_wrong_dim_raises(self) -> None:
        # 1023 dim — wrong
        with pytest.raises(ValueError, match="1024-dim"):
            _make_minimal_memory(embedding=tuple(0.0 for _ in range(1023)))
        # 1024 dim — accepted
        _make_minimal_memory(embedding=tuple(0.0 for _ in range(1024)))

    def test_with_full_fields(self) -> None:
        emb = tuple(0.5 for _ in range(1024))
        outcome = RiskMemoryOutcome(pnl_1d=-0.03, pnl_5d=-0.02, retrospective_correctness="correct")
        m = RiskMemory(
            event_type="RapidDrop5min",
            symbol_id="600519.SH",
            event_timestamp=datetime(2026, 5, 14, 10, 30, 0, tzinfo=UTC),
            context_snapshot={"trigger": "5min drop -5.2%", "regime": "Bear"},
            action_taken=ActionTaken.STAGED_EXECUTED,
            outcome=outcome,
            lesson="Bear regime + 5min sharp drop → STAGED sell prevented -8% next-day loss",
            embedding=emb,
        )
        assert m.action_taken == ActionTaken.STAGED_EXECUTED
        assert m.outcome.retrospective_correctness == "correct"
        assert len(m.embedding) == 1024
        # Serialization round-trip safety
        ctx_j = m.context_snapshot_jsonable()
        oc_j = m.outcome_jsonable()
        import json  # noqa: PLC0415

        json.dumps(ctx_j)
        json.dumps(oc_j)


# ─────────────────────────────────────────────────────────────
# SimilarMemoryHit
# ─────────────────────────────────────────────────────────────


class TestSimilarMemoryHit:
    def test_frozen(self) -> None:
        import dataclasses  # noqa: PLC0415

        m = _make_minimal_memory()
        hit = SimilarMemoryHit(memory=m, cosine_similarity=0.85)
        assert hit.cosine_similarity == 0.85
        # frozen — assignment raises FrozenInstanceError per @dataclass(frozen=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            hit.cosine_similarity = 0.9  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────
# Repository (real-PG SAVEPOINT smoke per LL-157)
# ─────────────────────────────────────────────────────────────


def _connect_real_db() -> psycopg2.extensions.connection | None:
    try:
        from app.services.db import get_sync_conn  # noqa: PLC0415

        return get_sync_conn()
    except Exception:
        return None


@pytest.fixture
def pg_conn():
    """Real PG conn with rollback teardown — sustained LL-157 pattern.

    Each test wraps INSERT/queries in SAVEPOINT → ROLLBACK TO SAVEPOINT to
    avoid persisting test rows + isolate from sibling tests in same conn.
    """
    conn = _connect_real_db()
    if conn is None:
        pytest.skip("PG not available — skip repository smoke")
    yield conn
    conn.rollback()
    conn.close()


def _make_embedding(seed: int = 42) -> tuple[float, ...]:
    """Generate deterministic 1024-dim test embedding."""
    import random  # noqa: PLC0415

    rng = random.Random(seed)
    return tuple(rng.gauss(0, 1) for _ in range(1024))


class TestPersistRiskMemory:
    def test_persist_full_row_with_embedding(self, pg_conn) -> None:
        m = RiskMemory(
            event_type="LimitDown",
            symbol_id="600519.SH",
            event_timestamp=datetime(2026, 5, 14, 9, 30, 0, tzinfo=UTC),
            context_snapshot={"price": 100.0, "drop": -0.099},
            action_taken=ActionTaken.STAGED_EXECUTED,
            outcome=RiskMemoryOutcome(pnl_1d=-0.05, retrospective_correctness="correct"),
            lesson="Limit-down on 9.9% drop — STAGED sell at next-day open captured -5% loss",
            embedding=_make_embedding(seed=1),
        )
        cur = pg_conn.cursor()
        cur.execute("SAVEPOINT test_persist_full")
        try:
            mem_id = persist_risk_memory(pg_conn, m)
            assert mem_id > 0
            # Verify row landed
            cur.execute(
                "SELECT event_type, symbol_id, action_taken, lesson, "
                "       embedding IS NOT NULL AS has_emb "
                "  FROM risk_memory WHERE memory_id = %s",
                (mem_id,),
            )
            row = cur.fetchone()
            assert row[0] == "LimitDown"
            assert row[1] == "600519.SH"
            assert row[2] == "STAGED_executed"
            assert row[3].startswith("Limit-down on 9.9%")
            assert row[4] is True  # embedding populated
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT test_persist_full")
            cur.close()

    def test_persist_without_embedding(self, pg_conn) -> None:
        """Pre-RiskReflectorAgent state — embedding NULL allowed."""
        m = _make_minimal_memory()
        cur = pg_conn.cursor()
        cur.execute("SAVEPOINT test_no_emb")
        try:
            mem_id = persist_risk_memory(pg_conn, m)
            assert mem_id > 0
            cur.execute(
                "SELECT embedding IS NULL FROM risk_memory WHERE memory_id = %s",
                (mem_id,),
            )
            assert cur.fetchone()[0] is True
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT test_no_emb")
            cur.close()

    def test_persist_action_taken_check_constraint(self, pg_conn) -> None:
        """DDL CHECK rejects raw out-of-vocab action_taken (defense in depth).

        Model layer ActionTaken Enum prevents construction with bad value, so
        test goes raw SQL bypass model.
        """
        cur = pg_conn.cursor()
        cur.execute("SAVEPOINT test_bad_action")
        try:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO risk_memory (event_type, event_timestamp, "
                    "  context_snapshot, action_taken) "
                    "VALUES (%s, %s, %s::jsonb, %s)",
                    (
                        "LimitDown",
                        datetime(2026, 5, 14, 9, 0, tzinfo=UTC),
                        "{}",
                        "buy",
                    ),  # 'buy' not in vocab
                )
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT test_bad_action")
            cur.close()

    def test_persist_empty_event_type_check_constraint(self, pg_conn) -> None:
        """DDL CHECK chk_event_type_non_empty rejects empty string (defense in depth)."""
        cur = pg_conn.cursor()
        cur.execute("SAVEPOINT test_empty_evtype")
        try:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO risk_memory (event_type, event_timestamp, "
                    "  context_snapshot) VALUES (%s, %s, %s::jsonb)",
                    ("", datetime(2026, 5, 14, 9, 0, tzinfo=UTC), "{}"),
                )
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT test_empty_evtype")
            cur.close()


class TestRetrieveSimilar:
    def test_retrieve_empty_when_no_embeddings(self, pg_conn) -> None:
        """Pre-TB-3b state — 0 embeddings means retrieve returns []."""
        # Insert a memory WITHOUT embedding
        m = _make_minimal_memory(event_type="UniqueTestType_xyz_no_emb")
        cur = pg_conn.cursor()
        cur.execute("SAVEPOINT test_retrieve_empty")
        try:
            persist_risk_memory(pg_conn, m)
            # Retrieve — should skip the NULL-embedding row (per partial index + WHERE)
            hits = retrieve_similar(
                pg_conn,
                _make_embedding(),
                k=5,
                event_type="UniqueTestType_xyz_no_emb",
            )
            assert hits == []
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT test_retrieve_empty")
            cur.close()

    def test_retrieve_top_k_with_embeddings(self, pg_conn) -> None:
        """Insert 3 memories with embeddings, retrieve top-2 → ordered by sim DESC."""
        emb_a = _make_embedding(seed=1)  # query target
        emb_b = _make_embedding(seed=2)  # different
        emb_c = _make_embedding(seed=3)  # different

        cur = pg_conn.cursor()
        cur.execute("SAVEPOINT test_retrieve_topk")
        try:
            base_args = {
                "event_type": "UniqueTestRetrieveType_abc",
                "event_timestamp": datetime(2026, 5, 14, 9, 0, 0, tzinfo=UTC),
                "context_snapshot": {"t": "test"},
            }
            id_a = persist_risk_memory(
                pg_conn, RiskMemory(embedding=emb_a, symbol_id="600519.SH", **base_args)
            )
            id_b = persist_risk_memory(
                pg_conn, RiskMemory(embedding=emb_b, symbol_id="600520.SH", **base_args)
            )
            id_c = persist_risk_memory(
                pg_conn, RiskMemory(embedding=emb_c, symbol_id="600521.SH", **base_args)
            )

            # Query with emb_a → expect id_a first (self-similarity = 1.0)
            hits = retrieve_similar(
                pg_conn,
                emb_a,
                k=3,
                event_type="UniqueTestRetrieveType_abc",
            )
            assert len(hits) == 3
            assert hits[0].memory.memory_id == id_a
            assert hits[0].cosine_similarity == pytest.approx(1.0, abs=1e-4)
            # Subsequent hits have lower similarity
            assert hits[1].cosine_similarity < hits[0].cosine_similarity
            assert hits[2].cosine_similarity < hits[0].cosine_similarity
            # Top-k respects k limit
            hits_top1 = retrieve_similar(
                pg_conn,
                emb_a,
                k=1,
                event_type="UniqueTestRetrieveType_abc",
            )
            assert len(hits_top1) == 1

            # Verify ids returned by sets (don't lose ordering check above)
            all_ids = {h.memory.memory_id for h in hits}
            assert all_ids == {id_a, id_b, id_c}
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT test_retrieve_topk")
            cur.close()

    def test_retrieve_min_similarity_floor(self, pg_conn) -> None:
        """min_cosine_similarity floor filters out low-relevance hits."""
        emb_a = _make_embedding(seed=10)
        emb_far = _make_embedding(seed=999)  # random orthogonal-ish

        cur = pg_conn.cursor()
        cur.execute("SAVEPOINT test_min_sim")
        try:
            base_args = {
                "event_type": "UniqueTestMinSimType_zzz",
                "event_timestamp": datetime(2026, 5, 14, 9, 0, 0, tzinfo=UTC),
                "context_snapshot": {},
            }
            persist_risk_memory(pg_conn, RiskMemory(embedding=emb_a, **base_args))
            persist_risk_memory(pg_conn, RiskMemory(embedding=emb_far, **base_args))
            # Floor 0.99 — only emb_a (self) passes (cosine ~1.0); emb_far filtered out
            hits = retrieve_similar(
                pg_conn,
                emb_a,
                k=5,
                event_type="UniqueTestMinSimType_zzz",
                min_cosine_similarity=0.99,
            )
            assert len(hits) == 1
            assert hits[0].cosine_similarity > 0.99
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT test_min_sim")
            cur.close()

    def test_retrieve_wrong_dim_raises(self, pg_conn) -> None:
        """Query embedding must be 1024-dim (BGE-M3 per ADR-064 D2)."""
        wrong_dim = tuple(0.0 for _ in range(512))
        with pytest.raises(ValueError, match="1024-dim"):
            retrieve_similar(pg_conn, wrong_dim, k=5)

    def test_retrieve_invalid_k_raises(self, pg_conn) -> None:
        """k must be > 0."""
        with pytest.raises(ValueError, match="k must be > 0"):
            retrieve_similar(pg_conn, _make_embedding(), k=0)
