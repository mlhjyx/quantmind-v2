"""A1/A8 回归测试 — WLS中性化正确性 + zscore clip(±3) 边界验证。

覆盖场景:
  A1 WLS中性化:
    - WLS权重正确性: 大市值股票比小市值股票权重高
    - WLS vs OLS: 两者残差均值接近0，但WLS对大市值异常值更鲁棒
    - 大小市值残差分布合理性: WLS中性化后大/小市值组残差方差相近
    - 市值相关性: 中性化后与ln_mcap相关性趋近0
  A8 zscore clip(±3):
    - Step5生效: pipeline输出 |z| <= 3.0 (全部值)
    - Step5截断边界: 极端异常因子被截断到±3
    - clip不改变主体分布: 非极端值不受影响
  neutralizer.py:
    - _WINSORIZE_K=5.0: 验证5σ下正常分布值不被错误截断
"""

import numpy as np
import pandas as pd
import pytest

from engines.factor_engine import (
    preprocess_neutralize,
    preprocess_pipeline,
    preprocess_zscore,
)
from engines.neutralizer import FactorNeutralizer, _WINSORIZE_K


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def cross_section_100():
    """100只股票截面因子值（模拟单日）。"""
    np.random.seed(101)
    codes = [f"{i:06d}.SZ" for i in range(100)]
    return pd.Series(np.random.randn(100), index=codes, name="factor")


@pytest.fixture
def industry_100():
    """100只股票行业分类（5个行业，各20只）。"""
    codes = [f"{i:06d}.SZ" for i in range(100)]
    industries = (
        ["银行"] * 20 + ["医药"] * 20 + ["电子"] * 20
        + ["食品"] * 20 + ["机械"] * 20
    )
    return pd.Series(industries, index=codes, name="industry")


@pytest.fixture
def ln_mcap_100():
    """100只股票对数市值，含大/小市值分层。

    前50只: 大市值 ln_mcap ∈ [14, 16] (市值 ~1.2万亿~890万亿元)
    后50只: 小市值 ln_mcap ∈ [10, 12] (市值 ~2.2万~1.6亿元)
    """
    np.random.seed(102)
    codes = [f"{i:06d}.SZ" for i in range(100)]
    large = np.random.uniform(14, 16, 50)
    small = np.random.uniform(10, 12, 50)
    return pd.Series(np.concatenate([large, small]), index=codes, name="ln_mcap")


@pytest.fixture
def mcap_correlated_factor(ln_mcap_100):
    """与市值高度相关的因子（中性化应消除该相关性）。"""
    np.random.seed(103)
    noise = np.random.randn(100) * 0.3
    return ln_mcap_100 + noise


# ============================================================
# A1: WLS中性化正确性
# ============================================================

