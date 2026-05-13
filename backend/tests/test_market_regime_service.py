"""V3 §5.3 MarketRegimeService — TB-2b mock-LLM integration tests.

Coverage:
  - prompt yaml load (3 prompts: bull / bear / judge)
  - BullAgent.find_arguments mock + parse 3 RegimeArgument
  - BearAgent.find_arguments mock + parse 3 RegimeArgument
  - RegimeJudge.judge mock + parse regime + confidence + reasoning
  - MarketRegimeService.classify end-to-end orchestration with mock router
    (side_effect=[bull_resp, bear_resp, judge_resp])
  - Cost accumulation across 3 V4-Pro calls
  - Failure paths: JSON parse / schema validate / arg count / invalid regime label

Sustains mock-router 体例 (test_news_classifier_service.py + LL-157 SAVEPOINT-insert NOT
applicable here — service layer 不 touch DB, persist via repository per 铁律 32).

关联铁律: 31 (Engine PURE side parsers) / 33 (fail-loud) / 40 (test debt) / 41 (timezone)
关联 V3: §5.3 / ADR-036/064
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from backend.app.services.risk.market_regime_service import MarketRegimeService
from backend.qm_platform.llm import LLMResponse, RiskTaskType
from backend.qm_platform.risk.regime import (
    MarketIndicators,
    MarketRegime,
    MarketRegimeError,
    RegimeArgument,
    RegimeLabel,
)
from backend.qm_platform.risk.regime.agents import (
    BearAgent,
    BullAgent,
    PromptLoadError,
    RegimeJudge,
)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def sample_indicators() -> MarketIndicators:
    """Sample MarketIndicators for Bull/Bear bias scenarios."""
    return MarketIndicators(
        timestamp=datetime(2026, 5, 14, 9, 0, 0, tzinfo=SHANGHAI_TZ),
        sse_return=0.0185,  # mildly bullish
        hs300_return=0.0212,
        breadth_up=2800,
        breadth_down=1500,
        north_flow_cny=87.5,  # positive flow
        iv_50etf=0.185,  # low fear
    )


def _make_bull_response(
    *,
    cost: Decimal = Decimal("0.0013"),
    weights: tuple[float, float, float] = (0.7, 0.5, 0.4),
) -> LLMResponse:
    content = json.dumps(
        {
            "arguments": [
                {
                    "argument": "上证综指 +1.85% 突破前高",
                    "evidence": "sse_return=0.0185",
                    "weight": weights[0],
                },
                {
                    "argument": "北向资金 +¥87.5 亿净流入",
                    "evidence": "north_flow_cny=87.5",
                    "weight": weights[1],
                },
                {
                    "argument": "市场宽度 2800 / 1500 多头占优",
                    "evidence": "breadth_up=2800, breadth_down=1500",
                    "weight": weights[2],
                },
            ]
        },
        ensure_ascii=False,
    )
    return LLMResponse(
        content=content,
        model="deepseek-v4-pro",
        tokens_in=150,
        tokens_out=80,
        cost_usd=cost,
        latency_ms=620.0,
        decision_id="market-regime-test-bull",
    )


def _make_bear_response(
    *,
    cost: Decimal = Decimal("0.0011"),
    weights: tuple[float, float, float] = (0.4, 0.3, 0.2),
) -> LLMResponse:
    content = json.dumps(
        {
            "arguments": [
                {
                    "argument": "涨幅过快短期超买风险",
                    "evidence": "sse_return=0.0185 单日涨幅高",
                    "weight": weights[0],
                },
                {
                    "argument": "50ETF IV 偏低市场缺乏对冲",
                    "evidence": "iv_50etf=0.185 历史低位",
                    "weight": weights[1],
                },
                {
                    "argument": "1500 跌停股提示分化加剧",
                    "evidence": "breadth_down=1500",
                    "weight": weights[2],
                },
            ]
        },
        ensure_ascii=False,
    )
    return LLMResponse(
        content=content,
        model="deepseek-v4-pro",
        tokens_in=150,
        tokens_out=80,
        cost_usd=cost,
        latency_ms=580.0,
        decision_id="market-regime-test-bear",
    )


def _make_judge_response(
    *,
    regime: str = "Bull",
    confidence: float = 0.75,
    reasoning: str = "Bull 论据加权高 (0.7+0.5+0.4=1.6) > Bear (0.4+0.3+0.2=0.9), 北向流入 + 突破前高共振判 Bull regime.",
    cost: Decimal = Decimal("0.0015"),
) -> LLMResponse:
    content = json.dumps(
        {
            "regime": regime,
            "confidence": confidence,
            "reasoning": reasoning,
        },
        ensure_ascii=False,
    )
    return LLMResponse(
        content=content,
        model="deepseek-v4-pro",
        tokens_in=300,
        tokens_out=120,
        cost_usd=cost,
        latency_ms=750.0,
        decision_id="market-regime-test-judge",
    )


@pytest.fixture
def mock_router() -> MagicMock:
    """Mock router with default 3-call side_effect (bull / bear / judge order)."""
    router = MagicMock()
    router.completion.side_effect = [
        _make_bull_response(),
        _make_bear_response(),
        _make_judge_response(),
    ]
    return router


# ─────────────────────────────────────────────────────────────
# TestPromptLoad — 3 yaml files exist + load successfully
# ─────────────────────────────────────────────────────────────


class TestPromptLoad:
    def test_bull_prompt_loads(self, mock_router: MagicMock) -> None:
        # Construct = yaml load executes; if path or schema fails, raises.
        agent = BullAgent(router=mock_router)
        assert agent is not None

    def test_bear_prompt_loads(self, mock_router: MagicMock) -> None:
        agent = BearAgent(router=mock_router)
        assert agent is not None

    def test_judge_prompt_loads(self, mock_router: MagicMock) -> None:
        judge = RegimeJudge(router=mock_router)
        assert judge is not None

    def test_missing_prompt_file_raises(self, mock_router: MagicMock, tmp_path) -> None:
        bogus = tmp_path / "nonexistent.yaml"
        with pytest.raises(PromptLoadError, match="not found"):
            BullAgent(router=mock_router, prompt_path=bogus)


# ─────────────────────────────────────────────────────────────
# TestBullAgent
# ─────────────────────────────────────────────────────────────


class TestBullAgent:
    def test_find_arguments_happy_path(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        # Only 1 call expected → set return_value (not side_effect).
        mock_router.completion.side_effect = None
        mock_router.completion.return_value = _make_bull_response()

        agent = BullAgent(router=mock_router)
        args, cost = agent.find_arguments(sample_indicators, decision_id="bull-test")

        assert len(args) == 3
        for arg in args:
            assert isinstance(arg, RegimeArgument)
            assert arg.argument
            assert 0.0 <= arg.weight <= 1.0
        assert cost == Decimal("0.0013")

        # Verify task routing.
        call = mock_router.completion.call_args
        assert call.kwargs["task"] == RiskTaskType.BULL_AGENT
        assert call.kwargs["decision_id"] == "bull-test"

    def test_find_arguments_wrong_count_raises(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        # 2 args instead of 3 — should fail-loud (sustained V3 §5.3 真 3 论据).
        mock_router.completion.side_effect = None
        bad_content = json.dumps(
            {
                "arguments": [
                    {"argument": "a", "evidence": "", "weight": 0.5},
                    {"argument": "b", "evidence": "", "weight": 0.5},
                ]
            }
        )
        mock_router.completion.return_value = LLMResponse(
            content=bad_content,
            model="deepseek-v4-pro",
        )

        agent = BullAgent(router=mock_router)
        with pytest.raises(MarketRegimeError, match="exactly 3 items, got 2"):
            agent.find_arguments(sample_indicators)

    def test_find_arguments_invalid_weight_raises(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        mock_router.completion.side_effect = None
        bad_content = json.dumps(
            {
                "arguments": [
                    {"argument": "a", "evidence": "", "weight": 1.5},  # out of [0,1]
                    {"argument": "b", "evidence": "", "weight": 0.5},
                    {"argument": "c", "evidence": "", "weight": 0.5},
                ]
            }
        )
        mock_router.completion.return_value = LLMResponse(
            content=bad_content, model="deepseek-v4-pro"
        )

        agent = BullAgent(router=mock_router)
        with pytest.raises(MarketRegimeError, match="weight must be in"):
            agent.find_arguments(sample_indicators)

    def test_find_arguments_non_json_raises(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        mock_router.completion.side_effect = None
        mock_router.completion.return_value = LLMResponse(
            content="不是 JSON 啊", model="deepseek-v4-pro"
        )
        agent = BullAgent(router=mock_router)
        with pytest.raises(MarketRegimeError, match="not JSON"):
            agent.find_arguments(sample_indicators)

    def test_find_arguments_markdown_fence_stripped(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        # V4-Pro occasional markdown fence wrap — must strip + parse.
        mock_router.completion.side_effect = None
        inner = json.dumps(
            {
                "arguments": [
                    {"argument": "a", "evidence": "x", "weight": 0.3},
                    {"argument": "b", "evidence": "y", "weight": 0.3},
                    {"argument": "c", "evidence": "z", "weight": 0.4},
                ]
            },
            ensure_ascii=False,
        )
        wrapped = f"```json\n{inner}\n```"
        mock_router.completion.return_value = LLMResponse(
            content=wrapped, model="deepseek-v4-pro", cost_usd=Decimal("0.001")
        )
        agent = BullAgent(router=mock_router)
        args, _ = agent.find_arguments(sample_indicators)
        assert len(args) == 3


# ─────────────────────────────────────────────────────────────
# TestBearAgent — symmetric to Bull
# ─────────────────────────────────────────────────────────────


class TestBearAgent:
    def test_find_arguments_happy_path(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        mock_router.completion.side_effect = None
        mock_router.completion.return_value = _make_bear_response()

        agent = BearAgent(router=mock_router)
        args, cost = agent.find_arguments(sample_indicators, decision_id="bear-test")

        assert len(args) == 3
        assert cost == Decimal("0.0011")
        call = mock_router.completion.call_args
        assert call.kwargs["task"] == RiskTaskType.BEAR_AGENT


# ─────────────────────────────────────────────────────────────
# TestRegimeJudge
# ─────────────────────────────────────────────────────────────


class TestRegimeJudge:
    def test_judge_happy_path(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        mock_router.completion.side_effect = None
        mock_router.completion.return_value = _make_judge_response()

        judge = RegimeJudge(router=mock_router)
        bull_args = (
            RegimeArgument(argument="b1", weight=0.7),
            RegimeArgument(argument="b2", weight=0.5),
            RegimeArgument(argument="b3", weight=0.4),
        )
        bear_args = (
            RegimeArgument(argument="r1", weight=0.4),
            RegimeArgument(argument="r2", weight=0.3),
            RegimeArgument(argument="r3", weight=0.2),
        )
        regime, conf, reasoning, cost = judge.judge(
            sample_indicators, bull_args, bear_args, decision_id="judge-test"
        )
        assert regime == RegimeLabel.BULL
        assert conf == pytest.approx(0.75, abs=1e-4)
        assert "加权" in reasoning
        assert cost == Decimal("0.0015")

        call = mock_router.completion.call_args
        assert call.kwargs["task"] == RiskTaskType.JUDGE

    def test_judge_invalid_regime_label_raises(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        mock_router.completion.side_effect = None
        mock_router.completion.return_value = _make_judge_response(regime="Bullish")

        judge = RegimeJudge(router=mock_router)
        bull = (RegimeArgument(argument="b", weight=0.5),) * 3
        bear = (RegimeArgument(argument="r", weight=0.5),) * 3
        with pytest.raises(MarketRegimeError, match="regime label invalid"):
            judge.judge(sample_indicators, bull, bear)

    def test_judge_confidence_out_of_range_raises(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        mock_router.completion.side_effect = None
        mock_router.completion.return_value = _make_judge_response(confidence=1.5)

        judge = RegimeJudge(router=mock_router)
        bull = (RegimeArgument(argument="b", weight=0.5),) * 3
        bear = (RegimeArgument(argument="r", weight=0.5),) * 3
        with pytest.raises(MarketRegimeError, match="confidence out of"):
            judge.judge(sample_indicators, bull, bear)

    def test_judge_missing_keys_raises(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        mock_router.completion.side_effect = None
        mock_router.completion.return_value = LLMResponse(
            content='{"regime": "Bull"}',  # missing confidence + reasoning
            model="deepseek-v4-pro",
        )
        judge = RegimeJudge(router=mock_router)
        bull = (RegimeArgument(argument="b", weight=0.5),) * 3
        bear = (RegimeArgument(argument="r", weight=0.5),) * 3
        with pytest.raises(MarketRegimeError, match="missing keys"):
            judge.judge(sample_indicators, bull, bear)

    @pytest.mark.parametrize("label", ["Bull", "Bear", "Neutral", "Transitioning"])
    def test_judge_all_4_labels_accepted(
        self,
        mock_router: MagicMock,
        sample_indicators: MarketIndicators,
        label: str,
    ) -> None:
        mock_router.completion.side_effect = None
        mock_router.completion.return_value = _make_judge_response(regime=label)
        judge = RegimeJudge(router=mock_router)
        bull = (RegimeArgument(argument="b", weight=0.5),) * 3
        bear = (RegimeArgument(argument="r", weight=0.5),) * 3
        regime, _, _, _ = judge.judge(sample_indicators, bull, bear)
        assert regime.value == label


# ─────────────────────────────────────────────────────────────
# TestMarketRegimeService — end-to-end orchestration
# ─────────────────────────────────────────────────────────────


class TestMarketRegimeService:
    def test_classify_end_to_end_bull(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        service = MarketRegimeService(router=mock_router)
        result = service.classify(sample_indicators, decision_id="test-1")

        assert isinstance(result, MarketRegime)
        assert result.regime == RegimeLabel.BULL
        assert result.confidence == pytest.approx(0.75, abs=1e-4)
        assert len(result.bull_arguments) == 3
        assert len(result.bear_arguments) == 3
        # Cost accumulated across 3 calls: 0.0013 + 0.0011 + 0.0015 = 0.0039.
        assert result.cost_usd == pytest.approx(0.0039, abs=1e-6)
        # Timestamp = classify-run-time UTC (反 indicators.timestamp).
        assert result.timestamp.tzinfo == UTC
        # Indicators snapshot preserved.
        assert result.indicators is sample_indicators

    def test_classify_dispatches_3_router_calls_in_order(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        service = MarketRegimeService(router=mock_router)
        service.classify(sample_indicators, decision_id="ord-test")

        # 3 calls in bull / bear / judge order.
        assert mock_router.completion.call_count == 3
        tasks = [c.kwargs["task"] for c in mock_router.completion.call_args_list]
        assert tasks == [
            RiskTaskType.BULL_AGENT,
            RiskTaskType.BEAR_AGENT,
            RiskTaskType.JUDGE,
        ]
        # decision_id sub-suffix per call.
        ids = [c.kwargs["decision_id"] for c in mock_router.completion.call_args_list]
        assert ids == ["ord-test-bull", "ord-test-bear", "ord-test-judge"]

    def test_classify_no_decision_id_passes_none(
        self, mock_router: MagicMock, sample_indicators: MarketIndicators
    ) -> None:
        service = MarketRegimeService(router=mock_router)
        service.classify(sample_indicators)  # decision_id default None

        ids = [c.kwargs["decision_id"] for c in mock_router.completion.call_args_list]
        assert ids == [None, None, None]

    def test_classify_bear_regime(self, sample_indicators: MarketIndicators) -> None:
        # Different scenario: judge returns Bear.
        router = MagicMock()
        router.completion.side_effect = [
            _make_bull_response(weights=(0.2, 0.1, 0.1)),
            _make_bear_response(weights=(0.9, 0.8, 0.7)),
            _make_judge_response(regime="Bear", confidence=0.85),
        ]
        service = MarketRegimeService(router=router)
        result = service.classify(sample_indicators)
        assert result.regime == RegimeLabel.BEAR
        assert result.confidence == pytest.approx(0.85, abs=1e-4)

    def test_classify_propagates_bull_parse_error(
        self, sample_indicators: MarketIndicators
    ) -> None:
        router = MagicMock()
        router.completion.side_effect = [
            LLMResponse(content="not json", model="deepseek-v4-pro"),
            _make_bear_response(),  # never called
            _make_judge_response(),  # never called
        ]
        service = MarketRegimeService(router=router)
        with pytest.raises(MarketRegimeError, match="not JSON"):
            service.classify(sample_indicators)
        # Only 1 call should have happened (fail-loud short-circuit).
        assert router.completion.call_count == 1

    def test_classify_handles_partial_indicators(self) -> None:
        """All-None indicators allowed (TB-2a design codification sustained)."""
        partial = MarketIndicators(
            timestamp=datetime(2026, 5, 14, 14, 30, 0, tzinfo=SHANGHAI_TZ),
            # All other fields None
        )
        router = MagicMock()
        router.completion.side_effect = [
            _make_bull_response(),
            _make_bear_response(),
            _make_judge_response(regime="Neutral", confidence=0.4),
        ]
        service = MarketRegimeService(router=router)
        result = service.classify(partial)
        assert result.regime == RegimeLabel.NEUTRAL
        assert result.indicators is partial
