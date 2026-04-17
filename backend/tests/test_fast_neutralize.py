"""fast_neutralize correctness tests — 验证向量化重构后的数学等价性。

测试策略:
  1. 参考实现: 内联OLD版本(Python for循环)作为"已知正确的baseline"
  2. 新实现: fast_neutralize内部 _mad_winsorize + _wls_neutralize + _zscore_clip
  3. 数学不变量: mean≈0, |std|∈[0.5, 2], |value|≤3
  4. 确定性: 同输入 → 同输出
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from engines.fast_neutralize import (
    _mad_winsorize,
    _wls_neutralize,
    _zscore_clip,
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def synthetic_day():
    """单日合成数据: 500股票, 8行业, 真实市值分布。"""
    np.random.seed(42)
    n = 500
    codes = [f"{600000 + i:06d}.SH" for i in range(n)]
    # 8个行业, 大致均匀
    industries = np.random.choice(
        ["电子", "医药", "银行", "房地产", "汽车", "食品", "化工", "机械"],
        size=n,
    )
    # 市值: 对数正态分布, 小市值多大市值少
    mv = np.exp(np.random.normal(np.log(100e8), 1.5, n))  # median ~100亿
    log_mv = np.log(mv + 1)
    # 因子值: 部分受行业+市值驱动, 部分为alpha
    ind_effect = pd.Series(industries).map(
        {"电子": 0.5, "医药": -0.3, "银行": 0.2, "房地产": -0.4,
         "汽车": 0.1, "食品": 0.3, "化工": -0.1, "机械": -0.2}
    ).values
    mv_effect = (log_mv - log_mv.mean()) * 0.1
    alpha = np.random.normal(0, 1, n)
    values = ind_effect + mv_effect + alpha
    return codes, industries, log_mv, values


# ============================================================
# 核心函数单元测试
# ============================================================


class TestMADWinsorize:
    def test_clips_outliers(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0] + [100.0])  # 100是outlier
        out = _mad_winsorize(x, n_sigma=5.0)
        assert out[-1] < 100.0  # 被截断

    def test_preserves_normal_values(self):
        np.random.seed(0)
        x = np.random.normal(0, 1, 200)
        out = _mad_winsorize(x)
        # 正态分布中95%以上应保持不变
        n_changed = (np.abs(out - x) > 1e-10).sum()
        assert n_changed < 10

    def test_preserves_nan(self):
        x = np.array([1.0, np.nan, 3.0, np.nan])
        out = _mad_winsorize(x)
        assert np.isnan(out[1]) and np.isnan(out[3])
        assert out[0] == 1.0 and out[2] == 3.0

    def test_handles_too_few_valid(self):
        x = np.array([1.0, np.nan, np.nan])  # 少于5个valid
        out = _mad_winsorize(x)
        # 应该原样返回
        assert out[0] == 1.0


class TestWLSNeutralize:
    def test_removes_industry_effect(self, synthetic_day):
        """验证WLS消除行业效应 — N-1个非参照类别加权残差≈0。

        注: pd.get_dummies(drop_first=True)会丢一个参照类别, 该类别残差不受约束。
        """
        codes, industries, log_mv, values = synthetic_day
        out = _wls_neutralize(values, industries, log_mv)

        weights = np.sqrt(np.exp(log_mv))
        all_industries = sorted(np.unique(industries))
        n_ind = len(all_industries)

        # 计算每个行业的加权残差均值
        weighted_means = {}
        for ind_name in all_industries:
            mask = industries == ind_name
            if mask.sum() < 5:
                continue
            valid = ~np.isnan(out[mask])
            if valid.sum() < 5:
                continue
            w_ind = weights[mask][valid]
            weighted_means[ind_name] = np.sum(
                out[mask][valid] * w_ind
            ) / w_ind.sum()

        # WLS保证: 至少 N-1 个非参照类别的加权均值接近0
        small_count = sum(1 for v in weighted_means.values() if abs(v) < 0.3)
        assert small_count >= n_ind - 1, (
            f"只有 {small_count}/{n_ind} 个行业加权残差<0.3, 期望 >={n_ind-1}, "
            f"详情: {weighted_means}"
        )

    def test_removes_size_effect(self, synthetic_day):
        codes, industries, log_mv, values = synthetic_day
        out = _wls_neutralize(values, industries, log_mv)

        # 残差和 log_mv 的相关性应很小
        valid = ~np.isnan(out) & ~np.isnan(log_mv)
        if valid.sum() > 30:
            corr = np.corrcoef(out[valid], log_mv[valid])[0, 1]
            assert abs(corr) < 0.1, f"残差与市值相关性={corr:.3f}, 应<0.1"

    def test_preserves_shape(self, synthetic_day):
        codes, industries, log_mv, values = synthetic_day
        out = _wls_neutralize(values, industries, log_mv)
        assert out.shape == values.shape

    def test_handles_nan_input(self):
        n = 100
        values = np.random.randn(n)
        values[::10] = np.nan  # 10% NaN
        industries = np.array(["A", "B"] * 50)
        log_mv = np.random.randn(n) + 5
        out = _wls_neutralize(values, industries, log_mv)

        # NaN位置仍是NaN
        assert np.isnan(out[::10]).all()
        # 非NaN位置有值
        assert (~np.isnan(out[1::10])).any()

    def test_too_few_valid_falls_back(self):
        values = np.array([1.0, 2.0, np.nan, np.nan])  # 只有2个valid
        industries = np.array(["A", "A", "A", "A"])
        log_mv = np.array([10.0, 11.0, np.nan, np.nan])
        out = _wls_neutralize(values, industries, log_mv)
        # 降级为 values - mean
        assert np.allclose(
            out[:2], values[:2] - np.nanmean(values), equal_nan=True
        )


class TestZScoreClip:
    def test_mean_near_zero(self):
        np.random.seed(1)
        x = np.random.normal(5.0, 2.0, 1000)  # 非标准正态
        out = _zscore_clip(x)
        assert abs(np.nanmean(out)) < 0.05

    def test_std_near_one(self):
        np.random.seed(2)
        x = np.random.normal(0, 5.0, 1000)
        out = _zscore_clip(x)
        # clip后std会略小于1
        assert 0.9 < np.nanstd(out) < 1.1

    def test_clips_at_three(self):
        x = np.array([-10.0, -5.0, 0.0, 5.0, 10.0] * 20)
        out = _zscore_clip(x, clip=3.0)
        assert out.min() >= -3.0 - 1e-10
        assert out.max() <= 3.0 + 1e-10

    def test_constant_input_returns_zeros(self):
        x = np.full(100, 5.0)
        out = _zscore_clip(x)
        assert np.allclose(out, 0.0)


# ============================================================
# 外层管道测试 — 数学不变量 + 对比reference实现
# ============================================================


def _reference_neutralize_pipeline(
    factor_df: pd.DataFrame,
    ind_dict: dict,
    mv_lookup: pd.Series,
) -> list[tuple]:
    """参考实现: 内联OLD版本 (Python for循环逐日), 作为正确性baseline。

    这是优化前的原始逻辑, 用于对比新实现是否等价。
    """
    results = []
    for fname in factor_df["factor_name"].unique():
        fdata = factor_df[factor_df["factor_name"] == fname]
        for dt, group in fdata.groupby("trade_date"):
            codes = group["code"].values
            values = group["raw_value"].values.copy()
            if len(values) < 10:
                continue
            # 每code逐个查找 (OLD方式)
            industries = np.array([ind_dict.get(c, "其他") for c in codes])
            log_mv = np.array([
                np.log(mv_lookup.get((c, dt), np.nan) + 1) for c in codes
            ])
            values = _mad_winsorize(values)
            values = _wls_neutralize(values, industries, log_mv)
            values = _zscore_clip(values)
            for j, code in enumerate(codes):
                if not np.isnan(values[j]):
                    results.append((code, dt, fname, float(values[j])))
    return results


def _new_neutralize_pipeline(
    factor_df: pd.DataFrame,
    ind_dict: dict,
    mv_lookup: pd.Series,
) -> list[tuple]:
    """新实现: 向量化merge + groupby.apply + bulk zip。

    复制 fast_neutralize.py Step 3 核心逻辑, 不走DB。
    """
    ind_series = pd.Series(ind_dict, name="industry")
    if isinstance(mv_lookup, pd.Series):
        mv_df_flat = mv_lookup.reset_index()
        mv_df_flat.columns = ["code", "trade_date", "total_mv"]
    else:
        mv_df_flat = mv_lookup

    results = []
    for fname in factor_df["factor_name"].unique():
        fdata = factor_df[factor_df["factor_name"] == fname].copy()
        if fdata.empty:
            continue
        fdata = fdata.merge(
            ind_series.rename_axis("code").reset_index(),
            on="code", how="left",
        )
        fdata["industry"] = fdata["industry"].fillna("其他")
        fdata = fdata.merge(mv_df_flat, on=["code", "trade_date"], how="left")
        fdata["log_mv"] = np.log(fdata["total_mv"].fillna(0).astype(float) + 1)

        def _neutralize_day(group):
            if len(group) < 10:
                return pd.Series(np.nan, index=group.index)
            values = group["raw_value"].values.copy()
            industries = group["industry"].values
            log_mv = group["log_mv"].values
            values = _mad_winsorize(values)
            values = _wls_neutralize(values, industries, log_mv)
            values = _zscore_clip(values)
            return pd.Series(values, index=group.index)

        fdata["neutral"] = fdata.groupby(
            "trade_date", group_keys=False, sort=False,
        ).apply(_neutralize_day)

        valid = fdata[~fdata["neutral"].isna()]
        if len(valid) > 0:
            results.extend(zip(
                valid["code"].values,
                valid["trade_date"].values,
                [fname] * len(valid),
                valid["neutral"].astype(float).values, strict=False,
            ))
    return results


@pytest.fixture
def synthetic_panel():
    """多日多股合成数据。"""
    np.random.seed(7)
    n_days = 10
    n_stocks = 100
    from datetime import date, timedelta
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(n_days)]
    codes = [f"{600000 + i:06d}.SH" for i in range(n_stocks)]
    industries_all = np.random.choice(
        ["电子", "医药", "银行", "房地产", "汽车", "食品"],
        size=n_stocks,
    )
    ind_dict = dict(zip(codes, industries_all, strict=False))

    # 市值: 每天有波动
    mv_rows = []
    for dt in dates:
        mvs = np.exp(np.random.normal(np.log(100e8), 1.0, n_stocks))
        for code, mv in zip(codes, mvs, strict=False):
            mv_rows.append((code, dt, mv))
    mv_df = pd.DataFrame(mv_rows, columns=["code", "trade_date", "total_mv"])
    mv_lookup = mv_df.set_index(["code", "trade_date"])["total_mv"]

    # 因子值
    factor_rows = []
    for dt in dates:
        vals = np.random.normal(0, 1, n_stocks)
        for code, v in zip(codes, vals, strict=False):
            factor_rows.append((code, dt, "test_factor", v))
    factor_df = pd.DataFrame(
        factor_rows, columns=["code", "trade_date", "factor_name", "raw_value"]
    )

    return factor_df, ind_dict, mv_lookup


class TestPipelineEquivalence:
    """核心: 新实现 vs 参考实现, 结果应数学等价。"""

    def test_same_output_as_reference(self, synthetic_panel):
        factor_df, ind_dict, mv_lookup = synthetic_panel

        ref_results = _reference_neutralize_pipeline(
            factor_df, ind_dict, mv_lookup
        )
        new_results = _new_neutralize_pipeline(
            factor_df, ind_dict, mv_lookup
        )

        assert len(ref_results) == len(new_results), \
            f"行数不一致: ref={len(ref_results)}, new={len(new_results)}"

        # 按 (code, trade_date, factor_name) 排序对比
        ref_sorted = sorted(ref_results, key=lambda r: (r[0], str(r[1]), r[2]))
        new_sorted = sorted(new_results, key=lambda r: (r[0], str(r[1]), r[2]))

        for (rc, rd, rn, rv), (nc, nd, nn, nv) in zip(ref_sorted, new_sorted, strict=False):
            assert rc == nc, f"code mismatch: {rc} vs {nc}"
            assert str(rd) == str(nd), f"date mismatch: {rd} vs {nd}"
            assert rn == nn, "factor_name mismatch"
            assert abs(rv - nv) < 1e-9, (
                f"neutral_value差异太大: ref={rv:.6f}, new={nv:.6f}, "
                f"diff={abs(rv-nv):.2e}"
            )

    def test_math_invariants(self, synthetic_panel):
        """每日输出应满足数学不变量: mean≈0, std∈[0.5, 2], |v|≤3。"""
        factor_df, ind_dict, mv_lookup = synthetic_panel
        results = _new_neutralize_pipeline(factor_df, ind_dict, mv_lookup)

        df = pd.DataFrame(results, columns=["code", "trade_date", "factor_name", "value"])
        for dt, group in df.groupby("trade_date"):
            v = group["value"].values
            assert abs(v.mean()) < 0.2, f"{dt}: mean={v.mean():.3f}, 超过阈值"
            assert 0.5 < v.std() < 2.0, f"{dt}: std={v.std():.3f}, 超出[0.5,2]"
            assert v.min() >= -3.0 - 1e-9, f"{dt}: min={v.min():.3f} < -3"
            assert v.max() <= 3.0 + 1e-9, f"{dt}: max={v.max():.3f} > 3"

    def test_deterministic(self, synthetic_panel):
        """相同输入应产生相同输出 (无随机性)。"""
        factor_df, ind_dict, mv_lookup = synthetic_panel

        r1 = _new_neutralize_pipeline(factor_df, ind_dict, mv_lookup)
        r2 = _new_neutralize_pipeline(factor_df, ind_dict, mv_lookup)

        assert len(r1) == len(r2)
        r1_sorted = sorted(r1, key=lambda r: (r[0], str(r[1])))
        r2_sorted = sorted(r2, key=lambda r: (r[0], str(r[1])))
        for (_, _, _, v1), (_, _, _, v2) in zip(r1_sorted, r2_sorted, strict=False):
            assert v1 == v2, f"非确定性: {v1} vs {v2}"
