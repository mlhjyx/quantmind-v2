"""scripts/llm_cost_monthly_audit.py SDK dispatch tests (MVP 4.1 batch 3.9, iter 51).

Covers batch 3.9 send_alert / _send_alert_via_platform_sdk /
_send_alert_via_legacy_dingtalk introduced in commit 14ae11a.

Pattern sustained from batch 3.8 test_intraday_monitor_observability.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Module under test
from scripts import llm_cost_monthly_audit as module


# ────────────────────────────────────────────────────────────────────
# SDK dispatch path (settings.OBSERVABILITY_USE_PLATFORM_SDK = True)
# ────────────────────────────────────────────────────────────────────


def test_send_alert_via_sdk_when_toggle_true():
    """SDK path called when OBSERVABILITY_USE_PLATFORM_SDK=True."""
    fake_settings = MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)
    with (
        patch.dict("sys.modules", {"app.config": MagicMock(settings=fake_settings)}),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        module.send_alert(
            env={}, status="WARN", mtd_total=42.5, budget=50.0, mtd_ratio=0.85, mom_change=12.3
        )
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_send_alert_via_legacy_when_toggle_false():
    """Legacy fallback path called when OBSERVABILITY_USE_PLATFORM_SDK=False."""
    fake_settings = MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=False)
    with (
        patch.dict("sys.modules", {"app.config": MagicMock(settings=fake_settings)}),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        module.send_alert(
            env={}, status="WARN", mtd_total=42.5, budget=50.0, mtd_ratio=0.85, mom_change=12.3
        )
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


def test_send_alert_settings_unavailable_falls_to_legacy():
    """Settings import failure → fall back to legacy path (fail-safe per 铁律 33)."""
    with (
        patch.dict("sys.modules", {"app.config": None}),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        # Simulate ImportError by removing app.config from modules
        module.send_alert(
            env={}, status="WARN", mtd_total=42.5, budget=50.0, mtd_ratio=0.85, mom_change=12.3
        )
        # When settings unavailable, use_sdk=False → legacy called
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


# ────────────────────────────────────────────────────────────────────
# SDK path dedup_key + Alert shape
# ────────────────────────────────────────────────────────────────────


def test_sdk_path_dedup_key_includes_status_and_year_month():
    """SDK path dedup_key shape: llm_cost_monthly:{status}:{year_month}."""
    fake_router = MagicMock()
    fake_alert_cls = MagicMock()

    with (
        patch.dict(
            "sys.modules",
            {
                "qm_platform._types": MagicMock(Severity=MagicMock(side_effect=lambda x: x)),
                "qm_platform.observability": MagicMock(
                    Alert=fake_alert_cls,
                    get_alert_router=MagicMock(return_value=fake_router),
                ),
            },
        ),
    ):
        module._send_alert_via_platform_sdk(
            level="P1",
            title="LLM 成本告警 WARN 2026-05",
            content="MTD 成本: $42.5 / 预算 $50.0 (85.0%)",
            kind="llm_cost_monthly_audit",
            details_extra={"status": "WARN", "mtd_total": "42.5000"},
        )

    # Router fire called once
    fake_router.fire.assert_called_once()
    call_kwargs = fake_router.fire.call_args.kwargs
    # dedup_key contains status + year-month
    assert "llm_cost_monthly:WARN:" in call_kwargs["dedup_key"]
    assert call_kwargs["suppress_minutes"] == 1440  # monthly cadence


# ────────────────────────────────────────────────────────────────────
# 2-tier fail-soft (铁律 33) — top-level send_alert swallows errors
# ────────────────────────────────────────────────────────────────────


def test_send_alert_swallows_alert_dispatch_error(capsys):
    """AlertDispatchError raised from SDK → caught at top-level (audit unaffected)."""
    fake_settings = MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)
    with (
        patch.dict("sys.modules", {"app.config": MagicMock(settings=fake_settings)}),
        patch.object(
            module,
            "_send_alert_via_platform_sdk",
            side_effect=module.AlertDispatchError("simulated sink failure"),
        ),
    ):
        # Must NOT raise
        module.send_alert(
            env={}, status="WARN", mtd_total=42.5, budget=50.0, mtd_ratio=0.85, mom_change=12.3
        )

    out = capsys.readouterr().out
    assert "AlertDispatchError sink failed" in out
    assert "fail-soft" in out


def test_send_alert_swallows_generic_exception(capsys):
    """Generic Exception raised → top-level catch (settings unavailable / config error etc)."""
    fake_settings = MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)
    with (
        patch.dict("sys.modules", {"app.config": MagicMock(settings=fake_settings)}),
        patch.object(
            module,
            "_send_alert_via_platform_sdk",
            side_effect=RuntimeError("simulated unexpected"),
        ),
    ):
        # Must NOT raise
        module.send_alert(
            env={},
            status="CAP_EXCEEDED",
            mtd_total=55.0,
            budget=50.0,
            mtd_ratio=1.1,
            mom_change=None,
        )

    out = capsys.readouterr().out
    assert "告警 dispatch 失败" in out or "fail-soft" in out


# ────────────────────────────────────────────────────────────────────
# Backward-compat alias preserved
# ────────────────────────────────────────────────────────────────────


def test_push_dingtalk_alias_points_to_send_alert():
    """_push_dingtalk alias preserved for backward-compat with line 282 call site."""
    assert module._push_dingtalk is module.send_alert


# ────────────────────────────────────────────────────────────────────
# Legacy path HMAC signing preserved
# ────────────────────────────────────────────────────────────────────


def test_legacy_dingtalk_no_webhook_skips(capsys):
    """Legacy path: missing DINGTALK_WEBHOOK_URL → skip with log, no exception."""
    module._send_alert_via_legacy_dingtalk(
        env={}, status="WARN", mtd_total=42.5, budget=50.0, mtd_ratio=0.85, mom_change=12.3
    )
    out = capsys.readouterr().out
    assert "未配置" in out
    assert "跳过" in out


@pytest.mark.parametrize(
    "status,expected_tail_kw",
    [
        ("WARN", "接近月度预算上限"),
        ("CAP_EXCEEDED", "CAP 超标"),
    ],
)
def test_legacy_dingtalk_status_tail(status, expected_tail_kw):
    """Legacy path: text body tail varies by status (WARN vs CAP_EXCEEDED)."""
    fake_resp = MagicMock(status_code=200)
    with patch("httpx.post", return_value=fake_resp) as mock_post:
        module._send_alert_via_legacy_dingtalk(
            env={"DINGTALK_WEBHOOK_URL": "https://oapi.example.com/robot/send"},
            status=status,
            mtd_total=42.5,
            budget=50.0,
            mtd_ratio=0.85,
            mom_change=12.3,
        )
    mock_post.assert_called_once()
    body = mock_post.call_args.kwargs["json"]
    assert expected_tail_kw in body["text"]["content"]
