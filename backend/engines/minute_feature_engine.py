"""分钟级数据日频特征引擎 — 纯计算, 无IO (铁律31)。

从5分钟K线聚合日频特征, 用于因子池扩展和多策略框架。
每个特征函数接收单日单股的numpy数组, 返回标量值。

特征来源:
  - Phase 3E 验证通过 (IC PASS + noise ROBUST): 4个
  - AlphaZero 因子进化 (Alpha1/Alpha2): 2个
  - FactorMiner 成交效率因子: 1个
  - Microstructure-Empowered: 1个
  - 学术共识 (日内动量/量价背离): 2个

架构:
  Engine (本文件) = 纯计算, 输入numpy数组, 输出dict
  编排脚本 (scripts/compute_minute_features.py) = 数据加载 + rolling + DB写入
"""

from __future__ import annotations

from typing import Any

import numpy as np

# ============================================================
# 特征注册表
# ============================================================

MINUTE_FEATURES: list[str] = [
    # Phase 3E 验证通过 (IC最强, noise ROBUST)
    "high_freq_volatility_20",       # 已实现高频波动率
    "volume_concentration_20",       # Herfindahl量集中度
    "volume_autocorr_20",            # 量自相关
    "smart_money_ratio_20",          # 尾盘/开盘量比
    # AlphaZero Alpha2 (ICIR=7.2)
    "opening_volume_share_20",       # 开盘30分钟量能占比
    # AlphaZero Alpha1
    "closing_trend_strength_20",     # 尾盘30分钟趋势强度
    # FactorMiner 成交效率
    "vwap_deviation_20",             # VWAP偏离度
    # Microstructure-Empowered
    "order_flow_imbalance_20",       # 订单流不平衡代理
    # 学术共识
    "intraday_momentum_20",          # 日内动量(前半段预测后半段)
    "volume_price_divergence_20",    # 量价背离
]

# 因子方向 (唯一真相源: factor_engine/_constants.py, 此处 re-export 保持向后兼容)
from engines.factor_engine._constants import MINUTE_FACTOR_DIRECTION  # noqa: E402,F401

# 日内raw指标名 (去掉_20后缀, 用于rolling前)
_DAILY_KEYS: list[str] = [f.replace("_20", "") for f in MINUTE_FEATURES]


# ============================================================
# 核心计算函数
# ============================================================


def compute_daily_minute_features(
    o: np.ndarray,
    h: np.ndarray,
    lo: np.ndarray,
    c: np.ndarray,
    v: np.ndarray,
    amt: np.ndarray,
    mod: np.ndarray,
) -> dict[str, float]:
    """计算单日单股的全部10个日内raw指标。

    Args:
        o: 开盘价数组 (48 bars, float64)
        h: 最高价数组
        lo: 最低价数组
        c: 收盘价数组
        v: 成交量数组 (手)
        amt: 成交额数组 (元)
        mod: minute_of_day 索引 (0-47)

    Returns:
        dict: {指标名(无_20后缀): raw日频值}
        数据不足时返回NaN。
    """
    n = len(c)
    if n < 10:
        return {k: np.nan for k in _DAILY_KEYS}

    # 预计算: 5分钟close-to-close收益率
    ret = np.diff(c) / np.where(c[:-1] != 0, c[:-1], np.nan)  # (n-1,)
    valid_ret = ret[np.isfinite(ret)]

    # 预计算: bar收益率 (open-to-close)
    bar_ret = (c - o) / np.where(o != 0, o, np.nan)  # (n,)

    total_vol = v.sum()

    result: dict[str, float] = {}

    # ---- 1. high_freq_volatility: 已实现波动率 (sum of squared returns) ----
    result["high_freq_volatility"] = _calc_high_freq_volatility(ret)

    # ---- 2. volume_concentration: Herfindahl量集中度 ----
    result["volume_concentration"] = _calc_volume_concentration(v, total_vol)

    # ---- 3. volume_autocorr: 成交量lag-1自相关 ----
    result["volume_autocorr"] = _calc_volume_autocorr(v)

    # ---- 4. smart_money_ratio: 尾盘/开盘成交量比 ----
    result["smart_money_ratio"] = _calc_smart_money_ratio(v, mod)

    # ---- 5. opening_volume_share: 开盘30分钟量能占比 (AlphaZero Alpha2) ----
    result["opening_volume_share"] = _calc_opening_volume_share(v, mod, total_vol)

    # ---- 6. closing_trend_strength: 尾盘30分钟趋势强度 (AlphaZero Alpha1) ----
    result["closing_trend_strength"] = _calc_closing_trend_strength(c, o, mod)

    # ---- 7. vwap_deviation: VWAP偏离度 (FactorMiner) ----
    result["vwap_deviation"] = _calc_vwap_deviation(c, amt, v)

    # ---- 8. order_flow_imbalance: 订单流不平衡代理 ----
    result["order_flow_imbalance"] = _calc_order_flow_imbalance(c, o, v, bar_ret)

    # ---- 9. intraday_momentum: 日内动量 ----
    result["intraday_momentum"] = _calc_intraday_momentum(bar_ret, n)

    # ---- 10. volume_price_divergence: 量价背离 ----
    result["volume_price_divergence"] = _calc_volume_price_divergence(
        v, valid_ret, ret
    )

    return result


