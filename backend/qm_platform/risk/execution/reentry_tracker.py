"""ReentryTracker — V3 §7.4 Re-entry 逻辑 PURE engine (S9b).

V3 §7.4: L4.2 batched 卖出后追踪 sold symbols. If:
  - 卖出价 + 5% 内反弹 (1 day 内)
  - L2 sentiment_24h 转正
  - L3 regime 转 Calm

→ Push "考虑 re-entry: {symbol}, 卖出价 {X}, 当前 {Y}, 建议买回 {Z} 股"

NOT 自动 buy back (T+1 限制 + 失控风险). user 决策.

This module is a PURE check function. Caller (Celery task / event handler):
  1. Queries trade_log for recently batched-sold rows (action=BATCH, status=EXECUTED)
  2. Fetches current_price (Redis market:latest:{code}), sentiment_24h (L2 RAG),
     regime (L3 MarketRegime cache)
  3. Calls ReentryTracker.check(sold_record, current_price, sentiment_24h,
     regime, at) → ReentryCheckResult
  4. If result.should_notify, pushes via AlertDispatcher (S6)

Layered architecture:
  - Engine (this file) — PURE: 0 IO, 0 DB, 0 broker, 0 push
  - Caller — DB query + Redis read + AlertDispatcher push integration

铁律 31 sustained: 0 imports of DB / broker / network / AlertDispatcher.
铁律 33 sustained: fail-loud on invalid input (sell_price ≤ 0 / negative qty).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

logger = logging.getLogger(__name__)


# V3 §7.4 conditions
_PRICE_REB_WINDOW_PCT: float = 0.05  # +5% upper bound for re-entry signal
_LOOKBACK_WINDOW_DAYS: int = 1  # sold within last 1 day
_DEFAULT_SUGGEST_RATIO: float = 0.5  # suggest buying back 50% of sold qty


RegimeLiteral = Literal["calm", "stress", "crisis"]


@dataclass(frozen=True)
class SoldRecord:
    """Snapshot of a batched-sold position (caller assembles from trade_log).

    Args:
      symbol: stock code (e.g. "600519.SH")
      sell_price: weighted average fill price of the batched sell.
      sell_qty: total shares sold across batches (caller pre-aggregates if
        batched into N rows).
      sell_at: timestamp of the latest batch in the sell sequence
        (caller picks MAX over batches for 1-day window check).
      sell_reason: human-readable cause from RuleResult.reason (for audit
        trail in notification).
    """

    symbol: str
    sell_price: float
    sell_qty: int
    sell_at: datetime
    sell_reason: str = ""


@dataclass(frozen=True)
class ReentryCheckResult:
    """Output of ReentryTracker.check — PURE.

    Caller turns should_notify=True into a DingTalk push via AlertDispatcher.
    """

    should_notify: bool
    symbol: str
    sell_price: float
    current_price: float
    suggested_qty: int  # caller-tunable; default = sell_qty × 50% (conservative)
    reasons: tuple[str, ...]  # human-readable condition outcomes (audit log)
    # Per-condition breakdown so downstream UI / dashboard can show partial
    # matches (e.g. price ✅ + sentiment ✅ + regime ❌) without re-checking.
    price_ok: bool
    sentiment_ok: bool
    regime_ok: bool
    within_window: bool


class ReentryTracker:
    """V3 §7.4 Re-entry condition checker.

    Stateless — caller invokes check() per sold record per evaluation cycle
    (typically once per day per recently-sold symbol).

    Conditions ALL required for should_notify=True:
      1. sell_at within 1 day of `at`
      2. current_price ≥ sell_price AND current_price ≤ sell_price × (1 + 5%)
         (price has rebounded BUT stayed within 5% — too high → momentum
         already gone, miss the entry)
      3. sentiment_24h > 0 (L2 sentiment 转正)
      4. regime == "calm" (L3 转 Calm)

    Partial match → should_notify=False but breakdown surfaces in result so
    operator dashboard / future RAG can correlate "almost re-entry" cases.

    Usage:
        tracker = ReentryTracker()
        sold = SoldRecord(symbol="600519.SH", sell_price=1700.0,
                          sell_qty=200, sell_at=at - timedelta(hours=6))
        result = tracker.check(
            sold=sold,
            current_price=1750.0,
            sentiment_24h=0.3,
            regime="calm",
            at=datetime.now(UTC),
        )
        if result.should_notify:
            # Caller pushes via AlertDispatcher
            ...
    """

    def __init__(
        self,
        *,
        price_reb_window_pct: float = _PRICE_REB_WINDOW_PCT,
        lookback_window_days: int = _LOOKBACK_WINDOW_DAYS,
        suggest_ratio: float = _DEFAULT_SUGGEST_RATIO,
    ) -> None:
        if price_reb_window_pct <= 0:
            raise ValueError(f"price_reb_window_pct must be > 0, got {price_reb_window_pct}")
        if lookback_window_days <= 0:
            raise ValueError(f"lookback_window_days must be > 0, got {lookback_window_days}")
        if not (0 < suggest_ratio <= 1.0):
            raise ValueError(f"suggest_ratio must be in (0, 1], got {suggest_ratio}")
        self._price_reb_window_pct = price_reb_window_pct
        self._lookback_window_days = lookback_window_days
        self._suggest_ratio = suggest_ratio

    def check(
        self,
        *,
        sold: SoldRecord,
        current_price: float,
        sentiment_24h: float | None,
        regime: RegimeLiteral | str,
        at: datetime,
    ) -> ReentryCheckResult:
        """Evaluate all V3 §7.4 conditions; return result with per-condition breakdown.

        Args:
            sold: SoldRecord snapshot from trade_log aggregate.
            current_price: latest tick price (Redis market:latest:{code}).
            sentiment_24h: L2 sentiment in [-1, +1]. None treated as
                sentiment_ok=False (反 silent assume positive when data missing).
            regime: L3 MarketRegime cache value. Anything other than "calm" =
                regime_ok=False.
            at: current time anchor (UTC).

        Returns:
            ReentryCheckResult with should_notify aggregate + per-condition
            breakdown + suggested_qty.

        Raises:
            ValueError: sold.sell_price ≤ 0 / sold.sell_qty ≤ 0 / current_price ≤ 0.
        """
        if sold.sell_price <= 0:
            raise ValueError(f"sold.sell_price must be > 0, got {sold.sell_price}")
        if sold.sell_qty <= 0:
            raise ValueError(f"sold.sell_qty must be > 0, got {sold.sell_qty}")
        if current_price <= 0:
            raise ValueError(f"current_price must be > 0, got {current_price}")

        reasons: list[str] = []

        # 1. 1-day lookback window
        elapsed = at - sold.sell_at
        within_window = elapsed <= timedelta(days=self._lookback_window_days)
        if within_window:
            reasons.append(f"within {self._lookback_window_days}d window (elapsed={elapsed})")
        else:
            reasons.append(
                f"outside {self._lookback_window_days}d window (elapsed={elapsed}) — stale signal"
            )

        # 2. Price rebound within ±5% above sell_price (反 chasing too-high momentum)
        price_upper_bound = sold.sell_price * (1 + self._price_reb_window_pct)
        price_ok = sold.sell_price <= current_price <= price_upper_bound
        if price_ok:
            reasons.append(
                f"price reb OK: sell={sold.sell_price:.2f} ≤ current={current_price:.2f} "
                f"≤ +5%={price_upper_bound:.2f}"
            )
        elif current_price < sold.sell_price:
            reasons.append(
                f"price still below sell: current={current_price:.2f} < sell={sold.sell_price:.2f}"
            )
        else:
            reasons.append(
                f"price past +5% window: current={current_price:.2f} > {price_upper_bound:.2f} "
                "— momentum gone"
            )

        # 3. sentiment_24h > 0 (L2 sentiment 转正)
        sentiment_ok = sentiment_24h is not None and sentiment_24h > 0
        if sentiment_24h is None:
            reasons.append("sentiment_24h unknown — fail-closed (反 silent assume positive)")
        elif sentiment_ok:
            reasons.append(f"sentiment positive: {sentiment_24h:+.2f}")
        else:
            reasons.append(f"sentiment not positive: {sentiment_24h:+.2f}")

        # 4. regime == "calm"
        regime_ok = regime == "calm"
        if regime_ok:
            reasons.append("regime=calm")
        else:
            reasons.append(f"regime={regime} (not calm)")

        should_notify = within_window and price_ok and sentiment_ok and regime_ok
        suggested_qty = max(1, int(round(sold.sell_qty * self._suggest_ratio)))

        if should_notify:
            logger.info(
                "[reentry-tracker] should_notify=True symbol=%s sell=%.2f current=%.2f qty=%d",
                sold.symbol,
                sold.sell_price,
                current_price,
                suggested_qty,
            )

        return ReentryCheckResult(
            should_notify=should_notify,
            symbol=sold.symbol,
            sell_price=sold.sell_price,
            current_price=current_price,
            suggested_qty=suggested_qty,
            reasons=tuple(reasons),
            price_ok=price_ok,
            sentiment_ok=sentiment_ok,
            regime_ok=regime_ok,
            within_window=within_window,
        )


def format_reentry_notification(result: ReentryCheckResult) -> str:
    """Format the DingTalk push message per V3 §7.4 wording.

    Returns a markdown-flavored string suitable for AlertDispatcher payload.
    Caller appends to the dispatch + sets severity (INFO — not actionable
    in T+1 since not auto-buyback).
    """
    return (
        f"**考虑 re-entry: {result.symbol}**\n\n"
        f"- 卖出价: `{result.sell_price:.2f}`\n"
        f"- 当前: `{result.current_price:.2f}`\n"
        f"- 建议买回: `{result.suggested_qty}` 股\n\n"
        f"_条件全部满足 (1日内反弹+5% / sentiment 转正 / regime calm)._\n"
        f"_T+1 限制 — 不自动买回, 仅候选 (V3 §7.4)._"
    )


__all__ = [
    "ReentryCheckResult",
    "ReentryTracker",
    "RegimeLiteral",
    "SoldRecord",
    "format_reentry_notification",
]