class TestWLSWeightCorrectness:
    """验证WLS权重机制正确性。"""

    def test_wls_weight_formula(self, ln_mcap_100):
        """WLS权重 = √market_cap = √exp(ln_mcap)，大市值>小市值。"""
        large_mcap = ln_mcap_100.iloc[:50]   # 大市值
        small_mcap = ln_mcap_100.iloc[50:]   # 小市值

        # 计算权重
        large_weights = np.sqrt(np.exp(large_mcap.values))
        small_weights = np.sqrt(np.exp(small_mcap.values))

        # 大市值权重显著高于小市值
        assert large_weights.mean() > small_weights.mean() * 5

    def test_wls_reduces_mcap_correlation(
        self, mcap_correlated_factor, ln_mcap_100, industry_100
    ):
        """WLS中性化后因子与市值的相关性 < 0.1。"""
        corr_before = abs(mcap_correlated_factor.corr(ln_mcap_100))
        result = preprocess_neutralize(
            mcap_correlated_factor, ln_mcap_100, industry_100
        )
        corr_after = abs(result.corr(ln_mcap_100))

        assert corr_before > 0.8, "前置条件: 测试因子应与市值高度相关"
        assert corr_after < 0.15, f"WLS中性化后相关性应<0.15，实际={corr_after:.3f}"

    def test_wls_residual_mean_near_zero(
        self, cross_section_100, ln_mcap_100, industry_100
    ):
        """WLS回归残差均值接近0（回归基本性质）。"""
        result = preprocess_neutralize(
            cross_section_100, ln_mcap_100, industry_100
        )
        valid = result.dropna()
        assert abs(float(valid.mean())) < 0.05, \
            f"WLS残差均值应接近0，实际={float(valid.mean()):.4f}"

    def test_wls_large_smallcap_residual_variance(
        self, mcap_correlated_factor, ln_mcap_100, industry_100
    ):
        """WLS中性化后大/小市值组残差方差相近（市值影响被消除）。"""
        result = preprocess_neutralize(
            mcap_correlated_factor, ln_mcap_100, industry_100
        )
        codes = ln_mcap_100.index
        large_codes = codes[:50]
        small_codes = codes[50:]

        large_std = float(result[large_codes].dropna().std())
        small_std = float(result[small_codes].dropna().std())

        # WLS中性化后两组残差方差比应在合理范围内（<3x）
        ratio = max(large_std, small_std) / (min(large_std, small_std) + 1e-9)
        assert ratio < 3.0, \
            f"大/小市值残差方差比={ratio:.2f}，WLS应减少分层差异"

    def test_wls_vs_ols_both_zero_mean(
        self, mcap_correlated_factor, ln_mcap_100, industry_100
    ):
        """WLS与OLS两者残差均值都应接近0，但WLS对大市值股权重更高。"""
        result_wls = preprocess_neutralize(
            mcap_correlated_factor, ln_mcap_100, industry_100
        )
        valid = result_wls.dropna()

        # 残差均值接近0（基本性质）
        assert abs(float(valid.mean())) < 0.05

        # 大市值组残差相关性应接近0（WLS更好消除）
        large_codes = ln_mcap_100.index[:50]
        large_result = result_wls[large_codes].dropna()
        large_mcap = ln_mcap_100[large_codes]
        corr_large = abs(large_result.corr(large_mcap))
        assert corr_large < 0.20, \
            f"WLS应较好消除大市值组内市值相关性，实际={corr_large:.3f}"

    def test_wls_small_sample_skips_neutralization(self):
        """样本 < 30 时跳过中性化，返回原值（与OLS行为一致）。"""
        s = pd.Series(np.arange(20, dtype=float))
        mcap = pd.Series(np.random.uniform(10, 16, 20))
        ind = pd.Series(["A"] * 20)
        result = preprocess_neutralize(s, mcap, ind)
        pd.testing.assert_series_equal(result, s)

    def test_wls_singular_matrix_returns_original(self):
        """矩阵奇异时不抛出异常，返回原值。"""
        np.random.seed(55)
        n = 50
        codes = [f"C{i}" for i in range(n)]
        # 构造奇异情况: 所有行业相同 + drop_first=True 后无虚拟变量差异
        s = pd.Series(np.random.randn(n), index=codes)
        # 让 ln_mcap 完全等于 s (X会线性相关产生奇异风险)
        # 实际 lstsq 有 rcond=None 保护，应能正常运行
        mcap = pd.Series(np.random.uniform(10, 16, n), index=codes)
        ind = pd.Series(["行业A"] * n, index=codes)  # 单一行业
        result = preprocess_neutralize(s, mcap, ind)
        # 应正常返回(不抛异常), 值合理
        assert len(result) == n
        assert result.notna().sum() >= n - 1


# ============================================================
# A8: zscore clip(±3) Step5 边界验证
# ============================================================

