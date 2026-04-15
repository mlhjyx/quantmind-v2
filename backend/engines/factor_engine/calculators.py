"""Factor engine — pure calculators (input: Series/DataFrame, output: Series).

Split from factor_engine.py at Phase C C1 (2026-04-16) for 铁律 31 compliance.
All functions in this module are pure: no DB access, no filesystem IO, no HTTP.
Input → output only. Safe for unit testing without fixtures.

Source lineage: backend/engines/factor_engine.py lines 24-431 (Phase C C1 cut).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ============================================================
# Phase 0 因子定义 (6 core → Week 6 扩展到 18)
# ============================================================


def calc_momentum(close_adj: pd.Series, window: int) -> pd.Series:
    """动量因子: N日收益率。

    Args:
        close_adj: 前复权收盘价, MultiIndex=(code, trade_date) 或按code分组后的Series
        window: 回看窗口(5/10/20)

    Returns:
        pd.Series: 动量值
    """
    return close_adj.pct_change(window)


def calc_reversal(close_adj: pd.Series, window: int) -> pd.Series:
    """反转因子: -1 × N日收益率（取反，近期跌多的排前面）。"""
    return -close_adj.pct_change(window)


def calc_volatility(close_adj: pd.Series, window: int) -> pd.Series:
    """波动率因子: N日收益率的滚动标准差。"""
    returns = close_adj.pct_change(1)
    return returns.rolling(window, min_periods=max(window // 2, 5)).std()


def calc_volume_std(volume: pd.Series, window: int) -> pd.Series:
    """成交量波动率: N日volume的滚动标准差。"""
    return volume.rolling(window, min_periods=max(window // 2, 5)).std()


def calc_turnover_mean(turnover_rate: pd.Series, window: int) -> pd.Series:
    """换手率均值: N日turnover_rate的滚动均值。"""
    return turnover_rate.rolling(window, min_periods=max(window // 2, 5)).mean()


def calc_turnover_std(turnover_rate: pd.Series, window: int) -> pd.Series:
    """换手率波动: N日turnover_rate的滚动标准差。"""
    return turnover_rate.rolling(window, min_periods=max(window // 2, 5)).std()


def calc_turnover_stability(turnover_rate: pd.Series, window: int) -> pd.Series:
    """日频换手率稳定性因子: N日换手率的滚动标准差。

    经济学假设: 换手率稳定的股票筹码结构稳定，机构持仓为主；
    换手率波动大的股票散户交易活跃，信息噪声大。

    与turnover_mean_20的区别: turnover_mean测均值水平，turnover_stability测波动性，
    捕获不同维度的换手率信息。

    方向: -1（低波动性 = 稳定 = 好）
    来源: 国盛证券2024-2025量化策略展望(minute_turn_std IR=2.64的日频近似)

    Args:
        turnover_rate: 换手率序列, 已按code分组
        window: 滚动窗口(默认20)

    Returns:
        pd.Series: 换手率稳定性因子值(标准差)
    """
    return turnover_rate.rolling(window, min_periods=max(window // 2, 5)).std()


def calc_amihud(
    close_adj: pd.Series, volume: pd.Series, amount: pd.Series, window: int
) -> pd.Series:
    """Amihud非流动性因子: mean(|return| / amount)。

    注意: amount单位是千元(klines_daily), 不影响截面排序（常数倍不改变排名）。
    """
    ret = close_adj.pct_change(1).abs()
    illiq = ret / (amount + 1e-12)
    return illiq.rolling(window, min_periods=max(window // 2, 5)).mean()


def calc_ln_mcap(total_mv: pd.Series) -> pd.Series:
    """对数市值: ln(total_mv)。total_mv单位万元(daily_basic)。"""
    return np.log(total_mv + 1e-12)


def calc_bp_ratio(pb: pd.Series) -> pd.Series:
    """账面市值比: 1/pb。pb=0时返回NaN。"""
    return 1.0 / pb.replace(0, np.nan)


def calc_ep_ratio(pe: pd.Series) -> pd.Series:
    """盈利收益率: 1/pe_ttm。pe_ttm=0时返回NaN。"""
    return 1.0 / pe.replace(0, np.nan)


def calc_pv_corr(close_adj: pd.Series, volume: pd.Series, window: int) -> pd.Series:
    """价量相关性: N日close与volume的滚动相关系数。"""
    return close_adj.rolling(window, min_periods=max(window // 2, 5)).corr(volume)


def calc_hl_range(high_adj: pd.Series, low_adj: pd.Series, window: int) -> pd.Series:
    """振幅因子: N日平均(high-low)/low。"""
    daily_range = (high_adj - low_adj) / (low_adj + 1e-12)
    return daily_range.rolling(window, min_periods=max(window // 2, 5)).mean()


def calc_price_level(close: pd.Series) -> pd.Series:
    """价格水平因子: -ln(close)。用原始close（非复权），反映价格分层偏好。"""
    return -np.log(close.clip(lower=1e-12))


def calc_relative_volume(volume: pd.Series, window: int) -> pd.Series:
    """相对成交量: volume_today / mean(volume, Nd)。"""
    vol_ma = volume.rolling(window, min_periods=max(window // 2, 5)).mean()
    return volume / (vol_ma + 1e-12)


def calc_turnover_surge_ratio(turnover_rate: pd.Series) -> pd.Series:
    """换手率突增比: mean(turnover_rate, 5d) / mean(turnover_rate, 20d)。"""
    ma5 = turnover_rate.rolling(5, min_periods=3).mean()
    ma20 = turnover_rate.rolling(20, min_periods=10).mean()
    return ma5 / (ma20 + 1e-12)


# ============================================================
# ML特征计算函数 (Sprint 1.4b LightGBM特征池)
# ============================================================

# --- KBAR系列 (来自OHLC) ---


def calc_kbar_kmid(open_: pd.Series, close: pd.Series) -> pd.Series:
    """K线实体方向: (close - open) / open。

    正值=阳线, 负值=阴线, 绝对值反映实体大小。

    Args:
        open_: 开盘价 (已按code分组)
        close: 收盘价 (已按code分组)

    Returns:
        pd.Series: K线实体方向因子值
    """
    return (close - open_) / (open_ + 1e-12)


def calc_kbar_ksft(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.Series:
    """收盘位置偏移: (2*close - high - low) / open。

    衡量收盘价在当日价格区间中的偏移程度。
    正值=偏向高位收盘, 负值=偏向低位收盘。

    Args:
        open_: 开盘价
        high: 最高价
        low: 最低价
        close: 收盘价

    Returns:
        pd.Series: 收盘位置偏移因子值
    """
    return (2 * close - high - low) / (open_ + 1e-12)


def calc_kbar_kup(open_: pd.Series, high: pd.Series, close: pd.Series) -> pd.Series:
    """上影线比例: (high - max(open, close)) / open。

    衡量上方抛压强度, 值越大说明上方卖压越重。

    Args:
        open_: 开盘价
        high: 最高价
        close: 收盘价

    Returns:
        pd.Series: 上影线比例因子值
    """
    body_top = np.maximum(open_, close)
    return (high - body_top) / (open_ + 1e-12)


# --- 资金流系列 (来自moneyflow_daily) ---


def calc_mf_divergence(
    close_adj: pd.Series, net_mf_amount: pd.Series, window: int = 20
) -> pd.Series:
    """资金流背离: close与net_mf_amount的滚动相关性取反。

    IC=9.1%全项目最强（Sprint 1.3确认）。
    当价格涨但净资金流出(负相关)时, 因子值为正, 预示反转。

    Args:
        close_adj: 前复权收盘价 (已按code分组)
        net_mf_amount: 净资金流入金额 (万元, moneyflow_daily)
        window: 滚动窗口

    Returns:
        pd.Series: 资金流背离因子值
    """
    return -close_adj.rolling(window, min_periods=max(window // 2, 5)).corr(net_mf_amount)


def calc_large_order_ratio(
    buy_lg_amount: pd.Series,
    buy_elg_amount: pd.Series,
    buy_md_amount: pd.Series,
    buy_sm_amount: pd.Series,
) -> pd.Series:
    """主力资金占比: (大单+超大单买入) / 全部买入。

    衡量主力资金参与程度, 高值表示机构主导。
    所有金额字段来自 moneyflow_daily，单位统一为万元，比值无量纲。

    Args:
        buy_lg_amount: 大单买入金额 (万元, moneyflow_daily)
        buy_elg_amount: 超大单买入金额 (万元, moneyflow_daily)
        buy_md_amount: 中单买入金额 (万元, moneyflow_daily)
        buy_sm_amount: 小单买入金额 (万元, moneyflow_daily)

    Returns:
        pd.Series: 主力资金占比因子值
    """
    large = buy_lg_amount + buy_elg_amount
    total = large + buy_md_amount + buy_sm_amount
    return large / (total + 1e-12)


def calc_money_flow_strength(
    net_mf_amount: pd.Series,
    total_mv: pd.Series,
) -> pd.Series:
    """净资金流入强度: net_mf_amount / total_mv。

    单位审计: net_mf_amount=万元(moneyflow_daily), total_mv=万元(daily_basic),
    比值无量纲，单位一致无需转换。

    Args:
        net_mf_amount: 净资金流入金额 (万元, moneyflow_daily)
        total_mv: 总市值 (万元, daily_basic)

    Returns:
        pd.Series: 净资金流入强度因子值
    """
    return net_mf_amount / (total_mv + 1e-12)


# --- 动量衍生 ---


def calc_maxret(close_adj: pd.Series, window: int = 20) -> pd.Series:
    """过去N日最大单日涨幅。

    彩票股效应: 最大单日收益越高, 后续越容易回调。

    Args:
        close_adj: 前复权收盘价 (已按code分组)
        window: 回看窗口

    Returns:
        pd.Series: 最大单日收益因子值
    """
    daily_ret = close_adj.pct_change(1)
    return daily_ret.rolling(window, min_periods=max(window // 2, 5)).max()


def calc_chmom(close_adj: pd.Series, long_window: int = 60, short_window: int = 20) -> pd.Series:
    """动量变化(change in momentum): momentum_long - momentum_short。

    原文用120-20, 因数据只有120天lookback, 用60-20替代。
    正值=近期(20日)收益低于长期(60日)均速, 动量减速/反转信号。

    Args:
        close_adj: 前复权收盘价 (已按code分组)
        long_window: 长期窗口
        short_window: 短期窗口

    Returns:
        pd.Series: 动量变化因子值
    """
    mom_long = close_adj.pct_change(long_window)
    mom_short = close_adj.pct_change(short_window)
    return mom_long - mom_short


def calc_up_days_ratio(close_adj: pd.Series, window: int = 20) -> pd.Series:
    """上涨天数占比(Alpha158 CNTP): count(return>0, N days) / N。

    衡量近期上涨频率, 值越高说明上涨天数越多。

    Args:
        close_adj: 前复权收盘价 (已按code分组)
        window: 回看窗口

    Returns:
        pd.Series: 上涨天数占比因子值
    """
    daily_ret = close_adj.pct_change(1)
    up_flag = (daily_ret > 0).astype(float)
    return up_flag.rolling(window, min_periods=max(window // 2, 5)).mean()


# --- VWAP / RSRS (Sprint 1.6 Gate通过, Reserve池) ---


def calc_vwap_bias(
    close: pd.Series, amount: pd.Series, volume: pd.Series, window: int = 1
) -> pd.Series:
    """VWAP偏差因子: (close - VWAP) / VWAP。

    VWAP = amount(元) / (volume(手) × 100) = 元/股
    Step 3-A后DB统一存元，不再需要千元×10的换算。

    方向: -1（低偏差更好，收盘价低于VWAP暗示卖压已释放）
    极值保护: clip(-1.0, 1.0)

    Args:
        close: 收盘价（未复权，元/股）
        amount: 成交额（元, Step 3-A后DB统一单位）
        volume: 成交量（手, 1手=100股）
        window: 窗口（默认1，当日VWAP偏差，无rolling）

    Returns:
        pd.Series: VWAP偏差因子值
    """
    # 零成交量保护: volume=0时VWAP无意义
    safe_volume = volume.replace(0, np.nan)
    vwap = amount / (safe_volume * 100)  # 元 / (手×100) = 元/股
    bias = (close - vwap) / (vwap.abs() + 1e-12)
    return bias.clip(-1.0, 1.0)


def calc_rsrs_raw(high: pd.Series, low: pd.Series, window: int = 18) -> pd.Series:
    """RSRS阻力支撑因子: OLS(high ~ low)斜率的高效实现。

    公式: Cov(high, low, N) / Var(low, N)
    等价于 rolling OLS回归 high = alpha + beta × low 中的beta。

    使用未复权价格（high/low同比例复权，斜率不受影响）。
    方向: -1

    Args:
        high: 最高价
        low: 最低价
        window: 滚动窗口（默认18）

    Returns:
        pd.Series: RSRS斜率因子值
    """
    min_periods = max(window // 2, 9)
    cov_hl = high.rolling(window, min_periods=min_periods).cov(low)
    var_l = low.rolling(window, min_periods=min_periods).var()
    return cov_hl / (var_l + 1e-12)


# --- 技术指标 ---


def calc_beta_market(stock_ret: pd.Series, index_ret: pd.Series, window: int = 20) -> pd.Series:
    """个股对沪深300的滚动Beta。

    Beta = Cov(stock, index) / Var(index)。

    Args:
        stock_ret: 个股日收益率 (已按code分组)
        index_ret: 沪深300日收益率 (与stock_ret等长, 已对齐)
        window: 滚动窗口

    Returns:
        pd.Series: Beta因子值
    """
    cov = stock_ret.rolling(window, min_periods=max(window // 2, 5)).cov(index_ret)
    var = index_ret.rolling(window, min_periods=max(window // 2, 5)).var()
    return cov / (var + 1e-12)


def calc_stoch_rsv(
    close: pd.Series, high: pd.Series, low: pd.Series, window: int = 20
) -> pd.Series:
    """随机值RSV: (close - min(low,N)) / (max(high,N) - min(low,N))。

    超买超卖指标, 0-1之间, >0.8为超买, <0.2为超卖。

    Args:
        close: 收盘价 (已按code分组)
        high: 最高价
        low: 最低价
        window: 回看窗口

    Returns:
        pd.Series: RSV因子值 (0-1)
    """
    low_min = low.rolling(window, min_periods=max(window // 2, 5)).min()
    high_max = high.rolling(window, min_periods=max(window // 2, 5)).max()
    return (close - low_min) / (high_max - low_min + 1e-12)


def calc_gain_loss_ratio(close_adj: pd.Series, window: int = 20) -> pd.Series:
    """盈亏比(类RSI): sum(positive_ret) / (sum(positive_ret) + |sum(negative_ret)|)。

    0-1之间, >0.5表示涨多跌少, <0.5表示跌多涨少。

    Args:
        close_adj: 前复权收盘价 (已按code分组)
        window: 回看窗口

    Returns:
        pd.Series: 盈亏比因子值 (0-1)
    """
    daily_ret = close_adj.pct_change(1)
    gains = daily_ret.clip(lower=0)
    losses = (-daily_ret).clip(lower=0)
    sum_gains = gains.rolling(window, min_periods=max(window // 2, 5)).sum()
    sum_losses = losses.rolling(window, min_periods=max(window // 2, 5)).sum()
    return sum_gains / (sum_gains + sum_losses + 1e-12)
