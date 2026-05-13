"""Counterfactual analysis helpers — V3 §15.5 sim-to-real gap audit (TB-1b sediment).

EventSummary + summarize_events: aggregate RuleResult list by rule_id / code /
severity. Used by ReplayRunner output for `docs/risk_reflections/replay/`
sediment per V3 §8.2 体例.

关联:
- V3 §15.5 (历史回放 sim-to-real gap counterfactual)
- V3 §8.2 (reflection dir 体例)
- ADR-064 D3=b (2 关键窗口 sustained)
- LL-159 (4-step preflight SOP — natural production behavior post-check)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ..interface import RuleResult


@dataclass(frozen=True)
class EventSummary:
    """Aggregate summary of RuleResult events from a replay window.

    Args:
      total_events: total RuleResult count.
      by_rule_id: per-rule_id count (most common first).
      by_code: per-code count (top 20 by frequency).
      unique_codes: distinct code count.
      unique_rule_ids: distinct rule_id count.
      window_start: replay window start timestamp.
      window_end: replay window end timestamp.
    """

    total_events: int
    by_rule_id: dict[str, int] = field(default_factory=dict)
    by_code: dict[str, int] = field(default_factory=dict)
    unique_codes: int = 0
    unique_rule_ids: int = 0
    window_start: datetime | None = None
    window_end: datetime | None = None

    def to_markdown(self) -> str:
        """Render summary as markdown for reflection dir sediment."""
        lines = [
            "# Replay Window Event Summary",
            "",
            f"- Window: {self.window_start} → {self.window_end}",
            f"- Total events: {self.total_events}",
            f"- Unique codes: {self.unique_codes}",
            f"- Unique rule_ids: {self.unique_rule_ids}",
            "",
            "## Events by rule_id",
            "",
        ]
        for rule_id, count in self.by_rule_id.items():
            lines.append(f"- `{rule_id}`: {count}")
        lines.extend(
            [
                "",
                "## Top events by code (top 20)",
                "",
            ]
        )
        top_codes = sorted(self.by_code.items(), key=lambda x: -x[1])[:20]
        for code, count in top_codes:
            lines.append(f"- `{code}`: {count}")
        return "\n".join(lines) + "\n"


def summarize_events(
    events: list[RuleResult],
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    top_codes_limit: int = 20,
) -> EventSummary:
    """Aggregate RuleResult events into EventSummary.

    Args:
        events: list of RuleResult from replay window.
        window_start: replay window start (for summary metadata).
        window_end: replay window end.
        top_codes_limit: include top N codes by frequency (default 20).

    Returns:
        EventSummary with by_rule_id / by_code / unique counts.
    """
    if not events:
        return EventSummary(
            total_events=0,
            window_start=window_start,
            window_end=window_end,
        )

    rule_counter: Counter[str] = Counter()
    code_counter: Counter[str] = Counter()
    for e in events:
        rule_counter[e.rule_id] += 1
        code_counter[e.code] += 1

    # by_rule_id: full distribution
    by_rule_id = dict(rule_counter.most_common())
    # by_code: top N most frequent
    by_code = dict(code_counter.most_common(top_codes_limit))

    return EventSummary(
        total_events=len(events),
        by_rule_id=by_rule_id,
        by_code=by_code,
        unique_codes=len(code_counter),
        unique_rule_ids=len(rule_counter),
        window_start=window_start,
        window_end=window_end,
    )
