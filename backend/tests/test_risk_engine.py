"""L1 unit tests for PlatformRiskEngine (orchestration, mocked IO).

覆盖 MVP 3.1 批 1 PR 2 Engine 核心契约:
  - register dedup by rule_id
  - build_context primary/fallback 切换
  - run 聚合多规则 RuleResult + rule 异常隔离
  - execute 分发 (sell → broker / alert_only / bypass) + risk_event_log INSERT + notify
  - _root_rule_id 反查 (pms_l1 → pms)
"""
from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from backend.platform._types import Severity
from backend.platform.risk.engine import PlatformRiskEngine, _root_rule_id
from backend.platform.risk.interface import (
    Position,
    PositionSourceError,
    RiskContext,
    RiskRule,
    RuleResult,
)

# ---------- Helpers ----------


def _pos(code="600519.SH", shares=100, entry=100.0, peak=120.0, current=110.0) -> Position:
    return Position(code=code, shares=shares, entry_price=entry, peak_price=peak, current_price=current)


def _ctx(positions=None) -> RiskContext:
    return RiskContext(
        strategy_id="00000000-0000-0000-0000-000000000001",
        execution_mode="paper",
        timestamp=datetime.now(UTC),
        positions=tuple(positions or []),
        portfolio_nav=1_000_000.0,
        prev_close_nav=None,
    )


class _SellRule(RiskRule):
    rule_id = "test_sell"
    severity = Severity.P1
    action = "sell"

    def __init__(self, results: list[RuleResult] | None = None):
        self._results = results or []

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        return self._results


class _AlertRule(RiskRule):
    rule_id = "test_alert"
    severity = Severity.P2
    action = "alert_only"

    def __init__(self, results: list[RuleResult] | None = None):
        self._results = results or []

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        return self._results


class _RaisingRule(RiskRule):
    rule_id = "test_raising"
    severity = Severity.P1
    action = "sell"

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        raise RuntimeError("intentional test error")


