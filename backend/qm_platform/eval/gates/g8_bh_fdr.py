"""G8 BH-FDR Gate — Benjamini-Hochberg 校正 (Harvey Liu Zhu 2016).

ctx.bh_fdr_p_value + bh_fdr_rank + bh_fdr_m 由调用方从 FACTOR_TEST_REGISTRY 读.
判定: p ≤ rank/m × 0.05 通过.
"""
from __future__ import annotations

from ..interface import GateResult
from ..utils import benjamini_hochberg_threshold
from .base import Gate, GateContext

G8_FDR: float = 0.05
"""Benjamini-Hochberg FDR 默认 5%."""


class G8BhFdrGate(Gate):
    """G8 BH-FDR — p ≤ rank/m × fdr."""

    name = "G8_bh_fdr"
    threshold = G8_FDR

    def __init__(self, *, fdr: float = G8_FDR) -> None:
        """Args:
          fdr: FDR 上限, 默认 0.05.
        """
        self.fdr = fdr

    def evaluate(self, ctx: GateContext) -> GateResult:
        missing: list[str] = []
        if ctx.bh_fdr_p_value is None:
            missing.append("bh_fdr_p_value")
        if ctx.bh_fdr_rank is None:
            missing.append("bh_fdr_rank")
        if ctx.bh_fdr_m is None:
            missing.append("bh_fdr_m")
        if missing:
            return self._data_unavailable(missing)

        try:
            passed = benjamini_hochberg_threshold(
                p_value=ctx.bh_fdr_p_value,  # type: ignore[arg-type]
                rank=ctx.bh_fdr_rank,  # type: ignore[arg-type]
                m=ctx.bh_fdr_m,  # type: ignore[arg-type]
                fdr=self.fdr,
            )
        except ValueError as e:
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=ctx.bh_fdr_p_value,
                details={"reason": "invalid_input", "error": str(e)},
            )

        rank = ctx.bh_fdr_rank  # type: ignore[assignment]
        m = ctx.bh_fdr_m  # type: ignore[assignment]
        bh_threshold = (rank / m) * self.fdr  # type: ignore[operator]
        return GateResult(
            gate_name=self.name,
            passed=passed,
            threshold=bh_threshold,
            observed=ctx.bh_fdr_p_value,
            details={
                "rank": rank,
                "m": m,
                "fdr": self.fdr,
                "bh_threshold": bh_threshold,
            },
        )
