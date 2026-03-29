"""QuantMind V2 ORM模型包。

统一导出所有模型类，使用方式:
    from app.models import Base, Symbol, KlineDaily, FactorRegistry, ...

注意: 项目中存在两个Base类:
  - app.models.base.Base: 新建模型使用（本包导出的Base）
  - app.models.pipeline_run.Base: 遗留模型使用（pipeline_run/approval_queue/mining_knowledge）
两者在运行时共存不冲突（extend_existing=True）。
"""

# 基类与Mixin
from .approval_queue import GPApprovalQueue

# 域1: 基础数据
from .astock import (
    DailyBasic,
    IndexDaily,
    KlineDaily,
    Symbol,
    TradingCalendar,
)

# 域9: 回测引擎
from .backtest import (
    BacktestRun,
    BacktestTrade,
)
from .base import Base, TimestampMixin

# 域3: 因子
from .factor import (
    FactorICHistory,
    FactorRegistry,
    FactorValue,
)
from .mining_knowledge import MiningKnowledge

# 域12: GP因子挖掘Pipeline（遗留模型，使用pipeline_run.Base）
from .pipeline_run import PipelineRun

# 域4: Universe与信号
from .signal import (
    Signal,
    UniverseDaily,
)

# 域5: 交易执行
from .trade import (
    PerformanceSeries,
    PositionSnapshot,
    TradeLog,
)

__all__ = [
    # 基类
    "Base",
    "TimestampMixin",
    # 域1
    "Symbol",
    "KlineDaily",
    "DailyBasic",
    "TradingCalendar",
    "IndexDaily",
    # 域3
    "FactorRegistry",
    "FactorValue",
    "FactorICHistory",
    # 域4
    "UniverseDaily",
    "Signal",
    # 域5
    "TradeLog",
    "PositionSnapshot",
    "PerformanceSeries",
    # 域9
    "BacktestRun",
    "BacktestTrade",
    # 域12
    "PipelineRun",
    "GPApprovalQueue",
    "MiningKnowledge",
]
