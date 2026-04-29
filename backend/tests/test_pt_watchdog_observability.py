"""MVP 4.1 batch 3.4 unit tests — pt_watchdog + pt_daily_summary 迁 Platform SDK."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import pt_daily_summary as pds_mod  # noqa: E402
import pt_watchdog as ptw_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import Alert, AlertDispatchError  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    ptw_mod._get_rules_engine.cache_clear()
    pds_mod._get_rules_engine.cache_clear()
    yield
    ptw_mod._get_rules_engine.cache_clear()
    pds_mod._get_rules_engine.cache_clear()


# ─────────────────────────── pt_watchdog ───────────────────────────


def test_ptw_send_alert_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(ptw_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(ptw_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        ptw_mod.send_alert("PT异常", "content")
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_ptw_send_alert_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(ptw_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(ptw_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        ptw_mod.send_alert("PT异常", "content")
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


def test_ptw_sdk_path_severity_p0_and_dedup():
    """pt_watchdog 全 P0 (PT 真金链路异常)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        ptw_mod._send_alert_via_platform_sdk("PT异常", "content")

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "pt_watchdog"
    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith("pt_watchdog:summary:")


def test_ptw_sdk_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        ptw_mod._send_alert_via_platform_sdk("PT异常", "content")


def test_ptw_get_rules_engine_caches():
    ptw_mod._get_rules_engine.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        ptw_mod._get_rules_engine()
        ptw_mod._get_rules_engine()
        assert mock_fy.call_count == 1


# ─────────────────────────── pt_daily_summary ───────────────────────────


def test_pds_send_dingtalk_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(pds_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pds_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        pds_mod._send_dingtalk("PT日报", "content", date(2026, 4, 29))
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_pds_send_dingtalk_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(pds_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pds_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        mock_legacy.return_value = True
        pds_mod._send_dingtalk("PT日报", "content")
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


def test_pds_sdk_path_severity_p1_and_dedup():
    """pt_daily_summary 固定 P1 (信息播报, 非紧急)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        pds_mod._send_alert_via_platform_sdk("PT日报", "content", date(2026, 4, 29))

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1
    assert fired_alert.source == "pt_daily_summary"
    assert "2026-04-29" in mock_router.fire.call_args.kwargs["dedup_key"]


def test_pds_sdk_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        pds_mod._send_alert_via_platform_sdk("PT日报", "content", date(2026, 4, 29))


def test_pds_send_dingtalk_default_trade_date_is_today():
    """trade_date 默认 today (caller 不传时 fallback)."""
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(pds_mod, "_send_alert_via_platform_sdk") as mock_sdk,
    ):
        pds_mod._send_dingtalk("title", "content")
    mock_sdk.assert_called_once()
    args = mock_sdk.call_args.args
    assert args[2] == date.today()


def test_pds_get_rules_engine_caches():
    pds_mod._get_rules_engine.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        pds_mod._get_rules_engine()
        pds_mod._get_rules_engine()
        assert mock_fy.call_count == 1
