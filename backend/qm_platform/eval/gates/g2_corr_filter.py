"""G2 Correlation Filter Gate — 与 active 池 |corr| < 0.7 + 月收益 corr < 0.3 (铁律 4).

ctx.active_corr_max: 调用方预计算的 max |corr| (避免 Gate 内部 IO).
ctx.monthly_return_corr_max: 月收益 corr (可选, 设计稿 0.3 阈值).
"""
from __future__ import annotations

from ..interface import GateResult
from .base import Gate, GateContext

G2_IC_CORR_THRESHOLD: float = 0.7
"""与 active 池因子 IC 相关性上限 (铁律 4)."""

G2_MONTHLY_RET_CORR_THRESHOLD: float = 0.3
"""月度选股收益与 active 池上限 (设计稿)."""


class G2CorrelationFilterGate(Gate):
    """G2 相关性过滤 — IC corr < 0.7 AND monthly return corr < 0.3 (若提供)."""

    name = "G2_corr_filter"
    threshold = G2_IC_CORR_THRESHOLD

    def evaluate(self, ctx: GateContext) -> GateResult:
        if ctx.active_corr_max is None:
            return self._data_unavailable(["active_corr_max"])

        ic_passed = abs(ctx.active_corr_max) < G2_IC_CORR_THRESHOLD

        # monthly return corr 可选, 若提供则需同时通过
        monthly_passed = True
        if ctx.monthly_return_corr_max is not None:
            monthly_passed = abs(ctx.monthly_return_corr_max) < G2_MONTHLY_RET_CORR_THRESHOLD

        passed = ic_passed and monthly_passed
        return GateResult(
            gate_name=self.name,
            passed=passed,
            threshold=self.threshold,
            observed=ctx.active_corr_max,
            details={
                "ic_corr_max": ctx.active_corr_max,
                "ic_corr_threshold": G2_IC_CORR_THRESHOLD,
                "monthly_return_corr_max": ctx.monthly_return_corr_max,
                "monthly_return_corr_threshold": G2_MONTHLY_RET_CORR_THRESHOLD,
                "ic_passed": ic_passed,
                "monthly_passed": monthly_passed,
            },
        )
