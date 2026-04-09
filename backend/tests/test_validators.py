"""ValidatorChain + 各Validator测试 — Step 4-A拆分模块。"""

import pandas as pd
from engines.backtest.validators import (
    DataCompletenessValidator,
    PriceLimitValidator,
    SuspensionValidator,
    ValidatorChain,
    _infer_price_limit,
)

# ── _infer_price_limit ───────────────────────────────────


class TestInferPriceLimit:
    def test_main_board_sh(self):
        assert _infer_price_limit("600519.SH") == 0.10

    def test_main_board_sz(self):
        assert _infer_price_limit("000001.SZ") == 0.10

    def test_gem_board(self):
        """创业板 300xxx → ±20%"""
        assert _infer_price_limit("300750.SZ") == 0.20

    def test_star_board(self):
        """科创板 688xxx → ±20%"""
        assert _infer_price_limit("688570.SH") == 0.20

    def test_bj_board_8xx(self):
        """北交所 8xxx → ±30%"""
        assert _infer_price_limit("830946.BJ") == 0.30

    def test_bj_board_4xx(self):
        """北交所 4xxx → ±30%"""
        assert _infer_price_limit("430047.BJ") == 0.30

    def test_bj_suffix(self):
        """北交所 .BJ后缀 → ±30%"""
        assert _infer_price_limit("920175.BJ") == 0.30


# ── SuspensionValidator ──────────────────────────────────


class TestSuspensionValidator:
    def setup_method(self):
        self.v = SuspensionValidator()

    def test_volume_zero_rejected(self):
        row = pd.Series({"volume": 0, "close": 10.0})
        assert self.v.validate("600519.SH", "buy", row) is not None

    def test_volume_positive_passes(self):
        row = pd.Series({"volume": 50000, "close": 10.0})
        assert self.v.validate("600519.SH", "buy", row) is None


# ── DataCompletenessValidator ────────────────────────────


class TestDataCompletenessValidator:
    def setup_method(self):
        self.v = DataCompletenessValidator()

    def test_close_zero_rejected(self):
        row = pd.Series({"close": 0, "pre_close": 10.0})
        assert self.v.validate("600519.SH", "buy", row) is not None

    def test_pre_close_zero_rejected(self):
        row = pd.Series({"close": 10.0, "pre_close": 0})
        assert self.v.validate("600519.SH", "buy", row) is not None

    def test_both_positive_passes(self):
        row = pd.Series({"close": 10.5, "pre_close": 10.0})
        assert self.v.validate("600519.SH", "buy", row) is None


# ── PriceLimitValidator ──────────────────────────────────


class TestPriceLimitValidator:
    def setup_method(self):
        self.v = PriceLimitValidator()

    def test_limit_up_buy_rejected(self):
        """涨停封板 + 低换手 → 买入被拒"""
        row = pd.Series({
            "close": 11.00, "pre_close": 10.00,
            "up_limit": 11.00, "down_limit": 9.00,
            "turnover_rate": 0.5,  # <1%
        })
        reason = self.v.validate("600519.SH", "buy", row)
        assert reason is not None
        assert "涨停" in reason

    def test_limit_down_sell_rejected(self):
        """跌停封板 + 低换手 → 卖出被拒"""
        row = pd.Series({
            "close": 9.00, "pre_close": 10.00,
            "up_limit": 11.00, "down_limit": 9.00,
            "turnover_rate": 0.3,
        })
        reason = self.v.validate("600519.SH", "sell", row)
        assert reason is not None
        assert "跌停" in reason

    def test_normal_price_passes(self):
        """正常价格 → 通过"""
        row = pd.Series({
            "close": 10.50, "pre_close": 10.00,
            "up_limit": 11.00, "down_limit": 9.00,
            "turnover_rate": 5.0,
        })
        assert self.v.validate("600519.SH", "buy", row) is None

    def test_inferred_limit_when_missing(self):
        """无up_limit/down_limit列 → 从code推断"""
        # pd.Series converts None→NaN, 但validator用 `is None` 检查。
        # 只有真正缺列或row.get返回None时才触发推断。
        # 构造不含up_limit列的row来测试推断路径。
        row = pd.Series({
            "close": 11.00, "pre_close": 10.00,
            "turnover_rate": 0.3,
        })
        # 无up_limit列 → row.get("up_limit", None) = None → 推断
        # 主板10%: up_limit = round(10.0*1.1, 2) = 11.00
        # close=11.00 ≈ up_limit=11.00, turnover=0.3<1.0 → 涨停封板
        reason = self.v.validate("600519.SH", "buy", row)
        assert reason is not None


# ── ValidatorChain ───────────────────────────────────────


class TestValidatorChain:
    def test_default_chain_passes_normal(self):
        chain = ValidatorChain()
        row = pd.Series({
            "volume": 50000, "close": 10.5, "pre_close": 10.0,
            "up_limit": 11.0, "down_limit": 9.0, "turnover_rate": 5.0,
        })
        can, reason = chain.can_trade("600519.SH", "buy", row)
        assert can is True
        assert reason is None

    def test_chain_first_fail_stops(self):
        """停牌(第一个validator) → 直接拒绝，不检查后续"""
        chain = ValidatorChain()
        row = pd.Series({
            "volume": 0, "close": 0, "pre_close": 0,
            "up_limit": None, "down_limit": None, "turnover_rate": None,
        })
        can, reason = chain.can_trade("600519.SH", "buy", row)
        assert can is False
        assert "停牌" in reason  # SuspensionValidator先触发

    def test_custom_single_validator(self):
        """自定义单validator链。"""
        chain = ValidatorChain(validators=[SuspensionValidator()])
        # volume>0 → 停牌检测通过, 无其他validator
        row = pd.Series({"volume": 100, "close": 0, "pre_close": 0})
        can, reason = chain.can_trade("600519.SH", "buy", row)
        assert can is True  # SuspensionValidator通过, 无DataCompleteness检查
