"""iter 176 MVP 4.7 Chunk 3 — NewsClassifier RAG wire tests.

TDD: tests written FIRST against not-yet-modified NewsClassifierService.
Expected fail: rag DI param + build_rag_context call + rag_context substitution
not yet implemented.

Phase J §1.4 wire: NewsClassifier classify() calls build_rag_context() to
retrieve top-5 similar news / risk events from risk_memory, then substitutes
the markdown table into the user prompt template for LLM augmentation per
V3 §5.4 design intent (L1 push augmentation).

Sibling pattern: rag_context_builder iter 175 (PR #504) shared utility.
Fail-soft contract sustained: rag.retrieve exception → "数据不足: ..." placeholder
auto-propagated by build_rag_context internals.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import yaml

from backend.qm_platform.llm.types import LLMResponse
from backend.qm_platform.news.base import NewsItem

# ─────────────────────────── Fixtures ───────────────────────────


@pytest.fixture
def sample_news_item():
    """Build NewsItem dataclass (sub-PR 1-6 sediment, qm_platform.news.base)."""
    return NewsItem(
        source="rsshub",
        timestamp=datetime(2026, 5, 26, 18, 0, tzinfo=UTC),
        title="LimitDown 600519 maotai 跌停",
        content="贵州茅台 600519 今日跌停, 资金净流出 5 亿。" * 30,  # >200 chars
        url="https://example.com/news/1",
        symbol_id="600519",
        lang="zh",
    )


@pytest.fixture
def mock_router():
    """Mock LiteLLMRouter returning valid JSON classification."""
    router = MagicMock()
    router.completion.return_value = LLMResponse(
        content=json.dumps(
            {
                "sentiment_score": -0.8,
                "category": "利空",  # VALID_CATEGORIES per news_classifier_service.py:80
                "urgency": "P0",  # VALID_URGENCIES per news_classifier_service.py:83
                "confidence": 0.92,
                "profile": "short",  # VALID_PROFILES per news_classifier_service.py:86
            }
        ),
        model="deepseek-v4-flash",
        tokens_in=100,
        tokens_out=50,
        cost_usd=Decimal("0.0001"),
    )
    return router


@pytest.fixture
def tmp_yaml_with_rag_placeholder(tmp_path):
    """Write a yaml prompt template that includes {rag_context} placeholder."""
    yaml_path = tmp_path / "news_classifier_v1.yaml"
    yaml_data = {
        "version": "v1",
        "description": "test classifier with rag",
        "system_prompt": "You are a news classifier.",
        "user_template": (
            "Source: {source}\nTime: {timestamp}\nTitle: {title}\n"
            "Content: {content}\nURL: {url}\nSymbol: {symbol_id}\nLang: {lang}\n\n"
            "RAG context (历史相似事件):\n{rag_context}\n\n"
            "Classify the above news."
        ),
    }
    yaml_path.write_text(yaml.dump(yaml_data), encoding="utf-8")
    return yaml_path


@pytest.fixture
def mock_rag():
    """Mock RiskMemoryRAG instance."""
    rag = MagicMock()

    # Default: returns 2 hits (with retrieve() interface)
    hit1 = MagicMock()
    hit1.cosine_similarity = 0.92
    hit1.memory = MagicMock(event_type="LimitDown", symbol_id="600519", lesson="茅台跌停 lesson one")
    hit2 = MagicMock()
    hit2.cosine_similarity = 0.85
    hit2.memory = MagicMock(event_type="RapidDrop", symbol_id="000001", lesson="平安跌停 lesson two")

    rag.retrieve.return_value = [hit1, hit2]
    return rag


# ─────────────────────────── Tests ───────────────────────────


def test_classify_calls_build_rag_context_when_rag_di_provided(
    sample_news_item, mock_router, tmp_yaml_with_rag_placeholder, mock_rag
):
    """When rag DI provided, classify() must invoke RAG retrieval via build_rag_context."""
    from app.services.news.news_classifier_service import NewsClassifierService

    service = NewsClassifierService(
        router=mock_router,
        prompt_path=tmp_yaml_with_rag_placeholder,
        rag=mock_rag,
    )

    service.classify(sample_news_item)

    # rag.retrieve was called (build_rag_context internals)
    assert mock_rag.retrieve.called, "RAG retrieve must be called when rag DI provided"


def test_classify_passes_rag_context_to_yaml_template(
    sample_news_item, mock_router, tmp_yaml_with_rag_placeholder, mock_rag
):
    """The user message content must include the RAG markdown table after classify()."""
    from app.services.news.news_classifier_service import NewsClassifierService

    service = NewsClassifierService(
        router=mock_router,
        prompt_path=tmp_yaml_with_rag_placeholder,
        rag=mock_rag,
    )

    service.classify(sample_news_item)

    # Inspect what was sent to the LLM router
    router_call_kwargs = mock_router.completion.call_args.kwargs
    messages = router_call_kwargs["messages"]
    user_content = next(m for m in messages if m.role == "user").content
    # RAG markdown table includes cosine + event_type + symbol + lesson
    assert "0.920" in user_content or "0.92" in user_content, (
        f"RAG cosine score must appear in user content; got: {user_content[:500]!r}"
    )
    assert "LimitDown" in user_content or "茅台跌停" in user_content, (
        "RAG hit event_type or lesson must appear in user content"
    )


def test_classify_handles_rag_failure_gracefully(
    sample_news_item, mock_router, tmp_yaml_with_rag_placeholder
):
    """When rag.retrieve raises, fail-soft '数据不足' placeholder propagated to template."""
    from app.services.news.news_classifier_service import NewsClassifierService

    failing_rag = MagicMock()
    failing_rag.retrieve.side_effect = RuntimeError("BGE-M3 GPU OOM")

    service = NewsClassifierService(
        router=mock_router,
        prompt_path=tmp_yaml_with_rag_placeholder,
        rag=failing_rag,
    )

    # Should NOT raise — fail-soft via build_rag_context internal try/except
    service.classify(sample_news_item)

    router_call_kwargs = mock_router.completion.call_args.kwargs
    messages = router_call_kwargs["messages"]
    user_content = next(m for m in messages if m.role == "user").content
    assert "数据不足" in user_content, (
        f"Fail-soft placeholder must propagate to user content; got: {user_content[:500]!r}"
    )


def test_classify_works_without_rag_di_backward_compat(
    sample_news_item, mock_router, tmp_yaml_with_rag_placeholder
):
    """When rag=None (default), classify works as before (backward compat); no retrieve call."""
    from app.services.news.news_classifier_service import NewsClassifierService

    service = NewsClassifierService(
        router=mock_router,
        prompt_path=tmp_yaml_with_rag_placeholder,
        # rag=None implicit
    )

    # Should NOT raise even though yaml has {rag_context} placeholder
    result = service.classify(sample_news_item)

    assert result is not None
    router_call_kwargs = mock_router.completion.call_args.kwargs
    messages = router_call_kwargs["messages"]
    user_content = next(m for m in messages if m.role == "user").content
    # rag_context should resolve to empty string OR a "RAG not configured" placeholder.
    # Point: no exception, AND no actual RAG markdown table content. Use markdown table
    # separator `|---|---|` (RAG context-builder header line) as the regression guard —
    # title "LimitDown" is part of news content itself so cannot be used as RAG marker.
    assert "|---|---|" not in user_content, (
        f"RAG markdown table separator must NOT appear when rag=None; got: {user_content[:300]!r}"
    )
    assert "0.920" not in user_content  # No RAG cosine score formatting


def test_classify_compose_query_uses_title_and_content(
    sample_news_item, mock_router, tmp_yaml_with_rag_placeholder, mock_rag
):
    """compose_query lambda must produce query containing title + content snippet (first 200 chars)."""
    from app.services.news.news_classifier_service import NewsClassifierService

    service = NewsClassifierService(
        router=mock_router,
        prompt_path=tmp_yaml_with_rag_placeholder,
        rag=mock_rag,
    )

    service.classify(sample_news_item)

    # Inspect query passed to rag.retrieve
    rag_call_args = mock_rag.retrieve.call_args.args
    rag_call_kwargs = mock_rag.retrieve.call_args.kwargs
    query = rag_call_args[0] if rag_call_args else rag_call_kwargs.get("query")
    assert sample_news_item.title in query, (
        f"compose_query must include title; got: {query[:200]!r}"
    )
    # Content snippet (first 200 chars) should be present
    content_snippet = sample_news_item.content[:200]
    assert content_snippet[:50] in query, (
        f"compose_query must include content snippet; got: {query[:200]!r}"
    )
    # k=5 default
    assert rag_call_kwargs.get("k") == 5
