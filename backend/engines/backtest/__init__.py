"""回测引擎包 — 从backtest_engine.py拆分(Step 4-A)。

所有公开接口re-export，保持向后兼容。
"""

from engines.backtest.broker import SimBroker  # noqa: F401
from engines.backtest.config import BacktestConfig, PMSConfig  # noqa: F401
from engines.backtest.engine import SimpleBacktester  # noqa: F401
from engines.backtest.executor import BaseExecutor, SimpleExecutor  # noqa: F401
from engines.backtest.runner import run_composite_backtest, run_hybrid_backtest  # noqa: F401
from engines.backtest.types import (  # noqa: F401
    BacktestResult,
    CorporateAction,
    Fill,
    PendingOrder,
    PendingOrderStats,
)
from engines.backtest.validators import ValidatorChain  # noqa: F401
