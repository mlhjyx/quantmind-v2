"""[REFACTORED] 已拆分到 backend/engines/backtest/ 目录。

向后兼容shim — 所有公开接口通过 engines.backtest 包re-export。
现有 `from engines.backtest_engine import BacktestConfig` 等import仍有效。

Step 4-A: 引擎拆分
- config.py: BacktestConfig, PMSConfig
- types.py: Fill, CorporateAction, PendingOrder, BacktestResult等
- validators.py: ValidatorChain + 各Validator
- broker.py: SimBroker
- executor.py: BaseExecutor, SimpleExecutor
- engine.py: SimpleBacktester(主循环)
- runner.py: run_hybrid_backtest, run_composite_backtest
"""

from engines.backtest import *  # noqa: F401,F403
