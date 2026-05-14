"""V3 §5.4 BGE-M3 EmbeddingService — single-text encode (TB-3b sprint).

Concrete service module: holds sentence-transformers BGE-M3 model state +
encodes risk memory `lesson || context_summary` texts → 1024-dim tuple
(per ADR-064 D2 BGE-M3 sustained).

3-layer architecture per package docstring:
  - interface.py (TB-3a, 已 merged): pure dataclass + Enum contract (Engine PURE)
  - repository.py (TB-3a, 已 merged): persist + retrieve via PG + pgvector
  - **embedding_service.py (本 PR, TB-3b): BGE-M3 model wire — model load + encode**
  - rag.py (TB-3c, 留): RiskMemoryRAG.retrieve orchestration

铁律 31 nuance: This module touches concrete model state (sentence-transformers
SentenceTransformer instance) — strictly speaking it's NOT pure compute since
it loads ~2.5GB model file + holds GPU/CPU state. However, the V3 architecture
sustained from V3 §5.4 + ADR-064 D2 places this alongside the memory package
(not in app/services) because:
  - The encode operation IS deterministic given fixed model + input (functional)
  - Caller (TB-3c rag service) injects this service — DI boundary preserved
  - Model load is lazy + reusable (1 load, N encodes) — amortized cost

DI factory pattern sustained (TB-2e DefaultIndicatorsProvider `tushare_factory` 体例):
  - Default: `from sentence_transformers import SentenceTransformer` + auto-load
  - Test: inject `model_factory` returning stub model with `encode` method

Fail-loud per 铁律 33:
  - Model load failure → RiskMemoryError (sustained interface.py exception)
  - Empty text → ValueError
  - Encode failure → RiskMemoryError chained
  - Output dim mismatch → RiskMemoryError (defensive — should not happen for BGE-M3)

关联 V3: §5.4 (Risk Memory RAG) + ADR-064 D2 (BGE-M3 1024-dim sustained)
关联 ADR: ADR-064 (D2 BGE-M3) / ADR-068 候选 (TB-3 sprint cumulative)
关联 铁律: 31 (Engine PURE nuance) / 32 (Service 不 commit — N/A 本 PR) /
  33 (fail-loud) / 24 (单一职责 — 仅 encode)
关联 LL: LL-159 (4-step preflight) / LL-160 (DI factory 体例) sustained
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# EMBEDDING_DIM (BGE-M3 1024-dim, ADR-064 D2 + ADR-068 D2) is the single source
# of truth in `interface.py` — imported here so existing callers that reference
# `embedding_service.EMBEDDING_DIM` keep working (TB-5c batch: constant
# consolidated into the PURE interface module, resolving the TB-3b reviewer LOW).
from .interface import EMBEDDING_DIM

logger = logging.getLogger(__name__)

# Default BGE-M3 model identifier per Session 53+19 Phase A install.
_DEFAULT_MODEL_NAME: str = "BAAI/bge-m3"


def _resolve_default_cache_folder() -> str:
    """Resolve default model cache folder to repo-relative absolute path.

    Reviewer-fix (PR #340 MEDIUM 1): the previous default `./models/bge-m3` is
    CWD-dependent — Servy uvicorn process CWD differs from Celery / script
    invocations. Walk up from this module file to find repo root (containing
    `CLAUDE.md` + `backend/`), join `models/bge-m3`. Caller can still override
    via `cache_folder=...` for tests / alternate install locations.

    Fallback: if repo markers not found (e.g. installed as wheel), return the
    original relative path `./models/bge-m3` — caller MUST then pass absolute.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "CLAUDE.md").exists() and (parent / "backend").is_dir():
            return str(parent / "models" / "bge-m3")
    return "./models/bge-m3"


_DEFAULT_CACHE_FOLDER: str = _resolve_default_cache_folder()


@runtime_checkable
class EmbeddingService(Protocol):
    """V3 §5.4 single-text encode contract — caller-facing.

    Implementations:
      - BGEM3EmbeddingService (本模块): production BGE-M3 via sentence-transformers
      - (留 TB-3c+ test fixture): deterministic stub for unit tests / replay

    Contract:
      - encode(text) returns exactly EMBEDDING_DIM-length tuple of float
      - Same input MUST return same output (deterministic) under fixed model
      - Empty / whitespace text raises ValueError (fail-loud per 铁律 33)

    Reviewer-note (PR #340 MEDIUM 2): `@runtime_checkable` here is intentional +
    diverges from sibling risk modules (intraday.py / qmt_fallback.py) which
    explicitly avoid it. Justification: this Protocol declares a SINGLE method
    (`encode`), so structural `isinstance()` check is safe — there is no risk
    of partial-implementation silently satisfying isinstance + then failing at
    call site (the multi-method Protocol concern that motivates the sibling
    modules' choice). Used at DI composition boundary for fail-loud validation
    when TB-3c rag service wires this in.
    """

    def encode(self, text: str) -> tuple[float, ...]:
        """Encode a single text → 1024-dim embedding tuple."""
        ...


