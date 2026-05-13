"""BatchedPlanner — V3 §7.2 batched 平仓 PURE engine (S9a).

V3 §7.2 触发: L1 P0 alert (CorrelatedDrop 4+ 股 / Crisis regime / portfolio
intraday < -5%). 不一次性全卖 (流动性冲击), 分 N 批:
  - N = max(3, ceil(持仓股数 × 0.3))
  - batch interval = 5min
  - 每 batch 优先卖 (a) 跌幅大 (b) 流动性差 (c) sentiment 最负
  - 每 batch 后重新评估: 若市场反弹 + alert 清除 → 停止后续 batch (Re-entry 候选)

This module produces N ExecutionPlan dataclasses with batch_index/batch_total/
scheduled_at offsets. Caller persists rows + schedules dispatch (Celery
countdown task per scheduled_at) + re-evaluates between batches.

Layered architecture (CLAUDE.md §3.1):
  - Engine (this file) — PURE function: (trigger, positions, mode, at) → list[ExecutionPlan]
  - Caller — persists batches + Celery dispatch + re-evaluation logic

铁律 31 sustained: 0 DB IO, 0 broker call, 0 network. Caller injects all data.
铁律 33 sustained: fail-loud on invalid input (empty positions / bad N).

设计:
  - Priority ordering: drop_pct DESC, then daily_volume ASC (liquidity), then
    sentiment ASC. Ties broken stably by symbol_id (反 non-determinism).
  - Quantity split: equal across batches with remainder added to early batches.
    e.g. 100 shares / 3 batches → [34, 33, 33].
  - Status routing: STAGED mode → PENDING_CONFIRM (each batch awaits user);
    OFF/AUTO mode → CONFIRMED (each batch dispatches at scheduled_at).
  - Limit price: derived from position.current_price × 0.98 (V3 §7.1 -2%).
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from .planner import ExecutionMode, ExecutionPlan, PlanStatus

logger = logging.getLogger(__name__)

# V3 §7.2 5min batch interval default. Configurable per-call for tests / future tuning.
DEFAULT_BATCH_INTERVAL_MIN: int = 5

# V3 §7.2 batch count formula: N = max(3, ceil(N_positions × 0.3))
_MIN_BATCHES: int = 3
_BATCH_RATIO: float = 0.3

# V3 §7.1 limit price = current_price × 0.98 (-2%)
_LIMIT_PRICE_FACTOR: float = 0.98

# Per-position cancel window: same 30min default as L4ExecutionPlanner (ADR-027 §2.2).
# Each batch has its OWN deadline = scheduled_at + 30min (反 shared deadline crowding
# late batches into too-short user-decision windows).
_DEFAULT_PER_BATCH_DEADLINE_MIN: int = 30


@dataclass(frozen=True)
class BatchedPositionInput:
    """Per-symbol input data needed for batched planning.

    Derived from L1 PositionSource + L2 sentiment + realtime market data.
    Caller assembles this; planner consumes (PURE).
    """

    code: str
    shares: int  # total shares to sell
    current_price: float
    daily_volume: float  # for liquidity ordering (lower = sell first)
    drop_pct: float  # negative for losses (more negative = sell first)
    sentiment_24h: float | None = None  # [-1, +1]; None = unknown


def compute_batch_count(n_positions: int) -> int:
    """V3 §7.2 N = max(3, ceil(N_positions × 0.3)).

    Returns:
        Number of batches. Always ≥ 3. For 1-2 positions, still uses 3 batches
        (each position split into 3 quantity tranches per V3 §7.2 流动性 logic).
    """
    if n_positions <= 0:
        raise ValueError(f"n_positions must be > 0, got {n_positions}")
    return max(_MIN_BATCHES, math.ceil(n_positions * _BATCH_RATIO))


def _priority_key(p: BatchedPositionInput) -> tuple[float, float, float, str]:
    """Stable ordering: (drop_pct ASC, volume ASC, sentiment ASC, code ASC).

    drop_pct most negative first (largest drop sells earliest). Volume low first
    (least liquid sells earliest, easier to avoid impact). Sentiment most
    negative first. Code as tiebreaker for deterministic test fixtures.

    None sentiment treated as 0 (neutral) for ordering purposes.
    """
    sentiment = p.sentiment_24h if p.sentiment_24h is not None else 0.0
    return (p.drop_pct, p.daily_volume, sentiment, p.code)


def _split_qty(total: int, batches: int) -> list[int]:
    """Equal split with remainder added to early batches.

    e.g. (100, 3) → [34, 33, 33]; (10, 3) → [4, 3, 3]; (3, 3) → [1, 1, 1].
    """
    if total < 0:
        raise ValueError(f"total must be ≥ 0, got {total}")
    if batches <= 0:
        raise ValueError(f"batches must be > 0, got {batches}")
    base, remainder = divmod(total, batches)
    return [base + 1 if i < remainder else base for i in range(batches)]


def generate_batched_plans(
    *,
    trigger_event_id: int | None,
    trigger_reason: str,
    positions: list[BatchedPositionInput],
    mode: ExecutionMode,
    at: datetime,
    batch_interval_min: int = DEFAULT_BATCH_INTERVAL_MIN,
    per_batch_deadline_min: int = _DEFAULT_PER_BATCH_DEADLINE_MIN,
    trigger_metrics: dict[str, float] | None = None,
) -> list[ExecutionPlan]:
    """Generate N ExecutionPlan rows for batched 平仓 execution.

    Args:
        trigger_event_id: risk_event_log row that triggered this batched
            sell (caller looks up before calling). May be None for synthetic
            tests or pre-event triggers.
        trigger_reason: human-readable cause (e.g. "CorrelatedDrop 4+ stocks").
        positions: list of BatchedPositionInput (≥ 1). Empty → ValueError.
        mode: ExecutionMode (OFF/STAGED/AUTO). OFF/AUTO → CONFIRMED initial
            status; STAGED → PENDING_CONFIRM (each batch awaits user).
        at: anchor time for batch scheduling. batch_i scheduled_at =
            at + i * batch_interval_min. First batch (i=0) at `at`.
        batch_interval_min: minutes between consecutive batches (default 5).
        per_batch_deadline_min: cancel window per batch (default 30).
        trigger_metrics: optional dict written to each plan's risk_metrics
            (e.g. portfolio_drop_pct, correlated_count).

    Returns:
        List[ExecutionPlan] with N entries, each having batch_index (1..N) +
        batch_total (N) + scheduled_at staggered. Order:
          1. Positions are priority-sorted (see _priority_key).
          2. Each position's qty is split across N batches via _split_qty.
          3. Plans are emitted batch-by-batch, code-by-code within batch.

    Raises:
        ValueError: empty positions / shares ≤ 0 in any position / invalid
            batch_interval_min ≤ 0.
    """
    if not positions:
        raise ValueError("positions must be non-empty")
    if batch_interval_min <= 0:
        raise ValueError(f"batch_interval_min must be > 0, got {batch_interval_min}")
    # Reviewer P2 (code-reviewer): duplicate-code check — splits dict keyed by
    # code; without dedup, second entry would silently overwrite first in dict
    # but both would still appear in sorted_positions, emitting double plans
    # with wrong quantities.
    codes = [p.code for p in positions]
    if len(codes) != len(set(codes)):
        dups = sorted({c for c in codes if codes.count(c) > 1})
        raise ValueError(f"duplicate position codes not allowed: {dups}")
    for p in positions:
        if p.shares <= 0:
            raise ValueError(f"position {p.code} shares must be > 0, got {p.shares}")
        # Reviewer P2 (code-reviewer): current_price > 0 validation. Zero/
        # negative price would yield nonsensical limit_price=0; better to fail
        # fast than emit a 0-price sell order.
        if p.current_price <= 0:
            raise ValueError(
                f"position {p.code} current_price must be > 0, got {p.current_price}"
            )

    n_batches = compute_batch_count(len(positions))
    sorted_positions = sorted(positions, key=_priority_key)

    # Pre-compute per-position split: dict[code, list[qty per batch]]
    splits: dict[str, list[int]] = {
        p.code: _split_qty(p.shares, n_batches) for p in sorted_positions
    }

    initial_status = (
        PlanStatus.PENDING_CONFIRM if mode == ExecutionMode.STAGED else PlanStatus.CONFIRMED
    )
    metrics_template = dict(trigger_metrics) if trigger_metrics else {}

    plans: list[ExecutionPlan] = []
    for batch_idx in range(n_batches):
        scheduled = at + timedelta(minutes=batch_interval_min * batch_idx)
        deadline = scheduled + timedelta(minutes=per_batch_deadline_min)
        for p in sorted_positions:
            qty_this_batch = splits[p.code][batch_idx]
            if qty_this_batch == 0:
                continue  # skip empty tranche (e.g. 1 share / 3 batches → 2 zero batches)
            limit_price = round(p.current_price * _LIMIT_PRICE_FACTOR, 4)
            per_metrics = dict(metrics_template)
            per_metrics["drop_pct"] = p.drop_pct
            per_metrics["daily_volume"] = p.daily_volume
            if p.sentiment_24h is not None:
                per_metrics["sentiment_24h"] = p.sentiment_24h
            per_metrics["batch_qty"] = float(qty_this_batch)

            plans.append(
                ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    mode=mode,
                    symbol_id=p.code,
                    action="BATCH",
                    qty=qty_this_batch,
                    limit_price=limit_price,
                    batch_index=batch_idx + 1,  # 1-based per V3 §7.5 schema
                    batch_total=n_batches,
                    scheduled_at=scheduled,
                    cancel_deadline=deadline,
                    status=initial_status,
                    triggered_by_event_id=trigger_event_id,
                    risk_reason=trigger_reason,
                    risk_metrics=per_metrics,
                )
            )

    logger.info(
        "[batched-planner] generated %d plans across %d batches for %d positions "
        "(mode=%s, reason=%s)",
        len(plans),
        n_batches,
        len(positions),
        mode.value,
        trigger_reason[:50],
    )
    return plans


__all__ = [
    "DEFAULT_BATCH_INTERVAL_MIN",
    "BatchedPositionInput",
    "compute_batch_count",
    "generate_batched_plans",
]
