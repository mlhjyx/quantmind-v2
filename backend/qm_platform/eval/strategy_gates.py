"""Framework #4 Eval — Strategy Gates concrete (G1' / G2' / G3').

针对策略 (而非因子) 的评估硬门. 与因子 G1-G10 互补:
  - G1' Sharpe paired bootstrap p < 0.05 vs baseline (铁律 5)
  - G2' Max drawdown < threshold (默认 -30%, 调用方可传)
  - G3' regression max_diff = 0 vs baseline (铁律 15)

Strategy Gates 复用 batch 1 Gate ABC + GateContext, 通过 `ctx.extra` (read-only Mapping)
取策略特化输入:
  - extra["candidate_daily_returns"]: np.ndarray (G1')
  - extra["baseline_daily_returns"]: np.ndarray (G1')
  - extra["nav_series"]: np.ndarray (G2')
  - extra["max_dd_threshold"]: float, 默认 -0.30 (G2', 比 5y baseline -50.75% 宽 + 比 WF OOS -30.23% 严)
  - extra["regression_runner"]: Callable[[], dict] 返 {"max_diff": float} (G3')

设计意图: register() 不 inline wire (避免 5min 阻塞), 调用方在升 LIVE 前显式调
PlatformStrategyEvaluator.evaluate_strategy(). 详见 ADR-014.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .gates.base import Gate, GateContext
from .interface import GateResult
from .utils import paired_bootstrap_pvalue

# ============================================================================
# G1' Sharpe paired bootstrap (铁律 5)
# ============================================================================


STRATEGY_G1_PVALUE_THRESHOLD: float = 0.05
"""单边 paired bootstrap p 上限 (铁律 5, 同 G3 因子级)."""

STRATEGY_G1_BOOTSTRAP_ITER: int = 1000


class StrategyG1SharpeGate(Gate):
    """G1' 策略 Sharpe paired bootstrap p < 0.05 vs baseline.

    候选策略 daily_return 经向量化 paired bootstrap 得 p 值, 单边检验
    candidate.mean() > baseline.mean(). p < 0.05 → PASS.

    缺数据 fail-soft: data_unavailable.
    """

    name = "G1prime_sharpe_bootstrap"
    threshold = STRATEGY_G1_PVALUE_THRESHOLD

    def __init__(
        self,
        *,
        n_iter: int = STRATEGY_G1_BOOTSTRAP_ITER,
        rng_seed: int | None = 42,
    ) -> None:
        self.n_iter = n_iter
        self.rng_seed = rng_seed

    def evaluate(self, ctx: GateContext) -> GateResult:
        candidate = ctx.extra.get("candidate_daily_returns")
        baseline = ctx.extra.get("baseline_daily_returns")
        missing: list[str] = []
        if candidate is None:
            missing.append("extra.candidate_daily_returns")
        if baseline is None:
            missing.append("extra.baseline_daily_returns")
        if missing:
            return self._data_unavailable(missing)

        p = paired_bootstrap_pvalue(
            candidate=candidate,
            baseline=baseline,
            n_iter=self.n_iter,
            rng_seed=self.rng_seed,
        )
        if p is None:
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=None,
                details={
                    "reason": "sample_size_or_shape_mismatch",
                    "candidate_n": int(np.asarray(candidate).size),
                    "baseline_n": int(np.asarray(baseline).size),
                },
            )

        passed = p < self.threshold
        return GateResult(
            gate_name=self.name,
            passed=passed,
            threshold=self.threshold,
            observed=p,
            details={
                "n_iter": self.n_iter,
                "rng_seed": self.rng_seed,
                "single_sided_test": True,
                "ironclad_rule": 5,
            },
        )


# ============================================================================
# G2' Max Drawdown (策略稳健性)
# ============================================================================


STRATEGY_G2_DEFAULT_MAX_DD: float = -0.30
"""默认 max DD 上限 -30% (比 5y CSI300 baseline -50.75% 宽, 比 PT WF OOS -30.23% 严).

