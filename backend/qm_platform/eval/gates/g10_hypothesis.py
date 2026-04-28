"""G10 Hypothesis Gate — economic mechanism 描述检查 (铁律 13).

包装 MVP 1.3c qm_platform/factor/registry.py:G10_HYPOTHESIS_MIN_LEN + G10_FORBIDDEN_PREFIXES.
DDL 字段名是 `hypothesis` (factor_registry.hypothesis TEXT), 非 `economic_mechanism`.
"""
from __future__ import annotations

from ...factor.registry import G10_FORBIDDEN_PREFIXES, G10_HYPOTHESIS_MIN_LEN
from ..interface import GateResult
from .base import Gate, GateContext


class G10HypothesisGate(Gate):
    """G10 经济机制描述 — hypothesis 非空 + 长度 ≥ 20 + 不以占位符前缀开头 (铁律 13).

    复用 MVP 1.3c 阈值常量 (qm_platform/factor/registry.py).
    Wave 4+ V2: LLM-based hypothesis ↔ expression 一致性检查.
    """

    name = "G10_hypothesis"
    threshold = float(G10_HYPOTHESIS_MIN_LEN)

    def evaluate(self, ctx: GateContext) -> GateResult:
        if ctx.factor_meta is None:
            return self._data_unavailable(["factor_meta"])

        hypo_raw = getattr(ctx.factor_meta, "hypothesis", None)
        hypo = (hypo_raw or "").strip()
        observed_len = float(len(hypo))

        # 检查 1: 非空 + 长度
        if len(hypo) < G10_HYPOTHESIS_MIN_LEN:
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=observed_len,
                details={
                    "reason": "hypothesis_too_short",
                    "min_len": G10_HYPOTHESIS_MIN_LEN,
                    "actual_len": int(observed_len),
                    "ironclad_rule": 13,
                },
            )

        # 检查 2: 不以占位符前缀开头
        for prefix in G10_FORBIDDEN_PREFIXES:
            if hypo.startswith(prefix):
                return GateResult(
                    gate_name=self.name,
                    passed=False,
                    threshold=self.threshold,
                    observed=observed_len,
                    details={
                        "reason": "forbidden_placeholder_prefix",
                        "matched_prefix": prefix,
                        "forbidden_prefixes": list(G10_FORBIDDEN_PREFIXES),
                        "ironclad_rule": 13,
                    },
                )

        return GateResult(
            gate_name=self.name,
            passed=True,
            threshold=self.threshold,
            observed=observed_len,
            details={
                "min_len": G10_HYPOTHESIS_MIN_LEN,
                "v1_check": "length_and_prefix",
                "v2_llm_check": "Wave 4+ TBD",
            },
        )
