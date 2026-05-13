"""ReplayRunner — V3 Tier B replay infrastructure (TB-1b sediment).

Orchestrates minute_bars window replay through RiskBacktestAdapter.evaluate_at,
collects RuleResults + counterfactual summary for V3 §15.5 sim-to-real gap audit.

Architecture (α — sustained user ack 2026-05-13):
- ReplayRunner holds: adapter (RiskBacktestAdapter) + engine (RealtimeRiskEngine)
- minute_bars loader builds RiskContext per timestamp from DB rows
- Each timestamp → adapter.evaluate_at(ts, ctx, engine) → list[RuleResult]
- Events collected + summarized via counterfactual.summarize_events()
- Output sediment to docs/risk_reflections/replay/YYYY_QX_<event>.md

Pure-function contract sustained (V3 §11.4 line 1294): 0 broker / 0 alert /
0 INSERT during replay run. ReplayRunner relies on adapter's
verify_pure_function_contract() for assert.

关联:
- V3 §11.4 (RiskBacktestAdapter pure function)
- V3 §15.5 (历史回放 sim-to-real gap counterfactual)
- ADR-029 (10 RealtimeRiskRule)
- ADR-064 D3=b (2 关键窗口: 2024Q1 量化踩踏 + 2025-04-07 关税 -13.15%)
- ADR-066 候选 (TB-1 closure, 留 TB-1c)
- LL-159 (4-step preflight SOP)
- 铁律 41 (timezone enforcement via adapter.evaluate_at)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .counterfactual import EventSummary, summarize_events

if TYPE_CHECKING:
    from ..backtest_adapter import RiskBacktestAdapter
    from ..interface import Position, RiskContext, RuleResult
    from ..realtime.engine import RealtimeRiskEngine

logger = logging.getLogger(__name__)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ReplayWindow:
    """Replay window definition — 2 关键窗口 per ADR-064 D3=b sustained.

    Args:
      name: human-readable label (e.g. "2024Q1_quant_crash").
      start_date: window start (inclusive, Asia/Shanghai trade date).
      end_date: window end (inclusive).
      description: brief context (e.g. "雪球结构化产品踩踏 + 微盘股下跌").
    """

    name: str
    start_date: date
    end_date: date
    description: str = ""


# D3=b lock: 2 关键窗口 (sustained ADR-064 + Plan v0.2 §A TB-1 row)
WINDOW_2024Q1_QUANT_CRASH = ReplayWindow(
    name="2024Q1_quant_crash",
    start_date=date(2024, 1, 2),
    end_date=date(2024, 2, 9),
    description="雪球结构化产品集中敲入 + 量化中性策略踩踏 (2024-01~02), 微盘股下跌 + 千股跌停",
)

WINDOW_2025_04_07_TARIFF_SHOCK = ReplayWindow(
    name="2025_04_07_tariff_shock",
    start_date=date(2025, 4, 1),
    end_date=date(2025, 4, 11),
    description="关税冲击 4-07 大盘单日 -13.15% + 千股跌停 (TB-1 真测窗口 #2)",
)

ALL_WINDOWS = (WINDOW_2024Q1_QUANT_CRASH, WINDOW_2025_04_07_TARIFF_SHOCK)


@dataclass
class ReplayRunResult:
    """ReplayRunner.run_window output.

    Args:
      window: replayed window definition.
      events: collected RuleResult list (post-dedup via adapter.evaluate_at).
      summary: EventSummary aggregate.
      total_timestamps: number of unique timestamps replayed.
      total_minute_bars: number of minute_bars rows consumed.
      wall_clock_seconds: replay run duration (informational).
      pure_function_contract_verified: True if 0 broker / 0 alert during run.
    """

    window: ReplayWindow
    events: list[RuleResult] = field(default_factory=list)
    summary: EventSummary | None = None
    total_timestamps: int = 0
    total_minute_bars: int = 0
    wall_clock_seconds: float = 0.0
    pure_function_contract_verified: bool = False


class ReplayRunner:
    """V3 Tier B replay orchestrator.

    Args:
      adapter: RiskBacktestAdapter with evaluate_at extension (TB-1a).
      engine: RealtimeRiskEngine with rules registered (use
        adapter.register_all_realtime_rules to register all 10).
      minute_bars_loader: callable taking (start_date, end_date) returning
        iterable of dict-like rows {trade_time, code, open, high, low, close,
        volume, amount}. Default impl uses psycopg2 (caller injects connection
        factory via constructor).
      tz: timezone for timestamp normalization (default Asia/Shanghai trade tz).

    Usage:
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        adapter.register_all_realtime_rules(engine)
        runner = ReplayRunner(adapter, engine, minute_bars_loader=my_loader)
        result = runner.run_window(WINDOW_2024Q1_QUANT_CRASH, positions=())
        # result.summary.to_markdown() → sediment to docs/risk_reflections/replay/
    """

    def __init__(
        self,
        adapter: RiskBacktestAdapter,
        engine: RealtimeRiskEngine,
        *,
        minute_bars_loader: Any = None,
        tz: ZoneInfo = SHANGHAI_TZ,
    ) -> None:
        self._adapter = adapter
        self._engine = engine
        self._loader = minute_bars_loader
        self._tz = tz

    def build_context(
        self,
        timestamp: datetime,
        positions: tuple[Position, ...],
        bar_row: dict[str, Any],
    ) -> RiskContext:
        """Build RiskContext for a given timestamp + bar row.

        Args:
            timestamp: tz-aware datetime (caller normalizes via _normalize_ts).
            positions: tuple of Position (frozen).
            bar_row: minute_bars row dict with code / close / volume / etc.

        Returns:
            RiskContext with realtime dict populated for the bar's symbol.
        """
        from ..interface import RiskContext  # lazy import

        code = bar_row["code"]
        realtime = {
            code: {
                "prev_close": float(bar_row.get("prev_close", 0) or 0),
                "open_price": float(bar_row.get("open", 0) or 0),
                "current_price": float(bar_row.get("close", 0) or 0),
                "high": float(bar_row.get("high", 0) or 0),
                "low": float(bar_row.get("low", 0) or 0),
                "day_volume": int(bar_row.get("volume", 0) or 0),
                "amount": float(bar_row.get("amount", 0) or 0),
            },
        }
        return RiskContext(
            strategy_id="tb_1b_replay",
            execution_mode="paper",
            timestamp=timestamp,
            positions=positions,
            portfolio_nav=1_000_000.0,  # synthetic NAV for replay
            prev_close_nav=1_000_000.0,
            realtime=realtime,
        )

    def _normalize_ts(self, raw_ts: datetime) -> datetime:
        """Ensure timestamp is tz-aware (Asia/Shanghai per 铁律 41)."""
        if raw_ts.tzinfo is None:
            return raw_ts.replace(tzinfo=self._tz)
        return raw_ts.astimezone(self._tz)

    def run_window(
        self,
        window: ReplayWindow,
        positions: tuple[Position, ...] = (),
        *,
        bars: list[dict[str, Any]] | None = None,
    ) -> ReplayRunResult:
        """Replay a window's minute_bars through evaluator.

        Args:
            window: ReplayWindow definition.
            positions: tuple of Position for context (default empty).
            bars: pre-loaded minute_bars rows (optional, mainly for testing).
                If None, uses self._loader(window.start_date, window.end_date).

        Returns:
            ReplayRunResult with events + summary + counts + pure-function audit.
        """
        import time

        # 4-step preflight: source data + cron alignment + natural production
        # behavior — caller responsibility to verify via SSOT before run_window.
        # ReplayRunner does pure-function contract audit only.

        # Snapshot broker/alert counts before run for pure-function audit
        before_sell = len(self._adapter.sell_calls)
        before_alert = len(self._adapter.alerts)

        # Load bars if not pre-loaded
        if bars is None:
            if self._loader is None:
                raise ValueError(
                    "ReplayRunner: 必 inject minute_bars_loader OR pass bars param "
                    "(沿用铁律 33 fail-loud)"
                )
            bars = list(self._loader(window.start_date, window.end_date))

        # Group bars by timestamp for per-timestamp dispatch
        # (multiple symbols can share a timestamp — process all together)
        ts_to_bars: dict[datetime, list[dict[str, Any]]] = {}
        for bar in bars:
            ts = self._normalize_ts(bar["trade_time"])
            ts_to_bars.setdefault(ts, []).append(bar)

        events: list[RuleResult] = []
        start_time = time.monotonic()

        for ts in sorted(ts_to_bars.keys()):
            ts_bars = ts_to_bars[ts]
            # For each timestamp, evaluate per symbol (one context per bar)
            # Dedup contract handles cross-symbol uniqueness
            for bar in ts_bars:
                ctx = self.build_context(ts, positions, bar)
                bar_events = self._adapter.evaluate_at(ts, ctx, self._engine)
                events.extend(bar_events)

        wall_clock = time.monotonic() - start_time

        # Construct window UTC timestamps for summary metadata
        window_start_dt = datetime.combine(
            window.start_date, datetime.min.time()
        ).replace(tzinfo=UTC)
        window_end_dt = (
            datetime.combine(window.end_date, datetime.min.time()).replace(tzinfo=UTC)
            + timedelta(days=1)
        )

        summary = summarize_events(
            events,
            window_start=window_start_dt,
            window_end=window_end_dt,
        )

        # Pure-function contract audit
        contract_verified = True
        try:
            self._adapter.verify_pure_function_contract(
                before_sell_count=before_sell,
                before_alert_count=before_alert,
            )
        except AssertionError as e:
            contract_verified = False
            logger.error(
                "[ReplayRunner] V3 §11.4 pure-function contract violated: %s", e
            )

        return ReplayRunResult(
            window=window,
            events=events,
            summary=summary,
            total_timestamps=len(ts_to_bars),
            total_minute_bars=len(bars),
            wall_clock_seconds=wall_clock,
            pure_function_contract_verified=contract_verified,
        )
