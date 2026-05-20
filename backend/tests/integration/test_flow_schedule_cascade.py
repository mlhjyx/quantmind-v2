"""Integration flow test: Multi-schtask schedule cascade.

Plan v10 Phase P Proposal 5: scaffold pending implementation (Phase J defer).
Covers: 16:25 HealthCheck -> 16:30 DailySignal -> 18:30 DataQualityCheck -> 20:00 PT_Watchdog.

Uses mock time (no real schtask trigger).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Plan v10 Phase P scaffold -- Phase J implementation defer")
def test_pt_chain_cascade_16_25_to_20_00():
    """Mock time cascade: verify 4 PT chain schtask fire correctly in order."""
    pass


def test_calendar_gate_skip_on_holidays_per_ll_181():
    """Verify is_trading_day_today_or_skip gates non-trading days (LL-181).

    Plan 1 (DEV_SCHEDULER §6.12 Phase I): the SSOT helper returns False on a
    non-trading day so Beat/schtask task bodies skip cleanly instead of 节假日空跑.
    """
    from unittest.mock import MagicMock, patch

    from qm_platform.calendar import is_trading_day_today_or_skip

    non_trading = MagicMock()
    non_trading.is_trading_day_with_reason.return_value = (False, "tushare_api: 非交易日")
    with patch("qm_platform.calendar.get_calendar", return_value=non_trading):
        assert is_trading_day_today_or_skip() is False

    trading = MagicMock()
    trading.is_trading_day_with_reason.return_value = (True, "tushare_api: 交易日")
    with patch("qm_platform.calendar.get_calendar", return_value=trading):
        assert is_trading_day_today_or_skip() is True


@pytest.mark.skip(reason="Plan v10 Phase P scaffold -- Phase J implementation defer")
def test_heartbeat_self_heal_signal_to_watchdog():
    """Verify DailySignal 16:30 self-heal writes heartbeat for PT_Watchdog 20:00 verify."""
    pass
