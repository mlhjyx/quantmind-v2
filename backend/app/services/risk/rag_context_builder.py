"""iter 175 MVP 4.7 Chunk 2 — shared rag_context_builder for 4 RAG consumers.

Phase J §1.4 enablement: generalizes the canonical `_gather_rag_top5` pattern
from `risk_reflector_tasks.py:415-448` into a shared utility. Consumed by
NewsClassifier / Bull / Bear / RegimeJudge in iter 176/177 chunks 3+4 wire.

Design (sibling sustained):
- compose_query callback: caller-supplied closure that returns the query
  string from caller-specific context (news title+body / regime indicators /
  bull-bear args). Decouples query composition from retrieval.
- Fail-soft per-source: compose OR retrieve exception → "数据不足: ..." placeholder
  (drop-in safe for LLM prompt injection; downstream prompt can still parse).
- Markdown table format: header + separator + 1 row per hit (cosine /
  event_type / symbol / lesson preview).
- lesson preview: truncated to 80 chars + pipe-escape + newline-collapse to
  avoid breaking the surrounding markdown table.
- 铁律 33: fail-soft is intentional (LLM degrades gracefully on RAG outage)
  but logged for ops follow-up.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_HEADER: tuple[str, ...] = ("cosine", "event_type", "symbol", "lesson")


def build_rag_context(
    rag: Any,
    compose_query: Callable[[], str],
    *,
    k: int = 5,
    event_type: str | None = None,
    table_header: tuple[str, ...] = _DEFAULT_HEADER,
) -> str:
    """Build markdown-formatted RAG context for LLM prompt injection.

    Generalizes risk_reflector_tasks._gather_rag_top5 pattern. Caller passes:
      - rag: RiskMemoryRAG instance (shared singleton via worker bootstrap)
      - compose_query: callback returning query string from caller context
      - k: top-k hits (default 5)
      - event_type: optional filter (e.g. "LimitDown" for narrow domain recall)

    Returns:
        Markdown-table string with hits, OR "数据不足: ..." placeholder on
        empty hits / exceptions. Always safe to substitute into prompt template.

    Fail-soft contract (sustained sibling _gather_rag_top5):
        - compose_query raise → placeholder, rag.retrieve NOT called
        - rag.retrieve raise → placeholder with exception type + message
        - 0 hits → placeholder noting filter context
    """
    try:
        query = compose_query()
    except Exception as e:  # noqa: BLE001 — fail-soft per-source
        logger.warning("[rag-context-builder] compose_query failed (fail-soft): %s", e)
        return f"数据不足: compose_query 失败 ({type(e).__name__}: {e})"

    try:
        hits = rag.retrieve(query, k=k, event_type=event_type)
    except Exception as e:  # noqa: BLE001 — fail-soft per-source
        logger.warning("[rag-context-builder] retrieve failed (fail-soft): %s", e)
        return f"数据不足: RAG retrieve 失败 ({type(e).__name__}: {e})"

    if not hits:
        filt = f"event_type={event_type!r}" if event_type else "(no filter)"
        return f"数据不足: RAG returned 0 hits for query {filt}"

    lines: list[str] = []
    # Header row + separator
    lines.append("| " + " | ".join(table_header) + " |")
    lines.append("|" + "|".join(["---"] * len(table_header)) + "|")

    for hit in hits:
        m = hit.memory
        lesson_raw = m.lesson or "(no lesson)"
        # Truncate to 80 + escape pipes + collapse newlines for table-safety
        lesson_preview = lesson_raw[:80] + ("..." if len(lesson_raw) > 80 else "")
        lesson_preview = lesson_preview.replace("|", "\\|").replace("\n", " ")
        symbol = m.symbol_id or "—"
        lines.append(
            f"| {hit.cosine_similarity:.3f} | {m.event_type} | {symbol} | {lesson_preview} |"
        )

    return "\n".join(lines)
