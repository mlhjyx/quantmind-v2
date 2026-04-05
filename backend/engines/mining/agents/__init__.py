"""AI闭环Agent模块 — LLM驱动的因子挖掘智能体

包含:
  - IdeaAgent: 因子假设生成（DeepSeek-R1驱动）
  - FactorAgent: 代码生成（DeepSeek-V3/Qwen3驱动）
  - EvalAgent: 统计评估（纯计算，不依赖LLM）
  - (Sprint 1.19+) DiagnosisAgent: 根因分析

设计来源: docs/research/R7_ai_model_selection.md §4.1
"""

from .eval_agent import EvalAgent, EvalResult
from .factor_agent import FactorAgent, GeneratedFactorCode
from .idea_agent import FactorHypothesis, IdeaAgent

__all__ = [
    "IdeaAgent",
    "FactorHypothesis",
    "FactorAgent",
    "GeneratedFactorCode",
    "EvalAgent",
    "EvalResult",
]
