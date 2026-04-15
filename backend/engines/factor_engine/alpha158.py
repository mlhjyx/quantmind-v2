"""Factor engine — Alpha158 helpers and composite factors.

Split from factor_engine.py at Phase C C1 (2026-04-16) for 铁律 31 compliance.
Contains: alpha158 rolling helper + wide-format composite factors (simple four + RSQR/RESI).
All pure functions — no DB access, no IO.

Source lineage: backend/engines/factor_engine.py lines 542-547, 778-911 (Phase C C1 cut).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _alpha158_rolling(df, op_name, window):
    """Alpha158滚动因子的统一计算入口。

    Note: 依赖 engines.alpha158_factors.compute_rolling 这一兄弟模块。
    这是一个薄包装, 本身不做 IO, 但加载的 compute_rolling 可能有内部
    优化。保持签名不变以兼容旧调用。
    """
    from engines.alpha158_factors import compute_rolling

    result = compute_rolling(df)
    key = f"{op_name}{window}"
    return result.get(key, pd.Series(dtype=float))


# ============================================================
# Phase 2.1 E2E因子 (wide-format批量计算, 非lambda模式)
# ============================================================


def calc_high_vol_price_ratio_wide(
    close_wide: pd.DataFrame,
    open_wide: pd.DataFrame,
    high_wide: pd.DataFrame,
    low_wide: pd.DataFrame,
    window: int = 20,
    top_k: int = 4,
) -> pd.DataFrame:
    """高位放量因子 — 高波动日均价/全窗口均价。

    经济学假设(铁律13): 高波动日价格偏高→庄家出货信号,
    ratio>1表示放量时价格偏高(利空), direction=-1。

    来源: scripts/research/phase2_signal_feasibility.py compute_24_high_vol_price()
    验证: IC=-0.077, t=-17.85, max_corr=0.443(独立)

    Args:
        close_wide: (trade_date × code) 收盘价
        open_wide: (trade_date × code) 开盘价
        high_wide: (trade_date × code) 最高价
        low_wide: (trade_date × code) 最低价
        window: 滚动窗口(默认20日)
        top_k: 取波动最高的天数(默认4=top 20%)

    Returns:
        DataFrame (trade_date × code), NaN for insufficient window
    """
    # 日内波动率
    intravol_wide = (high_wide - low_wide) / (open_wide + 1e-12)

    close_arr = close_wide.values
    intravol_arr = intravol_wide.values
    n_dates, n_codes = close_arr.shape

    result = np.full((n_dates, n_codes), np.nan)

    for i in range(window - 1, n_dates):
        c_win = close_arr[i - window + 1 : i + 1]  # (window, n_codes)
        v_win = intravol_arr[i - window + 1 : i + 1]

        # 按intravol降序排名, 取top_k天
        v_ranks = np.argsort(np.argsort(-v_win, axis=0), axis=0)
        top_v_mask = v_ranks < top_k

        c_mean_all = np.nanmean(c_win, axis=0)
        c_top_v = np.where(top_v_mask, c_win, np.nan)
        c_mean_top_v = np.nanmean(c_top_v, axis=0)
        result[i] = c_mean_top_v / (c_mean_all + 1e-12)

    return pd.DataFrame(result, index=close_wide.index, columns=close_wide.columns)


def calc_alpha158_simple_four(
    daily_ret: pd.DataFrame,
    price_wide: pd.DataFrame,
    window: int = 20,
) -> dict[str, pd.DataFrame]:
    """Alpha158简单四因子 — IMAX/IMIN/QTLU/CORD。

    来源: scripts/research/phase12_alpha158_six.py compute_simple_four()

    Args:
        daily_ret: (trade_date × code) 日收益率
        price_wide: (trade_date × code) 收盘价(用于CORD)
        window: 滚动窗口(默认20日)

    Returns:
        dict: {factor_name: DataFrame(trade_date × code)}
    """
    results = {}

    # IMAX_20: 窗口内最大日收益率
    results["IMAX_20"] = daily_ret.rolling(window, min_periods=window).max()

    # IMIN_20: 窗口内最小日收益率
    results["IMIN_20"] = daily_ret.rolling(window, min_periods=window).min()

    # QTLU_20: 窗口内收益率75th分位
    results["QTLU_20"] = daily_ret.rolling(window, min_periods=window).quantile(0.75)

    # CORD_20: corr(close, time_index) over rolling window
    time_idx = pd.Series(np.arange(len(price_wide), dtype=float), index=price_wide.index)
    results["CORD_20"] = price_wide.rolling(window, min_periods=window).corr(time_idx)

    return results


def calc_alpha158_rsqr_resi(
    daily_ret: pd.DataFrame,
    market_ret: pd.Series,
    window: int = 20,
) -> dict[str, pd.DataFrame]:
    """Alpha158 RSQR/RESI — 向量化rolling OLS。

    RSQR_20 = corr(stock_ret, market_ret)² (R²)
    RESI_20 = alpha = mean(y) - beta × mean(x) (OLS截距)

    来源: scripts/research/phase12_alpha158_six.py compute_rsqr_resi()

    Args:
        daily_ret: (trade_date × code) 个股日收益率
        market_ret: (trade_date,) 市场日收益率(CSI300)
        window: 滚动窗口(默认20日)

    Returns:
        dict: {"RSQR_20": DataFrame, "RESI_20": DataFrame}
    """
    # 对齐市场收益到stock日期
    mkt = market_ret.reindex(daily_ret.index)

    # RSQR_20 = corr(stock_ret, market_ret)²
    rolling_corr = daily_ret.rolling(window, min_periods=window).corr(mkt)
    rsqr = rolling_corr**2

    # RESI_20 = alpha = mean(y) - beta × mean(x)
    rolling_mean_y = daily_ret.rolling(window, min_periods=window).mean()
    rolling_mean_x = mkt.rolling(window, min_periods=window).mean()

    # cov(x,y) = E[xy] - E[x]E[y]
    xy = daily_ret.multiply(mkt, axis=0)
    rolling_mean_xy = xy.rolling(window, min_periods=window).mean()
    rolling_cov_xy = rolling_mean_xy - rolling_mean_y.multiply(rolling_mean_x, axis=0)

    # var(x) = E[x²] - E[x]²
    x2 = mkt**2
    rolling_mean_x2 = x2.rolling(window, min_periods=window).mean()
    rolling_var_x = rolling_mean_x2 - rolling_mean_x**2

    beta = rolling_cov_xy.div(rolling_var_x.replace(0, np.nan), axis=0)
    resi = rolling_mean_y - beta.multiply(rolling_mean_x, axis=0)

    return {"RSQR_20": rsqr, "RESI_20": resi}
