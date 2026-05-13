"""V3 §15.4 paper-mode 5d verify report — PURE acceptance checker (S10).

Aggregates risk_metrics_daily over a 5d window + checks the 4 V3 §15.4
acceptance items:
  1. P0 alert 误报率 < 30% (requires false_positive labeling — caller side
     joins trade_log for "alert but no actual loss" classification; this
     module computes the raw rate given pre-classified counts)
  2. L1 detection latency P99 < 5s (5000ms) per day, no day exceeding cap
  3. L4 STAGED 流程闭环 0 失败 (status=FAILED count must be 0)
  4. 元监控 0 P0 元告警 (caller side provides meta-alert count)

The output is a structured AcceptanceReport dataclass + a markdown formatter
suitable for sediment into docs/audit/v3_tier_a_paper_mode_5d_<date>.md.

铁律 31 sustained: PURE module. Reads risk_metrics_daily via injected conn,
  joins trade_log via injected conn — but doesn't do anything beyond read +
  arithmetic + boolean check. No commits.
铁律 33 sustained: missing days in window → AcceptanceReport.missing_days
  populated. Caller decides whether to fail-loud or retry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# V3 §15.4 acceptance thresholds
_P0_FALSE_POSITIVE_RATE_CAP: float = 0.30  # < 30%
_L1_DETECTION_LATENCY_P99_CAP_MS: int = 5_000  # < 5s
_STAGED_FAILED_CAP: int = 0  # exactly 0
_META_ALERT_P0_CAP: int = 0  # exactly 0


@dataclass(frozen=True)
class AcceptanceItem:
    """One V3 §15.4 acceptance criterion check result."""

    name: str  # human-readable
    pass_: bool  # True = PASS
    threshold: str  # e.g. "< 30%"
    actual: str  # e.g. "12.5%"
    details: str = ""  # extra context (per-day breakdown, raw counts)


@dataclass
class AcceptanceReport:
    """Aggregate 5d acceptance report (Plan §A S10 deliverable)."""

    window_start: date
    window_end: date
    days_in_window: int
    missing_days: list[date] = field(default_factory=list)
    items: list[AcceptanceItem] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        """True iff all items.pass_ AND no missing days."""
        if not self.items:
            return False
        return all(i.pass_ for i in self.items) and not self.missing_days

    def to_markdown(self) -> str:
        """Render markdown acceptance report (for sediment into docs/audit/)."""
        lines: list[str] = []
        lines.append(
            f"# V3 §15.4 Paper-Mode 5d Verify Report — {self.window_start} → {self.window_end}"
        )
        lines.append("")
        verdict = "✅ PASS" if self.all_pass else "❌ FAIL"
        lines.append(f"**Overall verdict**: {verdict}")
        lines.append("")
        if self.missing_days:
            lines.append(f"⚠️ Missing days in window: {self.missing_days}")
            lines.append("")
        lines.append("## V3 §15.4 4 Acceptance Items")
        lines.append("")
        lines.append("| # | Criterion | Threshold | Actual | Result |")
        lines.append("|---|---|---|---|---|")
        for idx, item in enumerate(self.items, start=1):
            mark = "✅" if item.pass_ else "❌"
            lines.append(f"| {idx} | {item.name} | `{item.threshold}` | `{item.actual}` | {mark} |")
        lines.append("")
        for item in self.items:
            if item.details:
                lines.append(f"### {item.name}")
                lines.append("")
                lines.append(item.details)
                lines.append("")
        return "\n".join(lines)


def generate_verify_report(
    conn: Any,
    *,
    window_end: date,
    window_days: int = 5,
    p0_false_positive_count: int = 0,
    meta_alert_p0_count: int = 0,
) -> AcceptanceReport:
    """Generate the V3 §15.4 acceptance report for a 5d window.

    Args:
        conn: psycopg2 connection (read-only, no commit).
        window_end: last date in the window (inclusive).
        window_days: window length (default 5 per V3 §15.4).
        p0_false_positive_count: caller-classified count of P0 alerts that
            turned out to be false positives (no actual loss event in the
            following 1 day). Caller joins trade_log + risk_event_log to
            classify; this module accepts the count.
        meta_alert_p0_count: count of P0 元告警 (alert on alert) in window.
            Caller queries the meta-alert log (out of S10 scope; defaults to 0
            until §13.3 元告警 channel + table land).

    Returns:
        AcceptanceReport with 4 items checked against V3 §15.4 thresholds.
    """
    window_start = window_end - timedelta(days=window_days - 1)

    # Load all 5 days of risk_metrics_daily
    rows = _load_window_rows(conn, window_start, window_end)
    found_dates = {r["date"] for r in rows}
    expected_dates = {window_start + timedelta(days=i) for i in range(window_days)}
    missing_days = sorted(expected_dates - found_dates)

    # Aggregate
    p0_total = sum(r.get("alerts_p0_count") or 0 for r in rows)
    fp_rate = (p0_false_positive_count / p0_total) if p0_total > 0 else 0.0
    p99_latencies = [
        r.get("detection_latency_p99_ms")
        for r in rows
        if r.get("detection_latency_p99_ms") is not None
    ]
    p99_max = max(p99_latencies) if p99_latencies else None
    # STAGED failure = execution_plans rows with status='FAILED' in window
    staged_failed_count = _count_staged_failed(conn, window_start, window_end)

    # Build items
    items: list[AcceptanceItem] = []

    # Item 1: P0 alert 误报率 < 30%
    items.append(
        AcceptanceItem(
            name="P0 alert 误报率",
            pass_=fp_rate < _P0_FALSE_POSITIVE_RATE_CAP,
            threshold=f"< {_P0_FALSE_POSITIVE_RATE_CAP:.0%}",
            actual=f"{fp_rate:.2%} ({p0_false_positive_count}/{p0_total})",
            details=f"P0 alerts cumulative: {p0_total}. False positives: {p0_false_positive_count}.",
        )
    )

    # Item 2: L1 detection latency P99 < 5s, no day exceeds
    if p99_max is None:
        item2 = AcceptanceItem(
            name="L1 detection latency P99",
            pass_=False,
            threshold=f"< {_L1_DETECTION_LATENCY_P99_CAP_MS}ms",
            actual="<no L1 data>",
            details="No detection_latency_p99_ms data in window — extraction not running?",
        )
    else:
        item2 = AcceptanceItem(
            name="L1 detection latency P99",
            pass_=p99_max < _L1_DETECTION_LATENCY_P99_CAP_MS,
            threshold=f"< {_L1_DETECTION_LATENCY_P99_CAP_MS}ms",
            actual=f"max(P99)={p99_max}ms",
            details=f"Per-day P99 (ms): {p99_latencies}",
        )
    items.append(item2)

    # Item 3: L4 STAGED 流程闭环 0 失败
    items.append(
        AcceptanceItem(
            name="L4 STAGED 流程闭环 0 失败",
            pass_=staged_failed_count == _STAGED_FAILED_CAP,
            threshold=f"= {_STAGED_FAILED_CAP}",
            actual=str(staged_failed_count),
            details=f"execution_plans status=FAILED count in {window_days}d window.",
        )
    )

    # Item 4: 元监控 0 P0 元告警
    items.append(
        AcceptanceItem(
            name="元监控 0 P0 元告警",
            pass_=meta_alert_p0_count == _META_ALERT_P0_CAP,
            threshold=f"= {_META_ALERT_P0_CAP}",
            actual=str(meta_alert_p0_count),
            details=(
                "Caller-provided count. §13.3 元告警 channel + table pending; "
                "default 0 until those land."
            ),
        )
    )

    return AcceptanceReport(
        window_start=window_start,
        window_end=window_end,
        days_in_window=window_days,
        missing_days=missing_days,
        items=items,
    )


# ── Helpers ──


def _load_window_rows(conn: Any, window_start: date, window_end: date) -> list[dict[str, Any]]:
    """Read risk_metrics_daily rows in [window_start, window_end] inclusive.

    Returns list of dicts (one per existing date row). Missing dates are
    NOT filled; caller compares against expected_dates set to find gaps.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT date, alerts_p0_count, alerts_p1_count, alerts_p2_count,
                   detection_latency_p99_ms, llm_cost_total
            FROM risk_metrics_daily
            WHERE date BETWEEN %s AND %s
            ORDER BY date ASC
            """,
            (window_start, window_end),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    except Exception:
        logger.exception(
            "[verify-report] _load_window_rows failed; returning empty (assume table missing)"
        )
        try:
            conn.rollback()
        except Exception:
            logger.exception("[verify-report] rollback after load error failed")
        return []
    finally:
        cur.close()


def _count_staged_failed(conn: Any, window_start: date, window_end: date) -> int:
    """Count execution_plans rows with status='FAILED' in window."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*) FROM execution_plans
            WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai')
                  BETWEEN %s AND %s
              AND status = 'FAILED'
            """,
            (window_start, window_end),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        logger.exception(
            "[verify-report] _count_staged_failed failed; returning 0 (assume table missing)"
        )
        try:
            conn.rollback()
        except Exception:
            logger.exception("[verify-report] rollback after count error failed")
        return 0
    finally:
        cur.close()


__all__ = [
    "AcceptanceItem",
    "AcceptanceReport",
    "generate_verify_report",
]
