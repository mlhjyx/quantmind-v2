"""Unit tests for QMTSellAdapter (S8 8c-followup).

覆盖:
  - sell() success path → status='ok', order_id=str(broker_order_id)
  - sell() broker returns -1 → status='rejected', error contains '-1'
  - sell() broker raises LiveTradingDisabledError → status='rejected',
    error='live_trading_disabled'
  - sell() broker raises generic Exception → status='error', error contains type
  - sell() shares ≤ 0 → ValueError (defensive)
  - reason truncated to 24 chars
  - market order: price=None + price_type='market' propagated
  - is_paper_mode_or_disabled() routing helper:
    EXECUTION_MODE=paper → True, EXECUTION_MODE=live + LIVE_TRADING_DISABLED=true → True,
    EXECUTION_MODE=live + LIVE_TRADING_DISABLED=false → False
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.exceptions import LiveTradingDisabledError
from app.services.risk.qmt_sell_adapter import QMTSellAdapter, is_paper_mode_or_disabled


class _MockBroker:
    """Mock MiniQMTBroker with controllable place_order behavior."""

    def __init__(
        self,
        *,
        order_id: int | None = 12345,
        raises: Exception | None = None,
    ):
        self._order_id = order_id
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    def place_order(
        self,
        code: str,
        direction: str,
        volume: int,
        price: float | None = None,
        price_type: str = "limit",
        remark: str = "",
    ) -> int:
        self.calls.append(
            {
                "code": code,
                "direction": direction,
                "volume": volume,
                "price": price,
                "price_type": price_type,
                "remark": remark,
            }
        )
        if self._raises is not None:
            raise self._raises
        assert self._order_id is not None
        return self._order_id


# ── SUCCESS ──


class TestQMTSellAdapterSuccess:
    def test_sell_success_returns_ok(self):
        broker = _MockBroker(order_id=98765)
        adapter = QMTSellAdapter(broker=broker)
        result = adapter.sell("600519.SH", 1000, "l4_abc12345", timeout=5.0)
        assert result["status"] == "ok"
        assert result["code"] == "600519.SH"
        assert result["shares"] == 1000
        assert result["order_id"] == "98765"
        assert result["filled_shares"] == 0  # fill arrives async via broker callback
        assert result["error"] is None

    def test_sell_invokes_market_order(self):
        broker = _MockBroker(order_id=1)
        adapter = QMTSellAdapter(broker=broker)
        adapter.sell("000001.SZ", 100, "l4_test", timeout=5.0)
        assert len(broker.calls) == 1
        call = broker.calls[0]
        assert call["direction"] == "sell"
        assert call["price"] is None
        assert call["price_type"] == "market"
        assert call["volume"] == 100

    def test_reason_truncated_to_24_chars(self):
        broker = _MockBroker(order_id=1)
        adapter = QMTSellAdapter(broker=broker)
        long_reason = "x" * 50
        adapter.sell("000001.SZ", 100, long_reason, timeout=5.0)
        assert len(broker.calls[0]["remark"]) <= 24


# ── FAILURE paths ──


class TestQMTSellAdapterFailures:
    def test_broker_returns_negative_one(self):
        broker = _MockBroker(order_id=-1)
        adapter = QMTSellAdapter(broker=broker)
        result = adapter.sell("600519.SH", 1000, "l4_test", timeout=5.0)
        assert result["status"] == "rejected"
        assert result["order_id"] is None
        assert "-1" in (result["error"] or "")

    def test_live_trading_disabled_error_returns_rejected(self):
        broker = _MockBroker(raises=LiveTradingDisabledError("LIVE_TRADING_DISABLED=true"))
        adapter = QMTSellAdapter(broker=broker)
        result = adapter.sell("600519.SH", 1000, "l4_test", timeout=5.0)
        assert result["status"] == "rejected"
        assert result["error"] == "live_trading_disabled"
        assert result["order_id"] is None

    def test_generic_exception_returns_error(self):
        broker = _MockBroker(raises=RuntimeError("xtquant not connected"))
        adapter = QMTSellAdapter(broker=broker)
        result = adapter.sell("600519.SH", 1000, "l4_test", timeout=5.0)
        assert result["status"] == "error"
        assert "RuntimeError" in (result["error"] or "")
        assert "xtquant not connected" in (result["error"] or "")

    def test_shares_zero_raises_value_error(self):
        broker = _MockBroker(order_id=1)
        adapter = QMTSellAdapter(broker=broker)
        with pytest.raises(ValueError, match="shares must be > 0"):
            adapter.sell("600519.SH", 0, "l4_test", timeout=5.0)

    def test_shares_negative_raises_value_error(self):
        broker = _MockBroker(order_id=1)
        adapter = QMTSellAdapter(broker=broker)
        with pytest.raises(ValueError, match="shares must be > 0"):
            adapter.sell("600519.SH", -10, "l4_test", timeout=5.0)


# ── is_paper_mode_or_disabled routing ──


class TestPaperModeRouting:
    def test_paper_execution_mode_returns_true(self):
        with patch("app.services.risk.qmt_sell_adapter.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "paper"
            mock_settings.LIVE_TRADING_DISABLED = False
            assert is_paper_mode_or_disabled() is True

    def test_live_mode_with_disabled_returns_true(self):
        with patch("app.services.risk.qmt_sell_adapter.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "live"
            mock_settings.LIVE_TRADING_DISABLED = True
            assert is_paper_mode_or_disabled() is True

    def test_live_mode_with_enabled_returns_false(self):
        with patch("app.services.risk.qmt_sell_adapter.settings") as mock_settings:
            mock_settings.EXECUTION_MODE = "live"
            mock_settings.LIVE_TRADING_DISABLED = False
            assert is_paper_mode_or_disabled() is False

    def test_missing_attrs_defaults_to_paper(self):
        """Defensive: if settings missing, default to safe stub path."""

        class _PartialSettings:
            pass  # no EXECUTION_MODE / LIVE_TRADING_DISABLED attrs

        with patch("app.services.risk.qmt_sell_adapter.settings", _PartialSettings()):
            # Defaults: EXECUTION_MODE="paper", LIVE_TRADING_DISABLED=True → True
            assert is_paper_mode_or_disabled() is True
