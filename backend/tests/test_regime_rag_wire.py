"""iter 177 MVP 4.7 Chunk 4 — Bull/Bear/Judge RAG wire tests.

TDD: tests written FIRST against not-yet-modified BullAgent/BearAgent/RegimeJudge +
MarketRegimeService. Expected fail: rag_context kwarg not yet accepted by _build_messages,
rag DI not yet on MarketRegimeService.

Phase J §1.4 Chunk 4: 3 regime agents collapsed into single chunk per architect
design. MarketRegimeService.classify() retrieves RAG context ONCE per call via
build_rag_context (iter 175 Chunk 2 shared utility), passes shared rag_context
str to bull/bear/judge agents — saves 2 BGE-M3 retrieves per classify().

Sibling pattern: iter 176 NewsClassifier RAG wire (PR #505) — DI via service-level
constructor, fail-soft sustained, backward-compat preserved (rag=None default).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import yaml

from backend.qm_platform.llm.types import LLMResponse

SHANGHAI_TZ = UTC


# ─────────────────────────── Fixtures ───────────────────────────


@pytest.fixture
def sample_indicators():
    from backend.qm_platform.risk.regime.interface import MarketIndicators

    return MarketIndicators(
        timestamp=datetime(2026, 5, 26, 14, 30, tzinfo=SHANGHAI_TZ),
        sse_return=0.0185,
        hs300_return=0.0212,
        breadth_up=2800,
        breadth_down=1500,
        north_flow_cny=87.5,
        iv_50etf=0.185,
    )


@pytest.fixture
def mock_rag():
    """Mock RiskMemoryRAG with controllable retrieve return (3 hits default)."""
    rag = MagicMock()

    hit1 = MagicMock()
    hit1.cosine_similarity = 0.91
    hit1.memory = MagicMock(event_type="BullishSignal", symbol_id=None, lesson="历史 lesson one")
    hit2 = MagicMock()
    hit2.cosine_similarity = 0.85
    hit2.memory = MagicMock(event_type="RegimeShift", symbol_id=None, lesson="历史 lesson two")
    rag.retrieve.return_value = [hit1, hit2]
    return rag


@pytest.fixture
def mock_bull_response():
    return LLMResponse(
        content=json.dumps(
            {
                "arguments": [
                    {"argument": "孟", "evidence": "ev1", "weight": 0.4},
                    {"argument": "看涨", "evidence": "ev2", "weight": 0.35},
                    {"argument": "动量", "evidence": "ev3", "weight": 0.25},
                ]
            }
        ),
        model="deepseek-v4-pro",
        tokens_in=200,
        tokens_out=100,
        cost_usd=Decimal("0.0002"),
    )


@pytest.fixture
def mock_bear_response():
    return LLMResponse(
        content=json.dumps(
            {
                "arguments": [
                    {"argument": "估值", "evidence": "ev1", "weight": 0.4},
                    {"argument": "看跌", "evidence": "ev2", "weight": 0.35},
                    {"argument": "风险", "evidence": "ev3", "weight": 0.25},
                ]
            }
        ),
        model="deepseek-v4-pro",
        tokens_in=200,
        tokens_out=100,
        cost_usd=Decimal("0.0002"),
    )


@pytest.fixture
def mock_judge_response():
    return LLMResponse(
        content=json.dumps({"regime": "Bull", "confidence": 0.78, "reasoning": "综合判断看涨"}),
        model="deepseek-v4-pro",
        tokens_in=300,
        tokens_out=80,
        cost_usd=Decimal("0.0003"),
    )


@pytest.fixture
def mock_router(mock_bull_response, mock_bear_response, mock_judge_response):
    """Mock LLM router returning bull → bear → judge sequence."""
    router = MagicMock()
    router.completion.side_effect = [mock_bull_response, mock_bear_response, mock_judge_response]
    return router


@pytest.fixture
def tmp_yamls_with_rag_placeholder(tmp_path):
    """Write 3 yaml prompt files with {rag_context} placeholder for testing."""
    indicator_block = (
        "Time: {timestamp}\nSSE: {sse_return}\nHS300: {hs300_return}\n"
        "BreadthUp: {breadth_up}\nBreadthDown: {breadth_down}\n"
        "NorthFlow: {north_flow_cny}\nIV50ETF: {iv_50etf}\n\n"
        "RAG context:\n{rag_context}\n"
    )
    bull_yaml = tmp_path / "bull_v1.yaml"
    bear_yaml = tmp_path / "bear_v1.yaml"
    judge_yaml = tmp_path / "judge_v1.yaml"
    for path, role in [(bull_yaml, "bull"), (bear_yaml, "bear")]:
        path.write_text(
            yaml.dump(
                {
                    "version": "v1",
                    "description": f"{role} test",
                    "system_prompt": f"You are the {role} agent.",
                    "user_template": indicator_block + f"\nProduce 3 {role}ish arguments as JSON.",
                }
            ),
            encoding="utf-8",
        )
    judge_yaml.write_text(
        yaml.dump(
            {
                "version": "v1",
                "description": "judge test",
                "system_prompt": "You are the regime judge.",
                "user_template": (
                    indicator_block + "\nBull args: {bull_arguments}\nBear args: {bear_arguments}\n"
                    "Decide regime as JSON."
                ),
            }
        ),
        encoding="utf-8",
    )
    return bull_yaml, bear_yaml, judge_yaml


# ─────────────────────────── Tests ───────────────────────────


def test_bull_agent_build_messages_accepts_rag_context_param(
    sample_indicators, mock_bull_response, tmp_yamls_with_rag_placeholder
):
    """_ArgumentsAgent._build_messages must accept rag_context kwarg + substitute into template."""
    from backend.qm_platform.risk.regime.agents import BullAgent

    router = MagicMock()
    router.completion.return_value = mock_bull_response
    bull_yaml, _, _ = tmp_yamls_with_rag_placeholder

    agent = BullAgent(router=router, prompt_path=bull_yaml)

    agent.find_arguments(sample_indicators, decision_id="t", rag_context="RAG_TEST_MARKER")

    router_call_kwargs = router.completion.call_args.kwargs
    messages = router_call_kwargs["messages"]
    user_content = next(m for m in messages if m.role == "user").content
    assert "RAG_TEST_MARKER" in user_content, (
        f"rag_context must be substituted into bull yaml template; got: {user_content[:300]!r}"
    )


def test_bear_agent_build_messages_accepts_rag_context_param(
    sample_indicators, mock_bear_response, tmp_yamls_with_rag_placeholder
):
    """BearAgent same wire pattern as BullAgent."""
    from backend.qm_platform.risk.regime.agents import BearAgent

    router = MagicMock()
    router.completion.return_value = mock_bear_response
    _, bear_yaml, _ = tmp_yamls_with_rag_placeholder

    agent = BearAgent(router=router, prompt_path=bear_yaml)
    agent.find_arguments(sample_indicators, decision_id="t", rag_context="BEAR_RAG_MARKER")

    router_call_kwargs = router.completion.call_args.kwargs
    messages = router_call_kwargs["messages"]
    user_content = next(m for m in messages if m.role == "user").content
    assert "BEAR_RAG_MARKER" in user_content


def test_judge_build_messages_accepts_rag_context_param(
    sample_indicators, mock_judge_response, tmp_yamls_with_rag_placeholder
):
    """RegimeJudge._build_messages must accept rag_context kwarg alongside bull/bear args."""
    from backend.qm_platform.risk.regime.agents import RegimeJudge
    from backend.qm_platform.risk.regime.interface import RegimeArgument

    router = MagicMock()
    router.completion.return_value = mock_judge_response
    _, _, judge_yaml = tmp_yamls_with_rag_placeholder
    judge = RegimeJudge(router=router, prompt_path=judge_yaml)

    # RegimeArgument.weight is float (per agents.py:283 `weight = float(weight_raw)`).
    # Using Decimal causes json.dumps in _build_messages to fail (not JSON serializable).
    bull_args = (
        RegimeArgument(argument="a1", evidence="e1", weight=0.4),
        RegimeArgument(argument="a2", evidence="e2", weight=0.35),
        RegimeArgument(argument="a3", evidence="e3", weight=0.25),
    )
    bear_args = (
        RegimeArgument(argument="b1", evidence="e1", weight=0.4),
        RegimeArgument(argument="b2", evidence="e2", weight=0.35),
        RegimeArgument(argument="b3", evidence="e3", weight=0.25),
    )

    judge.judge(
        sample_indicators,
        bull_args,
        bear_args,
        decision_id="t",
        rag_context="JUDGE_RAG_MARKER",
    )

    router_call_kwargs = router.completion.call_args.kwargs
    messages = router_call_kwargs["messages"]
    user_content = next(m for m in messages if m.role == "user").content
    assert "JUDGE_RAG_MARKER" in user_content


def test_market_regime_service_calls_build_rag_context_once(
    sample_indicators, mock_router, mock_rag, tmp_yamls_with_rag_placeholder
):
    """MarketRegimeService.classify() must call build_rag_context EXACTLY ONCE per
    classify (shared across bull/bear/judge — efficiency target)."""
    from backend.app.services.risk.market_regime_service import MarketRegimeService
    from backend.qm_platform.risk.regime.agents import BearAgent, BullAgent, RegimeJudge

    bull_yaml, bear_yaml, judge_yaml = tmp_yamls_with_rag_placeholder
    bull = BullAgent(router=mock_router, prompt_path=bull_yaml)
    bear = BearAgent(router=mock_router, prompt_path=bear_yaml)
    judge = RegimeJudge(router=mock_router, prompt_path=judge_yaml)
    service = MarketRegimeService(
        router=mock_router,
        bull_agent=bull,
        bear_agent=bear,
        judge=judge,
        rag=mock_rag,
    )

    service.classify(sample_indicators, decision_id="iter177-test")

    # rag.retrieve called exactly once (not 3x — shared context across agents)
    assert mock_rag.retrieve.call_count == 1, (
        f"Expected 1 retrieve call (shared context), got {mock_rag.retrieve.call_count}"
    )


def test_market_regime_service_passes_rag_context_to_all_3_agents(
    sample_indicators, mock_router, mock_rag, tmp_yamls_with_rag_placeholder
):
    """RAG markdown table must propagate to all 3 LLM message bodies (bull/bear/judge)."""
    from backend.app.services.risk.market_regime_service import MarketRegimeService
    from backend.qm_platform.risk.regime.agents import BearAgent, BullAgent, RegimeJudge

    bull_yaml, bear_yaml, judge_yaml = tmp_yamls_with_rag_placeholder
    bull = BullAgent(router=mock_router, prompt_path=bull_yaml)
    bear = BearAgent(router=mock_router, prompt_path=bear_yaml)
    judge = RegimeJudge(router=mock_router, prompt_path=judge_yaml)
    service = MarketRegimeService(
        router=mock_router,
        bull_agent=bull,
        bear_agent=bear,
        judge=judge,
        rag=mock_rag,
    )

    service.classify(sample_indicators, decision_id="iter177-test")

    # 3 router.completion calls: bull / bear / judge — each must have RAG cosine score in user content
    assert mock_router.completion.call_count == 3
    for i, call in enumerate(mock_router.completion.call_args_list):
        messages = call.kwargs["messages"]
        user_content = next(m for m in messages if m.role == "user").content
        assert "0.910" in user_content or "0.91" in user_content, (
            f"RAG cosine score must appear in agent {i} (bull/bear/judge) user content"
        )


def test_market_regime_service_backward_compat_rag_none(
    sample_indicators, mock_router, tmp_yamls_with_rag_placeholder
):
    """When rag=None (default), classify works without RAG call; rag_context resolves to empty."""
    from backend.app.services.risk.market_regime_service import MarketRegimeService
    from backend.qm_platform.risk.regime.agents import BearAgent, BullAgent, RegimeJudge

    bull_yaml, bear_yaml, judge_yaml = tmp_yamls_with_rag_placeholder
    bull = BullAgent(router=mock_router, prompt_path=bull_yaml)
    bear = BearAgent(router=mock_router, prompt_path=bear_yaml)
    judge = RegimeJudge(router=mock_router, prompt_path=judge_yaml)
    service = MarketRegimeService(
        router=mock_router,
        bull_agent=bull,
        bear_agent=bear,
        judge=judge,
        # rag=None implicit
    )

    # Should NOT raise even with rag=None + yamls have {rag_context} placeholder
    regime = service.classify(sample_indicators, decision_id="t")

    assert regime is not None
    # No RAG markdown table separator should appear in any agent's user content
    for call in mock_router.completion.call_args_list:
        messages = call.kwargs["messages"]
        user_content = next(m for m in messages if m.role == "user").content
        assert "|---|---|" not in user_content, (
            f"RAG markdown separator must NOT appear with rag=None; got: {user_content[:200]!r}"
        )


def test_market_regime_service_fail_soft_on_rag_exception(
    sample_indicators, mock_router, tmp_yamls_with_rag_placeholder
):
    """When rag.retrieve raises, fail-soft '数据不足' placeholder propagates to all 3 agents."""
    from backend.app.services.risk.market_regime_service import MarketRegimeService
    from backend.qm_platform.risk.regime.agents import BearAgent, BullAgent, RegimeJudge

    failing_rag = MagicMock()
    failing_rag.retrieve.side_effect = RuntimeError("BGE-M3 GPU OOM")

    bull_yaml, bear_yaml, judge_yaml = tmp_yamls_with_rag_placeholder
    bull = BullAgent(router=mock_router, prompt_path=bull_yaml)
    bear = BearAgent(router=mock_router, prompt_path=bear_yaml)
    judge = RegimeJudge(router=mock_router, prompt_path=judge_yaml)
    service = MarketRegimeService(
        router=mock_router,
        bull_agent=bull,
        bear_agent=bear,
        judge=judge,
        rag=failing_rag,
    )

    # Should NOT raise — fail-soft via build_rag_context internal try/except
    regime = service.classify(sample_indicators, decision_id="t")
    assert regime is not None

    # All 3 agents should see "数据不足" placeholder
    for call in mock_router.completion.call_args_list:
        messages = call.kwargs["messages"]
        user_content = next(m for m in messages if m.role == "user").content
        assert "数据不足" in user_content, (
            f"Fail-soft placeholder must propagate to user content; got: {user_content[:300]!r}"
        )
