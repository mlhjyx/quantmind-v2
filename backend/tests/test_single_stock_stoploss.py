"""Unit tests — SingleStockStopLossRule (MVP 3.1b Phase 1).

覆盖:
  - 4 档阈值触发 (-10/-15/-20/-25)
  - 反序命中: -29% 命中 L4 (而非 L1)
  - 不触发: 浮亏 < -10% / 浮盈
  - skip: entry_price=0 / current_price=0 / shares=0
  - root_rule_id_for: pms 或其他 rule_id passthrough
  - auto_sell_l4 flag: L4 档 action='sell' 切换 + shares 填充
  - levels 排序非升序 raise ValueError
  - reason / metrics 内容
  - 互补 PMSRule: 浮盈+回撤场景 SingleStockStopLoss 不动
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.qm_platform._types import Severity
from backend.qm_platform.risk.interface import Position, RiskContext
from backend.qm_platform.risk.rules.single_stock import (
    SingleStockStopLossRule,
    StopLossThreshold,
)


def _ctx(positions: list[Position]) -> RiskContext:
    return RiskContext(
        strategy_id="11111111-1111-1111-1111-111111111111",
        execution_mode="paper",
        timestamp=datetime.now(UTC),
        positions=tuple(positions),
        portfolio_nav=1_000_000.0,
        prev_close_nav=1_010_000.0,
    )


def _pos(code: str, entry: float, current: float, shares: int = 1000) -> Position:
    return Position(
        code=code,
        shares=shares,
        entry_price=entry,
        peak_price=max(entry, current),  # peak >= max(entry, current)
        current_price=current,
    )


# ─────────────────────────── 阈值触发: 4 档 ───────────────────────────


def test_l1_triggered_at_minus_10_pct():
    """-10% 触发 L1 (P2 alert_only)."""
    rule = SingleStockStopLossRule()
    pos = _pos("600028.SH", entry=10.0, current=9.0)  # -10%
    results = rule.evaluate(_ctx([pos]))
    assert len(results) == 1
    assert results[0].rule_id == "single_stock_stoploss_l1"
    assert results[0].code == "600028.SH"
    assert results[0].shares == 0  # alert_only
    assert results[0].metrics["level"] == 1.0
    assert results[0].metrics["loss_pct"] == pytest.approx(-0.10)


def test_l2_triggered_at_minus_15_pct():
    rule = SingleStockStopLossRule()
    pos = _pos("000012.SZ", entry=10.0, current=8.5)  # -15%
    results = rule.evaluate(_ctx([pos]))
    assert len(results) == 1
    assert results[0].rule_id == "single_stock_stoploss_l2"


def test_l3_triggered_at_minus_20_pct():
    rule = SingleStockStopLossRule()
    pos = _pos("002623.SZ", entry=10.0, current=8.0)  # -20%
    results = rule.evaluate(_ctx([pos]))
    assert len(results) == 1
    assert results[0].rule_id == "single_stock_stoploss_l3"


def test_l4_triggered_at_minus_25_pct():
    """-25% 触发 L4 (真生产 卓然 -29% 场景)."""
    rule = SingleStockStopLossRule()
    pos = _pos("688121.SH", entry=10.90, current=7.72, shares=4500)  # -29.17%
    results = rule.evaluate(_ctx([pos]))
    assert len(results) == 1
    assert results[0].rule_id == "single_stock_stoploss_l4"
    assert results[0].code == "688121.SH"
    assert results[0].shares == 0  # 默认 alert_only
    assert results[0].metrics["level"] == 4.0
    # 卓然 真生产 case: loss_pct ≈ -29.17%
    assert -0.30 < results[0].metrics["loss_pct"] < -0.29


# ─────────────────────────── 反序命中 (L4 先) ───────────────────────────


def test_minus_29_pct_hits_l4_not_l1():
    """卓然 -29% 必命中 L4 (最严), 而非 L1 (-10%) — 反序遍历."""
    rule = SingleStockStopLossRule()
    pos = _pos("688121.SH", entry=10.0, current=7.10)  # -29%
    results = rule.evaluate(_ctx([pos]))
    assert len(results) == 1
    assert results[0].rule_id == "single_stock_stoploss_l4"


def test_minus_18_pct_hits_l2_not_l3():
    """-18% 命中 L2 (-15%), 而非 L3 (要求 -20%)."""
    rule = SingleStockStopLossRule()
    pos = _pos("002623.SZ", entry=10.0, current=8.2)  # -18%
    results = rule.evaluate(_ctx([pos]))
    assert len(results) == 1
    assert results[0].rule_id == "single_stock_stoploss_l2"


# ─────────────────────────── 不触发 ───────────────────────────


def test_no_trigger_at_minus_5_pct():
    rule = SingleStockStopLossRule()
    pos = _pos("600028.SH", entry=10.0, current=9.5)  # -5%
    assert rule.evaluate(_ctx([pos])) == []


def test_no_trigger_when_profit():
    """浮盈不触发 (设计上对 PMS 互补, 不重叠)."""
    rule = SingleStockStopLossRule()
    pos = _pos("600028.SH", entry=10.0, current=11.0)  # +10%
    assert rule.evaluate(_ctx([pos])) == []


def test_no_trigger_at_exact_minus_9_99_pct():
    """边界: -9.99% 不触发 L1 (-10%)."""
    rule = SingleStockStopLossRule()
    pos = _pos("600028.SH", entry=10.0, current=9.001)  # -9.99%
    assert rule.evaluate(_ctx([pos])) == []


# ─────────────────────────── skip 条件 ───────────────────────────


def test_skip_zero_entry_price():
    """entry_price=0 (paper namespace 漂移) skip."""
    rule = SingleStockStopLossRule()
    pos = _pos("600028.SH", entry=0.0, current=9.0)
    assert rule.evaluate(_ctx([pos])) == []


def test_skip_zero_current_price():
    """current_price=0 (Redis 无价 / 数据异常) skip."""
    rule = SingleStockStopLossRule()
    pos = _pos("600028.SH", entry=10.0, current=0.0)
    assert rule.evaluate(_ctx([pos])) == []


def test_skip_zero_shares():
    """shares=0 (空仓 / 已平仓待清理) skip."""
    rule = SingleStockStopLossRule()
    pos = _pos("600028.SH", entry=10.0, current=7.0, shares=0)
    assert rule.evaluate(_ctx([pos])) == []


# ─────────────────────────── auto_sell_l4 flag ───────────────────────────


def test_auto_sell_l4_flag_changes_action_to_sell():
    """auto_sell_l4=True → L4 档 action='sell' + shares 填充全部仓位."""
    rule = SingleStockStopLossRule(auto_sell_l4=True)
    pos = _pos("688121.SH", entry=10.0, current=7.0, shares=4500)  # -30%
    results = rule.evaluate(_ctx([pos]))
    assert len(results) == 1
    assert results[0].rule_id == "single_stock_stoploss_l4"
    assert results[0].shares == 4500  # action='sell' 填全部
    assert "action=sell" in results[0].reason


def test_auto_sell_l4_does_not_affect_l1_l2_l3():
    """auto_sell_l4=True 仅改 L4, L1/L2/L3 仍 alert_only (shares=0)."""
    rule = SingleStockStopLossRule(auto_sell_l4=True)
    pos = _pos("002623.SZ", entry=10.0, current=8.5, shares=2100)  # -15% L2
    results = rule.evaluate(_ctx([pos]))
    assert len(results) == 1
    assert results[0].rule_id == "single_stock_stoploss_l2"
    assert results[0].shares == 0  # L2 仍 alert_only


# ─────────────────────────── levels 排序校验 ───────────────────────────


def test_init_raises_on_unsorted_levels():
    """levels 必须按 max_loss_pct 升序 (L1 最宽 → L4 最严)."""
    bad_levels = (
        StopLossThreshold(level=1, max_loss_pct=0.20, severity=Severity.P0, action="alert_only"),
        StopLossThreshold(level=2, max_loss_pct=0.10, severity=Severity.P2, action="alert_only"),
    )
    with pytest.raises(ValueError, match="must be sorted by max_loss_pct ASC"):
        SingleStockStopLossRule(levels=bad_levels)


# ─────────────────────────── root_rule_id_for ───────────────────────────


def test_root_rule_id_for_single_stock_l1_returns_root():
    rule = SingleStockStopLossRule()
    assert rule.root_rule_id_for("single_stock_stoploss_l1") == "single_stock_stoploss"
    assert rule.root_rule_id_for("single_stock_stoploss_l4") == "single_stock_stoploss"


def test_root_rule_id_for_other_rules_passthrough():
    """非 single_stock_stoploss_lN pattern 不声明拥有, passthrough."""
    rule = SingleStockStopLossRule()
    assert rule.root_rule_id_for("pms_l1") == "pms_l1"
    assert rule.root_rule_id_for("intraday_portfolio_drop_5pct") == "intraday_portfolio_drop_5pct"


# ─────────────────────────── reason / metrics 内容 ───────────────────────────


def test_reason_contains_key_fields():
    rule = SingleStockStopLossRule()
    pos = _pos("688121.SH", entry=10.90, current=7.72, shares=4500)
    results = rule.evaluate(_ctx([pos]))
    reason = results[0].reason
    assert "L4" in reason
    assert "10.8" in reason or "10.9" in reason  # entry_price
    assert "7.7" in reason  # current_price
    assert "4500" in reason  # shares


def test_metrics_contain_required_keys():
    rule = SingleStockStopLossRule()
    pos = _pos("688121.SH", entry=10.0, current=7.0, shares=4500)
    results = rule.evaluate(_ctx([pos]))
    m = results[0].metrics
    assert "level" in m
    assert "entry_price" in m
    assert "current_price" in m
    assert "loss_pct" in m
    assert "max_loss_threshold" in m
    assert "shares" in m
    assert "severity_level_p" in m
    # severity_level_p L4 = P0 → 0.0
    assert m["severity_level_p"] == 0.0


# ─────────────────────────── 多 position + 互补 PMSRule ───────────────────────────


def test_multi_positions_only_loss_triggered():
    """4 持仓: 2 浮盈 + 2 浮亏 → 仅 2 浮亏触发."""
    rule = SingleStockStopLossRule()
    positions = [
        _pos("PROFIT1.SH", entry=10.0, current=11.0),  # +10% 不触发
        _pos("PROFIT2.SH", entry=10.0, current=12.0),  # +20% 不触发
        _pos("LOSS1.SH", entry=10.0, current=8.5),  # -15% L2
        _pos("LOSS2.SH", entry=10.0, current=7.0),  # -30% L4
    ]
    results = rule.evaluate(_ctx(positions))
    assert len(results) == 2
    triggered_codes = {r.code for r in results}
    assert triggered_codes == {"LOSS1.SH", "LOSS2.SH"}
