"""PreTradeValidator 测试 — Sprint 1.10 Task 2.

覆盖:
- 正常通过场景（5项全PASS）
- 各项独立拒绝场景
- 边界条件（刚好在阈值上）
- 卖单跳过价格容差检查
"""

from __future__ import annotations

import pytest
from engines.pre_trade_validator import PreTradeValidator, ValidationResult

# ── 测试夹具 ──

TOTAL_VALUE = 1_000_000.0  # 100万总资产

DEFAULT_POSITIONS = {
    "600519": 0.07,   # 贵州茅台 7%
    "000001": 0.06,   # 平安银行 6%
    "601318": 0.06,   # 中国平安 6%
}

DEFAULT_INDUSTRY = {
    "600519": "白酒",
    "000001": "银行",
    "601318": "保险",
    "000651": "家电",
    "600036": "银行",   # 招商银行，同行业
}


def make_validator(
    total_value: float = TOTAL_VALUE,
    positions: dict = None,
    industry_map: dict = None,
    daily_return: float = 0.005,
    **kwargs,
) -> PreTradeValidator:
    return PreTradeValidator(
        total_value=total_value,
        current_positions=positions if positions is not None else DEFAULT_POSITIONS,
        industry_map=industry_map if industry_map is not None else DEFAULT_INDUSTRY,
        daily_return=daily_return,
        **kwargs,
    )


class TestNormalPass:
    """正常通过：5项全PASS。"""

    def test_all_checks_pass(self):
        """标准买单：金额5万(5%<15%), 价格在容差内, 行业不超, 无亏损, 单股<10%。"""
        v = make_validator()
        result = v.validate(
            code="000651",
            direction="buy",
            amount=50_000,       # 5%总资产，< 15%限额
            price=100.0,
            pre_close=98.0,      # 100 <= 98*1.05=102.9 ✓
            industry="家电",
        )
        assert result.passed is True
        assert result.failed_checks == []

    def test_sell_order_passes_price_check(self):
        """卖单不做价格容差检查，即使价格低也通过。"""
        v = make_validator()
        result = v.validate(
            code="600519",
            direction="sell",
            amount=60_000,
            price=50.0,         # 比前收低，但卖单不检查
            pre_close=1800.0,
            industry="白酒",
        )
        assert v.CHECK_PRICE_TOLERANCE not in result.failed_checks
        # 验证price_tolerance是PASS
        assert result.details[v.CHECK_PRICE_TOLERANCE].startswith("PASS")


