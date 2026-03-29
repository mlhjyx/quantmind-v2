"""因子挖掘引擎包 — Sprint 1.14-1.16 TrB轨道

三引擎Pipeline:
- Engine 1: BruteForceEngine — 50模板×参数网格暴力枚举
- Engine 2: DEAP GP (Sprint 1.16) — Warm Start + 岛屿模型 + 逻辑参数分离
- Engine 3: LLM 3-Agent (Sprint 1.17)

共享工具:
- FactorSandbox — AST安全检查+subprocess隔离
- ASTDeduplicator — 语义去重(AST结构+Spearman)
- FactorDSL — 因子表达式语言(GP搜索空间)
- GPEngine — Warm Start GP引擎(DEAP)
- QuickBacktester — GP适应度快速回测
"""

from .ast_dedup import ASTDeduplicator
from .bruteforce_engine import BruteForceEngine
from .factor_dsl import (
    SEED_FACTORS,
    ExprNode,
    FactorDSL,
    expr_to_string,
    get_seed_trees,
    string_to_expr,
)
from .factor_sandbox import FactorSandbox, ValidationResult
from .gp_engine import GPConfig, GPEngine, GPResult, GPRunStats, run_gp_pipeline
from .pipeline_utils import (
    compute_forward_returns,
    load_existing_factor_data,
    load_market_data,
    run_full_gate,
    send_dingtalk_notification,
)
from .quick_backtester import QuickBacktester, QuickBacktestResult

__all__ = [
    # Sprint 1.14
    "FactorSandbox",
    "ValidationResult",
    "BruteForceEngine",
    "ASTDeduplicator",
    "QuickBacktester",
    "QuickBacktestResult",
    # Sprint 1.16 — FactorDSL
    "ExprNode",
    "FactorDSL",
    "SEED_FACTORS",
    "get_seed_trees",
    "string_to_expr",
    "expr_to_string",
    # Sprint 1.16 — GP Engine
    "GPConfig",
    "GPEngine",
    "GPResult",
    "GPRunStats",
    "run_gp_pipeline",
    # Sprint 1.32 — Pipeline Utils (共享接口)
    "load_market_data",
    "load_existing_factor_data",
    "compute_forward_returns",
    "run_full_gate",
    "send_dingtalk_notification",
]
