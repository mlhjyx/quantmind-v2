"""TrailingStop — V3 §7.3 动态 trailing 阈值 (S9a).

V3 §7.3 替代 PMSRule v1 (静态阈值):
  - 浮盈 ≥ 20% 启动 trailing
  - trailing % = max(10%, ATR × 2)
  - 浮盈 ≥ 50% → trailing 收紧到 ATR × 1.5
  - 浮盈 ≥ 100% → trailing 收紧到 ATR × 1

设计:
  - cadence: 5min (RealtimeRiskEngine 注册 on_5min_beat)
  - state: in-memory dict[code, TrailState] (peak price + activated flag).
    Reset on engine restart (acceptable per V3 §7.3 — state rebuilds from
    current_price when next 5min beat fires, peak resets to current).
  - ATR sourcing: context.realtime[code]["atr_pct"] (caller injects).
    None → fallback to floor 10% (反 silent skip on missing data).

Trigger logic per evaluate call:
  1. For each position with peak_price > entry_price:
       pnl_pct = (current - entry) / entry
       if pnl_pct < 0.20: skip (not yet activated)
  2. On first activation, record peak_price = max(peak from input, current_price)
  3. Update peak_price = max(stored_peak, current_price) (ratchet up only)
  4. Compute trailing_pct based on pnl_pct bracket:
       pnl ≥ 100% → trailing = ATR × 1
       pnl ≥ 50%  → trailing = ATR × 1.5
       pnl ≥ 20%  → trailing = max(0.10, ATR × 2)
  5. stop_price = peak * (1 - trailing_pct)
  6. if current_price <= stop_price → trigger sell

action="sell" — Engine 直调 broker (via S8 8c-followup wire path).

铁律 24: 单一职责 — 一规则一文件.
铁律 31: rule.evaluate pure (state is rule-internal, not engine IO).
铁律 33: 触发 return RuleResult, 不触发 return [] (不 raise).

关联: V3 §7.3 / ADR-016 PMSRule v1 deprecation / S5 9 rules cumulative → 10
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from backend.qm_platform._types import Severity

from ...interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)


# V3 §7.3 activation threshold + bracket thresholds
_ACTIVATION_PNL_PCT: float = 0.20  # 浮盈 20%
_TIGHT_BRACKET_50: float = 0.50  # 浮盈 50% → ATR × 1.5
_TIGHT_BRACKET_100: float = 1.00  # 浮盈 100% → ATR × 1

# trailing % floor when ATR unknown / too small (反 stop_price 紧贴 peak)
_TRAILING_FLOOR: float = 0.10


@dataclass
class _TrailState:
    """Per-symbol trailing state (rule-internal, not exposed in RiskContext)."""

    peak_price: float
    activated: bool = False


class TrailingStop(RiskRule):
    """V3 §7.3 动态 trailing stop — replaces PMSRule v1 静态阈值.

    Cadence: 5min (register on_5min_beat).
    Action: sell (caller dispatches via S8 8c-followup broker wire path).
    Severity: P1 (浮盈保护, 非组合级 P0 crisis).

    Usage:
        rule = TrailingStop()
        engine.register(rule, cadence="5min")
        # ATR injected via context.realtime[code]["atr_pct"]
        ctx = RiskContext(..., realtime={"600519.SH": {"atr_pct": 0.04}})
        results = engine.on_5min_beat(ctx)

    State persistence: in-memory only. peak_price ratchets up across calls
    via _trail_state dict. Engine restart resets state (acceptable per V3
    §7.3 — peak rebuilds from current price on next beat).
    """

    rule_id: str = "trailing_stop"
    severity: Severity = Severity.P1
    action: Literal["sell", "alert_only", "bypass"] = "sell"

    def __init__(self, activation_pnl: float = _ACTIVATION_PNL_PCT) -> None:
        self._activation_pnl = activation_pnl
        # Per-symbol state. Reset by engine restart; tests should call reset().
        self._trail_state: dict[str, _TrailState] = {}

    def reset(self) -> None:
        """Clear all per-symbol trailing state (tests + manual ops)."""
        self._trail_state.clear()

    def update_threshold(self, new_value: float) -> None:
        """S7→S5 wire: DynamicThresholdEngine 调整 activation threshold."""
        if not (0 < new_value < 1):
            raise ValueError(f"activation_pnl must be in (0, 1), got {new_value}")
        self._activation_pnl = new_value

    @staticmethod
    def _trailing_pct(pnl_pct: float, atr_pct: float | None) -> float:
        """Compute trailing % based on V3 §7.3 bracket logic.

        Args:
            pnl_pct: position unrealized PnL ratio (e.g. 0.30 = +30%).
            atr_pct: ATR as fraction of price (e.g. 0.04 = 4%). None → use floor.

        Returns:
            trailing %, floored at 10% when ATR missing / too small.
        """
        atr = atr_pct if (atr_pct is not None and atr_pct > 0) else 0.0
        if pnl_pct >= _TIGHT_BRACKET_100:
            return max(_TRAILING_FLOOR, atr * 1.0)
        if pnl_pct >= _TIGHT_BRACKET_50:
            return max(_TRAILING_FLOOR, atr * 1.5)
        # pnl_pct ≥ activation threshold (caller pre-checks)
        return max(_TRAILING_FLOOR, atr * 2.0)

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """Check trailing stop trigger across all positions.

        Returns RuleResult per triggered symbol. Untriggered positions just
        update internal peak_price state (no result emitted).

        Activation semantics (V3 §7.3):
          - Once activated (state exists), keep tracking even if current pnl
            retraces below 20%. Trailing stop's purpose is to catch the
            retrace — clearing state on retrace would defeat the rule.
          - Reset only on full exit (caller invokes reset() / position
            disappears from RiskContext) or after a trigger fires.
        """
        results: list[RuleResult] = []
        realtime = context.realtime or {}

        for pos in context.positions:
            if pos.shares <= 0 or pos.entry_price <= 0 or pos.current_price <= 0:
                continue

            pnl_pct = (pos.current_price - pos.entry_price) / pos.entry_price
            state = self._trail_state.get(pos.code)

            if state is None:
                # Not yet activated — check activation gate
                if pnl_pct < self._activation_pnl:
                    continue
                # First activation: record peak
                seed_peak = max(pos.peak_price, pos.current_price)
                state = _TrailState(peak_price=seed_peak, activated=True)
                self._trail_state[pos.code] = state
            else:
                # Already activated — ratchet peak (only upward)
                state.peak_price = max(state.peak_price, pos.peak_price, pos.current_price)

            # Use the PEAK-based pnl bracket (反 retrace flipping to lower bracket).
            # Bracket is determined by max pnl reached (proxy via peak vs entry).
            peak_pnl_pct = (state.peak_price - pos.entry_price) / pos.entry_price

            # Compute trailing % + stop price
            atr_pct = realtime.get(pos.code, {}).get("atr_pct") if realtime else None
            trailing_pct = self._trailing_pct(peak_pnl_pct, atr_pct)
            stop_price = state.peak_price * (1 - trailing_pct)

            if pos.current_price > stop_price:
                continue  # still above trailing stop — no trigger

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=pos.shares,
                    reason=(
                        f"TrailingStop: {pos.code} 浮盈 {pnl_pct:.2%} 触发动态止盈 "
                        f"(peak={state.peak_price:.2f}, "
                        f"trailing={trailing_pct:.2%}, "
                        f"stop={stop_price:.2f}, "
                        f"current={pos.current_price:.2f})"
                    ),
                    metrics={
                        "pnl_pct": round(pnl_pct, 6),
                        "peak_price": state.peak_price,
                        "trailing_pct": round(trailing_pct, 6),
                        "stop_price": round(stop_price, 4),
                        "current_price": pos.current_price,
                        "entry_price": pos.entry_price,
                        "atr_pct": atr_pct if atr_pct is not None else -1.0,
                        "shares": float(pos.shares),
                    },
                )
            )
            # 清 state after trigger — next entry rebuilds fresh peak
            self._trail_state.pop(pos.code, None)

        return results


__all__ = ["TrailingStop"]
