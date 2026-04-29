"""MVP 4.1 batch 3.8 unit tests — intraday_monitor 迁 SDK (kind-aware dispatch)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import intraday_monitor as im_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import Alert, AlertDispatchError  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    """P1.2 pattern: cache 在 _load_rules_engine_cached."""
    im_mod._load_rules_engine_cached.cache_clear()
    yield
    im_mod._load_rules_engine_cached.cache_clear()


# ─────────────────────── dispatch path ───────────────────────


def test_send_alert_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(im_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(im_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        im_mod.send_alert("P0", "组合大跌", "msg", kind="portfolio_drop", details_extra={"cb_level": 2})
        mock_sdk.assert_called_once_with("P0", "组合大跌", "msg", "portfolio_drop", {"cb_level": 2})
        mock_legacy.assert_not_called()


def test_send_alert_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(im_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(im_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        im_mod.send_alert("P0", "QMT断连", "msg", kind="qmt_disconnect")
        mock_legacy.assert_called_once_with("P0", "QMT断连", "msg")
        mock_sdk.assert_not_called()


# ─────────────────────── kind → dedup_key ───────────────────────


def _setup_router_mock(mock_router, mock_engine):
    """Build patches for router + AlertRulesEngine."""
    return (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    )


def test_sdk_qmt_disconnect_dedup_key():
    """kind=qmt_disconnect → dedup_key = intraday:qmt_disconnect:{trade_date}."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    p1, p2 = _setup_router_mock(mock_router, mock_engine)
    with p1, p2:
        im_mod._send_alert_via_platform_sdk("P0", "QMT断连 10:00", "qmt fail", "qmt_disconnect", None)

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "intraday_monitor"
    assert fired_alert.details["kind"] == "qmt_disconnect"
    dedup_key = mock_router.fire.call_args.kwargs["dedup_key"]
    assert dedup_key.startswith("intraday:qmt_disconnect:")


def test_sdk_portfolio_drop_dedup_includes_cb_level():
    """kind=portfolio_drop → dedup_key 含 cb_level (cb_l1/2/3 区分升级)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    p1, p2 = _setup_router_mock(mock_router, mock_engine)
    with p1, p2:
        im_mod._send_alert_via_platform_sdk(
            "P0", "组合暴跌 10:00", "msg", "portfolio_drop", {"cb_level": 3}
        )

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.details["cb_level"] == "3"  # 转 str
    dedup_key = mock_router.fire.call_args.kwargs["dedup_key"]
    # PR #142 code-reviewer P1: dedup_key 必含 trade_date 后缀防跨日 silent suppress
    assert dedup_key.startswith("intraday:portfolio_drop:cb_l3:")
    from datetime import date
    assert str(date.today()) in dedup_key


def test_sdk_portfolio_drop_levels_distinct_dedup():
    """cb_l2 → cb_l3 升级时各自独立 dedup_key (不被前级 5min suppress 阻塞)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    p1, p2 = _setup_router_mock(mock_router, mock_engine)
    with p1, p2:
        im_mod._send_alert_via_platform_sdk("P0", "组合大跌", "msg", "portfolio_drop", {"cb_level": 2})
        im_mod._send_alert_via_platform_sdk("P0", "组合暴跌", "msg", "portfolio_drop", {"cb_level": 3})

    keys = [c.kwargs["dedup_key"] for c in mock_router.fire.call_args_list]
    assert keys[0].startswith("intraday:portfolio_drop:cb_l2:")
    assert keys[1].startswith("intraday:portfolio_drop:cb_l3:")
    assert keys[0] != keys[1]


def test_sdk_portfolio_drop_without_cb_level_raises_value_error():
    """PR #142 python-reviewer P1.2 regression: portfolio_drop 必填 cb_level.

    防 silent cb_l0 fallback 把 cb_l1/2/3 三真级别 dedup 进 phantom bucket.
    """
    mock_router = MagicMock()
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    p1, p2 = _setup_router_mock(mock_router, mock_engine)
    with p1, p2, pytest.raises(ValueError, match="portfolio_drop.*cb_level"):
        im_mod._send_alert_via_platform_sdk(
            "P0", "组合大跌", "msg", "portfolio_drop", None,
        )

    with p1, p2, pytest.raises(ValueError, match="portfolio_drop.*cb_level"):
        im_mod._send_alert_via_platform_sdk(
            "P0", "组合大跌", "msg", "portfolio_drop", {"pnl_pct": "-0.05"},  # cb_level missing
        )


def test_sdk_emergency_stock_batch_dedup_key():
    """kind=emergency_stock_batch → 聚合 alert (不 per-code dedup)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    p1, p2 = _setup_router_mock(mock_router, mock_engine)
    with p1, p2:
        im_mod._send_alert_via_platform_sdk(
            "P1", "单股急跌 10:00", "msg", "emergency_stock_batch",
            {"stock_count": 3, "codes": "600519.SH,300750.SZ,000001.SZ"},
        )

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1
    assert fired_alert.details["stock_count"] == "3"
    assert fired_alert.details["codes"] == "600519.SH,300750.SZ,000001.SZ"
    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith(
        "intraday:emergency_stock_batch:"
    )


def test_sdk_emergency_stock_per_code_dedup():
    """legacy kind=emergency_stock (per-code) 兼容路径."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    p1, p2 = _setup_router_mock(mock_router, mock_engine)
    with p1, p2:
        im_mod._send_alert_via_platform_sdk(
            "P1", "单股 600519", "msg", "emergency_stock", {"code": "600519.SH"}
        )

    dedup_key = mock_router.fire.call_args.kwargs["dedup_key"]
    assert dedup_key.startswith("intraday:emergency_stock:600519.SH:")


def test_sdk_unknown_level_falls_back_to_p1():
    """unknown level (e.g. WARN) → Severity.P1 (与 batch 3.5 P2.1 一致)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    p1, p2 = _setup_router_mock(mock_router, mock_engine)
    with p1, p2:
        im_mod._send_alert_via_platform_sdk("CRITICAL", "title", "msg", "generic", None)

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P1


# ─────────────────────── error propagation ───────────────────────


def test_send_alert_swallows_dispatch_error():
    """send_alert 顶层 catch AlertDispatchError 不阻塞 monitor 主流程."""
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(
            im_mod, "_send_alert_via_platform_sdk",
            side_effect=AlertDispatchError("sink failed"),
        ),
    ):
        # 不应 raise, monitor 主流程继续
        im_mod.send_alert("P0", "test", "msg", kind="qmt_disconnect")


def test_sdk_dispatch_error_propagates_from_inner():
    """_send_alert_via_platform_sdk 内 AlertDispatchError 必传播 (顶层 send_alert 才 catch)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("inner sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    p1, p2 = _setup_router_mock(mock_router, mock_engine)
    with p1, p2, pytest.raises(AlertDispatchError, match="inner sink failed"):
        im_mod._send_alert_via_platform_sdk("P0", "title", "msg", "qmt_disconnect", None)


# ─────────────────────── lru_cache ───────────────────────


def test_get_rules_engine_caches():
    im_mod._load_rules_engine_cached.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        im_mod._get_rules_engine()
        im_mod._get_rules_engine()
        assert mock_fy.call_count == 1


def test_get_rules_engine_does_not_cache_failure():
    """P1.2 regression: yaml load 失败 None 不缓存."""
    im_mod._load_rules_engine_cached.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.side_effect = [
            FileNotFoundError("yaml missing"),
            MagicMock(),
        ]
        first = im_mod._get_rules_engine()
        second = im_mod._get_rules_engine()
        assert first is None
        assert second is not None
        assert mock_fy.call_count == 2