def _mock_conn() -> MagicMock:
    """Build psycopg2 conn + cursor context manager mock."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = False
    return mock_conn


def _conn_factory(mock_conn: MagicMock):
    """Return a factory that yields mock_conn as context manager."""
    @contextlib.contextmanager
    def factory():
        yield mock_conn
    return factory


# ---------- Tests ----------


class TestEngineRegister:
    def test_register_new_rule(self):
        engine = PlatformRiskEngine(
            primary_source=MagicMock(), fallback_source=MagicMock(),
            broker=MagicMock(), notifier=MagicMock(),
            price_reader=MagicMock(), conn_factory=lambda: _mock_conn(),
        )
        rule = _SellRule()
        engine.register(rule)
        assert engine.registered_rules == ["test_sell"]

    def test_register_duplicate_raises(self):
        engine = PlatformRiskEngine(
            primary_source=MagicMock(), fallback_source=MagicMock(),
            broker=MagicMock(), notifier=MagicMock(),
            price_reader=MagicMock(), conn_factory=lambda: _mock_conn(),
        )
        engine.register(_SellRule())
        with pytest.raises(ValueError, match="already registered"):
            engine.register(_SellRule())


class TestEngineBuildContext:
    def test_primary_succeeds(self):
        primary = MagicMock()
        primary.load.return_value = [_pos()]
        fallback = MagicMock()
        price_reader = MagicMock()
        price_reader.get_nav.return_value = {"total_value": 999_000.0}

        engine = PlatformRiskEngine(
            primary_source=primary, fallback_source=fallback,
            broker=MagicMock(), notifier=MagicMock(),
            price_reader=price_reader, conn_factory=lambda: _mock_conn(),
        )
        ctx = engine.build_context(
            strategy_id="00000000-0000-0000-0000-000000000001",
            execution_mode="paper",
        )
        assert len(ctx.positions) == 1
        assert ctx.portfolio_nav == 999_000.0
        fallback.load.assert_not_called()

    def test_primary_fails_fallback_used(self):
        primary = MagicMock()
        primary.load.side_effect = PositionSourceError("Redis disconnected")
        fallback = MagicMock()
        fallback.load.return_value = [_pos()]
        price_reader = MagicMock()
        price_reader.get_nav.return_value = {"total_value": 500_000.0}
        notifier = MagicMock()

        engine = PlatformRiskEngine(
            primary_source=primary, fallback_source=fallback,
            broker=MagicMock(), notifier=notifier,
            price_reader=price_reader, conn_factory=lambda: _mock_conn(),
        )
        ctx = engine.build_context(
            strategy_id="00000000-0000-0000-0000-000000000001",
            execution_mode="live",
        )
        assert len(ctx.positions) == 1
        fallback.load.assert_called_once()
        notifier.send.assert_called_once()  # P1 fallback alert 发过

    def test_both_fail_raises(self):
        primary = MagicMock()
        primary.load.side_effect = PositionSourceError("primary fail")
        fallback = MagicMock()
        fallback.load.side_effect = PositionSourceError("fallback also fails")

        engine = PlatformRiskEngine(
            primary_source=primary, fallback_source=fallback,
            broker=MagicMock(), notifier=MagicMock(),
            price_reader=MagicMock(), conn_factory=lambda: _mock_conn(),
        )
        with pytest.raises(PositionSourceError, match="fallback also fails"):
            engine.build_context(
                strategy_id="00000000-0000-0000-0000-000000000001",
                execution_mode="paper",
            )

    def test_nav_unavailable_uses_approx(self):
        """price_reader.get_nav 返 None → 用 sum(shares*current) 估算."""
        primary = MagicMock()
        primary.load.return_value = [_pos(shares=200, current=110.0)]
        price_reader = MagicMock()
        price_reader.get_nav.return_value = None

        engine = PlatformRiskEngine(
            primary_source=primary, fallback_source=MagicMock(),
            broker=MagicMock(), notifier=MagicMock(),
            price_reader=price_reader, conn_factory=lambda: _mock_conn(),
        )
        ctx = engine.build_context(strategy_id="x", execution_mode="paper")
        assert ctx.portfolio_nav == 200 * 110.0


class TestEngineRun:
    def test_run_aggregates_multiple_rules(self):
        engine = PlatformRiskEngine(
            primary_source=MagicMock(), fallback_source=MagicMock(),
            broker=MagicMock(), notifier=MagicMock(),
            price_reader=MagicMock(), conn_factory=lambda: _mock_conn(),
        )
        engine.register(_SellRule(results=[
            RuleResult(rule_id="test_sell", code="A.SH", shares=100, reason="r", metrics={}),
        ]))
        engine.register(_AlertRule(results=[
            RuleResult(rule_id="test_alert", code="", shares=0, reason="a", metrics={}),
        ]))

        results = engine.run(_ctx())
        assert len(results) == 2
        ids = {r.rule_id for r in results}
        assert ids == {"test_sell", "test_alert"}

    def test_rule_exception_isolated(self):
        """一个 rule raise 不影响其他 rule."""
        engine = PlatformRiskEngine(
            primary_source=MagicMock(), fallback_source=MagicMock(),
            broker=MagicMock(), notifier=MagicMock(),
            price_reader=MagicMock(), conn_factory=lambda: _mock_conn(),
        )
        engine.register(_RaisingRule())
        engine.register(_AlertRule(results=[
            RuleResult(rule_id="test_alert", code="", shares=0, reason="a", metrics={}),
        ]))

        results = engine.run(_ctx())
        # RaisingRule skipped, AlertRule results still emitted
        assert len(results) == 1
        assert results[0].rule_id == "test_alert"


class TestEngineExecute:
    def test_sell_action_calls_broker(self):
        broker = MagicMock()
        broker.sell.return_value = {"status": "filled", "qty": 100}
        mock_conn = _mock_conn()

        engine = PlatformRiskEngine(
            primary_source=MagicMock(), fallback_source=MagicMock(),
            broker=broker, notifier=MagicMock(),
            price_reader=MagicMock(), conn_factory=_conn_factory(mock_conn),
        )
        engine.register(_SellRule())

        result = RuleResult(
            rule_id="test_sell", code="600519.SH", shares=100,
            reason="trigger", metrics={"level": 1.0},
        )
        engine.execute([result], _ctx())

        broker.sell.assert_called_once_with(
            code="600519.SH", shares=100,
            reason="risk:test_sell", timeout=5.0,
        )
        # risk_event_log INSERT happened
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        assert mock_cursor.execute.called
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO risk_event_log" in sql

    def test_alert_only_action_no_broker_call(self):
        broker = MagicMock()
        notifier = MagicMock()
        mock_conn = _mock_conn()

        engine = PlatformRiskEngine(
            primary_source=MagicMock(), fallback_source=MagicMock(),
            broker=broker, notifier=notifier,
            price_reader=MagicMock(), conn_factory=_conn_factory(mock_conn),
        )
        engine.register(_AlertRule())

        result = RuleResult(
            rule_id="test_alert", code="", shares=0,
            reason="portfolio drop", metrics={},
        )
        engine.execute([result], _ctx())

        broker.sell.assert_not_called()
        notifier.send.assert_called_once()

    def test_broker_failure_not_raising_logs(self):
        """broker.sell raise 不阻塞其他 result (log + action_result['status']='sell_failed')."""
        broker = MagicMock()
        broker.sell.side_effect = RuntimeError("QMT timeout")
        mock_conn = _mock_conn()

        engine = PlatformRiskEngine(
            primary_source=MagicMock(), fallback_source=MagicMock(),
            broker=broker, notifier=MagicMock(),
            price_reader=MagicMock(), conn_factory=_conn_factory(mock_conn),
        )
        engine.register(_SellRule())

        result = RuleResult(
            rule_id="test_sell", code="600519.SH", shares=100,
            reason="trigger", metrics={},
        )
        # 不 raise (内部捕)
        engine.execute([result], _ctx())

        # INSERT 仍发生, action_result 记录 sell_failed
        mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
        assert mock_cursor.execute.called
        call_args = mock_cursor.execute.call_args[0][1]
        # call_args[9] is json.dumps(action_result). Verify 'sell_failed' inside.
        assert "sell_failed" in call_args[9]


class TestRootRuleIdMapping:
    """_root_rule_id 反查约定."""

    @pytest.mark.parametrize(
        ("triggered_id", "expected_root"),
        [
            ("pms_l1", "pms"),
            ("pms_l2", "pms"),
            ("pms_l3", "pms"),
            ("intraday_portfolio_drop_5pct", "intraday_portfolio_drop_5pct"),
            ("cb_l2", "cb_l2"),  # 批 3 adapter 保留原 id
        ],
    )
    def test_pms_l_prefix_reverse(self, triggered_id: str, expected_root: str):
        assert _root_rule_id(triggered_id) == expected_root
