"""scripts/smoke_test.py SDK dispatch tests (MVP 4.1 batch 3.12 LAST, iter 57).

Covers batch 3.12 send_dingtalk_alert wrapper + _send_alert_via_platform_sdk +
_legacy_send_dingtalk_alert. Pattern sustained from batch 3.8-3.11.

完成后 Wave 4 MVP 4.1 batch 3.x = 17/17 = 100% milestone.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts import smoke_test as module


def test_send_alert_via_sdk_when_toggle_true():
    """SDK path called when OBSERVABILITY_USE_PLATFORM_SDK=True."""
    with (
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_legacy_send_dingtalk_alert") as mock_legacy,
        patch.dict(
            "sys.modules",
            {
                "app.config": MagicMock(settings=MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)),
            },
        ),
    ):
        module.send_dingtalk_alert("P1", "冒烟测试失败", "10 fails")
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_send_alert_via_legacy_when_toggle_false():
    """Legacy fallback path called when OBSERVABILITY_USE_PLATFORM_SDK=False."""
    with (
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_legacy_send_dingtalk_alert") as mock_legacy,
        patch.dict(
            "sys.modules",
            {
                "app.config": MagicMock(settings=MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=False)),
            },
        ),
    ):
        module.send_dingtalk_alert("P1", "冒烟测试通过", "all OK")
        mock_legacy.assert_called_once_with("P1", "冒烟测试通过", "all OK")
        mock_sdk.assert_not_called()


def test_settings_import_failure_falls_to_legacy():
    """app.config import 失败 → legacy fallback (fail-safe per 铁律 33)."""
    with (
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(module, "_legacy_send_dingtalk_alert") as mock_legacy,
        patch.dict("sys.modules", {"app.config": None}),
    ):
        module.send_dingtalk_alert("P0", "后端无响应", "ctx")
    # Settings import will fail → legacy fallback called
    mock_legacy.assert_called_once()
    mock_sdk.assert_not_called()


def test_kind_dispatch_backend_down():
    """Title containing '后端无响应' → kind='backend_down'."""
    with (
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.dict(
            "sys.modules",
            {
                "app.config": MagicMock(settings=MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)),
            },
        ),
    ):
        module.send_dingtalk_alert("P0", "冒烟测试: 后端无响应", "ctx")
    assert mock_sdk.call_args.kwargs["kind"] == "backend_down"


def test_kind_dispatch_smoke_fail():
    """Title containing '失败' → kind='smoke_fail'."""
    with (
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.dict(
            "sys.modules",
            {
                "app.config": MagicMock(settings=MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)),
            },
        ),
    ):
        module.send_dingtalk_alert("P1", "冒烟测试失败", "ctx")
    assert mock_sdk.call_args.kwargs["kind"] == "smoke_fail"


def test_kind_dispatch_smoke_pass():
    """Title containing '通过' → kind='smoke_pass'."""
    with (
        patch.object(module, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.dict(
            "sys.modules",
            {
                "app.config": MagicMock(settings=MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)),
            },
        ),
    ):
        module.send_dingtalk_alert("P2", "冒烟测试通过", "ctx")
    assert mock_sdk.call_args.kwargs["kind"] == "smoke_pass"


def test_sdk_path_dedup_key_shape():
    """SDK path dedup_key shape: smoke_test:{kind}:{trade_date}; suppress=30."""
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
        module._send_alert_via_platform_sdk(level="P0", title="t", content="c", kind="backend_down")
    fake_router.fire.assert_called_once()
    kwargs = fake_router.fire.call_args.kwargs
    assert kwargs["dedup_key"].startswith("smoke_test:backend_down:")
    assert kwargs["suppress_minutes"] == 30  # smoke test 30min dedup


def test_send_alert_swallows_alert_dispatch_error(capsys):
    """AlertDispatchError → 顶层 catch (fail-soft 铁律 33)."""
    fake_dispatch_error = type("AlertDispatchError", (Exception,), {})

    with (
        patch.dict(
            "sys.modules",
            {
                "app.config": MagicMock(settings=MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)),
                "qm_platform.observability": MagicMock(AlertDispatchError=fake_dispatch_error),
            },
        ),
        patch.object(
            module,
            "_send_alert_via_platform_sdk",
            side_effect=fake_dispatch_error("sink fail"),
        ),
    ):
        module.send_dingtalk_alert("P0", "冒烟测试失败", "ctx")
    out = capsys.readouterr().out
    assert "AlertDispatchError" in out or "fail-soft" in out


def test_send_alert_swallows_generic_exception(capsys):
    """Generic Exception → 顶层 catch."""
    with (
        patch.dict(
            "sys.modules",
            {
                "app.config": MagicMock(settings=MagicMock(OBSERVABILITY_USE_PLATFORM_SDK=True)),
            },
        ),
        patch.object(
            module, "_send_alert_via_platform_sdk", side_effect=RuntimeError("unexpected")
        ),
    ):
        module.send_dingtalk_alert("P1", "冒烟测试失败", "ctx")
    out = capsys.readouterr().out
    assert "告警 dispatch 失败" in out or "fail-soft" in out