class BGEM3EmbeddingService:
    """Production BGE-M3 EmbeddingService — sentence-transformers wire.

    Lazy model load (first encode() call) + thread-safe singleton-per-instance
    via threading.Lock (反 race condition under FastAPI worker concurrency).

    Args:
        model_name: HuggingFace repo / local path. Default "BAAI/bge-m3".
            If pre-cached at cache_folder, no network fetch needed.
        cache_folder: HuggingFace cache root (sentence-transformers honors
            HF_HUB_CACHE-equivalent override). Default "./models/bge-m3"
            (Session 53+19 Phase A pre-download location).
        normalize: pass `normalize_embeddings=True` to model.encode →
            unit-norm vectors. Default True — reduces numerical drift +
            simplifies downstream cosine math (though pgvector `<=>` operator
            handles non-normalized vectors correctly per pgvector docs).
        model_factory: optional DI hook for tests — Callable[(model_name,
            cache_folder), Any] returning a stub with `.encode(text,
            normalize_embeddings=bool)` method. None = use sentence_transformers
            SentenceTransformer (default production path).

    Thread-safety:
      - encode() is concurrency-safe (model.encode is thread-safe per
        sentence-transformers docs once loaded).
      - _ensure_loaded() uses double-checked-locking on self._lock.

    Memory cost: ~2.5GB resident once loaded. Caller should hold one
    instance per process (TB-3c rag service will own this).
    """

    def __init__(
        self,
        *,
        model_name: str = _DEFAULT_MODEL_NAME,
        cache_folder: str = _DEFAULT_CACHE_FOLDER,
        normalize: bool = True,
        model_factory: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_folder = cache_folder
        self.normalize = normalize
        self._model_factory = model_factory
        self._model: Any | None = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> Any:
        """Lazy load + return the underlying model (double-checked locking).

        First call: actually loads (~3-5s on warm cache, longer on cold).
        Subsequent calls: O(1) read after fast-path None check.

        Raises:
            RiskMemoryError: model load failure (chain original cause).
        """
        # Fast path — already loaded.
        if self._model is not None:
            return self._model

        with self._lock:
            # Re-check inside lock (another thread may have loaded between
            # outer None check and lock acquisition).
            if self._model is not None:
                return self._model

            logger.info(
                "[risk-memory] loading BGE-M3 model name=%s cache=%s "
                "(first encode call — ~3-5s warm / longer cold)",
                self.model_name,
                self.cache_folder,
            )
            try:
                if self._model_factory is not None:
                    model = self._model_factory(self.model_name, self.cache_folder)
                else:
                    # Local import — defer heavy sentence-transformers import
                    # until actually needed (helps test suite startup + repository.py
                    # / interface.py imports don't pay this cost).
                    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                    model = SentenceTransformer(
                        self.model_name,
                        cache_folder=self.cache_folder,
                    )
            except Exception as exc:
                # Fail-loud per 铁律 33 + wrap in RiskMemoryError so callers
                # (TB-3c rag service) can catch single exception type.
                from .interface import RiskMemoryError  # noqa: PLC0415

                raise RiskMemoryError(
                    f"BGEM3EmbeddingService: model load failed "
                    f"(name={self.model_name!r}, cache={self.cache_folder!r})"
                ) from exc

            self._model = model
            logger.info("[risk-memory] BGE-M3 model loaded successfully")
            return self._model

    def encode(self, text: str) -> tuple[float, ...]:
        """Encode a single text → 1024-dim float tuple (BGE-M3 contract).

        Args:
            text: non-empty string (typically `lesson || context_summary`
                per V3 §5.4 line 706 sediment 体例). Whitespace-only treated
                as empty → ValueError.

        Returns:
            Tuple of EMBEDDING_DIM (1024) Python floats.

        Raises:
            ValueError: empty / whitespace-only text (fail-loud per 铁律 33).
            RiskMemoryError: model load failure OR encode failure OR output
                dim mismatch (defensive — BGE-M3 always returns 1024 but
                schema drift would break downstream pgvector cast).
        """
        if not text or not text.strip():
            raise ValueError(
                "BGEM3EmbeddingService.encode: text must be non-empty "
                "(whitespace-only rejected per 铁律 33 fail-loud)"
            )

        model = self._ensure_loaded()

        try:
            vec = model.encode(text, normalize_embeddings=self.normalize)
        except Exception as exc:
            from .interface import RiskMemoryError  # noqa: PLC0415

            raise RiskMemoryError(
                f"BGEM3EmbeddingService.encode: model.encode failed "
                f"(text_len={len(text)}, normalize={self.normalize})"
            ) from exc

        # sentence-transformers returns numpy.ndarray of shape (D,) for single text.
        # Convert to plain Python tuple[float, ...] to satisfy interface.py
        # RiskMemory.embedding type contract (tuple[float, ...] | None) +
        # to decouple downstream code from numpy dtype quirks.
        try:
            out = tuple(float(x) for x in vec)
        except (TypeError, ValueError) as exc:
            from .interface import RiskMemoryError  # noqa: PLC0415

            raise RiskMemoryError(
                f"BGEM3EmbeddingService.encode: failed to convert model output "
                f"to tuple[float] (type={type(vec).__name__})"
            ) from exc

        if len(out) != EMBEDDING_DIM:
            from .interface import RiskMemoryError  # noqa: PLC0415

            raise RiskMemoryError(
                f"BGEM3EmbeddingService.encode: output dim mismatch — "
                f"expected {EMBEDDING_DIM} (BGE-M3 per ADR-064 D2), "
                f"got {len(out)}. Schema drift / wrong model?"
            )

        return out
