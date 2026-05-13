"""V3 §5.3 MarketRegimeService — Bull/Bear/Judge V4-Pro × 3 debate orchestration (TB-2b).

V3 §11.2 line 1227 真预约 path: backend/app/services/risk/MarketRegimeService.
Sustained ADR-036 (BULL_AGENT + BEAR_AGENT + JUDGE all V4-Pro) + ADR-064 (Plan v0.2 D2).

scope (TB-2b):
- DI router (LiteLLMRouter | BudgetAwareRouter via get_llm_router factory, ADR-032)
- classify(indicators) → MarketRegime: 3 LLM calls (bull / bear / judge) + assemble result
- persist hook: caller invokes persist_market_regime(conn, regime) directly (sustained
  铁律 32 — service 不 commit, caller manages transaction boundary)
- Cost accumulation across 3 calls (V3 §16.2 cost cap audit)

Out of scope (留 TB-2c/d):
- Celery Beat schedule (TB-2c)
- DynamicThresholdEngine L3 integration (TB-2d)
- prompts 历史回测 / eval iteration (TB-5 batch)

caller 真**唯一 sanctioned 入口** (sustained ADR-032 + NewsClassifierService 体例):
    from backend.qm_platform.llm import get_llm_router
    from backend.app.services.risk.market_regime_service import MarketRegimeService

    router = get_llm_router()
    service = MarketRegimeService(router=router)
    indicators = MarketIndicators(timestamp=..., sse_return=..., ...)
    regime = service.classify(indicators, decision_id="market-regime-2026-05-14-0900")
    # caller persists if desired:
    from backend.qm_platform.risk.regime import persist_market_regime
    regime_id = persist_market_regime(conn, regime)
    conn.commit()  # caller manages transaction (铁律 32)

关联铁律: 22 / 24 / 31 / 32 / 33 / 34 / 41
关联 V3: §5.3 / §11.2 / §16.2
关联 ADR: ADR-022 / ADR-029 / ADR-036 / ADR-064 / ADR-066 (Tier B context)
关联 LL: LL-067 (reviewer 体例) / LL-098 X10 / LL-115 family / LL-159 (4-step preflight)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from backend.qm_platform.llm import RiskTaskType
from backend.qm_platform.risk.regime.agents import (
    BearAgent,
    BullAgent,
    RegimeJudge,
)
from backend.qm_platform.risk.regime.interface import (
    MarketRegime,
)

if TYPE_CHECKING:
    from backend.qm_platform.llm import LLMMessage, LLMResponse
    from backend.qm_platform.risk.regime.interface import MarketIndicators

logger = logging.getLogger(__name__)


class _RouterProtocol(Protocol):
    """LiteLLMRouter | BudgetAwareRouter 共通 completion interface (duck typing)."""

    def completion(
        self,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        *,
        decision_id: str | None = ...,
        **kwargs: Any,
    ) -> LLMResponse: ...


class MarketRegimeService:
    """V3 §5.3 Bull/Bear regime detection orchestrator (V4-Pro × 3 debate).

    classify(indicators) → MarketRegime:
      1. BullAgent V4-Pro → 3 看多 RegimeArgument
      2. BearAgent V4-Pro → 3 看空 RegimeArgument
      3. RegimeJudge V4-Pro → RegimeLabel + confidence + reasoning
      4. Sum cost across 3 calls + assemble MarketRegime frozen dataclass

    DI 体例 — single shared router across 3 agents (sustained NewsClassifierService).
    """

    def __init__(
        self,
        router: _RouterProtocol,
        *,
        bull_agent: BullAgent | None = None,
        bear_agent: BearAgent | None = None,
        judge: RegimeJudge | None = None,
    ) -> None:
        """Initialize MarketRegimeService with 3 agents (DI for testability).

        Args:
            router: get_llm_router() result (LiteLLMRouter | BudgetAwareRouter).
            bull_agent: optional pre-built BullAgent override (default builds new).
            bear_agent: optional pre-built BearAgent override (default builds new).
            judge: optional pre-built RegimeJudge override (default builds new).
        """
        self._router = router
        self._bull = bull_agent if bull_agent is not None else BullAgent(router=router)
        self._bear = bear_agent if bear_agent is not None else BearAgent(router=router)
        self._judge = judge if judge is not None else RegimeJudge(router=router)

    def classify(
        self,
        indicators: MarketIndicators,
        *,
        decision_id: str | None = None,
    ) -> MarketRegime:
        """Orchestrate Bull/Bear/Judge 3 LLM calls → MarketRegime.

        Args:
            indicators: MarketIndicators input snapshot (tz-aware timestamp, 5 维 fields).
            decision_id: optional caller-traceable id for LiteLLM audit trail.

        Returns:
            MarketRegime frozen dataclass (regime + confidence + 6 arguments +
            reasoning + indicators snapshot + sum cost_usd).

        Raises:
            MarketRegimeError: any of 3 LLM calls fails parse / schema validate
                (sustained 铁律 33 fail-loud).
        """
        # Build decision_id sub-suffixes for per-call audit trail.
        bull_id = f"{decision_id}-bull" if decision_id else None
        bear_id = f"{decision_id}-bear" if decision_id else None
        judge_id = f"{decision_id}-judge" if decision_id else None

        logger.info(
            "[market-regime] classify start: ts=%s decision_id=%s",
            indicators.timestamp.isoformat(),
            decision_id or "(none)",
        )

        bull_args, bull_cost = self._bull.find_arguments(indicators, decision_id=bull_id)
        bear_args, bear_cost = self._bear.find_arguments(indicators, decision_id=bear_id)
        regime, confidence, reasoning, judge_cost = self._judge.judge(
            indicators,
            bull_args,
            bear_args,
            decision_id=judge_id,
        )

        # Sum cost across 3 V4-Pro calls (Decimal → float for MarketRegime cost_usd).
        total_cost = float(bull_cost + bear_cost + judge_cost)

        # MarketRegime.timestamp = "when classification ran" — use UTC NOW for audit
        # (反 stale indicators.timestamp if indicators 数据 cached / lagged).
        result = MarketRegime(
            timestamp=datetime.now(UTC),
            regime=regime,
            confidence=confidence,
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            judge_reasoning=reasoning,
            indicators=indicators,
            cost_usd=total_cost,
        )

        logger.info(
            "[market-regime] classify result: regime=%s confidence=%.4f "
            "cost_usd=%.4f decision_id=%s",
            regime.value,
            confidence,
            total_cost,
            decision_id or "(none)",
        )
        return result
