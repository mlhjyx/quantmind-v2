"""V3 §15.6 合成场景 ≥7 类 — synthetic scenario fixtures + assertions (TB-5a sub-PR).

V3 §15.6 line 1543-1554 codifies the synthetic-scenario methodology: T0-12 真生产
0 events 验证缺 → 走合成场景验证. Each scenario gets a pytest fixture + assertion,
CI runs them. This file is the TB-5a deliverable per Plan v0.2 §A TB-5 row line 138
("TB-5a V3 §15.6 ≥7 scenarios fixture + assertion + CI green").

The 7 scenarios (V3 §15.6 line 1546-1552):
  1. 4-29 类事件 (3 股盘中跌停 + 大盘 -2%)
  2. 单股闪崩 (-15% in 5min)
  3. 行业崩盘 (持仓 5 股同行业, 行业 day -5%)
  4. regime 急转 (Bull → Bear in 1 day)
  5. LLM 服务全挂 + Ollama fallback
  6. DingTalk 不可用 + email backup
  7. user 离线 4h + STAGED 30min timeout

Design notes:
  - Scenarios 1-3 exercise the REAL L1 RealtimeRiskEngine + 10 RealtimeRiskRule
    via RiskBacktestAdapter (production-parity path, sustained TB-1a 体例).
  - Scenario 4-5 exercise the REAL MarketRegimeService with a mock LiteLLM router
    (sustained test_market_regime_service.py mock-router 体例).
  - Scenario 6 exercises the REAL AlertDispatcher + EmailBackupStub fallback chain.
  - Scenario 7 exercises the REAL L4ExecutionPlanner STAGED state machine.
  - All assertions hit real code paths — 0 invented API (铁律 25/36 sustained).

关联 V3: §15.6 (合成场景 methodology) / §13.1 (5 SLA, scenario 5/6/7 transferable)
关联铁律: 25 (改什么读什么) / 31 (Engine PURE) / 33 (fail-loud) / 40 (test debt) / 41 (timezone)
关联 ADR: ADR-029 (10 RealtimeRiskRule) / ADR-036 (V4-Pro) / ADR-027 (STAGED) / ADR-063 (replay path)
关联 Plan: V3_TIER_B_SPRINT_PLAN_v0.1.md §A TB-5 row line 131-145 (TB-5a sub-PR)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from backend.app.services.risk.market_regime_service import MarketRegimeService
from backend.qm_platform.risk import Position, RiskContext, RuleResult
from backend.qm_platform.risk.backtest_adapter import RiskBacktestAdapter
from backend.qm_platform.risk.execution.planner import (
    ExecutionMode,
    L4ExecutionPlanner,
    PlanStatus,
)
from backend.qm_platform.risk.realtime import RealtimeRiskEngine
from backend.qm_platform.risk.realtime.alert import AlertDispatcher
from backend.qm_platform.risk.realtime.email_backup import EmailBackupStub
from backend.qm_platform.risk.regime import (
    MarketIndicators,
    MarketRegime,
    RegimeArgument,
    RegimeLabel,
)
from backend.qm_platform.risk.rules.realtime.correlated_drop import CorrelatedDrop
from backend.qm_platform.risk.rules.realtime.industry_concentration import (
    IndustryConcentration,
)
from backend.qm_platform.risk.rules.realtime.limit_down import (
    LimitDownDetection,
    NearLimitDown,
)
from backend.qm_platform.risk.rules.realtime.rapid_drop import RapidDrop5min

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# 4-29 类事件 anchor date — synthetic scenarios reuse the 4-29 卓然新能 跌停教训
# date as a stable, semantically-meaningful timestamp anchor (V3 §15.6 line 1546).
_EVENT_DATE = datetime(2026, 4, 29, tzinfo=SHANGHAI_TZ)


# ─────────────────────────────────────────────────────────────
# Shared builders — construct REAL Position / RiskContext / realtime dicts
# ─────────────────────────────────────────────────────────────


def _position(
    code: str,
    current_price: float,
    *,
    shares: int = 1000,
    entry_price: float = 100.0,
    peak_price: float = 100.0,
) -> Position:
    """Build a Position with sensible defaults (entry/peak only matter for TrailingStop)."""
    return Position(
        code=code,
        shares=shares,
        entry_price=entry_price,
        peak_price=peak_price,
        current_price=current_price,
    )


def _tick(
    *,
    prev_close: float | None = None,
    open_price: float | None = None,
    price_5min_ago: float | None = None,
    price_15min_ago: float | None = None,
    day_volume: float | None = None,
    avg_daily_volume: float | None = None,
    industry: str | None = None,
    atr_pct: float | None = None,
) -> dict[str, Any]:
    """Build a realtime tick dict — only non-None keys included (rules silent-skip on missing)."""
    tick: dict[str, Any] = {}
    if prev_close is not None:
        tick["prev_close"] = prev_close
    if open_price is not None:
        tick["open_price"] = open_price
    if price_5min_ago is not None:
        tick["price_5min_ago"] = price_5min_ago
    if price_15min_ago is not None:
        tick["price_15min_ago"] = price_15min_ago
    if day_volume is not None:
        tick["day_volume"] = day_volume
    if avg_daily_volume is not None:
        tick["avg_daily_volume"] = avg_daily_volume
    if industry is not None:
        tick["industry"] = industry
    if atr_pct is not None:
        tick["atr_pct"] = atr_pct
    return tick


def _context(
    positions: tuple[Position, ...],
    realtime: dict[str, dict[str, Any]] | None,
    *,
    timestamp: datetime,
    portfolio_nav: float = 1_000_000.0,
    prev_close_nav: float | None = 1_000_000.0,
) -> RiskContext:
    """Build a RiskContext for a synthetic scenario."""
    return RiskContext(
        strategy_id="test-v3-15-6-synthetic",
        execution_mode="paper",
        timestamp=timestamp,
        positions=positions,
        portfolio_nav=portfolio_nav,
        prev_close_nav=prev_close_nav,
        realtime=realtime,
    )


# ─────────────────────────────────────────────────────────────
# Scenario 1 — 4-29 类事件 (3 股盘中跌停 + 大盘 -2%)
# ─────────────────────────────────────────────────────────────


class TestScenario1MultiLimitDown:
    """V3 §15.6 #1 — 持仓 3 股同时盘中跌停 + 大盘 -2% context.

    Expected L1 behavior:
      - LimitDownDetection (tick) fires 3 RuleResult (one per limit-down stock).
      - CorrelatedDrop (5min) fires 1 portfolio-level P0 (≥3 股 5min 联动 ≥3%).
      - NearLimitDown does NOT fire (mutually exclusive with full limit-down).
    The 大盘 -2% context is encoded via portfolio_nav vs prev_close_nav (no index-level
    rule in the 10-rule set — L1 catches the 3-stock cluster + correlated drop).
    """

    @pytest.fixture
    def context(self) -> RiskContext:
        # 3 main-board stocks (60x prefix → 9.9% rule threshold). current_price is
        # the real -10.0% 跌停板 price (a main-board A-share is halted at -10%, so
        # -10% is the physically-realistic limit-down value, not a deeper drop).
        codes = ("600519.SH", "601318.SH", "600036.SH")
        positions = tuple(_position(c, current_price=90.0) for c in codes)
        realtime = {c: _tick(prev_close=100.0, price_5min_ago=100.0) for c in codes}
        # 大盘 -2%: portfolio NAV reflects -2% vs prev close.
        return _context(
            positions,
            realtime,
            timestamp=_EVENT_DATE.replace(hour=10, minute=15, second=30),
            portfolio_nav=980_000.0,
            prev_close_nav=1_000_000.0,
        )

    def test_limit_down_fires_for_all_3_stocks(self, context: RiskContext) -> None:
        engine = RealtimeRiskEngine()
        engine.register(LimitDownDetection(), cadence="tick")

        results = engine.on_tick(context)

        assert len(results) == 3
        assert {r.rule_id for r in results} == {"limit_down_detection"}
        assert {r.code for r in results} == {"600519.SH", "601318.SH", "600036.SH"}
        # All limit-down hits are alert_only with shares=0 (4-29 教训: 跌停板无买盘).
        assert all(r.shares == 0 for r in results)
        for r in results:
            # -10.0% 跌停板 — below the 9.9% rule threshold so the rule fires.
            assert r.metrics["drop_pct"] == pytest.approx(-0.10, abs=1e-6)

    def test_near_limit_down_silent_when_full_limit_down(self, context: RiskContext) -> None:
        # NearLimitDown is mutually exclusive — full limit-down stocks must NOT
        # also produce a near-limit-down alert (反 duplicate告警).
        engine = RealtimeRiskEngine()
        engine.register(NearLimitDown(), cadence="tick")
        assert engine.on_tick(context) == []

    def test_near_limit_down_fires_in_warning_band(self) -> None:
        # Complement to the mutual-exclusion test: a stock dropping into the
        # [9.5%, 9.9%) warning band MUST trigger NearLimitDown (尾盘限价卖单预警).
        position = _position("600519.SH", current_price=90.4)  # -9.6% drop
        realtime = {"600519.SH": _tick(prev_close=100.0)}
        ctx = _context(
            (position,),
            realtime,
            timestamp=_EVENT_DATE.replace(hour=14, minute=40, second=0),
        )
        engine = RealtimeRiskEngine()
        engine.register(NearLimitDown(), cadence="tick")

        results = engine.on_tick(ctx)
        assert len(results) == 1
        assert results[0].rule_id == "near_limit_down"
        assert results[0].metrics["drop_pct"] == pytest.approx(-0.096, abs=1e-6)

    def test_correlated_drop_fires_portfolio_level_p0(self, context: RiskContext) -> None:
        engine = RealtimeRiskEngine()
        engine.register(CorrelatedDrop(), cadence="5min")

        results = engine.on_5min_beat(context)

        assert len(results) == 1
        cd = results[0]
        assert cd.rule_id == "correlated_drop"
        # CorrelatedDrop joins triggered codes into the `code` field — all 3 present.
        assert set(cd.code.split(",")) == {"600519.SH", "601318.SH", "600036.SH"}
        assert cd.metrics["triggered_count"] == 3
        assert cd.metrics["total_positions"] == 3

    def test_evaluate_at_production_parity_pure_function(self, context: RiskContext) -> None:
        # RiskBacktestAdapter.evaluate_at is the production-parity replay path —
        # verify it dispatches the tick cadence + honors the 0-broker/0-alert契约.
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        engine.register(LimitDownDetection(), cadence="tick")

        before_sell = len(adapter.sell_calls)
        before_alert = len(adapter.alerts)
        results = adapter.evaluate_at(context.timestamp, context, engine)
        adapter.verify_pure_function_contract(
            before_sell_count=before_sell, before_alert_count=before_alert
        )

        assert len(results) == 3
        # Dedup contract: re-running the same timestamp yields 0 new events.
        assert adapter.evaluate_at(context.timestamp, context, engine) == []


# ─────────────────────────────────────────────────────────────
# Scenario 2 — 单股闪崩 (-15% in 5min)
# ─────────────────────────────────────────────────────────────


class TestScenario2SingleStockFlashCrash:
    """V3 §15.6 #2 — 单股 5min 内闪崩 -15%.

    Expected: RapidDrop5min (5min cadence) fires for the single crashing stock.
    Other positions (steady) produce no result — isolation verified.
    """

    @pytest.fixture
    def context(self) -> RiskContext:
        positions = (
            _position("600000.SH", current_price=85.0),  # -15% crash
            _position("600004.SH", current_price=99.5),  # steady, no trigger
        )
        realtime = {
            "600000.SH": _tick(price_5min_ago=100.0, prev_close=88.0),
            "600004.SH": _tick(price_5min_ago=100.0, prev_close=100.0),
        }
        return _context(
            positions,
            realtime,
            timestamp=_EVENT_DATE.replace(hour=11, minute=5, second=0),
        )

    def test_rapid_drop_5min_fires_for_crashing_stock_only(self, context: RiskContext) -> None:
        engine = RealtimeRiskEngine()
        engine.register(RapidDrop5min(), cadence="5min")

        results = engine.on_5min_beat(context)

        assert len(results) == 1
        r = results[0]
        assert r.rule_id == "rapid_drop_5min"
        assert r.code == "600000.SH"
        # (85 - 100) / 100 = -0.15 exactly — production round(drop_pct, 6) is
        # identity here; the approx tolerance just guards IEEE-754 noise.
        assert r.metrics["drop_pct"] == pytest.approx(-0.15, abs=1e-6)

    def test_steady_stock_does_not_trigger(self, context: RiskContext) -> None:
        # -0.5% move on 600004.SH stays well below the 5% RapidDrop5min threshold.
        engine = RealtimeRiskEngine()
        engine.register(RapidDrop5min(), cadence="5min")
        results = engine.on_5min_beat(context)
        assert all(r.code != "600004.SH" for r in results)

    def test_evaluate_at_5min_boundary_dispatch(self, context: RiskContext) -> None:
        # evaluate_at only dispatches 5min cadence when minute % 5 == 0 + second == 0.
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        engine.register(RapidDrop5min(), cadence="5min")

        # context.timestamp is 11:05:00 → on a 5min boundary → 5min rules run.
        on_boundary = adapter.evaluate_at(context.timestamp, context, engine)
        assert len(on_boundary) == 1

        # A non-boundary timestamp (11:07:00) → 5min rules skipped.
        adapter.reset()
        off_boundary_ts = context.timestamp.replace(minute=7)
        assert adapter.evaluate_at(off_boundary_ts, context, engine) == []


# ─────────────────────────────────────────────────────────────
# Scenario 3 — 行业崩盘 (持仓 5 股同行业, 行业 day -5%)
# ─────────────────────────────────────────────────────────────


class TestScenario3IndustryCollapse:
    """V3 §15.6 #3 — 持仓 5 股全同一行业, 行业当日 -5%+.

    Expected:
      - IndustryConcentration (5min) fires 1 portfolio-level P2 (5/5 = 100% > 30%).
      - CorrelatedDrop (5min) fires 1 P0 (5 股 5min 联动 ≥ 3%).
    """

    _CODES = ("601012.SH", "600875.SH", "002129.SZ", "300274.SZ", "688599.SH")
    _INDUSTRY = "电力设备"

    @pytest.fixture
    def context(self) -> RiskContext:
        # 5 stocks, all 电力设备, each down ~6% in the last 5min (行业崩盘 day -5%+).
        positions = tuple(_position(c, current_price=94.0) for c in self._CODES)
        realtime = {
            c: _tick(prev_close=100.0, price_5min_ago=100.0, industry=self._INDUSTRY)
            for c in self._CODES
        }
        return _context(
            positions,
            realtime,
            timestamp=_EVENT_DATE.replace(hour=13, minute=30, second=0),
        )

    def test_industry_concentration_fires(self, context: RiskContext) -> None:
        engine = RealtimeRiskEngine()
        engine.register(IndustryConcentration(), cadence="5min")

        results = engine.on_5min_beat(context)

        assert len(results) == 1
        ic = results[0]
        assert ic.rule_id == "industry_concentration"
        assert ic.code == ""  # portfolio-level
        assert ic.metrics["top_industry"] == self._INDUSTRY
        assert ic.metrics["concentration"] == pytest.approx(1.0, abs=1e-6)
        assert ic.metrics["total_positions"] == 5

    def test_correlated_drop_fires_for_all_5(self, context: RiskContext) -> None:
        engine = RealtimeRiskEngine()
        engine.register(CorrelatedDrop(), cadence="5min")

        results = engine.on_5min_beat(context)

        assert len(results) == 1
        assert results[0].rule_id == "correlated_drop"
        assert results[0].metrics["triggered_count"] == 5

    def test_diversified_portfolio_does_not_trigger_concentration(self) -> None:
        # Control: 5 stocks across 5 distinct industries → no concentration alert.
        positions = tuple(_position(c, current_price=94.0) for c in self._CODES)
        realtime = {
            c: _tick(prev_close=100.0, industry=f"行业{i}") for i, c in enumerate(self._CODES)
        }
        ctx = _context(
            positions,
            realtime,
            timestamp=_EVENT_DATE.replace(hour=13, minute=30, second=0),
        )
        engine = RealtimeRiskEngine()
        engine.register(IndustryConcentration(), cadence="5min")
        assert engine.on_5min_beat(ctx) == []


# ─────────────────────────────────────────────────────────────
# Scenario 4/5 — LLM-backed regime scenarios: mock-agent helpers
#
# These scenarios inject MagicMock Bull/Bear/Judge agents via the
# MarketRegimeService DI slots (bull_agent= / bear_agent= / judge=). This
# exercises the REAL classify() orchestration (cost summing, MarketRegime
# assembly, decision_id sub-suffixing) WITHOUT coupling the synthetic-scenario
# fixture to the prompt YAML files on disk — agent-internal JSON parsing is
# §15.2 unit-test scope (test_market_regime_service.py), not §15.6 scope.
# ─────────────────────────────────────────────────────────────


def _regime_args() -> tuple[RegimeArgument, RegimeArgument, RegimeArgument]:
    """Build a fixed 3-tuple of RegimeArgument (V3 §5.3 真 3 论据)."""
    return (
        RegimeArgument(argument="论据一", evidence="数据一", weight=0.6),
        RegimeArgument(argument="论据二", evidence="数据二", weight=0.5),
        RegimeArgument(argument="论据三", evidence="数据三", weight=0.4),
    )


def _mock_regime_service(
    *,
    regime: RegimeLabel,
    confidence: float,
    bull_cost: Decimal = Decimal("0.0013"),
    bear_cost: Decimal = Decimal("0.0011"),
    judge_cost: Decimal = Decimal("0.0015"),
) -> tuple[MarketRegimeService, MagicMock, MagicMock, MagicMock]:
    """Build a MarketRegimeService with mock Bull/Bear/Judge agents (DI, no YAML).

    Returns (service, bull_agent, bear_agent, judge) so tests can assert on the
    agent call counts + decision_id sub-suffixes the real classify() passes down.
    """
    bull = MagicMock()
    bull.find_arguments.return_value = (_regime_args(), bull_cost)
    bear = MagicMock()
    bear.find_arguments.return_value = (_regime_args(), bear_cost)
    judge = MagicMock()
    judge.judge.return_value = (
        regime,
        confidence,
        f"加权 Bull/Bear 6 论据后判定 {regime.value}.",
        judge_cost,
    )
    service = MarketRegimeService(router=MagicMock(), bull_agent=bull, bear_agent=bear, judge=judge)
    return service, bull, bear, judge


def _indicators(*, hour: int, sse_return: float) -> MarketIndicators:
    """Build a MarketIndicators snapshot at a given hour with a given SSE return."""
    return MarketIndicators(
        timestamp=_EVENT_DATE.replace(hour=hour, minute=0, second=0),
        sse_return=sse_return,
        hs300_return=sse_return * 1.1,
        breadth_up=2800 if sse_return > 0 else 800,
        breadth_down=1200 if sse_return > 0 else 3600,
        north_flow_cny=85.0 if sse_return > 0 else -120.0,
        iv_50etf=0.18 if sse_return > 0 else 0.34,
    )


# ─────────────────────────────────────────────────────────────
# Scenario 4 — regime 急转 (Bull → Bear in 1 day)
# ─────────────────────────────────────────────────────────────


class TestScenario4RegimeFlip:
    """V3 §15.6 #4 — regime 在一天内从 Bull 急转 Bear.

    Expected: MarketRegimeService.classify() run twice (morning bullish snapshot,
    afternoon bearish snapshot) yields RegimeLabel.BULL then RegimeLabel.BEAR — the
    transition is detected. Exercises the REAL classify() orchestration via DI agents.
    """

    def test_regime_flips_bull_to_bear_same_day(self) -> None:
        # Morning: Judge returns Bull.
        morning_service, *_ = _mock_regime_service(regime=RegimeLabel.BULL, confidence=0.78)
        morning = morning_service.classify(
            _indicators(hour=9, sse_return=0.021), decision_id="syn4-am"
        )

        # Afternoon: Judge returns Bear.
        afternoon_service, *_ = _mock_regime_service(regime=RegimeLabel.BEAR, confidence=0.83)
        afternoon = afternoon_service.classify(
            _indicators(hour=14, sse_return=-0.038), decision_id="syn4-pm"
        )

        assert isinstance(morning, MarketRegime)
        assert isinstance(afternoon, MarketRegime)
        assert morning.regime == RegimeLabel.BULL
        assert afternoon.regime == RegimeLabel.BEAR
        # The flip happened within the same trading day.
        assert morning.indicators is not None
        assert afternoon.indicators is not None
        assert morning.indicators.timestamp.date() == afternoon.indicators.timestamp.date()
        # 急转 = adjacent regimes differ → transition detected.
        assert morning.regime != afternoon.regime
        # Cost accumulated across the 3 agent calls (0.0013 + 0.0011 + 0.0015).
        assert morning.cost_usd == pytest.approx(0.0039, abs=1e-9)

    def test_classify_dispatches_bull_bear_judge_in_order(self) -> None:
        service, bull, bear, judge = _mock_regime_service(regime=RegimeLabel.BULL, confidence=0.7)
        service.classify(_indicators(hour=9, sse_return=0.02), decision_id="ord")

        # Each of the 3 V4-Pro agents invoked exactly once.
        assert bull.find_arguments.call_count == 1
        assert bear.find_arguments.call_count == 1
        assert judge.judge.call_count == 1
        # decision_id sub-suffixes threaded through to each agent (audit trail).
        assert bull.find_arguments.call_args.kwargs["decision_id"] == "ord-bull"
        assert bear.find_arguments.call_args.kwargs["decision_id"] == "ord-bear"
        assert judge.judge.call_args.kwargs["decision_id"] == "ord-judge"


# ─────────────────────────────────────────────────────────────
# Scenario 5 — LLM 服务全挂 + Ollama fallback
# ─────────────────────────────────────────────────────────────


class TestScenario5LLMOutageAndFallback:
    """V3 §15.6 #5 — LLM 服务全挂 + Ollama fallback.

    Three halves:
      (a) Full outage → MarketRegimeService fail-loud (raises + short-circuits, NOT a
          silent garbage regime).
      (b) L1 RealtimeRiskEngine (LLM-independent) keeps detecting — graceful
          degradation: 实时风控 survives an L2 LLM outage.
      (c) Ollama fallback path → when the LiteLLM router has fallen back to
          qwen3-local, the agents still return usable (0-cost) results and classify()
          still produces a valid MarketRegime. (Router-level is_fallback detection is
          the LiteLLMRouter's own unit-test scope, not §15.6.)
    """

    def test_llm_full_outage_fails_loud(self) -> None:
        # All LLM endpoints unreachable — the Bull agent's first call raises.
        service, bull, bear, judge = _mock_regime_service(
            regime=RegimeLabel.NEUTRAL, confidence=0.5
        )
        bull.find_arguments.side_effect = ConnectionError("LLM service cluster unreachable")

        # Fail-loud: classify must raise, never return a fabricated regime (铁律 33).
        with pytest.raises(ConnectionError, match="unreachable"):
            service.classify(_indicators(hour=10, sse_return=-0.02))
        # Short-circuit: bear + judge never invoked after the bull-call failure.
        assert bull.find_arguments.call_count == 1
        assert bear.find_arguments.call_count == 0
        assert judge.judge.call_count == 0

    def test_l1_detection_survives_llm_outage(self) -> None:
        # L1 RealtimeRiskEngine rules are pure (0 LLM) — they MUST keep working
        # even when the entire LLM stack is down. This is the core degradation 契约.
        positions = (_position("600519.SH", current_price=90.0),)  # -10% 跌停板
        realtime = {"600519.SH": _tick(prev_close=100.0)}
        ctx = _context(
            positions,
            realtime,
            timestamp=_EVENT_DATE.replace(hour=10, minute=0, second=0),
        )
        engine = RealtimeRiskEngine()
        engine.register(LimitDownDetection(), cadence="tick")

        results = engine.on_tick(ctx)
        assert len(results) == 1
        assert results[0].rule_id == "limit_down_detection"

    def test_ollama_fallback_path_still_classifies(self) -> None:
        # LLM primary down → LiteLLM router falls back to qwen3-local (Ollama).
        # Ollama is local → 0 cost. The agents still return valid results, so
        # classify() still produces a usable MarketRegime — regime detection
        # stays alive through the fallback.
        service, *_ = _mock_regime_service(
            regime=RegimeLabel.BEAR,
            confidence=0.6,
            bull_cost=Decimal("0.0"),
            bear_cost=Decimal("0.0"),
            judge_cost=Decimal("0.0"),
        )
        result = service.classify(_indicators(hour=10, sse_return=-0.025))

        assert isinstance(result, MarketRegime)
        assert result.regime == RegimeLabel.BEAR
        assert result.confidence == pytest.approx(0.6, abs=1e-9)
        # Local Ollama fallback → 0 cost; cost accumulation still sums cleanly.
        assert result.cost_usd == pytest.approx(0.0, abs=1e-9)


# ─────────────────────────────────────────────────────────────
# Scenario 6 — DingTalk 不可用 + email backup
# ─────────────────────────────────────────────────────────────


class TestScenario6DingTalkDownEmailBackup:
    """V3 §15.6 #6 — DingTalk 推送不可用, 降级 email backup.

    Expected: AlertDispatcher.dispatch of a P0 alert with a failing send_fn (DingTalk
    down) records send_failed; the caller then falls back to EmailBackupStub which
    persists the alert to a JSONL file. The alert is NOT silently lost (铁律 33).
    """

    @pytest.fixture
    def p0_alert(self) -> RuleResult:
        return RuleResult(
            rule_id="limit_down_detection",  # a P0 rule per AlertDispatcher routing
            code="600519.SH",
            shares=0,
            reason="LimitDownDetection: 600519.SH 触发跌停",
            metrics={"drop_pct": -0.11},
        )

    def test_dingtalk_down_records_send_failure(self, p0_alert: RuleResult) -> None:
        # send_fn returns False → DingTalk push failed.
        dispatcher = AlertDispatcher(send_fn=lambda _r: False)
        immediate = dispatcher.dispatch([p0_alert])

        # P0 is dispatched immediately (count=1) but the send itself failed.
        assert immediate == 1
        assert dispatcher.stats["send_failed"] == 1
        assert dispatcher.stats["p0_sent"] == 0

    def test_email_backup_persists_failed_alert(self, p0_alert: RuleResult, tmp_path) -> None:
        # DingTalk down → caller routes the failed alert to EmailBackupStub.
        log_path = tmp_path / "email_backup.jsonl"
        backup = EmailBackupStub(log_path=log_path)

        backup.backup(p0_alert, retry_count=3)

        assert backup.backup_count == 1
        assert log_path.exists()
        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["rule_id"] == "limit_down_detection"
        assert record["code"] == "600519.SH"
        assert record["retry_exhausted_after"] == 3

    def test_dingtalk_down_then_email_backup_end_to_end(
        self, p0_alert: RuleResult, tmp_path
    ) -> None:
        # End-to-end degradation chain: DingTalk fails → email backup catches it.
        log_path = tmp_path / "email_backup.jsonl"
        backup = EmailBackupStub(log_path=log_path)

        def send_with_email_fallback(result: RuleResult) -> bool:
            # Simulate the production wire: DingTalk send fails → email backup.
            dingtalk_ok = False  # DingTalk 不可用
            if not dingtalk_ok:
                backup.backup(result, retry_count=3)
            return dingtalk_ok

        dispatcher = AlertDispatcher(send_fn=send_with_email_fallback)
        dispatcher.dispatch([p0_alert])

        # DingTalk failed, but the alert survived via email backup — 0 silent loss.
        assert dispatcher.stats["send_failed"] == 1
        assert backup.backup_count == 1
        assert log_path.exists()


# ─────────────────────────────────────────────────────────────
# Scenario 7 — user 离线 4h + STAGED 30min timeout
# ─────────────────────────────────────────────────────────────


class TestScenario7UserOfflineStagedTimeout:
    """V3 §15.6 #7 — user 离线 4h, STAGED plan 30min cancel 窗口超时 → 默认执行.

    Expected: an L4 STAGED ExecutionPlan generated at T0 has a strict 30min cancel
    window. Within the window (T0+15min) it stays PENDING_CONFIRM. After the window
    (user offline 4h → T0+4h) it is expired, check_timeout fires, and timeout_execute
    transitions it to TIMEOUT_EXECUTED — the reverse-decision-window degraded into a
    default-execute (V3 §13.1 SLA #5: STAGED 30min 严格).
    """

    @pytest.fixture
    def staged_plan(self):
        # A triggered sell RuleResult (code set + shares > 0 → actionable plan).
        result = RuleResult(
            rule_id="trailing_stop",
            code="600519.SH",
            shares=500,
            reason="TrailingStop: 600519.SH 触发动态止盈",
            metrics={"current_price": 200.0},
        )
        planner = L4ExecutionPlanner(staged_enabled=True)
        # T0 = 10:00 — normal trading window (not auction, not late session).
        t0 = _EVENT_DATE.replace(hour=10, minute=0, second=0)
        plan = planner.generate_plan(result, mode=ExecutionMode.STAGED, at=t0)
        assert plan is not None
        return plan, t0

    def test_staged_plan_has_strict_30min_window(self, staged_plan) -> None:
        plan, _t0 = staged_plan
        assert plan.mode == ExecutionMode.STAGED
        assert plan.status == PlanStatus.PENDING_CONFIRM
        # V3 §13.1 SLA #5: STAGED cancel 窗口 严格 30min.
        assert plan.cancel_deadline - plan.scheduled_at == timedelta(minutes=30)

    def test_within_window_plan_not_expired(self, staged_plan) -> None:
        plan, t0 = staged_plan
        # User checks back at T0+15min — still inside the 30min window.
        within = t0 + timedelta(minutes=15)
        assert plan.is_expired(within) is False
        assert L4ExecutionPlanner.check_timeout(plan, within) is False

    def test_user_offline_4h_triggers_timeout_execute(self, staged_plan) -> None:
        plan, t0 = staged_plan
        # User offline 4h — well past the 30min window.
        offline_until = t0 + timedelta(hours=4)
        assert plan.is_expired(offline_until) is True
        assert L4ExecutionPlanner.check_timeout(plan, offline_until) is True

        # Timeout → default-execute (反向决策权 窗口耗尽 → 默认执行).
        executed = plan.timeout_execute(offline_until)
        assert executed.status == PlanStatus.TIMEOUT_EXECUTED
        assert executed.user_decision == "timeout"
        assert executed.user_decision_at == offline_until
        # The PENDING_CONFIRM → TIMEOUT_EXECUTED transition is valid per the state machine.
        assert L4ExecutionPlanner.valid_transition(
            PlanStatus.PENDING_CONFIRM, PlanStatus.TIMEOUT_EXECUTED
        )

    def test_user_cancels_within_window_blocks_timeout(self, staged_plan) -> None:
        # Control: if the user IS online and cancels within the window, the plan is
        # CANCELLED and can never be timeout-executed (terminal state).
        plan, t0 = staged_plan
        cancelled = plan.cancel(t0 + timedelta(minutes=10))
        assert cancelled.status == PlanStatus.CANCELLED
        assert not L4ExecutionPlanner.valid_transition(
            PlanStatus.CANCELLED, PlanStatus.TIMEOUT_EXECUTED
        )

    def test_alert_only_result_does_not_generate_staged_plan(self) -> None:
        # Control: alert_only L1 rules emit shares=0 RuleResult — generate_plan
        # returns None (no STAGED plan for non-actionable alerts). Confirms the
        # "user 离线 → timeout" path only ever applies to actionable sells.
        alert_only_result = RuleResult(
            rule_id="limit_down_detection",
            code="600519.SH",
            shares=0,  # alert_only rules emit shares=0
            reason="LimitDownDetection: 600519.SH 触发跌停 (alert_only, 不挂 sell)",
            metrics={"drop_pct": -0.10},
        )
        planner = L4ExecutionPlanner(staged_enabled=True)
        t0 = _EVENT_DATE.replace(hour=10, minute=0, second=0)
        assert planner.generate_plan(alert_only_result, mode=ExecutionMode.STAGED, at=t0) is None
