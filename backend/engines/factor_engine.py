"""因子计算引擎 — Phase 0 规则版因子管道。

流程: 读取行情 → 计算原始因子值 → 预处理(MAD→fill→neutralize→zscore) → 批量写入

严格遵守 CLAUDE.md 因子计算规则:
1. 预处理顺序不可调换: MAD去极值 → 缺失值填充 → 中性化 → 标准化
2. 按日期批量写入(单事务)
3. IC使用超额收益(vs CSI300)
"""

from datetime import date

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


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


def calc_hl_range(
    high_adj: pd.Series, low_adj: pd.Series, window: int
) -> pd.Series:
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


def calc_kbar_ksft(open_: pd.Series, high: pd.Series,
                   low: pd.Series, close: pd.Series) -> pd.Series:
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


def calc_kbar_kup(open_: pd.Series, high: pd.Series,
                  close: pd.Series) -> pd.Series:
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
    buy_lg_amount: pd.Series, buy_elg_amount: pd.Series,
    buy_md_amount: pd.Series, buy_sm_amount: pd.Series,
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
    net_mf_amount: pd.Series, total_mv: pd.Series,
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


def calc_chmom(close_adj: pd.Series, long_window: int = 60,
               short_window: int = 20) -> pd.Series:
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

    VWAP = amount * 10.0 / volume
    单位换算: amount(千元, klines_daily)×1000 / (volume(手)×100) = amount×10/volume = 元/股

    方向: -1（低偏差更好，收盘价低于VWAP暗示卖压已释放）
    极值保护: clip(-1.0, 1.0)

    Args:
        close: 收盘价（未复权，与VWAP单位一致）
        amount: 成交额（千元）
        volume: 成交量（手）
        window: 窗口（默认1，当日VWAP偏差，无rolling）

    Returns:
        pd.Series: VWAP偏差因子值
    """
    # 零成交量保护: volume=0时VWAP无意义
    safe_volume = volume.replace(0, np.nan)
    vwap = amount * 10.0 / safe_volume
    bias = (close - vwap) / (vwap.abs() + 1e-12)
    return bias.clip(-1.0, 1.0)


def calc_rsrs_raw(
    high: pd.Series, low: pd.Series, window: int = 18
) -> pd.Series:
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

def calc_beta_market(
    stock_ret: pd.Series, index_ret: pd.Series, window: int = 20
) -> pd.Series:
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


def calc_stoch_rsv(close: pd.Series, high: pd.Series,
                   low: pd.Series, window: int = 20) -> pd.Series:
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


# ============================================================
# 因子注册表
# ============================================================

# Phase 0 Week 3: 5 core factors (momentum_20 deprecated per factor评级报告)
PHASE0_CORE_FACTORS = {
    "volatility_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_volatility(x, 20)
    ),
    "turnover_mean_20": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_mean(x, 20)
    ),
    "amihud_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_amihud(g["adj_close"], g["volume"], g["amount"], 20)
    ),
    "ln_market_cap": lambda df: calc_ln_mcap(df["total_mv"]),
    "bp_ratio": lambda df: calc_bp_ratio(df["pb"]),
}

# Phase 0 Week 6: 扩展因子 (不含deprecated)
PHASE0_FULL_FACTORS = {
    **PHASE0_CORE_FACTORS,
    # momentum_5/10 已移至DEPRECATED (与reversal_5/10数学等价, corr=-1.0)
    "reversal_5": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 5)
    ),
    "reversal_10": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 10)
    ),
    "reversal_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 20)
    ),
    "ep_ratio": lambda df: calc_ep_ratio(df["pe_ttm"]),
    "price_volume_corr_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_pv_corr(g["adj_close"], g["volume"].astype(float), 20)
    ),
    # northbound_pct: Phase 1 (需要额外数据源 AKShare)
    # ---- v1.2 新增因子 ----
    "price_level_factor": lambda df: df.groupby("code")["close"].transform(
        lambda x: calc_price_level(x)
    ),
    "relative_volume_20": lambda df: df.groupby("code")["volume"].transform(
        lambda x: calc_relative_volume(x.astype(float), 60)
    ),
    "dv_ttm": lambda df: df["dv_ttm"].fillna(df.get("dv_ratio", 0)),  # fallback到dv_ratio
    "turnover_surge_ratio": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_surge_ratio(x)
    ),
}

# Deprecated因子 (factor评级报告确认, 从日常计算中移除)
# 原因: IC衰减/正交性不足/被更优因子替代
DEPRECATED_FACTORS = {
    "momentum_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 20)
    ),
    # momentum_5 = -reversal_5 (数学等价, corr=-1.000), 保留reversal_5在FULL
    "momentum_5": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 5)
    ),
    # momentum_10 = -reversal_10 (数学等价, corr=-1.000), 保留reversal_10在FULL
    "momentum_10": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 10)
    ),
    "volatility_60": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_volatility(x, 60)
    ),
    "volume_std_20": lambda df: df.groupby("code")["volume"].transform(
        lambda x: calc_volume_std(x, 20)
    ),
    "turnover_std_20": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_std(x, 20)
    ),
    "high_low_range_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_hl_range(g["adj_high"], g["adj_low"], 20)
    ),
    # turnover_stability_20: corr(turnover_mean_20)=0.904, 高度冗余
    "turnover_stability_20": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_stability(x, 20)
    ),
}

# 全量因子(含deprecated): 用于回测对比、历史分析
PHASE0_ALL_FACTORS = {**PHASE0_FULL_FACTORS, **DEPRECATED_FACTORS}

# Reserve池因子 (Sprint 1.6 Gate通过, 不入v1.1等权组合)
# 日常计算+写入factor_values, 用于监控IC/未来组合升级评估
RESERVE_FACTORS = {
    "vwap_bias_1d": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_vwap_bias(g["close"], g["amount"], g["volume"], 1)
    ),
    "rsrs_raw_18": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_rsrs_raw(g["high"], g["low"], 18)
    ),
    # turnover_stability_20 移至DEPRECATED (corr(turnover_mean_20)=0.904)
}

# Reserve因子方向映射
RESERVE_FACTOR_DIRECTION = {
    "vwap_bias_1d": -1,   # 低偏差更好（收盘价低于VWAP）
    "rsrs_raw_18": -1,    # Sprint 1.6确认方向
}

# ============================================================
# Alpha158因子 (Qlib导入, corr<0.7 vs现有因子)
# 计算逻辑在 engines/alpha158_factors.py, 这里用lambda封装
# ============================================================

def _alpha158_rolling(df, op_name, window):
    """Alpha158滚动因子的统一计算入口。"""
    from engines.alpha158_factors import compute_rolling
    result = compute_rolling(df)
    key = f"{op_name}{window}"
    return result.get(key, pd.Series(dtype=float))


# 4个RANKING因子（月度调仓）
ALPHA158_RANKING = {
    "a158_std60": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: g["close"].rolling(60, min_periods=60).std() / g["close"]
    ),
    "a158_vsump60": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: (
            (g["volume"] - g["volume"].shift(1)).clip(lower=0).rolling(60, min_periods=60).sum()
            / ((g["volume"] - g["volume"].shift(1)).abs().rolling(60, min_periods=60).sum() + 1e-12)
        )
    ),
    "a158_cord30": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: (g["close"] / g["close"].shift(1) - 1).rolling(30, min_periods=30).corr(
            np.log(g["volume"] / g["volume"].shift(1).replace(0, np.nan) + 1)
        )
    ),
    "a158_vstd30": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: g["volume"].rolling(30, min_periods=30).std() / (g["volume"] + 1e-12)
    ),
}

# 4个FAST_RANKING因子（周度/双周调仓）
ALPHA158_FAST_RANKING = {
    "a158_rank5": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: (
            (g["close"] - g["close"].rolling(5, min_periods=5).min())
            / (g["close"].rolling(5, min_periods=5).max() - g["close"].rolling(5, min_periods=5).min() + 1e-12)
        )
    ),
    "a158_corr5": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: g["close"].rolling(5, min_periods=5).corr(np.log(g["volume"] + 1))
    ),
    "a158_vsump5": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: (
            (g["volume"] - g["volume"].shift(1)).clip(lower=0).rolling(5, min_periods=5).sum()
            / ((g["volume"] - g["volume"].shift(1)).abs().rolling(5, min_periods=5).sum() + 1e-12)
        )
    ),
    "a158_vma5": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: g["volume"].rolling(5, min_periods=5).mean() / (g["volume"] + 1e-12)
    ),
}

ALPHA158_FACTORS = {**ALPHA158_RANKING, **ALPHA158_FAST_RANKING}

# Alpha158因子方向 (IC方向)
ALPHA158_FACTOR_DIRECTION = {
    "a158_std60": -1,      # 低波动好
    "a158_vsump60": -1,    # 量能下降好
    "a158_cord30": -1,     # 量价负相关好
    "a158_vstd30": 1,      # 交易稳定性
    "a158_rank5": -1,      # 低位好（反转）
    "a158_corr5": -1,      # 价量负相关好
    "a158_vsump5": -1,     # 短期量能下降好
    "a158_vma5": 1,        # 近期放量好
}

# ============================================================
# PEAD因子 (Post-Earnings Announcement Drift, Q1季报限定)
# EVENT类型: 公告后7天内有效，非日频rolling
# 验证: Q1季报 spread=+1.19%, t=8.42, 最优窗口+7天
# H1/Q3/Y方向反转，禁止使用
# ============================================================


def calc_pead_q1(trade_date, conn=None) -> pd.Series:
    """PEAD Q1季报因子 — 公告后7天内的eps_surprise_pct。

    只使用report_type='Q1'的公告。同一股票取最近一条。
    超过7天的记录返回NaN（信号衰减）。

    Args:
        trade_date: 计算日期 (date或str)
        conn: psycopg2连接（None则自建）

    Returns:
        pd.Series: index=code, values=eps_surprise_pct (正=超预期)
    """
    import psycopg2 as _pg2

    close_conn = conn is None
    if conn is None:
        conn = _pg2.connect(
            dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
        )

    if isinstance(trade_date, str):
        from datetime import datetime as _dt

        trade_date = _dt.strptime(trade_date, "%Y-%m-%d").date()

    cur = conn.cursor()
    cur.execute(
        """SELECT ea.ts_code, ea.eps_surprise_pct, ea.trade_date AS ann_td
        FROM earnings_announcements ea
        WHERE ea.report_type = 'Q1'
          AND ea.trade_date <= %s
          AND ea.trade_date >= %s - INTERVAL '7 days'
          AND ea.eps_surprise_pct IS NOT NULL
          AND ABS(ea.eps_surprise_pct) < 10
        ORDER BY ea.ts_code, ea.trade_date DESC""",
        (trade_date, trade_date),
    )

    rows = cur.fetchall()
    if close_conn:
        conn.close()

    if not rows:
        return pd.Series(dtype=float)

    # 同一股票取最近一条（已按trade_date DESC排序）
    seen = set()
    data = {}
    for ts_code, surprise, _ann_td in rows:
        code = ts_code  # 统一带后缀格式
        if code not in seen:
            data[code] = float(surprise)
            seen.add(code)

    return pd.Series(data, name="pead_q1")


# PEAD因子方向和分类
PEAD_FACTOR_DIRECTION = {
    "pead_q1": 1,  # 正surprise → 正drift (Q1季报限定)
}

# ============================================================
# ML特征注册表 (Sprint 1.4b LightGBM 50+特征池)
# ============================================================
# 注意: 资金流因子和beta_market需要额外数据(moneyflow_daily / index_daily),
# 使用 load_bulk_data_with_extras 加载。普通因子只依赖 klines_daily + daily_basic。

# --- 仅依赖klines_daily + daily_basic的ML特征 ---
ML_FEATURES_KLINE = {
    # KBAR系列 (纯element-wise, 无需groupby)
    "kbar_kmid": lambda df: calc_kbar_kmid(df["open"], df["close"]),
    "kbar_ksft": lambda df: calc_kbar_ksft(df["open"], df["high"], df["low"], df["close"]),
    "kbar_kup": lambda df: calc_kbar_kup(df["open"], df["high"], df["close"]),
    # 动量衍生
    "maxret_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_maxret(x, 20)
    ),
    "chmom_60_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_chmom(x, 60, 20)
    ),
    "up_days_ratio_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_up_days_ratio(x, 20)
    ),
    # 技术指标 (不含beta, 不需要index数据)
    "stoch_rsv_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_stoch_rsv(g["adj_close"], g["adj_high"], g["adj_low"], 20)
    ),
    "gain_loss_ratio_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_gain_loss_ratio(x, 20)
    ),
}

# --- 需要moneyflow_daily数据的ML特征 ---
ML_FEATURES_MONEYFLOW = {
    "mf_divergence": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_mf_divergence(g["adj_close"], g["net_mf_amount"].astype(float), 20)
    ),
    "large_order_ratio": lambda df: calc_large_order_ratio(
        df["buy_lg_amount"].astype(float), df["buy_elg_amount"].astype(float),
        df["buy_md_amount"].astype(float), df["buy_sm_amount"].astype(float),
    ),
    "money_flow_strength": lambda df: calc_money_flow_strength(
        df["net_mf_amount"].astype(float), df["total_mv"],
    ),
}

# --- 需要index_daily数据的ML特征 ---
ML_FEATURES_INDEX = {
    "beta_market_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_beta_market(
            g["adj_close"].pct_change(1), g["index_ret"], 20
        )
    ),
}

# 全部ML特征 (合并三组)
ML_FEATURES = {**ML_FEATURES_KLINE, **ML_FEATURES_MONEYFLOW, **ML_FEATURES_INDEX}

# LightGBM完整特征集 = Phase0全量 + ML新特征 + Alpha158独立因子
LIGHTGBM_FEATURE_SET = {**PHASE0_FULL_FACTORS, **ML_FEATURES, **ALPHA158_FACTORS}


# ============================================================
# 基本面Delta特征 (Sprint 1.5 — 北大2025+国信金工共识: 变化率>水平值)
# ============================================================
# 注意: 基本面因子依赖financial_indicators表(PIT), 不走kline lambda模式。
# 通过 load_fundamental_pit_data() 单独加载, 返回 (code -> value) 字典。

# 因子名 → (方向, clip范围, 说明)
FUNDAMENTAL_DELTA_META = {
    "roe_delta":            (1,  (-2.0, 5.0),   "ROE环比变化率"),
    "revenue_growth_yoy":   (1,  (-2.0, 5.0),   "营收同比增速(直接取字段)"),
    "gross_margin_delta":   (1,  (-100, 100),    "毛利率环比变化(百分点)"),
    "eps_acceleration":     (1,  (-2.0, 5.0),    "EPS增速差分(加速度)"),
    "debt_change":          (-1, (-100, 100),    "资产负债率变化(负=减杠杆=好)"),
    "net_margin_delta":     (1,  (-100, 100),    "净利润率环比变化(百分点)"),
}

# 时间特征
FUNDAMENTAL_TIME_META = {
    "days_since_announcement": (-1, (0, 365),  "距最近公告日天数(越近越好)"),
    "reporting_season_flag":   (1,  (0, 1),    "财报季标志(4/8/10月=1)"),
}

# 合并: 全部8个基本面+时间因子名
FUNDAMENTAL_DELTA_FEATURES = list(FUNDAMENTAL_DELTA_META.keys())
FUNDAMENTAL_TIME_FEATURES = list(FUNDAMENTAL_TIME_META.keys())
FUNDAMENTAL_ALL_FEATURES = FUNDAMENTAL_DELTA_FEATURES + FUNDAMENTAL_TIME_FEATURES

# LightGBM v2特征集 = 5基线 + 6delta + 2时间 = 13个
LGBM_V2_BASELINE_FACTORS = [
    "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio",
]

# 因子方向映射(用于信号合成)
FUNDAMENTAL_FACTOR_DIRECTION = {
    k: v[0] for k, v in {**FUNDAMENTAL_DELTA_META, **FUNDAMENTAL_TIME_META}.items()
}


def load_fundamental_pit_data(
    trade_date: date,
    conn,
) -> dict[str, pd.Series]:
    """加载并计算基本面delta特征(PIT对齐)。

    对每个trade_date:
    - 调用 load_financial_pit 获取每只股票可见的最近4季财报
    - 取"当期"(最新) 和"上期"(次新) 两行计算delta

    Args:
        trade_date: 交易日
        conn: psycopg2连接

    Returns:
        dict[factor_name -> pd.Series(index=code, value=raw)]
        包含6个delta因子 + 2个时间因子
    """
    from engines.financial_factors import load_financial_pit

    fina_df = load_financial_pit(trade_date, conn)
    if fina_df.empty:
        logger.warning(f"[FundDelta] {trade_date} 无PIT财务数据")
        return {name: pd.Series(dtype=float) for name in FUNDAMENTAL_ALL_FEATURES}

    n_stocks = fina_df["code"].nunique()
    logger.debug(f"[FundDelta] {trade_date}: {n_stocks}只股票")

    # --- 计算6个delta因子 ---
    roe_delta: dict[str, float] = {}
    revenue_growth_yoy: dict[str, float] = {}
    gross_margin_delta: dict[str, float] = {}
    eps_acceleration: dict[str, float] = {}
    debt_change: dict[str, float] = {}
    net_margin_delta: dict[str, float] = {}

    # --- 时间因子 ---
    days_since_ann: dict[str, float] = {}

    for code, grp in fina_df.groupby("code"):
        grp = grp.sort_values("report_date", ascending=False, kind="mergesort")
        latest = grp.iloc[0]
        prev = grp.iloc[1] if len(grp) >= 2 else None

        # 1. roe_delta: (当期ROE - 上期ROE) / abs(上期ROE + 1e-8)
        if prev is not None:
            roe_col = "roe_dt" if pd.notna(latest.get("roe_dt")) and pd.notna(prev.get("roe_dt")) else "roe"
            roe_curr = latest.get(roe_col)
            roe_prev = prev.get(roe_col)
            if pd.notna(roe_curr) and pd.notna(roe_prev):
                roe_delta[code] = float(roe_curr - roe_prev) / (abs(float(roe_prev)) + 1e-8)

        # 2. revenue_growth_yoy: 直接取字段
        rev_yoy = latest.get("revenue_yoy")
        if pd.notna(rev_yoy):
            revenue_growth_yoy[code] = float(rev_yoy) / 100.0  # 百分比→小数

        # 3. gross_margin_delta: 当期 - 上期 (百分点差值)
        if prev is not None:
            gm_curr = latest.get("gross_profit_margin")
            gm_prev = prev.get("gross_profit_margin")
            if pd.notna(gm_curr) and pd.notna(gm_prev):
                gross_margin_delta[code] = float(gm_curr) - float(gm_prev)

        # 4. eps_acceleration: 当期basic_eps_yoy - 上期basic_eps_yoy
        if prev is not None:
            eps_yoy_curr = latest.get("basic_eps_yoy")
            eps_yoy_prev = prev.get("basic_eps_yoy")
            if pd.notna(eps_yoy_curr) and pd.notna(eps_yoy_prev):
                eps_acceleration[code] = (float(eps_yoy_curr) - float(eps_yoy_prev)) / 100.0

        # 5. debt_change: 当期debt_to_asset - 上期debt_to_asset
        if prev is not None:
            d_curr = latest.get("debt_to_asset")
            d_prev = prev.get("debt_to_asset")
            if pd.notna(d_curr) and pd.notna(d_prev):
                debt_change[code] = float(d_curr) - float(d_prev)

        # 6. net_margin_delta: 当期net_profit_margin - 上期net_profit_margin
        if prev is not None:
            nm_curr = latest.get("net_profit_margin")
            nm_prev = prev.get("net_profit_margin")
            if pd.notna(nm_curr) and pd.notna(nm_prev):
                net_margin_delta[code] = float(nm_curr) - float(nm_prev)

        # 7. days_since_announcement
        ann_date = latest.get("actual_ann_date")
        if pd.notna(ann_date):
            if isinstance(ann_date, str):
                from datetime import datetime as _dt
                ann_date = _dt.strptime(ann_date, "%Y-%m-%d").date()
            elif hasattr(ann_date, "date"):
                ann_date = ann_date.date()
            days_since_ann[code] = float((trade_date - ann_date).days)

    # 8. reporting_season_flag (不依赖个股, 取trade_date月份)
    month = trade_date.month
    season_flag = 1.0 if month in (4, 8, 10) else 0.0

    # --- clip极端值 ---
    def _clip_series(d: dict, lo: float, hi: float) -> pd.Series:
        """将dict转为Series并clip。"""
        s = pd.Series(d, dtype=float)
        return s.clip(lower=lo, upper=hi)

    results: dict[str, pd.Series] = {
        "roe_delta": _clip_series(roe_delta, -2.0, 5.0),
        "revenue_growth_yoy": _clip_series(revenue_growth_yoy, -2.0, 5.0),
        "gross_margin_delta": _clip_series(gross_margin_delta, -100, 100),
        "eps_acceleration": _clip_series(eps_acceleration, -2.0, 5.0),
        "debt_change": _clip_series(debt_change, -100, 100),
        "net_margin_delta": _clip_series(net_margin_delta, -100, 100),
        "days_since_announcement": _clip_series(days_since_ann, 0, 365),
        "reporting_season_flag": pd.Series(
            {code: season_flag for code in fina_df["code"].unique()},
            dtype=float,
        ),
    }

    for name, s in results.items():
        if not s.empty:
            logger.debug(f"  {name}: {len(s)}只, mean={s.mean():.4f}")

    return results


# ============================================================
# 预处理管道 (CLAUDE.md 强制顺序: MAD → fill → neutralize → zscore)
# ============================================================

def preprocess_mad(series: pd.Series, n_mad: float = 5.0) -> pd.Series:
    """Step 1: MAD去极值。

    将超出 median ± n_mad × MAD 的值截断到边界。

    Args:
        series: 单因子截面值 (一个trade_date的全部股票)
        n_mad: MAD倍数, 默认5倍

    Returns:
        去极值后的Series
    """
    median = series.median()
    mad = (series - median).abs().median()
    if mad < 1e-12:
        return series
    upper = median + n_mad * mad
    lower = median - n_mad * mad
    return series.clip(lower=lower, upper=upper)


def preprocess_fill(
    series: pd.Series,
    industry: pd.Series,
) -> pd.Series:
    """Step 2: 缺失值填充。

    先用行业中位数填充, 再用0填充剩余。

    Args:
        series: 单因子截面值
        industry: 对应的行业分类

    Returns:
        填充后的Series (无NaN)
    """
    # 行业中位数填充
    industry_median = series.groupby(industry).transform("median")
    filled = series.fillna(industry_median)
    # 剩余NaN用0填充
    filled = filled.fillna(0.0)
    return filled


def preprocess_neutralize(
    series: pd.Series,
    ln_mcap: pd.Series,
    industry: pd.Series,
) -> pd.Series:
    """Step 3: WLS中性化 — 加权最小二乘回归掉市值 + 行业。

    模型: factor = alpha + beta1 × ln_mcap + Σ(beta_i × industry_dummy) + residual
    权重: w_i = √market_cap_i = √exp(ln_mcap_i)（大市值股票权重更高）
    WLS变换: 用 √w_i 乘以 X 和 y，转化为等价的OLS问题后 lstsq 求解。
    残差: 用原始(未加权)的 y - X @ beta 计算，保留经济含义。

    设计文档: DESIGN_V5 §4.4 — WLS(√market_cap加权)回归。

    Args:
        series: 单因子截面值 (已去极值+填充)
        ln_mcap: 对数市值（ln(流通市值)）
        industry: 行业分类

    Returns:
        中性化后的残差 Series，无效样本保持 NaN
    """
    valid_mask = series.notna() & ln_mcap.notna() & industry.notna()
    if valid_mask.sum() < 30:
        logger.warning("中性化样本不足30，跳过中性化")
        return series

    y = series[valid_mask].values
    mcap_vals = ln_mcap[valid_mask].values

    # 构建设计矩阵 X: [intercept, ln_mcap, industry_dummies]
    mcap_col = mcap_vals.reshape(-1, 1)
    ind_dummies = pd.get_dummies(industry[valid_mask], drop_first=True).values
    x_mat = np.column_stack([np.ones(len(y)), mcap_col, ind_dummies])  # noqa: N806

    # WLS权重: w_i = √market_cap = √exp(ln_mcap)
    # WLS → OLS变换: 用 √w_i 乘以 X 和 y
    weights = np.sqrt(np.exp(mcap_vals))          # w_i = √market_cap
    w_sqrt = np.sqrt(weights)                      # √w_i = market_cap^(1/4)
    # 归一化避免数值溢出 (不影响回归结果)
    w_sqrt = w_sqrt / w_sqrt.mean()

    xw = x_mat * w_sqrt[:, np.newaxis]
    yw = y * w_sqrt

    try:
        # WLS: beta = (X'WX)^-1 X'Wy，等价OLS on (Xw, yw)
        beta = np.linalg.lstsq(xw, yw, rcond=None)[0]
        # 残差使用原始空间（非加权），保留经济含义
        residual = y - x_mat @ beta

        result = series.copy()
        result[valid_mask] = residual
        result[~valid_mask] = np.nan
        return result
    except np.linalg.LinAlgError:
        logger.warning("WLS中性化回归失败(矩阵奇异)，返回原值")
        return series


def preprocess_zscore(series: pd.Series) -> pd.Series:
    """Step 4: zscore标准化。

    (x - mean) / std, 标准差为0时返回全0。
    """
    mean = series.mean()
    std = series.std()
    if std < 1e-12:
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def preprocess_pipeline(
    factor_series: pd.Series,
    ln_mcap: pd.Series,
    industry: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """完整预处理管道。

    返回 (raw_value, neutral_value)。
    neutral_value = 经过 MAD→fill→neutralize(WLS)→zscore→clip(±3) 全部5步处理后的值。

    步骤:
      1. MAD去极值 (5σ)
      2. 缺失值填充 (行业中位数→0)
      3. WLS中性化 (行业+市值加权回归，w=√market_cap)
      4. zscore标准化
      5. clip(±3): 截断|z|>3的极端值 (DESIGN_V5 §4.4)

    Args:
        factor_series: 原始因子截面值
        ln_mcap: 对数市值
        industry: 行业分类

    Returns:
        (raw_value, neutral_value) 两个Series
    """
    raw = factor_series.copy()

    # Step 1: MAD去极值 (5σ)
    step1 = preprocess_mad(raw)
    # Step 2: 缺失值填充
    step2 = preprocess_fill(step1, industry)
    # Step 3: WLS中性化 (行业+市值加权回归)
    step3 = preprocess_neutralize(step2, ln_mcap, industry)
    # Step 4: zscore
    step4 = preprocess_zscore(step3)
    # Step 5: clip ±3σ (截断zscore极端值)
    step5 = step4.clip(lower=-3.0, upper=3.0)

    return raw, step5


# ============================================================
# IC计算
# ============================================================

def calc_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    method: str = "spearman",
) -> float:
    """计算单日单因子的IC (Information Coefficient)。

    Args:
        factor_values: 因子截面值 (index=code)
        forward_returns: 前向超额收益 (index=code)
        method: 'spearman'(rank IC) 或 'pearson'

    Returns:
        IC值 (float)
    """
    # 对齐index
    common = factor_values.dropna().index.intersection(forward_returns.dropna().index)
    if len(common) < 30:
        return np.nan

    f = factor_values.loc[common]
    r = forward_returns.loc[common]

    if method == "spearman":
        return f.rank().corr(r.rank())
    else:
        return f.corr(r)


# ============================================================
# 数据加载 (读取行情 + daily_basic, 计算adj_close)
# ============================================================

def load_daily_data(
    trade_date: date,
    lookback_days: int = 120,
    conn=None,
) -> pd.DataFrame:
    """加载因子计算所需的每日数据。

    合并 klines_daily + daily_basic, 计算前复权价格。

    Args:
        trade_date: 计算日期
        lookback_days: 回看天数(用于滚动计算)
        conn: psycopg2连接

    Returns:
        DataFrame with columns: code, trade_date, open, high, low, close,
        volume, amount, adj_factor, adj_close, adj_high, adj_low,
        turnover_rate, total_mv, pb, pe_ttm, industry_sw1
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        )
        SELECT
            k.code,
            k.trade_date,
            k.open, k.high, k.low, k.close,
            k.volume, k.amount,
            k.adj_factor,
            k.close * k.adj_factor / la.latest_adj_factor AS adj_close,
            k.high  * k.adj_factor / la.latest_adj_factor AS adj_high,
            k.low   * k.adj_factor / la.latest_adj_factor AS adj_low,
            db.turnover_rate,
            db.total_mv,
            db.pb,
            db.pe_ttm,
            db.dv_ttm,
            s.industry_sw1
        FROM klines_daily k
        JOIN latest_adj la ON k.code = la.code
        LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
        LEFT JOIN symbols s ON k.code = s.code
        WHERE k.trade_date BETWEEN
            (SELECT DISTINCT trade_date FROM klines_daily
             WHERE trade_date <= %s
             ORDER BY trade_date DESC
             OFFSET %s LIMIT 1)
            AND %s
          AND k.adj_factor IS NOT NULL
          AND k.volume > 0
        ORDER BY k.code, k.trade_date
        """
        df = pd.read_sql(sql, conn, params=(trade_date, lookback_days, trade_date))
        return df
    finally:
        if close_conn:
            conn.close()


def load_forward_returns(
    trade_date: date,
    horizon: int = 5,
    conn=None,
) -> pd.Series:
    """加载前向超额收益(vs CSI300)。

    Args:
        trade_date: 基准日期
        horizon: 前看天数(1/5/10/20)
        conn: psycopg2连接

    Returns:
        pd.Series indexed by code, values = excess return
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        # 先找到N个交易日后的日期
        future_date_df = pd.read_sql(
            """SELECT DISTINCT trade_date FROM klines_daily
               WHERE trade_date > %s ORDER BY trade_date LIMIT %s""",
            conn, params=(trade_date, horizon),
        )
        if future_date_df.empty:
            return pd.Series(dtype=float)
        future_date = future_date_df.iloc[-1]["trade_date"]

        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        ),
        base AS (
            SELECT k.code,
                   k.close * k.adj_factor / la.latest_adj_factor AS adj_close
            FROM klines_daily k
            JOIN latest_adj la ON k.code = la.code
            WHERE k.trade_date = %s AND k.adj_factor IS NOT NULL
        ),
        future AS (
            SELECT k.code,
                   k.close * k.adj_factor / la.latest_adj_factor AS adj_close
            FROM klines_daily k
            JOIN latest_adj la ON k.code = la.code
            WHERE k.trade_date = %s AND k.adj_factor IS NOT NULL
        )
        SELECT
            b.code,
            (f.adj_close / NULLIF(b.adj_close, 0) - 1)
            - (
                (SELECT close FROM index_daily
                 WHERE index_code = '000300.SH' AND trade_date = %s)
                / NULLIF(
                    (SELECT close FROM index_daily
                     WHERE index_code = '000300.SH' AND trade_date = %s), 0)
                - 1
              ) AS excess_return
        FROM base b
        JOIN future f ON b.code = f.code
        """
        df = pd.read_sql(
            sql, conn,
            params=(trade_date, future_date, future_date, trade_date),
        )
        return df.set_index("code")["excess_return"]
    finally:
        if close_conn:
            conn.close()


# ============================================================
# 因子写入
# ============================================================

def save_daily_factors(
    trade_date: date,
    factor_df: pd.DataFrame,
    conn=None,
) -> int:
    """按日期批量写入因子值(单事务)。

    CLAUDE.md强制要求: 一次事务写入当日全部股票×全部因子。

    Args:
        trade_date: 交易日期
        factor_df: DataFrame with columns [code, factor_name, raw_value, neutral_value, zscore]
        conn: psycopg2连接

    Returns:
        写入行数
    """
    from psycopg2.extras import execute_values

    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    def _safe_float(val):
        """将NaN/inf转为None（PostgreSQL NUMERIC不支持inf）。"""
        if pd.isna(val):
            return None
        v = float(val)
        if not np.isfinite(v):
            return None
        return v

    try:
        rows = []
        for _, row in factor_df.iterrows():
            rows.append((
                row["code"],
                trade_date,
                row["factor_name"],
                _safe_float(row.get("raw_value")),
                _safe_float(row.get("neutral_value")),
                _safe_float(row.get("zscore")),
            ))

        with conn.cursor() as cur:
            execute_values(
                cur,
                """INSERT INTO factor_values (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                   VALUES %s
                   ON CONFLICT (code, trade_date, factor_name)
                   DO UPDATE SET raw_value = EXCLUDED.raw_value,
                                 neutral_value = EXCLUDED.neutral_value,
                                 zscore = EXCLUDED.zscore""",
                rows,
                page_size=5000,
            )
        conn.commit()
        logger.info(f"[{trade_date}] 写入因子 {len(rows)} 行")
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()


# ============================================================
# 主流程: 单日因子计算
# ============================================================

def compute_daily_factors(
    trade_date: date,
    factor_set: str = "core",
    conn=None,
    include_reserve: bool = True,
) -> pd.DataFrame:
    """计算单日全部因子。

    Args:
        trade_date: 交易日期
        factor_set: 'core'(5因子) / 'full'(不含deprecated) / 'all'(含deprecated,向后兼容)
        conn: 可选连接
        include_reserve: 是否包含Reserve池因子(默认True, 日常管道计算)

    Returns:
        DataFrame [code, factor_name, raw_value, neutral_value, zscore]
    """
    if factor_set == "core":
        factors = dict(PHASE0_CORE_FACTORS)
    elif factor_set == "all":
        logger.warning("factor_set='all' 包含deprecated因子，仅用于历史分析/对比")
        factors = dict(PHASE0_ALL_FACTORS)
    else:
        factors = dict(PHASE0_FULL_FACTORS)

    # Reserve池因子随日常管道一起计算(不入v1.1等权组合, 仅写入factor_values供监控)
    if include_reserve:
        factors.update(RESERVE_FACTORS)
        factors.update(ALPHA158_FACTORS)

    # 1. 加载数据
    logger.info(f"[{trade_date}] 加载行情数据...")
    df = load_daily_data(trade_date, lookback_days=120, conn=conn)

    if df.empty:
        logger.warning(f"[{trade_date}] 无数据，跳过")
        return pd.DataFrame()

    # 取当日截面
    today_mask = df["trade_date"] == trade_date
    if today_mask.sum() == 0:
        logger.warning(f"[{trade_date}] 当日无数据，跳过")
        return pd.DataFrame()

    today_codes = df.loc[today_mask, "code"].values
    today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
    today_industry.index = today_codes
    today_ln_mcap = df.loc[today_mask, "total_mv"].apply(lambda x: np.log(x + 1e-12))
    today_ln_mcap.index = today_codes

    # 2. 计算每个因子
    all_results = []

    for factor_name, calc_fn in factors.items():
        try:
            logger.debug(f"[{trade_date}] 计算因子: {factor_name}")

            # 计算原始值
            raw_series = calc_fn(df)

            # 取当日截面
            raw_today = raw_series[today_mask].copy()
            raw_today.index = today_codes

            # 预处理
            raw_val, neutral_val = preprocess_pipeline(
                raw_today, today_ln_mcap, today_industry
            )

            # 组装结果
            for code in today_codes:
                rv = raw_val.get(code, np.nan)
                nv = neutral_val.get(code, np.nan)
                all_results.append({
                    "code": code,
                    "factor_name": factor_name,
                    "raw_value": rv,
                    "neutral_value": nv,
                    "zscore": nv,  # neutral_value已经是zscore
                })
        except Exception as e:
            logger.error(f"[{trade_date}] 因子 {factor_name} 计算失败: {e}")
            continue

    result_df = pd.DataFrame(all_results)
    logger.info(
        f"[{trade_date}] 计算完成: {len(factors)}因子 × {len(today_codes)}股 = {len(result_df)}行"
    )
    return result_df


# ============================================================
# 批量计算: 一次加载全量数据, 逐日计算+写入
# ============================================================

def load_bulk_data(
    start_date: date,
    end_date: date,
    conn=None,
) -> pd.DataFrame:
    """批量加载行情数据(含前复权价格)。

    一次性加载 [start_date-120天, end_date] 的全部数据，
    避免逐日加载的重复IO。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        conn: psycopg2连接

    Returns:
        DataFrame sorted by (code, trade_date)
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        ),
        lookback_start AS (
            SELECT COALESCE(
                (SELECT DISTINCT trade_date FROM klines_daily
                 WHERE trade_date <= %s
                 ORDER BY trade_date DESC
                 OFFSET 120 LIMIT 1),
                (SELECT MIN(trade_date) FROM klines_daily)
            ) AS trade_date
        )
        SELECT
            k.code,
            k.trade_date,
            k.open, k.high, k.low, k.close,
            k.volume, k.amount,
            k.adj_factor,
            k.close * k.adj_factor / la.latest_adj_factor AS adj_close,
            k.high  * k.adj_factor / la.latest_adj_factor AS adj_high,
            k.low   * k.adj_factor / la.latest_adj_factor AS adj_low,
            db.turnover_rate,
            db.total_mv,
            db.pb,
            db.pe_ttm,
            db.dv_ttm,
            s.industry_sw1
        FROM klines_daily k
        JOIN latest_adj la ON k.code = la.code
        LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
        LEFT JOIN symbols s ON k.code = s.code
        WHERE k.trade_date BETWEEN (SELECT trade_date FROM lookback_start) AND %s
          AND k.adj_factor IS NOT NULL
          AND k.volume > 0
        ORDER BY k.code, k.trade_date
        """
        logger.info(f"批量加载数据: {start_date} → {end_date} (+120天回看)")
        df = pd.read_sql(sql, conn, params=(start_date, end_date))
        logger.info(f"数据加载完成: {len(df)}行, {df['code'].nunique()}股, "
                     f"{df['trade_date'].nunique()}天")
        return df
    finally:
        if close_conn:
            conn.close()


# ============================================================
# ML特征数据加载 (moneyflow + index)
# ============================================================

def load_bulk_moneyflow(
    start_date: date,
    end_date: date,
    conn=None,
) -> pd.DataFrame:
    """批量加载资金流数据。

    加载 [start_date-120天, end_date] 的 moneyflow_daily 数据。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        conn: psycopg2连接

    Returns:
        DataFrame with moneyflow columns, sorted by (code, trade_date)
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH lookback_start AS (
            SELECT COALESCE(
                (SELECT DISTINCT trade_date FROM klines_daily
                 WHERE trade_date <= %s
                 ORDER BY trade_date DESC
                 OFFSET 120 LIMIT 1),
                (SELECT MIN(trade_date) FROM klines_daily)
            ) AS trade_date
        )
        SELECT
            mf.code,
            mf.trade_date,
            mf.buy_sm_amount,
            mf.buy_md_amount,
            mf.buy_lg_amount,
            mf.buy_elg_amount,
            mf.net_mf_amount
        FROM moneyflow_daily mf
        WHERE mf.trade_date BETWEEN (SELECT trade_date FROM lookback_start) AND %s
        ORDER BY mf.code, mf.trade_date
        """
        logger.info(f"批量加载资金流数据: {start_date} → {end_date} (+120天回看)")
        df = pd.read_sql(sql, conn, params=(start_date, end_date))
        logger.info(f"资金流数据加载完成: {len(df)}行, {df['code'].nunique()}股")
        return df
    finally:
        if close_conn:
            conn.close()


def load_index_returns(
    start_date: date,
    end_date: date,
    index_code: str = "000300.SH",
    conn=None,
) -> pd.Series:
    """加载指数日收益率序列。

    用于计算个股beta。返回以trade_date为index的收益率Series。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        index_code: 指数代码, 默认沪深300
        conn: psycopg2连接

    Returns:
        pd.Series: 指数日收益率, index=trade_date
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH lookback_start AS (
            SELECT COALESCE(
                (SELECT DISTINCT trade_date FROM klines_daily
                 WHERE trade_date <= %s
                 ORDER BY trade_date DESC
                 OFFSET 120 LIMIT 1),
                (SELECT MIN(trade_date) FROM klines_daily)
            ) AS trade_date
        )
        SELECT trade_date, close
        FROM index_daily
        WHERE index_code = %s
          AND trade_date BETWEEN (SELECT trade_date FROM lookback_start) AND %s
        ORDER BY trade_date
        """
        logger.info(f"加载指数 {index_code} 收益率: {start_date} → {end_date}")
        df = pd.read_sql(sql, conn, params=(start_date, index_code, end_date))
        if df.empty:
            logger.warning(f"指数 {index_code} 无数据")
            return pd.Series(dtype=float)
        ret = df.set_index("trade_date")["close"].pct_change(1)
        ret.name = "index_ret"
        return ret
    finally:
        if close_conn:
            conn.close()


def load_bulk_data_with_extras(
    start_date: date,
    end_date: date,
    conn=None,
) -> pd.DataFrame:
    """批量加载行情+资金流+指数收益率数据(ML特征专用)。

    在 load_bulk_data 基础上, 左连接 moneyflow_daily 的资金流字段,
    并合并沪深300日收益率(按trade_date对齐)。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        conn: psycopg2连接

    Returns:
        DataFrame with all columns needed for ML features
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        # 1. 基础行情数据
        df = load_bulk_data(start_date, end_date, conn=conn)
        if df.empty:
            return df

        # 2. 资金流数据
        mf = load_bulk_moneyflow(start_date, end_date, conn=conn)
        if not mf.empty:
            df = df.merge(mf, on=["code", "trade_date"], how="left")
            logger.info(f"合并资金流数据: moneyflow匹配率 "
                        f"{df['net_mf_amount'].notna().mean():.1%}")
        else:
            logger.warning("资金流数据为空, moneyflow因子将全为NaN")
            for col in ["buy_sm_amount", "buy_md_amount", "buy_lg_amount",
                        "buy_elg_amount", "net_mf_amount"]:
                df[col] = np.nan

        # 3. 指数收益率
        idx_ret = load_index_returns(start_date, end_date, conn=conn)
        if not idx_ret.empty:
            idx_ret_df = idx_ret.reset_index()
            idx_ret_df.columns = ["trade_date", "index_ret"]
            df = df.merge(idx_ret_df, on="trade_date", how="left")
            logger.info(f"合并指数收益率: index_ret匹配率 "
                        f"{df['index_ret'].notna().mean():.1%}")
        else:
            logger.warning("指数收益率为空, beta因子将全为NaN")
            df["index_ret"] = np.nan

        return df
    finally:
        if close_conn:
            conn.close()


