"""AST去重器 — 三层级联去重 (AlphaAgent KDD 2025模式)

R2研究结论: AST结构去重准确率比字符串去重高81%（AlphaAgent实验数据）。

三层级联去重策略 (R2 §2.4推荐):
  L1: AST结构规范化 + 哈希  — 捕获结构克隆 (rank(a+b) == rank(b+a))
  L2: 规范化AST dump比较    — 捕获边界哈希碰撞和命名变体
  L3: Spearman相关性        — 捕获语义等价 (不同公式但输出高度相关)

参考: AlphaAgent (arXiv 2502.16789, KDD 2025)
"""

from __future__ import annotations

import ast
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class DedupResult:
    """去重结果"""

    unique_expressions: list[str]
    removed_expressions: list[str]
    removal_reasons: dict[str, str]  # expr -> 去重原因
    n_input: int = 0
    n_output: int = 0

    @property
    def dedup_rate(self) -> float:
        if self.n_input == 0:
            return 0.0
        return (self.n_input - self.n_output) / self.n_input


# ---------------------------------------------------------------------------
# AST 规范化变换器
# ---------------------------------------------------------------------------


class _ASTNormalizer(ast.NodeTransformer):
    """AST规范化器 — 消除语义等价的结构差异

    变换规则:
    1. 交换律: 对 Add/Mult 按 AST dump 排序操作数
    2. 常数折叠: 2+3 → 5
    3. 统一数值: 1.0 → 1
    4. 消除双重取负: --x → x
    """

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]

        # 常数折叠
        if isinstance(node.left, ast.Constant) and isinstance(
            node.right, ast.Constant
        ):
            result = _eval_constant_binop(
                node.op, node.left.value, node.right.value
            )
            if result is not None:
                return ast.Constant(value=result)

        # 交换律规范化（Add/Mult）
        if isinstance(node.op, (ast.Add, ast.Mult)):
            left_str = ast.dump(node.left)
            right_str = ast.dump(node.right)
            if left_str > right_str:
                node.left, node.right = node.right, node.left

        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, float) and node.value == int(node.value):
            return ast.Constant(value=int(node.value))
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        node = self.generic_visit(node)  # type: ignore[assignment]
        if (
            isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.UnaryOp)
            and isinstance(node.operand.op, ast.USub)
        ):
            return node.operand.operand
        return node


def _eval_constant_binop(
    op: ast.operator, left: Any, right: Any
) -> Any:
    """对常数二元运算求值"""
    try:
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right if right != 0 else None
        if isinstance(op, ast.Pow):
            return left**right
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 核心去重器
# ---------------------------------------------------------------------------


