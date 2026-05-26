"""iter 178 MVP 4.7 Chunk 5 — RAG consumer integration smoke test.

Exercises end-to-end RAG wire on REAL production yaml templates (NOT tmp_path
fixtures used by iter 176/177 unit tests) to catch yaml-side regression caused
by iter 178 `{rag_context}` placeholder additions to 4 yamls:
- prompts/risk/news_classifier_v1.yaml
- prompts/risk/bull_agent_v1.yaml
- prompts/risk/bear_agent_v1.yaml
- prompts/risk/regime_judge_v1.yaml

Mock strategy: full MagicMock router + RAG (no real LLM / BGE-M3 / DB). Per
@pytest.mark.smoke marker for pre-push hook coverage (sibling
test_daily_reconciliation_smoke iter 167 pattern).

Sibling: iter 176/177 unit tests already cover service-level DI behavior.
This smoke test specifically catches REAL-YAML regression (e.g. wrong
placeholder name, missing format kwarg, yaml load fail).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from backend.qm_platform.llm.types import LLMResponse
from backend.qm_platform.news.base import NewsItem


def _make_news_item():
    return NewsItem(
        source="rsshub",
        timestamp=datetime(2026, 5, 26, 18, 0, tzinfo=UTC),
        title="iter 178 smoke test news",
        content="smoke test content body" * 5,
        url="https://example.com/news/smoke",
        symbol_id="600519",
        lang="zh",
    )


def _make_rag(marker: str = "SMOKE_RAG_MARKER"):
    """Mock RAG returning a single hit whose lesson contains the marker."""
    hit = MagicMock()
    hit.cosine_similarity = 0.95
    hit.memory = MagicMock(event_type="LimitDown", symbol_id="600519", lesson=marker)
    rag = MagicMock()
    rag.retrieve.return_value = [hit]
    return rag


def _make_classifier_response():
    return LLMResponse(
        content=json.dumps(
            {
                "sentiment_score": -0.5,
                "category": "利空",
                "urgency": "P1",
                "confidence": 0.8,
                "profile": "short",
            }
        ),
        model="deepseek-v4-flash",
        tokens_in=100,
        tokens_out=50,
        cost_usd=Decimal("0.0001"),
    )


@pytest.mark.smoke
def test_news_classifier_real_yaml_substitutes_rag_context():
    """News classifier production yaml (post iter 178 edit) substitutes {rag_context}."""
    from app.services.news.news_classifier_service import NewsClassifierService

    router = MagicMock()
    router.completion.return_value = _make_classifier_response()
    rag = _make_rag(marker="SMOKE_NEWS_LESSON_MARKER")

    # NewsClassifierService loads DEFAULT_PROMPT_PATH (production yaml)
    service = NewsClassifierService(router=router, rag=rag)
    service.classify(_make_news_item())

    messages = router.completion.call_args.kwargs["messages"]
    user_content = next(m for m in messages if m.role == "user").content
    # RAG marker from lesson must appear in user_content (proves {rag_context}
    # placeholder in production yaml correctly substituted)
    assert "SMOKE_NEWS_LESSON_MARKER" in user_content, (
        f"RAG lesson marker must appear via {{rag_context}} substitution; "
        f"got: {user_content[:500]!r}"
    )


@pytest.mark.smoke
def test_market_regime_real_yamls_substitute_rag_context():
    """Bull/Bear/Judge production yamls (post iter 178 edits) substitute {rag_context}."""
    from backend.app.services.risk.market_regime_service import MarketRegimeService
    from backend.qm_platform.risk.regime.agents import BearAgent, BullAgent, RegimeJudge
    from backend.qm_platform.risk.regime.interface import MarketIndicators

    bull_resp = LLMResponse(
        content=json.dumps(
            {"arguments": [{"argument": "a", "evidence": "e", "weight": 0.4}] * 3}
        ),
        model="deepseek-v4-pro",
        tokens_in=200, tokens_out=100, cost_usd=Decimal("0.0002"),
    )
    bear_resp = LLMResponse(
        content=json.dumps(
            {"arguments": [{"argument": "b", "evidence": "e", "weight": 0.4}] * 3}
        ),
        model="deepseek-v4-pro",
        tokens_in=200, tokens_out=100, cost_usd=Decimal("0.0002"),
    )
    judge_resp = LLMResponse(
        content=json.dumps({"regime": "Bull", "confidence": 0.7, "reasoning": "smoke"}),
        model="deepseek-v4-pro",
        tokens_in=300, tokens_out=80, cost_usd=Decimal("0.0003"),
    )
    router = MagicMock()
    router.completion.side_effect = [bull_resp, bear_resp, judge_resp]
    rag = _make_rag(marker="SMOKE_REGIME_LESSON_MARKER")

    indicators = MarketIndicators(
        timestamp=datetime(2026, 5, 26, 14, 30, tzinfo=UTC),
        sse_return=0.0185, hs300_return=0.0212,
        breadth_up=2800, breadth_down=1500,
        north_flow_cny=87.5, iv_50etf=0.185,
    )
    # MarketRegimeService default-constructs BullAgent/BearAgent/RegimeJudge
    # which load DEFAULT_PROMPT_PATH (production yamls).
    service = MarketRegimeService(
        router=router,
        bull_agent=BullAgent(router=router),
        bear_agent=BearAgent(router=router),
        judge=RegimeJudge(router=router),
        rag=rag,
    )
    service.classify(indicators, decision_id="smoke")

    # 3 router.completion calls (bull/bear/judge) — each must contain RAG marker
    assert router.completion.call_count == 3
    for i, call in enumerate(router.completion.call_args_list):
        messages = call.kwargs["messages"]
        user_content = next(m for m in messages if m.role == "user").content
        assert "SMOKE_REGIME_LESSON_MARKER" in user_content, (
            f"Agent {i} (bull/bear/judge) production yaml failed to substitute "
            f"{{rag_context}}; got: {user_content[:500]!r}"
        )


@pytest.mark.smoke
def test_real_yamls_backward_compat_when_rag_none():
    """All 4 production yamls + service rag=None default: no crash, no RAG marker leak."""
    from app.services.news.news_classifier_service import NewsClassifierService
    from backend.app.services.risk.market_regime_service import MarketRegimeService
    from backend.qm_platform.risk.regime.agents import BearAgent, BullAgent, RegimeJudge
    from backend.qm_platform.risk.regime.interface import MarketIndicators

    # NewsClassifier with rag=None
    router_news = MagicMock()
    router_news.completion.return_value = _make_classifier_response()
    news_service = NewsClassifierService(router=router_news)  # rag=None default
    news_service.classify(_make_news_item())  # should NOT raise
    news_user_content = next(
        m for m in router_news.completion.call_args.kwargs["messages"] if m.role == "user"
    ).content
    # rag_context resolves to "" — no markdown table separator
    assert "|---|---|" not in news_user_content

    # MarketRegimeService with rag=None
    router_regime = MagicMock()
    router_regime.completion.side_effect = [
        LLMResponse(
            content=json.dumps(
                {"arguments": [{"argument": "a", "evidence": "e", "weight": 0.4}] * 3}
            ),
            model="m", tokens_in=1, tokens_out=1, cost_usd=Decimal("0"),
        ),
        LLMResponse(
            content=json.dumps(
                {"arguments": [{"argument": "b", "evidence": "e", "weight": 0.4}] * 3}
            ),
            model="m", tokens_in=1, tokens_out=1, cost_usd=Decimal("0"),
        ),
        LLMResponse(
            content=json.dumps({"regime": "Neutral", "confidence": 0.5, "reasoning": "n"}),
            model="m", tokens_in=1, tokens_out=1, cost_usd=Decimal("0"),
        ),
    ]
    indicators = MarketIndicators(
        timestamp=datetime(2026, 5, 26, 14, 30, tzinfo=UTC),
        sse_return=0.01, hs300_return=0.01,
        breadth_up=1000, breadth_down=1000,
        north_flow_cny=0.0, iv_50etf=0.15,
    )
    regime_service = MarketRegimeService(
        router=router_regime,
        bull_agent=BullAgent(router=router_regime),
        bear_agent=BearAgent(router=router_regime),
        judge=RegimeJudge(router=router_regime),
        # rag=None default
    )
    regime_service.classify(indicators, decision_id="bc-smoke")  # should NOT raise

    for call in router_regime.completion.call_args_list:
        messages = call.kwargs["messages"]
        user_content = next(m for m in messages if m.role == "user").content
        assert "|---|---|" not in user_content, (
            f"RAG markdown separator must NOT appear with rag=None backward-compat path; "
            f"got: {user_content[:300]!r}"
        )
