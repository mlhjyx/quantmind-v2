"""回测配置数据类。"""

from __future__ import annotations

from dataclasses import dataclass, field

from engines.slippage_model import SlippageConfig


@dataclass
class PMSConfig:
    """利润保护配置(Position Management System)。

    阶梯式利润保护: 盈利越多,允许的回撤越大。
    tiers: [(pnl_threshold, trailing_stop), ...] 按pnl从高到低排列。
    例: [(0.30, 0.15), (0.20, 0.12), (0.10, 0.10)]
      = 盈利>30%且从高点回撤>15%卖出
      = 盈利>20%且从高点回撤>12%卖出
      = 盈利>10%且从高点回撤>10%卖出

    exec_mode:
      'next_open': 收盘后发现→T+1日开盘卖(保守/真实)
      'same_close': 盘中发现→当日收盘卖(乐观)
    """
    enabled: bool = False
    tiers: list[tuple[float, float]] = field(default_factory=lambda: [
        (0.30, 0.15), (0.20, 0.12), (0.10, 0.10),
    ])
    exec_mode: str = "next_open"  # 'next_open' | 'same_close'


@dataclass
class BacktestConfig:
    """回测配置。"""
    initial_capital: float = 1_000_000.0
    top_n: int = 20
    rebalance_freq: str = "monthly"  # 与PT配置对齐(之前默认biweekly导致回测与PT不一致)
    slippage_bps: float = 10.0   # 基础滑点 (bps), fixed模式使用
    slippage_mode: str = "volume_impact"  # 'volume_impact' | 'fixed'
    slippage_config: SlippageConfig = field(default_factory=SlippageConfig)
    commission_rate: float = 0.0000854  # 佣金万0.854（国金证券实际费率）
    stamp_tax_rate: float = 0.0005   # 印花税千0.5(仅卖出), historical_stamp_tax=True时此值被覆盖
    historical_stamp_tax: bool = True  # P3: 启用历史税率(2023-08-28前0.1%, 后0.05%)
    transfer_fee_rate: float = 0.00001  # 过户费万0.1
    lot_size: int = 100  # A股最小交易单位
    turnover_cap: float = 0.50
    benchmark_code: str = "000300.SH"
    volume_cap_pct: float = 0.10  # 单笔成交额上限(占当日成交额比例) DEV_BACKTEST_ENGINE §4.9
    pms: PMSConfig = field(default_factory=PMSConfig)  # 利润保护
