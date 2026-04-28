"""G9 Novelty AST Gate — AST Jaccard < 0.7 (铁律 12).

包装 MVP 1.3c qm_platform/factor/registry.py:_default_ast_jaccard + novelty_check.
ctx.factor_meta + ctx.registry 必需 (registry.novelty_check 已封 ACTIVE 因子遍历).
"""
from __future__ import annotations

from ...factor.interface import FactorSpec
from ...factor.registry import G9_SIMILARITY_THRESHOLD
from ..interface import GateResult
from .base import Gate, GateContext


class G9NoveltyAstGate(Gate):
    """G9 AST 新颖性 — Jaccard < 0.7 (复用 MVP 1.3c 实现)."""

    name = "G9_novelty_ast"
    threshold = G9_SIMILARITY_THRESHOLD

    def evaluate(self, ctx: GateContext) -> GateResult:
        missing: list[str] = []
        if ctx.factor_meta is None:
            missing.append("factor_meta")
        if ctx.registry is None:
            missing.append("registry")
        if missing:
            return self._data_unavailable(missing)

        meta = ctx.factor_meta  # type: ignore[assignment]

        # 构造 FactorSpec (registry.novelty_check 接受 spec 而非 meta)
        # FactorSpec schema (MVP 1.3a): name/hypothesis/expression/direction/category/pool/author 共 7 字段
        try:
            spec = FactorSpec(
                name=meta.name,  # type: ignore[union-attr]
                hypothesis=meta.hypothesis or "",  # type: ignore[union-attr]
                expression=meta.expression or "",  # type: ignore[union-attr]
                direction=meta.direction,  # type: ignore[union-attr]
                category=meta.category,  # type: ignore[union-attr]
                pool=meta.pool,  # type: ignore[union-attr]
                author=meta.source,  # type: ignore[union-attr] — Meta.source 充当 author 字段
            )
        except (TypeError, AttributeError) as e:
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=None,
                details={"reason": "factor_meta_incompatible", "error": str(e)},
            )

        try:
            passed = ctx.registry.novelty_check(spec)  # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001 — Gate pure function 不 re-raise
            return GateResult(
                gate_name=self.name,
                passed=False,
                threshold=self.threshold,
                observed=None,
                details={"reason": "registry_call_failed", "error": str(e)},
            )

        return GateResult(
            gate_name=self.name,
            passed=passed,
            threshold=self.threshold,
            observed=None,  # Jaccard 实测值在 registry 内部, 不暴露
            details={
                "via": "registry.novelty_check",
                "expression_len": len(spec.expression),
                "ironclad_rule": 12,
            },
        )