# ============================================================
# 各特征计算纯函数
# ============================================================


def _calc_high_freq_volatility(ret: np.ndarray) -> float:
    """已实现高频波动率: sum(r²)。

    经济机制: 高频波动率捕捉日内价格不确定性,
    高不确定性→散户恐慌抛售→次日反弹(反转效应)。
    """
    valid = ret[np.isfinite(ret)]
    if len(valid) < 5:
        return np.nan
    return float(np.sum(valid**2))


def _calc_volume_concentration(v: np.ndarray, total_vol: float) -> float:
    """Herfindahl量集中度: sum(vol_share²)。

    经济机制: 成交量均匀分布(低HHI)→信息持续流入, 市场定价效率高;
    集中在少数bar(高HHI)→大单冲击或流动性枯竭→价格失真。
    """
    if total_vol <= 0:
        return np.nan
    vol_share = v / total_vol
    return float(np.sum(vol_share**2))


def _calc_volume_autocorr(v: np.ndarray) -> float:
    """成交量lag-1自相关系数。

    经济机制: 低自相关→信息混合快, 不同时段投资者类型多元;
    高自相关→羊群效应, 同一类交易者连续操作。
    """
    if len(v) < 10 or np.std(v) < 1e-10:
        return np.nan
    corr = np.corrcoef(v[:-1], v[1:])[0, 1]
    return float(corr) if np.isfinite(corr) else np.nan


def _calc_smart_money_ratio(v: np.ndarray, mod: np.ndarray) -> float:
    """尾盘/开盘成交量比 (smart money indicator)。

    经济机制: 机构倾向在尾盘交易(信息不对称最低时),
    尾盘>开盘→机构主导日→次日延续。
    Last 6 bars (14:30-15:00, mod 42-47) / First 6 bars (09:35-10:05, mod 0-5)。
    """
    first_vol = v[mod <= 5].sum()
    last_vol = v[mod >= 42].sum()
    if first_vol <= 0:
        return np.nan
    return float(last_vol / first_vol)


def _calc_opening_volume_share(
    v: np.ndarray, mod: np.ndarray, total_vol: float
) -> float:
    """开盘30分钟量能占比 (AlphaZero Alpha2, ICIR=7.2)。

    经济机制: 开盘半小时量能占比高→散户追涨行为集中→当日已过度反应,
    次日容易反转。AlphaZero原文用5日时序最小值, 此处先取日值,
    rolling时取min替代mean更贴近原文。

    开盘30分钟 = 9:35-10:05 = 前6个bar (mod 0-5)。
    """
    if total_vol <= 0:
        return np.nan
    opening_vol = v[mod <= 5].sum()
    return float(opening_vol / total_vol)


def _calc_closing_trend_strength(
    c: np.ndarray, o: np.ndarray, mod: np.ndarray
) -> float:
    """尾盘30分钟趋势强度 (AlphaZero Alpha1)。

    经济机制: 尾盘趋势反映机构投资者的方向性判断,
    尾盘正趋势(收盘>14:30开盘)→机构加仓→次日延续。

    计算: 尾盘区间收益 / 全日收益的绝对值。
    尾盘 = 最后6个bar (mod 42-47)。
    """
    tail_mask = mod >= 42
    if tail_mask.sum() < 3:
        return np.nan

    # 尾盘收益: 最后bar收盘 / 尾盘首bar开盘 - 1
    tail_o = o[tail_mask]
    tail_c = c[tail_mask]
    if tail_o[0] <= 0:
        return np.nan
    tail_ret = (tail_c[-1] - tail_o[0]) / tail_o[0]

    # 全日收益
    if o[0] <= 0:
        return np.nan
    day_ret = (c[-1] - o[0]) / o[0]

    # 归一化: 尾盘占全日比例 (保留符号)
    if abs(day_ret) < 1e-10:
        # 全日平盘, 尾盘趋势就是绝对值
        return float(tail_ret)
    return float(tail_ret / abs(day_ret))


