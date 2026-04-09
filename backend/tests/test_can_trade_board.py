"""测试 SimBroker.can_trade() 板块差异涨跌停判断。

覆盖场景:
- 主板(沪深): ±10%
- 创业板(300/301开头): ±20%
- 科创板(688开头): ±20%
- ST股(通过symbols_info): ±5%
- 北交所(8/4开头): ±30%
- up_limit/down_limit 数据源字段优先
"""

import pandas as pd
import pytest

from backend.engines.backtest.broker import SimBroker
from backend.engines.backtest.config import BacktestConfig
from backend.engines.backtest.validators import _infer_price_limit


@pytest.fixture
def broker() -> SimBroker:
    config = BacktestConfig(initial_capital=1_000_000)
    return SimBroker(config)


# ============================================================
# _infer_price_limit 单元测试
# ============================================================

class TestInferPriceLimit:
    """测试从股票代码推断涨跌幅。"""

    def test_main_board_sz(self):
        assert _infer_price_limit("000001.SZ") == 0.10

    def test_main_board_sh(self):
        assert _infer_price_limit("600000.SH") == 0.10

    def test_gem_300(self):
        """创业板300开头 → 20%"""
        assert _infer_price_limit("300750.SZ") == 0.20

    def test_gem_301(self):
        """创业板301开头 → 20%"""
        assert _infer_price_limit("301236.SZ") == 0.20

    def test_star_688(self):
        """科创板688开头 → 20%"""
        assert _infer_price_limit("688981.SH") == 0.20

    def test_bse_8(self):
        """北交所8开头 → 30%"""
        assert _infer_price_limit("830799.BJ") == 0.30

    def test_bse_4(self):
        """北交所4开头 → 30%"""
        assert _infer_price_limit("430047.BJ") == 0.30

    def test_pure_code_no_suffix(self):
        """纯数字代码(无交易所后缀) → 正常推断"""
        assert _infer_price_limit("300750") == 0.20
        assert _infer_price_limit("688001") == 0.20
        assert _infer_price_limit("000001") == 0.10


# ============================================================
# can_trade 板块涨跌停集成测试
# ============================================================

def _make_row(**kwargs) -> pd.Series:
    """构造行情数据行。"""
    defaults = {
        "close": 10.0,
        "pre_close": 10.0,
        "volume": 1_000_000,
        "turnover_rate": 5.0,
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


class TestCanTradeMainBoard:
    """主板(沪深) ±10%"""

    def test_normal_trade_allowed(self, broker):
        row = _make_row(close=10.5, pre_close=10.0)
        assert broker.can_trade("000001.SZ", "buy", row) is True

    def test_limit_up_blocked(self, broker):
        """涨停封板(10%) + 低换手 → 买入被拒"""
        row = _make_row(close=11.0, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("000001.SZ", "buy", row) is False

    def test_limit_up_high_turnover_allowed(self, broker):
        """涨停价但高换手 → 允许(未封死)"""
        row = _make_row(close=11.0, pre_close=10.0, turnover_rate=3.0)
        assert broker.can_trade("000001.SZ", "buy", row) is True

    def test_limit_down_blocked(self, broker):
        """跌停封板(10%) + 低换手 → 卖出被拒"""
        row = _make_row(close=9.0, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("000001.SZ", "sell", row) is False

    def test_9pct_rise_not_blocked(self, broker):
        """涨9%不是涨停 → 允许"""
        row = _make_row(close=10.9, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("000001.SZ", "buy", row) is True


class TestCanTradeGEM:
    """创业板(300/301) ±20% — 核心修复验证"""

    def test_15pct_rise_allowed(self, broker):
        """创业板涨15%不是涨停 → 允许买入(修复前会误判)"""
        row = _make_row(close=11.5, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("300750.SZ", "buy", row) is True

    def test_20pct_limit_up_blocked(self, broker):
        """创业板涨停20% + 低换手 → 买入被拒"""
        row = _make_row(close=12.0, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("300750.SZ", "buy", row) is False

    def test_20pct_limit_down_blocked(self, broker):
        """创业板跌停20% + 低换手 → 卖出被拒"""
        row = _make_row(close=8.0, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("300750.SZ", "sell", row) is False

    def test_15pct_drop_sell_allowed(self, broker):
        """创业板跌15%不是跌停 → 允许卖出"""
        row = _make_row(close=8.5, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("300750.SZ", "sell", row) is True

    def test_301_code(self, broker):
        """301开头同样适用20%"""
        row = _make_row(close=11.5, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("301236.SZ", "buy", row) is True


class TestCanTradeSTAR:
    """科创板(688) ±20%"""

    def test_15pct_rise_allowed(self, broker):
        row = _make_row(close=11.5, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("688981.SH", "buy", row) is True

    def test_20pct_limit_up_blocked(self, broker):
        row = _make_row(close=12.0, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("688981.SH", "buy", row) is False


class TestCanTradeST:
    """ST股 ±5% — 通过symbols_info传入"""

    @pytest.fixture
    def st_symbols_info(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"price_limit": [0.05]},
            index=pd.Index(["000001.SZ"], name="code"),
        )

    def test_st_5pct_limit_up(self, broker, st_symbols_info):
        """ST股涨停5% + 低换手 → 买入被拒"""
        row = _make_row(close=10.5, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("000001.SZ", "buy", row, st_symbols_info) is False

    def test_st_3pct_rise_allowed(self, broker, st_symbols_info):
        """ST股涨3%未涨停 → 允许"""
        row = _make_row(close=10.3, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("000001.SZ", "buy", row, st_symbols_info) is True


class TestCanTradeBSE:
    """北交所(8/4开头) ±30%"""

    def test_25pct_rise_allowed(self, broker):
        """北交所涨25%不是涨停 → 允许"""
        row = _make_row(close=12.5, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("830799.BJ", "buy", row) is True

    def test_30pct_limit_up_blocked(self, broker):
        """北交所涨停30% + 低换手 → 买入被拒"""
        row = _make_row(close=13.0, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("830799.BJ", "buy", row) is False


class TestCanTradeDataSourcePriority:
    """up_limit/down_limit数据源字段优先于代码推断"""

    def test_data_field_overrides_inference(self, broker):
        """即使代码是创业板(20%)，数据字段给10%也用数据字段"""
        row = _make_row(
            close=11.0, pre_close=10.0, turnover_rate=0.5,
            up_limit=11.0, down_limit=9.0,
        )
        # up_limit=11.0(10%), close=11.0 → 涨停封板
        assert broker.can_trade("300750.SZ", "buy", row) is False

    def test_data_field_none_falls_back(self, broker):
        """up_limit=None → fallback到代码推断(创业板20%)"""
        row = _make_row(close=11.0, pre_close=10.0, turnover_rate=0.5)
        # 创业板20%涨停价=12.0, close=11.0 → 不是涨停
        assert broker.can_trade("300750.SZ", "buy", row) is True

    def test_suspended_stock(self, broker):
        """停牌(volume=0) → 所有板块都拒绝"""
        row = _make_row(close=10.0, pre_close=10.0, volume=0)
        assert broker.can_trade("300750.SZ", "buy", row) is False
        assert broker.can_trade("000001.SZ", "sell", row) is False
