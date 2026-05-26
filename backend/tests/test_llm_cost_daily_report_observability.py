"""scripts/llm_cost_daily_report.py SDK dispatch tests (MVP 4.1 batch 3.10, iter 54).

Covers batch 3.10 send_alert / _send_alert_via_platform_sdk /
_send_alert_via_legacy_dingtalk introduced as part of iter 54 SDK migration.

Pattern sustained from batch 3.9 test_llm_cost_monthly_audit_observability.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts import llm_cost_daily_report as module

# ────────────────────────────────────────────────────────────────────
# SDK dispatch path (settings.OBSERVABILITY_USE_PLATFORM_SDK = True)
# ────────────────────────────────────────────────────────────────────


def test_send_alert_via_sdk_when_toggle_true():
    """SDK path called when OBSERVABILITY_USE_PLATFORM_SDK=True. Returns 0 on success."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        result = module.send_alert(
            webhook_url="https://oapi.example.com",
            title="LLM Daily 2026-05-25",
            content="MTD: $10.5",
            secret="",
            keyword="",
        )
        assert result == 0
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_send_alert_via_legacy_when_toggle_false():
    """Legacy fallback path called when OBSERVABILITY_USE_PLATFORM_SDK=False."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", False, create=True),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_send_alert_via_legacy_dingtalk", return_value=True) as mock_legacy,
    ):
        result = module.send_alert(
            webhook_url="https://oapi.example.com",
            title="LLM Daily 2026-05-25",
            content="MTD: $10.5",
        )
        assert result == 0
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


def test_send_alert_legacy_push_failure_returns_1():
    """Legacy path returns False → send_alert returns 1 (报告 OK 但 dispatch failed)."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", False, create=True),
        patch.object(module, "_send_alert_via_legacy_dingtalk", return_value=False),
    ):
        result = module.send_alert(
            webhook_url="https://oapi.example.com",
            title="LLM Daily 2026-05-25",
            content="MTD: $10.5",
        )
        assert result == 1


# ────────────────────────────────────────────────────────────────────
# SDK path dedup_key shape
# ────────────────────────────────────────────────────────────────────


def test_sdk_path_dedup_key_daily_format():
    """SDK path dedup_key shape: llm_cost_daily:{trade_date}."""
    fake_router = MagicMock()
    with (
        patch.dict(
            "sys.modules",
            {
                "qm_platform._types": MagicMock(Severity=MagicMock(side_effect=lambda x: x)),
                "qm_platform.observability": MagicMock(
                    Alert=MagicMock(),
                    get_alert_router=MagicMock(return_value=fake_router),
                ),
            },
        ),
    ):
        module._send_alert_via_platform_sdk(
            level="P1",
            title="LLM Daily 2026-05-25",
            content="MTD: $10.5",
            kind="llm_cost_daily_report",
            details_extra={"webhook_configured": "1"},
        )
    fake_router.fire.assert_called_once()
    call_kwargs = fake_router.fire.call_args.kwargs
    assert call_kwargs["dedup_key"].startswith("llm_cost_daily:")
    assert call_kwargs["suppress_minutes"] == 1440  # daily cadence


# ────────────────────────────────────────────────────────────────────
# Fail-soft (铁律 33) — top-level send_alert swallows errors → returns 1
# ────────────────────────────────────────────────────────────────────


def test_send_alert_swallows_alert_dispatch_error():
    """AlertDispatchError from SDK → caught + return 1 (report unaffected)."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(
            module,
            "_send_alert_via_platform_sdk",
            side_effect=module.AlertDispatchError("simulated sink failure"),
        ),
    ):
        result = module.send_alert(webhook_url="x", title="t", content="c")
    assert result == 1


def test_send_alert_swallows_generic_exception():
    """Generic Exception → top-level catch → return 1."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(
            module,
            "_send_alert_via_platform_sdk",
            side_effect=RuntimeError("simulated unexpected"),
        ),
    ):
        result = module.send_alert(webhook_url="x", title="t", content="c")
    assert result == 1


# ────────────────────────────────────────────────────────────────────
# Legacy path delegates to send_markdown_sync
# ────────────────────────────────────────────────────────────────────


def test_legacy_dispatcher_delegates_to_send_markdown_sync():
    """Legacy path calls existing app.services.dispatchers.dingtalk.send_markdown_sync."""
    with patch.object(module, "send_markdown_sync", return_value=True) as mock_smd:
        result = module._send_alert_via_legacy_dingtalk(
            webhook_url="https://oapi.example.com",
            title="t",
            content="c",
            secret="s",
            keyword="k",
        )
    assert result is True
    mock_smd.assert_called_once_with(
        webhook_url="https://oapi.example.com",
        title="t",
        content="c",
        secret="s",
        keyword="k",
    )


def test_legacy_dispatcher_propagates_false():
    """Legacy path returns underlying send_markdown_sync return value."""
    with patch.object(module, "send_markdown_sync", return_value=False):
        result = module._send_alert_via_legacy_dingtalk(webhook_url="x", title="t", content="c")
    assert result is False
