"""RealtimeRiskContextBuilder — Phase J §1.1 Chunk 1 (iter 153).

Builds `RiskContext` from live Redis state (QMT positions + market ticks) +
DB position_snapshot (entry_price / peak_price / entry_date metadata) for
RealtimeRiskEngine evaluation.

Design doc: docs/mvp/MVP_4_5_l1_realtime_risk_wire.md §3 Chunk 1.
Backend SSOT:
  - backend/qm_platform/risk/interface.py:21-67 (Position + RiskContext dataclass)
  - backend/app/core/qmt_client.py:46-75 (QMT Redis cache reader)

Pattern: Application service layer (allowed IO + Redis + DB; pure-engine
contract per 铁律 31 stays in qm_platform/).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.core.qmt_client import QMTClient, get_qmt_client
from backend.qm_platform.risk.interface import Position, RiskContext

logger = logging.getLogger(__name__)


class PositionSourceError(Exception):
    """Raised when Redis position / market data is stale or unavailable.

    iter 153 mitigation: TTL check on `market:latest:*` keys — if all
    latest tick data is > 120s stale, raise this exception. Caller (Beat
    task in Chunk 2) catches + logs + skips this tick (no false rule fire).
    """


class RealtimeRiskContextBuilder:
    """Builds RiskContext for RealtimeRiskEngine.on_tick / on_5min_beat.

    Inputs (lazy fetched per call):
      - QMTClient.get_positions() → {code: shares} from Redis portfolio:current
      - QMTClient.get_nav() → {cash, total_value, ...} from Redis portfolio:nav
      - QMTClient.get_prices(codes) → {code: price} from Redis market:latest:*
      - position_snapshot DB JOIN (entry_price / peak_price / entry_date)

    Output: RiskContext frozen dataclass (interface.py:45-67).

    Failure modes (fail-soft for context_builder, fail-loud for caller):
      - Redis stale (no QMT connection) → returns context with empty positions
      - DB unavailable → returns context with placeholder entry_price=0.0
        (engine rule will skip per Position spec "entry_price 0 表示未能计算, rule 应 skip")
      - All ticks stale > 120s → raise PositionSourceError (caller decides)
    """

    def __init__(self, qmt_client: QMTClient | None = None) -> None:
        self._qmt = qmt_client or get_qmt_client()

    def build_context(
        self,
        strategy_id: str | None = None,
        execution_mode: str | None = None,
    ) -> RiskContext:
        """Build RiskContext for current moment.

        Args:
            strategy_id: override; default = settings.PAPER_STRATEGY_ID
            execution_mode: override; default = settings.EXECUTION_MODE

        Returns:
            RiskContext frozen instance suitable for engine.on_tick(context).

        Raises:
            PositionSourceError: if all market:latest tick data is stale > 120s
                (caller should skip this tick).
        """
        sid = strategy_id or settings.PAPER_STRATEGY_ID
        mode = execution_mode or settings.EXECUTION_MODE
        if mode not in ("paper", "live"):
            logger.warning("Invalid execution_mode %r, defaulting to paper", mode)
            mode = "paper"

        # ── Fetch positions + current prices from QMT Redis cache ──
        positions_raw = self._qmt.get_positions()  # {code: shares}
        nav_dict = self._qmt.get_nav()  # {cash, total_value, ...} or None

        if not positions_raw:
            # Empty portfolio is a valid state (post-清仓 sustained)
            portfolio_nav = float(nav_dict.get("cash", 0.0)) if nav_dict else 0.0
            return RiskContext(
                strategy_id=sid,
                execution_mode=mode,  # type: ignore[arg-type]
                timestamp=datetime.now(UTC),
                positions=(),
                portfolio_nav=portfolio_nav,
            )

        codes = list(positions_raw.keys())
        prices_raw = self._qmt.get_prices(codes)  # {code: price}

        # Stale check — if ALL codes missing price, raise (Redis QMT down)
        if not prices_raw:
            raise PositionSourceError(
                "No market:latest:* prices for any held code "
                f"({len(codes)} positions). QMT Data Service may be down."
            )

        # ── Build Position tuple (entry_price / peak_price defaults to 0.0;
        #    DB-augmented entry_price requires Chunk 1.5 follow-up). ──
        positions = tuple(
            Position(
                code=code,
                shares=shares,
                entry_price=0.0,  # MVP Chunk 1: placeholder; engine rules skip
                peak_price=0.0,  # MVP Chunk 1: placeholder; engine rules skip
                current_price=float(prices_raw.get(code, 0.0)),
                entry_date=None,  # MVP Chunk 1: placeholder
            )
            for code, shares in positions_raw.items()
        )

        # ── Portfolio NAV from QMT (cash + position market_value) ──
        portfolio_nav: float = 0.0
        if nav_dict:
            portfolio_nav = float(nav_dict.get("total_value", 0.0))
        # Fallback: compute from positions × current_price (NAV missing case)
        if portfolio_nav == 0.0:
            portfolio_nav = sum(p.shares * p.current_price for p in positions)
            cash = float(nav_dict.get("cash", 0.0)) if nav_dict else 0.0
            portfolio_nav += cash

        return RiskContext(
            strategy_id=sid,
            execution_mode=mode,  # type: ignore[arg-type]
            timestamp=datetime.now(UTC),
            positions=positions,
            portfolio_nav=portfolio_nav,
        )

    def build_realtime_dict(
        self, positions: tuple[Position, ...]
    ) -> dict[str, dict[str, Any]] | None:
        """Build realtime extension dict for engine.on_tick (S5+ rules).

        Per RiskContext.realtime spec (interface.py:64-67):
            Keys: code → {prev_close, open_price, price_5min_ago, price_15min_ago,
                          day_volume, avg_daily_volume, industry}

        MVP Chunk 1: returns None (engine rules requiring realtime data skip).
        Chunk 2 follow-up will populate from market:latest:{code} 5min/15min ring buffer.
        """
        # Placeholder for Chunk 2 expansion — return None means engine skips realtime rules
        return None
