"""G3 Paired Bootstrap Gate — paired bootstrap p < 0.05 vs baseline (铁律 5).

调 utils.paired_bootstrap_pvalue 单边检验 ic > baseline.
ctx.ic_series + ctx.ic_baseline_series 必需 (同长度对齐).
"""
from __future__ import annotations

from ..interface import GateResult
from ..utils import paired_bootstrap_pvalue
from .base import Gate, GateContext

G3_PVALUE_THRESHOLD: float = 0.05
"""单边 paired bootstrap p 上限 (铁律 5)."""

G3_BOOTSTRAP_ITER: int = 1000
"""bootstrap 重抽样次数."""


class G3PairedBootstrapGate(Gate):
    """G3 paired bootstrap — p < 0.05 vs baseline IC."""

    name = "G3_paired_bootstrap"
    threshold = G3_PVALUE_THRESHOLD

    def __init__(self, *, n_iter: int = G3_BOOTSTRAP_ITER, rng_seed: int | None = 42) -> None:
        """注入 rng_seed 保 deterministic test (默认 42).

        Args:
          n_iter: bootstrap 次数.
          rng_seed: 随机种子, None 则非 deterministic.
        """
        self.n_iter = n_iter
        self.rng_seed = rng_seed

    def evaluate(self, ctx: GateContext) -> GateResult:
        missing: list[str] = []
        if ctx.ic_series is None:
            missing.append("ic_series")
        if ctx.ic_baseline_series is None:
            missing.append("ic_baseline_series")
        if missing:
            return self._data_unavailable(missing)

        # type: ignore[arg-type] — already None-checked above
        p = paired_bootstrap_pvalue(
            candidate=ctx.ic_series,  # type: ignore[arg-type]
            baseline=ctx.ic_baseline_series,  # type: ignore[arg-type]
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
                    "candidate_n": int(ctx.ic_series.size),  # type: ignore[union-attr]
                    "baseline_n": int(ctx.ic_baseline_series.size),  # type: ignore[union-attr]
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
            },
        )
