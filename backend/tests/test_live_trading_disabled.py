"""Live Trading guard + Beat pause tests — T1 sprint 链路停止 PR.

防真金风险 (LIVE_TRADING_DISABLED 双因素 OVERRIDE) + 防钉钉刷屏 (Beat 风控任务暂停).

铁律: 33 (fail-loud) / 34 (single source via settings) / 40 (baseline 不增 fail) /
      X2 候选 (真金硬开关, ADR-022 待写归属).

测试覆盖:
  TestGuardBlocking — LIVE_TRADING_DISABLED=true 阻断
  TestOverrideHardening1DoubleFactor — OVERRIDE 双因素 (FLAG + REASON)
  TestOverrideBypassWithAudit — bypass 触发 DingTalk P0 + logger audit
  TestPaperBrokerUnaffected — paper_broker 物理隔离
  TestBrokerQmtGuardSAST — MiniQMTBroker.place_order + cancel_order guard 落位
  TestBeatRiskTasksPaused — risk Beat 已暂停
  TestSettingsDefault — fail-secure 默认 True
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.exceptions import LiveTradingDisabledError
from app.security.live_trading_guard import assert_live_trading_allowed

_BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_override_env(monkeypatch):
    """每 test 清 OVERRIDE env, 防 cross-test 污染."""
    monkeypatch.delenv("LIVE_TRADING_FORCE_OVERRIDE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_OVERRIDE_REASON", raising=False)


class TestGuardBlocking:
    """LIVE_TRADING_DISABLED=true + 无 OVERRIDE → 必 raise."""

    def test_override_disabled_raises(self, monkeypatch):
        """无 OVERRIDE → raise + 错误信息含修法提示."""
        monkeypatch.setattr(
            "app.security.live_trading_guard.settings.LIVE_TRADING_DISABLED", True
        )
        with pytest.raises(LiveTradingDisabledError) as exc:
            assert_live_trading_allowed(operation="place_order", code="600519.SH")
        msg = str(exc.value)
        assert "place_order" in msg
        assert "600519.SH" in msg
        assert "LIVE_TRADING_FORCE_OVERRIDE" in msg
        assert "LIVE_TRADING_OVERRIDE_REASON" in msg

    def test_disabled_false_passes(self, monkeypatch):
        """LIVE_TRADING_DISABLED=False → 直接放行 (向后兼容路径)."""
        monkeypatch.setattr(
            "app.security.live_trading_guard.settings.LIVE_TRADING_DISABLED", False
        )
        # no raise expected
        assert_live_trading_allowed(operation="place_order", code="600519.SH")


class TestOverrideHardening1DoubleFactor:
    """加固 1 双因素: OVERRIDE=1 单独不够, 必须配 REASON 非空."""

    def test_override_without_reason_raises(self, monkeypatch):
        """OVERRIDE=1 + REASON 空 → raise (REASON 缺失)."""
        monkeypatch.setattr(
            "app.security.live_trading_guard.settings.LIVE_TRADING_DISABLED", True
        )
        monkeypatch.setenv("LIVE_TRADING_FORCE_OVERRIDE", "1")
        # REASON 不设
        with pytest.raises(LiveTradingDisabledError) as exc:
            assert_live_trading_allowed(operation="place_order")
        msg_lower = str(exc.value).lower()
        assert "reason" in msg_lower
        assert "empty" in msg_lower or "explicit" in msg_lower

    def test_override_with_whitespace_only_reason_raises(self, monkeypatch):
        """边界: REASON='   ' (全空格) → strip 后空 → raise."""
        monkeypatch.setattr(
            "app.security.live_trading_guard.settings.LIVE_TRADING_DISABLED", True
        )
        monkeypatch.setenv("LIVE_TRADING_FORCE_OVERRIDE", "1")
        monkeypatch.setenv("LIVE_TRADING_OVERRIDE_REASON", "   ")
        with pytest.raises(LiveTradingDisabledError):
            assert_live_trading_allowed(operation="place_order")

    def test_override_flag_zero_with_reason_still_raises(self, monkeypatch):
        """OVERRIDE=0 + REASON 设 → 仍 raise (FLAG 必精确 == '1')."""
        monkeypatch.setattr(
            "app.security.live_trading_guard.settings.LIVE_TRADING_DISABLED", True
        )
        monkeypatch.setenv("LIVE_TRADING_FORCE_OVERRIDE", "0")
        monkeypatch.setenv("LIVE_TRADING_OVERRIDE_REASON", "test reason")
        with pytest.raises(LiveTradingDisabledError):
            assert_live_trading_allowed(operation="place_order")


class TestOverrideBypassWithAudit:
    """加固 2 审计: bypass 时 DingTalk P0 + audit log."""

    def test_override_with_reason_bypasses(self, monkeypatch):
        """OVERRIDE=1 + REASON 非空 → bypass (no raise) + DingTalk P0 推送."""
        monkeypatch.setattr(
            "app.security.live_trading_guard.settings.LIVE_TRADING_DISABLED", True
        )
        monkeypatch.setenv("LIVE_TRADING_FORCE_OVERRIDE", "1")
        monkeypatch.setenv(
            "LIVE_TRADING_OVERRIDE_REASON", "Emergency close 600519.SH after gap-down",
        )

        with patch("app.security.live_trading_guard.send_alert") as mock_send:
            assert_live_trading_allowed(
                operation="place_order", code="600519.SH"
            )  # no raise

            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["level"] == "P0"
            title = call_kwargs["title"]
            assert "OVERRIDE" in title
            assert "place_order" in title
            content = call_kwargs["content"]
            assert "600519.SH" in content
            assert "Emergency close" in content

    def test_override_logs_audit_trail(self, monkeypatch, caplog):
        """bypass 时 logger.warning audit 含 timestamp / reason / script / operation."""
        monkeypatch.setattr(
            "app.security.live_trading_guard.settings.LIVE_TRADING_DISABLED", True
        )
        monkeypatch.setenv("LIVE_TRADING_FORCE_OVERRIDE", "1")
        monkeypatch.setenv("LIVE_TRADING_OVERRIDE_REASON", "T1 sprint emergency test")

        with (
            patch("app.security.live_trading_guard.send_alert"),
            caplog.at_level("WARNING", logger="app.security.live_trading_guard"),
        ):
            assert_live_trading_allowed(operation="cancel_order", code="000001.SZ")

        matched = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "OVERRIDE bypass" in r.getMessage()
        ]
        assert matched, (
            f"Expected OVERRIDE bypass warning, got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )
        record = matched[0]
        assert hasattr(record, "audit"), "audit extra missing on log record"
        audit = record.audit
        assert audit["operation"] == "cancel_order"
        assert audit["code"] == "000001.SZ"
        assert audit["reason"] == "T1 sprint emergency test"
        assert "timestamp_utc" in audit
        assert "script" in audit

    def test_override_dingtalk_failure_does_not_block_bypass(self, monkeypatch):
        """钉钉发送 raise → bypass 仍继续 (silent_ok 防紧急清仓被网络阻断).

        防 DingTalk 不可达时 OVERRIDE 也 fail = 真紧急时 user 自己也救不了.
        审计 log 已写, DingTalk fail 是次要 channel. 沿用铁律 33-d silent_ok 注释模式.
        """
        monkeypatch.setattr(
            "app.security.live_trading_guard.settings.LIVE_TRADING_DISABLED", True
        )
        monkeypatch.setenv("LIVE_TRADING_FORCE_OVERRIDE", "1")
        monkeypatch.setenv("LIVE_TRADING_OVERRIDE_REASON", "Network failure test")

        with patch(
            "app.security.live_trading_guard.send_alert",
            side_effect=RuntimeError("DingTalk unreachable"),
        ):
            # 钉钉失败但 bypass 仍 PASS (no raise from assert_live_trading_allowed)
            assert_live_trading_allowed(operation="place_order")


class TestPaperBrokerUnaffected:
    """paper_broker.py 物理隔离 — 不 import 不调 guard."""

    def test_paper_broker_no_guard_import(self):
        """SAST: paper_broker.py 源码不 import live_trading_guard / 不调 assert."""
        src = (_BACKEND_DIR / "engines" / "paper_broker.py").read_text(
            encoding="utf-8"
        )
        assert "live_trading_guard" not in src, (
            "paper_broker.py 不应 import live_trading_guard (物理隔离, "
            "guard 只挂 MiniQMTBroker.place_order/cancel_order)"
        )
        assert "assert_live_trading_allowed" not in src


class TestBrokerQmtGuardSAST:
    """SAST: MiniQMTBroker.place_order + cancel_order 必含 guard 调用."""

    def test_broker_qmt_imports_guard(self):
        src = (_BACKEND_DIR / "engines" / "broker_qmt.py").read_text(encoding="utf-8")
        assert (
            "from app.security.live_trading_guard import" in src
            or "import app.security.live_trading_guard" in src
        ), "broker_qmt.py 必 import live_trading_guard"

    def test_broker_qmt_place_and_cancel_call_guard(self):
        """place_order + cancel_order 各 1 次 (≥ 2 次出现)."""
        src = (_BACKEND_DIR / "engines" / "broker_qmt.py").read_text(encoding="utf-8")
        count = src.count("assert_live_trading_allowed")
        assert count >= 2, (
            f"assert_live_trading_allowed 至少 2 处 (place_order + cancel_order), "
            f"实际 {count}"
        )


class TestBeatRiskTasksPaused:
    """Beat schedule 必不再含 risk-daily-check / intraday-risk-check (T1 暂停)."""

    def test_risk_beat_tasks_not_active(self):
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE

        assert "risk-daily-check" not in CELERY_BEAT_SCHEDULE, (
            "risk-daily-check 应在 T1 sprint 暂停 (注释), "
            "还原见 docs/audit/link_paused_2026_04_29.md"
        )
        assert "intraday-risk-check" not in CELERY_BEAT_SCHEDULE, (
            "intraday-risk-check 应在 T1 sprint 暂停 (注释), "
            "还原见 docs/audit/link_paused_2026_04_29.md"
        )
        # 其他 Beat 任务保留 (smoke 验证调度结构没被误删)
        assert "outbox-publisher-tick" in CELERY_BEAT_SCHEDULE
        assert "daily-quality-report" in CELERY_BEAT_SCHEDULE


class TestSettingsDefault:
    """LIVE_TRADING_DISABLED 默认 True (fail-secure 真金保护默认)."""

    def test_settings_default_is_true(self):
        from app.config import Settings

        field = Settings.model_fields.get("LIVE_TRADING_DISABLED")
        assert field is not None, "Settings 必含 LIVE_TRADING_DISABLED 字段"
        assert field.default is True, (
            f"LIVE_TRADING_DISABLED 默认必 True (fail-secure 真金保护). "
            f"实际默认值: {field.default}"
        )
