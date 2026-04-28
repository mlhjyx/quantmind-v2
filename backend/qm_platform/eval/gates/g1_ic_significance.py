"""G1 IC Significance Gate — t > 2.5 硬下限 (Harvey Liu Zhu 2016, 铁律 4).

ic_series: 时间序列 IC (e.g. ic_5d / ic_20d 数列).
判定: t = ic.mean() / (ic.std(ddof=1) / sqrt(n)), t > G1_T_THRESHOLD 通过.
"""
from __future__ import annotations

from ..interface import GateResult
from ..utils import t_statistic
from .base import Gate, GateContext

G1_T_THRESHOLD: float = 2.5
"""Harvey Liu Zhu (2016) hard lower bound for cross-sectional alpha."""


class G1IcSignificanceGate(Gate):
    """G1 IC 显著性 — t-statistic > 2.5."""

    name = "G1_ic_significance"
    threshold = G1_T_THRESHOLD

    def evaluate(self, ctx: GateContext) -> GateResult:
        if ctx.ic_series is None or ctx.ic_series.size == 0:
            return self._data_unavailable(["ic_series"])

        t_stat = t_statistic(ctx.ic_series)
        if t_stat is None:
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=None,
                details={"reason": "insufficient_sample_or_zero_std", "n": int(ctx.ic_series.size)},
            )

        passed = abs(t_stat) > self.threshold
        return GateResult(
            gate_name=self.name,
            passed=passed,
            threshold=self.threshold,
            observed=t_stat,
            details={
                "n": int(ctx.ic_series.size),
                "ic_mean": float(ctx.ic_series.mean()),
                "harvey_liu_zhu_2016": True,
            },
        )
