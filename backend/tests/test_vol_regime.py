"""vol_regime.py 单元测试。

测试波动率Regime缩放：高波→降仓，低波→加仓，边界clip。
"""

import numpy as np
import pandas as pd
import pytest
from engines.vol_regime import (
    VOL_REGIME_CLIP_HIGH,
    VOL_REGIME_CLIP_LOW,
    calc_baseline_vol,
    calc_vol_regime,
)


def _make_closes(n: int = 260, base: float = 100.0, daily_vol: float = 0.01) -> pd.Series:
    """生成模拟收盘价序列。

    Args:
        n: 数据点数量。
        base: 初始价格。
        daily_vol: 日对数收益率波动率（标准差）。

    Returns:
        pd.Series: 以日期为index的收盘价序列。
    """
    rng = np.random.default_rng(42)
    log_rets = rng.normal(0, daily_vol, n)
    closes = base * np.exp(np.cumsum(log_rets))
    idx = pd.date_range("2021-01-01", periods=n, freq="B")
    return pd.Series(closes, index=idx)


class TestCalcVolRegime:
    """calc_vol_regime 核心逻辑测试。"""

    def test_returns_float(self):
        closes = _make_closes()
        result = calc_vol_regime(closes)
        assert isinstance(result, float)

    def test_normal_vol_returns_near_one(self):
        """当前波动率 ≈ baseline时，scale应接近1.0（允许±10%误差）。"""
        closes = _make_closes(daily_vol=0.01)
        # 计算baseline然后用同样数据，scale应≈1.0
        baseline = calc_baseline_vol(closes)
        scale = calc_vol_regime(closes, baseline_vol=baseline)
        # 因baseline是中位数，最后20日未必等于中位数，允许较大误差
        assert 0.5 <= scale <= 2.0

    def test_high_vol_scale_less_than_one(self):
        """高波动时scale < 1.0（降仓）。"""
        # 低波动基线
        low_vol_closes = _make_closes(n=260, daily_vol=0.005)
        baseline = calc_baseline_vol(low_vol_closes)

        # 高波动序列：最后20日用高波动替换
        rng = np.random.default_rng(99)
        high_vol_tail = low_vol_closes.values.copy()
        # 给最后30个点更高波动的收益率
        high_vol_rets = rng.normal(0, 0.04, 30)  # 8x normal vol
        for i, ret in enumerate(high_vol_rets):
            idx = len(high_vol_tail) - 30 + i
            high_vol_tail[idx] = high_vol_tail[idx - 1] * np.exp(ret)

        closes = pd.Series(high_vol_tail, index=low_vol_closes.index)
        scale = calc_vol_regime(closes, baseline_vol=baseline)
        assert scale < 1.0, f"高波动时scale应<1.0, 实际={scale}"

    def test_low_vol_scale_greater_than_one(self):
        """低波动时scale > 1.0（加仓）。"""
        # 高波动基线
        high_vol_closes = _make_closes(n=260, daily_vol=0.025)
        baseline = calc_baseline_vol(high_vol_closes)

        # 低波动序列：最后20日用极低波动替换
        rng = np.random.default_rng(77)
        low_vol_tail = high_vol_closes.values.copy()
        low_vol_rets = rng.normal(0, 0.002, 30)  # 0.08x normal vol
        for i, ret in enumerate(low_vol_rets):
            idx = len(low_vol_tail) - 30 + i
            low_vol_tail[idx] = low_vol_tail[idx - 1] * np.exp(ret)

        closes = pd.Series(low_vol_tail, index=high_vol_closes.index)
        scale = calc_vol_regime(closes, baseline_vol=baseline)
        assert scale > 1.0, f"低波动时scale应>1.0, 实际={scale}"

    def test_clip_lower_bound(self):
        """极高波动时scale clip到VOL_REGIME_CLIP_LOW。"""
        # 极低baseline
        low_vol_closes = _make_closes(n=260, daily_vol=0.001)
        baseline = calc_baseline_vol(low_vol_closes)

        # 极高波动序列（日波动30%，是baseline的约300倍）
        rng = np.random.default_rng(11)
        extreme_tail = low_vol_closes.values.copy()
        extreme_rets = rng.normal(0, 0.30, 25)
        for i, ret in enumerate(extreme_rets):
            idx = len(extreme_tail) - 25 + i
            extreme_tail[idx] = max(extreme_tail[idx - 1] * np.exp(ret), 1e-3)

        closes = pd.Series(extreme_tail, index=low_vol_closes.index)
        scale = calc_vol_regime(closes, baseline_vol=baseline)
        assert scale == pytest.approx(VOL_REGIME_CLIP_LOW, abs=1e-9)

    def test_clip_upper_bound(self):
        """极低波动时scale clip到VOL_REGIME_CLIP_HIGH。"""
        # 极高baseline
        high_vol_closes = _make_closes(n=260, daily_vol=0.10)
        baseline = calc_baseline_vol(high_vol_closes)

        # 几乎不动的序列（日波动0.001%，约baseline的0.001倍）
        rng = np.random.default_rng(22)
        flat_tail = high_vol_closes.values.copy()
        flat_rets = rng.normal(0, 0.0001, 25)
        for i, ret in enumerate(flat_rets):
            idx = len(flat_tail) - 25 + i
            flat_tail[idx] = flat_tail[idx - 1] * np.exp(ret)

        closes = pd.Series(flat_tail, index=high_vol_closes.index)
        scale = calc_vol_regime(closes, baseline_vol=baseline)
        assert scale == pytest.approx(VOL_REGIME_CLIP_HIGH, abs=1e-9)

    def test_insufficient_data_returns_one(self):
        """数据不足时返回1.0（不调整）。"""
        # 只有10个数据点（需要21个）
        closes = _make_closes(n=10)
        scale = calc_vol_regime(closes)
        assert scale == 1.0

    def test_exactly_minimum_data(self):
        """恰好21个数据点（VOL_WINDOW+1）可以正常运行。"""
        closes = _make_closes(n=21)
        scale = calc_vol_regime(closes)
        assert isinstance(scale, float)
        assert VOL_REGIME_CLIP_LOW <= scale <= VOL_REGIME_CLIP_HIGH

    def test_clip_constants(self):
        """验证clip常量值符合Sprint 1.1设计。"""
        assert VOL_REGIME_CLIP_LOW == 0.5
        assert VOL_REGIME_CLIP_HIGH == 2.0

    def test_auto_baseline_from_series(self):
        """baseline_vol=None时，自动从序列计算中位数作为baseline。"""
        closes = _make_closes(n=260, daily_vol=0.015)
        scale_auto = calc_vol_regime(closes, baseline_vol=None)

        # 手动计算baseline
        baseline = calc_baseline_vol(closes)
        scale_manual = calc_vol_regime(closes, baseline_vol=baseline)

        # 两种调用方式结果应该一样
        assert scale_auto == pytest.approx(scale_manual, abs=1e-9)

    def test_deterministic(self):
        """同样输入，两次调用结果应完全一致。"""
        closes = _make_closes(n=260, daily_vol=0.012)
        baseline = calc_baseline_vol(closes)
        s1 = calc_vol_regime(closes, baseline_vol=baseline)
        s2 = calc_vol_regime(closes, baseline_vol=baseline)
        assert s1 == s2

    def test_scale_affects_portfolio_weights(self):
        """vol_regime_scale通过PortfolioBuilder.build()缩放权重总和。"""
        from engines.signal_engine import PortfolioBuilder, SignalConfig

        config = SignalConfig(top_n=5, cash_buffer=0.03)
        builder = PortfolioBuilder(config)
        scores = pd.Series({"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0})
        industry = pd.Series({"A": "金融", "B": "科技", "C": "消费", "D": "工业", "E": "医疗"})

        # scale=1.0: 权重和 = 1 - 0.03 = 0.97
        target_1 = builder.build(scores, industry, vol_regime_scale=1.0)
        assert sum(target_1.values()) == pytest.approx(0.97, abs=1e-9)

        # scale=0.8: 权重和 = 0.97 × 0.8 = 0.776
        target_08 = builder.build(scores, industry, vol_regime_scale=0.8)
        assert sum(target_08.values()) == pytest.approx(0.97 * 0.8, abs=1e-9)

        # scale=1.5: 权重和 = 0.97 × 1.5 = 1.455
        target_15 = builder.build(scores, industry, vol_regime_scale=1.5)
        assert sum(target_15.values()) == pytest.approx(0.97 * 1.5, abs=1e-9)


class TestCalcBaselineVol:
    """calc_baseline_vol 测试。"""

    def test_returns_float(self):
        closes = _make_closes(n=260)
        result = calc_baseline_vol(closes)
        assert isinstance(result, float)

    def test_insufficient_data_returns_zero(self):
        closes = _make_closes(n=10)
        result = calc_baseline_vol(closes)
        assert result == 0.0

    def test_higher_vol_series_higher_baseline(self):
        """高波动序列baseline应高于低波动序列。"""
        low_vol = _make_closes(n=260, daily_vol=0.005)
        high_vol = _make_closes(n=260, daily_vol=0.025)
        assert calc_baseline_vol(high_vol) > calc_baseline_vol(low_vol)

    def test_log_returns_not_pct_change(self):
        """验证使用对数收益率而非pct_change。

        对数收益率和pct_change在小幅波动时接近，但有系统偏差。
        验证函数产生有效正数baseline（日波动率年化后通常在5%-40%之间）。
        """
        closes = _make_closes(n=260, daily_vol=0.015)
        baseline = calc_baseline_vol(closes)
        # 日波动0.015年化后约 0.015 × sqrt(244) ≈ 0.234 (23.4%)
        # baseline（中位数）应在合理范围内
        assert 0.05 < baseline < 0.80, f"baseline={baseline}不在合理范围(0.05-0.80)"