调用方可通过 ctx.extra["max_dd_threshold"] 覆盖.
"""


def _compute_max_drawdown(nav: np.ndarray) -> float:
    """从 NAV 时间序列计算 max drawdown (负值, e.g. -0.25 表 25% 跌幅).

    Args:
      nav: 累计净值 (起始 1.0 或任意正值).

    Returns:
      max drawdown 浮点数. 若 nav 全升序返 0.0.
    """
    if nav.size < 2:
        return 0.0
    running_max = np.maximum.accumulate(nav)
    drawdowns = (nav - running_max) / running_max
    return float(drawdowns.min())


class StrategyG2MaxDrawdownGate(Gate):
    """G2' 策略 Max Drawdown 限额硬门.

    默认阈值 -0.30 (调用方可 override 通过 ctx.extra["max_dd_threshold"]).
    实测 max DD < threshold (即跌幅小于阈值绝对值) → PASS.
    """

    name = "G2prime_max_drawdown"
    threshold = STRATEGY_G2_DEFAULT_MAX_DD

    def evaluate(self, ctx: GateContext) -> GateResult:
        nav = ctx.extra.get("nav_series")
        if nav is None:
            return self._data_unavailable(["extra.nav_series"])

        nav_array = np.asarray(nav, dtype=np.float64)
        if nav_array.size < 2:
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=None,
                details={
                    "reason": "nav_series_too_short",
                    "n": int(nav_array.size),
                },
            )

        threshold = float(ctx.extra.get("max_dd_threshold", STRATEGY_G2_DEFAULT_MAX_DD))
        max_dd = _compute_max_drawdown(nav_array)
        passed = max_dd >= threshold  # max_dd 是负值, ≥ threshold 表跌幅小

        return GateResult(
            gate_name=self.name,
            passed=passed,
            threshold=threshold,
            observed=max_dd,
            details={
                "n_days": int(nav_array.size),
                "max_dd": max_dd,
                "threshold": threshold,
            },
        )


# ============================================================================
# G3' Regression max_diff = 0 (铁律 15 可复现性硬门)
# ============================================================================


class StrategyG3RegressionGate(Gate):
    """G3' regression max_diff = 0 vs baseline (铁律 15).

    调用方提供 ctx.extra["regression_runner"]: Callable[[], dict] 返 {"max_diff": float}.
    max_diff == 0.0 严格要求 (NAV 完全 bit-identical, 铁律 15).

    例外: 全新策略无 baseline → ctx.extra["no_baseline"] = True → PASS with reason='no_baseline'.
    """

    name = "G3prime_regression_max_diff"
    threshold = 0.0  # 严格 max_diff = 0

    def evaluate(self, ctx: GateContext) -> GateResult:
        # 全新策略无 baseline 例外 (ADR-014 §4 明确, SKIP 视为 PASS).
        # PR #125 reviewer P1 警告: no_baseline 是一次性首部署 flag, **必须**在第一次 deploy
        # 落 baseline parquet 后清除. 调用方若 stale 持有 no_baseline=True 会让 G3' 永远
        # 无法捕获 regression 漂移. ADR-014 后续 follow-up #1 (DBStrategyRegistry 状态机
        # check evaluation_required 中间态) 将额外把关.
        if ctx.extra.get("no_baseline"):
            return GateResult(
                gate_name=self.name,
                passed=True,
                threshold=self.threshold,
                observed=None,
                details={
                    "reason": "no_baseline_first_deployment",
                    "ironclad_rule": 15,
                    "note": "全新策略无 baseline → SKIP, 后续 deploy 后必跑 regression",
                    "warning": (
                        "no_baseline=True 是一次性首部署 flag, 必须在 baseline 落地后清除. "
                        "审计 log 检查这条 warning, stale flag 会让 G3' 永远 PASS."
                    ),
                },
            )

        runner = ctx.extra.get("regression_runner")
        if runner is None:
            return self._data_unavailable(["extra.regression_runner"])
        if not callable(runner):
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=None,
                details={
                    "reason": "regression_runner_not_callable",
                    "type": type(runner).__name__,
                },
            )

        try:
            result = runner()
        except Exception as e:  # noqa: BLE001 — Gate 不 raise, 包 GateResult
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=None,
                details={
                    "reason": "regression_runner_raised",
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

        if not isinstance(result, dict) or "max_diff" not in result:
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=None,
                details={
                    "reason": "regression_runner_invalid_result",
                    "result_keys": list(result.keys()) if isinstance(result, dict) else None,
                },
            )

        max_diff = float(result["max_diff"])
        passed = max_diff == 0.0
        return GateResult(
            gate_name=self.name,
            passed=passed,
            threshold=self.threshold,
            observed=max_diff,
            details={
                "max_diff": max_diff,
                "ironclad_rule": 15,
                "extra_metrics": {k: v for k, v in result.items() if k != "max_diff"},
            },
        )


# ============================================================================
# Helper: 默认 Strategy 评估 pipeline 工厂
# ============================================================================


def default_strategy_pipeline(
    context_loader: Any,
    *,
    rng_seed: int = 42,
):
    """构造 Strategy 评估默认 pipeline (G1' + G2' + G3').

    Args:
      context_loader: Callable[[str], GateContext] — 调用方按 strategy_id 提供 ctx
        (含 extra 内 candidate/baseline daily_returns / nav_series / regression_runner).
      rng_seed: G1' bootstrap 种子.

    Returns:
      PlatformEvaluationPipeline 含 G1' / G2' / G3'.
    """
    from .pipeline import PlatformEvaluationPipeline

    return PlatformEvaluationPipeline(
        gates=[
            StrategyG1SharpeGate(rng_seed=rng_seed),
            StrategyG2MaxDrawdownGate(),
            StrategyG3RegressionGate(),
        ],
        context_loader=context_loader,
    )
