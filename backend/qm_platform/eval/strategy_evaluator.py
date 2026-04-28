"""Framework #4 Eval — PlatformStrategyEvaluator concrete (StrategyEvaluator).

针对策略层评估, 区别于因子层 PlatformEvaluationPipeline. 复用底层 Pipeline 跑
Strategy Gates (G1' / G2' / G3') 后包成 Verdict.

设计意图 (ADR-014):
  - register() 不 inline wire (避免 5min 阻塞)
  - 调用方在升 LIVE 前显式调 evaluator.evaluate_strategy(strategy_id), 通过才 update_status(LIVE)
  - sim_to_real_check 对齐铁律 18 (回测 vs PT 实盘 H0 验证)
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .._types import Verdict
from .gates.base import GateContext
from .interface import StrategyEvaluator
from .pipeline import EvaluationDecision, PlatformEvaluationPipeline
from .strategy_gates import (
    StrategyG1SharpeGate,
    StrategyG2MaxDrawdownGate,
    StrategyG3RegressionGate,
)


class PlatformStrategyEvaluator(StrategyEvaluator):
    """Strategy 评估 concrete — 跑 G1' + G2' + G3' 返 Verdict.

    Args:
      context_loader: Callable[[str], GateContext] — 给 strategy_id 加载 ctx
        (含 extra 内 daily_returns / nav_series / regression_runner).
      rng_seed: G1' bootstrap 种子, 默认 42 保 deterministic test.
    """

    def __init__(
        self,
        context_loader: Callable[[str], GateContext],
        *,
        rng_seed: int = 42,
    ) -> None:
        self._loader = context_loader
        self._pipeline = PlatformEvaluationPipeline(
            gates=[
                StrategyG1SharpeGate(rng_seed=rng_seed),
                StrategyG2MaxDrawdownGate(),
                StrategyG3RegressionGate(),
            ],
            context_loader=context_loader,
        )

    def evaluate_strategy(self, strategy_id: str, years: int = 5) -> Verdict:
        """评估策略, 返 Verdict.

        Args:
          strategy_id: 策略 ID.
          years: 回测年数 (5 / 12), 由 ctx 提供, 此参数仅文档化记录到 details.

        Returns:
          Verdict.passed=True 当且仅当 G1'/G2'/G3' 全过 (ACCEPT).
          REJECT 时 blockers 列具体未过 Gate, details 含 EvaluationReport.
        """
        report = self._pipeline.evaluate_full(strategy_id)
        verdict = report.to_verdict()
        # 注入 years (文档化)
        new_details = dict(verdict.details)
        new_details["evaluation_years"] = years
        return Verdict(
            subject=verdict.subject,
            passed=verdict.passed,
            p_value=verdict.p_value,
            blockers=verdict.blockers,
            details=new_details,
        )

    def sim_to_real_check(self, strategy_id: str) -> Verdict:
        """对比回测 vs PT 实盘 (铁律 18 H0 验证).

        判定: ctx.extra["sim_to_real_gap_bps"] 必需, |gap| < 5 bps → PASS.

        gap 单位: basis points (1 bps = 0.0001 = 0.01%).

        Returns:
          Verdict.passed=True 若 |gap| < 5 bps. blockers 含 'sim_to_real_gap'.
        """
        ctx = self._loader(strategy_id)
        gap_bps = ctx.extra.get("sim_to_real_gap_bps")

        if gap_bps is None:
            return Verdict(
                subject=strategy_id,
                passed=False,
                p_value=None,
                blockers=["sim_to_real_check"],
                details={
                    "decision": EvaluationDecision.WARNING.value,
                    "reasoning": "sim_to_real_gap_bps not provided in ctx.extra (data_unavailable)",
                    "ironclad_rule": 18,
                },
            )

        gap_abs = abs(float(gap_bps))
        passed = gap_abs < 5.0
        return Verdict(
            subject=strategy_id,
            passed=passed,
            p_value=None,
            blockers=[] if passed else ["sim_to_real_gap"],
            details={
                "decision": (
                    EvaluationDecision.ACCEPT.value if passed else EvaluationDecision.REJECT.value
                ),
                "reasoning": (
                    f"|gap|={gap_abs:.2f}bps {'<' if passed else '≥'} 5.0 bps threshold"
                ),
                "gap_bps": float(gap_bps),
                "threshold_bps": 5.0,
                "ironclad_rule": 18,
            },
        )


def build_strategy_context(
    strategy_id: str,
    *,
    candidate_daily_returns: Any = None,
    baseline_daily_returns: Any = None,
    nav_series: Any = None,
    max_dd_threshold: float | None = None,
    regression_runner: Callable[[], dict] | None = None,
    no_baseline: bool = False,
    sim_to_real_gap_bps: float | None = None,
) -> GateContext:
    """构造 Strategy 评估 GateContext helper.

    把 strategy 特化输入 (daily_returns / nav / regression / sim_to_real) 装入 extra (read-only),
    交 G1' / G2' / G3' / sim_to_real_check 取用.
    """
    extra: dict[str, Any] = {}
    if candidate_daily_returns is not None:
        extra["candidate_daily_returns"] = candidate_daily_returns
    if baseline_daily_returns is not None:
        extra["baseline_daily_returns"] = baseline_daily_returns
    if nav_series is not None:
        extra["nav_series"] = nav_series
    if max_dd_threshold is not None:
        extra["max_dd_threshold"] = max_dd_threshold
    if regression_runner is not None:
        extra["regression_runner"] = regression_runner
    if no_baseline:
        extra["no_baseline"] = True
    if sim_to_real_gap_bps is not None:
        extra["sim_to_real_gap_bps"] = sim_to_real_gap_bps

    from types import MappingProxyType

    # PR #125 reviewer P2 note: MappingProxyType 是 shallow freeze — 阻止 key 重赋值
    # 但 value (numpy array / Callable / dict) 仍可被 mutate.
    # Gate 实现层面应不持有 ctx.extra 内 mutable value 的引用做 in-place 修改 (e.g.
    # `ctx.extra["nav_series"] *= 2` 会污染同 ctx 后续 Gate). 当前 3 Strategy Gates 都纯读
    # 无 mutate, 后续新增 Gate 须遵守此约定.
    return GateContext(
        factor_name=strategy_id,  # 复用 factor_name 字段, Strategy 视角下视为 strategy_id
        extra=MappingProxyType(extra),
    )
