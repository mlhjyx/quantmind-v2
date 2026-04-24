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

    @patch("app.services.risk_wiring.get_qmt_client")
    @patch("app.services.risk_wiring.get_sync_conn")
    def test_factory_accepts_extra_rules(
        self, mock_get_conn: MagicMock, mock_get_qmt: MagicMock
    ):
        """reviewer P2-1 采纳 (architect): extra_rules 为批 2/3 铺路."""
        mock_get_qmt.return_value = MagicMock()
        mock_get_conn.return_value = MagicMock()

        from dataclasses import dataclass

        from app.services.risk_wiring import build_risk_engine
        from backend.platform._types import Severity
        from backend.platform.risk import RiskRule

        @dataclass
        class _DummyRule(RiskRule):
            rule_id = "dummy_test"
            severity = Severity.P2
            action = "alert_only"

            def evaluate(self, context):
                return []

        engine = build_risk_engine(extra_rules=[_DummyRule()])
        assert engine.registered_rules == ["pms", "dummy_test"]

    @patch("app.services.risk_wiring.get_qmt_client")
    @patch("app.services.risk_wiring.get_sync_conn")
    def test_factory_extra_rules_none_keeps_pms_only(
        self, mock_get_conn: MagicMock, mock_get_qmt: MagicMock
    ):
        mock_get_qmt.return_value = MagicMock()
        mock_get_conn.return_value = MagicMock()

        from app.services.risk_wiring import build_risk_engine

        engine = build_risk_engine(extra_rules=None)
        assert engine.registered_rules == ["pms"]


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


# ══════════════════════════════════════════════════════════════════════════
# MVP 3.1 批 2 PR 2 (Session 30) — Intraday factory + Dedup + NAV helper
# ══════════════════════════════════════════════════════════════════════════


class TestBuildIntradayRiskEngine:
    @patch("app.services.risk_wiring.get_qmt_client")
    @patch("app.services.risk_wiring.get_sync_conn")
    def test_factory_registers_4_intraday_rules(
        self, mock_get_conn: MagicMock, mock_get_qmt: MagicMock
    ):
        """批 2 factory 注册 4 条 intraday 规则 (不含 PMS)."""
        mock_get_qmt.return_value = MagicMock()
        mock_get_conn.return_value = MagicMock()

        from app.services.risk_wiring import build_intraday_risk_engine

        engine = build_intraday_risk_engine()
        assert engine.registered_rules == [
            "intraday_portfolio_drop_3pct",
            "intraday_portfolio_drop_5pct",
            "intraday_portfolio_drop_8pct",
            "qmt_disconnect",
        ]

    @patch("app.services.risk_wiring.get_qmt_client")
    @patch("app.services.risk_wiring.get_sync_conn")
    def test_intraday_factory_does_not_include_pms(
        self, mock_get_conn: MagicMock, mock_get_qmt: MagicMock
    ):
        """intraday engine 不注册 PMSRule (PMS 归批 1 daily 14:30 专属, 避双告警)."""
        mock_get_qmt.return_value = MagicMock()
        mock_get_conn.return_value = MagicMock()

        from app.services.risk_wiring import build_intraday_risk_engine

        engine = build_intraday_risk_engine()
        assert "pms" not in engine.registered_rules

    @patch("app.services.risk_wiring.get_qmt_client")
    @patch("app.services.risk_wiring.get_sync_conn")
    def test_intraday_factory_accepts_extra_rules(
        self, mock_get_conn: MagicMock, mock_get_qmt: MagicMock
    ):
        """extra_rules 为批 3 CB adapter 铺路."""
        mock_get_qmt.return_value = MagicMock()
        mock_get_conn.return_value = MagicMock()

        from app.services.risk_wiring import build_intraday_risk_engine
        from backend.platform._types import Severity
        from backend.platform.risk import RiskRule

        class _TestExtra(RiskRule):
            rule_id = "test_extra_intraday"
            severity = Severity.P2
            action = "alert_only"

            def evaluate(self, context):
                return []

        engine = build_intraday_risk_engine(extra_rules=[_TestExtra()])
        assert "test_extra_intraday" in engine.registered_rules
        assert len(engine.registered_rules) == 5  # 4 + 1 extra


