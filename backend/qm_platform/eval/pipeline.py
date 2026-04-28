"""Framework #4 Eval — PlatformEvaluationPipeline concrete + EvaluationReport.

Pipeline 顺序跑所有 Gate, 收集 GateResult, 聚合成 Verdict / EvaluationReport.
顶层异常捕获 (Gate 实现内部应不 raise, 但 belt-and-suspenders).

设计稿: docs/mvp/MVP_3_5_eval_gate_framework.md
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from .._types import Verdict
from .gates.base import Gate, GateContext
from .interface import EvaluationPipeline, GateResult


class EvaluationDecision(StrEnum):
    """聚合决策 — Pipeline 顶层 verdict."""

    ACCEPT = "accept"   # 所有 Gate PASS
    REJECT = "reject"   # ≥1 hard fail (业务不通过)
    WARNING = "warning"  # ≥1 data_unavailable, 不能下定论


@dataclass(frozen=True)
class EvaluationReport:
    """完整评估报告 — 含逐 Gate 结果 + 聚合决策 + 时间戳.

    Args:
      candidate_id: factor_name / strategy_id.
      decision: ACCEPT / REJECT / WARNING.
      passed: 同 Verdict.passed (decision == ACCEPT 时 True).
      gate_results: 逐 Gate 的 GateResult 列表 (顺序与执行顺序一致).
      timestamp: UTC 时间戳 (铁律 41 必带 tz).
      reasoning: 人可读理由 (e.g. "G9 fail: AST Jaccard 0.85 > 0.7").
    """

    candidate_id: str
    decision: EvaluationDecision
    passed: bool
    gate_results: list[GateResult]
    timestamp: datetime
    reasoning: str
    # 扩展字段, 便于 audit log / observability 消费
    extra: dict[str, object] = field(default_factory=dict)

    def to_verdict(self) -> Verdict:
        """转 Verdict 对象 (兼容 EvaluationPipeline.evaluate_factor 的返回类型)."""
        blockers = [r.gate_name for r in self.gate_results if not r.passed]
        return Verdict(
            subject=self.candidate_id,
            passed=self.passed,
            p_value=None,  # 多 gate 不存单 p, 留 details 看 G3
            blockers=blockers,
            details={
                "decision": self.decision.value,
                "reasoning": self.reasoning,
                "gate_results": [
                    {
                        "gate": r.gate_name,
                        "passed": r.passed,
                        "threshold": r.threshold,
                        "observed": r.observed,
                        "details": r.details,
                    }
                    for r in self.gate_results
                ],
                "timestamp": self.timestamp.isoformat(),
            },
        )


def _classify_decision(results: list[GateResult]) -> tuple[EvaluationDecision, str]:
    """聚合决策 + 人可读 reasoning.

    规则:
      - 所有 passed=True → ACCEPT
      - ≥1 fail with reason=data_unavailable → WARNING (不能下定论)
      - ≥1 hard fail (passed=False, reason 非 data_unavailable) → REJECT
    """
    if all(r.passed for r in results):
        return EvaluationDecision.ACCEPT, "all gates passed"

    hard_fails = [
        r for r in results
        if not r.passed and r.details.get("reason") != "data_unavailable"
    ]
    if hard_fails:
        first = hard_fails[0]
        reasoning = f"{first.gate_name} fail: " + str(first.details.get("reason", "unspecified"))
        if len(hard_fails) > 1:
            reasoning += f" (+{len(hard_fails) - 1} more)"
        return EvaluationDecision.REJECT, reasoning

    # 剩余情况: 全是 data_unavailable → WARNING
    missing_gates = [r.gate_name for r in results if not r.passed]
    return (
        EvaluationDecision.WARNING,
        f"data unavailable for {len(missing_gates)} gate(s): {missing_gates[:3]}",
    )


class PlatformEvaluationPipeline(EvaluationPipeline):
    """Concrete Pipeline — 持有 Gate 列表 + 上下文 loader, 顺序跑所有 Gate.

    依赖注入:
      gates: list[Gate] — 注入 Gate 实例集合. 顺序即执行顺序.
      context_loader: Callable[[str], GateContext] — 给定 factor_name 加载 ctx.
        生产: 从 DB / cache 加载 ic_history / baseline / corr 等.
        测试: 直接构造 GateContext 返回, 不需 IO.

    Usage:
      ```python
      from qm_platform.eval.pipeline import PlatformEvaluationPipeline
      from qm_platform.eval.gates import G1IcSignificanceGate, G9NoveltyAstGate

      def loader(name: str) -> GateContext:
          return GateContext(factor_name=name, ic_series=...)

      pipeline = PlatformEvaluationPipeline(
          gates=[G1IcSignificanceGate(), G9NoveltyAstGate()],
          context_loader=loader,
      )
      verdict = pipeline.evaluate_factor("turnover_mean_20")
      assert verdict.passed
      ```
    """

    def __init__(
        self,
        gates: list[Gate],
        context_loader: Callable[[str], GateContext],
    ) -> None:
        if not gates:
            raise ValueError("gates 列表不能为空")
        self._gates = list(gates)
        self._loader = context_loader

    # ---------- EvaluationPipeline ABC 实现 ----------

    def evaluate_factor(self, factor_name: str) -> Verdict:
        """评估单因子, 返 Verdict (含 details["gate_results"] 完整 trace)."""
        report = self.evaluate_full(factor_name)
        return report.to_verdict()

    def gate_detail(self, factor_name: str, gate_name: str) -> GateResult:
        """查单个 Gate 详情 (debug / 可视化用)."""
        ctx = self._loader(factor_name)
        for gate in self._gates:
            if gate.name == gate_name:
                return self._safe_evaluate(gate, ctx)
        raise ValueError(
            f"unknown gate: {gate_name!r}, "
            f"registered: {[g.name for g in self._gates]}"
        )

    # ---------- 扩展 API (返 EvaluationReport, 比 Verdict 更富信息) ----------

    def evaluate_full(self, factor_name: str) -> EvaluationReport:
        """完整评估 — 跑所有 Gate, 返 EvaluationReport.

        Pipeline 顶层 try/except 兜底每个 Gate (gate.evaluate 内部应不 raise,
        但 belt-and-suspenders, 防止单 Gate 崩溃影响其他).
        """
        ctx = self._loader(factor_name)
        results = [self._safe_evaluate(gate, ctx) for gate in self._gates]
        decision, reasoning = _classify_decision(results)
        return EvaluationReport(
            candidate_id=factor_name,
            decision=decision,
            passed=(decision == EvaluationDecision.ACCEPT),
            gate_results=results,
            timestamp=datetime.now(UTC),
            reasoning=reasoning,
        )

    @staticmethod
    def _safe_evaluate(gate: Gate, ctx: GateContext) -> GateResult:
        """Gate.evaluate 兜底 — 异常包成 GateResult (Pipeline 不 raise)."""
        try:
            return gate.evaluate(ctx)
        except Exception as e:  # noqa: BLE001 — Pipeline 顶层兜底, 不再 re-raise
            return GateResult(
                gate_name=gate.name,
                passed=False,
                threshold=gate.threshold,
                observed=None,
                details={
                    "reason": "gate_internal_error",
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
