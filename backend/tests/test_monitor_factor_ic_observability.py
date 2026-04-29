"""MVP 4.1 batch 3.3 unit tests — monitor_factor_ic 迁 Platform SDK."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import monitor_factor_ic as mfi_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import Alert, AlertDispatchError  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    mfi_mod._get_rules_engine.cache_clear()
    yield
    mfi_mod._get_rules_engine.cache_clear()


def _transition(factor="bp_ratio", to_status="warning"):
    """P1 reviewer 采纳: 实际键是 to_status (evaluate_transitions line 271/286/296/310)."""
    return {
        "factor_name": factor,
        "to_status": to_status,
        "from_status": "active",
        "reason": "test",
    }


# ─────────────────────────── send_dingtalk dispatch ───────────────────────────


def test_send_dingtalk_sdk_path_when_flag_true():
    from app.config import settings as app_settings

    with (
        patch.object(app_settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(mfi_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(mfi_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        mfi_mod.send_dingtalk("report text", [_transition()])
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_send_dingtalk_legacy_path_when_flag_false():
    from app.config import settings as app_settings

    with (
        patch.object(app_settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(mfi_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(mfi_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        mfi_mod.send_dingtalk("report", [])
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


# ─────────────────────────── _send_alert_via_platform_sdk severity ───────────────────────────


def test_sdk_severity_p0_when_retired_transition():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        mfi_mod._send_alert_via_platform_sdk(
            "report",
            [_transition(to_status="warning"), _transition(to_status="retired")],
        )

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0  # retired wins


def test_sdk_severity_p1_when_only_warning():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        mfi_mod._send_alert_via_platform_sdk("report", [_transition(to_status="warning")])

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1


def test_sdk_severity_real_evaluate_transitions_dict_format():
    """P1 reviewer 真 bug regression: evaluate_transitions 实际产 to_status, 不是 new_state."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    # 模拟 evaluate_transitions line 286 实际产物 (确切键名)
    real_transitions = [
        {
            "factor_name": "bp_ratio",
            "from_status": "warning",
            "to_status": "retired",
            "reason": "consecutive_negative_ic_6m",
        }
    ]

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        mfi_mod._send_alert_via_platform_sdk("report", real_transitions)

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    # 旧代码 read t.get("new_state") 返 None → INFO. 修后 read to_status → P0.
    assert fired_alert.severity == Severity.P0, (
        f"evaluate_transitions to_status='retired' must yield P0, got {fired_alert.severity}"
    )


def test_sdk_severity_info_when_no_transitions():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        mfi_mod._send_alert_via_platform_sdk("All OK report", [])

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.INFO


def test_sdk_dedup_key_summary_pattern():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        mfi_mod._send_alert_via_platform_sdk("report", [_transition()])

    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith(
        "monitor_factor_ic:summary:"
    )


def test_sdk_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        mfi_mod._send_alert_via_platform_sdk("report", [_transition(to_status="retired")])


# ─────────────────────────── legacy path ───────────────────────────


def test_legacy_no_webhook_skips():
    from app.config import settings as app_settings

    with patch.object(app_settings, "DINGTALK_WEBHOOK_URL", ""):
        mfi_mod._send_alert_via_legacy_dingtalk("report", [])  # silent skip


def test_send_dingtalk_caller_catches_alert_dispatch_error():
    """P3 reviewer 采纳: AlertDispatchError 必由 send_dingtalk 调用方 catch.

    main() line 605-610 应 try/except, 测试验证 send_dingtalk 自身仍 raise (不 swallow),
    caller 责任 catch. 覆盖 batch 3.1 P1.1 模式 — 防意外 silent swallow.
    """
    from app.config import settings as app_settings

    with (
        patch.object(app_settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(
            mfi_mod,
            "_send_alert_via_platform_sdk",
            side_effect=AlertDispatchError("sink failed"),
        ),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        mfi_mod.send_dingtalk("report", [_transition(to_status="retired")])


def test_get_rules_engine_caches_result():
    mfi_mod._get_rules_engine.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_from_yaml:
        mock_from_yaml.return_value = MagicMock()
        e1 = mfi_mod._get_rules_engine()
        e2 = mfi_mod._get_rules_engine()
        assert mock_from_yaml.call_count == 1
        assert e1 is e2
