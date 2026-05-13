"""Unit tests for ReentryTracker — V3 §7.4 (S9b).

覆盖:
  - ReentryTracker.check: all 4 conditions met → should_notify=True
  - 1-day lookback window: stale sold record → within_window=False
  - Price rebound: below sell / within +5% / past +5%
  - Sentiment: None / negative / zero / positive
  - Regime: calm vs stress vs crisis
  - Defensive: ValueError on invalid sold_price / qty / current_price
  - Constructor validation: price_reb_window_pct / lookback_window_days /
    suggest_ratio range
  - format_reentry_notification: markdown shape contains all key fields
  - suggested_qty: 50% default ratio, configurable

铁律 31 sustained: PURE — 0 IO, 0 DB, 0 broker, 0 push.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.qm_platform.risk.execution.reentry_tracker import (
    ReentryCheckResult,
    ReentryTracker,
    SoldRecord,
    format_reentry_notification,
)

_NOW = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)


def _sold(
    symbol: str = "600519.SH",
    *,
    sell_price: float = 1700.0,
    sell_qty: int = 200,
    sell_at: datetime | None = None,
    sell_reason: str = "test",
) -> SoldRecord:
    return SoldRecord(
        symbol=symbol,
        sell_price=sell_price,
        sell_qty=sell_qty,
        sell_at=sell_at or _NOW - timedelta(hours=6),
        sell_reason=sell_reason,
    )


# ── All conditions met (happy path) ──


class TestAllConditionsMet:
    def test_all_4_conditions_should_notify(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(),
            current_price=1750.0,  # +2.9% above sell, within 5%
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.should_notify is True
        assert result.within_window is True
        assert result.price_ok is True
        assert result.sentiment_ok is True
        assert result.regime_ok is True
        assert result.symbol == "600519.SH"
        assert result.sell_price == 1700.0
        assert result.current_price == 1750.0
        # 50% of 200 = 100
        assert result.suggested_qty == 100


# ── Window check ──


class TestLookbackWindow:
    def test_within_24h_ok(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_at=_NOW - timedelta(hours=23)),
            current_price=1750.0,
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.within_window is True

    def test_exactly_24h_ok(self):
        """exact 1d boundary: ≤ 1 day → still ok."""
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_at=_NOW - timedelta(days=1)),
            current_price=1750.0,
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.within_window is True

    def test_past_24h_stale(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_at=_NOW - timedelta(days=2)),
            current_price=1750.0,
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.within_window is False
        assert result.should_notify is False  # window fail blocks aggregate


# ── Price rebound ──


class TestPriceRebound:
    def test_price_below_sell_no_reb(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_price=1700.0),
            current_price=1690.0,  # below sell
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.price_ok is False
        assert result.should_notify is False

    def test_price_at_sell_ok(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_price=1700.0),
            current_price=1700.0,  # exactly sell
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.price_ok is True

    def test_price_within_5pct_ok(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_price=1700.0),
            current_price=1750.0,  # +2.9%, within 5%
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.price_ok is True

    def test_price_at_5pct_boundary_ok(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_price=1700.0),
            current_price=1785.0,  # exactly +5%
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.price_ok is True

    def test_price_past_5pct_momentum_gone(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_price=1700.0),
            current_price=1800.0,  # +5.9%, past 5%
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.price_ok is False
        assert result.should_notify is False


# ── Sentiment ──


class TestSentiment:
    def test_positive_sentiment_ok(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(),
            current_price=1750.0,
            sentiment_24h=0.5,
            regime="calm",
            at=_NOW,
        )
        assert result.sentiment_ok is True

    def test_zero_sentiment_not_ok(self):
        """sentiment > 0 strict — zero treated as not yet 转正."""
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(),
            current_price=1750.0,
            sentiment_24h=0.0,
            regime="calm",
            at=_NOW,
        )
        assert result.sentiment_ok is False
        assert result.should_notify is False

    def test_negative_sentiment_not_ok(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(),
            current_price=1750.0,
            sentiment_24h=-0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.sentiment_ok is False

    def test_none_sentiment_fail_closed(self):
        """反 silent: None sentiment fails closed (反 assume positive)."""
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(),
            current_price=1750.0,
            sentiment_24h=None,
            regime="calm",
            at=_NOW,
        )
        assert result.sentiment_ok is False
        assert result.should_notify is False


# ── Regime ──


class TestRegime:
    @pytest.mark.parametrize("regime", ["calm"])
    def test_calm_ok(self, regime: str):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(),
            current_price=1750.0,
            sentiment_24h=0.3,
            regime=regime,
            at=_NOW,
        )
        assert result.regime_ok is True

    @pytest.mark.parametrize("regime", ["stress", "crisis", "unknown"])
    def test_non_calm_not_ok(self, regime: str):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(),
            current_price=1750.0,
            sentiment_24h=0.3,
            regime=regime,
            at=_NOW,
        )
        assert result.regime_ok is False
        assert result.should_notify is False


# ── Suggested qty ──


class TestSuggestedQty:
    def test_default_50pct_ratio(self):
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_qty=200),
            current_price=1750.0,
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.suggested_qty == 100

    def test_custom_ratio(self):
        tracker = ReentryTracker(suggest_ratio=0.75)
        result = tracker.check(
            sold=_sold(sell_qty=200),
            current_price=1750.0,
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.suggested_qty == 150

    def test_min_qty_1_for_tiny_positions(self):
        """1-share sold + 50% ratio → still suggests 1 (min)."""
        tracker = ReentryTracker()
        result = tracker.check(
            sold=_sold(sell_qty=1),
            current_price=1750.0,
            sentiment_24h=0.3,
            regime="calm",
            at=_NOW,
        )
        assert result.suggested_qty == 1


# ── Defensive ──


class TestDefensive:
    def test_zero_sell_price_raises(self):
        tracker = ReentryTracker()
        with pytest.raises(ValueError, match="sell_price must be > 0"):
            tracker.check(
                sold=_sold(sell_price=0),
                current_price=1750.0,
                sentiment_24h=0.3,
                regime="calm",
                at=_NOW,
            )

    def test_zero_sell_qty_raises(self):
        tracker = ReentryTracker()
        with pytest.raises(ValueError, match="sell_qty must be > 0"):
            tracker.check(
                sold=_sold(sell_qty=0),
                current_price=1750.0,
                sentiment_24h=0.3,
                regime="calm",
                at=_NOW,
            )

    def test_zero_current_price_raises(self):
        tracker = ReentryTracker()
        with pytest.raises(ValueError, match="current_price must be > 0"):
            tracker.check(
                sold=_sold(),
                current_price=0,
                sentiment_24h=0.3,
                regime="calm",
                at=_NOW,
            )

    @pytest.mark.parametrize("bad", [-0.05, 0])
    def test_constructor_rejects_invalid_price_window(self, bad: float):
        with pytest.raises(ValueError, match="price_reb_window_pct must be > 0"):
            ReentryTracker(price_reb_window_pct=bad)

    @pytest.mark.parametrize("bad", [-1, 0])
    def test_constructor_rejects_invalid_lookback(self, bad: int):
        with pytest.raises(ValueError, match="lookback_window_days must be > 0"):
            ReentryTracker(lookback_window_days=bad)

    @pytest.mark.parametrize("bad", [-0.1, 0, 1.5])
    def test_constructor_rejects_invalid_ratio(self, bad: float):
        with pytest.raises(ValueError, match="suggest_ratio must be in"):
            ReentryTracker(suggest_ratio=bad)


# ── format_reentry_notification ──


class TestFormatNotification:
    def test_markdown_contains_all_fields(self):
        result = ReentryCheckResult(
            should_notify=True,
            symbol="600519.SH",
            sell_price=1700.0,
            current_price=1750.0,
            suggested_qty=100,
            reasons=("all 4 conditions met",),
            price_ok=True,
            sentiment_ok=True,
            regime_ok=True,
            within_window=True,
        )
        text = format_reentry_notification(result)
        assert "600519.SH" in text
        assert "1700.00" in text
        assert "1750.00" in text
        assert "100" in text
        assert "考虑 re-entry" in text
        assert "V3 §7.4" in text  # citation for audit trail