def _calc_vwap_deviation(
    c: np.ndarray, amt: np.ndarray, v: np.ndarray
) -> float:
    """VWAP偏离度 (FactorMiner 成交效率因子)。

    经济机制: 收盘价低于VWAP→日内卖方占优→短期超卖→次日反弹;
    收盘价高于VWAP→日内买方占优→短期超买→次日回调。

    计算: close[-1] / VWAP - 1, 其中 VWAP = sum(amount) / sum(volume)。
    """
    total_vol = v.sum()
    total_amt = amt.sum()
    if total_vol <= 0 or total_amt <= 0:
        return np.nan

    # VWAP = 总成交额 / 总成交量 (amt单位元, v单位手→需×100得股数)
    # 但因为close单位也是元/股, VWAP = amt / (v * 100)
    vwap = total_amt / (total_vol * 100.0)
    close_price = c[-1]
    if vwap <= 0 or close_price <= 0:
        return np.nan
    return float(close_price / vwap - 1.0)


def _calc_order_flow_imbalance(
    c: np.ndarray,
    o: np.ndarray,
    v: np.ndarray,
    bar_ret: np.ndarray,
) -> float:
    """订单流不平衡代理 (Microstructure-Empowered)。

    经济机制: 正bar(close>open)的成交量视为"买量",
    负bar(close<open)视为"卖量"。净买入/总量→反映订单流方向。
    无逐笔数据时的最佳代理指标。

    计算: sum(v * sign(bar_ret)) / sum(v)。
    """
    total_vol = v.sum()
    if total_vol <= 0:
        return np.nan

    # 用bar收益率符号加权
    signs = np.sign(np.where(np.isfinite(bar_ret), bar_ret, 0))
    flow = np.sum(v * signs)
    return float(flow / total_vol)


def _calc_intraday_momentum(bar_ret: np.ndarray, n: int) -> float:
    """日内动量: 前半段收益率与后半段收益率的相关性代理。

    经济机制: 日内动量(上午涨→下午也涨)反映"追涨杀跌"散户行为,
    高日内动量→散户过度推动→次日反转。
    低/负日内动量→日内已反转→次日延续。

    计算: (上午bar_ret均值 - 下午bar_ret均值) / 全日bar_ret std。
    """
    half = n // 2
    first_half = bar_ret[:half]
    second_half = bar_ret[half:]

    fh = first_half[np.isfinite(first_half)]
    sh = second_half[np.isfinite(second_half)]

    if len(fh) < 5 or len(sh) < 5:
        return np.nan

    all_valid = bar_ret[np.isfinite(bar_ret)]
    std_all = np.std(all_valid, ddof=1)
    if std_all < 1e-10:
        return np.nan

    # 前后半段均值差 / 全日波动率
    return float((np.mean(fh) - np.mean(sh)) / std_all)


def _calc_volume_price_divergence(
    v: np.ndarray,
    valid_ret: np.ndarray,
    ret: np.ndarray,
) -> float:
    """量价背离度: 价格变动方向与成交量变动方向的负相关程度。

    经济机制: 价涨但量缩→上涨动能耗竭, 次日容易回调;
    价跌但量缩→恐慌情绪减弱, 次日可能企稳。
    量价背离是经典的趋势耗竭信号。

    计算: -corr(|return|, volume[1:])。取负号使"背离"为正值。
    """
    if len(valid_ret) < 10:
        return np.nan

    # ret 长度 = n-1, 对应 v[1:] (每个return对应那个bar的量)
    v_aligned = v[1: len(ret) + 1]
    mask = np.isfinite(ret) & (v_aligned > 0)
    if mask.sum() < 10:
        return np.nan

    abs_ret = np.abs(ret[mask])
    vol = v_aligned[mask].astype(np.float64)

    if np.std(abs_ret) < 1e-15 or np.std(vol) < 1e-10:
        return np.nan

    corr = np.corrcoef(abs_ret, vol)[0, 1]
    if not np.isfinite(corr):
        return np.nan

    # 取负: 正值=背离(|ret|↑但vol↓), 负值=同步
    return float(-corr)


# ============================================================
# 批量计算接口
# ============================================================


def compute_batch_features(
    daily_groups: list[tuple[str, Any, np.ndarray, np.ndarray, np.ndarray,
                             np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
) -> list[tuple[str, Any, str, float]]:
    """批量计算日频特征。

    Args:
        daily_groups: [(code, trade_date, o, h, lo, c, v, amt, mod), ...]

    Returns:
        [(code, trade_date, factor_key, value), ...]
    """
    records = []
    for code, td, o, h, lo, c, v, amt, mod in daily_groups:
        metrics = compute_daily_minute_features(o, h, lo, c, v, amt, mod)
        for key, val in metrics.items():
            records.append((code, td, key, val))
    return records
