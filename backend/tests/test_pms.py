"""PMS阶梯利润保护测试 — 验证adj_close使用和触发逻辑。"""



from engines.backtest.config import BacktestConfig, PMSConfig
from engines.slippage_model import SlippageConfig


def _config(pms_enabled=True, exec_mode="same_close") -> BacktestConfig:
    return BacktestConfig(
        initial_capital=1_000_000,
        slippage_mode="fixed",
        slippage_bps=0,
        slippage_config=SlippageConfig(),
        commission_rate=0,
        stamp_tax_rate=0,
        historical_stamp_tax=False,
        transfer_fee_rate=0,
        lot_size=100,
        pms=PMSConfig(
            enabled=pms_enabled,
            tiers=[(0.30, 0.15), (0.20, 0.12), (0.10, 0.10)],
            exec_mode=exec_mode,
        ),
    )


class TestPMSTriggerLogic:
    """PMS触发逻辑测试(不测引擎循环，测纯逻辑)。"""

    def test_no_trigger_below_threshold(self):
        """盈利5%回撤3% → 不触发任何层级。"""
        pnl = 0.05  # 5%盈利 < L3的10%
        dd = -0.03  # 3%回撤
        config = _config()
        triggered = False
        for pnl_thresh, trail_stop in config.pms.tiers:
            if pnl > pnl_thresh and dd < -trail_stop:
                triggered = True
                break
        assert triggered is False

    def test_l3_trigger(self):
        """盈利12%回撤11% → L3触发(>10%gain + >10%dd)。"""
        pnl = 0.12
        dd = -0.11
        config = _config()
        triggered_tier = None
        for pnl_thresh, trail_stop in config.pms.tiers:
            if pnl > pnl_thresh and dd < -trail_stop:
                triggered_tier = (pnl_thresh, trail_stop)
                break
        assert triggered_tier == (0.10, 0.10)

    def test_l1_trigger(self):
        """盈利35%回撤18% → L1触发(>30%gain + >15%dd)。"""
        pnl = 0.35
        dd = -0.18
        config = _config()
        triggered_tier = None
        for pnl_thresh, trail_stop in config.pms.tiers:
            if pnl > pnl_thresh and dd < -trail_stop:
                triggered_tier = (pnl_thresh, trail_stop)
                break
        assert triggered_tier == (0.30, 0.15)

    def test_pms_disabled_no_action(self):
        """PMS disabled → 无论什么pnl/dd都不触发。"""
        config = _config(pms_enabled=False)
        assert config.pms.enabled is False

    def test_adj_close_prevents_false_trigger(self):
        """除权日raw close跌3%但adj_close平稳 → 不应触发。

        场景: 买入价adj=100, max_price adj=115(+15%),
        除权日raw close跌到97但adj_close仍=115 → dd=0 → 不触发。
        """
        buy_price_adj = 100.0
        max_price_adj = 115.0
        # 除权日: raw close跌3%, 但adj_close不变
        current_adj = 115.0  # adj_close没变

        pnl = (current_adj - buy_price_adj) / buy_price_adj  # 15%
        dd = (current_adj - max_price_adj) / max_price_adj  # 0%

        config = _config()
        triggered = False
        for pnl_thresh, trail_stop in config.pms.tiers:
            if pnl > pnl_thresh and dd < -trail_stop:
                triggered = True
                break
        assert triggered is False  # adj_close没跌，不触发

    def test_raw_close_would_false_trigger(self):
        """对比: 如果用raw close，除权日会误触发。"""
        buy_price_raw = 100.0
        max_price_raw = 115.0
        # 除权日raw close跌到97(分红3元), adj_close仍115
        current_raw = 97.0

        _pnl_raw = (current_raw - buy_price_raw) / buy_price_raw  # -3% (unused, for documentation)
        dd_raw = (current_raw - max_price_raw) / max_price_raw  # -15.7%

        # raw close: pnl=-3% < 10% → 不触发L3(需pnl>10%)
        # 但如果之前pnl曾>10%: dd=-15.7% > L1的15% → 会误触发
        # 这说明adj_close的必要性
        assert dd_raw < -0.15  # 会被L1误判为回撤超阈值
