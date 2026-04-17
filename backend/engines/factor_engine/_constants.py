"""Factor engine constants — direction maps and metadata only.

Split from factor_engine.py at Phase C C1 (2026-04-16) for 铁律 31 compliance.
Pure data, no function references — can be imported without computing factors.
"""

from __future__ import annotations

# ============================================================
# Alpha158 独立因子方向 (8 factors)
# ============================================================
ALPHA158_FACTOR_DIRECTION: dict[str, int] = {
    "a158_std60": -1,  # 低波动好
    "a158_vsump60": -1,  # 量能下降好
    "a158_cord30": -1,  # 量价负相关好
    "a158_vstd30": 1,  # 交易稳定性
    "a158_rank5": -1,  # 低位好（反转）
    "a158_corr5": -1,  # 价量负相关好
    "a158_vsump5": -1,  # 短期量能下降好
    "a158_vma5": 1,  # 近期放量好
}

# ============================================================
# Reserve 池因子方向 (Sprint 1.6 Gate 通过, 不入 v1.1 等权组合)
# ============================================================
RESERVE_FACTOR_DIRECTION: dict[str, int] = {
    "vwap_bias_1d": -1,  # 低偏差更好（收盘价低于VWAP）
    "rsrs_raw_18": -1,  # Sprint 1.6 确认方向
}

# ============================================================
# PEAD (Post-Earnings Announcement Drift) 因子方向
# ============================================================
PEAD_FACTOR_DIRECTION: dict[str, int] = {
    "pead_q1": 1,  # 正 surprise → 正 drift (Q1 季报限定)
}

# ============================================================
# Phase 2.1 E2E 因子方向 (wide-format)
# ============================================================
PHASE21_FACTOR_DIRECTION: dict[str, int] = {
    "high_vol_price_ratio_20": -1,  # 高波动日价偏高=利空
    "IMAX_20": -1,  # 极端正收益=彩票偏好被高估
    "IMIN_20": 1,  # 深跌后均值回归
    "QTLU_20": -1,  # 上行偏度=过度乐观
    "CORD_20": -1,  # 强上行趋势=反转
    "RSQR_20": -1,  # 低 R²=特质风险=散户溢价
    "RESI_20": 1,  # 正 alpha=近期跑赢
}

# ============================================================
# 基本面 Delta 特征元数据 (Sprint 1.5 — 北大 2025+国信金工共识: 变化率>水平值)
# 因子名 → (方向, clip 范围, 说明)
# ============================================================
FUNDAMENTAL_DELTA_META: dict[str, tuple[int, tuple[float, float], str]] = {
    "roe_delta": (1, (-2.0, 5.0), "ROE环比变化率"),
    "revenue_growth_yoy": (1, (-2.0, 5.0), "营收同比增速(直接取字段)"),
    "gross_margin_delta": (1, (-100, 100), "毛利率环比变化(百分点)"),
    "eps_acceleration": (1, (-2.0, 5.0), "EPS增速差分(加速度)"),
    "debt_change": (-1, (-100, 100), "资产负债率变化(负=减杠杆=好)"),
    "net_margin_delta": (1, (-100, 100), "净利润率环比变化(百分点)"),
}

# 时间特征元数据
FUNDAMENTAL_TIME_META: dict[str, tuple[int, tuple[float, float], str]] = {
    "days_since_announcement": (-1, (0, 365), "距最近公告日天数(越近越好)"),
    "reporting_season_flag": (1, (0, 1), "财报季标志(4/8/10月=1)"),
}

# 合并: 全部 8 个基本面+时间因子名
FUNDAMENTAL_DELTA_FEATURES: list[str] = list(FUNDAMENTAL_DELTA_META.keys())
FUNDAMENTAL_TIME_FEATURES: list[str] = list(FUNDAMENTAL_TIME_META.keys())
FUNDAMENTAL_ALL_FEATURES: list[str] = FUNDAMENTAL_DELTA_FEATURES + FUNDAMENTAL_TIME_FEATURES

# 基本面因子方向映射 (从 META 提取)
FUNDAMENTAL_FACTOR_DIRECTION: dict[str, int] = {
    k: v[0] for k, v in {**FUNDAMENTAL_DELTA_META, **FUNDAMENTAL_TIME_META}.items()
}

# ============================================================
# LightGBM v2 baseline 因子列表 (5 基线 + 6 delta + 2 时间 = 13 个)
# ============================================================
LGBM_V2_BASELINE_FACTORS: list[str] = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

# ============================================================
# 分钟级日频特征方向 (minute_feature_engine, 10 factors)
# ============================================================
MINUTE_FACTOR_DIRECTION: dict[str, int] = {
    "high_freq_volatility_20": -1,     # 低波动好 (反转效应)
    "volume_concentration_20": -1,     # 低集中=均匀成交=好
    "volume_autocorr_20": -1,          # 低自相关=信息混合快
    "smart_money_ratio_20": 1,         # 尾盘>开盘=机构主导
    "opening_volume_share_20": 1,      # 2026-04-17b neutral IC=+0.0013 (弱, 方向修正 -1→+1)
    "closing_trend_strength_20": 1,    # 2026-04-17b neutral IC=+0.0069 (弱, 方向修正 -1→+1)
    "vwap_deviation_20": 1,            # 2026-04-17b neutral IC=+0.0509 (真反转, 方向修正 -1→+1)
    "order_flow_imbalance_20": -1,     # IC验证: 净卖出→次日反弹 (反转效应, t=-8.24)
    "intraday_momentum_20": -1,        # 负=日内反转=次日反转
    "volume_price_divergence_20": 1,   # IC验证: 正背离(|ret|↑vol↓)→次日好 (t=+25.39)
}
