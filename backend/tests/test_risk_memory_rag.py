"""V3 §5.4 RiskMemoryRAG orchestration tests (TB-3c).

Coverage:
  - retrieve() end-to-end flow: embed query + retrieve_similar + retention filter
  - DI factory pattern: EmbeddingService stub + conn_factory stub
  - Over-fetch math: k=5 + multiplier=3 → DB fetched k=15 (or hard cap 50)
  - default_k fallback when k=None
  - retention filter integration: 4-tier drops applied before trim-to-k
  - event_type filter passthrough
  - Fail-loud: k≤0, naive now, empty query (delegated to EmbeddingService)
  - Order preservation (cosine DESC)

LL-159 4-step preflight sustained — unit tests with DI mocks, 0 DB / 0 model load.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from qm_platform.risk.memory.embedding_service import EMBEDDING_DIM
from qm_platform.risk.memory.interface import RiskMemory, SimilarMemoryHit
from qm_platform.risk.memory.retention import DEFAULT_POLICY, RetentionPolicy

from app.services.risk.risk_memory_rag import RiskMemoryRAG

logger = logging.getLogger(__name__)

_NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubEmbeddingService:
    """Deterministic stub — encode(text) → 1024-dim tuple based on text hash."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def encode(self, text: str) -> tuple[float, ...]:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("stub encode failure")
        if not text:
            raise ValueError("encode: non-empty required")
        seed = hash(text) & 0xFFFFFFFF
        return tuple((seed % 1000) / 1000.0 + i * 1e-6 for i in range(EMBEDDING_DIM))


def _memory_at(age_days: float, *, event_type: str = "LimitDown") -> RiskMemory:
    ts = _NOW - timedelta(days=age_days)
    return RiskMemory(
        event_type=event_type,
        event_timestamp=ts,
        context_snapshot={"age_days": age_days},
        lesson=f"lesson age={age_days}",
    )


def _hit(age_days: float, similarity: float, **mem_kwargs) -> SimilarMemoryHit:
    return SimilarMemoryHit(
        memory=_memory_at(age_days, **mem_kwargs),
        cosine_similarity=similarity,
    )


def _conn_factory(_conn: Any = None) -> Callable[[], Any]:
    """Build conn_factory returning sentinel object (RAG doesn't use it
    directly — retrieve_similar is mocked)."""
    sentinel = _conn if _conn is not None else MagicMock(name="psycopg2_conn")
    return lambda: sentinel


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_basic_construction(self) -> None:
        rag = RiskMemoryRAG(
            embedding_service=_StubEmbeddingService(),
            conn_factory=_conn_factory(),
        )
        assert rag.default_k == 5
        assert rag.overfetch_multiplier == 3
        assert rag.retention_policy is DEFAULT_POLICY

    def test_custom_default_k(self) -> None:
        rag = RiskMemoryRAG(
            embedding_service=_StubEmbeddingService(),
            conn_factory=_conn_factory(),
            default_k=10,
        )
        assert rag.default_k == 10

    def test_custom_retention_policy(self) -> None:
        custom = RetentionPolicy(hot_max_days=3, warm_max_days=10, cold_max_days=30)
        rag = RiskMemoryRAG(
            embedding_service=_StubEmbeddingService(),
            conn_factory=_conn_factory(),
            retention_policy=custom,
        )
        assert rag.retention_policy.hot_max_days == 3


# ---------------------------------------------------------------------------
# retrieve() — end-to-end flow with mocked retrieve_similar
# ---------------------------------------------------------------------------


