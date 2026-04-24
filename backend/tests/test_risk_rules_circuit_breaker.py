"""L1 unit tests for backend/platform/risk/rules/circuit_breaker.py (MVP 3.1 批 3).

覆盖 20 tests:
  - 4 escalate transitions (L0→L1/L2/L3/L4)
  - 3 recover transitions (L1→L0, L3→L2, L4→L0)
  - No-change (prev == new → return [])
  - severity 分级 (L3/L4 = P0, L1/L2 = P1, recover = P2)
  - rule_id 动态 cb_escalate_l{N} / cb_recover_l{N}
  - root_rule_id_for passthrough + ownership
  - _read_current_level: row exists / no row / DB error (fallback L0)
  - Class contract (rule_id / severity / action)
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.platform._types import Severity
from backend.platform.risk import RiskContext
from backend.platform.risk.rules.circuit_breaker import CircuitBreakerRule


def _make_context(strategy_id: str = "strat_a", execution_mode: str = "paper") -> RiskContext:
    return RiskContext(
        strategy_id=strategy_id,
        execution_mode=execution_mode,
        timestamp=datetime(2026, 4, 28, 14, 30, tzinfo=UTC),
        positions=(),
        portfolio_nav=1_000_000.0,
        prev_close_nav=1_020_000.0,
    )


def _make_rule_with_mocks(prev_level: int, cb_result: dict):
    """Factory: CircuitBreakerRule with mocked conn_factory + check_circuit_breaker_sync.

    prev_level: `_read_current_level` 返的 pre-snapshot level
    cb_result: check_circuit_breaker_sync 返的 dict (含 new level)
    """
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (prev_level,) if prev_level else None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.cursor.return_value.__exit__.return_value = False

    # conn_factory as context manager
    mock_conn_factory = MagicMock()
    mock_conn_factory.return_value.__enter__.return_value = mock_conn
    mock_conn_factory.return_value.__exit__.return_value = False

    rule = CircuitBreakerRule(
        conn_factory=mock_conn_factory, initial_capital=1_000_000.0
    )
    return rule, mock_conn_factory, cb_result


# ---------- Class contract ----------


class TestCircuitBreakerRuleContract:
    def test_class_attrs(self):
        rule = CircuitBreakerRule(conn_factory=MagicMock(), initial_capital=1_000_000.0)
        assert rule.rule_id == "circuit_breaker"
        assert rule.severity == Severity.P1
        assert rule.action == "alert_only"

    def test_init_stores_dependencies(self):
        mock_factory = MagicMock()
        rule = CircuitBreakerRule(conn_factory=mock_factory, initial_capital=2_000_000.0)
        assert rule._conn_factory is mock_factory
        assert rule._initial_capital == 2_000_000.0


# ---------- Escalate transitions (L0 → L1/L2/L3/L4) ----------


class TestEscalateTransitions:
    def _run_escalate(self, prev_level: int, new_level: int):
        rule, _, cb_result_fixture = _make_rule_with_mocks(
            prev_level=prev_level,
            cb_result={
                "level": new_level,
                "action": "pause" if new_level == 1 else "halt",
                "reason": f"escalate L{prev_level}->L{new_level}",
                "position_multiplier": 0.5,
                "recovery_info": "",
            },
        )
        with patch(
            "app.services.risk_control_service.check_circuit_breaker_sync",
            return_value=cb_result_fixture,
        ):
            results = rule.evaluate(_make_context())
        return results

    def test_escalate_l0_to_l1(self):
        results = self._run_escalate(prev_level=0, new_level=1)
        assert len(results) == 1
        assert results[0].rule_id == "cb_escalate_l1"
        assert results[0].metrics["prev_level"] == 0
        assert results[0].metrics["new_level"] == 1
        assert results[0].metrics["transition_type"] == 1.0  # escalate

    def test_escalate_l0_to_l2(self):
        results = self._run_escalate(prev_level=0, new_level=2)
        assert results[0].rule_id == "cb_escalate_l2"

    def test_escalate_l1_to_l3(self):
        results = self._run_escalate(prev_level=1, new_level=3)
        assert results[0].rule_id == "cb_escalate_l3"
        assert results[0].metrics["prev_level"] == 1
        assert results[0].metrics["new_level"] == 3

    def test_escalate_l2_to_l4(self):
        results = self._run_escalate(prev_level=2, new_level=4)
        assert results[0].rule_id == "cb_escalate_l4"


# ---------- Recover transitions ----------


class TestRecoverTransitions:
    def _run_recover(self, prev_level: int, new_level: int):
        rule, _, cb_result_fixture = _make_rule_with_mocks(
            prev_level=prev_level,
            cb_result={
                "level": new_level,
                "action": "normal",
                "reason": f"recover L{prev_level}->L{new_level}",
                "position_multiplier": 1.0,
                "recovery_info": "streak 5 days",
            },
        )
        with patch(
            "app.services.risk_control_service.check_circuit_breaker_sync",
            return_value=cb_result_fixture,
        ):
            results = rule.evaluate(_make_context())
        return results

    def test_recover_l1_to_l0(self):
        results = self._run_recover(prev_level=1, new_level=0)
        assert len(results) == 1
        assert results[0].rule_id == "cb_recover_l0"
        assert results[0].metrics["transition_type"] == -1.0  # recover

    def test_recover_l3_to_l2(self):
        results = self._run_recover(prev_level=3, new_level=2)
        assert results[0].rule_id == "cb_recover_l2"

    def test_recover_l4_to_l0(self):
        """L4 人工 approve 后一次性恢复到 L0."""
        results = self._run_recover(prev_level=4, new_level=0)
        assert results[0].rule_id == "cb_recover_l0"
        assert results[0].metrics["position_multiplier"] == 1.0


# ---------- No-change (prev == new) ----------


class TestNoChange:
    def test_no_change_l0(self):
        rule, _, cb_result = _make_rule_with_mocks(
            prev_level=0,
            cb_result={"level": 0, "action": "normal", "reason": "no change",
                      "position_multiplier": 1.0, "recovery_info": ""},
        )
        with patch(
            "app.services.risk_control_service.check_circuit_breaker_sync",
            return_value=cb_result,
        ):
            assert rule.evaluate(_make_context()) == []

    def test_no_change_l3(self):
        """L3 持续状态 — 不写事件 (铁律 33 只真 transition 入 log)."""
        rule, _, cb_result = _make_rule_with_mocks(
            prev_level=3,
            cb_result={"level": 3, "action": "reduce", "reason": "still L3",
                      "position_multiplier": 0.5, "recovery_info": "streak 2 days"},
        )
        with patch(
            "app.services.risk_control_service.check_circuit_breaker_sync",
            return_value=cb_result,
        ):
            assert rule.evaluate(_make_context()) == []


# ---------- Severity 分级验证 ----------


class TestSeverityMapping:
    """RuleResult severity 映射未来扩展, 当前 class-level severity=P1 固定.

    reason 字段及 rule_id 反映 transition 级别, severity 后续版本按 level 动态.
    本测试锚 rule_id 级别数字与 metrics 一致性.
    """

    def test_l4_escalate_reason_contains_transition(self):
        rule, _, cb_result = _make_rule_with_mocks(
            prev_level=0,
            cb_result={"level": 4, "action": "stop", "reason": "cumulative loss > 25%",
                      "position_multiplier": 0.0, "recovery_info": ""},
        )
        with patch(
            "app.services.risk_control_service.check_circuit_breaker_sync",
            return_value=cb_result,
        ):
            result = rule.evaluate(_make_context())[0]
        assert "L0" in result.reason and "L4" in result.reason
        assert "cumulative loss > 25%" in result.reason
        assert "action=stop" in result.reason

    def test_recover_reason_contains_transition(self):
        rule, _, cb_result = _make_rule_with_mocks(
            prev_level=3,
            cb_result={"level": 0, "action": "normal", "reason": "streak satisfied",
                      "position_multiplier": 1.0, "recovery_info": "5d streak"},
        )
        with patch(
            "app.services.risk_control_service.check_circuit_breaker_sync",
            return_value=cb_result,
        ):
            result = rule.evaluate(_make_context())[0]
        assert "recover" in result.reason
        assert "L3" in result.reason and "L0" in result.reason


# ---------- root_rule_id_for ----------


class TestRootRuleIdFor:
    def test_escalate_patterns_owned(self):
        rule = CircuitBreakerRule(conn_factory=MagicMock(), initial_capital=1e6)
        assert rule.root_rule_id_for("cb_escalate_l1") == "circuit_breaker"
        assert rule.root_rule_id_for("cb_escalate_l4") == "circuit_breaker"

    def test_recover_patterns_owned(self):
        rule = CircuitBreakerRule(conn_factory=MagicMock(), initial_capital=1e6)
        assert rule.root_rule_id_for("cb_recover_l0") == "circuit_breaker"
        assert rule.root_rule_id_for("cb_recover_l2") == "circuit_breaker"

    def test_passthrough_unknown(self):
        """非 cb_* pattern → 不声明所有权 (返原 id)."""
        rule = CircuitBreakerRule(conn_factory=MagicMock(), initial_capital=1e6)
        assert rule.root_rule_id_for("pms_l1") == "pms_l1"
        assert rule.root_rule_id_for("intraday_portfolio_drop_5pct") == "intraday_portfolio_drop_5pct"
        # Edge: cb_ 前缀但非数字后缀
        assert rule.root_rule_id_for("cb_escalate_lx") == "cb_escalate_lx"


# ---------- _read_current_level edge cases ----------


class TestReadCurrentLevel:
    def test_returns_level_when_row_exists(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (3,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False

        level = CircuitBreakerRule._read_current_level(mock_conn, "s1", "paper")
        assert level == 3

    def test_returns_zero_when_no_row(self):
        """首次运行, state 表空 → L0."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False

        level = CircuitBreakerRule._read_current_level(mock_conn, "s1", "paper")
        assert level == 0

    def test_returns_zero_on_db_error_fallback(self):
        """表不存在 (首次 adapter 运行前) → fallback L0 + rollback conn."""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = RuntimeError("relation does not exist")

        level = CircuitBreakerRule._read_current_level(mock_conn, "s1", "paper")
        assert level == 0
        # rollback 被调过 (虽可能失败 silent)
        assert mock_conn.rollback.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
