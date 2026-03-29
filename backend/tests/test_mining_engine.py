"""单元测试: Factor Sandbox + BruteForce引擎 + AST去重器

测试覆盖:
- FactorSandbox: AST安全检查拦截危险表达式; 合法表达式正常执行
- BruteForceEngine: 模板展开数量; 候选生成; 经济学假设完整性; Gate阈值
- ASTDeduplicator: 语义等价检测(交换律/常数折叠); 哈希稳定性; 批量去重
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from engines.mining.ast_dedup import ASTDeduplicator, DedupResult
from engines.mining.bruteforce_engine import (
    FACTOR_TEMPLATES,
    BruteForceEngine,
    FactorCandidate,
)
from engines.mining.factor_sandbox import FactorSandbox

# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


@pytest.fixture()
def sandbox() -> FactorSandbox:
    return FactorSandbox(timeout=5)


@pytest.fixture()
def dedup() -> ASTDeduplicator:
    return ASTDeduplicator()


@pytest.fixture()
def simple_cross_section() -> pd.DataFrame:
    """100只股票的单截面数据"""
    rng = np.random.default_rng(42)
    n = 100
    close = rng.uniform(10, 100, n)
    return pd.DataFrame(
        {
            "close": close,
            "open": close * rng.uniform(0.95, 1.05, n),
            "high": close * rng.uniform(1.0, 1.1, n),
            "low": close * rng.uniform(0.9, 1.0, n),
            "volume": rng.uniform(1e6, 1e8, n),
            "amount": rng.uniform(1e7, 1e9, n),
            "turnover_rate": rng.uniform(0.01, 0.1, n),
            "pe_ttm": rng.uniform(5, 100, n),
            "pb": rng.uniform(0.5, 10, n),
            "total_mv": rng.uniform(1e8, 1e11, n),
            "circ_mv": rng.uniform(1e8, 1e11, n),
        }
    )


# ===========================================================================
# FactorSandbox 测试
# ===========================================================================


class TestFactorSandboxSecurity:
    """安全检查必须拦截所有危险表达式"""

    @pytest.mark.parametrize(
        "dangerous_expr",
        [
            "import os",
            "__import__('os').system('rm -rf /')",
            "exec('print(1)')",
            "eval('1+1')",
            "os.system('ls')",
            "sys.exit(0)",
            "subprocess.run(['ls'])",
            "__builtins__['eval']('1')",
            "globals()['os']",
            "getattr(os, 'system')('ls')",
        ],
    )
    def test_blocks_dangerous_expressions(
        self, sandbox: FactorSandbox, dangerous_expr: str
    ) -> None:
        result = sandbox.validate_expression(dangerous_expr)
        assert not result.is_valid, f"应该拦截危险表达式: {dangerous_expr!r}"
        assert len(result.errors) > 0

    def test_blocks_open_file_call(self, sandbox: FactorSandbox) -> None:
        """open() 文件调用必须被拦截（安全检查核心要求）"""
        result = sandbox.validate_expression("open('/etc/passwd').read()")
        assert not result.is_valid, "应该拦截 open() 文件访问"

    def test_blocks_dunder_attribute_access(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression("close.__class__.__bases__")
        assert not result.is_valid

    def test_blocks_overlong_expression(self, sandbox: FactorSandbox) -> None:
        long_expr = "rank(close)" + " + rank(close)" * 100
        result = sandbox.validate_expression(long_expr)
        assert not result.is_valid

    def test_allows_safe_financial_expressions(self, sandbox: FactorSandbox) -> None:
        safe_exprs = [
            "rank(close / delay(close, 20))",
            "rank(ts_std(close, 20))",
            "zscore(ts_mean(turnover_rate, 20))",
            "rank(abs(delta(close, 5)) / close)",
            "rank(1.0 / (pe_ttm + 1e-8))",
            "(close - open) / (open + 1e-10)",  # open as OHLCV field
        ]
        for expr in safe_exprs:
            result = sandbox.validate_expression(expr)
            assert result.is_valid, f"应该允许安全表达式: {expr!r}, errors={result.errors}"

    def test_execute_safely_returns_series(
        self, sandbox: FactorSandbox, simple_cross_section: pd.DataFrame
    ) -> None:
        result = sandbox.execute_safely("rank(close)", simple_cross_section)
        assert result.success
        assert result.result is not None
        assert isinstance(result.result, pd.Series)
        assert len(result.result) == len(simple_cross_section)

    def test_execute_blocks_dangerous_expression(
        self, sandbox: FactorSandbox, simple_cross_section: pd.DataFrame
    ) -> None:
        result = sandbox.execute_safely("eval('1+1')", simple_cross_section)
        assert not result.success

    def test_timeout_config(self) -> None:
        sb = FactorSandbox(timeout=2)
        assert sb.timeout == 2


# ===========================================================================
# BruteForce 引擎测试
# ===========================================================================


class TestBruteForceTemplates:
    """模板质量和完整性检查（成败标准之一）"""

    def test_template_count_at_least_30(self) -> None:
        assert len(FACTOR_TEMPLATES) >= 30, f"模板数量不足: {len(FACTOR_TEMPLATES)}"

    def test_all_templates_have_required_fields(self) -> None:
        for tpl in FACTOR_TEMPLATES:
            assert tpl.name, "模板name不能为空"
            assert tpl.category, f"模板 {tpl.name} 缺少category"
            assert tpl.economic_rationale, f"模板 {tpl.name} 缺少经济学假设"
            assert tpl.expr_template, f"模板 {tpl.name} 缺少expr_template"
            assert len(tpl.windows) > 0, f"模板 {tpl.name} 需要至少1个窗口"

    def test_all_templates_have_valid_direction(self) -> None:
        valid_directions = {"positive", "negative"}
        for tpl in FACTOR_TEMPLATES:
            assert tpl.direction in valid_directions, (
                f"无效方向 {tpl.direction!r}: {tpl.name}"
            )

    def test_all_templates_have_valid_category(self) -> None:
        valid_categories = {
            "price_volume", "liquidity", "flow",
            "fundamental", "cross_source", "conditional",
        }
        for tpl in FACTOR_TEMPLATES:
            assert tpl.category in valid_categories, (
                f"无效类别 {tpl.category!r}: {tpl.name}"
            )

    def test_all_templates_have_economic_rationale(self) -> None:
        """每个模板必须有有意义的经济学解释（不能是占位符）"""
        for tpl in FACTOR_TEMPLATES:
            assert len(tpl.economic_rationale.strip()) >= 10, (
                f"经济学假设过短: {tpl.name!r}"
            )

    def test_category_coverage_required(self) -> None:
        """至少覆盖价量、流动性、基本面三大类"""
        categories = {tpl.category for tpl in FACTOR_TEMPLATES}
        required = {"price_volume", "liquidity", "fundamental"}
        missing = required - categories
        assert not missing, f"缺少类别: {missing}"

    def test_flow_category_present(self) -> None:
        """资金流向类（设计文档最大缺口）必须有模板"""
        flow = [t for t in FACTOR_TEMPLATES if t.category == "flow"]
        assert len(flow) >= 2, f"资金流向类模板不足: {len(flow)}"

    def test_no_duplicate_template_names(self) -> None:
        names = [tpl.name for tpl in FACTOR_TEMPLATES]
        assert len(names) == len(set(names)), "存在重复模板名"


class TestBruteForceEngine:
    """BruteForce引擎展开和接口测试"""

    def test_enumerate_candidates_count(self) -> None:
        """展开后候选数量 >= 50（成败标准）"""
        engine = BruteForceEngine()
        candidates = engine.enumerate_candidates()
        assert len(candidates) >= 50, f"候选数量不足: {len(candidates)}"

    def test_enumerate_candidates_unique_names(self) -> None:
        engine = BruteForceEngine()
        candidates = engine.enumerate_candidates()
        names = [c.name for c in candidates]
        assert len(names) == len(set(names)), "存在重复候选名"

    def test_enumerate_candidates_returns_factor_candidate(self) -> None:
        engine = BruteForceEngine()
        for c in engine.enumerate_candidates():
            assert isinstance(c, FactorCandidate)
            assert c.expression, f"候选 {c.name} 表达式为空"
            assert c.economic_rationale, f"候选 {c.name} 缺少经济学假设"

    def test_enumerate_candidates_custom_templates(self) -> None:
        """自定义模板列表时只展开指定模板"""
        engine = BruteForceEngine()
        custom = [FACTOR_TEMPLATES[0]]
        candidates = engine.enumerate_candidates(templates=custom)
        n_windows = len(FACTOR_TEMPLATES[0].windows)
        assert len(candidates) == n_windows

    def test_all_template_expressions_pass_ast_safety_check(self) -> None:
        """所有模板展开后的表达式必须通过 AST 安全检查（成败标准）"""
        engine = BruteForceEngine()
        sb = FactorSandbox()
        failed = []
        for c in engine.enumerate_candidates():
            r = sb.validate_expression(c.expression)
            if not r.is_valid:
                failed.append((c.name, c.expression, r.errors))
        assert not failed, "以下表达式未通过AST检查:\n" + "\n".join(
            f"  {n}: {e} → {errs}" for n, e, errs in failed[:5]
        )

    def test_engine_default_gate_thresholds(self) -> None:
        engine = BruteForceEngine()
        assert engine.g1_ic_threshold == 0.015
        assert engine.g2_corr_threshold == 0.7
        assert engine.g3_t_threshold == 2.0

    def test_engine_custom_gate_thresholds(self) -> None:
        engine = BruteForceEngine(g1_ic_threshold=0.02, g3_t_threshold=2.5)
        assert engine.g1_ic_threshold == 0.02
        assert engine.g3_t_threshold == 2.5

    def test_factor_candidate_passed_all_property(self) -> None:
        c = FactorCandidate(
            name="test", category="price_volume", direction="negative",
            expression="rank(close)", window=20, economic_rationale="test",
            academic_support=3, passed_g1=True, passed_g2=True, passed_g3=True,
        )
        assert c.passed_all

        c2 = FactorCandidate(
            name="test2", category="price_volume", direction="negative",
            expression="rank(close)", window=20, economic_rationale="test",
            academic_support=3, passed_g1=True, passed_g2=False, passed_g3=True,
        )
        assert not c2.passed_all


# ===========================================================================
# ASTDeduplicator 测试
# ===========================================================================


class TestASTDeduplicator:
    """ASTDeduplicator: 规范化、哈希、去重（成败标准之一）"""

    # --- 规范化 ---

    def test_normalize_ast_returns_ast(self, dedup: ASTDeduplicator) -> None:
        import ast as ast_mod

        tree = dedup.normalize_ast("rank(close + volume)")
        assert tree is not None
        assert isinstance(tree, ast_mod.AST)

    def test_normalize_ast_returns_none_on_syntax_error(
        self, dedup: ASTDeduplicator
    ) -> None:
        result = dedup.normalize_ast("rank(close +")
        assert result is None

    # --- 哈希稳定性 ---

    def test_hash_is_stable(self, dedup: ASTDeduplicator) -> None:
        expr = "rank(close / delay(close, 20))"
        assert dedup.ast_hash(expr) == dedup.ast_hash(expr)

    def test_hash_different_for_different_exprs(self, dedup: ASTDeduplicator) -> None:
        assert dedup.ast_hash("rank(close)") != dedup.ast_hash("rank(volume)")

    def test_hash_returns_16_chars(self, dedup: ASTDeduplicator) -> None:
        h = dedup.ast_hash("rank(close)")
        assert len(h) == 16

    # --- 交换律等价（成败标准）---

    def test_addition_commutativity(self, dedup: ASTDeduplicator) -> None:
        """a + b 与 b + a 应被识别为等价（成败标准）"""
        assert dedup.are_equivalent("close + volume", "volume + close")

    def test_multiplication_commutativity(self, dedup: ASTDeduplicator) -> None:
        """a * b 与 b * a 应被识别为等价（成败标准）"""
        assert dedup.are_equivalent("close * volume", "volume * close")

    def test_subtraction_not_commutative(self, dedup: ASTDeduplicator) -> None:
        assert not dedup.are_equivalent("close - volume", "volume - close")

    def test_division_not_commutative(self, dedup: ASTDeduplicator) -> None:
        assert not dedup.are_equivalent("close / volume", "volume / close")

    # --- 常数折叠 ---

    def test_constant_folding_add(self, dedup: ASTDeduplicator) -> None:
        assert dedup.are_equivalent("rank(close + (2 + 3))", "rank(close + 5)")

    def test_constant_folding_multiply(self, dedup: ASTDeduplicator) -> None:
        assert dedup.are_equivalent("rank(close * (2 * 3))", "rank(close * 6)")

    # --- 不同表达式不应误判等价 ---

    def test_different_functions_not_equal(self, dedup: ASTDeduplicator) -> None:
        assert not dedup.are_equivalent("ts_mean(close, 20)", "ts_std(close, 20)")

    def test_different_windows_not_equal(self, dedup: ASTDeduplicator) -> None:
        assert not dedup.are_equivalent("ts_mean(close, 20)", "ts_mean(close, 40)")

    def test_rank_vs_zscore_not_equal(self, dedup: ASTDeduplicator) -> None:
        assert not dedup.are_equivalent("rank(close)", "zscore(close)")

    # --- 批量去重（成败标准）---

    def test_deduplicate_empty_list(self, dedup: ASTDeduplicator) -> None:
        result = dedup.deduplicate([])
        assert isinstance(result, DedupResult)
        assert len(result.unique_expressions) == 0
        assert len(result.removed_expressions) == 0

    def test_deduplicate_no_duplicates(self, dedup: ASTDeduplicator) -> None:
        exprs = ["rank(close)", "rank(volume)", "zscore(close)"]
        result = dedup.deduplicate(exprs)
        assert len(result.unique_expressions) == 3
        assert len(result.removed_expressions) == 0

    def test_deduplicate_commutative_duplicates(self, dedup: ASTDeduplicator) -> None:
        """a+b 和 b+a 应被去重（成败标准）"""
        exprs = ["rank(close + volume)", "rank(volume + close)", "rank(close)"]
        result = dedup.deduplicate(exprs)
        assert len(result.unique_expressions) == 2, (
            f"期望2个唯一, 实际{len(result.unique_expressions)}: {result.unique_expressions}"
        )
        assert len(result.removed_expressions) == 1

    def test_deduplicate_keeps_first(self, dedup: ASTDeduplicator) -> None:
        exprs = ["rank(close + volume)", "rank(volume + close)"]
        result = dedup.deduplicate(exprs)
        assert result.unique_expressions[0] == "rank(close + volume)"

    def test_deduplicate_dedup_rate(self, dedup: ASTDeduplicator) -> None:
        exprs = ["rank(close + volume)", "rank(volume + close)", "zscore(close)"]
        result = dedup.deduplicate(exprs)
        assert result.n_input == 3
        assert result.n_output == 2
        assert abs(result.dedup_rate - 1 / 3) < 0.01

    def test_deduplicate_multiple_groups(self, dedup: ASTDeduplicator) -> None:
        exprs = [
            "rank(a + b)", "rank(b + a)",
            "rank(a * b)", "rank(b * a)",
        ]
        result = dedup.deduplicate(exprs)
        assert len(result.unique_expressions) == 2

    # --- 其他接口 ---

    def test_get_ast_structure_returns_string(self, dedup: ASTDeduplicator) -> None:
        s = dedup.get_ast_structure("rank(close)")
        assert isinstance(s, str)
        assert len(s) > 0

    def test_compute_ast_similarity_same_expr(self, dedup: ASTDeduplicator) -> None:
        sim = dedup.compute_ast_similarity("rank(close)", "rank(close)")
        assert sim == 1.0

    def test_compute_ast_similarity_different_expr(self, dedup: ASTDeduplicator) -> None:
        sim = dedup.compute_ast_similarity("rank(close)", "zscore(volume)")
        assert 0.0 <= sim <= 1.0
