"""Tests for NewPositionVolatilityRule (Phase 1.5b, Session 44).

真生产事件回放: 卓然 (688121) 4-22 entry @ 10.90, 4-23 close 9.79 →
  holding_days=1, loss_pct=-10.17%. 默认阈值 (7d, 5%) → P1 触发.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.qm_platform.risk.interface import Position, RiskContext
from backend.qm_platform.risk.rules.new_position import NewPositionVolatilityRule


def _ctx(positions: list[Position], today: date | None = None) -> RiskContext:
    if today is None:
        today = date(2026, 4, 23)  # 卓然真事件 1 天后
    return RiskContext(
        strategy_id="test-uuid",
        execution_mode="live",
        timestamp=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
        positions=tuple(positions),
        portfolio_nav=1_000_000.0,
        prev_close_nav=None,
    )


def _pos(
    code: str = "688121.SH",
    entry: float = 10.0,
    current: float = 9.0,  # -10% default
    shares: int = 4500,
    entry_date: date | None = date(2026, 4, 22),
) -> Position:
    return Position(
        code=code,
        shares=shares,
        entry_price=entry,
        peak_price=max(entry, current),
        current_price=current,
        entry_date=entry_date,
    )


# ─── 真生产事件回放 ──────────────────────────────────────────


def test_replay_zhuoran_4_23_triggers_p1():
    """卓然 4-22 entry 10.90 → 4-23 close 9.79 = -10.17%, holding=1d → P1."""
    rule = NewPositionVolatilityRule()  # default 7d / 5%
    pos = _pos(
        code="688121.SH",
        entry=10.90,
        current=9.79,
        shares=4500,
        entry_date=date(2026, 4, 22),
    )
    results = rule.evaluate(_ctx([pos], today=date(2026, 4, 23)))
    assert len(results) == 1
    assert results[0].rule_id == "new_position_volatility"
    assert results[0].code == "688121.SH"
    assert results[0].metrics["holding_days"] == 1.0
    assert -0.103 < results[0].metrics["loss_pct"] < -0.101  # -10.17%


# ─── 触发 boundary ────────────────────────────────────────────


def test_trigger_at_loss_boundary_5pct():
    """loss = -5% (boundary, <= -5%) → 触发."""
    rule = NewPositionVolatilityRule()
    pos = _pos(entry=10.0, current=9.5, entry_date=date(2026, 4, 22))  # -5%
    results = rule.evaluate(_ctx([pos], today=date(2026, 4, 23)))
    assert len(results) == 1


def test_no_trigger_at_loss_above_threshold():
    """loss = -4.99% > -5% → 不触发."""
    rule = NewPositionVolatilityRule()
    pos = _pos(entry=10.0, current=9.501, entry_date=date(2026, 4, 22))
    results = rule.evaluate(_ctx([pos], today=date(2026, 4, 23)))
    assert results == []


def test_trigger_at_holding_days_boundary_7():
    """holding_days = 7 (boundary, <= 7) → 仍视为新仓 → 触发."""
    rule = NewPositionVolatilityRule()
    today = date(2026, 4, 29)
    pos = _pos(entry=10.0, current=8.0, entry_date=today - timedelta(days=7))
    results = rule.evaluate(_ctx([pos], today=today))
    assert len(results) == 1


def test_no_trigger_at_holding_days_8():
    """holding_days = 8 > 7 → 已不"新仓", SingleStockStopLoss 接管."""
    rule = NewPositionVolatilityRule()
    today = date(2026, 4, 29)
    pos = _pos(entry=10.0, current=8.0, entry_date=today - timedelta(days=8))
    results = rule.evaluate(_ctx([pos], today=today))
    assert results == []


# ─── 跳过条件 ─────────────────────────────────────────────────


def test_skip_when_entry_date_none():
    """entry_date=None (旧持仓 backfill 缺数据) → silent skip."""
    rule = NewPositionVolatilityRule()
    pos = _pos(entry_date=None)
    results = rule.evaluate(_ctx([pos]))
    assert results == []


def test_skip_when_shares_zero():
    rule = NewPositionVolatilityRule()
    pos = _pos(shares=0)
    results = rule.evaluate(_ctx([pos]))
    assert results == []


def test_skip_when_entry_price_zero():
    """entry_price=0 (无法算 loss_pct) → skip."""
    rule = NewPositionVolatilityRule()
    pos = _pos(entry=0.0)
    results = rule.evaluate(_ctx([pos]))
    assert results == []


def test_skip_when_current_price_zero():
    """current_price=0 (Redis 无价) → skip."""
    rule = NewPositionVolatilityRule()
    pos = _pos(current=0.0)
    results = rule.evaluate(_ctx([pos]))
    assert results == []


def test_skip_when_profitable():
    """loss_pct > -5% (含浮盈) → skip."""
    rule = NewPositionVolatilityRule()
    pos = _pos(entry=10.0, current=11.0, entry_date=date(2026, 4, 22))  # +10%
    results = rule.evaluate(_ctx([pos], today=date(2026, 4, 23)))
    assert results == []


def test_skip_when_entry_date_is_future():
    """P1 CRITICAL reviewer 采纳 (PR #148): entry_date in future (T+1 settlement
    anomaly / data corruption) → holding_days < 0, 必须 silent skip 防 false-positive.

    原代码 `if holding_days > 7: continue` 不挡 -2 → 误报真金事故风险.
    """
    rule = NewPositionVolatilityRule()
    today = date(2026, 4, 29)
    # entry_date=4-30 (今天+1 天, 异常), current 大跌 -10% 但不应触发
    pos = _pos(entry=10.0, current=8.0, entry_date=today + timedelta(days=1))
    results = rule.evaluate(_ctx([pos], today=today))
    assert results == []  # 必须 skip, 即使 loss_pct=-20% 也不该误报


# ─── 自定义阈值 ────────────────────────────────────────────────


def test_custom_loss_threshold_3pct():
    """自定义 loss_pct=0.03: -4% 应触发 (>= 3% 阈值)."""
    rule = NewPositionVolatilityRule(loss_pct_threshold=0.03)
    pos = _pos(entry=10.0, current=9.6, entry_date=date(2026, 4, 22))  # -4%
    results = rule.evaluate(_ctx([pos], today=date(2026, 4, 23)))
    assert len(results) == 1


def test_custom_new_days_threshold_3():
    """自定义 new_days=3: 5 天前 entry → 不触发 (已不"新仓")."""
    rule = NewPositionVolatilityRule(new_days_threshold=3)
    today = date(2026, 4, 29)
    pos = _pos(entry=10.0, current=8.0, entry_date=today - timedelta(days=5))
    results = rule.evaluate(_ctx([pos], today=today))
    assert results == []


def test_invalid_thresholds_raise():
    with pytest.raises(ValueError, match="new_days_threshold"):
        NewPositionVolatilityRule(new_days_threshold=0)
    with pytest.raises(ValueError, match="loss_pct_threshold"):
        NewPositionVolatilityRule(loss_pct_threshold=0)
    with pytest.raises(ValueError, match="loss_pct_threshold"):
        NewPositionVolatilityRule(loss_pct_threshold=1.5)


# ─── root_rule_id_for ─────────────────────────────────────────


def test_root_rule_id_for_self():
    rule = NewPositionVolatilityRule()
    assert rule.root_rule_id_for("new_position_volatility") == "new_position_volatility"


def test_root_rule_id_for_other_passthrough():
    rule = NewPositionVolatilityRule()
    assert rule.root_rule_id_for("pms_l1") == "pms_l1"
