"""V3 §5.4 BGEM3EmbeddingService tests (TB-3b).

Coverage:
  - Unit tests with DI mock model_factory (fast, no sentence-transformers import).
  - Real-model smoke tests gated by skip-if-cache-missing — verifies model loads
    + encode produces 1024-dim + deterministic + semantic similarity sane.

Fail-loud surface area per 铁律 33:
  - Empty / whitespace text → ValueError
  - Model load failure → RiskMemoryError
  - model.encode failure → RiskMemoryError
  - Non-numeric output → RiskMemoryError
  - Dim mismatch → RiskMemoryError

LL-159 4-step preflight 体例 sustained — unit tests pass without external deps,
real-model smoke verifies actual cached model + library.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any

import pytest
from qm_platform.risk.memory.embedding_service import (
    EMBEDDING_DIM,
    BGEM3EmbeddingService,
    EmbeddingService,
)
from qm_platform.risk.memory.interface import RiskMemoryError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubModel:
    """Minimal stub matching sentence_transformers.SentenceTransformer.encode contract.

    Returns a deterministic 1024-dim list based on text hash so we can verify
    determinism + dim contracts without loading 2.5GB BGE-M3.
    """

    def __init__(self, dim: int = EMBEDDING_DIM, fail_encode: bool = False) -> None:
        self._dim = dim
        self._fail_encode = fail_encode
        self.encode_call_count = 0
        self.last_normalize: bool | None = None
        self.last_text: str | None = None

    def encode(self, text: str, normalize_embeddings: bool = False) -> list[float]:
        self.encode_call_count += 1
        self.last_text = text
        self.last_normalize = normalize_embeddings
        if self._fail_encode:
            raise RuntimeError("stub encode failure")
        # Deterministic vector — same text + dim = same output.
        seed = hash(text) & 0xFFFFFFFF
        return [(seed % 1000) / 1000.0 + i * 1e-6 for i in range(self._dim)]


def _stub_factory(model: _StubModel):
    """Return a factory closure that records load calls + returns stub model."""
    calls: list[tuple[str, str]] = []

    def factory(model_name: str, cache_folder: str) -> _StubModel:
        calls.append((model_name, cache_folder))
        return model

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


def _find_repo_root() -> Path:
    """Find quantmind-v2 repo root by walking up from this test file."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "CLAUDE.md").exists() and (parent / "backend").exists():
            return parent
    # Fallback: assume backend/tests/ → ../..
    return here.parent.parent.parent


_REPO_ROOT = _find_repo_root()
_MODEL_CACHE_DIR = _REPO_ROOT / "models" / "bge-m3"


def _model_cache_exists() -> bool:
    """Check if BGE-M3 model cache exists for real-model smoke tests."""
    cache_root = _MODEL_CACHE_DIR / "models--BAAI--bge-m3"
    if not cache_root.exists():
        return False
    snapshots = cache_root / "snapshots"
    if not snapshots.exists():
        return False
    return any((snap / "config.json").exists() for snap in snapshots.iterdir())


_MODEL_CACHE_AVAILABLE = _model_cache_exists()


# ---------------------------------------------------------------------------
# Unit tests — DI mock model_factory (fast, no real model load)
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_bgem3_satisfies_embedding_service_protocol(self) -> None:
        stub = _StubModel()
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        assert isinstance(svc, EmbeddingService)


class TestEncodeBasic:
    def test_encode_returns_1024_tuple_of_floats(self) -> None:
        stub = _StubModel()
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        out = svc.encode("test text")
        assert isinstance(out, tuple)
        assert len(out) == EMBEDDING_DIM
        assert all(isinstance(x, float) for x in out)

    def test_encode_same_text_returns_same_output(self) -> None:
        stub = _StubModel()
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        out1 = svc.encode("limit down event")
        out2 = svc.encode("limit down event")
        assert out1 == out2

    def test_encode_passes_normalize_default_true(self) -> None:
        stub = _StubModel()
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        svc.encode("hello")
        assert stub.last_normalize is True

    def test_encode_normalize_false_respected(self) -> None:
        stub = _StubModel()
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub), normalize=False)
        svc.encode("hello")
        assert stub.last_normalize is False

    def test_encode_passes_text_through(self) -> None:
        stub = _StubModel()
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        svc.encode("A股市场大跌")
        assert stub.last_text == "A股市场大跌"