def compute_batch_factors(
    start_date: date,
    end_date: date,
    factor_set: str = "core",
    conn=None,
    write: bool = True,
    factor_names: list[str] | None = None,
) -> dict:
    """批量计算因子并逐日写入。

    高效模式: 一次加载全量数据 → 计算滚动因子 → 逐日预处理+写入。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        factor_set: 'core'/'full'/'all'/'ml'/'lgbm'/'fundamental'(8个PIT因子)/'lgbm_v2'(5基线+8基本面=13个)
        conn: 可选连接
        write: 是否写入数据库
        factor_names: 可选，只计算指定因子列表。None=计算全部。

    Returns:
        dict with stats (total_rows, elapsed, etc.)
    """
    import time

    from psycopg2.extras import execute_values

    from app.services.price_utils import _get_sync_conn

    use_extras = False  # 是否需要加载moneyflow+index数据
    use_fundamental = False  # 是否需要加载PIT财务数据
    include_reserve = False  # Reserve池因子是否加入
    if factor_set == "core":
        factors = dict(PHASE0_CORE_FACTORS)
        include_reserve = True
    elif factor_set == "all":
        logger.warning("factor_set='all' 包含deprecated因子，仅用于历史分析/对比")
        factors = dict(PHASE0_ALL_FACTORS)
        include_reserve = True
    elif factor_set == "ml":
        factors = dict(ML_FEATURES)
        use_extras = True
    elif factor_set == "lgbm":
        factors = dict(LIGHTGBM_FEATURE_SET)
        use_extras = True
    elif factor_set == "fundamental":
        # 仅计算8个基本面+时间因子(不需要kline滚动因子)
        factors = {}
        use_fundamental = True
    elif factor_set == "lgbm_v2":
        # 5基线 + 6delta + 2时间 = 13个
        factors = {k: v for k, v in PHASE0_CORE_FACTORS.items()
                   if k in LGBM_V2_BASELINE_FACTORS}
        # reversal_20 在 PHASE0_FULL_FACTORS 中
        if "reversal_20" not in factors:
            factors["reversal_20"] = PHASE0_FULL_FACTORS.get("reversal_20")
        use_fundamental = True
    else:
        factors = dict(PHASE0_FULL_FACTORS)
        include_reserve = True

    # Reserve池因子随日常管道一起计算(不入v1.1等权组合)
    if include_reserve:
        factors.update(RESERVE_FACTORS)
    if factor_names:
        factors = {k: v for k, v in factors.items() if k in factor_names}
        if not factors:
            logger.warning(f"指定的因子名 {factor_names} 在 {factor_set} 集中均未找到")
            return {"total_rows": 0, "elapsed": 0, "dates": 0,
                    "load_time": 0, "calc_time": 0, "total_time": 0}
        # 仅当实际需要moneyflow/index因子时才加载额外数据
        _mf_and_idx = set(ML_FEATURES_MONEYFLOW) | set(ML_FEATURES_INDEX)
        use_extras = use_extras and bool(set(factors) & _mf_and_idx)

    # 字符串→date转换（命令行调用时传入str）
    if isinstance(start_date, str):
        from datetime import datetime as _dt
        start_date = _dt.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        from datetime import datetime as _dt
        end_date = _dt.strptime(end_date, "%Y-%m-%d").date()

    if conn is None:
        conn = _get_sync_conn()

    t0 = time.time()

    # 1. 一次性加载全量数据 (kline因子需要)
    if factors:
        if use_extras:
            df = load_bulk_data_with_extras(start_date, end_date, conn=conn)
        else:
            df = load_bulk_data(start_date, end_date, conn=conn)
        if df.empty:
            return {"total_rows": 0, "elapsed": 0, "dates": 0,
                    "load_time": 0, "calc_time": 0, "total_time": 0}
    else:
        # fundamental-only模式: 仍需kline数据获取交易日列表和截面信息
        df = load_bulk_data(start_date, end_date, conn=conn)
        if df.empty:
            return {"total_rows": 0, "elapsed": 0, "dates": 0,
                    "load_time": 0, "calc_time": 0, "total_time": 0}

    t_load = time.time() - t0

    # 2. 一次性计算所有kline因子的滚动值
    logger.info(f"计算 {len(factors)} 个kline因子的滚动值...")
    factor_raw = {}
    for fname, calc_fn in factors.items():
        try:
            factor_raw[fname] = calc_fn(df)
        except Exception as e:
            logger.error(f"因子 {fname} 计算失败: {e}")

    t_calc = time.time() - t0 - t_load

    # 3. 获取计算范围内的交易日
    all_dates = sorted(df.loc[
        (df["trade_date"] >= start_date) &
        (df["trade_date"] <= end_date),
        "trade_date"
    ].unique())

    n_fund = len(FUNDAMENTAL_ALL_FEATURES) if use_fundamental else 0
    logger.info(f"逐日预处理+写入: {len(all_dates)}个交易日"
                f"{f' (含{n_fund}个基本面因子)' if use_fundamental else ''}")

    total_rows = 0
    for i, td in enumerate(all_dates):
        td_date = td.date() if hasattr(td, "date") else td

        # 取当日截面
        today_mask = df["trade_date"] == td
        if today_mask.sum() == 0:
            continue

        today_codes = df.loc[today_mask, "code"].values
        today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
        today_industry.index = today_codes
        today_ln_mcap = df.loc[today_mask, "total_mv"].apply(
            lambda x: np.log(x + 1e-12)
        )
        today_ln_mcap.index = today_codes

        def _safe(v):
            """将NaN/inf转为None。"""
            if pd.isna(v):
                return None
            fv = float(v)
            return None if not np.isfinite(fv) else fv

        # 逐因子预处理 (kline因子)
        day_rows = []
        for fname in factor_raw:
            raw_today = factor_raw[fname][today_mask].copy()
            raw_today.index = today_codes

            raw_val, neutral_val = preprocess_pipeline(
                raw_today, today_ln_mcap, today_industry
            )

            for code in today_codes:
                rv = raw_val.get(code, np.nan)
                nv = neutral_val.get(code, np.nan)
                day_rows.append((
                    code, td_date, fname,
                    _safe(rv), _safe(nv), _safe(nv),
                ))

        # 基本面delta因子 (PIT加载, 逐日计算)
        if use_fundamental:
            try:
                fund_data = load_fundamental_pit_data(td_date, conn)
                for fname, raw_series in fund_data.items():
                    if raw_series.empty:
                        continue
                    # 对齐到当日截面的code集合
                    raw_aligned = raw_series.reindex(today_codes)

                    raw_val, neutral_val = preprocess_pipeline(
                        raw_aligned, today_ln_mcap, today_industry
                    )

                    for code in today_codes:
                        rv = raw_val.get(code, np.nan)
                        nv = neutral_val.get(code, np.nan)
                        day_rows.append((
                            code, td_date, fname,
                            _safe(rv), _safe(nv), _safe(nv),
                        ))
            except Exception as e:
                logger.error(f"[{td_date}] 基本面因子计算失败: {e}")

        # 写入当日所有因子(单事务)
        if write and day_rows:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """INSERT INTO factor_values
                       (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                       VALUES %s
                       ON CONFLICT (code, trade_date, factor_name)
                       DO UPDATE SET raw_value = EXCLUDED.raw_value,
                                     neutral_value = EXCLUDED.neutral_value,
                                     zscore = EXCLUDED.zscore""",
                    day_rows,
                    page_size=5000,
                )
            conn.commit()

        total_rows += len(day_rows)
        if (i + 1) % 50 == 0 or i == 0 or i == len(all_dates) - 1:
            elapsed = time.time() - t0
            logger.info(
                f"  [{i+1}/{len(all_dates)}] {td_date} | "
                f"{len(day_rows)}行 | 累计{total_rows}行 | "
                f"{elapsed:.0f}s"
            )

    elapsed = time.time() - t0
    stats = {
        "total_rows": total_rows,
        "dates": len(all_dates),
        "load_time": round(t_load, 1),
        "calc_time": round(t_calc, 1),
        "total_time": round(elapsed, 1),
    }
    logger.info(
        f"批量因子计算完成: {stats['dates']}天, {total_rows}行, "
        f"加载{t_load:.0f}s + 计算{t_calc:.0f}s + 总计{elapsed:.0f}s"
    )
    return stats
