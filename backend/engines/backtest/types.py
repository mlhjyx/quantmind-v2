"""回测数据类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from engines.backtest.config import BacktestConfig


@dataclass
class Fill:
    """成交记录。"""
    code: str
    trade_date: date
    direction: str  # 'buy' or 'sell'
    price: float
    shares: int
    amount: float
    commission: float
    tax: float
    slippage: float
    total_cost: float


@dataclass
class CorporateAction:
    """分红/送股/拆股事件（P1+P2）。

    ex_date当日开盘前处理:
    - cash_div_per_share: 每股现金分红(税前，元)
    - stock_div_ratio: 送股比例(如10送5=0.5)
    - tax_rate: 红利税率(持股>1年免税=0, <1月=0.20, 1月-1年=0.10)
    """
    code: str
    ex_date: date
    cash_div_per_share: float = 0.0
    stock_div_ratio: float = 0.0
    tax_rate: float = 0.10  # 默认10%(持股1月-1年)


@dataclass
class PendingOrder:
    """封板未成交的补单记录（回测引擎内部使用）。

    仅买入方向。涨停封板时创建，T+1日尝试补单，最多补1次。
    """
    code: str
    signal_date: date
    exec_date: date          # 封板发生日
    target_weight: float     # 目标权重
    original_score: float    # 原始composite score（排序用）
    direction: str = "buy"
    status: str = "pending"  # pending / filled / cancelled
    cancel_reason: str = ""


@dataclass
class PendingOrderStats:
    """补单统计。"""
    total_pending: int = 0           # 总封板次数
    filled_count: int = 0            # 补单成功次数
    cancelled_count: int = 0         # 放弃次数
    fill_rate: float = 0.0           # 补单成功率 = filled / total
    avg_retry_return_1d: float = 0.0 # 补单股票T+1日平均涨幅
    cancel_reasons: dict = field(default_factory=dict)  # {reason: count}


@dataclass
class BacktestResult:
    """回测结果。"""
    daily_nav: pd.Series         # date → NAV
    daily_returns: pd.Series     # date → daily return
    benchmark_nav: pd.Series     # date → benchmark NAV
    benchmark_returns: pd.Series # date → benchmark return
    trades: list[Fill]
    holdings_history: dict       # date → {code: shares}
    config: BacktestConfig
    turnover_series: pd.Series   # date → turnover ratio
    pending_order_stats: PendingOrderStats | None = None
    pms_events: list[dict] = field(default_factory=list)  # 利润保护触发事件

    def metrics(self, num_trials: int = 69, **kwargs):
        """生成完整绩效报告(Phase 2: P9)。

        Args:
            num_trials: M = FACTOR_TEST_REGISTRY累计测试数, 用于DSR计算。
        """
        from engines.metrics import generate_report
        return generate_report(self, num_trials=num_trials, **kwargs)
