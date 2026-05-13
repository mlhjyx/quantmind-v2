"""XtQuantTickSubscriber audit-fix tests (S5 audit fix P1-1 + P1-2).

Coverage:
- P1-1 stop() invokes xtdata.unsubscribe_quote for each registered seq id
- P1-1 stop() is a no-op when not running
- P1-1 stop() best-effort: continues unsubscribing remaining symbols even if one fails
- P1-2 get_avg_daily_volume returns None when no provider injected (default safe stub)
- P1-2 get_avg_daily_volume routes to injected provider
- P1-2 get_avg_daily_volume swallows provider exception and returns None (反 per-tick crash)

关联铁律: 31 (lazy xtquant) / 33 (fail-loud at top, silent skip at per-tick provider)
关联 ADR: ADR-055 §S5 audit fix sediment
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from qm_platform.risk.realtime.subscriber import XtQuantTickSubscriber

# §1 P1-1: stop() invokes unsubscribe_quote


def test_stop_unsubscribes_all_registered_seq_ids() -> None:
    """stop() calls xtdata.unsubscribe_quote(seq) for each registered subscription."""
    sub = XtQuantTickSubscriber()
    mock_xt = MagicMock()
    # subscribe_quote returns incrementing seq ids
    mock_xt.subscribe_quote.side_effect = [101, 202, 303]
    sub._xtdata = mock_xt  # bypass lazy import

    sub.start(["600519.SH", "000001.SZ", "300750.SZ"])
    assert sub.is_running is True
    assert sub._subscribe_ids == {
        "600519.SH": 101,
        "000001.SZ": 202,
        "300750.SZ": 303,
    }

    sub.stop()

    assert sub.is_running is False
    # 3 unsubscribe calls, one per seq id
    assert mock_xt.unsubscribe_quote.call_count == 3
    called_seqs = sorted(c.args[0] for c in mock_xt.unsubscribe_quote.call_args_list)
    assert called_seqs == [101, 202, 303]
    # State cleared
    assert sub._subscribe_ids == {}


def test_stop_is_noop_when_not_running() -> None:
    """stop() returns silently when subscriber was never started."""
    sub = XtQuantTickSubscriber()
    mock_xt = MagicMock()
    sub._xtdata = mock_xt

    sub.stop()  # never started

    mock_xt.unsubscribe_quote.assert_not_called()
    assert sub.is_running is False


def test_stop_best_effort_continues_on_failure() -> None:
    """If unsubscribe_quote fails on one seq, the loop continues for the rest."""
    sub = XtQuantTickSubscriber()
    mock_xt = MagicMock()
    mock_xt.subscribe_quote.side_effect = [10, 20, 30]
    sub._xtdata = mock_xt

    sub.start(["A.SH", "B.SZ", "C.SZ"])

    mock_xt.unsubscribe_quote.side_effect = [None, RuntimeError("xt boom"), None]
    sub.stop()  # should not raise

    assert mock_xt.unsubscribe_quote.call_count == 3
    assert sub._subscribe_ids == {}


def test_subscribe_failure_does_not_record_seq_id() -> None:
    """If subscribe_quote raises, the symbol is not added to _subscribe_ids."""
    sub = XtQuantTickSubscriber()
    mock_xt = MagicMock()
    mock_xt.subscribe_quote.side_effect = [42, RuntimeError("xt down")]
    sub._xtdata = mock_xt

    sub.start(["GOOD.SH", "BAD.SZ"])

    # Only GOOD.SH recorded
    assert sub._subscribe_ids == {"GOOD.SH": 42}


# §2 P1-2: avg_volume_provider injection


def test_avg_volume_default_returns_none() -> None:
    """Without provider injection, get_avg_daily_volume returns None (safe stub)."""
    sub = XtQuantTickSubscriber()
    assert sub.get_avg_daily_volume("600519.SH") is None


def test_avg_volume_routes_to_injected_provider() -> None:
    """With provider injected, get_avg_daily_volume forwards (code, days) and returns the result."""
    provider = MagicMock(return_value=1_234_567.0)
    sub = XtQuantTickSubscriber(avg_volume_provider=provider)

    value = sub.get_avg_daily_volume("600519.SH", days=20)

    assert value == pytest.approx(1_234_567.0)
    provider.assert_called_once_with("600519.SH", 20)


def test_avg_volume_provider_exception_returns_none() -> None:
    """Provider exception is swallowed → None (反 per-tick callback crash)."""

    def boom(code: str, days: int) -> float | None:
        raise ValueError(f"db connection lost for {code}")

    sub = XtQuantTickSubscriber(avg_volume_provider=boom)
    assert sub.get_avg_daily_volume("600519.SH") is None


def test_avg_volume_provider_returning_none_propagates() -> None:
    """Provider explicitly returning None is preserved (not coerced)."""
    sub = XtQuantTickSubscriber(avg_volume_provider=lambda c, d: None)
    assert sub.get_avg_daily_volume("600519.SH") is None
