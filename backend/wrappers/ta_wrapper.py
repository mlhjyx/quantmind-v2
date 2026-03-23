"""TA-Lib统一接口 -- CLAUDE.md规则5: 一个工具一个wrapper。

130+技术指标的统一入口。底层调TA-Lib C库，上层通过calculate_indicator()
单一入口访问。Service层只依赖本模块，不直接import talib。

CLAUDE.md规则2(数据格式统一): 所有因子不管来源，最终都是
(code, trade_date, factor_value)写入factor_values表。
"""

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


def calculate_indicator(
    name: str,
    prices: dict[str, np.ndarray],
    **params: Any,
) -> np.ndarray:
    """计算技术指标（统一入口）。

    Args:
        name: 指标名称（大写），如 "RSI", "MACD", "ATR", "BBANDS" 等
        prices: 行情数据字典。键为 'open','high','low','close','volume'，
                值为 np.ndarray（float64, 按时间升序）
        **params: 指标参数。参数名与TA-Lib原始参数一致。

    Returns:
        np.ndarray: 计算结果。多输出指标返回主输出。
            - RSI: RSI值
            - MACD: MACD柱状图 (histogram)
            - ATR: ATR值
            - BBANDS: 中轨 (middleband)
            - ADX: ADX值
            - OBV: OBV值
            - CCI: CCI值

    Raises:
        RuntimeError: TA-Lib未安装
        ValueError: 未知指标名或缺少必需价格数据
    """
    try:
        import talib
    except ImportError:
        raise RuntimeError(
            "TA-Lib未安装: brew install ta-lib && pip install TA-Lib"
        )

    name = name.upper()

    # 提取常用价格序列
    close = prices.get("close")
    high = prices.get("high")
    low = prices.get("low")
    volume = prices.get("volume")

    if name == "RSI":
        _require(close, "close", name)
        return talib.RSI(close, timeperiod=params.get("period", 14))

    elif name == "MACD":
        _require(close, "close", name)
        _macd, _signal, hist = talib.MACD(
            close,
            fastperiod=params.get("fastperiod", 12),
            slowperiod=params.get("slowperiod", 26),
            signalperiod=params.get("signalperiod", 9),
        )
        return hist

    elif name == "MACD_FULL":
        # 返回完整MACD三条线
        _require(close, "close", name)
        macd_line, signal_line, hist = talib.MACD(
            close,
            fastperiod=params.get("fastperiod", 12),
            slowperiod=params.get("slowperiod", 26),
            signalperiod=params.get("signalperiod", 9),
        )
        return np.column_stack([macd_line, signal_line, hist])

    elif name == "ATR":
        _require(high, "high", name)
        _require(low, "low", name)
        _require(close, "close", name)
        return talib.ATR(
            high, low, close,
            timeperiod=params.get("period", 14),
        )

    elif name == "BBANDS":
        _require(close, "close", name)
        upper, middle, lower = talib.BBANDS(
            close,
            timeperiod=params.get("period", 20),
            nbdevup=params.get("nbdevup", 2.0),
            nbdevdn=params.get("nbdevdn", 2.0),
        )
        return middle  # 默认返回中轨

    elif name == "BBANDS_FULL":
        _require(close, "close", name)
        upper, middle, lower = talib.BBANDS(
            close,
            timeperiod=params.get("period", 20),
            nbdevup=params.get("nbdevup", 2.0),
            nbdevdn=params.get("nbdevdn", 2.0),
        )
        return np.column_stack([upper, middle, lower])

    elif name == "ADX":
        _require(high, "high", name)
        _require(low, "low", name)
        _require(close, "close", name)
        return talib.ADX(
            high, low, close,
            timeperiod=params.get("period", 14),
        )

    elif name == "OBV":
        _require(close, "close", name)
        _require(volume, "volume", name)
        return talib.OBV(close, volume)

    elif name == "CCI":
        _require(high, "high", name)
        _require(low, "low", name)
        _require(close, "close", name)
        return talib.CCI(
            high, low, close,
            timeperiod=params.get("period", 14),
        )

    elif name == "SMA":
        _require(close, "close", name)
        return talib.SMA(close, timeperiod=params.get("period", 20))

    elif name == "EMA":
        _require(close, "close", name)
        return talib.EMA(close, timeperiod=params.get("period", 20))

    elif name == "WILLR":
        _require(high, "high", name)
        _require(low, "low", name)
        _require(close, "close", name)
        return talib.WILLR(
            high, low, close,
            timeperiod=params.get("period", 14),
        )

    elif name == "MFI":
        _require(high, "high", name)
        _require(low, "low", name)
        _require(close, "close", name)
        _require(volume, "volume", name)
        return talib.MFI(
            high, low, close, volume,
            timeperiod=params.get("period", 14),
        )

    elif name == "KDJ":
        # KDJ指标: 基于STOCH(K,D), J = 3K - 2D
        # 默认返回K线; output='D'返回D线, output='J'返回J线
        _require(high, "high", name)
        _require(low, "low", name)
        _require(close, "close", name)
        k, d = talib.STOCH(
            high, low, close,
            fastk_period=params.get("fastk_period", 9),
            slowk_period=params.get("slowk_period", 3),
            slowk_matype=0,
            slowd_period=params.get("slowd_period", 3),
            slowd_matype=0,
        )
        output = params.get("output", "K")
        if output == "D":
            return d
        elif output == "J":
            return 3 * k - 2 * d
        return k  # default: K

    elif name == "STOCH":
        # 原始Stochastic Oscillator
        _require(high, "high", name)
        _require(low, "low", name)
        _require(close, "close", name)
        k, d = talib.STOCH(
            high, low, close,
            fastk_period=params.get("fastk_period", 5),
            slowk_period=params.get("slowk_period", 3),
            slowk_matype=0,
            slowd_period=params.get("slowd_period", 3),
            slowd_matype=0,
        )
        return k  # default: slowK

    else:
        raise ValueError(
            f"未知指标: {name}。请在ta_wrapper.py中添加支持，"
            f"或直接使用talib.{name}()"
        )


def list_supported_indicators() -> list[str]:
    """返回当前wrapper支持的指标列表。"""
    return [
        "RSI", "MACD", "MACD_FULL", "ATR", "BBANDS", "BBANDS_FULL",
        "ADX", "OBV", "CCI", "SMA", "EMA", "WILLR", "MFI",
        "KDJ", "STOCH",
    ]


def _require(
    arr: Optional[np.ndarray],
    field_name: str,
    indicator_name: str,
) -> None:
    """检查必需的价格数据是否存在。"""
    if arr is None:
        raise ValueError(
            f"指标{indicator_name}需要'{field_name}'数据，"
            f"但prices字典中未提供"
        )