class TestRetrieve:
    def test_basic_retrieve_returns_filtered_topk(self, monkeypatch) -> None:
        """k=2: DB over-fetch 6, retention drops irrelevant, trim to 2."""
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())

        # Mock retrieve_similar to return 6 hits (over-fetch k=2*3=6).
        mock_retrieve = MagicMock(
            return_value=[
                _hit(age_days=1, similarity=0.95),  # HOT — keep
                _hit(age_days=3, similarity=0.85),  # HOT — keep
                _hit(age_days=20, similarity=0.55),  # WARM — drop (< 0.6)
                _hit(age_days=60, similarity=0.65),  # COLD — drop (< 0.7)
                _hit(age_days=200, similarity=0.75),  # ARCHIVE — drop (< 0.8)
                _hit(age_days=200, similarity=0.85),  # ARCHIVE — keep
            ]
        )
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            mock_retrieve,
        )

        out = rag.retrieve("query text", k=2, now=_NOW)
        assert len(out) == 2
        # First 2 of 3 keeps (cosine DESC order preserved through filter).
        assert out[0].cosine_similarity == 0.95
        assert out[1].cosine_similarity == 0.85

    def test_overfetch_multiplier_passed_to_retrieve_similar(self, monkeypatch) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(
            embedding_service=emb,
            conn_factory=_conn_factory(),
            overfetch_multiplier=4,
        )
        mock_retrieve = MagicMock(return_value=[])
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            mock_retrieve,
        )

        rag.retrieve("query", k=3, now=_NOW)
        # k=3, multiplier=4 → over-fetch 12
        kwargs = mock_retrieve.call_args.kwargs
        assert kwargs["k"] == 12

    def test_overfetch_hard_cap_50(self, monkeypatch) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(
            embedding_service=emb,
            conn_factory=_conn_factory(),
            overfetch_multiplier=10,
        )
        mock_retrieve = MagicMock(return_value=[])
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            mock_retrieve,
        )

        rag.retrieve("query", k=20, now=_NOW)  # 20*10=200, capped to 50
        kwargs = mock_retrieve.call_args.kwargs
        assert kwargs["k"] == 50

    def test_default_k_used_when_k_none(self, monkeypatch) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(
            embedding_service=emb, conn_factory=_conn_factory(), default_k=7
        )
        mock_retrieve = MagicMock(return_value=[])
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            mock_retrieve,
        )

        rag.retrieve("query", now=_NOW)
        # default_k=7, multiplier=3 → over-fetch 21
        kwargs = mock_retrieve.call_args.kwargs
        assert kwargs["k"] == 21

    def test_event_type_filter_passthrough(self, monkeypatch) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        mock_retrieve = MagicMock(return_value=[])
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            mock_retrieve,
        )

        rag.retrieve("query", k=5, event_type="RapidDrop", now=_NOW)
        assert mock_retrieve.call_args.kwargs["event_type"] == "RapidDrop"

    def test_min_cosine_similarity_none_passed(self, monkeypatch) -> None:
        """RAG always passes min_cosine_similarity=None; retention handles it."""
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        mock_retrieve = MagicMock(return_value=[])
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            mock_retrieve,
        )

        rag.retrieve("query", k=5, now=_NOW)
        assert mock_retrieve.call_args.kwargs["min_cosine_similarity"] is None

    def test_embedding_passed_to_retrieve_similar(self, monkeypatch) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        mock_retrieve = MagicMock(return_value=[])
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            mock_retrieve,
        )

        rag.retrieve("query text X", k=5, now=_NOW)
        # Positional arg 1 = query_embedding
        args = mock_retrieve.call_args.args
        assert len(args) == 2  # conn + query_embedding
        embedding = args[1]
        assert isinstance(embedding, tuple)
        assert len(embedding) == EMBEDDING_DIM
        # Same text encoded by embedding_service?
        assert emb.calls == ["query text X"]

    def test_conn_factory_called_per_retrieve(self, monkeypatch) -> None:
        emb = _StubEmbeddingService()
        call_count = {"n": 0}

        def factory():
            call_count["n"] += 1
            return MagicMock(name="conn")

        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=factory)
        mock_retrieve = MagicMock(return_value=[])
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            mock_retrieve,
        )

        rag.retrieve("q1", k=5, now=_NOW)
        rag.retrieve("q2", k=5, now=_NOW)
        assert call_count["n"] == 2

    def test_empty_retrieve_returns_empty(self, monkeypatch) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            MagicMock(return_value=[]),
        )
        assert rag.retrieve("query", k=5, now=_NOW) == []

    def test_all_filtered_out_returns_empty(self, monkeypatch) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        # All ARCHIVE with low sim → all dropped.
        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            MagicMock(
                return_value=[
                    _hit(age_days=200, similarity=0.1),
                    _hit(age_days=300, similarity=0.3),
                ]
            ),
        )
        assert rag.retrieve("query", k=5, now=_NOW) == []

    def test_now_default_to_utcnow_when_none(self, monkeypatch) -> None:
        """When now=None, RAG uses utcnow() — verify it's tz-aware."""
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        captured_now = {"val": None}

        def fake_filter(hits, now, policy):
            captured_now["val"] = now
            return hits

        monkeypatch.setattr(
            "qm_platform.risk.memory.repository.retrieve_similar",
            MagicMock(return_value=[]),
        )
        monkeypatch.setattr(
            "app.services.risk.risk_memory_rag.filter_by_retention",
            fake_filter,
        )

        rag.retrieve("query", k=5)
        assert captured_now["val"] is not None
        assert captured_now["val"].tzinfo is not None


# ---------------------------------------------------------------------------
# Fail-loud
# ---------------------------------------------------------------------------


class TestFailLoud:
    def test_k_zero_raises(self) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        with pytest.raises(ValueError, match="k must be > 0"):
            rag.retrieve("query", k=0, now=_NOW)

    def test_k_negative_raises(self) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        with pytest.raises(ValueError, match="k must be > 0"):
            rag.retrieve("query", k=-5, now=_NOW)

    def test_naive_now_raises(self) -> None:
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        naive = datetime(2026, 5, 14, 12, 0)
        with pytest.raises(ValueError, match="now must be tz-aware"):
            rag.retrieve("query", k=5, now=naive)

    def test_empty_query_text_propagates_value_error(self) -> None:
        """EmbeddingService raises ValueError → RAG propagates (no swallow)."""
        emb = _StubEmbeddingService()
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        with pytest.raises(ValueError):
            rag.retrieve("", k=5, now=_NOW)

    def test_embedding_failure_propagates(self) -> None:
        emb = _StubEmbeddingService(fail=True)
        rag = RiskMemoryRAG(embedding_service=emb, conn_factory=_conn_factory())
        with pytest.raises(RuntimeError, match="stub encode failure"):
            rag.retrieve("query", k=5, now=_NOW)
