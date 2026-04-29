"""MVP 4.1 batch 3.1 unit tests — data_quality_check 迁 Platform SDK.

覆盖:
  - SDK path: settings.OBSERVABILITY_USE_PLATFORM_SDK=True 走 PlatformAlertRouter
  - Legacy path: settings.OBSERVABILITY_USE_PLATFORM_SDK=False 走 dingtalk.send_markdown_sync
  - severity 自动从 alerts "[P0]"/"[P1]"/"[P2]" 前缀提取最高级
  - dry-run 不实发任一 path
  - rule 匹配 → format_dedup_key + suppress_minutes 正确传给 router
  - rules yaml 加载失败 fallback 通用 dedup_key
  - AlertDispatchError 传播 (fail-loud, 铁律 33)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 加 scripts 到 path 以便 import data_quality_check 函数
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import data_quality_check as dq_mod  # noqa: E402
from qm_platform._types import Severity  # noqa: E402
from qm_platform.observability import (  # noqa: E402
    Alert,
    AlertDispatchError,
)


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    """Clear _get_rules_engine cache between tests (防 mock pollution).

    reviewer P2 引入 lru_cache 后, 测试间共享 process-level cache 导致 mock 污染
    (test A mock from_yaml 返 rule, test B mock from_yaml 返 None 但 cache 命中
    test A 的 rule). 显式 clear 隔离每个 test.
    """
    dq_mod._get_rules_engine.cache_clear()
    yield
    dq_mod._get_rules_engine.cache_clear()


# ─────────────────────────── _max_severity ───────────────────────────


def test_max_severity_p0_wins():
    alerts = ["[P1] some warn", "[P0] critical thing", "[P2] info"]
    assert dq_mod._max_severity(alerts) == "p0"


def test_max_severity_p1_when_no_p0():
    alerts = ["[P1] warn1", "[P2] info", "[P1] warn2"]
    assert dq_mod._max_severity(alerts) == "p1"


def test_max_severity_p2_only():
    assert dq_mod._max_severity(["[P2] info"]) == "p2"


def test_max_severity_default_p1_when_no_prefix():
    """无 [PX] 前缀时默认 p1 (兜底, 现状行为)."""
    assert dq_mod._max_severity(["plain message"]) == "p1"


def test_max_severity_empty_list_rejected():
    """reviewer P2 采纳: 空列表 reject, 防 silent p1 误导."""
    with pytest.raises(ValueError, match="empty alerts list"):
        dq_mod._max_severity([])


# ─────────────────────────── send_dingtalk_alert dispatch ───────────────────────────


def test_send_alert_dry_run_no_dispatch():
    """dry-run 不调 SDK 也不调 legacy."""
    with (
        patch.object(dq_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(dq_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        dq_mod.send_dingtalk_alert(["[P1] test"], date(2026, 4, 29), dry_run=True)
        mock_sdk.assert_not_called()
        mock_legacy.assert_not_called()


def test_send_alert_sdk_path_when_flag_true():
    with (
        patch.object(dq_mod.settings, "OBSERVABILITY_USE_PLATFORM_SDK", True),
        patch.object(dq_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(dq_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        dq_mod.send_dingtalk_alert(["[P0] critical"], date(2026, 4, 29), dry_run=False)
        mock_sdk.assert_called_once()
        mock_legacy.assert_not_called()


def test_send_alert_legacy_path_when_flag_false():
    with (
        patch.object(dq_mod.settings, "OBSERVABILITY_USE_PLATFORM_SDK", False),
        patch.object(dq_mod, "_send_alert_via_platform_sdk") as mock_sdk,
        patch.object(dq_mod, "_send_alert_via_legacy_dingtalk") as mock_legacy,
    ):
        dq_mod.send_dingtalk_alert(["[P1] warn"], date(2026, 4, 29), dry_run=False)
        mock_legacy.assert_called_once()
        mock_sdk.assert_not_called()


# ─────────────────────────── _send_alert_via_platform_sdk ───────────────────────────


def test_sdk_path_uses_correct_severity_and_dedup_key():
    """SDK path: severity 从 alerts 提取, dedup_key 走 yaml rule format."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")

    mock_rule = MagicMock()
    mock_rule.format_dedup_key = MagicMock(
        return_value="data_quality:summary:2026-04-29"
    )
    mock_rule.suppress_minutes = 5

    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=mock_rule)

    with (
        patch.object(dq_mod, "PROJECT_ROOT", PROJECT_ROOT),
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        dq_mod._send_alert_via_platform_sdk(["[P0] critical issue"], date(2026, 4, 29))

    mock_router.fire.assert_called_once()
    call_args = mock_router.fire.call_args
    fired_alert: Alert = call_args.args[0]
    assert fired_alert.severity == Severity.P0
    assert fired_alert.source == "data_quality_check"
    assert fired_alert.trade_date == "2026-04-29"
    assert fired_alert.details["trade_date"] == "2026-04-29"
    assert fired_alert.details["issue_count"] == "1"
    # dedup_key 来自 rule.format_dedup_key
    assert call_args.kwargs["dedup_key"] == "data_quality:summary:2026-04-29"
    assert call_args.kwargs["suppress_minutes"] == 5


def test_sdk_path_fallback_dedup_key_when_no_rule_match():
    """rule.match() 返 None 时, fallback 通用 dedup_key + None suppress_minutes."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")

    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch.object(dq_mod, "PROJECT_ROOT", PROJECT_ROOT),
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
    ):
        dq_mod._send_alert_via_platform_sdk(["[P1] warn"], date(2026, 4, 29))

    call_args = mock_router.fire.call_args
    assert call_args.kwargs["dedup_key"] == "data_quality:summary:2026-04-29"
    assert call_args.kwargs["suppress_minutes"] is None


def test_sdk_path_yaml_load_failure_does_not_block_alert():
    """yaml 加载异常: 降级用 fallback dedup_key, 仍 fire (不阻断告警)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(return_value="sent")

    with (
        patch.object(dq_mod, "PROJECT_ROOT", PROJECT_ROOT),
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch(
            "qm_platform.observability.AlertRulesEngine.from_yaml",
            side_effect=RuntimeError("yaml broken"),
        ),
    ):
        dq_mod._send_alert_via_platform_sdk(["[P1] warn"], date(2026, 4, 29))

    # 仍 fire, 用 fallback dedup_key
    mock_router.fire.assert_called_once()
    assert mock_router.fire.call_args.kwargs["dedup_key"].startswith("data_quality:summary:")


def test_sdk_path_dispatch_error_propagates():
    """AlertDispatchError 必传播 (铁律 33 fail-loud, main() top-level catch → exit=2)."""
    mock_router = MagicMock()
    mock_router.fire = MagicMock(
        side_effect=AlertDispatchError("All channels failed")
    )

    mock_engine = MagicMock()
    mock_engine.match = MagicMock(return_value=None)

    with (
        patch.object(dq_mod, "PROJECT_ROOT", PROJECT_ROOT),
        patch("qm_platform.observability.get_alert_router", return_value=mock_router),
        patch("qm_platform.observability.AlertRulesEngine.from_yaml", return_value=mock_engine),
        pytest.raises(AlertDispatchError, match="All channels failed"),
    ):
        dq_mod._send_alert_via_platform_sdk(["[P0] critical"], date(2026, 4, 29))


# ─────────────────────────── _send_alert_via_legacy_dingtalk ───────────────────────────


def test_legacy_path_no_webhook_skips():
    """webhook 未配置时 legacy path warn + 跳过, 不 raise (旧行为保留)."""
    with patch.object(dq_mod.settings, "DINGTALK_WEBHOOK_URL", ""):
        # 不抛异常即 PASS (legacy 行为是 silent skip, 与旧版一致)
        dq_mod._send_alert_via_legacy_dingtalk(["[P1] x"], date(2026, 4, 29))


def test_legacy_path_calls_dingtalk_send_markdown_sync():
    with (
        patch.object(dq_mod.settings, "DINGTALK_WEBHOOK_URL", "https://oapi.test"),
        patch.object(dq_mod.dingtalk, "send_markdown_sync", return_value=True) as mock_send,
    ):
        dq_mod._send_alert_via_legacy_dingtalk(["[P1] warn"], date(2026, 4, 29))

    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["webhook_url"] == "https://oapi.test"
    assert "数据质量巡检告警" in kwargs["content"]
    assert "[P1]" in kwargs["title"]


def test_legacy_path_uses_p0_title_when_alerts_contain_p0():
    """reviewer P1.2 采纳: legacy path 不再 hardcode [P1], 走 _max_severity 自动提取.

    Bug 修: 原 hardcoded `[P1]` 让 P0 alerts silent 标 P1 屏蔽运维 (flag 回滚后真发钉钉).
    """
    with (
        patch.object(dq_mod.settings, "DINGTALK_WEBHOOK_URL", "https://oapi.test"),
        patch.object(dq_mod.dingtalk, "send_markdown_sync", return_value=True) as mock_send,
    ):
        dq_mod._send_alert_via_legacy_dingtalk(
            ["[P0] critical issue", "[P1] minor"], date(2026, 4, 29)
        )

    title = mock_send.call_args.kwargs["title"]
    assert "[P0]" in title, f"P0 alerts 必标 [P0] title (P1.2 fix), got: {title}"


def test_build_alert_content_uses_utc_timestamp():
    """reviewer P2 采纳: 内容时间戳 UTC tz-aware (铁律 41), 显式标 ' UTC'."""
    content = dq_mod._build_alert_content(["[P1] x"], date(2026, 4, 29))
    assert " UTC" in content, f"巡检时间必含 UTC 标识 (铁律 41), got: {content}"


def test_get_rules_engine_caches_result():
    """reviewer P2 采纳: lru_cache 防 17 scripts 每次 fire 重复 yaml I/O."""
    # 清缓存
    dq_mod._get_rules_engine.cache_clear()

    with patch(
        "qm_platform.observability.AlertRulesEngine.from_yaml"
    ) as mock_from_yaml:
        mock_from_yaml.return_value = MagicMock()

        # 多次调用
        engine1 = dq_mod._get_rules_engine()
        engine2 = dq_mod._get_rules_engine()
        engine3 = dq_mod._get_rules_engine()

        # from_yaml 仅调一次 (cache hit)
        assert mock_from_yaml.call_count == 1
        assert engine1 is engine2 is engine3


# ─────────────────────────── run_checks AlertDispatchError 集成 (P1.1) ───────────────────────────


def test_run_checks_alert_dispatch_error_does_not_block_db_write_or_exit_code_1(
    tmp_path,
):
    """reviewer P1.1 采纳: AlertDispatchError 单 catch, write_db_alert 仍走, exit_code=1."""
    from argparse import Namespace

    args = Namespace(date="2026-04-29", dry_run=False)

    # mock 全链路
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with (
        patch.object(dq_mod, "get_connection", return_value=mock_conn),
        patch.object(dq_mod, "send_dingtalk_alert") as mock_send,
        patch.object(dq_mod, "write_db_alert") as mock_write_db,
        patch.object(
            dq_mod, "check_future_dates", return_value=["[P0] critical"]
        ),
        patch.object(dq_mod, "check_row_counts", return_value=[]),
        patch.object(dq_mod, "check_null_ratios", return_value=[]),
        patch.object(dq_mod, "check_latest_dates", return_value=[]),
    ):
        # send_dingtalk_alert raise AlertDispatchError
        mock_send.side_effect = AlertDispatchError("All channels failed")

        exit_code = dq_mod.run_checks(args)

    # P1.1 验证三点:
    # 1. AlertDispatchError 被 catch (run_checks 不传播 exit=2)
    assert exit_code == 1, (
        f"exit_code=1 反映'发现 issue'与脚本异常 (=2) 区分, got: {exit_code}"
    )
    # 2. write_db_alert 仍调用 (审计留底)
    mock_write_db.assert_called_once()
    # 3. send_dingtalk_alert 被尝试
    mock_send.assert_called_once()


# ─────────────────────────── _build_alert_content (shared) ───────────────────────────


def test_build_alert_content_format():
    content = dq_mod._build_alert_content(
        ["[P0] table empty", "[P1] lag 2 days"], date(2026, 4, 29)
    )
    assert "数据质量巡检告警 2026-04-29" in content
    assert "1. [P0] table empty" in content
    assert "2. [P1] lag 2 days" in content
    assert "巡检时间:" in content