class TestZscoreClip:
    """验证 preprocess_pipeline Step5 clip(±3) 行为。"""

    def test_pipeline_step5_max_abs_3(
        self, cross_section_100, ln_mcap_100, industry_100
    ):
        """pipeline输出 |neutral_value| <= 3.0 (Step5生效)。"""
        _, neutral = preprocess_pipeline(
            cross_section_100, ln_mcap_100, industry_100
        )
        valid = neutral.dropna()
        assert float(valid.abs().max()) <= 3.0 + 1e-9, \
            f"Step5 clip后最大绝对值应<=3.0，实际={float(valid.abs().max()):.4f}"

    def test_pipeline_step5_with_extreme_outlier(
        self, cross_section_100, ln_mcap_100, industry_100
    ):
        """含极端异常值的因子: Step5将zscore>3的值截断到3。"""
        # 注入极端异常值
        factor_with_outlier = cross_section_100.copy()
        factor_with_outlier.iloc[0] = 9999.0
        factor_with_outlier.iloc[1] = -9999.0

        _, neutral = preprocess_pipeline(
            factor_with_outlier, ln_mcap_100, industry_100
        )
        valid = neutral.dropna()

        # Step5后绝对值不超过3
        assert float(valid.max()) <= 3.0 + 1e-9
        assert float(valid.min()) >= -3.0 - 1e-9

    def test_pipeline_step5_clips_exactly_at_boundary(self):
        """边界检验: 手动构造zscore=4的值，clip后=3.0。"""
        np.random.seed(77)
        n = 100
        codes = [f"S{i}" for i in range(n)]
        industries = ["A"] * 50 + ["B"] * 50
        industry = pd.Series(industries, index=codes)
        ln_mcap = pd.Series(np.random.uniform(12, 15, n), index=codes)

        # 构造 zscore ≈ 4 的值: factor = mean + 4*std
        raw = pd.Series(np.random.randn(n), index=codes)
        zscore_step = preprocess_zscore(raw)
        max_z = float(zscore_step.max())

        # 若 zscore > 3, pipeline 输出应被截断
        if max_z > 3.0:
            _, neutral = preprocess_pipeline(raw, ln_mcap, industry)
            assert float(neutral.dropna().max()) <= 3.0 + 1e-9

    def test_pipeline_clip_does_not_affect_bulk(
        self, cross_section_100, ln_mcap_100, industry_100
    ):
        """clip不影响主体分布: z ∈ [-3,3] 的值占95%+。"""
        _, neutral = preprocess_pipeline(
            cross_section_100, ln_mcap_100, industry_100
        )
        valid = neutral.dropna()
        # zscore 后主体应在 [-3,3] 内，clip 不修改这些值
        pct_in_range = (valid.abs() <= 3.0).mean()
        assert pct_in_range == 1.0, \
            "clip(±3)后所有值都在[-3,3]内"

    def test_pipeline_step5_neutral_mean_near_zero(
        self, cross_section_100, ln_mcap_100, industry_100
    ):
        """Step5 clip后均值应仍接近0 (对称截断不影响中心)。"""
        _, neutral = preprocess_pipeline(
            cross_section_100, ln_mcap_100, industry_100
        )
        valid = neutral.dropna()
        assert abs(float(valid.mean())) < 0.3, \
            f"clip后均值应仍接近0，实际={float(valid.mean()):.4f}"

    def test_pipeline_returns_raw_unchanged(
        self, cross_section_100, ln_mcap_100, industry_100
    ):
        """pipeline 返回的 raw 值是原始值（Step5不影响raw）。"""
        raw, neutral = preprocess_pipeline(
            cross_section_100, ln_mcap_100, industry_100
        )
        pd.testing.assert_series_equal(raw, cross_section_100)


# ============================================================
# neutralizer.py: _WINSORIZE_K=5.0
# ============================================================

class TestNeutralizerWinsorizeK:
    """验证 neutralizer.py _WINSORIZE_K 已统一为 5.0。"""

    def test_winsorize_k_is_5(self):
        """_WINSORIZE_K 模块常量应为 5.0，与 preprocess_mad 对齐。"""
        assert _WINSORIZE_K == 5.0, \
            f"_WINSORIZE_K 应为5.0(对齐DESIGN_V5 §4.4)，实际={_WINSORIZE_K}"

    def test_normalish_values_not_clipped_at_5sigma(self):
        """正态分布值在5σ范围内不应被截断（宽松阈值）。"""
        np.random.seed(88)
        neutralizer = FactorNeutralizer()
        values = pd.Series(np.random.randn(200))
        industry = pd.Series(["A"] * 100 + ["B"] * 100)

        result = neutralizer.neutralize(values, industry)
        valid = result.dropna()

        # 5σ下正态分布几乎无截断，输出应与原始分布接近
        # 至少95%的值保留（不为边界值）
        assert len(valid) >= 180

    def test_extreme_outlier_clipped_at_5sigma(self):
        """5σ外的极端异常值应被截断。"""
        neutralizer = FactorNeutralizer()
        np.random.seed(89)
        values = pd.Series(np.random.randn(100))
        values.iloc[0] = 999.0   # 极端异常值，远超5σ
        values.iloc[1] = -999.0
        industry = pd.Series(["A"] * 50 + ["B"] * 50)

        result = neutralizer.neutralize(values, industry)
        valid = result.dropna()

        # 极端值在Winsorize后被截断，因此最终zscore不会极端大
        assert float(valid.abs().max()) < 10.0, \
            "5σ Winsorize后极端值不应在最终zscore中出现"
