"""V3 Tier B Replay infrastructure (TB-1b sediment, Plan v0.2 §A TB-1 row).

Modules:
- `runner`: ReplayRunner — orchestrates minute_bars window replay through
  RiskBacktestAdapter.evaluate_at, collects events + counterfactual summary.
- `counterfactual`: counterfactual analysis helpers (V3 §15.5 sim-to-real gap).

Architecture (α — sustained user ack 2026-05-13):
ReplayRunner uses RiskBacktestAdapter as both injection target (broker /
notifier / price reader stubs) AND evaluator (evaluate_at). Production parity
maximized — replay invokes RealtimeRiskEngine same path as production.

V3 §15.5 sim-to-real gap audit: counterfactual analysis output sediment to
`docs/risk_reflections/replay/` per V3 §8.2 dir 体例.

关联:
- V3 §11.4 (RiskBacktestAdapter pure function)
- V3 §15.5 (历史回放 sim-to-real gap)
- ADR-029 (10 RealtimeRiskRule)
- ADR-064 (Plan v0.2 5 决议 lock — D3=b 2 关键窗口 sustained)
- ADR-066 候选 (TB-1 closure sediment, 留 TB-1c)
- LL-159 (4-step preflight SOP)
"""

from .counterfactual import (
    EventSummary,
    summarize_events,
)
from .runner import ReplayRunner, ReplayWindow

__all__ = [
    "EventSummary",
    "ReplayRunner",
    "ReplayWindow",
    "summarize_events",
]
