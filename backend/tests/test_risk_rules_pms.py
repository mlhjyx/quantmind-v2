"""L1 unit tests for PMSRule (纯逻辑, 无 IO).

覆盖 MVP 3.1 批 1 PR 2 PMSRule 核心契约:
  - 3 Level × 3 scenario (触发 / 边界 / 不触发)
  - 数据异常 skip (entry<=0 / peak<=0 / current<=0)
  - peak 扩展 (current > peak 时用 current)
  - 顺序命中 (L1 > L2 > L3 优先级)
  - RuleResult schema 完整 (rule_id 动态 / reason / metrics 含 level)
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from backend.qm_platform._types import Severity
from backend.qm_platform.risk.interface import Position, RiskContext
from backend.qm_platform.risk.rules.pms import PMSRule, PMSThreshold


def _make_context(positions: list[Position]) -> RiskContext:
    """构造 test RiskContext helper."""
    return RiskContext(
        strategy_id="00000000-0000-0000-0000-000000000001",
        execution_mode="paper",
        timestamp=datetime.now(UTC),
        positions=tuple(positions),
        portfolio_nav=1_000_000.0,
        prev_close_nav=None,
    )


def _pos(
    code: str = "600519.SH",
    shares: int = 100,
    entry: float = 100.0,
    peak: float = 150.0,
    current: float = 127.0,
) -> Position:
    return Position(
        code=code, shares=shares,
        entry_price=entry, peak_price=peak, current_price=current,
    )


class TestPMSRuleClassContract:
    """PMSRule 类属性契约 (RiskRule __init_subclass__ fail-loud)."""

    def test_rule_id_is_pms(self):
        assert PMSRule.rule_id == "pms"

    def test_severity_is_p1(self):
        assert PMSRule.severity == Severity.P1

    def test_action_is_sell(self):
        assert PMSRule.action == "sell"

    def test_bad_levels_not_sorted_raises(self):
        """levels 必须 min_gain 降序, 否则 L1 被 L3 早退吞掉."""
        bad_levels = (
            PMSThreshold(level=3, min_gain=0.10, max_drawdown=0.10),  # 错序
            PMSThreshold(level=1, min_gain=0.30, max_drawdown=0.15),
        )
        with pytest.raises(ValueError, match="sorted by min_gain DESC"):
            PMSRule(levels=bad_levels)


class TestPMSRuleTriggerScenarios:
    """3 Level × 3 scenario."""

    def test_l1_trigger_gain30_dd15(self):
        """浮盈 +30%, 回撤 -15% → L1 触发."""
        # entry=100, peak=200, current=170 → gain=+70% / dd=15%
        # 但 L1 最高, current=150 → gain=+50% / dd=(200-150)/200=25% > 15% → L1 命中
        pos = _pos(entry=100, peak=200, current=150)
        results = PMSRule().evaluate(_make_context([pos]))

        assert len(results) == 1
        r = results[0]
        assert r.rule_id == "pms_l1"
        assert r.code == "600519.SH"
        assert r.shares == 100
        assert r.metrics["level"] == 1.0
        assert "L1" in r.reason
        assert r.metrics["unrealized_pnl_pct"] == pytest.approx(0.50, abs=1e-3)
        assert r.metrics["drawdown_from_peak_pct"] == pytest.approx(0.25, abs=1e-3)

    def test_l2_trigger_gain22_dd13(self):
        """浮盈 +22%, 回撤 -13% → L2 触发 (L1 gain 30 不达)."""
        # entry=100, peak=140, current=122
        # gain=22% (<30% L1), dd=(140-122)/140 ≈ 12.86% (<15% L1)  → L1 fail
        # L2: gain ≥20% ✓, dd ≥12% ✓ (12.86%) → L2 命中
        pos = _pos(entry=100, peak=140, current=122)
        results = PMSRule().evaluate(_make_context([pos]))

        assert len(results) == 1
        assert results[0].rule_id == "pms_l2"
        assert results[0].metrics["level"] == 2.0

    def test_l3_trigger_gain11_dd11(self):
        """浮盈 +11%, 回撤 -11% → L3 触发."""
        pos = _pos(entry=100, peak=125, current=111)
        # gain=11%, dd=(125-111)/125=11.2%
        # L1 (30/15): fail gain. L2 (20/12): fail gain. L3 (10/10): gain ✓ / dd ✓
        results = PMSRule().evaluate(_make_context([pos]))

        assert len(results) == 1
        assert results[0].rule_id == "pms_l3"
        assert results[0].metrics["level"] == 3.0

    def test_l3_boundary_gain_exact(self):
        """浮盈恰好 +10%, 回撤恰好 -10% → L3 触发 (>= 阈值)."""
        pos = _pos(entry=100, peak=100 * 1.1 / 0.9, current=110)
        # entry=100, peak ≈ 122.22, current=110
        # gain=10%, dd=(122.22-110)/122.22=10%
        # L3 10/10 边界 >= 触发
        results = PMSRule().evaluate(_make_context([pos]))
        assert len(results) == 1
        assert results[0].rule_id == "pms_l3"

    def test_no_trigger_profit_too_small(self):
        """浮盈 +5% < L3 10% → 不触发."""
        pos = _pos(entry=100, peak=110, current=105)
        results = PMSRule().evaluate(_make_context([pos]))
        assert results == []

    def test_no_trigger_drawdown_too_small(self):
        """浮盈 +20% 达 L2, 但回撤 +5% < L2 12% → 不触发."""
        # entry=100, peak=120, current=117 → gain 17%... 不够 L2
        # 调: entry=100, peak=125, current=120 → gain=20% / dd=(125-120)/125=4% → L2 fail dd
        pos = _pos(entry=100, peak=125, current=120)
        results = PMSRule().evaluate(_make_context([pos]))
        assert results == []


class TestPMSRuleSkipOnInvalidData:
    """异常数据 skip (对齐 pms_engine.check_protection L108-110)."""

    def test_skip_entry_price_zero(self):
        """entry_price=0 (老 paper 命名空间 F29) → skip 不 raise."""
        pos = _pos(entry=0.0, peak=150, current=127)
        results = PMSRule().evaluate(_make_context([pos]))
        assert results == []

    def test_skip_peak_price_zero(self):
        pos = _pos(entry=100, peak=0.0, current=127)
        results = PMSRule().evaluate(_make_context([pos]))
        assert results == []

    def test_skip_current_price_zero(self):
        """Redis 无价 (F19 phantom 码) → skip 不 raise."""
        pos = _pos(entry=100, peak=150, current=0.0)
        results = PMSRule().evaluate(_make_context([pos]))
        assert results == []


class TestPMSRulePeakExpansion:
    """peak 扩展: current > peak 时用 current (同 pms_engine.check_all_positions L268)."""

    def test_current_higher_than_peak_uses_current_as_peak(self):
        """entry=100, peak=120, current=130 → effective_peak=130, no drawdown → 不触发."""
        pos = _pos(entry=100, peak=120, current=130)
        results = PMSRule().evaluate(_make_context([pos]))
        assert results == []


class TestPMSRuleMultiPosition:
    """多 position 独立判定."""

    def test_two_positions_one_triggers(self):
        """A 触发 L1, B 不触发."""
        triggered = _pos(code="000001.SZ", entry=100, peak=200, current=150)  # L1
        safe = _pos(code="600519.SH", entry=100, peak=105, current=102)  # not triggered
        results = PMSRule().evaluate(_make_context([triggered, safe]))
        assert len(results) == 1
        assert results[0].code == "000001.SZ"
        assert results[0].rule_id == "pms_l1"

    def test_empty_positions_returns_empty(self):
        results = PMSRule().evaluate(_make_context([]))
        assert results == []


class TestPMSRuleCustomLevels:
    """自定义阈值 (daily_pipeline wire 从 settings 注入用)."""

    def test_custom_levels_used(self):
        """覆盖默认 L1 30% 为 50%, gain 35% 不触发."""
        custom = (
            PMSThreshold(level=1, min_gain=0.50, max_drawdown=0.15),
        )
        # gain=35% < 50% → not triggered with custom
        pos = _pos(entry=100, peak=200, current=135)
        results = PMSRule(levels=custom).evaluate(_make_context([pos]))
        assert results == []

        # Same pos with default PMSRule → should trigger L1 (gain 35% >= 30%)
        # dd = (200-135)/200 = 32.5% >= 15% ✓
        results_default = PMSRule().evaluate(_make_context([pos]))
        assert len(results_default) == 1
        assert results_default[0].rule_id == "pms_l1"


class TestPMSRuleOrderPriority:
    """L1→L2→L3 顺序命中 (首次命中即 break, 保留 pms_engine 原语义)."""

    def test_position_matching_all_three_levels_only_l1_emitted(self):
        """entry=100, peak=300, current=200 → gain 100%, dd 33% 同时 >= L1/L2/L3, 只 L1 emit."""
        pos = _pos(entry=100, peak=300, current=200)
        results = PMSRule().evaluate(_make_context([pos]))
        assert len(results) == 1
        assert results[0].rule_id == "pms_l1"  # L1 最严先命中


class TestPMSRuleRuleResultSchema:
    """RuleResult 字段完整性 (engine._log_event 依赖)."""

    def test_metrics_contains_all_fields(self):
        pos = _pos(entry=100, peak=200, current=150)
        r = PMSRule().evaluate(_make_context([pos]))[0]
        required = {
            "level", "entry_price", "peak_price", "current_price",
            "unrealized_pnl_pct", "drawdown_from_peak_pct",
            "min_gain_threshold", "max_drawdown_threshold",
        }
        assert required.issubset(r.metrics.keys())

    def test_reason_human_readable(self):
        pos = _pos(entry=100, peak=200, current=150)
        r = PMSRule().evaluate(_make_context([pos]))[0]
        assert "PMS L1" in r.reason
        assert "gain=" in r.reason
        assert "drawdown=" in r.reason

    def test_frozen_position_not_mutated(self):
        """RiskRule.evaluate 不得修改 context.positions (frozen dataclass 已保)."""
        pos = _pos()
        ctx = _make_context([pos])
        original = replace(pos)  # deep copy via replace
        PMSRule().evaluate(ctx)
        assert ctx.positions[0] == original


class TestPMSRuleFailLoudOnHighSkipRatio:
    """PR-X2 LL-081 真修复: 大比例 skip 必告警 (zombie 模式 fail-loud).

    背景: 4-27 真生产首日 zombie 4h17m, 14:30 risk-daily-check 触发, 19/19 持仓
    current_price=0 全 silent skip, "risk_event_log 0 events" 是伪健康. 修复后
    skip 比例 > 60% + 持仓 > 5 → logger.warning P1.
    """

    def test_warns_when_zombie_pattern_19_of_19_skipped(self, caplog):
        """LL-081 实战场景: 19 持仓 current_price=0 (Redis market:latest:* 全过期)
        → logger.warning 触发 (skip ratio = 100% > 60% + 19 > 5).
        """
        positions = [
            _pos(code=f"60{i:04d}.SH", current=0.0)  # current_price=0 全 skip
            for i in range(19)
        ]
        ctx = _make_context(positions)

        with caplog.at_level("WARNING", logger="backend.qm_platform.risk.rules.pms"):
            results = PMSRule().evaluate(ctx)

        assert results == []  # 全 skip 无 trigger
        # 必有 warning log: "PMSRule skip 大比例" + "19/19" + "100%"
        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("PMSRule skip 大比例" in msg for msg in warning_msgs), (
            f"期望 'PMSRule skip 大比例' warning, 实际 logs: {warning_msgs}"
        )
        assert any("19/19" in msg for msg in warning_msgs), (
            f"期望 ratio 19/19 in log, 实际: {warning_msgs}"
        )

    def test_no_warn_when_few_positions_single_data_issue(self, caplog):
        """3 持仓 2 skip (ratio 67% > 60%, 但 total=3 <= 5) → 不告警.

        LL-081 设计: 单股 / 少股 skip 是 data quality 噪声 (e.g. 新建仓 entry_price=0
        timing race), 不是系统性故障, 避免噪声告警.
        """
        positions = [
            _pos(code="600519.SH", current=0.0),  # skip
            _pos(code="600028.SH", current=0.0),  # skip
            _pos(code="600900.SH", current=130.0),  # 正常
        ]
        ctx = _make_context(positions)

        with caplog.at_level("WARNING", logger="backend.qm_platform.risk.rules.pms"):
            PMSRule().evaluate(ctx)

        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert not any("PMSRule skip 大比例" in msg for msg in warning_msgs), (
            f"少股 skip 不应告警 (LL-081 设计避噪声), 实际 logs: {warning_msgs}"
        )

    def test_no_warn_when_skip_ratio_below_threshold(self, caplog):
        """20 持仓 5 skip (ratio 25% < 60%) → 不告警 (常态数据问题接受)."""
        positions = []
        # 5 个 skip
        for i in range(5):
            positions.append(_pos(code=f"60{i:04d}.SH", current=0.0))
        # 15 个正常 (gain 5%, drawdown 5% — 不触发 L3 阈值 gain≥10% + dd≥10%)
        for i in range(5, 20):
            positions.append(_pos(code=f"60{i:04d}.SH", entry=100.0, peak=110.0, current=105.0))
        ctx = _make_context(positions)

        with caplog.at_level("WARNING", logger="backend.qm_platform.risk.rules.pms"):
            PMSRule().evaluate(ctx)

        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert not any("PMSRule skip 大比例" in msg for msg in warning_msgs), (
            f"25% skip ratio 应低于 60% 阈值, 实际 logs: {warning_msgs}"
        )

    # ─── reviewer code P1-1 + P1-2 + python P2 采纳: boundary precision tests ───

    def test_boundary_exactly_at_min_positions_no_warn(self, caplog):
        """total=5 (== MIN_POSITIONS, 条件 strict `> 5`) 全 skip → 不告警.

        boundary 验证: SKIP_RATIO_MIN_POSITIONS=5 持仓数门槛严格大于, total=5 不触发.
        """
        positions = [_pos(code=f"60{i:04d}.SH", current=0.0) for i in range(5)]
        ctx = _make_context(positions)

        with caplog.at_level("WARNING", logger="backend.qm_platform.risk.rules.pms"):
            PMSRule().evaluate(ctx)

        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert not any("PMSRule skip 大比例" in msg for msg in warning_msgs), (
            f"total=5 边界严格 > 不应告警, 实际 logs: {warning_msgs}"
        )

    def test_boundary_just_above_min_positions_warns(self, caplog):
        """total=6 (> MIN_POSITIONS=5) 全 skip → 告警 (ratio 100% > 60%)."""
        positions = [_pos(code=f"60{i:04d}.SH", current=0.0) for i in range(6)]
        ctx = _make_context(positions)

        with caplog.at_level("WARNING", logger="backend.qm_platform.risk.rules.pms"):
            PMSRule().evaluate(ctx)

        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("PMSRule skip 大比例" in msg for msg in warning_msgs), (
            f"total=6 边界严格 > 应告警, 实际 logs: {warning_msgs}"
        )
        assert any("6/6" in msg for msg in warning_msgs)

    def test_boundary_ratio_exactly_60_pct_no_warn(self, caplog):
        """20 持仓 12 skip = 60.0% (== THRESHOLD, strict `>`) → 不告警."""
        positions = []
        for i in range(12):
            positions.append(_pos(code=f"60{i:04d}.SH", current=0.0))  # skip
        for i in range(12, 20):
            positions.append(_pos(code=f"60{i:04d}.SH", entry=100.0, peak=110.0, current=105.0))
        ctx = _make_context(positions)

        with caplog.at_level("WARNING", logger="backend.qm_platform.risk.rules.pms"):
            PMSRule().evaluate(ctx)

        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert not any("PMSRule skip 大比例" in msg for msg in warning_msgs), (
            f"ratio 60.0% 严格 > 不应告警, 实际 logs: {warning_msgs}"
        )

    def test_boundary_ratio_just_above_60_pct_warns(self, caplog):
        """20 持仓 13 skip = 65.0% (> THRESHOLD) → 告警."""
        positions = []
        for i in range(13):
            positions.append(_pos(code=f"60{i:04d}.SH", current=0.0))  # skip
        for i in range(13, 20):
            positions.append(_pos(code=f"60{i:04d}.SH", entry=100.0, peak=110.0, current=105.0))
        ctx = _make_context(positions)

        with caplog.at_level("WARNING", logger="backend.qm_platform.risk.rules.pms"):
            PMSRule().evaluate(ctx)

        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("PMSRule skip 大比例" in msg for msg in warning_msgs), (
            f"ratio 65.0% > 60% 应告警, 实际 logs: {warning_msgs}"
        )
        assert any("13/20" in msg for msg in warning_msgs)

    def test_empty_portfolio_no_warn_no_crash(self, caplog):
        """空仓 (total_positions=0) 不告警不 crash (reviewer P2 explicit ZeroDivisionError 防御)."""
        ctx = _make_context([])

        with caplog.at_level("WARNING", logger="backend.qm_platform.risk.rules.pms"):
            results = PMSRule().evaluate(ctx)

        assert results == []
        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert not any("PMSRule skip 大比例" in msg for msg in warning_msgs)
