"""V3 §15.4 + §13.1 replay-path acceptance evaluator — PURE module (TB-5b).

ADR-063 转 Tier B 真测路径: V3 §15.4 4 项 acceptance + V3 §13.1 SLA 原为 Tier A
S10 paper-mode 5d dry-run 设计, post-ADR-063 transferable 到 RiskBacktestAdapter
历史 minute_bars replay path. This module computes the **replay-path transferable
form** of those acceptance criteria from a `ReplayRunResult` + side-channel data.

What this module does (PURE — 0 IO / 0 DB / 0 broker, 铁律 31):
  - `classify_false_positives` — counterfactual FP classification: a P0 alert is a
    false positive if the stock did NOT continue falling within the forward window
    (V3 §15.5 counterfactual methodology). Forward prices injected via callable.
  - `evaluate_staged_closure` — runs each actionable RuleResult through the real
    L4ExecutionPlanner STAGED state machine, verifies 0 失败 + 30min deadline
    integrity (V3 §13.1 SLA #5).
  - `latency_percentile` — P99 over per-evaluate_at wall-clock samples.
  - `evaluate_replay_acceptance` — assembles the 4 V3 §15.4 items + the 2
    replay-exercisable V3 §13.1 SLA into a `ReplayAcceptanceReport`.

Replay-path scope honesty (Plan v0.2 §C line 203-207 sustained):
  Of the 5 SLA in Plan §C, only 2 are exercisable on a pure-function replay path:
    - L1 detection latency P99 < 5s     → measured here (per-evaluate_at wall-clock)
    - L4 STAGED 30min cancel 窗口        → measured here (pure state-machine check)
  The other 3 have no LLM / News / DingTalk path in a pure-function replay and are
  covered by the TB-5a synthetic scenarios instead:
    - L0 News 6 源 30s timeout          ↗ TB-5a scenario 5 (LLM 服务全挂)
    - LiteLLM API < 3s, fail → Ollama   ↗ TB-5a scenario 5
    - DingTalk push < 10s P99           ↗ TB-5a scenario 6 (DingTalk 不可用)

关联 V3: §15.4 (4 项 acceptance) / §13.1 (SLA) / §13.2-13.3 (元监控/元告警) / §15.5 (counterfactual)
关联铁律: 31 (Engine PURE) / 33 (fail-loud) / 41 (timezone-aware)
关联 ADR: ADR-063 (Tier B 真测路径 transferable) / ADR-064 D3=b (2 关键窗口) /
  ADR-066 (TB-1 replay baseline) / ADR-070 (本 module sediment 锁 methodology + 阈值)
关联 Plan: V3_TIER_B_SPRINT_PLAN_v0.1.md §A TB-5 row + §C + §D
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from math import ceil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ..interface import RuleResult
    from .runner import ReplayRunResult

# ─────────────────────────────────────────────────────────────
# Thresholds — sustained verify_report.py caps (V3 §15.4). ADR-070 locks these.
# ─────────────────────────────────────────────────────────────

_P0_FALSE_POSITIVE_RATE_CAP: float = 0.30  # V3 §15.4 #1: < 30%
_L1_LATENCY_P99_CAP_MS: float = 5_000.0  # V3 §15.4 #2 / §13.1: < 5s
_STAGED_FAILED_CAP: int = 0  # V3 §15.4 #3: exactly 0

# False-positive classification methodology (ADR-070 locked).
#
# Step 1 — DAILY DEDUP: the synthetic-universe replay registers gap_down_open at
#   `tick` cadence, so it re-fires on every 5min bar of a gapped-down day (the
#   rule is semantically pre_market once-daily — a v1-baseline artifact, sustained
#   ADR-066 D3 caveat family). Before classification, P0 events are deduped to the
#   FIRST occurrence per (code, rule_id, trading-day) — this mirrors a real alert
#   dispatcher (no re-spamming the same stuck stock) and removes the per-bar
#   artifact so the rate is a meaningful precision metric.
# Step 2 — COUNTERFACTUAL ("alert but no actual loss", sustained verify_report.py
#   semantics + V3 §15.4 "following 1 day" → here "by alert-day close"): each
#   deduped P0 alert is judged against `prev_close` (the day's baseline, carried
#   in every directional P0 rule's metrics). A FALSE POSITIVE is an alert whose
#   stock's END-OF-DAY close RECOVERED to >= prev_close — the flagged downside
#   fully reversed, a synthetic position entered at prev_close ended NOT
#   underwater. A TRUE POSITIVE ended the day below prev_close (real loss).
#
#   Why `prev_close` and not "did it fall further": floor-hitting rules
#   (limit_down_detection, gap_down_open) flag a stock already AT / NEAR the
#   price floor — it physically cannot fall much further, so a "fell further"
#   test mis-labels nearly every 跌停 alert as a false positive. The
#   prev_close-baseline test asks the operationally-correct question — did the
#   held position end the day underwater — uniformly across all directional
#   P0 rules.
#
#   If `prev_close` is absent (correlated_drop — portfolio-level) OR no day-end
#   close is available, the event is UNCLASSIFIABLE and excluded from the rate
#   denominator (反 silent skew, 铁律 33).

# P0 rule_ids — sustained alert.py `_rule_severity_str` P0 set.
_P0_RULE_IDS: frozenset[str] = frozenset(
    {"limit_down_detection", "near_limit_down", "gap_down_open", "correlated_drop"}
)

# STAGED cancel-window upper bound (V3 §13.1 SLA #5 + ADR-027 §2.2 30min 窗口).
# §13.3 P0 元告警 condition: a PENDING_CONFIRM plan whose cancel window exceeds
# 35min. We check the stricter 30min ceiling (the planner's design ceiling).
_STAGED_CANCEL_WINDOW_CEIL_MINUTES: float = 30.0


# ─────────────────────────────────────────────────────────────
# False-positive classification (V3 §15.4 #1 + §15.5 counterfactual)
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FalsePositiveClassification:
    """Counterfactual FP classification result for a replay window's P0 events.

    Args:
      total_p0: distinct daily P0 alerts AFTER (code, rule_id, day) dedup.
      false_positives: deduped P0 alerts whose stock's day-end close recovered
        to >= prev_close — the flagged downside fully reversed.
      true_positives: deduped P0 alerts whose stock ended the day below
        prev_close — the held position was actually underwater (real loss).
      unclassifiable: deduped P0 alerts with no prev_close in metrics (e.g.
        correlated_drop) OR no day-end close available — excluded from the
        rate denominator.
      raw_total_p0: pre-dedup P0 event count (shows the per-bar artifact
        magnitude — see ADR-066 D3 caveat family).
      by_rule: per-rule_id breakdown {rule_id: (fp, tp, unclassifiable)} over
        the deduped stream — transparency for ADR-070 + reviewer.
    """

    total_p0: int
    false_positives: int
    true_positives: int
    unclassifiable: int
    raw_total_p0: int = 0
    by_rule: dict[str, tuple[int, int, int]] = field(default_factory=dict)

    @property
    def classified(self) -> int:
        """Deduped alerts with prev_close + a day-end close (rate denominator)."""
        return self.false_positives + self.true_positives

    @property
    def fp_rate(self) -> float:
        """False-positive rate over classified events. 0.0 when nothing classified."""
        return (self.false_positives / self.classified) if self.classified > 0 else 0.0


def classify_false_positives(
    timestamped_events: Sequence[tuple[datetime, RuleResult]],
    day_end_price_lookup: Callable[[str, datetime], float | None],
) -> FalsePositiveClassification:
    """Classify P0 alerts as false / true positives via a prev_close counterfactual.

    Methodology (ADR-070 locked — see the comment block above `_P0_RULE_IDS`):
      1. Dedup P0 events to the first occurrence per (code, rule_id, trading-day)
         — removes the gap_down_open per-bar artifact (ADR-066 D3 caveat family).
      2. For each deduped alert, compare `prev_close` (the day's baseline, from
         the event's metrics) to the stock's END-OF-DAY close: day-end close
         >= prev_close → false positive (downside reversed); below → true
         positive (held position ended underwater).

    Args:
        timestamped_events: (alert_ts, RuleResult) pairs from the replay run,
            in ascending timestamp order (post evaluate_at dedup).
        day_end_price_lookup: callable (code, alert_ts) -> the code's end-of-day
            close on alert_ts's trading day, or None if unavailable.

    Returns:
        FalsePositiveClassification with deduped FP / TP / unclassifiable counts,
        the raw (pre-dedup) total, and a per-rule breakdown.
    """
    raw_total_p0 = 0
    # Step 1 — daily dedup. timestamped_events is time-ordered, so the first
    # occurrence seen for a (code, rule_id, day) key is the earliest alert.
    seen_daily: set[tuple[str, str, object]] = set()
    deduped: list[tuple[datetime, RuleResult]] = []
    for alert_ts, event in timestamped_events:
        if event.rule_id not in _P0_RULE_IDS:
            continue
        raw_total_p0 += 1
        key = (event.code, event.rule_id, alert_ts.date())
        if key in seen_daily:
            continue
        seen_daily.add(key)
        deduped.append((alert_ts, event))

    # Step 2 — prev_close counterfactual classification over the deduped stream.
    false_positives = 0
    true_positives = 0
    unclassifiable = 0
    # rule_id -> [fp, tp, unclassifiable]
    by_rule_acc: dict[str, list[int]] = {}

    for alert_ts, event in deduped:
        acc = by_rule_acc.setdefault(event.rule_id, [0, 0, 0])
        prev_close = event.metrics.get("prev_close")
        if prev_close is None or prev_close <= 0:
            # correlated_drop is portfolio-level — no prev_close in metrics.
            unclassifiable += 1
            acc[2] += 1
            continue
        day_end_price = day_end_price_lookup(event.code, alert_ts)
        if day_end_price is None or day_end_price <= 0:
            unclassifiable += 1
            acc[2] += 1
            continue
        if day_end_price >= prev_close:
            # Day-end recovered to/above baseline — flagged downside reversed.
            false_positives += 1
            acc[0] += 1
        else:
            # Ended the day underwater — the alert flagged a real loss.
            true_positives += 1
            acc[1] += 1

    return FalsePositiveClassification(
        total_p0=len(deduped),
        false_positives=false_positives,
        true_positives=true_positives,
        unclassifiable=unclassifiable,
        raw_total_p0=raw_total_p0,
        by_rule={rid: (a[0], a[1], a[2]) for rid, a in by_rule_acc.items()},
    )


# ─────────────────────────────────────────────────────────────
# L4 STAGED closure (V3 §15.4 #3 + §13.1 SLA #5)
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StagedClosureResult:
    """L4 STAGED state-machine closure check over replay actionable events.

    Args:
      total_actionable: RuleResult events with shares > 0 (action would be sell).
      plans_generated: actionable events that produced a non-None ExecutionPlan.
      closed_ok: plans that reached a terminal non-FAILED status via the state
        machine (PENDING_CONFIRM → TIMEOUT_EXECUTED).
      failed: plans that ended FAILED, or failed to generate, or violated the
        30min cancel-window ceiling.
      deadline_integrity_ok: True iff every generated plan's cancel window is
        <= 30min (V3 §13.1 SLA #5 / §13.3 元告警 inverse).
    """

    total_actionable: int
    plans_generated: int
    closed_ok: int
    failed: int
    deadline_integrity_ok: bool


def evaluate_staged_closure(
    timestamped_events: Sequence[tuple[datetime, RuleResult]],
) -> StagedClosureResult:
    """Run actionable replay events through the real L4ExecutionPlanner state machine.

    For each RuleResult with shares > 0: generate a STAGED ExecutionPlan, verify
    its cancel window is <= 30min, then drive the state machine to a terminal
    non-FAILED status (timeout_execute). Counts any generation failure / FAILED
    status / deadline-ceiling violation as `failed`.

    Args:
        timestamped_events: (alert_ts, RuleResult) pairs from the replay run.

    Returns:
        StagedClosureResult with closure + deadline-integrity counts.
    """
    # Lazy import — planner.py is a PURE sibling module (铁律 31), safe to import.
    from ..execution.planner import ExecutionMode, L4ExecutionPlanner, PlanStatus

    planner = L4ExecutionPlanner(staged_enabled=True)
    total_actionable = 0
    plans_generated = 0
    closed_ok = 0
    failed = 0
    deadline_integrity_ok = True

    for alert_ts, event in timestamped_events:
        if event.shares <= 0:
            continue
        total_actionable += 1

        plan = planner.generate_plan(event, mode=ExecutionMode.STAGED, at=alert_ts)
        if plan is None:
            # Actionable event (shares > 0) that produced no plan = closure failure.
            failed += 1
            continue
        plans_generated += 1

        # Deadline integrity: cancel window must be within the 30min ceiling.
        window_minutes = (plan.cancel_deadline - plan.scheduled_at).total_seconds() / 60.0
        if window_minutes > _STAGED_CANCEL_WINDOW_CEIL_MINUTES:
            deadline_integrity_ok = False
            failed += 1
            continue

        # Drive the state machine to a terminal status — the cancel window
        # elapsed with no user decision → timeout_execute (反向决策权 耗尽 → 默认执行).
        terminal = plan.timeout_execute(plan.cancel_deadline)
        if terminal.status == PlanStatus.TIMEOUT_EXECUTED:
            closed_ok += 1
        else:
            failed += 1

    return StagedClosureResult(
        total_actionable=total_actionable,
        plans_generated=plans_generated,
        closed_ok=closed_ok,
        failed=failed,
        deadline_integrity_ok=deadline_integrity_ok,
    )


# ─────────────────────────────────────────────────────────────
# Latency percentile (V3 §15.4 #2 + §13.1 SLA #1)
# ─────────────────────────────────────────────────────────────


def latency_percentile(latencies_ms: Sequence[float], pct: float) -> float | None:
    """Compute the `pct` percentile (e.g. 99.0) over per-evaluate_at latency samples.

    Uses the nearest-rank method on a sorted copy. Returns None for an empty
    sample (反 silent 0.0 — caller distinguishes "no data" from "fast").

    Args:
        latencies_ms: per-evaluate_at wall-clock samples (milliseconds).
        pct: percentile in (0, 100].

    Returns:
        The percentile value in ms, or None if `latencies_ms` is empty.

    Raises:
        ValueError: pct not in (0, 100].
    """
    if not (0.0 < pct <= 100.0):
        raise ValueError(f"pct must be in (0, 100], got {pct}")
    if not latencies_ms:
        return None
    ordered = sorted(latencies_ms)
    # Nearest-rank: rank = ceil(pct/100 * N), 1-indexed.
    rank = ceil(pct / 100.0 * len(ordered))
    rank = max(1, min(rank, len(ordered)))
    return ordered[rank - 1]


# ─────────────────────────────────────────────────────────────
# Acceptance report assembly (V3 §15.4 4 项 + §13.1 SLA)
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AcceptanceItem:
    """One acceptance criterion check result (sustained verify_report.AcceptanceItem)."""

    name: str
    pass_: bool
    threshold: str
    actual: str
    details: str = ""


@dataclass(frozen=True)
class ReplayAcceptanceReport:
    """V3 §15.4 + §13.1 acceptance report for one replay window (TB-5b deliverable).

    Frozen — `evaluate_replay_acceptance` assembles `items` + `sla_items` first
    then constructs the report in one shot (no post-construction mutation).
    """

    window_name: str
    total_events: int
    total_minute_bars: int
    total_timestamps: int
    items: list[AcceptanceItem] = field(default_factory=list)
    sla_items: list[AcceptanceItem] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        """True iff every §15.4 item and every replay-exercisable SLA passed."""
        if not self.items:
            return False
        return all(i.pass_ for i in self.items) and all(s.pass_ for s in self.sla_items)

    def to_markdown(self) -> str:
        """Render the acceptance report as markdown (for docs/audit/ sediment)."""
        lines: list[str] = []
        verdict = "✅ PASS" if self.all_pass else "❌ FAIL"
        lines.append(f"## Replay Acceptance — `{self.window_name}`")
        lines.append("")
        lines.append(f"**Overall verdict**: {verdict}")
        lines.append("")
        lines.append(
            f"- Total events: **{self.total_events:,}** · "
            f"minute_bars: **{self.total_minute_bars:,}** · "
            f"timestamps: **{self.total_timestamps:,}**"
        )
        lines.append("")
        lines.append("### V3 §15.4 — 4 项 acceptance (replay-path transferable)")
        lines.append("")
        lines.append("| # | Criterion | Threshold | Actual | Result |")
        lines.append("|---|---|---|---|---|")
        for idx, item in enumerate(self.items, start=1):
            mark = "✅" if item.pass_ else "❌"
            lines.append(f"| {idx} | {item.name} | `{item.threshold}` | `{item.actual}` | {mark} |")
        lines.append("")
        lines.append("### V3 §13.1 — SLA verify (replay-exercisable subset)")
        lines.append("")
        lines.append("| SLA | Threshold | Actual | Result |")
        lines.append("|---|---|---|---|")
        for item in self.sla_items:
            mark = "✅" if item.pass_ else "❌"
            lines.append(f"| {item.name} | `{item.threshold}` | `{item.actual}` | {mark} |")
        lines.append("")
        lines.append(
            "> 3/5 §13.1 SLA (L0 News 30s / LiteLLM 3s / DingTalk 10s) have no "
            "LLM/News/DingTalk path in a pure-function replay — covered by the "
            "TB-5a synthetic scenarios (scenario 5 + 6) per Plan v0.2 §C line 203-207."
        )
        lines.append("")
        for item in (*self.items, *self.sla_items):
            if item.details:
                lines.append(f"#### {item.name}")
                lines.append("")
                lines.append(item.details)
                lines.append("")
        return "\n".join(lines)


def evaluate_replay_acceptance(
    *,
    replay_result: ReplayRunResult,
    fp_classification: FalsePositiveClassification,
    staged_closure: StagedClosureResult,
    latencies_ms: Sequence[float],
) -> ReplayAcceptanceReport:
    """Assemble the V3 §15.4 4 项 + §13.1 SLA acceptance report for a replay window.

    Args:
        replay_result: ReplayRunResult from ReplayRunner.run_window.
        fp_classification: output of classify_false_positives.
        staged_closure: output of evaluate_staged_closure.
        latencies_ms: per-evaluate_at wall-clock samples (ms).

    Returns:
        ReplayAcceptanceReport with 4 §15.4 items + 2 replay-exercisable SLA items.
    """
    p99 = latency_percentile(latencies_ms, 99.0)

    items: list[AcceptanceItem] = []

    # §15.4 #1 — P0 alert 误报率 < 30%
    by_rule_lines = "; ".join(
        f"{rid}: FP={fp}/TP={tp}/uncls={unc}"
        for rid, (fp, tp, unc) in sorted(fp_classification.by_rule.items())
    )
    items.append(
        AcceptanceItem(
            name="P0 alert 误报率",
            pass_=fp_classification.fp_rate < _P0_FALSE_POSITIVE_RATE_CAP,
            threshold=f"< {_P0_FALSE_POSITIVE_RATE_CAP:.0%}",
            actual=(
                f"{fp_classification.fp_rate:.2%} "
                f"({fp_classification.false_positives}/{fp_classification.classified})"
            ),
            details=(
                f"Counterfactual FP methodology (ADR-070 locked): P0 events deduped "
                f"to first-per-(code, rule_id, day) [removes the gap_down_open "
                f"per-bar artifact], then a deduped alert is a false positive if "
                f"the stock's day-end close recovered to >= prev_close (flagged "
                f"downside fully reversed), true positive if it ended the day "
                f"below prev_close (held position underwater = real loss). "
                f"Raw P0 events (pre-dedup): {fp_classification.raw_total_p0:,}. "
                f"Deduped daily alerts: {fp_classification.total_p0:,}. "
                f"Classified: {fp_classification.classified:,} "
                f"(FP={fp_classification.false_positives:,}, "
                f"TP={fp_classification.true_positives:,}). "
                f"Unclassifiable (no prev_close / no day-end close, incl. "
                f"correlated_drop): {fp_classification.unclassifiable:,}. "
                f"Per-rule: {by_rule_lines or '(none)'}."
            ),
        )
    )

    # §15.4 #2 — L1 detection latency P99 < 5s (replay = per-evaluate_at wall-clock)
    if p99 is None:
        items.append(
            AcceptanceItem(
                name="L1 detection latency P99",
                pass_=False,
                threshold=f"< {_L1_LATENCY_P99_CAP_MS:.0f}ms",
                actual="<no latency samples>",
                details="No per-evaluate_at latency samples collected.",
            )
        )
    else:
        items.append(
            AcceptanceItem(
                name="L1 detection latency P99",
                pass_=p99 < _L1_LATENCY_P99_CAP_MS,
                threshold=f"< {_L1_LATENCY_P99_CAP_MS:.0f}ms",
                actual=f"{p99:.3f}ms",
                details=(
                    "Replay-path proxy: wall-clock of each "
                    "RiskBacktestAdapter.evaluate_at call (one synthetic tick over "
                    "the pure RealtimeRiskEngine). This is a LOWER-BOUND proxy for "
                    "production tick→risk_event_log INSERT latency — it excludes "
                    "I/O (DB INSERT, Redis read, network). ADR-063 §1.5: replay "
                    f"path 等价 transferable. Samples: {len(latencies_ms):,}."
                ),
            )
        )

    # §15.4 #3 — L4 STAGED 流程闭环 0 失败
    items.append(
        AcceptanceItem(
            name="L4 STAGED 流程闭环 0 失败",
            pass_=staged_closure.failed == _STAGED_FAILED_CAP,
            threshold=f"= {_STAGED_FAILED_CAP}",
            actual=str(staged_closure.failed),
            details=(
                f"Each actionable RuleResult (shares > 0) driven through the real "
                f"L4ExecutionPlanner STAGED state machine. "
                f"Actionable events: {staged_closure.total_actionable}. "
                f"Plans generated: {staged_closure.plans_generated}. "
                f"Closed OK (→ TIMEOUT_EXECUTED): {staged_closure.closed_ok}. "
                f"Failed: {staged_closure.failed}."
            ),
        )
    )

    # §15.4 #4 — 元监控 0 P0 元告警 (replay-run integrity form)
    meta_ok = replay_result.pure_function_contract_verified and staged_closure.deadline_integrity_ok
    items.append(
        AcceptanceItem(
            name="元监控 0 P0 元告警",
            pass_=meta_ok,
            threshold="= 0",
            actual="0" if meta_ok else "≥1",
            details=(
                "Replay-run integrity form: a pure-function replay cannot exercise "
                "the live §13.3 P0 元告警 conditions (L1 心跳 / LiteLLM 失败率 / "
                "DingTalk push fail / News 全 timeout — all production-runtime). The "
                "replay-exercisable subset is: pure-function contract held "
                f"(0 broker / 0 alert / 0 INSERT) = "
                f"{replay_result.pure_function_contract_verified}; and STAGED "
                f"cancel-window integrity (no plan > 30min, §13.3 inverse) = "
                f"{staged_closure.deadline_integrity_ok}."
            ),
        )
    )

    # §13.1 SLA — replay-exercisable subset (2/5)
    sla_items: list[AcceptanceItem] = []

    # SLA #1 — L1 detection latency P99 < 5s (same measurement as §15.4 #2)
    sla_items.append(
        AcceptanceItem(
            name="L1 detection latency P99 < 5s",
            pass_=(p99 is not None and p99 < _L1_LATENCY_P99_CAP_MS),
            threshold=f"< {_L1_LATENCY_P99_CAP_MS:.0f}ms",
            actual=("<no samples>" if p99 is None else f"{p99:.3f}ms"),
        )
    )

    # SLA #5 — L4 STAGED 30min cancel 窗口 严格 30min
    sla_items.append(
        AcceptanceItem(
            name="L4 STAGED 30min cancel 窗口",
            pass_=staged_closure.deadline_integrity_ok,
            threshold=f"<= {_STAGED_CANCEL_WINDOW_CEIL_MINUTES:.0f}min",
            actual=(
                "all within window"
                if staged_closure.deadline_integrity_ok
                else "≥1 plan exceeded 30min"
            ),
        )
    )

    return ReplayAcceptanceReport(
        window_name=replay_result.window.name,
        total_events=len(replay_result.events),
        total_minute_bars=replay_result.total_minute_bars,
        total_timestamps=replay_result.total_timestamps,
        items=items,
        sla_items=sla_items,
    )


__all__ = [
    "AcceptanceItem",
    "FalsePositiveClassification",
    "ReplayAcceptanceReport",
    "StagedClosureResult",
    "classify_false_positives",
    "evaluate_replay_acceptance",
    "evaluate_staged_closure",
    "latency_percentile",
]
