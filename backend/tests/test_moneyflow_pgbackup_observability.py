"""MVP 4.1 batch 3.7 unit tests — pull_moneyflow + pg_backup 迁 SDK."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import pg_backup as pgb_mod  # noqa: E402
import pull_moneyflow as pmf_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import Alert, AlertDispatchError  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    """P1.2 pattern: cache 在 _load_rules_engine_cached (非 _get_rules_engine).

    autouse 防 cross-test pollution + 反失败 None 误以为缓存命中.
    """
    pmf_mod._load_rules_engine_cached.cache_clear()
    pgb_mod._load_rules_engine_cached.cache_clear()
    yield
    pmf_mod._load_rules_engine_cached.cache_clear()
    pgb_mod._load_rules_engine_cached.cache_clear()


# ─────────────────────────── pull_moneyflow ───────────────────────────


def test_pmf_dispatch_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(pmf_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pmf_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        pmf_mod._send_moneyflow_alert("20260429", 5, 120)
        mock_sdk.assert_called_once_with("20260429", 5, 120)
        mock_legacy.assert_not_called()


def test_pmf_dispatch_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(pmf_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pmf_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        pmf_mod._send_moneyflow_alert("20260429", 5, 120)
        mock_legacy.assert_called_once_with("20260429", 5, 120)
        mock_sdk.assert_not_called()


def test_pmf_sdk_p0_severity_and_dedup():
    """pull_moneyflow 数据延迟 P0 (Tushare 入库延迟影响下游因子)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        pmf_mod._send_alert_via_platform_sdk("20260429", 5, 120)

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "pull_moneyflow"
    assert fired_alert.details["data_date"] == "20260429"
    assert fired_alert.details["max_retry"] == "5"
    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith(
        "pull_moneyflow:summary:"
    )


def test_pmf_sdk_dedup_keys_distinct_per_data_date():
    """P1 regression (PR #141 code-reviewer): 不同 td (data date) → 不同 dedup_key.

    防 backfill 一次跨多日 (e.g. 20260428 + 20260429) 时所有 td 共享 today_str
    dedup key, 第二个起 silently 5min suppress drop. 修复后 trade_date=td_iso
    (非 today), 每个 data date 独立 suppress window.
    """
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        pmf_mod._send_alert_via_platform_sdk("20260428", 5, 120)
        pmf_mod._send_alert_via_platform_sdk("20260429", 5, 120)

    assert mock_router.fire.call_count == 2
    dedup_28 = mock_router.fire.call_args_list[0].kwargs["dedup_key"]
    dedup_29 = mock_router.fire.call_args_list[1].kwargs["dedup_key"]
    assert dedup_28 != dedup_29, "P1: backfill 跨日 dedup collision"
    assert "2026-04-28" in dedup_28
    assert "2026-04-29" in dedup_29

    # alert.details["trade_date"] 必 = data date (非 today_str)
    alert_28: Alert = mock_router.fire.call_args_list[0].args[0]
    alert_29: Alert = mock_router.fire.call_args_list[1].args[0]
    assert alert_28.details["trade_date"] == "2026-04-28"
    assert alert_29.details["trade_date"] == "2026-04-29"
    # data_date 保留 YYYYMMDD format (向后兼容)
    assert alert_28.details["data_date"] == "20260428"
    assert alert_29.details["data_date"] == "20260429"


def test_pmf_sdk_dispatch_error_propagates():
    mock_router = MagicMock()
    mock_router.fire = MagicMock(side_effect=AlertDispatchError("sink failed"))
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="sink failed"),
    ):
        pmf_mod._send_alert_via_platform_sdk("20260429", 5, 120)


def test_pmf_get_rules_engine_caches():
    pmf_mod._load_rules_engine_cached.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        pmf_mod._get_rules_engine()
        pmf_mod._get_rules_engine()
        assert mock_fy.call_count == 1


def test_pmf_get_rules_engine_does_not_cache_failure():
    """P1.2 regression: yaml load 失败时 None 不被缓存, 下次重试."""
    pmf_mod._load_rules_engine_cached.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.side_effect = [
            FileNotFoundError("yaml missing"),
            MagicMock(),
        ]
        first = pmf_mod._get_rules_engine()
        second = pmf_mod._get_rules_engine()
        assert first is None
        assert second is not None
        assert mock_fy.call_count == 2


# ─────────────────────────── pg_backup ───────────────────────────


def test_pgb_send_alert_sdk_path_when_flag_true():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(pgb_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pgb_mod, "_send_alert_via_legacy_notification") as mock_legacy,
    ):
        pgb_mod.send_alert("pg_dump备份失败", "exit=1")
        mock_sdk.assert_called_once_with("pg_dump备份失败", "exit=1")
        mock_legacy.assert_not_called()


def test_pgb_send_alert_legacy_path_when_flag_false():
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(pgb_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(pgb_mod, "_send_alert_via_legacy_notification") as mock_legacy,
    ):
        pgb_mod.send_alert("pg_dump备份失败", "exit=1")
        mock_legacy.assert_called_once_with("pg_dump备份失败", "exit=1")
        mock_sdk.assert_not_called()


def test_pgb_sdk_p0_severity_and_dedup():
    """pg_backup 全 P0 (备份失败 = DR 链路风险)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")
    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        pgb_mod._send_alert_via_platform_sdk("pg_dump备份超时", "30min timeout")

    fired_alert: Alert = mock_router.fire.call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "pg_backup"
    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith(
        "pg_backup:summary:"
    )


def test_pgb_send_alert_swallows_dispatch_error():
    """send_alert (顶层) catch AlertDispatchError 不阻塞备份流程."""
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(
            pgb_mod, "_send_alert_via_platform_sdk",
            side_effect=AlertDispatchError("sink fail"),
        ),
    ):
        # 不应 raise, 备份流程继续
        pgb_mod.send_alert("test title", "test content")


def test_pgb_send_alert_swallows_legacy_exception():
    """send_alert (顶层) catch legacy Exception 不阻塞备份流程."""
    from app.config import settings

    with (
        patch.object(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(
            pgb_mod, "_send_alert_via_legacy_notification",
            side_effect=ConnectionError("DB down"),
        ),
    ):
        # 不应 raise, 备份流程继续
        pgb_mod.send_alert("test title", "test content")


def test_pgb_get_rules_engine_caches():
    pgb_mod._load_rules_engine_cached.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.return_value = MagicMock()
        pgb_mod._get_rules_engine()
        pgb_mod._get_rules_engine()
        assert mock_fy.call_count == 1


def test_pgb_get_rules_engine_does_not_cache_failure():
    """P1.2 regression: pg_backup yaml load 失败 None 不缓存."""
    pgb_mod._load_rules_engine_cached.cache_clear()
    with patch("qm_platform.observability.AlertRulesEngine.from_yaml") as mock_fy:
        mock_fy.side_effect = [
            FileNotFoundError("yaml missing"),
            MagicMock(),
        ]
        first = pgb_mod._get_rules_engine()
        second = pgb_mod._get_rules_engine()
        assert first is None
        assert second is not None
        assert mock_fy.call_count == 2
