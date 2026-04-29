"""Tests for PositionHoldingTimeRule (Phase 1.5b, Session 44)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.qm_platform.risk.interface import Position, RiskContext
from backend.qm_platform.risk.rules.holding_time import PositionHoldingTimeRule


def _ctx(positions: list[Position], today: date | None = None) -> RiskContext:
    """Build RiskContext at given today (default 2026-04-29)."""
    if today is None:
        today = date(2026, 4, 29)
    return RiskContext(
        strategy_id="test-uuid",
        execution_mode="live",
        timestamp=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
        positions=tuple(positions),
        portfolio_nav=1_000_000.0,
        prev_close_nav=None,
    )


def _pos(
    code: str = "600000.SH",
    entry: float = 10.0,
    current: float = 11.0,
    shares: int = 100,
    entry_date: date | None = date(2026, 1, 1),
) -> Position:
    return Position(
        code=code,
        shares=shares,
        entry_price=entry,
        peak_price=max(entry, current),
        current_price=current,
        entry_date=entry_date,
    )


# ─── 触发 ─────────────────────────────────────────────────────


def test_trigger_when_holding_30_days():
    """holding_days = 30 (boundary, >= threshold) → 触发."""
    rule = PositionHoldingTimeRule()  # default threshold=30
    today = date(2026, 4, 29)
    pos = _pos(entry_date=today - timedelta(days=30))
    results = rule.evaluate(_ctx([pos], today=today))
    assert len(results) == 1
    assert results[0].rule_id == "position_holding_time"
    assert results[0].metrics["holding_days"] == 30.0


def test_trigger_when_holding_100_days():
    """holding_days = 100 → 触发, 信息正确."""
    rule = PositionHoldingTimeRule()
    today = date(2026, 4, 29)
    entry = today - timedelta(days=100)
    pos = _pos(entry_date=entry)
    results = rule.evaluate(_ctx([pos], today=today))
    assert len(results) == 1
    assert results[0].metrics["holding_days"] == 100.0
    assert "holding_days=100" in results[0].reason


def test_no_trigger_when_holding_29_days():
    """holding_days = 29 < 30 → 不触发."""
    rule = PositionHoldingTimeRule()
    today = date(2026, 4, 29)
    pos = _pos(entry_date=today - timedelta(days=29))
    results = rule.evaluate(_ctx([pos], today=today))
    assert results == []


# ─── 跳过条件 ─────────────────────────────────────────────────


def test_skip_when_entry_date_none():
    """entry_date=None (Phase 1.5a 缺数据) → silent skip."""
    rule = PositionHoldingTimeRule()
    pos = _pos(entry_date=None)
    results = rule.evaluate(_ctx([pos]))
    assert results == []


def test_skip_when_shares_zero():
    """shares=0 (已平仓) → silent skip."""
    rule = PositionHoldingTimeRule()
    pos = _pos(shares=0, entry_date=date(2025, 1, 1))
    results = rule.evaluate(_ctx([pos]))
    assert results == []


def test_skip_when_entry_date_is_future():
    """P1 defense reviewer 采纳 (PR #148): future entry_date → holding_days < 0,
    显式 guard skip (defense-in-depth, 与 NewPositionVolatilityRule 同源)."""
    rule = PositionHoldingTimeRule()
    today = date(2026, 4, 29)
    pos = _pos(entry_date=today + timedelta(days=1))  # +1 天异常
    results = rule.evaluate(_ctx([pos], today=today))
    assert results == []


# ─── 自定义阈值 ────────────────────────────────────────────────


def test_custom_threshold_60_days():
    """自定义 threshold=60: 30 天不触发, 60 天触发."""
    rule = PositionHoldingTimeRule(threshold_days=60)
    today = date(2026, 4, 29)
    short = _pos(code="A.SH", entry_date=today - timedelta(days=30))
    long_ = _pos(code="B.SZ", entry_date=today - timedelta(days=60))
    results = rule.evaluate(_ctx([short, long_], today=today))
    assert len(results) == 1
    assert results[0].code == "B.SZ"


def test_invalid_threshold_raises():
    """threshold_days < 1 → ValueError."""
    with pytest.raises(ValueError, match=">= 1"):
        PositionHoldingTimeRule(threshold_days=0)
    with pytest.raises(ValueError, match=">= 1"):
        PositionHoldingTimeRule(threshold_days=-5)


# ─── 多 position ─────────────────────────────────────────────


def test_multi_position_only_long_triggers():
    """混合短期 (10d) + 长期 (45d) → 仅长期触发."""
    rule = PositionHoldingTimeRule(threshold_days=30)
    today = date(2026, 4, 29)
    pos1 = _pos(code="A.SH", entry_date=today - timedelta(days=10))  # 短期
    pos2 = _pos(code="B.SZ", entry_date=today - timedelta(days=45))  # 长期
    pos3 = _pos(code="C.SH", entry_date=None)  # 无 entry_date, skip
    results = rule.evaluate(_ctx([pos1, pos2, pos3], today=today))
    assert len(results) == 1
    assert results[0].code == "B.SZ"


# ─── root_rule_id_for ─────────────────────────────────────────


def test_root_rule_id_for_self():
    rule = PositionHoldingTimeRule()
    assert rule.root_rule_id_for("position_holding_time") == "position_holding_time"


def test_root_rule_id_for_other_passthrough():
    rule = PositionHoldingTimeRule()
    assert rule.root_rule_id_for("pms_l1") == "pms_l1"
