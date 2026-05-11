"""L1 unit tests for realtime risk rule: IndustryConcentration (S5 sub-PR 5b).

覆盖:
  - 单行业集中触发 (concentration > 30%)
  - 多行业分散不触发
  - 无 realtime (全部 unknown)
  - 部分 industry 缺失
  - 空持仓
  - 自定义阈值
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.qm_platform._types import Severity
from backend.qm_platform.risk import Position, RiskContext
from backend.qm_platform.risk.rules.realtime import IndustryConcentration


def _make_context(
    positions: tuple[Position, ...] = (),
    realtime: dict[str, dict] | None = None,
) -> RiskContext:
    return RiskContext(
        strategy_id="test-s5-industry",
        execution_mode="paper",
        timestamp=datetime.now(UTC),
        positions=positions,
        portfolio_nav=1_000_000.0,
        prev_close_nav=1_000_000.0,
        realtime=realtime,
    )


def _pos(code: str, price: float, shares: int = 1000) -> Position:
    return Position(
        code=code,
        shares=shares,
        entry_price=price * 1.1,
        peak_price=price * 1.2,
        current_price=price,
        entry_date=None,
    )


# ===== IndustryConcentration =====


class TestIndustryConcentration:
    def test_rule_contract(self):
        rule = IndustryConcentration()
        assert rule.rule_id == "industry_concentration"
        assert rule.severity == Severity.P2
        assert rule.action == "alert_only"

    def test_concentration_trigger(self):
        """6/10 = 60% 同行业 > 30%."""
        rule = IndustryConcentration()
        positions = tuple(_pos(f"00000{i}.SZ", 10.0) for i in range(1, 11))
        realtime = {}
        for i in range(1, 7):
            realtime[f"00000{i}.SZ"] = {"industry": "食品饮料"}
        for i in range(7, 11):
            realtime[f"00000{i}.SZ"] = {"industry": "电子"}

        ctx = _make_context(positions=positions, realtime=realtime)
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].rule_id == "industry_concentration"
        assert results[0].metrics["top_industry"] == "食品饮料"
        assert results[0].metrics["concentration"] == 0.6

    def test_concentration_at_boundary(self):
        """3/10 = 30% === threshold, 不触发 (threshold 是 exclusive <=)."""
        rule = IndustryConcentration(threshold=0.30)
        positions = tuple(_pos(f"00000{i}.SZ", 10.0) for i in range(1, 11))
        realtime = {}
        for i in range(1, 4):
            realtime[f"00000{i}.SZ"] = {"industry": "银行"}
        for i in range(4, 7):
            realtime[f"00000{i}.SZ"] = {"industry": "电子"}
        for i in range(7, 9):
            realtime[f"00000{i}.SZ"] = {"industry": "医药生物"}
        for i in range(9, 11):
            realtime[f"00000{i}.SZ"] = {"industry": "食品饮料"}

        ctx = _make_context(positions=positions, realtime=realtime)
        assert rule.evaluate(ctx) == []

    def test_balanced_not_trigger(self):
        """5 行业均匀分布 (max 22.2%), 不触发."""
        rule = IndustryConcentration()
        positions = tuple(_pos(f"00000{i}.SZ", 10.0) for i in range(1, 10))
        realtime = {}
        for i in range(1, 3):
            realtime[f"00000{i}.SZ"] = {"industry": "银行"}
        for i in range(3, 5):
            realtime[f"00000{i}.SZ"] = {"industry": "电子"}
        for i in range(5, 7):
            realtime[f"00000{i}.SZ"] = {"industry": "医药生物"}
        for i in range(7, 9):
            realtime[f"00000{i}.SZ"] = {"industry": "食品饮料"}
        for i in range(9, 10):
            realtime[f"00000{i}.SZ"] = {"industry": "汽车"}

        ctx = _make_context(positions=positions, realtime=realtime)
        assert rule.evaluate(ctx) == []

    def test_empty_positions(self):
        """空持仓, 返回空."""
        rule = IndustryConcentration()
        ctx = _make_context(positions=())
        assert rule.evaluate(ctx) == []

    def test_no_realtime_all_unknown(self):
        """无 realtime, 所有股归入 unknown, 100% > 30% 触发."""
        rule = IndustryConcentration()
        positions = tuple(_pos(f"00000{i}.SZ", 10.0) for i in range(1, 6))
        ctx = _make_context(positions=positions)
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].metrics["top_industry"] == "unknown"
        assert results[0].metrics["concentration"] == 1.0

    def test_partial_industry_missing(self):
        """部分股缺 industry, 归入 unknown."""
        rule = IndustryConcentration(threshold=0.30)
        # 8 stocks: 3 "银行", 3 "电子", 2 unknown
        positions = tuple(_pos(f"00000{i}.SZ", 10.0) for i in range(1, 9))
        realtime = {}
        for i in range(1, 4):
            realtime[f"00000{i}.SZ"] = {"industry": "银行"}
        for i in range(4, 7):
            realtime[f"00000{i}.SZ"] = {"industry": "电子"}
        # 000007-000008 have no realtime entry

        ctx = _make_context(positions=positions, realtime=realtime)
        results = rule.evaluate(ctx)
        # 3 银行 / 8 = 37.5% > 30% → 触发
        assert len(results) == 1
        assert results[0].metrics["top_industry"] == "银行"
        assert results[0].metrics["unknown_count"] == 2

    def test_custom_threshold(self):
        """自定义 threshold=0.5, max=40%=2/5 不触发."""
        rule = IndustryConcentration(threshold=0.5)
        positions = tuple(_pos(f"00000{i}.SZ", 10.0) for i in range(1, 6))
        realtime = {}
        for i in range(1, 3):
            realtime[f"00000{i}.SZ"] = {"industry": "银行"}
        for i in range(3, 5):
            realtime[f"00000{i}.SZ"] = {"industry": "电子"}
        realtime["000005.SZ"] = {"industry": "医药生物"}

        ctx = _make_context(positions=positions, realtime=realtime)
        assert rule.evaluate(ctx) == []

    def test_non_string_industry_handled(self):
        """industry 非 str (None/int), 归入 unknown."""
        rule = IndustryConcentration(threshold=0.30)
        positions = tuple(_pos(f"00000{i}.SZ", 10.0) for i in range(1, 6))
        realtime = {}
        for i in range(1, 4):
            realtime[f"00000{i}.SZ"] = {"industry": "银行"}
        realtime["000004.SZ"] = {"industry": None}
        realtime["000005.SZ"] = {"industry": 123}

        ctx = _make_context(positions=positions, realtime=realtime)
        results = rule.evaluate(ctx)
        # 3 "银行" / 5 = 60% > 30% → 触发
        assert len(results) == 1
        assert results[0].metrics["unknown_count"] == 2