class TestFailLoud:
    def test_empty_text_raises_value_error(self) -> None:
        stub = _StubModel()
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        with pytest.raises(ValueError, match="non-empty"):
            svc.encode("")

    def test_whitespace_only_text_raises_value_error(self) -> None:
        stub = _StubModel()
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        with pytest.raises(ValueError, match="non-empty"):
            svc.encode("   \t\n  ")

    def test_empty_text_does_not_load_model(self) -> None:
        """Fast-fail before load — important for cold-start latency."""
        stub = _StubModel()
        factory = _stub_factory(stub)
        svc = BGEM3EmbeddingService(model_factory=factory)
        with pytest.raises(ValueError):
            svc.encode("")
        # Model not loaded (factory not called).
        assert factory.calls == []  # type: ignore[attr-defined]

    def test_model_load_failure_raises_risk_memory_error(self) -> None:
        def failing_factory(name: str, cache: str) -> Any:
            raise RuntimeError("model file corrupt")

        svc = BGEM3EmbeddingService(model_factory=failing_factory)
        with pytest.raises(RiskMemoryError, match="model load failed"):
            svc.encode("anything")

    def test_encode_runtime_failure_raises_risk_memory_error(self) -> None:
        stub = _StubModel(fail_encode=True)
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        with pytest.raises(RiskMemoryError, match="model.encode failed"):
            svc.encode("anything")

    def test_dim_mismatch_raises_risk_memory_error(self) -> None:
        stub = _StubModel(dim=512)  # Wrong dim — defensive case
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(stub))
        with pytest.raises(RiskMemoryError, match="output dim mismatch"):
            svc.encode("anything")

    def test_non_numeric_output_raises_risk_memory_error(self) -> None:
        class BadModel:
            def encode(self, text: str, normalize_embeddings: bool = False) -> Any:
                return ["not_a_number"] * EMBEDDING_DIM

        def factory(name: str, cache: str) -> Any:
            return BadModel()

        svc = BGEM3EmbeddingService(model_factory=factory)
        with pytest.raises(RiskMemoryError, match="convert model output"):
            svc.encode("anything")


class TestLazyLoad:
    def test_model_loaded_only_on_first_encode(self) -> None:
        stub = _StubModel()
        factory = _stub_factory(stub)
        svc = BGEM3EmbeddingService(model_factory=factory)
        # Construction does NOT load.
        assert factory.calls == []  # type: ignore[attr-defined]
        # First encode loads.
        svc.encode("first")
        assert len(factory.calls) == 1  # type: ignore[attr-defined]
        # Second encode reuses.
        svc.encode("second")
        assert len(factory.calls) == 1  # type: ignore[attr-defined]
        # Stub recorded 2 encode calls.
        assert stub.encode_call_count == 2

    def test_concurrent_first_encode_loads_only_once(self) -> None:
        """Double-checked locking — 10 threads racing first encode = 1 load."""
        stub = _StubModel()
        factory = _stub_factory(stub)
        svc = BGEM3EmbeddingService(model_factory=factory)

        barrier = threading.Barrier(10)

        def worker() -> None:
            barrier.wait()  # All threads start near-simultaneously.
            svc.encode("concurrent text")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(factory.calls) == 1, (  # type: ignore[attr-defined]
            f"Model loaded {len(factory.calls)} times "  # type: ignore[attr-defined]
            f"(expected 1 — double-checked lock failure)"
        )
        assert stub.encode_call_count == 10


