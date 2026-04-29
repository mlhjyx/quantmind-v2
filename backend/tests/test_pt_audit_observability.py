"""MVP 4.1 batch 3.2 unit tests — pt_audit 迁 Platform SDK.

覆盖:
  - SDK path: settings.OBSERVABILITY_USE_PLATFORM_SDK=True 走 PlatformAlertRouter
  - Legacy path: settings flag=False 走 httpx.post 直调
  - top_level severity 提取 (P0 > P1 > P2 via _LEVEL_SEVERITY)
  - rule 匹配 → format_dedup_key + suppress_minutes 正确传给 router
  - rules yaml 加载失败 fallback 通用 dedup_key
  - AlertDispatchError 传播 (fail-loud, 铁律 33)
  - send_aggregated_alert 空 findings 跳过
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import pt_audit as pa_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import (  # noqa: E402
    Alert,
    AlertDispatchError,
)


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    """Clear _get_rules_engine cache between tests (防 mock pollution)."""
    pa_mod._get_rules_engine.cache_clear()
    yield
    pa_mod._get_rules_engine.cache_clear()


def _finding(level: str = "P1", check: str = "test_check", title: str = "test"):
    return pa_mod.Finding(level=level, check=check, title=title)


# ─────────────────────────── _build_alert_text ───────────────────────────


def test_build_alert_text_p0_wins():
    findings = [_finding("P1", "c1", "x"), _finding("P0", "c2", "y"), _finding("P2", "c3", "z")]
    top, text = pa_mod._build_alert_text(findings, date(2026, 4, 29))
    assert top == "P0"
    assert "[P0] pt_audit 2026-04-29 — 3 findings" in text
    assert "[P0] c2: y" in text
    assert "[P1] c1: x" in text


def test_build_alert_text_only_p2():
    findings = [_finding("P2", "c1", "x"), _finding("P2", "c2", "y")]
    top, _ = pa_mod._build_alert_text(findings, date(2026, 4, 29))
    assert top == "P2"


# ─────────────────────────── send_aggregated_alert dispatch ───────────────────────────


def test_send_aggregated_alert_empty_skips():
    """空 findings 直接 return, 不调任何 path."""
    with (
        patch.object(pa_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pa_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        pa_mod.send_aggregated_alert([], date(2026, 4, 29))
        mock_sdk.assert_not_called()
        mock_legacy.assert_not_called()


def test_send_aggregated_alert_sdk_path_when_flag_true():
    from app.config import settings as app_settings

    with (
        patch.object(app_settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(pa_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pa_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        pa_mod.send_aggregated_alert([_finding("P0")], date(2026, 4, 29))
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_send_aggregated_alert_legacy_path_when_flag_false():
    from app.config import settings as app_settings

    with (
        patch.object(app_settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(pa_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pa_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        pa_mod.send_aggregated_alert([_finding("P1")], date(2026, 4, 29))
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


# ─────────────────────────── _send_alert_via_platform_sdk ───────────────────────────


def test_sdk_path_uses_correct_severity_and_dedup_key():
    """SDK path: severity 从 top_level 取, dedup_key 走 yaml rule format."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")

    mock_rule = MagicMock()
    mock_rule.format_dedup_key = MagicMock(return_value="pt_audit:summary:2026-04-29")
    mock_rule.suppress_minutes = 5

    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=mock_rule)

    findings = [_finding("P0", "st_leak", "ST stock"), _finding("P1", "turnover", "high")]

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        pa_mod._send_alert_via_platform_sdk(findings, date(2026, 4, 29))

    mock_router.fire.assert_called_once()
    call_args = mock_router.fire.call_args
    fired_alert: Alert = call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "pt_audit"
    assert fired_alert.trade_date == "2026-04-29"
    assert fired_alert.details["trade_date"] == "2026-04-29"
    assert fired_alert.details["finding_count"] == "2"
    assert "st_leak" in fired_alert.details["checks"]
    assert call_args.kwargs["dedup_key"] == "pt_audit:summary:2026-04-29"
    assert call_args.kwargs["suppress_minutes"] == 5


def test_sdk_path_fallback_dedup_key_when_no_rule_match():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        pa_mod._send_alert_via_platform_sdk([_finding("P1")], date(2026, 4, 29))

    call_args = mock_router.fire.call_args
    assert call_args.kwargs["dedup_key"] == "pt_audit:summary:2026-04-29"
    assert call_args.kwargs["suppress_minutes"] is None


def test_sdk_path_yaml_load_failure_does_not_block_alert():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch(
            "qm_platform.observability.AlertRulesEngine.from_yaml",
            side_effect=RuntimeError("yaml broken"),
        ),
    ):
        pa_mod._send_alert_via_platform_sdk([_finding("P1")], date(2026, 4, 29))

    mock_router.fire.assert_called_once()
    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith("pt_audit:summary:")


