"""MVP 4.1 batch 3.6 unit tests — rolling_wf + services_healthcheck 迁 SDK."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import rolling_wf as rwf_mod  # noqa: E402
import services_healthcheck as svc_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import Alert, AlertDispatchError  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    rwf_mod._get_rules_engine.cache_clear()
    svc_mod._get_rules_engine.cache_clear()
    yield
    rwf_mod._get_rules_engine.cache_clear()
    svc_mod._get_rules_engine.cache_clear()


# ─────────────────────────── rolling_wf ───────────────────────────


def test_rwf_send_dingtalk_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(rwf_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(rwf_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        rwf_mod._send_dingtalk("Rolling WF ALERT", "msg", "P1")
        mock_sdk.assert_called_once_with("Rolling WF ALERT", "msg", "P1")
        mock_legacy.assert_not_called()


def test_rwf_send_dingtalk_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(rwf_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(rwf_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        rwf_mod._send_dingtalk("Rolling WF WARN", "msg", "WARN")
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


def test_rwf_sdk_p1_severity_and_dedup():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        rwf_mod._send_alert_via_platform_sdk("Rolling WF ALERT", "msg", "P1")

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1
    assert fired_alert.source == "rolling_wf"
    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith(
        "rolling_wf:summary:"
    )


def test_rwf_sdk_warn_maps_to_p2():
    """WARN level (15-30% Sharpe 下降) 映射 Severity.P2 (less severe than ALERT P1)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        rwf_mod._send_alert_via_platform_sdk("Rolling WF WARN", "msg", "WARN")

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P2


def test_rwf_sdk_unknown_level_falls_back_to_p1():
    """非 p0/p1/p2/info/warn 的 level fallback p1 (与 batch 3.5 一致防 ValueError)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        rwf_mod._send_alert_via_platform_sdk("title", "msg", "CRITICAL")

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1


def test_rwf_sdk_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        rwf_mod._send_alert_via_platform_sdk("title", "msg", "P1")


def test_rwf_get_rules_engine_caches():
    rwf_mod._get_rules_engine.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        rwf_mod._get_rules_engine()
        rwf_mod._get_rules_engine()
        assert mock_fy.call_count == 1


# ─────────────────────────── services_healthcheck ───────────────────────────


def _make_health_report(status: str = "degraded", failures=None):
    """构造 HealthReport mock (避免触发真 sc/Redis 调用)."""
    report = MagicMock(spec=svc_mod.HealthReport)
    report.status = status
    report.failures = failures or ["QuantMind-CeleryBeat: STOPPED"]
    report.timestamp_utc = "2026-04-29T03:00:00+00:00"
    report.services = []
    report.beat_heartbeat = None
    report.redis_freshness = []
    return report


def test_svc_send_alert_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(svc_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(svc_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        svc_mod.send_alert(_make_health_report(), "transition (ok → degraded)")
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_svc_send_alert_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(svc_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(svc_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        svc_mod.send_alert(_make_health_report(), "transition")
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


def test_svc_sdk_path_p0_severity():
    """services_healthcheck 全 P0 (Beat 死亡 = MVP 3.1 Risk Framework 失效)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        svc_mod._send_alert_via_platform_sdk(_make_health_report(), "transition")

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "services_healthcheck"


def test_svc_sdk_dedup_key_includes_status():
    """status (ok / degraded) 进 dedup_key 防 transition 5min suppress 阻塞."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        svc_mod._send_alert_via_platform_sdk(_make_health_report("degraded"), "transition")

    dedup_key = mock_router.fire.call_args.kwargs["dedup_key"]
    assert "services_healthcheck:degraded:" in dedup_key
    assert str(date.today()) in dedup_key


def test_svc_sdk_recovery_status_uses_separate_dedup_key():
    """recovery (degraded → ok) 使用 'ok' status dedup_key, 不被 'degraded' 同日 suppress."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        svc_mod._send_alert_via_platform_sdk(_make_health_report("ok", []), "recovery")

    dedup_key = mock_router.fire.call_args.kwargs["dedup_key"]
    assert "services_healthcheck:ok:" in dedup_key


def test_svc_sdk_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        svc_mod._send_alert_via_platform_sdk(_make_health_report(), "transition")


def test_svc_get_rules_engine_caches():
    svc_mod._get_rules_engine.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        svc_mod._get_rules_engine()
        svc_mod._get_rules_engine()
        assert mock_fy.call_count == 1


def test_svc_build_alert_body_renders_failures():
    """_build_alert_body 公共函数 (SDK + legacy 共用), 校验 failures 行渲染."""
    report = _make_health_report("degraded", ["service-A: STOPPED", "service-B: STALE"])
    title, content = svc_mod._build_alert_body(report, "test reason")
    assert "DEGRADED" in title
    assert "test reason" in content
    assert "service-A: STOPPED" in content
    assert "service-B: STALE" in content


def test_svc_build_alert_body_recovery_status():
    """status='ok' 渲染 'Services Recovered' title (not DEGRADED)."""
    report = _make_health_report("ok", [])
    title, content = svc_mod._build_alert_body(report, "recovery (degraded → ok)")
    assert "Recovered" in title
    assert "recovery" in content
