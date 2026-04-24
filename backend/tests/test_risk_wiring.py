"""L1 unit tests for backend/app/services/risk_wiring.py (MVP 3.1 批 1 PR 3).

覆盖:
  - LoggingSellBroker.sell 符合 BrokerProtocol 契约 + 返 status='logged_only' (批 1 占位)
  - DingTalkRiskNotifier.send 调用 send_alert 时 severity 映射正确 + 失败 silent
  - build_pms_thresholds 从 settings 读 L1/L2/L3 三层
  - build_risk_engine 工厂注册 PMSRule + primary/fallback source 正确接线
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.risk_wiring import (
    DingTalkRiskNotifier,
    LoggingSellBroker,
    build_pms_thresholds,
)
from backend.platform.risk.rules.pms import PMSThreshold

# ---------- LoggingSellBroker ----------


class TestLoggingSellBroker:
    def test_sell_returns_logged_only_status(self):
        broker = LoggingSellBroker()
        result = broker.sell(code="600519.SH", shares=100, reason="test")
        assert result["status"] == "logged_only"
        assert result["code"] == "600519.SH"
        assert result["shares"] == 100
        assert "note" in result

    def test_sell_ignores_timeout_param(self):
        """batch 1 placeholder 不 IO, timeout 无语义."""
        broker = LoggingSellBroker()
        result = broker.sell(code="A", shares=1, reason="r", timeout=99.0)
        assert result["status"] == "logged_only"


# ---------- DingTalkRiskNotifier ----------


class TestDingTalkRiskNotifier:
    @patch("app.services.risk_wiring.send_alert")
    def test_severity_maps_p0(self, mock_send: MagicMock):
        notifier = DingTalkRiskNotifier()
        notifier.send(title="t", text="x", severity="p0")
        assert mock_send.called
        assert mock_send.call_args.kwargs["level"] == "P0"

    @patch("app.services.risk_wiring.send_alert")
    def test_severity_maps_p1(self, mock_send: MagicMock):
        notifier = DingTalkRiskNotifier()
        notifier.send(title="t", text="x", severity="p1")
        assert mock_send.call_args.kwargs["level"] == "P1"

    @patch("app.services.risk_wiring.send_alert")
    def test_severity_warning_fallback_to_p1(self, mock_send: MagicMock):
        """engine _load_positions fallback 告警用 severity='warning'."""
        notifier = DingTalkRiskNotifier()
        notifier.send(title="t", text="x", severity="warning")
        assert mock_send.call_args.kwargs["level"] == "P1"

    @patch("app.services.risk_wiring.send_alert")
    def test_unknown_severity_defaults_to_p1(self, mock_send: MagicMock):
        notifier = DingTalkRiskNotifier()
        notifier.send(title="t", text="x", severity="unknown_xyz")
        assert mock_send.call_args.kwargs["level"] == "P1"

    @patch("app.services.risk_wiring.send_alert")
    def test_send_failure_silent(self, mock_send: MagicMock):
        """send_alert raise 时 notifier 不 propagate (Engine 主路径不能被告警失败阻塞)."""
        mock_send.side_effect = RuntimeError("dingtalk webhook down")
        notifier = DingTalkRiskNotifier()
        # 不 raise = PASS
        notifier.send(title="t", text="x", severity="p1")


# ---------- build_pms_thresholds ----------


class TestBuildPMSThresholds:
    def test_three_levels_returned(self):
        thresholds = build_pms_thresholds()
        assert len(thresholds) == 3
        assert all(isinstance(t, PMSThreshold) for t in thresholds)
        assert [t.level for t in thresholds] == [1, 2, 3]

    def test_levels_monotonic_desc_gain(self):
        """min_gain 按 L1 ≥ L2 ≥ L3 降序 (对齐 PMSRule precondition)."""
        thresholds = build_pms_thresholds()
        assert thresholds[0].min_gain >= thresholds[1].min_gain
        assert thresholds[1].min_gain >= thresholds[2].min_gain


# ---------- build_risk_engine factory (skip live deps) ----------


class TestBuildRiskEngine:
    @patch("app.services.risk_wiring.get_qmt_client")
    @patch("app.services.risk_wiring.get_sync_conn")
    def test_factory_registers_pms_rule(
        self, mock_get_conn: MagicMock, mock_get_qmt: MagicMock
    ):
        """build_risk_engine 返 PlatformRiskEngine 已 register 单 PMSRule."""
        mock_qmt = MagicMock()
        mock_qmt.is_connected.return_value = True
        mock_qmt.get_positions.return_value = {}
        mock_qmt.get_prices.return_value = {}
        mock_qmt.get_nav.return_value = None
        mock_get_qmt.return_value = mock_qmt
        mock_get_conn.return_value = MagicMock()

        from app.services.risk_wiring import build_risk_engine

        engine = build_risk_engine()
        assert engine.registered_rules == ["pms"]

    @patch("app.services.risk_wiring.get_qmt_client")
    @patch("app.services.risk_wiring.get_sync_conn")
    def test_factory_injects_logging_broker_and_dingding(
        self, mock_get_conn: MagicMock, mock_get_qmt: MagicMock
    ):
        mock_get_qmt.return_value = MagicMock()
        mock_get_conn.return_value = MagicMock()

        from app.services.risk_wiring import build_risk_engine

        engine = build_risk_engine()
        assert isinstance(engine._broker, LoggingSellBroker)
        assert isinstance(engine._notifier, DingTalkRiskNotifier)


# ---------- PMSRule Protocol contract via risk_wiring ----------


def test_logging_sell_broker_matches_broker_protocol():
    """静态检查: LoggingSellBroker.sell 签名符合 engine.BrokerProtocol."""
    from backend.platform.risk.engine import BrokerProtocol

    broker: BrokerProtocol = LoggingSellBroker()  # mypy structural check
    _ = broker.sell(code="x", shares=1, reason="r")


def test_dingding_notifier_matches_notifier_protocol():
    from backend.platform.risk.engine import NotifierProtocol

    notifier: NotifierProtocol = DingTalkRiskNotifier()  # mypy structural check
    with patch("app.services.risk_wiring.send_alert"):
        notifier.send(title="t", text="x", severity="p1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