class TestSingleOrderSize:
    """检查1: 单笔订单 < 总资产15%。"""

    def test_reject_over_15pct(self):
        """单笔15万 = 15% = 触发限额(要求<15%)。"""
        v = make_validator()
        result = v.validate(
            code="000651", direction="buy",
            amount=150_000,     # 15% >= 15% FAIL
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_SINGLE_ORDER_SIZE in result.failed_checks
        assert result.passed is False

    def test_pass_under_15pct(self):
        """单笔14.9万 < 15%通过。"""
        v = make_validator()
        result = v.validate(
            code="000651", direction="buy",
            amount=149_999,
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_SINGLE_ORDER_SIZE not in result.failed_checks

    def test_boundary_just_under(self):
        """边界：14.99万 < 15万通过。"""
        v = make_validator()
        result = v.validate(
            code="000651", direction="buy",
            amount=149_990,
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_SINGLE_ORDER_SIZE not in result.failed_checks

    def test_custom_threshold(self):
        """自定义上限10%：单笔10万刚好触发。"""
        v = make_validator(single_order_pct=0.10)
        result = v.validate(
            code="000651", direction="buy",
            amount=100_000,     # 10% >= 10% FAIL
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_SINGLE_ORDER_SIZE in result.failed_checks


class TestPriceTolerance:
    """检查2: 买入价不超过前收盘×1.05。"""

    def test_reject_above_1_05(self):
        """买入价 > 前收×1.05 拒绝。"""
        v = make_validator()
        result = v.validate(
            code="000651", direction="buy",
            amount=50_000,
            price=106.0,        # 106 > 100*1.05=105 FAIL
            pre_close=100.0,
            industry="家电",
        )
        assert v.CHECK_PRICE_TOLERANCE in result.failed_checks

    def test_pass_at_1_05(self):
        """买入价 = 前收×1.05 通过（≤）。"""
        v = make_validator()
        result = v.validate(
            code="000651", direction="buy",
            amount=50_000,
            price=105.0,        # 105 == 100*1.05 PASS (<=)
            pre_close=100.0,
            industry="家电",
        )
        assert v.CHECK_PRICE_TOLERANCE not in result.failed_checks

    def test_skip_when_no_pre_close(self):
        """无前收盘价时跳过检查（宽松处理）。"""
        v = make_validator()
        result = v.validate(
            code="000651", direction="buy",
            amount=50_000,
            price=999.0,
            pre_close=None,
            industry="家电",
        )
        assert v.CHECK_PRICE_TOLERANCE not in result.failed_checks

    def test_skip_for_sell(self):
        """卖单跳过价格检查。"""
        v = make_validator()
        result = v.validate(
            code="600519", direction="sell",
            amount=50_000,
            price=10000.0,      # 极高价格但是卖单
            pre_close=100.0,
            industry="白酒",
        )
        assert v.CHECK_PRICE_TOLERANCE not in result.failed_checks


class TestIndustryConcentration:
    """检查3: 单行业持仓≤25%。"""

    def test_reject_over_industry_cap(self):
        """银行: 已有6%，再买20%=26% > 25% 拒绝。"""
        v = make_validator()
        result = v.validate(
            code="600036", direction="buy",
            amount=200_000,     # 20%，银行现有6%+20%=26% FAIL
            price=50.0, pre_close=49.0,
            industry="银行",
        )
        assert v.CHECK_INDUSTRY_CONCENTRATION in result.failed_checks

    def test_pass_under_industry_cap(self):
        """银行: 已有6%，再买18%=24% <= 25% 通过。"""
        v = make_validator()
        result = v.validate(
            code="600036", direction="buy",
            amount=180_000,     # 18%，银行现有6%+18%=24% PASS
            price=50.0, pre_close=49.0,
            industry="银行",
        )
        assert v.CHECK_INDUSTRY_CONCENTRATION not in result.failed_checks

    def test_new_industry_full_cap(self):
        """新行业(无现有持仓)：买26%超上限。"""
        v = make_validator()
        result = v.validate(
            code="000651", direction="buy",
            amount=260_000,     # 26%家电，无现有持仓 FAIL
            price=100.0, pre_close=99.0,
            industry="家电",
        )
        assert v.CHECK_INDUSTRY_CONCENTRATION in result.failed_checks


class TestDailyLossLimit:
    """检查4: 日亏损>3%停止下单。"""

    def test_reject_on_daily_loss_3pct(self):
        """当日亏损3% = 等于阈值，触发停单。"""
        v = make_validator(daily_return=-0.03)
        result = v.validate(
            code="000651", direction="buy",
            amount=50_000,
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_DAILY_LOSS_LIMIT in result.failed_checks

    def test_reject_on_daily_loss_above_3pct(self):
        """当日亏损4% > 3%阈值，触发停单。"""
        v = make_validator(daily_return=-0.04)
        result = v.validate(
            code="000651", direction="buy",
            amount=50_000,
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_DAILY_LOSS_LIMIT in result.failed_checks
        assert result.passed is False

    def test_pass_under_daily_loss_threshold(self):
        """当日亏损2.9% < 3%阈值，通过。"""
        v = make_validator(daily_return=-0.029)
        result = v.validate(
            code="000651", direction="buy",
            amount=50_000,
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_DAILY_LOSS_LIMIT not in result.failed_checks

    def test_pass_on_positive_day(self):
        """当日盈利，通过。"""
        v = make_validator(daily_return=0.01)
        result = v.validate(
            code="000651", direction="buy",
            amount=50_000,
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_DAILY_LOSS_LIMIT not in result.failed_checks


class TestSingleStockLimit:
    """检查5: 单股持仓<总资产10%。"""

    def test_reject_over_10pct(self):
        """600519已有7%，再买4%=11% >= 10% 拒绝。"""
        v = make_validator()
        result = v.validate(
            code="600519", direction="buy",
            amount=40_000,      # 4%，现有7%+4%=11% FAIL
            price=1800.0, pre_close=1750.0, industry="白酒",
        )
        assert v.CHECK_SINGLE_STOCK_LIMIT in result.failed_checks

    def test_pass_under_10pct(self):
        """600519已有7%，再买2%=9% < 10% 通过。"""
        v = make_validator()
        result = v.validate(
            code="600519", direction="buy",
            amount=20_000,      # 2%，现有7%+2%=9% PASS
            price=1800.0, pre_close=1750.0, industry="白酒",
        )
        assert v.CHECK_SINGLE_STOCK_LIMIT not in result.failed_checks

    def test_new_stock_full_cap(self):
        """新股(无现有持仓)：直接买11% 拒绝。"""
        v = make_validator()
        result = v.validate(
            code="000651", direction="buy",
            amount=110_000,     # 11% FAIL
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_SINGLE_STOCK_LIMIT in result.failed_checks


class TestMultipleFailures:
    """多项同时失败场景。"""

    def test_daily_loss_and_order_size_both_fail(self):
        """当日亏损4% + 单笔20万(20%>15%)：两项都失败。"""
        v = make_validator(daily_return=-0.04)
        result = v.validate(
            code="000651", direction="buy",
            amount=200_000,
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert v.CHECK_SINGLE_ORDER_SIZE in result.failed_checks
        assert v.CHECK_DAILY_LOSS_LIMIT in result.failed_checks
        assert result.passed is False
        assert len(result.failed_checks) >= 2

    def test_details_populated_on_fail(self):
        """失败时details包含所有检查的说明信息。"""
        v = make_validator(daily_return=-0.05)
        result = v.validate(
            code="000651", direction="buy",
            amount=50_000,
            price=100.0, pre_close=99.0, industry="家电",
        )
        assert len(result.details) == 5
        for check_name in [
            v.CHECK_SINGLE_ORDER_SIZE,
            v.CHECK_PRICE_TOLERANCE,
            v.CHECK_INDUSTRY_CONCENTRATION,
            v.CHECK_DAILY_LOSS_LIMIT,
            v.CHECK_SINGLE_STOCK_LIMIT,
        ]:
            assert check_name in result.details


class TestValidationResult:
    """ValidationResult数据类测试。"""

    def test_result_immutable(self):
        """ValidationResult是frozen dataclass，不可修改。"""
        result = ValidationResult(passed=True, failed_checks=[], details={})
        with pytest.raises((AttributeError, TypeError)):
            result.passed = False  # type: ignore[misc]

    def test_result_fields(self):
        """验证字段正确填充。"""
        result = ValidationResult(
            passed=False,
            failed_checks=["check_1"],
            details={"check_1": "FAIL: test"},
        )
        assert result.passed is False
        assert "check_1" in result.failed_checks
        assert result.details["check_1"] == "FAIL: test"


class TestInitValidation:
    """初始化参数验证。"""

    def test_invalid_total_value_raises(self):
        """total_value<=0时抛出ValueError。"""
        with pytest.raises(ValueError, match="total_value"):
            PreTradeValidator(
                total_value=0,
                current_positions={},
                industry_map={},
                daily_return=0.0,
            )
