"""Framework #4 Eval — Gate concretes (G1-G10).

每个 Gate 是 pure function (不 raise, 返 GateResult).
Pipeline 顺序跑所有 Gate, 用户看到完整 picture (而非首 fail 抛中断).

设计稿: docs/mvp/MVP_3_5_eval_gate_framework.md
"""
from __future__ import annotations

from .base import Gate, GateContext, GateError
from .g1_ic_significance import G1IcSignificanceGate
from .g2_corr_filter import G2CorrelationFilterGate
from .g3_paired_bootstrap import G3PairedBootstrapGate
from .g4_oos_walkforward import G4WalkForwardGate
from .g8_bh_fdr import G8BhFdrGate
from .g9_novelty_ast import G9NoveltyAstGate
from .g10_hypothesis import G10HypothesisGate

__all__ = [
    "Gate",
    "GateContext",
    "GateError",
    "G1IcSignificanceGate",
    "G2CorrelationFilterGate",
    "G3PairedBootstrapGate",
    "G4WalkForwardGate",
    "G8BhFdrGate",
    "G9NoveltyAstGate",
    "G10HypothesisGate",
]
