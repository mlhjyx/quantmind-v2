"""G4 OOS Walk-Forward Gate — WF 5-fold OOS Sharpe ≥ baseline (铁律 8).

不实跑回测 (Wave 3 暂只读已存 cache), ctx.wf_oos_sharpe + ctx.wf_baseline_sharpe 由调用方提供.
"""
from __future__ import annotations

from ..interface import GateResult
from .base import Gate, GateContext


class G4WalkForwardGate(Gate):
    """G4 WF OOS — wf_oos_sharpe ≥ wf_baseline_sharpe."""

    name = "G4_oos_walkforward"
    threshold = None  # 阈值是 baseline_sharpe (relative), 不是绝对值

    def evaluate(self, ctx: GateContext) -> GateResult:
        missing: list[str] = []
        if ctx.wf_oos_sharpe is None:
            missing.append("wf_oos_sharpe")
        if ctx.wf_baseline_sharpe is None:
            missing.append("wf_baseline_sharpe")
        if missing:
            return self._data_unavailable(missing)

        # type narrowing: both are float after None check
        oos: float = ctx.wf_oos_sharpe  # type: ignore[assignment]
        base: float = ctx.wf_baseline_sharpe  # type: ignore[assignment]

        passed = oos >= base
        return GateResult(
            gate_name=self.name,
            passed=passed,
            threshold=base,
            observed=oos,
            details={
                "wf_oos_sharpe": oos,
                "wf_baseline_sharpe": base,
                "delta": oos - base,
            },
        )
