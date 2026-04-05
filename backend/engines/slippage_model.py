"""三因素滑点模型 — base_bps + impact_bps + overnight_gap_bps。

R4研究结论: PT实测64.5bps = 基础价差(10-15bps) + 市场冲击(25-35bps) + 隔夜跳空(10-15bps)。
三组件合计目标与PT实测偏差 < 15%（54.8-74.2bps范围内）。

三因素结构:
  total = base_bps + impact_bps + overnight_gap_bps

  1. base_bps: 按市值分档的bid-ask spread（tiered_base_bps）
     大盘(>500亿): 3bps / 中盘(100-500亿): 5bps / 小盘(<100亿): 8bps

  2. impact_bps: Bouchaud 2018 square-root law（新路径, config模式）
     impact = Y * sigma_daily * sqrt(Q/V) * 10000

  3. overnight_gap_bps: 隔夜跳空成本（T日信号→T+1开盘执行）
     gap_cost = abs(open/prev_close - 1) * gap_penalty_factor * 10000
     gap_penalty_factor默认0.5（只承受部分跳空, 非全量承受）

旧路径（向后兼容, 无config）:
  impact = impact_coeff * sqrt(trade_amount / daily_amount) * 10000

遵循CLAUDE.md: 类型注解 + Google style docstring(中文) + Decimal用于金额
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SlippageResult:
    """滑点计算结果（三因素分解）。

    Attributes:
        base_bps: 基础滑点(bps)，代表bid-ask spread，按市值分档。
        impact_bps: 冲击成本(bps)，Bouchaud 2018 square-root law。
        overnight_gap_bps: 隔夜跳空成本(bps)，T日信号→T+1开盘执行。
        total_bps: 总滑点(bps) = base + impact + overnight_gap。
        slippage_amount: 滑点金额(元)。
        execution_price: 估计成交价格(元), 含滑点。
    """

    base_bps: float
    impact_bps: float
    overnight_gap_bps: float
    total_bps: float
    slippage_amount: Decimal
    execution_price: Decimal


@dataclass(frozen=True)
class SlippageConfig:
    """市值分层滑点配置（三因素模型）。

    R4研究结论: 三因素 = tiered_base + Bouchaud冲击 + overnight_gap。
    tiered_base按市值分档替代固定base_bps，更准确反映A股流动性差异。

    公式: impact_bps = Y * sigma_daily * sqrt(Q/V) * 10000
    其中 Y 按市值分档, sigma_daily 为个股日波动率。

    参数为L2级可配置（DEV_PARAM_CONFIG.md §3.7）。

    Attributes:
        Y_large: 大盘(500亿+)冲击乘数。
        Y_mid: 中盘(100-500亿)冲击乘数。
        Y_small: 小盘(< 100亿)冲击乘数。
        sell_penalty: 卖出方向冲击惩罚倍数。
        base_bps: 旧版固定基础滑点(bps)，tiered模式下被覆盖。
        base_bps_large: 大盘(500亿+)基础滑点(bps)，bid-ask spread分档。
        base_bps_mid: 中盘(100-500亿)基础滑点(bps)。
        base_bps_small: 小盘(<100亿)基础滑点(bps)。
        gap_penalty_factor: 隔夜跳空惩罚系数(0-1)，默认0.5。
            只承受部分跳空——策略会在高跳空股上自然减配。
    """

    Y_large: float = 0.8
    Y_mid: float = 1.0
    Y_small: float = 1.5
    sell_penalty: float = 1.2
    base_bps: float = 5.0
    # tiered base bps（R4建议，按市值分档）
    base_bps_large: float = 3.0  # 大盘: 流动性好，价差窄
    base_bps_mid: float = 5.0  # 中盘: 中等价差
    base_bps_small: float = 8.0  # 小盘: 流动性差，价差宽
    gap_penalty_factor: float = 0.5  # 隔夜跳空：只承受50%

    def get_y(self, market_cap: float) -> float:
        """根据总市值(元)返回对应冲击乘数Y。"""
        if market_cap >= 50_000_000_000:
            return self.Y_large
        elif market_cap >= 10_000_000_000:
            return self.Y_mid
        else:
            return self.Y_small

    def get_base_bps(self, market_cap: float) -> float:
        """根据总市值(元)返回分档基础滑点(bps)。

        Args:
            market_cap: 总市值(元)。

        Returns:
            分档基础滑点(bps)。
        """
        if market_cap >= 50_000_000_000:  # 500亿+
            return self.base_bps_large
        elif market_cap >= 10_000_000_000:  # 100亿+
            return self.base_bps_mid
        else:
            return self.base_bps_small


def overnight_gap_cost(
    open_price: float,
    prev_close: float,
    gap_penalty_factor: float = 0.5,
) -> float:
    """计算隔夜跳空成本(bps)。

    R4核心发现: T日信号→T+1开盘执行存在~10-15bps的隔夜跳空成本。
    公式: gap_cost = abs(open/prev_close - 1) * gap_penalty_factor * 10000

    gap_penalty_factor=0.5的含义: 策略只承受一半的跳空成本。
    另一半被视为新信息（策略在高跳空股上会自然减配）。

    Args:
        open_price: T+1日开盘价(元)。
        prev_close: T日收盘价(元，即信号价格参考点）。
        gap_penalty_factor: 跳空惩罚系数(0-1)，默认0.5。
            0表示不计入跳空成本, 1表示全额承受跳空。

    Returns:
        隔夜跳空成本(bps)，非负值。

    Raises:
        ValueError: prev_close <= 0 时抛出。

    Examples:
        >>> # 小盘股隔夜跳空1.5%，承受50%
        >>> gap = overnight_gap_cost(open_price=10.15, prev_close=10.0)
        >>> abs(gap - 75.0) < 0.01  # 0.015 * 0.5 * 10000 = 75bps
        True
    """
    if prev_close <= 0:
        raise ValueError(f"prev_close必须为正值, 收到: {prev_close}")

    if open_price <= 0 or gap_penalty_factor <= 0:
        return 0.0

    gap_ratio = abs(open_price / prev_close - 1.0)
    gap_bps = gap_ratio * gap_penalty_factor * 10000

    logger.debug(
        "隔夜跳空: open=%.4f, prev_close=%.4f, gap_ratio=%.4f%%, gap_cost=%.2fbps",
        open_price,
        prev_close,
        gap_ratio * 100,
        gap_bps,
    )

    return gap_bps


def volume_impact_slippage(
    trade_amount: float,
    daily_volume: float,
    daily_amount: float,
    market_cap: float,
    direction: str,
    base_bps: float = 5.0,
    impact_coeff: float = 0.1,
    config: SlippageConfig | None = None,
    sigma_daily: float = 0.02,
) -> float:
    """双因素滑点 = 基础滑点 + 冲击成本。

    新路径(config模式, Bouchaud 2018):
      impact = Y * sigma_daily * sqrt(Q/V) * 10000
    旧路径(向后兼容):
      impact = impact_coeff * sqrt(trade_amount / daily_amount) * 10000

    算法:
      1. 基础滑点: 固定bps, 代表买卖价差(bid-ask spread)
      2. 冲击成本: 与交易金额占日成交额比例的平方根成正比
         - sqrt关系来自Kyle(1985)/Bouchaud(2018)
         - 参与率(trade_amount/daily_amount)越高, 冲击越大
         - sigma_daily引入波动率维度: 高波动股票冲击更大
      3. 卖出方向额外惩罚: 卖出冲击 = 买入冲击 * sell_penalty
         - 实证研究表明卖出(尤其恐慌性卖出)冲击更大

    Args:
        trade_amount: 交易金额(元)。调用方负责转换。
        daily_volume: 日成交量(股)。
            用于流动性判断, 成交量为0时返回极大滑点。
        daily_amount: 日成交额(元)。调用方已从千元(klines_daily)转换。
            冲击成本的分母, 代表市场可吸收的交易规模。
        market_cap: 总市值(元)。调用方已从万元(daily_basic)转换。
            用于市值分层(config模式)或小盘股惩罚(旧模式)。
        direction: 交易方向, "buy" 或 "sell"。
        base_bps: 基础滑点(bps), 默认5bps。旧路径使用。
        impact_coeff: 冲击系数, 默认0.1。旧路径使用。
        config: 市值分层配置。传入则走新路径(Bouchaud 2018)。
        sigma_daily: 个股日波动率, 默认0.02(约30%年化)。
            新路径(config模式)使用, 旧路径忽略。

    Returns:
        总滑点(bps)。正数表示成本。
        例: 返回15.0 表示 15bps = 0.15% 的滑点。

    Raises:
        ValueError: direction不是"buy"或"sell"。

    Examples:
        >>> # Bouchaud模式: 大盘股, 低波动, 小额交易
        >>> slippage = volume_impact_slippage(
        ...     trade_amount=100_000,
        ...     daily_volume=50_000_000,
        ...     daily_amount=500_000_000,
        ...     market_cap=100_000_000_000,
        ...     direction="buy",
        ...     config=SlippageConfig(),
        ...     sigma_daily=0.02,
        ... )
        >>> 5.0 < slippage < 30.0
        True
    """
    if direction not in ("buy", "sell"):
        raise ValueError(f"direction必须是'buy'或'sell', 收到: {direction!r}")

    # 边界处理: 无成交量或无成交额 → 极大滑点(流动性极差)
    if daily_volume <= 0 or daily_amount <= 0:
        logger.warning(
            "日成交量/额为0, 返回极大滑点(500bps): vol=%.0f, amount=%.0f",
            daily_volume,
            daily_amount,
        )
        return 500.0  # 5% — 基本等于不可交易

    if trade_amount <= 0:
        return 0.0

    # 根据是否传入config走不同路径
    if config is not None:
        # ── 新路径: Bouchaud 2018 square-root law + tiered base bps ──
        # impact = Y * sigma_daily * sqrt(Q/V) * 10000
        base = config.get_base_bps(market_cap)  # tiered: 大3/中5/小8 bps
        y_coeff = config.get_y(market_cap)

        # sigma_daily防御: 负值或零时用默认值
        if sigma_daily <= 0:
            sigma_daily = 0.02

        participation_rate = trade_amount / daily_amount
        impact = y_coeff * sigma_daily * math.sqrt(participation_rate) * 10000  # 转为bps

        if direction == "sell":
            impact *= config.sell_penalty
    else:
        # ── 旧路径: 向后兼容 ──
        base = base_bps

        participation_rate = trade_amount / daily_amount
        impact = impact_coeff * math.sqrt(participation_rate) * 10000  # 转为bps

        # 小盘股惩罚: 市值<50亿额外加20%冲击
        if market_cap > 0 and market_cap < 5_000_000_000:
            small_cap_penalty = 1.2
            impact *= small_cap_penalty
            logger.debug("小盘股惩罚(市值%.0f亿): 冲击×1.2", market_cap / 1e8)

        # 卖出方向惩罚: 卖出冲击 × 1.2
        if direction == "sell":
            impact *= 1.2

    total = base + impact

    logger.debug(
        "滑点计算: trade=%.0f, daily_amt=%.0f, 参与率=%.4f%%, "
        "base=%.1fbps, impact=%.1fbps, total=%.1fbps",
        trade_amount,
        daily_amount,
        participation_rate * 100,
        base,
        impact,
        total,
    )

    return total


def estimate_execution_price(
    signal_price: float,
    trade_amount: float,
    daily_volume: float,
    daily_amount: float,
    market_cap: float,
    direction: str,
    base_bps: float = 5.0,
    impact_coeff: float = 0.1,
    config: SlippageConfig | None = None,
    sigma_daily: float = 0.02,
    open_price: float | None = None,
    prev_close: float | None = None,
) -> SlippageResult:
    """估算含滑点的成交价格（三因素分解）。

    R4研究: total = base_bps + impact_bps + overnight_gap_bps。
    三组件合计目标与PT实测64.5bps偏差 < 15%。

    Args:
        signal_price: 信号价格(元), 通常是前收盘价或VWAP。
        trade_amount: 交易金额(元)。
        daily_volume: 日成交量(股)。
        daily_amount: 日成交额(元)。
        market_cap: 总市值(元)。
        direction: "buy" 或 "sell"。
        base_bps: 旧路径固定基础滑点(bps)，config模式下被tiered值覆盖。
        impact_coeff: 旧路径冲击系数。
        config: 市值分层配置，传入时走新路径（tiered base + Bouchaud冲击）。
        sigma_daily: 个股日波动率，新路径使用，默认0.02。
        open_price: T+1日开盘价(元)，用于计算隔夜跳空成本。
            不传入则overnight_gap_bps=0。
        prev_close: T日收盘价(元，信号参考价)，与open_price配合使用。

    Returns:
        SlippageResult, 包含三因素分项滑点和估计成交价。
    """
    total_impact_bps = volume_impact_slippage(
        trade_amount=trade_amount,
        daily_volume=daily_volume,
        daily_amount=daily_amount,
        market_cap=market_cap,
        direction=direction,
        base_bps=base_bps,
        impact_coeff=impact_coeff,
        config=config,
        sigma_daily=sigma_daily,
    )

    # 分解base和impact部分
    base_part = config.get_base_bps(market_cap) if config is not None else base_bps
    impact_part = total_impact_bps - base_part

    # 计算隔夜跳空成本
    gap_bps = 0.0
    if open_price is not None and prev_close is not None and prev_close > 0:
        gap_factor = config.gap_penalty_factor if config is not None else 0.5
        gap_bps = overnight_gap_cost(
            open_price=open_price,
            prev_close=prev_close,
            gap_penalty_factor=gap_factor,
        )

    total_bps = total_impact_bps + gap_bps

    # 计算滑点金额和成交价
    slippage_pct = Decimal(str(total_bps)) / Decimal("10000")
    signal_price_d = Decimal(str(signal_price))

    if direction == "buy":
        execution_price = signal_price_d * (1 + slippage_pct)
    else:
        execution_price = signal_price_d * (1 - slippage_pct)

    slippage_amount = (
        abs(execution_price - signal_price_d) * Decimal(str(trade_amount)) / signal_price_d
    )

    return SlippageResult(
        base_bps=round(base_part, 2),
        impact_bps=round(impact_part, 2),
        overnight_gap_bps=round(gap_bps, 2),
        total_bps=round(total_bps, 2),
        slippage_amount=slippage_amount.quantize(Decimal("0.01")),
        execution_price=execution_price.quantize(Decimal("0.0001")),
    )
