"""双因素滑点模型 — Volume-Impact 滑点估计（Bouchaud 2018 square-root law）。

替代SimBroker中的固定bps滑点, 采用更真实的
基础滑点 + 市场冲击成本 模型。

冲击成本公式（新路径, config模式）:
  impact = Y * sigma_daily * sqrt(Q/V) * 10000
  其中 Y 按市值分档, sigma_daily 为个股日波动率。

旧路径（向后兼容, 无config）:
  impact = impact_coeff * sqrt(trade_amount / daily_amount) * 10000

核心逻辑:
  - 大单相对日成交额的比例越高, 冲击越大
  - 小盘股(市值小)天然流动性差, 冲击更大
  - 高波动股票冲击更大（sigma项, Bouchaud 2018）
  - 买入/卖出方向对冲击有不同影响(卖出通常更贵)

遵循CLAUDE.md: 类型注解 + Google style docstring(中文) + Decimal用于金额
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlippageResult:
    """滑点计算结果。

    Attributes:
        base_bps: 基础滑点(bps)。
        impact_bps: 冲击成本(bps)。
        total_bps: 总滑点(bps) = 基础 + 冲击。
        slippage_amount: 滑点金额(元)。
        execution_price: 估计成交价格(元), 含滑点。
    """

    base_bps: float
    impact_bps: float
    total_bps: float
    slippage_amount: Decimal
    execution_price: Decimal


@dataclass(frozen=True)
class SlippageConfig:
    """市值分层滑点配置（Bouchaud 2018 square-root law）。

    公式: impact_bps = Y * sigma_daily * sqrt(Q/V) * 10000
    其中 Y 按市值分档, sigma_daily 为个股日波动率。

    市值越大流动性越好，Y越小。
    参数为L2级可配置（DEV_PARAM_CONFIG.md §3.7）。

    Attributes:
        Y_large: 大盘(500亿+)冲击乘数。
        Y_mid: 中盘(100-500亿)冲击乘数。
        Y_small: 小盘(< 100亿)冲击乘数。
        sell_penalty: 卖出方向冲击惩罚倍数。
        base_bps: 基础滑点(bps, bid-ask spread)。
    """

    Y_large: float = 0.8
    Y_mid: float = 1.0
    Y_small: float = 1.5
    sell_penalty: float = 1.2
    base_bps: float = 5.0

    def get_Y(self, market_cap: float) -> float:
        """根据总市值(元)返回对应冲击乘数Y。"""
        if market_cap >= 50_000_000_000:
            return self.Y_large
        elif market_cap >= 10_000_000_000:
            return self.Y_mid
        else:
            return self.Y_small


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
        trade_amount: 交易金额(元)。
        daily_volume: 日成交量(股)。
            用于流动性判断, 成交量为0时返回极大滑点。
        daily_amount: 日成交额(元)。
            冲击成本的分母, 代表市场可吸收的交易规模。
        market_cap: 总市值(元)。
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
            daily_volume, daily_amount,
        )
        return 500.0  # 5% — 基本等于不可交易

    if trade_amount <= 0:
        return 0.0

    # 根据是否传入config走不同路径
    if config is not None:
        # ── 新路径: Bouchaud 2018 square-root law ──
        # impact = Y * sigma_daily * sqrt(Q/V) * 10000
        base = config.base_bps
        Y = config.get_Y(market_cap)

        # sigma_daily防御: 负值或零时用默认值
        if sigma_daily <= 0:
            sigma_daily = 0.02

        participation_rate = trade_amount / daily_amount
        impact = Y * sigma_daily * math.sqrt(participation_rate) * 10000  # 转为bps

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
        trade_amount, daily_amount, participation_rate * 100,
        base, impact, total,
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
) -> SlippageResult:
    """估算含滑点的成交价格。

    封装volume_impact_slippage, 直接返回估计成交价格和详细分解。

    Args:
        signal_price: 信号价格(元), 通常是前收盘价或VWAP。
        trade_amount: 交易金额(元)。
        daily_volume: 日成交量(股)。
        daily_amount: 日成交额(元)。
        market_cap: 总市值(元)。
        direction: "buy" 或 "sell"。
        base_bps: 基础滑点(bps)。
        impact_coeff: 冲击系数。

    Returns:
        SlippageResult, 包含分项滑点和估计成交价。
    """
    total_bps = volume_impact_slippage(
        trade_amount=trade_amount,
        daily_volume=daily_volume,
        daily_amount=daily_amount,
        market_cap=market_cap,
        direction=direction,
        base_bps=base_bps,
        impact_coeff=impact_coeff,
    )

    # 分解: 重新计算base和impact部分(用于报告)
    base_part = base_bps
    impact_part = total_bps - base_part

    # 计算滑点金额和成交价
    slippage_pct = Decimal(str(total_bps)) / Decimal("10000")
    signal_price_d = Decimal(str(signal_price))

    if direction == "buy":
        # 买入: 价格上移
        execution_price = signal_price_d * (1 + slippage_pct)
    else:
        # 卖出: 价格下移
        execution_price = signal_price_d * (1 - slippage_pct)

    slippage_amount = abs(execution_price - signal_price_d) * Decimal(str(trade_amount)) / signal_price_d

    return SlippageResult(
        base_bps=round(base_part, 2),
        impact_bps=round(impact_part, 2),
        total_bps=round(total_bps, 2),
        slippage_amount=slippage_amount.quantize(Decimal("0.01")),
        execution_price=execution_price.quantize(Decimal("0.0001")),
    )
