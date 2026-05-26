"""iter 175 MVP 4.7 Chunk 2 — shared rag_context_builder tests.

TDD: tests written FIRST against not-yet-implemented build_rag_context().
Expected fail: ModuleNotFoundError.

Phase J §1.4 enablement: extracts canonical `_gather_rag_top5` pattern from
risk_reflector_tasks.py:415-448 into a shared utility for the 4 RAG consumers
(NewsClassifier / Bull / Bear / RegimeJudge — wired iter 176/177).

Fail-soft contract (sibling sustained):
- compose_query exception OR rag.retrieve exception → "数据不足: ..." placeholder
- 0 hits → "数据不足: RAG returned 0 hits..." placeholder
- Hits returned → markdown table | cosine | event_type | symbol | lesson |
- lesson preview truncated to 80 chars + pipe-escape for table-safety
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_memory(event_type="LimitDown", symbol="600519", lesson="Test lesson"):
    """Build a mock RiskMemory."""
    m = MagicMock()
    m.event_type = event_type
    m.symbol_id = symbol
    m.lesson = lesson
    return m


def _make_hit(cosine, memory):
    """Build a mock SimilarMemoryHit."""
    h = MagicMock()
    h.cosine_similarity = cosine
    h.memory = memory
    return h


@pytest.fixture
def mock_rag():
    """Mock RiskMemoryRAG with controllable retrieve return."""
    return MagicMock()


@pytest.fixture
def sample_hits():
    return [
        _make_hit(0.95, _make_memory("LimitDown", "600519", "Lesson one body text")),
        _make_hit(0.87, _make_memory("RapidDrop", "000001", "Lesson two")),
        _make_hit(0.81, _make_memory("IndustryCorrelated", None, "Lesson three")),
    ]


def test_builds_query_via_compose_callback(mock_rag, sample_hits):
    """compose_query callback invoked once + result passed to rag.retrieve."""
    from app.services.risk.rag_context_builder import build_rag_context

    mock_rag.retrieve.return_value = sample_hits
    compose = MagicMock(return_value="news title + body")

    build_rag_context(mock_rag, compose, k=5)

    compose.assert_called_once_with()
    mock_rag.retrieve.assert_called_once()
    call_kwargs = mock_rag.retrieve.call_args.kwargs
    call_args = mock_rag.retrieve.call_args.args
    # Query may be positional OR keyword
    query_arg = call_args[0] if call_args else call_kwargs.get("query")
    assert query_arg == "news title + body"


def test_calls_rag_retrieve_with_k_and_event_type(mock_rag, sample_hits):
    """k and event_type propagated to rag.retrieve kwargs."""
    from app.services.risk.rag_context_builder import build_rag_context

    mock_rag.retrieve.return_value = sample_hits
    compose = MagicMock(return_value="query")

    build_rag_context(mock_rag, compose, k=3, event_type="LimitDown")

    kwargs = mock_rag.retrieve.call_args.kwargs
    assert kwargs.get("k") == 3
    assert kwargs.get("event_type") == "LimitDown"


def test_formats_hits_as_markdown_table(mock_rag, sample_hits):
    """3 hits → markdown table with header row + separator + 3 data rows."""
    from app.services.risk.rag_context_builder import build_rag_context

    mock_rag.retrieve.return_value = sample_hits
    compose = MagicMock(return_value="query")

    result = build_rag_context(mock_rag, compose, k=5)

    lines = result.split("\n")
    # Header + separator + 3 hit rows
    assert len(lines) >= 5
    assert "cosine" in lines[0] and "event_type" in lines[0] and "symbol" in lines[0]
    assert "---" in lines[1]
    assert "LimitDown" in result
    assert "600519" in result
    assert "0.950" in result or "0.95" in result  # cosine formatting tolerance


def test_fail_soft_returns_placeholder_on_empty(mock_rag):
    """rag.retrieve returning [] → '数据不足' placeholder string."""
    from app.services.risk.rag_context_builder import build_rag_context

    mock_rag.retrieve.return_value = []
    compose = MagicMock(return_value="query")

    result = build_rag_context(mock_rag, compose, k=5, event_type="LimitDown")

    assert "数据不足" in result
    assert "0 hits" in result or "no hits" in result.lower()
    assert "LimitDown" in result  # event_type filter cited in placeholder


def test_fail_soft_returns_placeholder_on_rag_exception(mock_rag):
    """rag.retrieve raise → '数据不足' placeholder with exception type + message."""
    from app.services.risk.rag_context_builder import build_rag_context

    mock_rag.retrieve.side_effect = RuntimeError("BGE-M3 model load failed")
    compose = MagicMock(return_value="query")

    result = build_rag_context(mock_rag, compose, k=5)

    assert "数据不足" in result
    assert "RuntimeError" in result
    assert "BGE-M3 model load failed" in result


def test_fail_soft_returns_placeholder_on_compose_exception(mock_rag):
    """compose_query callback raise → '数据不足' placeholder (sibling fail-soft contract)."""
    from app.services.risk.rag_context_builder import build_rag_context

    compose = MagicMock(side_effect=ValueError("missing context"))

    result = build_rag_context(mock_rag, compose, k=5)

    assert "数据不足" in result
    # rag.retrieve should NOT be called since compose failed first
    mock_rag.retrieve.assert_not_called()


def test_lesson_preview_truncated_and_pipe_escaped(mock_rag):
    """Lesson preview truncated to 80 chars + `|` escaped to avoid breaking markdown table."""
    from app.services.risk.rag_context_builder import build_rag_context

    long_lesson = "a" * 200 + " | pipe in middle | end"
    hits = [_make_hit(0.9, _make_memory("LimitDown", "600519", long_lesson))]
    mock_rag.retrieve.return_value = hits
    compose = MagicMock(return_value="query")

    result = build_rag_context(mock_rag, compose, k=5)

    # Find the data row (line starting with "| 0.9")
    data_row = next(l for l in result.split("\n") if l.startswith("| 0.9"))
    # No unescaped pipe in lesson column (lesson is between 3rd and 4th `|`)
    cells = data_row.split("|")
    lesson_cell = cells[4]  # idx 0='', 1='cosine', 2='event_type', 3='symbol', 4='lesson'
    # No raw pipe inside lesson (must be escaped)
    assert "\\|" in lesson_cell or "|" not in lesson_cell.replace("\\|", "")
    # Length truncated (rough check — < 100 chars)
    assert len(lesson_cell.strip()) < 100
