"""因子挖掘引擎包 — Sprint 1.14 TrB轨道

三引擎Pipeline:
- Engine 1: BruteForceEngine — 50模板×参数网格暴力枚举
- Engine 2: DEAP GP (Sprint 1.16)
- Engine 3: LLM 3-Agent (Sprint 1.17)

共享工具:
- FactorSandbox — AST安全检查+subprocess隔离
- ASTDeduplicator — 语义去重(AST结构+Spearman)
"""

from .ast_dedup import ASTDeduplicator
from .bruteforce_engine import BruteForceEngine
from .factor_sandbox import FactorSandbox, ValidationResult

__all__ = [
    "FactorSandbox",
    "ValidationResult",
    "BruteForceEngine",
    "ASTDeduplicator",
]
