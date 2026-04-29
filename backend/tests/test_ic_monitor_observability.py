"""MVP 4.1 batch 3.3 unit tests — ic_monitor 迁 Platform SDK."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import ic_monitor as im_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import (  # noqa: E402
    Alert,
    AlertDispatchError,
)


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    im_mod._get_rules_engine.cache_clear()
    yield
    im_mod._get_rules_engine.cache_clear()


def _alert(level="P1", factor="bp_ratio", msg="IC drop"):
    return {"level": level, "factor": factor, "msg": msg, "label": "L2_DECAY"}


# ─────────────────────────── _send_dingtalk dispatch ───────────────────────────


def test_send_dingtalk_sdk_path_when_flag_true():
    from app.config import settings as app_settings

    with (
        patch.object(app_settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(im_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(im_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        im_mod._send_dingtalk("title", "content", "P0", alerts=[_alert("P0")])
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_send_dingtalk_legacy_path_when_flag_false():
    from app.config import settings as app_settings

    with (
        patch.object(app_settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(im_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(im_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        mock_legacy.return_value = True
        im_mod._send_dingtalk("title", "content", "P1", alerts=[])
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


# ─────────────────────────── _send_alert_via_platform_sdk ───────────────────────────


def test_sdk_path_uses_correct_severity_and_dedup_key():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")

    mock_rule = MagicMock()
    mock_rule.format_dedup_key = MagicMock(return_value="ic_monitor:summary:2026-04-29")
    mock_rule.suppress_minutes = 5

    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=mock_rule)

    alerts = [_alert("P0", "bp_ratio"), _alert("P1", "dv_ttm")]

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        im_mod._send_alert_via_platform_sdk("title", "content", "P0", alerts)

    mock_router.fire.assert_called_once()
    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "ic_monitor"
    assert fired_alert.details["alert_count"] == "2"
    assert "bp_ratio" in fired_alert.details["factors"]
    assert "dv_ttm" in fired_alert.details["factors"]


def test_sdk_path_fallback_dedup_key_when_no_rule_match():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        im_mod._send_alert_via_platform_sdk("title", "content", "P1", [_alert("P1")])

    call_args = mock_router.fire.call_args
    assert call_args.kwargs["dedup_key"].startswith("ic_monitor:summary:")
    assert call_args.kwargs["suppress_minutes"] is None


def test_sdk_path_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("All channels failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="All channels failed"),
    ):
        im_mod._send_alert_via_platform_sdk("title", "content", "P0", [_alert("P0")])


# ─────────────────────────── lru_cache ───────────────────────────


def test_get_rules_engine_caches_result():
    im_mod._get_rules_engine.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_from_yaml:
        mock_from_yaml.return_value = MagicMock()
        e1 = im_mod._get_rules_engine()
        e2 = im_mod._get_rules_engine()
        assert mock_from_yaml.call_count == 1
        assert e1 is e2
