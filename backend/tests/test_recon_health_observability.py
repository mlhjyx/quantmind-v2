"""MVP 4.1 batch 3.5 unit tests — daily_reconciliation + factor_health_daily 迁 SDK."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import daily_reconciliation as dr_mod  # noqa: E402
import factor_health_daily as fhd_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import Alert, AlertDispatchError  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    dr_mod._get_rules_engine.cache_clear()
    fhd_mod._get_rules_engine.cache_clear()
    yield
    dr_mod._get_rules_engine.cache_clear()
    fhd_mod._get_rules_engine.cache_clear()


# ─────────────────────────── daily_reconciliation ───────────────────────────


def test_dr_send_alert_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(dr_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(dr_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        dr_mod.send_alert(MagicMock(), "P0", "对账失败", "QMT 无连接")
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_dr_send_alert_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(dr_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(dr_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        dr_mod.send_alert(MagicMock(), "P1", "对账差异", "5 只不一致")
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


def test_dr_sdk_path_p0_severity_and_dedup():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        dr_mod._send_alert_via_platform_sdk("P0", "对账失败", "QMT 无连接")

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "daily_reconciliation"
    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith(
        "daily_reconciliation:summary:"
    )


def test_dr_sdk_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        dr_mod._send_alert_via_platform_sdk("P0", "title", "content")


def test_dr_get_rules_engine_caches():
    dr_mod._get_rules_engine.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        dr_mod._get_rules_engine()
        dr_mod._get_rules_engine()
        assert mock_fy.call_count == 1


# ─────────────────────────── factor_health_daily ───────────────────────────


def test_fhd_send_alert_unified_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(fhd_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(fhd_mod, "_legacy_send_alert") as mock_legacy,
    ):
        fhd_mod._send_alert_unified(
            "P1", "因子健康 warning", "msg", date(2026, 4, 29), MagicMock()
        )
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_fhd_send_alert_unified_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(fhd_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(fhd_mod, "_legacy_send_alert") as mock_legacy,
    ):
        fhd_mod._send_alert_unified(
            "P1", "因子健康 warning", "msg", date(2026, 4, 29), MagicMock()
        )
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


def test_fhd_sdk_path_severity_and_dedup():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        fhd_mod._send_alert_via_platform_sdk(
            "P1", "因子健康 warning", "msg", date(2026, 4, 29)
        )

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1
    assert fired_alert.source == "factor_health_daily"
    assert "2026-04-29" in mock_router.fire.call_args.kwargs["dedup_key"]


def test_fhd_sdk_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        fhd_mod._send_alert_via_platform_sdk("P0", "title", "msg", date(2026, 4, 29))


def test_fhd_unknown_level_falls_back_to_p1():
    """非 p0/p1/p2/info 的 level (e.g. 'critical') fallback p1 (避免 ValueError)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        fhd_mod._send_alert_via_platform_sdk(
            "WARN", "title", "msg", date(2026, 4, 29)
        )

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1


def test_fhd_get_rules_engine_caches():
    fhd_mod._get_rules_engine.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        fhd_mod._get_rules_engine()
        fhd_mod._get_rules_engine()
        assert mock_fy.call_count == 1


# ─────────── P2.1 + P2.3 reviewer fix regression (batch 3.5) ───────────


def test_dr_unknown_level_falls_back_to_p1():
    """daily_reconciliation 与 factor_health_daily 一致, unknown level fallback p1.

    P2.1 reviewer 采纳: 防 ValueError → schtask FATAL 级联.
    """
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        dr_mod._send_alert_via_platform_sdk("WARN", "title", "content")

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1


def test_fhd_unified_legacy_path_requires_conn():
    """legacy notification_service.send_alert 路径 conn=None → ValueError.

    P2.3 reviewer 采纳: 防 silent AttributeError (legacy fn 内部对 conn 调用 cursor()).
    """
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        pytest.raises(ValueError, match="legacy notification_service.send_alert path requires conn"),
    ):
        fhd_mod._send_alert_unified(
            "P1", "title", "msg", date(2026, 4, 29), conn=None,
        )


def test_fhd_unified_sdk_path_accepts_none_conn():
    """SDK path 不需要 conn (Platform SDK 自管 PG dedup), conn=None 不 raise.

    P2.3 reviewer 采纳: SDK path conn 显式忽略契约.
    """
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(fhd_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(fhd_mod, "_legacy_send_alert") as mock_legacy,
    ):
        fhd_mod._send_alert_unified(
            "P1", "title", "msg", date(2026, 4, 29), conn=None,
        )
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()
