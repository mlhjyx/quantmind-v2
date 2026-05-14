"""Unit tests for the PURE replay-acceptance evaluator (TB-5b).

Covers `qm_platform.risk.replay.acceptance`:
  - latency_percentile — nearest-rank percentile + empty / validation edges
  - classify_false_positives — counterfactual FP/TP/unclassifiable classification
  - evaluate_staged_closure — real L4ExecutionPlanner state-machine closure check
  - evaluate_replay_acceptance — 4 §15.4 items + 2 §13.1 SLA assembly + all_pass
  - ReplayAcceptanceReport.to_markdown — render smoke

These are PURE unit tests — 0 DB, 0 IO. The DB-wired 2-window run lives in
scripts/v3_tb_5b_replay_acceptance.py and is exercised separately.

关联铁律: 31 (Engine PURE) / 40 (test debt) / 41 (timezone)
关联 V3: §15.4 / §13.1 / §15.5 · ADR-070 (methodology lock)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.qm_platform.risk import RuleResult
from backend.qm_platform.risk.replay.acceptance import (
    AcceptanceItem,
    FalsePositiveClassification,
    ReplayAcceptanceReport,
    StagedClosureResult,
    classify_false_positives,
    evaluate_replay_acceptance,
    evaluate_staged_closure,
    latency_percentile,
)
from backend.qm_platform.risk.replay.runner import ReplayRunResult, ReplayWindow

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_TS = datetime(2026, 4, 29, 10, 0, 0, tzinfo=SHANGHAI_TZ)


def _p0_event(
    code: str, prev_close: float = 100.0, rule_id: str = "limit_down_detection"
) -> RuleResult:
    """A P0 alert RuleResult carrying prev_close (the FP-classification baseline)."""
    return RuleResult(
        rule_id=rule_id,
        code=code,
        shares=0,
        reason=f"{rule_id}: {code}",
        metrics={
            "prev_close": prev_close,
            "current_price": prev_close * 0.90,
            "drop_pct": -0.10,
        },
    )


def _actionable_event(code: str, shares: int = 500, current_price: float = 200.0) -> RuleResult:
    """A TrailingStop-style actionable RuleResult (shares > 0 → STAGED plan)."""
    return RuleResult(
        rule_id="trailing_stop",
        code=code,
        shares=shares,
        reason=f"TrailingStop: {code}",
        metrics={"current_price": current_price},
    )


# ─────────────────────────────────────────────────────────────
# latency_percentile
# ─────────────────────────────────────────────────────────────


class TestLatencyPercentile:
    def test_empty_returns_none(self) -> None:
        assert latency_percentile([], 99.0) is None

    def test_single_sample(self) -> None:
        assert latency_percentile([4.2], 99.0) == 4.2

    def test_p99_nearest_rank(self) -> None:
        # 100 samples 1..100 → P99 nearest-rank = ceil(0.99*100)=99 → value 99.
        samples = [float(i) for i in range(1, 101)]
        assert latency_percentile(samples, 99.0) == 99.0

    def test_p50_median_ish(self) -> None:
        samples = [float(i) for i in range(1, 101)]
        # ceil(0.50*100)=50 → value 50.
        assert latency_percentile(samples, 50.0) == 50.0

    def test_p100_is_max(self) -> None:
        assert latency_percentile([3.0, 1.0, 9.0, 2.0], 100.0) == 9.0

    def test_unsorted_input_handled(self) -> None:
        assert latency_percentile([9.0, 1.0, 5.0], 100.0) == 9.0

    @pytest.mark.parametrize("bad_pct", [0.0, -1.0, 100.1, 200.0])
    def test_invalid_pct_raises(self, bad_pct: float) -> None:
        with pytest.raises(ValueError, match="pct must be in"):
            latency_percentile([1.0, 2.0], bad_pct)


# ─────────────────────────────────────────────────────────────
# classify_false_positives
# ─────────────────────────────────────────────────────────────


class TestClassifyFalsePositives:
    def test_false_positive_when_day_recovers(self) -> None:
        # Day-end close >= prev_close → flagged downside fully reversed → FP.
        events = [(_TS, _p0_event("600519.SH", prev_close=100.0))]
        result = classify_false_positives(events, lambda c, t: 102.0)
        assert result.false_positives == 1
        assert result.true_positives == 0
        assert result.fp_rate == 1.0

    def test_true_positive_when_day_ends_underwater(self) -> None:
        # Day-end close < prev_close → held position underwater → TP (real loss).
        events = [(_TS, _p0_event("600519.SH", prev_close=100.0))]
        result = classify_false_positives(events, lambda c, t: 92.0)
        assert result.true_positives == 1
        assert result.false_positives == 0
        assert result.fp_rate == 0.0

    def test_equal_day_end_price_is_false_positive(self) -> None:
        # day_end == prev_close → recovered to baseline → FP (boundary inclusive).
        events = [(_TS, _p0_event("600519.SH", prev_close=100.0))]
        result = classify_false_positives(events, lambda c, t: 100.0)
        assert result.false_positives == 1

    def test_limit_down_floor_not_auto_false_positive(self) -> None:
        # Regression for the methodology flaw the smoke run exposed: a 跌停 stock
        # sits AT the price floor and physically cannot fall further — a
        # "did it fall more" test would mis-label it a false positive. The
        # prev_close baseline correctly calls a 跌停 stock that ENDS the day
        # still down a TRUE POSITIVE (the held position is really underwater).
        ld = _p0_event("600519.SH", prev_close=100.0, rule_id="limit_down_detection")
        result = classify_false_positives([(_TS, ld)], lambda c, t: 90.0)  # still 跌停
        assert result.true_positives == 1
        assert result.false_positives == 0

    def test_unclassifiable_when_no_day_end_price(self) -> None:
        events = [(_TS, _p0_event("600519.SH", prev_close=100.0))]
        result = classify_false_positives(events, lambda c, t: None)
        assert result.unclassifiable == 1
        assert result.classified == 0
        assert result.fp_rate == 0.0  # nothing classified → 0.0, not a crash

    def test_unclassifiable_when_no_prev_close(self) -> None:
        # correlated_drop is portfolio-level — no prev_close in metrics.
        cd = RuleResult(
            rule_id="correlated_drop",
            code="600519.SH,601318.SH,600036.SH",
            shares=0,
            reason="CorrelatedDrop",
            metrics={"triggered_count": 3},
        )
        result = classify_false_positives([(_TS, cd)], lambda c, t: 100.0)
        assert result.total_p0 == 1
        assert result.unclassifiable == 1
        assert result.classified == 0

    def test_non_p0_events_ignored(self) -> None:
        # rapid_drop_5min is P1, not P0 — must not be counted.
        p1 = RuleResult(
            rule_id="rapid_drop_5min",
            code="600519.SH",
            shares=0,
            reason="RapidDrop5min",
            metrics={"prev_close": 100.0},
        )
        result = classify_false_positives([(_TS, p1)], lambda c, t: 105.0)
        assert result.total_p0 == 0
        assert result.classified == 0

    def test_mixed_batch_fp_rate(self) -> None:
        # 3 P0 alerts (prev_close 100): 1 recovers (FP), 2 end underwater (TP).
        events = [
            (_TS, _p0_event("A.SH", prev_close=100.0)),  # day-end 103 → FP
            (_TS, _p0_event("B.SH", prev_close=100.0)),  # day-end 88  → TP
            (_TS, _p0_event("C.SH", prev_close=100.0)),  # day-end 91  → TP
        ]
        day_end = {"A.SH": 103.0, "B.SH": 88.0, "C.SH": 91.0}
        result = classify_false_positives(events, lambda c, t: day_end.get(c))
        assert result.total_p0 == 3
        assert result.false_positives == 1
        assert result.true_positives == 2
        assert result.fp_rate == pytest.approx(1 / 3, abs=1e-9)

    def test_gap_down_open_classified_via_prev_close(self) -> None:
        # gap_down_open carries prev_close (NO current_price) — must classify fine.
        gdo = RuleResult(
            rule_id="gap_down_open",
            code="600519.SH",
            shares=0,
            reason="GapDownOpen: 600519.SH 集合竞价跳空",
            metrics={"gap_pct": -0.06, "open_price": 94.0, "prev_close": 100.0},
        )
        # day-end 101 >= prev_close 100 → gap filled → false positive.
        result = classify_false_positives([(_TS, gdo)], lambda c, t: 101.0)
        assert result.total_p0 == 1
        assert result.classified == 1
        assert result.false_positives == 1
        assert result.unclassifiable == 0

    def test_daily_dedup_collapses_per_bar_artifact(self) -> None:
        # gap_down_open re-fires every 5min bar of a gapped-down day (tick cadence
        # artifact). Daily dedup must collapse same (code, rule_id, day) to 1.
        def _gdo() -> RuleResult:
            return RuleResult(
                rule_id="gap_down_open",
                code="600519.SH",
                shares=0,
                reason="GapDownOpen",
                metrics={"prev_close": 100.0},
            )

        # 48 same-day bars all firing gap_down_open for the same code.
        events = [(_TS + timedelta(minutes=5 * i), _gdo()) for i in range(48)]
        result = classify_false_positives(events, lambda c, t: 102.0)
        assert result.raw_total_p0 == 48  # pre-dedup artifact magnitude visible
        assert result.total_p0 == 1  # collapsed to 1 distinct daily alert
        assert result.classified == 1

    def test_daily_dedup_keeps_distinct_days(self) -> None:
        # Same code + rule_id on TWO different days → 2 distinct daily alerts.
        def _gdo() -> RuleResult:
            return RuleResult(
                rule_id="gap_down_open",
                code="600519.SH",
                shares=0,
                reason="GapDownOpen",
                metrics={"prev_close": 100.0},
            )

        events = [(_TS, _gdo()), (_TS + timedelta(days=1), _gdo())]
        result = classify_false_positives(events, lambda c, t: 88.0)
        assert result.raw_total_p0 == 2
        assert result.total_p0 == 2  # distinct days NOT collapsed

    def test_by_rule_breakdown_populated(self) -> None:
        events = [
            (_TS, _p0_event("A.SH", prev_close=100.0, rule_id="limit_down_detection")),
            (_TS, _p0_event("B.SH", prev_close=100.0, rule_id="near_limit_down")),
        ]
        day_end = {"A.SH": 105.0, "B.SH": 80.0}  # A recovers → FP, B underwater → TP
        result = classify_false_positives(events, lambda c, t: day_end.get(c))
        assert result.by_rule["limit_down_detection"] == (1, 0, 0)  # (fp, tp, uncls)
        assert result.by_rule["near_limit_down"] == (0, 1, 0)


# ─────────────────────────────────────────────────────────────
# evaluate_staged_closure
# ─────────────────────────────────────────────────────────────


class TestEvaluateStagedClosure:
    def test_actionable_event_closes_ok(self) -> None:
        events = [(_TS, _actionable_event("600519.SH"))]
        result = evaluate_staged_closure(events)
        assert result.total_actionable == 1
        assert result.plans_generated == 1
        assert result.closed_ok == 1
        assert result.failed == 0
        assert result.deadline_integrity_ok is True

    def test_alert_only_event_not_counted(self) -> None:
        # shares=0 (alert_only) events produce no plan — not "actionable".
        events = [(_TS, _p0_event("600519.SH"))]
        result = evaluate_staged_closure(events)
        assert result.total_actionable == 0
        assert result.plans_generated == 0
        assert result.failed == 0

    def test_multiple_actionable_all_close(self) -> None:
        events = [
            (_TS, _actionable_event("A.SH")),
            (_TS, _actionable_event("B.SH")),
            (_TS, _actionable_event("C.SH")),
        ]
        result = evaluate_staged_closure(events)
        assert result.total_actionable == 3
        assert result.closed_ok == 3
        assert result.failed == 0

    def test_deadline_within_30min_window(self) -> None:
        # A normal-hours STAGED plan must have a cancel window <= 30min.
        events = [(_TS, _actionable_event("600519.SH"))]
        result = evaluate_staged_closure(events)
        assert result.deadline_integrity_ok is True


# ─────────────────────────────────────────────────────────────
# evaluate_replay_acceptance + ReplayAcceptanceReport
# ─────────────────────────────────────────────────────────────


def _replay_result(*, contract_verified: bool = True, events: int = 100) -> ReplayRunResult:
    window = ReplayWindow(
        name="test_window",
        start_date=datetime(2024, 1, 2).date(),
        end_date=datetime(2024, 2, 9).date(),
        description="test",
    )
    return ReplayRunResult(
        window=window,
        events=[_p0_event("X.SH", 90.0) for _ in range(events)],
        summary=None,
        total_timestamps=1344,
        total_minute_bars=3_322_031,
        wall_clock_seconds=29.8,
        pure_function_contract_verified=contract_verified,
    )


class TestEvaluateReplayAcceptance:
    def test_all_pass_when_metrics_clean(self) -> None:
        report = evaluate_replay_acceptance(
            replay_result=_replay_result(contract_verified=True),
            fp_classification=FalsePositiveClassification(
                total_p0=100, false_positives=10, true_positives=90, unclassifiable=0
            ),
            staged_closure=StagedClosureResult(
                total_actionable=15,
                plans_generated=15,
                closed_ok=15,
                failed=0,
                deadline_integrity_ok=True,
            ),
            latencies_ms=[0.5, 1.2, 2.0, 3.1, 4.0],
        )
        assert report.all_pass is True
        assert len(report.items) == 4
        assert len(report.sla_items) == 2
        # fp_rate = 10/100 = 10% < 30% → item 1 passes.
        assert report.items[0].pass_ is True

    def test_fp_rate_over_cap_fails(self) -> None:
        report = evaluate_replay_acceptance(
            replay_result=_replay_result(),
            fp_classification=FalsePositiveClassification(
                total_p0=100, false_positives=40, true_positives=60, unclassifiable=0
            ),
            staged_closure=StagedClosureResult(15, 15, 15, 0, True),
            latencies_ms=[1.0],
        )
        # 40/100 = 40% >= 30% → item 1 fails → overall fail.
        assert report.items[0].pass_ is False
        assert report.all_pass is False

    def test_staged_failed_fails_item3(self) -> None:
        report = evaluate_replay_acceptance(
            replay_result=_replay_result(),
            fp_classification=FalsePositiveClassification(100, 5, 95, 0),
            staged_closure=StagedClosureResult(15, 14, 14, 1, True),
            latencies_ms=[1.0],
        )
        assert report.items[2].pass_ is False
        assert report.all_pass is False

    def test_contract_violation_fails_item4(self) -> None:
        report = evaluate_replay_acceptance(
            replay_result=_replay_result(contract_verified=False),
            fp_classification=FalsePositiveClassification(100, 5, 95, 0),
            staged_closure=StagedClosureResult(15, 15, 15, 0, True),
            latencies_ms=[1.0],
        )
        # item 4 (元监控) = contract_verified AND deadline_integrity → False here.
        assert report.items[3].pass_ is False
        assert report.all_pass is False

    def test_deadline_integrity_violation_fails_item4_and_sla5(self) -> None:
        report = evaluate_replay_acceptance(
            replay_result=_replay_result(contract_verified=True),
            fp_classification=FalsePositiveClassification(100, 5, 95, 0),
            staged_closure=StagedClosureResult(15, 15, 14, 1, False),
            latencies_ms=[1.0],
        )
        assert report.items[3].pass_ is False  # 元监控
        # SLA #5 (STAGED 30min window) keys off deadline_integrity_ok.
        sla_staged = next(s for s in report.sla_items if "STAGED" in s.name)
        assert sla_staged.pass_ is False

    def test_no_latency_samples_fails_item2(self) -> None:
        report = evaluate_replay_acceptance(
            replay_result=_replay_result(),
            fp_classification=FalsePositiveClassification(100, 5, 95, 0),
            staged_closure=StagedClosureResult(15, 15, 15, 0, True),
            latencies_ms=[],
        )
        # No latency data → item 2 + SLA #1 fail (反 silent pass).
        assert report.items[1].pass_ is False
        sla_latency = next(s for s in report.sla_items if "latency" in s.name)
        assert sla_latency.pass_ is False

    def test_latency_over_5s_fails(self) -> None:
        report = evaluate_replay_acceptance(
            replay_result=_replay_result(),
            fp_classification=FalsePositiveClassification(100, 5, 95, 0),
            staged_closure=StagedClosureResult(15, 15, 15, 0, True),
            latencies_ms=[6_000.0],  # 6s > 5s cap
        )
        assert report.items[1].pass_ is False

    def test_to_markdown_renders_verdict_and_tables(self) -> None:
        report = evaluate_replay_acceptance(
            replay_result=_replay_result(contract_verified=True),
            fp_classification=FalsePositiveClassification(100, 10, 90, 5),
            staged_closure=StagedClosureResult(15, 15, 15, 0, True),
            latencies_ms=[1.0, 2.0, 3.0],
        )
        md = report.to_markdown()
        assert "Replay Acceptance" in md
        assert "✅ PASS" in md
        assert "V3 §15.4" in md
        assert "V3 §13.1" in md
        # The 3/5-SLA cross-reference note must be present (Plan §C honesty).
        assert "TB-5a" in md


class TestReplayAcceptanceReportAllPass:
    def test_empty_items_is_not_pass(self) -> None:
        report = ReplayAcceptanceReport(
            window_name="empty",
            total_events=0,
            total_minute_bars=0,
            total_timestamps=0,
        )
        assert report.all_pass is False

    def test_sla_failure_blocks_all_pass(self) -> None:
        report = ReplayAcceptanceReport(
            window_name="w",
            total_events=1,
            total_minute_bars=1,
            total_timestamps=1,
            items=[AcceptanceItem("ok", True, "", "", "")],
            sla_items=[AcceptanceItem("bad sla", False, "", "", "")],
        )
        assert report.all_pass is False