class TestIntradayAlertDedup:
    def _mock_redis(self, exists_return=False):
        redis_mock = MagicMock()
        redis_mock.exists.return_value = exists_return
        return redis_mock

    def test_first_call_should_alert(self):
        from app.services.risk_wiring import IntradayAlertDedup

        redis_mock = self._mock_redis(exists_return=False)
        dedup = IntradayAlertDedup(redis_client=redis_mock)
        assert dedup.should_alert("rule_x", "strat_a", "paper") is True

    def test_second_call_blocked_by_dedup(self):
        from app.services.risk_wiring import IntradayAlertDedup

        redis_mock = self._mock_redis(exists_return=True)
        dedup = IntradayAlertDedup(redis_client=redis_mock)
        assert dedup.should_alert("rule_x", "strat_a", "paper") is False

    def test_mark_alerted_calls_setex(self):
        from app.services.risk_wiring import IntradayAlertDedup

        redis_mock = self._mock_redis()
        dedup = IntradayAlertDedup(redis_client=redis_mock)
        dedup.mark_alerted("rule_x", "strat_a", "paper")
        assert redis_mock.setex.called
        call_args = redis_mock.setex.call_args
        assert call_args[0][1] == 86400  # TTL 24h
        assert "rule_x" in call_args[0][0]  # key 含 rule_id
        assert "strat_a" in call_args[0][0]  # key 含 strategy_id
        assert "paper" in call_args[0][0]  # key 含 execution_mode

    def test_key_isolation_by_rule_strategy_mode(self):
        """不同 rule/strategy/mode 组合 key 不共用."""
        from app.services.risk_wiring import IntradayAlertDedup

        k1 = IntradayAlertDedup._build_key("r1", "s1", "paper")
        k2 = IntradayAlertDedup._build_key("r2", "s1", "paper")
        k3 = IntradayAlertDedup._build_key("r1", "s2", "paper")
        k4 = IntradayAlertDedup._build_key("r1", "s1", "live")
        assert len({k1, k2, k3, k4}) == 4

    def test_should_alert_fail_open_on_redis_error(self):
        """Redis 异常 fail-open (宁可误告警不漏告警)."""
        from app.services.risk_wiring import IntradayAlertDedup

        redis_mock = MagicMock()
        redis_mock.exists.side_effect = RuntimeError("Redis down")
        dedup = IntradayAlertDedup(redis_client=redis_mock)
        assert dedup.should_alert("rule_x", "strat_a", "paper") is True

    def test_mark_alerted_silent_on_redis_error(self):
        """Redis 异常 dedup mark 失败 silent (不阻塞主路径)."""
        from app.services.risk_wiring import IntradayAlertDedup

        redis_mock = MagicMock()
        redis_mock.setex.side_effect = RuntimeError("Redis down")
        dedup = IntradayAlertDedup(redis_client=redis_mock)
        # 不 raise = PASS
        dedup.mark_alerted("rule_x", "strat_a", "paper")

    def test_key_uses_china_timezone_not_os_local(self):
        """reviewer P2 采纳 (code): 铁律 41 timezone — dedup key 日期用北京时间.

        锚定契约: key 日期部分是 Asia/Shanghai, 防 OS 时区漂移致日边界错.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.services.risk_wiring import IntradayAlertDedup

        key = IntradayAlertDedup._build_key("r", "s", "paper")
        today_cn = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        assert today_cn in key, f"key {key} does not contain China tz date {today_cn}"


class TestLoadPrevCloseNav:
    def test_returns_nav_when_row_exists(self):
        from app.services.risk_wiring import _load_prev_close_nav

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (987654.32,)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False

        result = _load_prev_close_nav(mock_conn, "strat_a", "paper")
        assert result == 987654.32

    def test_returns_none_when_no_row(self):
        from app.services.risk_wiring import _load_prev_close_nav

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False

        result = _load_prev_close_nav(mock_conn, "strat_a", "paper")
        assert result is None

    def test_returns_none_when_nav_is_zero(self):
        """NAV <= 0 异常数据 → None (intraday drop rules silent skip)."""
        from app.services.risk_wiring import _load_prev_close_nav

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0.0,)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False

        result = _load_prev_close_nav(mock_conn, "strat_a", "paper")
        assert result is None

    def test_returns_none_on_db_error(self):
        """DB 异常 fallback None (读路径 fallback 允许, 铁律 33-c)."""
        from app.services.risk_wiring import _load_prev_close_nav

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = RuntimeError("DB timeout")

        result = _load_prev_close_nav(mock_conn, "strat_a", "paper")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
