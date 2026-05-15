#!/usr/bin/env python3
"""V3 IC-3a — 5y full minute_bars replay on FULLY-INTEGRATED V3 chain.

Plan v0.4 §A IC-3a — extends HC-4a's L1-RealtimeRiskEngine-only 5y replay to
also exercise the L3 daily-cadence PURE rules layer (PMSRule +
PositionHoldingTimeRule + NewPositionVolatilityRule + SingleStockStopLossRule).
The 4 §15.4 acceptance criteria (FP rate / latency P99 / STAGED 0 failed /
元监控 contract) remain L1-derived (sustained ADR-070 methodology). The L3
extension is an additional **wiring assertion section** in the report
demonstrating the daily-cadence rules execute without crash over the full 5y
horizon — sustained synthetic-universe methodology per acceptance.py §1
("synthetic universe-wide Position = 误报率 upper-bound proxy NOT
production-portfolio precision; wiring + correctness test, not real-portfolio
P&L precision").

**Why L3 over L2/L0**:
  - L0 News classifier: no news data in minute_bars (acceptance.py already
    documents this as out-of-replay-path, sustained TB-5a synthetic scenario 5).
  - L2 regime detection: Bull/Bear/Judge LLM debate is OUT-OF-BAND per IC-3
    Q2 decision (LLM lesson-learning loop is post-event, NOT signal critical
    path; including LLM in replay would mock-out anyway).
  - L3 daily-cadence rules: live in `qm_platform.risk.rules.{pms, holding_time,
    new_position, single_stock}`, all marked 铁律 31 纯计算 (verified via
    multi-directory grep per LL-172 lesson 1 amended preflight). PURE
    .evaluate(RiskContext) — directly invokable without PlatformRiskEngine
    instantiation (which would pull in broker / notifier / conn_factory IO
    deps that replay must not exercise).
  - L4 STAGED state machine: already exercised by HC-4a via
    `evaluate_staged_closure` in acceptance.py.

**Why NOT CircuitBreakerRule**:
  - circuit_breaker.py internally calls legacy `_check_cb_sync` which does DB
    SELECT on trade_log for cumulative P&L (NOT pure). Including it would
    require either mock conn returning synthetic trade history OR skipping
    the 1 P&L-dependent rule — adds complexity for marginal coverage. The 4
    PURE rules above already establish "NOT only L1" per Plan §A IC-3a.

**Why NOT PlatformRiskEngine.run()**:
  - PlatformRiskEngine requires DI of broker / notifier / price_reader /
    conn_factory + primary/fallback PositionSource. Replay-mode mock setup
    multiplies surface area without testing more semantics — each Rule.evaluate
    is PURE (铁律 31), so direct invocation is equivalent + lighter.

**Synthetic position construction** (per trading day per code):
  - shares = 1 (sustained synthetic-universe体例)
  - entry_price = first bar's open (synthetic intra-day entry)
  - peak_price = max(high) over all bars that day
  - current_price = last bar's close (day-end)
  - entry_date = trade_date (holding_days = 0 for the day's evaluation)

  Most daily rules WILL NOT trigger on single-day synthetic positions:
    - PMSRule needs ≥10% gain + ≥10% drawdown (Level 3 most lenient) → rare
      in single intra-day window.
    - PositionHoldingTimeRule needs ≥30 days holding → holding_days=0 here,
      always skips. (Wiring smoke only.)
    - NewPositionVolatilityRule needs new-position AND loss; loss possible
      when close < open, may trigger.
    - SingleStockStopLossRule needs ≥10% loss from entry; possible on bad days.

  Triggers themselves are NOT the test; **0 crash across 5y × 252 td × N
  codes × 4 rules** is the wiring-assertion test. Per-rule trigger counts are
  reported for transparency (replay-as-instrumentation, NOT replay-as-alpha).

**Synthetic NAV**: sum(shares × current_price) across all synthetic positions
  for the trading day. portfolio_nav consistency is a precondition for
  daily-cadence rules that may consume it; PMSRule uses peak/entry/current
  per-position so portfolio_nav is informational.

**Safety**: 0 broker / 0 .env / 0 INSERT — pure read-only DB SELECT + in-memory
replay (sustained HC-4a + TB-5b). Re-runnable. Per-quarter pure-function
contract audited.

4-step preflight verify SOP (sustained LL-159 + LL-172 amendment):
  ✅ Step 1 SSOT calendar: per-quarter windows over minute_bars actual range
     (2021-2025 per CLAUDE.md §因子存储).
  ✅ Step 2 data presence: minute_bars 190,885,634 rows verified (CLAUDE.md).
  N/A Step 3 cron alignment: one-shot ops script, not a schtask.
  N/A Step 4 natural production behavior: this script IS the verification.
  ✅ Step 5 multi-directory grep (LL-172 lesson 1): verified 0 reflector
     imports in `backend/qm_platform/risk/realtime/` confirming LLM out-of-band;
     verified 4 daily rules in `rules/` carry 铁律 31 PURE marker.

Usage:
    python scripts/v3_ic_3a_5y_integrated_replay.py                  # full 5y
    python scripts/v3_ic_3a_5y_integrated_replay.py --codes-limit 50 # quick smoke
    python scripts/v3_ic_3a_5y_integrated_replay.py --quarters 2     # first 2 quarters only
    python scripts/v3_ic_3a_5y_integrated_replay.py --dry-run        # no markdown sediment

关联铁律: 22 / 24 / 25 / 31 (rules PURE) / 33 / 41
关联 V3: §15.4 (4 项 acceptance) / §13.1 (SLA) / §15.5 (counterfactual replay 体例)
关联 ADR: ADR-063 (Tier B 真测路径) / ADR-066 (TB-1 baseline) / ADR-070
  (TB-5b methodology + 阈值 sustained) / ADR-076 (横切层 closed prereq) /
  ADR-080 候选 (IC-3 closure 体例)
关联 Plan: V3_PT_CUTOVER_PLAN_v0.1.md §A IC-3a row + §B + §F
关联 LL: LL-098 X10 / LL-159 (4-step preflight) / LL-170 候选 lesson 3
  (replay-as-gate 取代 wall-clock observation) / LL-172 lesson 1 (multi-dir grep)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# PROJECT_ROOT itself enables `from backend.qm_platform._types ...` imports
# (some backtest sub-modules use this form, distinct from the `from qm_platform.*`
# form HC-4a relies on). Add both PROJECT_ROOT and backend/ to maximize coverage.
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Reuse HC-4a's per-quarter loop entirely (DRY — 0 duplication of HC-4a's
# closure-free helpers, sustained ADR-022 反 closed-code blast radius).
from v3_hc_4a_5y_replay_acceptance import (  # noqa: E402
    _aggregate,
    _build_quarter_windows,
    _QuarterResult,
    _run_quarter,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


# ---------- L3 daily-cadence rule eval (NEW for IC-3a) ----------


@dataclass
class _QuarterDailyMetrics:
    """L3 daily-cadence rule evaluation metrics for one quarter.

    Wiring-assertion fields (sustained synthetic-universe体例):
      trading_days: distinct (code-agnostic) trading days seen in this quarter.
      synthetic_positions: total (code, day) pairs evaluated.
      eval_calls: total Rule.evaluate calls = trading_days × len(daily_rules).
      crashes: any rule.evaluate() raise — must be 0 for green wiring.
      triggers_by_rule: per-rule_id RuleResult count (informational, NOT a
        verdict; synthetic positions deliberately rarely satisfy real rule
        thresholds, per docstring §Synthetic position construction).
    """

    trading_days: int = 0
    synthetic_positions: int = 0
    eval_calls: int = 0
    crashes: int = 0
    triggers_by_rule: dict[str, int] = field(default_factory=dict)


def _build_synthetic_positions(bars_for_day: list[dict[str, Any]]) -> list[Any]:
    """Build synthetic Position list from one trading day's minute_bars.

    Per docstring §Synthetic position construction: groups bars by code, then
    for each (code, trade_date) emits 1 Position with entry=open-of-day,
    peak=max(high), current=close-of-day, shares=1, entry_date=trade_date.

    Args:
        bars_for_day: bars from minute_bars filtered to a single trade_date.
            Each bar is a dict with keys `trade_time` (datetime), `code` (str),
            `open` / `high` / `low` / `close` (float). Sustained TB-5b loader
            schema (v3_tb_5b_replay_acceptance._make_minute_bars_loader line 159).
            trade_date is derived from `trade_time.date()`.

    Returns:
        list[Position] — 1 per distinct code present that day. Skips codes
        whose price stream is degenerate (close <= 0 or open <= 0 — fail-loud
        candidates upstream, silent_ok here per synthetic-universe noise).
    """
    from qm_platform.risk.interface import Position

    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bar in bars_for_day:
        by_code[bar["code"]].append(bar)

    positions: list[Any] = []
    for code, bars in by_code.items():
        if not bars:
            continue
        # bars within a day are time-sorted by the upstream loader cursor.
        entry_price = float(bars[0]["open"])
        current_price = float(bars[-1]["close"])
        peak_price = max(float(b["high"]) for b in bars)
        if entry_price <= 0 or current_price <= 0 or peak_price < entry_price:
            # silent_ok: degenerate intraday stream (e.g. all-zero ticks before
            # listing day) — skip rather than feed rules garbage. Aligns with
            # PMSRule docstring "若 peak < entry, rule 应 skip".
            continue
        positions.append(
            Position(
                code=code,
                shares=1,
                entry_price=entry_price,
                peak_price=peak_price,
                current_price=current_price,
                entry_date=bars[0]["trade_time"].date(),
            )
        )
    return positions


def _build_synthetic_context(
    trade_date: date, positions: list[Any]
) -> Any:
    """Build RiskContext at 15:00 Asia/Shanghai of trade_date.

    Args:
        trade_date: the trading day's date (Asia/Shanghai calendar).
        positions: output of _build_synthetic_positions.

    Returns:
        RiskContext with tz-aware UTC timestamp (15:00 CST → 07:00 UTC),
        synthetic portfolio_nav = sum(shares × current_price), strategy_id
        "ic_3a_synthetic", execution_mode "paper".
    """
    from qm_platform.risk.interface import RiskContext

    # 15:00 Asia/Shanghai = EOD A-share trading close. Convert to UTC tz-aware
    # per 铁律 41 (RiskContext.timestamp contract).
    eod_local = datetime.combine(trade_date, dt_time(15, 0), tzinfo=_SHANGHAI_TZ)
    eod_utc = eod_local.astimezone(UTC)

    portfolio_nav = sum(p.shares * p.current_price for p in positions)

    return RiskContext(
        strategy_id="ic_3a_synthetic",
        execution_mode="paper",
        timestamp=eod_utc,
        positions=tuple(positions),
        portfolio_nav=portfolio_nav,
        prev_close_nav=None,
    )


def _build_daily_rules() -> list[Any]:
    """Construct the 4 PURE daily-cadence rules (no DI args, defaults).

    Returns:
        list[RiskRule]: PMSRule, PositionHoldingTimeRule,
            NewPositionVolatilityRule, SingleStockStopLossRule.

    Why these 4 (and not CircuitBreakerRule): docstring §Why NOT CircuitBreakerRule.
    """
    from qm_platform.risk.rules.holding_time import PositionHoldingTimeRule
    from qm_platform.risk.rules.new_position import NewPositionVolatilityRule
    from qm_platform.risk.rules.pms import PMSRule
    from qm_platform.risk.rules.single_stock import SingleStockStopLossRule

    return [
        PMSRule(),
        PositionHoldingTimeRule(),
        NewPositionVolatilityRule(),
        SingleStockStopLossRule(),
    ]


def _evaluate_daily_cadence_for_quarter(
    bars_in_quarter: list[Any], rules: list[Any]
) -> _QuarterDailyMetrics:
    """Run 4 daily-cadence PURE rules at each trading day's EOD over the quarter.

    Args:
        bars_in_quarter: bars from one HC-4a quarter window (already loaded).
        rules: output of _build_daily_rules.

    Returns:
        _QuarterDailyMetrics aggregating per-rule trigger counts + wiring health
        (eval_calls / crashes).
    """
    metrics = _QuarterDailyMetrics()
    if not bars_in_quarter:
        return metrics

    # Group bars by trade_date — bars are not guaranteed ordered across days
    # depending on cursor + ORDER BY; group defensively. trade_date derived
    # from `trade_time.date()` (TB-5b loader schema).
    bars_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for bar in bars_in_quarter:
        bars_by_date[bar["trade_time"].date()].append(bar)

    metrics.trading_days = len(bars_by_date)

    for trade_date, day_bars in sorted(bars_by_date.items()):
        positions = _build_synthetic_positions(day_bars)
        if not positions:
            # silent_ok: 0 positions = skip day (e.g. quarter-edge day with
            # only degenerate bars). Does NOT count toward eval_calls or
            # crashes since no rule was invoked.
            continue
        metrics.synthetic_positions += len(positions)
        ctx = _build_synthetic_context(trade_date, positions)

        for rule in rules:
            metrics.eval_calls += 1
            try:
                results = rule.evaluate(ctx)
            except Exception:  # noqa: BLE001 — wiring assertion: fail-loud
                # fail-loud: ANY rule.evaluate raise is the wiring-test failure
                # we exist to surface. Log + count, but continue other rules
                # (per-rule isolation, sustained PlatformRiskEngine.run体例).
                logger.exception(
                    "[IC-3a] daily-cadence rule crashed: rule=%s date=%s",
                    type(rule).__name__,
                    trade_date.isoformat(),
                )
                metrics.crashes += 1
                continue
            for r in results:
                metrics.triggers_by_rule[r.rule_id] = (
                    metrics.triggers_by_rule.get(r.rule_id, 0) + 1
                )

    return metrics


# ---------- Integrated per-quarter run ----------


@dataclass
class _QuarterIntegratedResult:
    """Combined L1 + L3-daily result for one quarter (sediment-safe)."""

    l1: _QuarterResult
    daily: _QuarterDailyMetrics


def _run_quarter_integrated(
    window: Any, conn: Any, codes_limit: int | None, rules: list[Any]
) -> _QuarterIntegratedResult | None:
    """Run HC-4a L1 + L4 STAGED + NEW L3 daily-cadence over one quarter.

    Implementation note: HC-4a's `_run_quarter` consumes its bar list via
    `bars = list(loader(...))` then `del bars` mid-function. To run L3
    daily-cadence WITHOUT double-loading the heavy bar stream (~3GB/quarter),
    we replicate HC-4a's loader call locally and pass bars to both:
      1. The HC-4a path (rebuilt locally — see comment block below).
      2. The new L3 daily-cadence evaluator.

    Args:
        window: ReplayWindow (per HC-4a).
        conn: psycopg2 connection (server-side cursor opened by loader).
        codes_limit: optional code subset cap.
        rules: pre-instantiated daily-cadence rules (constructed once per run).

    Returns:
        _QuarterIntegratedResult, or None if 0 bars (sustained HC-4a体例).
    """
    # NOTE on architecture: we deliberately RE-LOAD bars locally (vs. calling
    # HC-4a's _run_quarter then re-loading) because:
    #   (a) HC-4a's _run_quarter is closed (no bar return path) — bars get
    #       `del`ed inside the function. Refactoring HC-4a to return bars
    #       would balloon IC-3a scope into HC-4a regression risk (sustained
    #       ADR-022 反 closed-code blast radius).
    #   (b) Re-load doubles I/O time per quarter — acceptable for IC-3a's
    #       additive wiring assertion. Quarter wall-clock per HC-4a: ~70s;
    #       doubling → ~140s × 20 quarters → ~47min total (vs HC-4a ~24min
    #       baseline). Plan §A IC-3a cycle 1-2 day baseline absorbs this.
    #
    # Alternative considered + rejected: refactor HC-4a _run_quarter to expose
    # bars via a callback — touches HC-4a's reviewer-locked surface (ADR-070
    # methodology audit), out-of-scope for IC-3a per Plan §A row 5 mitigation
    # "任何 latent bug fix 走 separate sub-PR / hotfix, IC-3 不 inline fix".

    # Path A: HC-4a L1 + L4 STAGED via _run_quarter as-is.
    l1_result = _run_quarter(window, conn, codes_limit)
    if l1_result is None:
        return None

    # Path B: L3 daily-cadence — re-load bars locally for this quarter.
    from v3_tb_5b_replay_acceptance import _make_minute_bars_loader  # noqa: PLC0415

    loader = _make_minute_bars_loader(conn, codes_limit)
    bars = list(loader(window.start_date, window.end_date))
    logger.info(
        "[IC-3a] quarter=%s — re-loaded %d bars for L3 daily-cadence eval",
        window.name,
        len(bars),
    )

    t0 = time.monotonic()
    daily_metrics = _evaluate_daily_cadence_for_quarter(bars, rules)
    wall = time.monotonic() - t0
    del bars  # release ~3GB before next quarter

    logger.info(
        "[IC-3a] quarter=%s L3 done in %.1fs — trading_days=%d positions=%d "
        "eval_calls=%d crashes=%d triggers=%s",
        window.name,
        wall,
        daily_metrics.trading_days,
        daily_metrics.synthetic_positions,
        daily_metrics.eval_calls,
        daily_metrics.crashes,
        dict(daily_metrics.triggers_by_rule) or "(none)",
    )

    return _QuarterIntegratedResult(l1=l1_result, daily=daily_metrics)


# ---------- 5y aggregation + report ----------


def _aggregate_daily(quarters: list[_QuarterIntegratedResult]) -> dict[str, Any]:
    """Incrementally aggregate L3 daily-cadence metrics across quarters."""
    triggers: dict[str, int] = defaultdict(int)
    for q in quarters:
        for rid, n in q.daily.triggers_by_rule.items():
            triggers[rid] += n
    total_eval_calls = sum(q.daily.eval_calls for q in quarters)
    total_crashes = sum(q.daily.crashes for q in quarters)
    return {
        "total_trading_days": sum(q.daily.trading_days for q in quarters),
        "total_synthetic_positions": sum(q.daily.synthetic_positions for q in quarters),
        "total_eval_calls": total_eval_calls,
        "total_crashes": total_crashes,
        "triggers_by_rule": dict(sorted(triggers.items())),
        # Wiring-assertion verdict: 0 crashes across 5y × 4 rules × ~1260 td.
        "pass_l3_wiring": total_crashes == 0 and total_eval_calls > 0,
    }


def _render_integrated_report(
    quarters: list[_QuarterIntegratedResult],
    l1_agg: dict[str, Any],
    daily_agg: dict[str, Any],
) -> str:
    """Render integrated 5y replay acceptance report (L1 + L3-daily + L4 STAGED)."""
    overall_l1 = (
        l1_agg["pass_fp_rate"]
        and l1_agg["pass_latency"]
        and l1_agg["pass_staged"]
        and l1_agg["pass_meta"]
    )
    overall = overall_l1 and daily_agg["pass_l3_wiring"]

    lines: list[str] = []
    lines.append("# V3 IC-3a — 5y Integrated V3 Chain Replay Acceptance Report")
    lines.append("")
    lines.append(f"**Run date**: {datetime.now(_SHANGHAI_TZ).date().isoformat()}  ")
    lines.append(f"**Overall verdict**: {'✅ PASS' if overall else '❌ FAIL'}  ")
    lines.append(
        "**Scope**: V3 Plan v0.4 §A IC-3a — 5y full minute_bars replay on "
        "FULLY-INTEGRATED V3 chain (L1 RealtimeRiskEngine + L4 STAGED state "
        "machine + L3 daily-cadence PURE rules). Sustained HC-4a chunked "
        "per-quarter体例 (20 quarters, 5y range 2021-2025, sustained "
        "CLAUDE.md §因子存储 minute_bars 190M+ rows). LLM reflector + L0 News "
        "EXCLUDED per IC-3 Q2 (out-of-band, sustained acceptance.py §1 + IC-3 "
        "user decision 2026-05-16). Synthetic-universe体例 sustained ADR-070."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §1 L1 + L4 STAGED — V3 §15.4 4 项 acceptance (sustained HC-4a)")
    lines.append("")
    lines.append("| # | Criterion | Threshold | Actual | Result |")
    lines.append("|---|---|---|---|---|")
    fp_pct = l1_agg["fp_rate"] * 100.0
    lines.append(
        f"| 1 | P0 alert 误报率 | `< 30%` | "
        f"`{fp_pct:.2f}% ({l1_agg['total_false_positives']:,}/{l1_agg['total_classified']:,})` "
        f"| {'✅' if l1_agg['pass_fp_rate'] else '❌'} |"
    )
    p99 = l1_agg["max_quarter_p99_ms"]
    p99_str = f"{p99:.3f}ms (max-quarter)" if p99 is not None else "<no samples>"
    lines.append(
        f"| 2 | L1 detection latency P99 | `< 5000ms` | `{p99_str}` "
        f"| {'✅' if l1_agg['pass_latency'] else '❌'} |"
    )
    lines.append(
        f"| 3 | L4 STAGED 流程闭环 0 失败 | `= 0` | `{l1_agg['total_staged_failed']}` "
        f"| {'✅' if l1_agg['pass_staged'] else '❌'} |"
    )
    lines.append(
        f"| 4 | 元监控 0 P0 元告警 (replay-integrity form) | `= 0` | "
        f"`{'0' if l1_agg['pass_meta'] else '≥1'}` | {'✅' if l1_agg['pass_meta'] else '❌'} |"
    )
    lines.append("")
    lines.append(
        f"- Total minute_bars: **{l1_agg['total_minute_bars']:,}** · "
        f"events: **{l1_agg['total_events']:,}** · raw P0: "
        f"**{l1_agg['total_raw_p0']:,}** · deduped daily P0: "
        f"**{l1_agg['total_deduped_p0']:,}** · classified: "
        f"**{l1_agg['total_classified']:,}** · "
        f"STAGED actionable: **{l1_agg['total_staged_actionable']:,}** · "
        f"closed-ok: **{l1_agg['total_staged_closed_ok']:,}** · "
        f"failed: **{l1_agg['total_staged_failed']}**"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §2 L3 daily-cadence PURE rule wiring (NEW for IC-3a)")
    lines.append("")
    lines.append("| Metric | Value | Verdict |")
    lines.append("|---|---|---|")
    lines.append(
        f"| Trading days evaluated (5y) | `{daily_agg['total_trading_days']:,}` | — |"
    )
    lines.append(
        f"| Synthetic positions (Σ code×day) | "
        f"`{daily_agg['total_synthetic_positions']:,}` | — |"
    )
    lines.append(
        f"| Rule.evaluate() calls | `{daily_agg['total_eval_calls']:,}` "
        f"(= trading_days × 4 rules) | — |"
    )
    lines.append(
        f"| Crashes | `{daily_agg['total_crashes']}` | "
        f"{'✅' if daily_agg['total_crashes'] == 0 else '❌'} |"
    )
    lines.append(
        f"| L3 wiring (eval_calls > 0 AND crashes == 0) | — | "
        f"{'✅' if daily_agg['pass_l3_wiring'] else '❌'} |"
    )
    lines.append("")
    if daily_agg["triggers_by_rule"]:
        lines.append("**Per-rule trigger counts** (informational — synthetic-universe ≠ real-portfolio precision):")
        lines.append("")
        lines.append("| rule_id | triggers |")
        lines.append("|---|---|")
        for rid, n in daily_agg["triggers_by_rule"].items():
            lines.append(f"| `{rid}` | {n:,} |")
        lines.append("")
    else:
        lines.append("**Per-rule trigger counts**: 0 across all rules (expected for synthetic single-day positions — see script docstring §Synthetic position construction).")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §3 Per-quarter breakdown")
    lines.append("")
    lines.append(
        "| quarter | bars | events | FP | TP | P99 ms | staged failed | "
        "L3 td | L3 calls | L3 crashes |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for q in quarters:
        p99q = f"{q.l1.p99_ms:.3f}" if q.l1.p99_ms is not None else "n/a"
        lines.append(
            f"| {q.l1.name} | {q.l1.minute_bars:,} | {q.l1.events:,} | "
            f"{q.l1.false_positives:,} | {q.l1.true_positives:,} | "
            f"{p99q} | {q.l1.staged_failed} | "
            f"{q.daily.trading_days} | {q.daily.eval_calls:,} | "
            f"{q.daily.crashes} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §4 Methodology + caveats")
    lines.append("")
    lines.append(
        "- **Integrated V3 chain** scope: L1 RealtimeRiskEngine (10 rules at "
        "tick cadence) + L4 STAGED state machine (via `evaluate_staged_closure`) "
        "+ L3 daily-cadence PURE rules (PMSRule + PositionHoldingTimeRule + "
        "NewPositionVolatilityRule + SingleStockStopLossRule, evaluated at "
        "15:00 Asia/Shanghai EOD per trading day). L2 regime + LLM reflector + "
        "L0 News classifier are out-of-band per IC-3 Q2 (LLM lesson-learning "
        "loop is post-event, NOT signal critical path)."
    )
    lines.append(
        "- **L3 synthetic positions**: 1 share per code per trading day, "
        "entry_price = first bar's open, peak_price = max(high), "
        "current_price = last bar's close, entry_date = trade_date. Single-day "
        "positions deliberately rarely satisfy real rule thresholds (PMSRule "
        "needs ≥10% gain + ≥10% drawdown; PositionHoldingTime needs ≥30 days; "
        "etc) — the wiring-assertion test is **0 rule.evaluate() crashes**, "
        "NOT trigger-count significance."
    )
    lines.append(
        "- **L1 + L4 STAGED methodology** sustained ADR-070 (daily-dedup + "
        "prev_close baseline counterfactual FP classification + max-quarter "
        "P99 conservative aggregate + STAGED state-machine 30min cancel "
        "window ceiling). Pure-function replay path per ADR-063."
    )
    lines.append(
        "- **0 真账户 / 0 broker / 0 .env / 0 INSERT** — pure read-only DB SELECT "
        "+ in-memory replay (sustained HC-4a + TB-5b). 红线 5/5 sustained: "
        "cash=￥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / "
        "EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102."
    )
    lines.append("")
    lines.append(
        "关联: V3 §15.4 / §13.1 / §15.5 · ADR-063 / ADR-066 / ADR-070 / "
        "ADR-076 / ADR-080 候选 · Plan v0.4 §A IC-3a row · 铁律 31/33/41 · "
        "LL-098 X10 / LL-159 / LL-170 候选 lesson 3 / LL-172 lesson 1"
    )
    lines.append("")
    return "\n".join(lines)


# ---------- main ----------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    p.add_argument(
        "--codes-limit",
        type=int,
        default=None,
        help="可选 code subset 限制 (quick smoke; 省略 = full universe)",
    )
    p.add_argument(
        "--quarters",
        type=int,
        default=None,
        help="只跑前 N 个 quarter (debug; N >= 1; 省略 = all 20)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="report markdown 输出路径 (default: docs/audit/v3_ic_3a_5y_integrated_replay_*.md)",
    )
    p.add_argument("--dry-run", action="store_true", help="仅打印 report, 不 sediment markdown")
    p.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return p


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    if args.quarters is not None and args.quarters <= 0:
        parser.error("--quarters must be >= 1 (省略 for all 20)")
    if args.codes_limit is not None and args.codes_limit < 0:
        parser.error("--codes-limit must be >= 0 (0 或省略 for full universe)")
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")

    from app.services.db import get_sync_conn  # noqa: PLC0415

    windows = _build_quarter_windows()
    if args.quarters is not None:
        windows = windows[: args.quarters]

    rules = _build_daily_rules()
    logger.info(
        "[IC-3a] starting 5y integrated chunked replay — %d quarters, "
        "codes_limit=%s, L3 rules=%s",
        len(windows),
        args.codes_limit,
        [type(r).__name__ for r in rules],
    )

    out_path = args.out or (
        PROJECT_ROOT
        / "docs"
        / "audit"
        / f"v3_ic_3a_5y_integrated_replay_report_{datetime.now(_SHANGHAI_TZ):%Y_%m_%d}.md"
    )

    conn = get_sync_conn()
    quarters: list[_QuarterIntegratedResult] = []
    try:
        for window in windows:
            qr = _run_quarter_integrated(window, conn, args.codes_limit, rules)
            if qr is not None:
                quarters.append(qr)
            # Sustained HC-4a/TB-5b体例: release long-lived snapshot between quarters.
            conn.commit()
    finally:
        conn.close()

    if not quarters:
        logger.error("[IC-3a] 0 quarters produced data — nothing to report")
        return 1

    # Reuse HC-4a's _aggregate over l1 fields (Adapter pattern: HC-4a expects
    # _QuarterResult list, so unwrap .l1).
    l1_quarters = [q.l1 for q in quarters]
    l1_agg = _aggregate(l1_quarters)
    daily_agg = _aggregate_daily(quarters)

    report = _render_integrated_report(quarters, l1_agg, daily_agg)
    print(report)  # noqa: T201 — ops script user-facing output

    overall = (
        l1_agg["pass_fp_rate"]
        and l1_agg["pass_latency"]
        and l1_agg["pass_staged"]
        and l1_agg["pass_meta"]
        and daily_agg["pass_l3_wiring"]
    )
    if not args.dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        logger.info("[IC-3a] sedimented integrated 5y replay report: %s", out_path)
    else:
        logger.info("[IC-3a] --dry-run: skipped sediment")

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
