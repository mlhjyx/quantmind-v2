"""Unit tests for verify_report — V3 §15.4 paper-mode 5d acceptance (S10).

覆盖:
  - generate_verify_report: all 4 items computed, all_pass aggregate
  - Window math: 5d default, missing day detection
  - Item 1 (P0 误报率 < 30%): pass / fail / divide-by-zero
  - Item 2 (L1 latency P99 < 5s): pass / fail / no data
  - Item 3 (STAGED FAILED = 0): pass / fail
  - Item 4 (元告警 P0 = 0): pass / fail
  - AcceptanceReport.to_markdown: shape contains all 4 items
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

from backend.qm_platform.risk.metrics.verify_report import (
    AcceptanceReport,
    generate_verify_report,
)

# ── Mock conn helper ──


class _MockConn:
    """Mock that returns staged rows for risk_metrics_daily + scalar for STAGED FAILED count."""

    def __init__(
        self,
        *,
        daily_rows: list[dict[str, Any]] | None = None,
        staged_failed: int = 0,
    ) -> None:
        self._daily_rows = daily_rows or []
        self._staged_failed = staged_failed
        self.rollback_count = 0

    def cursor(self) -> MagicMock:
        cur = MagicMock()
        column_names = [
            "date",
            "alerts_p0_count",
            "alerts_p1_count",
            "alerts_p2_count",
            "detection_latency_p99_ms",
            "llm_cost_total",
        ]
        desc_items = [type("Col", (), {"name": n})() for n in column_names]

        def execute(sql: str, params: tuple) -> None:  # noqa: ARG001
            sql_upper = sql.strip().upper()
            if "FROM RISK_METRICS_DAILY" in sql_upper:
                cur.description = desc_items
                # Build row tuples matching column order
                rows = [tuple(r.get(c) for c in column_names) for r in self._daily_rows]
                cur.fetchall = MagicMock(return_value=rows)
            elif "FROM EXECUTION_PLANS" in sql_upper:
                cur.fetchone = MagicMock(return_value=(self._staged_failed,))

        cur.execute = MagicMock(side_effect=execute)
        cur.close = MagicMock()
        return cur

    def rollback(self) -> None:
        self.rollback_count += 1


def _day(y: int, m: int, d: int) -> date:
    return date(y, m, d)


# ── Happy path: all 4 acceptance items pass ──


class TestAcceptancePass:
    def test_all_4_items_pass(self):
        """5d clean run: low P0, low latency, 0 STAGED failed, 0 元告警."""
        # 5d window, each day P0=10 (50 total), latency 2500ms, all good
        daily_rows = [
            {
                "date": _day(2026, 5, 9 + i),
                "alerts_p0_count": 10,
                "alerts_p1_count": 20,
                "alerts_p2_count": 50,
                "detection_latency_p99_ms": 2500,
                "llm_cost_total": 1.20,
            }
            for i in range(5)
        ]
        conn = _MockConn(daily_rows=daily_rows, staged_failed=0)
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=10,  # 10 / 50 = 20%, < 30%
            meta_alert_p0_count=0,
        )
        assert report.all_pass is True
        assert len(report.items) == 4
        # Per-item pass
        assert all(i.pass_ for i in report.items)


# ── Window detection ──


class TestWindow:
    def test_missing_day_recorded(self):
        """3 of 5 days populated → 2 missing days surfaced."""
        # Days 9, 10, 13 populated; 11, 12 missing
        daily_rows = [
            {
                "date": _day(2026, 5, d),
                "alerts_p0_count": 10,
                "alerts_p1_count": 0,
                "alerts_p2_count": 0,
                "detection_latency_p99_ms": 2500,
                "llm_cost_total": 1.0,
            }
            for d in [9, 10, 13]
        ]
        conn = _MockConn(daily_rows=daily_rows)
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        assert report.missing_days == [_day(2026, 5, 11), _day(2026, 5, 12)]
        # all_pass is False when missing days present
        assert report.all_pass is False

    def test_window_5d_default(self):
        conn = _MockConn(daily_rows=[])
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        assert report.days_in_window == 5
        assert report.window_start == _day(2026, 5, 9)
        assert report.window_end == _day(2026, 5, 13)

    def test_window_custom_days(self):
        conn = _MockConn(daily_rows=[])
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            window_days=3,
            p0_false_positive_count=0,
        )
        assert report.days_in_window == 3
        assert report.window_start == _day(2026, 5, 11)


# ── Item 1: P0 误报率 ──


class TestItem1FalsePositiveRate:
    def test_fp_rate_above_30pct_fails(self):
        daily_rows = [
            {
                "date": _day(2026, 5, 9 + i),
                "alerts_p0_count": 10,
                "alerts_p1_count": 0,
                "alerts_p2_count": 0,
                "detection_latency_p99_ms": 2500,
                "llm_cost_total": 0.0,
            }
            for i in range(5)
        ]
        conn = _MockConn(daily_rows=daily_rows)
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=20,  # 20 / 50 = 40%, > 30%
        )
        fp_item = report.items[0]
        assert fp_item.pass_ is False
        assert "40.00%" in fp_item.actual

    def test_fp_rate_zero_p0_returns_0_pct(self):
        """0 P0 alerts in window → 0% rate (passes vacuously, but suspicious)."""
        conn = _MockConn(daily_rows=[])
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        fp_item = report.items[0]
        # 0 P0 alerts → 0% rate, passes the <30% threshold
        assert fp_item.pass_ is True
        assert "0/0" in fp_item.actual


# ── Item 2: L1 latency P99 ──


class TestItem2Latency:
    def test_latency_above_5s_fails(self):
        daily_rows = [
            {
                "date": _day(2026, 5, 9 + i),
                "alerts_p0_count": 10,
                "alerts_p1_count": 0,
                "alerts_p2_count": 0,
                "detection_latency_p99_ms": 6000 if i == 2 else 2500,
                "llm_cost_total": 0.0,
            }
            for i in range(5)
        ]
        conn = _MockConn(daily_rows=daily_rows)
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        latency_item = report.items[1]
        assert latency_item.pass_ is False
        assert "6000ms" in latency_item.actual

    def test_no_latency_data_fails(self):
        """All days have null detection_latency_p99_ms → fails with informative msg."""
        daily_rows = [
            {
                "date": _day(2026, 5, 9 + i),
                "alerts_p0_count": 10,
                "alerts_p1_count": 0,
                "alerts_p2_count": 0,
                "detection_latency_p99_ms": None,
                "llm_cost_total": 0.0,
            }
            for i in range(5)
        ]
        conn = _MockConn(daily_rows=daily_rows)
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        latency_item = report.items[1]
        assert latency_item.pass_ is False
        assert "<no L1 data>" in latency_item.actual


# ── Item 3: STAGED FAILED ──


class TestItem3StagedFailed:
    def test_staged_failed_zero_passes(self):
        conn = _MockConn(staged_failed=0)
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        staged_item = report.items[2]
        assert staged_item.pass_ is True
        assert staged_item.actual == "0"

    def test_staged_failed_nonzero_fails(self):
        conn = _MockConn(staged_failed=2)
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        staged_item = report.items[2]
        assert staged_item.pass_ is False
        assert staged_item.actual == "2"


# ── Item 4: 元告警 ──


class TestItem4MetaAlert:
    def test_zero_meta_alert_passes(self):
        conn = _MockConn()
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
            meta_alert_p0_count=0,
        )
        meta_item = report.items[3]
        assert meta_item.pass_ is True

    def test_nonzero_meta_alert_fails(self):
        conn = _MockConn()
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
            meta_alert_p0_count=3,
        )
        meta_item = report.items[3]
        assert meta_item.pass_ is False
        assert meta_item.actual == "3"


# ── Markdown rendering ──


class TestMarkdown:
    def test_markdown_contains_all_4_items_and_verdict(self):
        conn = _MockConn(daily_rows=[], staged_failed=0)
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        md = report.to_markdown()
        assert "V3 §15.4 Paper-Mode 5d Verify Report" in md
        assert "Overall verdict" in md
        assert "P0 alert 误报率" in md
        assert "L1 detection latency P99" in md
        assert "L4 STAGED 流程闭环 0 失败" in md
        assert "元监控 0 P0 元告警" in md

    def test_markdown_missing_days_surfaced(self):
        # 0 rows → all 5 days missing
        conn = _MockConn(daily_rows=[])
        report = generate_verify_report(
            conn,
            window_end=_day(2026, 5, 13),
            p0_false_positive_count=0,
        )
        md = report.to_markdown()
        assert "Missing days in window" in md


# ── AcceptanceReport.all_pass aggregate ──


class TestAllPass:
    def test_all_pass_true_when_all_items_pass_and_no_missing(self):
        report = AcceptanceReport(
            window_start=_day(2026, 5, 9),
            window_end=_day(2026, 5, 13),
            days_in_window=5,
        )
        from backend.qm_platform.risk.metrics.verify_report import AcceptanceItem

        report.items = [
            AcceptanceItem(name=f"item{i}", pass_=True, threshold="x", actual="y") for i in range(4)
        ]
        assert report.all_pass is True

    def test_all_pass_false_when_missing_days(self):
        report = AcceptanceReport(
            window_start=_day(2026, 5, 9),
            window_end=_day(2026, 5, 13),
            days_in_window=5,
            missing_days=[_day(2026, 5, 11)],
        )
        from backend.qm_platform.risk.metrics.verify_report import AcceptanceItem

        report.items = [
            AcceptanceItem(name=f"item{i}", pass_=True, threshold="x", actual="y") for i in range(4)
        ]
        assert report.all_pass is False

    def test_all_pass_false_when_any_item_fails(self):
        report = AcceptanceReport(
            window_start=_day(2026, 5, 9),
            window_end=_day(2026, 5, 13),
            days_in_window=5,
        )
        from backend.qm_platform.risk.metrics.verify_report import AcceptanceItem

        report.items = [
            AcceptanceItem(name=f"item{i}", pass_=(i != 2), threshold="x", actual="y")
            for i in range(4)
        ]
        assert report.all_pass is False

    def test_all_pass_false_when_no_items(self):
        report = AcceptanceReport(
            window_start=_day(2026, 5, 9),
            window_end=_day(2026, 5, 13),
            days_in_window=5,
        )
        assert report.all_pass is False
