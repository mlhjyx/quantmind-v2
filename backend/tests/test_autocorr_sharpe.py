"""自相关调整Sharpe测试。

验证 autocorr_adjusted_sharpe() 的四种边界场景:
1. 零自相关序列 → adjusted ≈ raw
2. 正自相关(ρ≈0.3) → adjusted < raw
3. 负自相关 → 返回raw不调整，rho返回0
4. 常数序列 → 处理边界条件，返回(0.0, 0.0)

参考: Lo (2002) "The Statistics of Sharpe Ratios"
"""

import numpy as np
import pandas as pd
from engines.metrics import autocorr_adjusted_sharpe


def _make_ar1_series(n: int, rho: float, seed: int = 42) -> pd.Series:
    """生成AR(1)序列：r_t = rho * r_{t-1} + ε_t。

    用于构造具有精确自相关系数的测试序列。
    """
    rng = np.random.RandomState(seed)
    eps = rng.normal(0, 1, n)
    series = np.zeros(n)
    series[0] = eps[0]
    for t in range(1, n):
        series[t] = rho * series[t - 1] + np.sqrt(1 - rho**2) * eps[t]
    # 加正均值使Sharpe > 0，更接近真实收益序列
    series = series * 0.02 + 0.005
    return pd.Series(series)


class TestAutocorrAdjustedSharpe:
    """autocorr_adjusted_sharpe() 正确性测试。"""

    def test_zero_autocorr_adjusted_approx_raw(self) -> None:
        """零自相关序列：adjusted ≈ raw（允许5%误差）。

        当 ρ ≈ 0 时，sqrt((1-ρ)/(1+ρ)) ≈ 1，调整前后基本相等。
        """
        returns = _make_ar1_series(n=500, rho=0.0, seed=1)
        adj, rho = autocorr_adjusted_sharpe(returns, periods_per_year=244)

        raw_sharpe = float(returns.mean() / returns.std() * np.sqrt(244))

        # 实测ρ会有抽样误差，不一定恰好为0
        # 如果ρ>0则adjusted应略小于raw；如果ρ<=0则adjusted==raw
        if rho > 0:
            assert adj <= raw_sharpe + 1e-9
        else:
            # ρ<=0时不调整，返回raw
            assert abs(adj - raw_sharpe) < 1e-9
            assert rho == 0.0

        # 无论哪种情况，偏差应在5%以内
        assert abs(adj - raw_sharpe) / (abs(raw_sharpe) + 1e-9) < 0.05

    def test_positive_autocorr_adjusted_less_than_raw(self) -> None:
        """正自相关(ρ≈0.3) → adjusted < raw。

        AR(1) with ρ=0.3，长序列样本ρ收敛到0.3。
        调整系数 sqrt((1-0.3)/(1+0.3)) ≈ 0.733，adjusted应明显小于raw。
        """
        returns = _make_ar1_series(n=1000, rho=0.3, seed=2)
        adj, rho = autocorr_adjusted_sharpe(returns, periods_per_year=244)

        raw_sharpe = float(returns.mean() / returns.std() * np.sqrt(244))

        # 样本ρ应在0.2-0.4之间
        assert 0.15 < rho < 0.45, f"Expected rho ~0.3, got {rho:.3f}"

        # adjusted < raw
        assert adj < raw_sharpe, (
            f"Expected adjusted ({adj:.3f}) < raw ({raw_sharpe:.3f})"
        )

        # 调整量应与理论接近：adjusted ≈ raw * sqrt((1-rho)/(1+rho))
        expected_adj = raw_sharpe * np.sqrt((1 - rho) / (1 + rho))
        assert abs(adj - expected_adj) < 1e-9

    def test_negative_autocorr_returns_raw(self) -> None:
        """负自相关(ρ<0) → 不惩罚，返回raw Sharpe，rho返回0。

        负自相关意味着收益序列有均值回归特性，不应降低Sharpe。
        """
        returns = _make_ar1_series(n=800, rho=-0.3, seed=3)
        adj, rho = autocorr_adjusted_sharpe(returns, periods_per_year=244)

        raw_sharpe = float(returns.mean() / returns.std() * np.sqrt(244))

        # 应返回原始Sharpe
        assert abs(adj - raw_sharpe) < 1e-9, (
            f"Negative autocorr: expected adj ({adj:.3f}) == raw ({raw_sharpe:.3f})"
        )
        # rho应返回0（不暴露负值）
        assert rho == 0.0

    def test_constant_series_returns_zero(self) -> None:
        """常数序列 → 标准差为0，返回(0.0, 0.0)。"""
        returns = pd.Series([0.01] * 100)
        adj, rho = autocorr_adjusted_sharpe(returns, periods_per_year=244)

        assert adj == 0.0
        assert rho == 0.0

    def test_too_short_series(self) -> None:
        """序列长度<3 → 返回(0.0, 0.0)。"""
        returns = pd.Series([0.01, 0.02])
        adj, rho = autocorr_adjusted_sharpe(returns, periods_per_year=244)

        assert adj == 0.0
        assert rho == 0.0

    def test_monthly_periods(self) -> None:
        """月度频率参数(periods_per_year=12)。

        月度调仓策略用 periods_per_year=12 时，年化Sharpe应与日频不同。
        """
        returns = _make_ar1_series(n=120, rho=0.15, seed=4)  # 10年月度数据
        adj, rho = autocorr_adjusted_sharpe(returns, periods_per_year=12)

        raw_sharpe = float(returns.mean() / returns.std() * np.sqrt(12))

        # ρ>0时adjusted < raw
        if rho > 0:
            assert adj < raw_sharpe
        else:
            assert abs(adj - raw_sharpe) < 1e-9

    def test_adjustment_formula_correctness(self) -> None:
        """公式验证：手动计算与函数输出完全一致。"""
        returns = _make_ar1_series(n=600, rho=0.25, seed=5)
        adj, rho = autocorr_adjusted_sharpe(returns, periods_per_year=244)

        raw_sharpe = float(returns.mean() / returns.std() * np.sqrt(244))

        if rho > 0:
            expected = raw_sharpe * np.sqrt((1 - rho) / (1 + rho))
            assert abs(adj - expected) < 1e-9, (
                f"Formula mismatch: adj={adj:.6f}, expected={expected:.6f}"
            )
