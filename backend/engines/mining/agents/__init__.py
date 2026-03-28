"""AI闭环Agent模块 — LLM驱动的因子挖掘智能体

包含:
  - IdeaAgent: 因子假设生成（DeepSeek-R1驱动）
  - (Sprint 1.18+) FactorAgent: 代码生成
  - (Sprint 1.18+) EvalAgent: 统计评估
  - (Sprint 1.18+) DiagnosisAgent: 根因分析

设计来源: docs/research/R7_ai_model_selection.md §4.1
"""

from .idea_agent import FactorHypothesis, IdeaAgent

__all__ = ["IdeaAgent", "FactorHypothesis"]