class ASTDeduplicator:
    """AST语义去重器

    使用三层级联策略对因子表达式列表去重。

    Args:
        spearman_threshold: L3 Spearman相关性阈值（默认0.7，来自 R2 Gate G6）
        use_l3_spearman: 是否启用 L3 Spearman 检查（需要因子数据）
    """

    def __init__(
        self,
        spearman_threshold: float = 0.7,
        use_l3_spearman: bool = False,
    ) -> None:
        self.spearman_threshold = spearman_threshold
        self.use_l3_spearman = use_l3_spearman
        self._normalizer = _ASTNormalizer()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def normalize_ast(self, expr: str) -> ast.AST | None:
        """规范化表达式 AST

        Returns:
            规范化后的 AST，解析失败返回 None
        """
        try:
            tree = ast.parse(expr, mode="eval")
            normalized = self._normalizer.visit(tree)
            ast.fix_missing_locations(normalized)
            return normalized
        except SyntaxError:
            logger.debug("AST解析失败: %s", expr)
            return None

    def ast_hash(self, expr: str) -> str:
        """计算表达式的语义哈希（规范化AST dump的SHA256前16位）

        语义相同的表达式产生相同哈希，例如:
            rank(a + b) == rank(b + a)  → 相同哈希

        Returns:
            16位十六进制哈希字符串，解析失败返回空字符串
        """
        normalized = self.normalize_ast(expr)
        if normalized is None:
            return ""
        dump = ast.dump(normalized, indent=None)
        return hashlib.sha256(dump.encode()).hexdigest()[:16]

    def are_equivalent(self, expr1: str, expr2: str) -> bool:
        """判断两个表达式是否语义等价（L1+L2层）"""
        h1 = self.ast_hash(expr1)
        h2 = self.ast_hash(expr2)
        if h1 and h2 and h1 == h2:
            return True

        n1 = self.normalize_ast(expr1)
        n2 = self.normalize_ast(expr2)
        if n1 is not None and n2 is not None:
            return ast.dump(n1) == ast.dump(n2)

        return False

    def deduplicate(
        self,
        candidates: list[str],
        factor_data: dict[str, pd.Series] | None = None,
    ) -> DedupResult:
        """批量去重因子表达式列表

        L1+L2: 始终执行（基于 AST 结构）
        L3: 仅在 use_l3_spearman=True 且 factor_data 不为 None 时执行

        Args:
            candidates: 因子表达式字符串列表
            factor_data: 表达式 → 因子值 Series 的映射（L3用）

        Returns:
            DedupResult
        """
        if not candidates:
            return DedupResult(
                unique_expressions=[],
                removed_expressions=[],
                removal_reasons={},
                n_input=0,
                n_output=0,
            )

        unique: list[str] = []
        removed: list[str] = []
        reasons: dict[str, str] = {}

        seen_hashes: set[str] = set()
        seen_ast_dumps: set[str] = set()

        for expr in candidates:
            h = self.ast_hash(expr)

            # L1: 哈希去重
            if h and h in seen_hashes:
                removed.append(expr)
                reasons[expr] = f"L1_AST_hash_duplicate(hash={h})"
                continue

            # L2: 规范化 AST dump 去重
            normalized = self.normalize_ast(expr)
            dump = ast.dump(normalized) if normalized is not None else expr
            if dump in seen_ast_dumps:
                removed.append(expr)
                reasons[expr] = "L2_normalized_ast_duplicate"
                continue

            # L3: Spearman 相关性去重（可选）
            if (
                self.use_l3_spearman
                and factor_data is not None
                and expr in factor_data
            ):
                is_dup, dup_reason = self._l3_spearman_check(
                    expr, unique, factor_data
                )
                if is_dup:
                    removed.append(expr)
                    reasons[expr] = dup_reason
                    continue

            unique.append(expr)
            if h:
                seen_hashes.add(h)
            seen_ast_dumps.add(dump)

        return DedupResult(
            unique_expressions=unique,
            removed_expressions=removed,
            removal_reasons=reasons,
            n_input=len(candidates),
            n_output=len(unique),
        )

    def deduplicate_with_existing(
        self,
        new_candidates: list[str],
        existing_expressions: list[str],
        factor_data: dict[str, pd.Series] | None = None,
    ) -> DedupResult:
        """对新候选因子去重，同时考虑已有因子库

        先内部去重，再与现有因子库对比。

        Returns:
            DedupResult（只包含新候选中的去重结果）
        """
        intra_result = self.deduplicate(new_candidates, factor_data)

        # 预计算现有因子库的哈希和 dump
        existing_hashes: set[str] = set()
        existing_dumps: set[str] = set()
        for expr in existing_expressions:
            h = self.ast_hash(expr)
            if h:
                existing_hashes.add(h)
            n = self.normalize_ast(expr)
            if n is not None:
                existing_dumps.add(ast.dump(n))

        final_unique: list[str] = []
        extra_removed: list[str] = []
        extra_reasons: dict[str, str] = {}

        for expr in intra_result.unique_expressions:
            h = self.ast_hash(expr)
            n = self.normalize_ast(expr)
            dump = ast.dump(n) if n is not None else expr

            if h and h in existing_hashes:
                extra_removed.append(expr)
                extra_reasons[expr] = f"L1_duplicate_with_existing(hash={h})"
                continue
            if dump in existing_dumps:
                extra_removed.append(expr)
                extra_reasons[expr] = "L2_duplicate_with_existing"
                continue

            if (
                self.use_l3_spearman
                and factor_data is not None
                and expr in factor_data
            ):
                is_dup, dup_reason = self._l3_spearman_check(
                    expr, existing_expressions, factor_data
                )
                if is_dup:
                    extra_removed.append(expr)
                    extra_reasons[expr] = f"L3_corr_with_existing:{dup_reason}"
                    continue

            final_unique.append(expr)

        return DedupResult(
            unique_expressions=final_unique,
            removed_expressions=intra_result.removed_expressions + extra_removed,
            removal_reasons={
                **intra_result.removal_reasons,
                **extra_reasons,
            },
            n_input=len(new_candidates),
            n_output=len(final_unique),
        )

    # ------------------------------------------------------------------
    # L3: Spearman 相关性检查
    # ------------------------------------------------------------------

    def _l3_spearman_check(
        self,
        expr: str,
        reference_exprs: list[str],
        factor_data: dict[str, pd.Series],
    ) -> tuple[bool, str]:
        """L3: 检查新表达式与参考因子库的 Spearman 相关性"""
        if expr not in factor_data:
            return False, ""

        new_series = factor_data[expr]

        for ref_expr in reference_exprs:
            if ref_expr not in factor_data or ref_expr == expr:
                continue

            ref_series = factor_data[ref_expr]
            common = new_series.index.intersection(ref_series.index)
            if len(common) < 30:
                continue

            try:
                corr, _ = stats.spearmanr(
                    new_series.loc[common].fillna(0).values,
                    ref_series.loc[common].fillna(0).values,
                )
                if abs(float(corr)) >= self.spearman_threshold:
                    return True, (
                        f"L3_spearman_corr={corr:.3f}_with_{ref_expr[:40]}"
                    )
            except Exception:
                continue

        return False, ""

    # ------------------------------------------------------------------
    # 便捷工具
    # ------------------------------------------------------------------

    def get_ast_structure(self, expr: str) -> str:
        """返回规范化 AST 的可读表示（调试用）"""
        normalized = self.normalize_ast(expr)
        if normalized is None:
            return f"PARSE_ERROR: {expr}"
        return ast.dump(normalized, indent=2)

    def compute_ast_similarity(self, expr1: str, expr2: str) -> float:
        """计算两个表达式的 AST 节点集合 Jaccard 相似度（0-1）"""
        n1 = self.normalize_ast(expr1)
        n2 = self.normalize_ast(expr2)
        if n1 is None or n2 is None:
            return 0.0

        nodes1 = {ast.dump(n) for n in ast.walk(n1)}
        nodes2 = {ast.dump(n) for n in ast.walk(n2)}

        if not nodes1 or not nodes2:
            return 0.0

        intersection = nodes1 & nodes2
        return len(intersection) / max(len(nodes1), len(nodes2))

    def batch_deduplicate_candidates(
        self,
        candidates: list[Any],
        expr_attr: str = "expression",
        factor_data: dict[str, pd.Series] | None = None,
    ) -> list[Any]:
        """对 FactorCandidate 对象列表去重（便捷方法）

        Args:
            candidates: FactorCandidate 对象列表
            expr_attr: 表达式属性名（默认 "expression"）
            factor_data: 表达式 → 因子值（L3用）

        Returns:
            去重后的列表（保留每个等价组的首次出现）
        """
        exprs = [getattr(c, expr_attr) for c in candidates]
        result = self.deduplicate(exprs, factor_data)
        unique_set = set(result.unique_expressions)

        seen: set[str] = set()
        deduped: list[Any] = []
        for cand in candidates:
            expr = getattr(cand, expr_attr)
            if expr in unique_set and expr not in seen:
                deduped.append(cand)
                seen.add(expr)

        logger.info(
            "候选去重: %d → %d (移除 %d 个)",
            len(candidates),
            len(deduped),
            len(candidates) - len(deduped),
        )
        return deduped