def test_sdk_path_dispatch_error_propagates():
    """AlertDispatchError 必传播 (铁律 33 fail-loud, run_audit catch 不混淆 exit_code)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("All channels failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="All channels failed"),
    ):
        pa_mod._send_alert_via_platform_sdk([_finding("P0")], date(2026, 4, 29))


# ─────────────────────────── _send_alert_via_legacy_dingtalk ───────────────────────────


def test_legacy_path_no_webhook_skips():
    """webhook 未配置 silent skip (与旧版一致)."""
    from app.config import settings as app_settings

    with patch.object(app_settings, "DINGTALK_WEBHOOK_URL", ""):
        # 不抛异常即 PASS (legacy silent skip 行为)
        pa_mod._send_alert_via_legacy_dingtalk([_finding("P1")], date(2026, 4, 29))


def test_legacy_path_calls_httpx_post():
    """legacy path 用 httpx.post 直调 (pt_audit 历史 pattern, 不走 dingtalk dispatcher).

    P2.1 reviewer 采纳后: webhook 从 settings.DINGTALK_WEBHOOK_URL 读 (vs 旧 os.environ).
    """
    from app.config import settings as app_settings

    fake_httpx = MagicMock()
    fake_httpx.post = MagicMock()

    with (
        patch.object(app_settings, "DINGTALK_WEBHOOK_URL", "https://oapi.test"),
        patch.dict("sys.modules", {"httpx": fake_httpx}),
    ):
        pa_mod._send_alert_via_legacy_dingtalk(
            [_finding("P0", "st_leak", "ST stock")], date(2026, 4, 29)
        )

    fake_httpx.post.assert_called_once()
    args = fake_httpx.post.call_args
    assert args.args[0] == "https://oapi.test"
    payload = args.kwargs["json"]
    assert payload["msgtype"] == "text"
    assert "[P0]" in payload["text"]["content"]
    assert "st_leak" in payload["text"]["content"]


# ─────────────────────────── _get_rules_engine cache ───────────────────────────


def test_run_audit_alert_dispatch_error_does_not_block_scheduler_log_or_exit_code(
    tmp_path,
):
    """reviewer P3.1 采纳: run_audit AlertDispatchError integration test.

    模式 P1.1 batch 3.1 一致: AlertDispatchError 不阻断 _write_scheduler_log + exit_code
    反映 finding 严重度 (而非 sink 失败). schtask LastResult 仍能反映 issue 严重度.
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

    fake_findings = [_finding("P0", "st_leak", "ST stock leak detected")]

    with (
        patch.object(pa_mod, "get_sync_conn", return_value=mock_conn),
        patch.object(pa_mod, "_is_trading_day", return_value=True),
        patch.object(pa_mod, "send_aggregated_alert") as mock_send,
        patch.object(pa_mod, "_write_scheduler_log") as mock_write_log,
        patch.object(pa_mod, "_CHECK_FUNCS", {"st_leak": lambda *args: fake_findings}),
    ):
        # send_aggregated_alert raise AlertDispatchError
        mock_send.side_effect = AlertDispatchError("All channels failed")

        exit_code, findings = pa_mod.run_audit(
            strategy_id="test_sid",
            audit_date=date(2026, 4, 29),
            alert=True,
        )

    # P3.1 验证三点:
    # 1. AlertDispatchError 被 catch (exit_code 反映 P0 finding 严重度, 不传播)
    assert exit_code == 1, (
        f"exit_code=1 反映 P0 finding 严重度 (vs sink 失败 exit=2 混淆), got: {exit_code}"
    )
    # 2. _write_scheduler_log 仍调用 (审计留底)
    mock_write_log.assert_called_once()
    write_log_args = mock_write_log.call_args.args
    assert write_log_args[3] == "alert"  # status
    # 3. send_aggregated_alert 被尝试
    mock_send.assert_called_once()
    # 4. findings 正确返回
    assert len(findings) == 1
    assert findings[0].level == "P0"


def test_get_rules_engine_caches_result():
    """reviewer P2 from batch 3.1: lru_cache 防 17 scripts 每次重复 yaml I/O."""
    pa_mod._get_rules_engine.cache_clear()
    with patch(
        "qm_platform.observability.AlertRulesEngine.from_yaml"
    ) as mock_from_yaml:
        mock_from_yaml.return_value = MagicMock()
        engine1 = pa_mod._get_rules_engine()
        engine2 = pa_mod._get_rules_engine()
        engine3 = pa_mod._get_rules_engine()

        assert mock_from_yaml.call_count == 1
        assert engine1 is engine2 is engine3
