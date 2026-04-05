"""行业中性化共享模块 — 替代 factor_onboarding.py 中的截面 zscore 近似。

行业+截面双重中性化流程:
  1. Winsorize: 5σ 截断（MAD 法，与 preprocess_mad 对齐）
  2. 行业内 zscore: 每个行业组内 (value - group_mean) / group_std
  3. 截面 zscore: 全截面再做一次标准化

设计文档:
  - docs/DEV_FACTOR_MINING.md: 因子计算规则（预处理顺序+IC定义）
  - docs/QUANTMIND_V2_DESIGN_V5.md §9.5: 市场状态+行业中性化

铁律2: 因子验证用生产基线+中性化（宪法 §2）

DEPRECATED:
  FactorNeutralizer 用行业内 zscore 近似中性化，不含市值加权回归。
  新代码（有 ln_mcap 可用时）应使用 factor_engine.preprocess_pipeline()，
  其 Step 3 为 WLS 回归（DESIGN_V5 §4.4 标准实现）。
  本模块保留供 factor_onboarding（GP 管道）使用，该路径暂无 ln_mcap 数据。
"""

from __future__ import annotations

import structlog

import numpy as np
import pandas as pd

logger = structlog.get_logger(__name__)

# 行业组内样本数最低阈值，低于此值时 fallback 到截面 zscore
_MIN_INDUSTRY_SIZE: int = 5

# Winsorize 截断倍数（MAD 法）— 对齐 preprocess_mad 的 5σ 标准（DESIGN_V5 §4.4）
_WINSORIZE_K: float = 5.0


class FactorNeutralizer:
    """行业+截面双重中性化器。

    设计为无状态工具类，不依赖 DB 连接，纯 pandas 计算。
    调用方负责传入行业 Series（从 symbols 表 industry_sw1 列查询）。

    典型用法:
        neutralizer = FactorNeutralizer()
        neutral = neutralizer.neutralize(raw_values, industry)
    """

    def neutralize(
        self,
        raw_values: pd.Series,
        industry: pd.Series,
    ) -> pd.Series:
        """行业+截面双重中性化。

        步骤:
          1. Winsorize: MAD 法 3σ 截断（去极值），不改变 NaN
          2. 行业内 zscore: 每个行业组内 (value - group_mean) / group_std，
             行业组样本 < _MIN_INDUSTRY_SIZE 时 fallback 到截面 zscore
          3. 截面 zscore: 全截面再标准化一次

        Args:
            raw_values: 某日的原始因子值，index 为股票代码。
            industry: 对应的申万一级行业标签，index 为股票代码。
                      与 raw_values 的 index 可以不完全对齐，取交集处理。

        Returns:
            neutral_values: 中性化后的因子值 Series，index 同 raw_values。
            NaN 值保持 NaN 不填充。不足 _MIN_INDUSTRY_SIZE 的行业组降级为截面 zscore。
        """
        if raw_values.empty:
            return raw_values.copy()

        # ── Step 0: 对齐 index ─────────────────────────────────────────
        common_idx = raw_values.index.intersection(industry.index)
        if len(common_idx) == 0:
            logger.warning("raw_values 与 industry 无公共 index，返回截面 zscore 近似")
            return self._cross_section_zscore(raw_values)

        values = raw_values.loc[common_idx].copy()
        ind = industry.loc[common_idx]

        # ── Step 1: Winsorize（MAD 法）─────────────────────────────────
        values = self._winsorize_mad(values, k=_WINSORIZE_K)

        # ── Step 2: 行业内 zscore ──────────────────────────────────────
        result = pd.Series(index=values.index, dtype=float)

        # 计算各行业组大小（仅考虑非 NaN 值）
        valid_mask = values.notna()
        valid_values = values[valid_mask]
        valid_ind = ind[valid_mask]

        group_sizes = valid_ind.value_counts()
        large_groups = group_sizes[group_sizes >= _MIN_INDUSTRY_SIZE].index
        small_groups = group_sizes[group_sizes < _MIN_INDUSTRY_SIZE].index

        # 行业组足够大：行业内 zscore
        if len(large_groups) > 0:
            for grp in large_groups:
                mask = (ind == grp) & valid_mask
                grp_vals = values[mask]
                mean_v = float(grp_vals.mean())
                std_v = float(grp_vals.std(ddof=1))
                if std_v < 1e-9:
                    result[mask] = 0.0
                else:
                    result[mask] = (grp_vals - mean_v) / std_v

        # 行业组太小：用截面全局均值/方差 zscore 近似
        if len(small_groups) > 0:
            logger.debug(
                "行业组样本不足（<5），fallback 截面 zscore: 行业=%s",
                list(small_groups),
            )
            all_valid = valid_values
            global_mean = float(all_valid.mean())
            global_std = float(all_valid.std(ddof=1))

            for grp in small_groups:
                mask = (ind == grp) & valid_mask
                grp_vals = values[mask]
                if global_std < 1e-9:
                    result[mask] = 0.0
                else:
                    result[mask] = (grp_vals - global_mean) / global_std

        # NaN 原样保留
        result[~valid_mask] = np.nan

        # ── Step 3: 截面 zscore（全截面再标准化）──────────────────────
        result = self._cross_section_zscore(result)

        # ── 对齐回原始 index（原本不在 common_idx 的保持 NaN）─────────
        output = pd.Series(index=raw_values.index, dtype=float)
        output[common_idx] = result
        return output

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _winsorize_mad(series: pd.Series, k: float = 3.0) -> pd.Series:
        """MAD 法 Winsorize（去极值）。

        median ± k * MAD * 1.4826 作为上下界截断。
        1.4826 是正态分布下 MAD→σ 的一致性因子。

        Args:
            series: 原始因子值 Series。
            k: 截断倍数，默认 3.0。

        Returns:
            截断后的 Series，NaN 不参与计算且保持 NaN。
        """
        valid = series.dropna()
        if len(valid) == 0:
            return series.copy()

        median = float(valid.median())
        mad = float((valid - median).abs().median())
        sigma_est = mad * 1.4826  # MAD → σ 换算

        if sigma_est < 1e-9:
            return series.copy()

        lower = median - k * sigma_est
        upper = median + k * sigma_est
        return series.clip(lower=lower, upper=upper)

    @staticmethod
    def _cross_section_zscore(series: pd.Series) -> pd.Series:
        """截面 zscore 标准化。

        Args:
            series: 因子值 Series。

        Returns:
            标准化后的 Series，NaN 保持 NaN。
        """
        valid = series.dropna()
        if len(valid) < 2:
            return series.copy()

        mean_v = float(valid.mean())
        std_v = float(valid.std(ddof=1))
        if std_v < 1e-9:
            result = series.copy()
            result[series.notna()] = 0.0
            return result

        return (series - mean_v) / std_v
