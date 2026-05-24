"""scripts/approve_l4.py SDK dispatch tests (MVP 4.1 batch 3.11, iter 56).

Covers batch 3.11 send_alert wrapper + _send_alert_via_platform_sdk.
Pattern sustained from batch 3.9/3.10 (test_llm_cost_*_observability.py).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts import approve_l4 as module


def test_send_alert_via_sdk_when_toggle_true():
    """SDK path called when OBSERVABILITY_USE_PLATFORM_SDK=True."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_legacy_send_alert") as mock_legacy,
    ):
        module.send_alert(
            "P1", "L4审批已通过", "策略 X 审批通过", "https://x.com", "sec", MagicMock()
        )
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_send_alert_via_legacy_when_toggle_false():
    """Legacy fallback path called when OBSERVABILITY_USE_PLATFORM_SDK=False."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", False, create=True),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_legacy_send_alert") as mock_legacy,
    ):
        module.send_alert("P1", "L4审批已通过", "ctx", "https://x.com", "sec", MagicMock())
        mock_legacy.assert_called_once_with(
            "P1", "L4审批已通过", "ctx", "https://x.com", "sec", mock_legacy.call_args.args[5]
        )
        mock_sdk.assert_not_called()


def test_kind_dispatch_approve():
    """Title containing '审批已通过' → kind='approve' in SDK dispatch."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
    ):
        module.send_alert("P1", "L4审批已通过", "ctx", "x", "s", None)
    assert mock_sdk.call_args.kwargs["kind"] == "approve"


def test_kind_dispatch_reject():
    """Title containing '审批已拒绝' → kind='reject'."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
    ):
        module.send_alert("P1", "L4审批已拒绝", "ctx", "x", "s", None)
    assert mock_sdk.call_args.kwargs["kind"] == "reject"


def test_kind_dispatch_force_reset():
    """Title containing '重置' → kind='force_reset'."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
    ):
        module.send_alert("P0", "L4强制重置", "ctx", "x", "s", None)
    assert mock_sdk.call_args.kwargs["kind"] == "force_reset"


def test_sdk_path_dedup_key_shape(capsys):
    """SDK path dedup_key shape: approve_l4:{kind}:{trade_date}."""
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
            title="L4审批已通过",
            content="content",
            kind="approve",
            details_extra={"webhook_configured": "1"},
        )
    fake_router.fire.assert_called_once()
    kwargs = fake_router.fire.call_args.kwargs
    assert kwargs["dedup_key"].startswith("approve_l4:approve:")
    assert kwargs["suppress_minutes"] == 60  # L4 审批 1h dedup


def test_send_alert_swallows_alert_dispatch_error(capsys):
    """AlertDispatchError → 顶层 catch, no raise (fail-soft 铁律 33)."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(
            module,
            "_send_alert_via_platform_sdk",
            side_effect=module.AlertDispatchError("sink fail"),
        ),
    ):
        module.send_alert("P1", "L4审批已通过", "ctx", "x", "s", None)
    out = capsys.readouterr().out
    assert "AlertDispatchError sink failed" in out
    assert "fail-soft" in out


def test_send_alert_swallows_generic_exception(capsys):
    """Generic Exception → 顶层 catch."""
    with (
        patch.object(module.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True, create=True),
        patch.object(
            module, "_send_alert_via_platform_sdk", side_effect=RuntimeError("unexpected")
        ),
    ):
        module.send_alert("P1", "L4审批已通过", "ctx", "x", "s", None)
    out = capsys.readouterr().out
    assert "告警 dispatch 失败" in out or "fail-soft" in out