class TestConstructorDefaults:
    def test_default_model_name(self) -> None:
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(_StubModel()))
        assert svc.model_name == "BAAI/bge-m3"

    def test_default_cache_folder_resolves_to_repo_models_bge_m3(self) -> None:
        """PR #340 MEDIUM 1 reviewer-fix: default cache_folder resolves to
        absolute repo-rooted path (CWD-independent) instead of relative
        `./models/bge-m3` which broke under Servy / Celery process CWDs.
        """
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(_StubModel()))
        cache = Path(svc.cache_folder)
        # When invoked from repo root, the resolver finds CLAUDE.md +
        # backend/ markers and returns absolute path.
        assert cache.is_absolute() or svc.cache_folder == "./models/bge-m3", (
            f"cache_folder should resolve to absolute path or fallback "
            f"literal, got {svc.cache_folder!r}"
        )
        # Path ends with models/bge-m3 (platform-agnostic check).
        assert cache.name == "bge-m3"
        assert cache.parent.name == "models"

    def test_default_normalize_true(self) -> None:
        svc = BGEM3EmbeddingService(model_factory=_stub_factory(_StubModel()))
        assert svc.normalize is True

    def test_factory_receives_configured_paths(self) -> None:
        stub = _StubModel()
        factory = _stub_factory(stub)
        svc = BGEM3EmbeddingService(
            model_factory=factory,
            model_name="custom/model",
            cache_folder="/tmp/cache",
        )
        svc.encode("trigger load")
        assert factory.calls == [("custom/model", "/tmp/cache")]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Real-model smoke (skip if cache missing)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _MODEL_CACHE_AVAILABLE,
    reason="BGE-M3 model cache not found at ./models/bge-m3/ — Phase A install required",
)
class TestRealModelSmoke:
    """Smoke against actual sentence-transformers + cached BGE-M3 model.

    Skipped automatically when cache missing — preserves CI portability while
    validating production wire on developer machine post-Phase A install.

    Session 53+19 smoke verified:
      - 1024-dim output ✓
      - 中文 cross-paraphrase similarity 0.84 ✓
      - 中 vs 英 unrelated similarity 0.40 ✓
    """

    @pytest.fixture(scope="class")
    def service(self) -> BGEM3EmbeddingService:
        # Real factory path — no model_factory injection. Use absolute cache
        # path so pytest cwd (backend/) doesn't break model lookup.
        return BGEM3EmbeddingService(cache_folder=str(_MODEL_CACHE_DIR))

    def test_real_encode_returns_1024_floats(self, service: BGEM3EmbeddingService) -> None:
        out = service.encode("A股市场今日大涨 +3.5%")
        assert len(out) == EMBEDDING_DIM
        assert all(isinstance(x, float) for x in out)
        # Normalized vectors should have L2 norm ≈ 1
        norm = math.sqrt(sum(x * x for x in out))
        assert 0.99 < norm < 1.01, f"normalized vector L2 norm = {norm} (expected ≈ 1)"

    def test_real_encode_deterministic(self, service: BGEM3EmbeddingService) -> None:
        """Same text twice returns identical (or near-identical) output."""
        out1 = service.encode("跌停事件复盘")
        out2 = service.encode("跌停事件复盘")
        # Allow tiny FP drift but should be effectively identical.
        max_diff = max(abs(a - b) for a, b in zip(out1, out2, strict=True))
        assert max_diff < 1e-5, f"non-deterministic encode: max diff = {max_diff}"

    def test_real_semantic_similarity_chinese_paraphrase(
        self, service: BGEM3EmbeddingService
    ) -> None:
        """Paraphrase pair similarity > unrelated pair similarity."""
        para_a = service.encode("股票跌停, 卖出止损")
        para_b = service.encode("股价触及跌停板, 应立即卖出止损")
        unrelated = service.encode("苹果手机价格今日上涨")

        # Cosine on already-normalized vectors = dot product.
        sim_para = sum(a * b for a, b in zip(para_a, para_b, strict=True))
        sim_unrelated = sum(a * b for a, b in zip(para_a, unrelated, strict=True))

        assert sim_para > sim_unrelated, (
            f"semantic ordering wrong: paraphrase sim={sim_para:.4f} "
            f"<= unrelated sim={sim_unrelated:.4f}"
        )
        # Sanity: paraphrase should be reasonably similar (BGE-M3 typical 0.7-0.9).
        assert sim_para > 0.6, f"paraphrase similarity too low: {sim_para:.4f}"
