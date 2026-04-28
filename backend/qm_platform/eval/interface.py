"""Framework #4 Evaluation Gate — 因子 / 策略评估一键化.

目标: 合并 `engines/factor_gate.py` (G1-G8 阈值 + GateStatus) + 散落 Gate 逻辑
为 Platform `EvaluationPipeline` (concrete: `pipeline.PlatformEvaluationPipeline`).

关联铁律:
  - 5: paired bootstrap p<0.05 (G3, MVP 3.5 batch 1 新建 utils.paired_bootstrap_pvalue)
  - 12: G9 Gate AST 新颖性 (复用 MVP 1.3c registry._default_ast_jaccard + novelty_check)
  - 13: G10 Gate hypothesis 描述 (复用 MVP 1.3c register() G10_HYPOTHESIS_MIN_LEN + G10_FORBIDDEN_PREFIXES)
  - 19: IC 定义统一 (G1 调 engines/ic_calculator.py)
  - 20: 噪声鲁棒性 G_robust (留 MVP 3.5 后续批次)

实施时机:
  - MVP 3.5 batch 1: EvaluationPipeline + 7 Gates concrete (G1/G2/G3/G4/G8/G9/G10)
  - MVP 3.5 batch 2: factor_lifecycle 集成 (双路径并存 4 周观察)
  - MVP 3.5 batch 3: Strategy Eval Gate + ADR-013
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .._types import Verdict


@dataclass(frozen=True)
class GateResult:
    """单个 Gate 的评估结果.

    Args:
      gate_name: "G1_ic_significance" / "G9_novelty" / "G10_economic" / "G_robust" 等
      passed: 是否通过
      threshold: 阈值 (e.g. p<0.05 的 0.05)
      observed: 实测值
      details: 辅助信息
    """

    gate_name: str
    passed: bool
    threshold: float | None
    observed: float | None
    details: dict[str, Any]


class EvaluationPipeline(ABC):
    """因子评估一键管道 — 跑所有 Gate, 返回统一 Verdict.

    Gate 清单:
      G1 IC 显著性 (t > 2.5 硬下限, Harvey Liu Zhu 2016)
      G2 IC 衰减速率
      G3 单调性 (decile monotone)
      G4 成本可行性 (annual_cost < alpha × 0.5)
      G5 冗余性 (corr < 0.7)
      G9 新颖性 (AST 相似度 < 0.7, 铁律 12)
      G10 经济机制 (人工 review, 铁律 13)
      G_robust 噪声鲁棒性 (20% noise retention ≥ 0.5, 铁律 20)
      BH-FDR 累积校正 (M = FACTOR_TEST_REGISTRY 累积数)
    """

    @abstractmethod
    def evaluate_factor(self, factor_name: str) -> Verdict:
        """评估单因子, 返回 Verdict.

        Verdict.passed 为 True 当且仅当所有 Gate 全过 (含 BH-FDR).
        Verdict.blockers 列出未过 Gate.
        Verdict.details 含每个 Gate 的 GateResult.

        Raises:
          FactorNotFound: factor_name 未注册
          InsufficientData: IC 样本 < 60 (铁律 7)
        """

    @abstractmethod
    def gate_detail(self, factor_name: str, gate_name: str) -> GateResult:
        """查单个 Gate 详情 (debug / 可视化用)."""


class StrategyEvaluator(ABC):
    """策略评估 — 区别于因子评估, 关注组合层指标.

    检查:
      - Sharpe / Sortino / Calmar
      - Walk-Forward OOS 稳定性 (铁律 8)
      - sim-to-real gap (回测 vs PT 实盘, 铁律 18)
      - regime 敏感性
    """

    @abstractmethod
    def evaluate_strategy(self, strategy_id: str, years: int = 5) -> Verdict:
        """评估策略, 返回 Verdict.

        Args:
          strategy_id: 策略 ID
          years: 回测年数 (5 / 12)

        Returns:
          Verdict, details 含 WF chain-link Sharpe / overfit_ratio 等
        """

    @abstractmethod
    def sim_to_real_check(self, strategy_id: str) -> Verdict:
        """对比回测 vs PT 实盘, 铁律 18 的 H0 验证.

        Returns:
          Verdict.passed 若误差 < 5bps, blockers 列具体偏差来源.
        """
