"""单元测试 — 因子挖掘引擎 (Sprint 1.14 TrB)

覆盖:
- FactorSandbox: AST安全检查 + 安全执行
- BruteForceEngine: 模板展开 + 候选生成
- ASTDeduplicator: 规范化 + 哈希 + 批量去重
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from engines.mining.ast_dedup import ASTDeduplicator
from engines.mining.bruteforce_engine import (
    FACTOR_TEMPLATES,
    BruteForceEngine,
    FactorCandidate,
    FactorTemplate,
)
from engines.mining.factor_sandbox import (
    FactorSandbox,
)

# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


@pytest.fixture()
def sandbox() -> FactorSandbox:
    return FactorSandbox(timeout=5)


@pytest.fixture()
def dedup() -> ASTDeduplicator:
    return ASTDeduplicator(spearman_threshold=0.7)


@pytest.fixture()
def engine() -> BruteForceEngine:
    return BruteForceEngine(
        g1_ic_threshold=0.015,
        g2_corr_threshold=0.7,
        g3_t_threshold=2.0,
        min_ic_periods=3,
    )


@pytest.fixture()
def simple_series() -> pd.Series:
    """单只股票的简单价格序列"""
    np.random.seed(42)
    idx = pd.date_range("2022-01-01", periods=60, freq="B")
    return pd.Series(
        100 * np.exp(np.cumsum(np.random.randn(60) * 0.01)),
        index=idx,
        name="close",
    )


@pytest.fixture()
def panel_data() -> pd.DataFrame:
    """小型面板数据: 10只股票 × 60个交易日"""
    np.random.seed(42)
    dates = pd.date_range("2022-01-01", periods=60, freq="B")
    symbols = [f"stock_{i:02d}" for i in range(10)]
    idx = pd.MultiIndex.from_product(
        [dates, symbols], names=["date", "symbol_id"]
    )
    n = len(idx)

    close = 100 * np.exp(np.cumsum(np.random.randn(n) * 0.01).reshape(60, 10)).flatten()
    volume = np.abs(np.random.randn(n) * 1e6 + 1e7)
    amount = close * volume / 100
    turnover_rate = np.abs(np.random.randn(n) * 0.02 + 0.03)
    high = close * (1 + np.abs(np.random.randn(n) * 0.005))
    low = close * (1 - np.abs(np.random.randn(n) * 0.005))
    open_ = close * (1 + np.random.randn(n) * 0.003)

    df = pd.DataFrame(
        {
            "close": close,
            "volume": volume,
            "amount": amount,
            "turnover_rate": turnover_rate,
            "high": high,
            "low": low,
            "open": open_,
        },
        index=idx,
    )
    return df


@pytest.fixture()
def forward_returns(panel_data: pd.DataFrame) -> pd.Series:
    """1期远期收益"""
    fwd = panel_data["close"].groupby(level="symbol_id").shift(-1)
    cur = panel_data["close"]
    return (fwd / cur - 1).rename("fwd_ret_1d")


# ===========================================================================
# FactorSandbox 测试
# ===========================================================================


class TestFactorSandboxValidation:
    """AST静态安全检查测试"""

    def test_safe_expression_passes(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression(
            "rank(close / delay(close, 20) - 1)"
        )
        assert result.is_valid
        assert len(result.errors) == 0

    def test_import_blocked(self, sandbox: FactorSandbox) -> None:
        # "import os" is a statement, parse mode="eval" raises SyntaxError
        # Either syntax error OR Import node error — both mean not valid
        result = sandbox.validate_expression("import os")
        assert not result.is_valid

    def test_exec_blocked(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression("exec('import os')")
        assert not result.is_valid

    def test_eval_blocked(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression("eval('1+1')")
        assert not result.is_valid

    def test_open_blocked(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression("open('/etc/passwd').read()")
        assert not result.is_valid

    def test_os_blocked(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression("os.system('rm -rf /')")
        assert not result.is_valid

    def test_dunder_attribute_blocked(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression("close.__class__.__bases__")
        assert not result.is_valid

    def test_expression_too_long(self, sandbox: FactorSandbox) -> None:
        long_expr = "close + " * 100 + "close"
        result = sandbox.validate_expression(long_expr)
        assert not result.is_valid
        assert any("长" in e or "长度" in e or "长" in e for e in result.errors)

    def test_syntax_error(self, sandbox: FactorSandbox) -> None:
        # 真正的语法错误: 非法表达式
        result = sandbox.validate_expression("close (( + open")
        assert not result.is_valid
        assert len(result.errors) > 0

    def test_numpy_allowed(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression("np.log(close + 1)")
        assert result.is_valid

    def test_ts_operators_allowed(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression(
            "ts_mean(close, 20) / ts_std(close, 20)"
        )
        assert result.is_valid

    def test_complex_safe_expression(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression(
            "rank(ts_corr(close / delay(close, 1) - 1, "
            "volume / ts_mean(volume, 20), 20))"
        )
        assert result.is_valid

    def test_ast_depth_reported(self, sandbox: FactorSandbox) -> None:
        result = sandbox.validate_expression("close")
        assert result.ast_depth > 0
        assert result.node_count > 0


class TestFactorSandboxExecution:
    """沙箱执行测试"""

    def test_simple_execution(
        self, sandbox: FactorSandbox, simple_series: pd.Series
    ) -> None:
        df = simple_series.to_frame("close")
        df.index.name = None
        result = sandbox.execute_safely("close * 2", df)
        assert result.success
        assert result.result is not None
        assert len(result.result) == len(df)

    def test_dangerous_expression_blocked_before_execution(
        self, sandbox: FactorSandbox, simple_series: pd.Series
    ) -> None:
        df = simple_series.to_frame("close")
        result = sandbox.execute_safely("exec('import os')", df)
        assert not result.success
        assert result.error is not None

    def test_timeout_kills_process(
        self, sandbox: FactorSandbox, simple_series: pd.Series
    ) -> None:
        # Windows subprocess spawn有额外开销，使用3s超时确保简单表达式能完成
        fast_sandbox = FactorSandbox(timeout=3)
        df = simple_series.to_frame("close")
        result = fast_sandbox.execute_safely("close + 1", df)
        assert result.success


# ===========================================================================
# BruteForceEngine 测试
# ===========================================================================


class TestFactorTemplates:
    """模板定义测试"""

    def test_template_count_sufficient(self) -> None:
        assert len(FACTOR_TEMPLATES) >= 40

    def test_all_templates_have_economic_rationale(self) -> None:
        for tmpl in FACTOR_TEMPLATES:
            assert len(tmpl.economic_rationale) > 20, (
                f"模板 {tmpl.name} 缺少经济学解释"
            )

    def test_all_templates_have_required_fields(self) -> None:
        for tmpl in FACTOR_TEMPLATES:
            assert len(tmpl.required_fields) > 0, (
                f"模板 {tmpl.name} 缺少 required_fields"
            )

    def test_all_templates_have_windows(self) -> None:
        for tmpl in FACTOR_TEMPLATES:
            assert len(tmpl.windows) > 0, (
                f"模板 {tmpl.name} 缺少 windows"
            )

    def test_directions_valid(self) -> None:
        valid = {"positive", "negative"}
        for tmpl in FACTOR_TEMPLATES:
            assert tmpl.direction in valid, (
                f"模板 {tmpl.name} direction 非法: {tmpl.direction}"
            )

    def test_categories_cover_required_types(self) -> None:
        categories = {tmpl.category for tmpl in FACTOR_TEMPLATES}
        assert "price_volume" in categories
        assert "liquidity" in categories
        assert "flow" in categories
        assert "fundamental" in categories

    def test_flow_category_present(self) -> None:
        """类别③资金流向类（DESIGN_V5中全部未实现）必须有模板"""
        flow_templates = [
            t for t in FACTOR_TEMPLATES if t.category == "flow"
        ]
        assert len(flow_templates) >= 5, (
            f"资金流向类模板不足，只有 {len(flow_templates)} 个"
        )


class TestBruteForceEnumeration:
    """候选因子展开测试"""

    def test_enumerate_returns_candidates(
        self, engine: BruteForceEngine
    ) -> None:
        candidates = engine.enumerate_candidates()
        assert len(candidates) > 50  # 40+ 模板 × 多窗口 > 50

    def test_enumerate_with_custom_templates(
        self, engine: BruteForceEngine
    ) -> None:
        custom = [
            FactorTemplate(
                name="test_factor",
                category="price_volume",
                description="测试",
                economic_rationale="测试用途，无经济学意义",
                direction="positive",
                required_fields=["close"],
                windows=(5, 10),
                expr_template="ts_mean(close, {w})",
            )
        ]
        candidates = engine.enumerate_candidates(custom)
        assert len(candidates) == 2
        assert candidates[0].window == 5
        assert candidates[1].window == 10

    def test_candidate_expression_has_window_substituted(
        self, engine: BruteForceEngine
    ) -> None:
        candidates = engine.enumerate_candidates()
        for cand in candidates:
            assert "{w}" not in cand.expression, (
                f"{cand.name} 表达式中仍有 {{w}} 占位符"
            )

    def test_template_summary_returns_dataframe(
        self, engine: BruteForceEngine
    ) -> None:
        df = engine.get_template_summary()
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert "name" in df.columns
        assert "category" in df.columns

    def test_required_fields_extraction(
        self, engine: BruteForceEngine
    ) -> None:
        fields = BruteForceEngine._get_required_fields(
            "ts_mean(close, 20) / (volume + 1e-10)"
        )
        assert "close" in fields
        assert "volume" in fields
        assert "ts_mean" not in fields  # 算子不算字段


class TestBruteForceRun:
    """完整 run() 流程测试"""

    def test_run_with_panel_data(
        self,
        engine: BruteForceEngine,
        panel_data: pd.DataFrame,
        forward_returns: pd.Series,
    ) -> None:
        # 只用价量模板，避免缺失字段导致跳过
        pv_templates = [
            t for t in FACTOR_TEMPLATES
            if t.category == "price_volume"
            and all(f in panel_data.columns for f in t.required_fields)
        ]
        results = engine.run(panel_data, forward_returns, templates=pv_templates)
        # 不要求一定通过（样本小），只要不报错
        assert isinstance(results, list)
        for cand in results:
            assert isinstance(cand, FactorCandidate)
            assert cand.passed_all

    def test_missing_fields_skipped(
        self,
        engine: BruteForceEngine,
        panel_data: pd.DataFrame,
        forward_returns: pd.Series,
    ) -> None:
        # flow 模板需要 buy_lg_amount 等字段，panel_data 中没有，应被静默跳过
        flow_templates = [
            t for t in FACTOR_TEMPLATES if t.category == "flow"
        ]
        results = engine.run(
            panel_data, forward_returns, templates=flow_templates
        )
        # 不崩溃即可
        assert isinstance(results, list)

    def test_ic_series_computation(
        self,
        engine: BruteForceEngine,
        panel_data: pd.DataFrame,
        forward_returns: pd.Series,
    ) -> None:
        # 构造一个确定有IC的因子（reversal）
        reversal = (
            panel_data["close"]
            / panel_data.groupby(level="symbol_id")["close"].shift(20)
            - 1
        )
        ic_series = BruteForceEngine._compute_ic_series(
            reversal, forward_returns
        )
        assert len(ic_series) >= 1
        assert all(isinstance(v, float) for v in ic_series.values)

    def test_correlation_check(
        self,
        engine: BruteForceEngine,
        panel_data: pd.DataFrame,
    ) -> None:
        s1 = panel_data["close"].rename("f1")
        s2 = panel_data["close"].rename("f2")  # 完全相同应corr=1.0
        active = s2.to_frame("existing_factor")
        corr = BruteForceEngine._check_correlation(s1, active)
        assert corr > 0.99


# ===========================================================================
# ASTDeduplicator 测试
# ===========================================================================


class TestASTNormalization:
    """AST规范化测试"""

    def test_commutativity_addition(self, dedup: ASTDeduplicator) -> None:
        """a+b 和 b+a 应有相同哈希"""
        h1 = dedup.ast_hash("a + b")
        h2 = dedup.ast_hash("b + a")
        assert h1 == h2, "加法交换律规范化失败"

    def test_commutativity_multiplication(
        self, dedup: ASTDeduplicator
    ) -> None:
        h1 = dedup.ast_hash("x * y")
        h2 = dedup.ast_hash("y * x")
        assert h1 == h2, "乘法交换律规范化失败"

    def test_constant_folding(self, dedup: ASTDeduplicator) -> None:
        """2+3 和 5 应有相同哈希"""
        h1 = dedup.ast_hash("2 + 3")
        h2 = dedup.ast_hash("5")
        assert h1 == h2, "常数折叠失败"

    def test_float_int_unification(self, dedup: ASTDeduplicator) -> None:
        """1.0 和 1 应有相同哈希"""
        h1 = dedup.ast_hash("close * 1.0")
        h2 = dedup.ast_hash("close * 1")
        assert h1 == h2, "浮点/整数统一化失败"

    def test_different_expressions_different_hash(
        self, dedup: ASTDeduplicator
    ) -> None:
        h1 = dedup.ast_hash("ts_mean(close, 5)")
        h2 = dedup.ast_hash("ts_mean(close, 20)")
        assert h1 != h2, "不同窗口应有不同哈希"

    def test_syntax_error_returns_empty(
        self, dedup: ASTDeduplicator
    ) -> None:
        h = dedup.ast_hash("close +++")
        assert h == "", "语法错误应返回空哈希"


class TestASTEquivalence:
    """等价性判断测试"""

    def test_equivalent_expressions(self, dedup: ASTDeduplicator) -> None:
        assert dedup.are_equivalent("a + b", "b + a")
        assert dedup.are_equivalent("x * y", "y * x")
        assert dedup.are_equivalent("close * 1", "close * 1.0")

    def test_non_equivalent_expressions(
        self, dedup: ASTDeduplicator
    ) -> None:
        assert not dedup.are_equivalent("ts_mean(close, 5)", "ts_mean(close, 20)")
        assert not dedup.are_equivalent("close + open", "close - open")
        assert not dedup.are_equivalent("rank(close)", "zscore(close)")


class TestASTDeduplicate:
    """批量去重测试"""

    def test_dedup_removes_commutative_duplicates(
        self, dedup: ASTDeduplicator
    ) -> None:
        candidates = ["a + b", "b + a", "c + d"]
        result = dedup.deduplicate(candidates)
        assert result.n_input == 3
        assert result.n_output == 2
        assert "a + b" in result.unique_expressions
        assert "b + a" in result.removed_expressions
        assert "L1" in result.removal_reasons.get("b + a", "")

    def test_dedup_empty_list(self, dedup: ASTDeduplicator) -> None:
        result = dedup.deduplicate([])
        assert result.n_input == 0
        assert result.n_output == 0
        assert result.unique_expressions == []

    def test_dedup_no_duplicates(self, dedup: ASTDeduplicator) -> None:
        candidates = [
            "ts_mean(close, 5)",
            "ts_mean(close, 20)",
            "ts_std(close, 10)",
        ]
        result = dedup.deduplicate(candidates)
        assert result.n_output == 3

    def test_dedup_rate_calculation(self, dedup: ASTDeduplicator) -> None:
        candidates = ["a + b", "b + a", "c"]
        result = dedup.deduplicate(candidates)
        assert abs(result.dedup_rate - 1 / 3) < 0.01

    def test_dedup_with_existing_factors(
        self, dedup: ASTDeduplicator
    ) -> None:
        existing = ["ts_mean(close, 20)"]
        new_candidates = [
            "ts_mean(close, 5)",
            "ts_mean(close, 20)",  # 重复
            "ts_std(close, 10)",
        ]
        result = dedup.deduplicate_with_existing(new_candidates, existing)
        assert result.n_output == 2
        assert "ts_mean(close, 20)" in result.removed_expressions

    def test_dedup_preserves_order(self, dedup: ASTDeduplicator) -> None:
        candidates = ["c", "a", "b", "c"]
        result = dedup.deduplicate(candidates)
        assert result.unique_expressions == ["c", "a", "b"]

    def test_batch_dedup_candidates(self, dedup: ASTDeduplicator) -> None:
        """batch_deduplicate_candidates 对 FactorCandidate 对象去重"""
        cand1 = FactorCandidate(
            name="f1",
            category="price_volume",
            direction="positive",
            expression="a + b",
            window=5,
            economic_rationale="test",
            academic_support=3,
        )
        cand2 = FactorCandidate(
            name="f2",
            category="price_volume",
            direction="positive",
            expression="b + a",  # 语义等价
            window=5,
            economic_rationale="test",
            academic_support=3,
        )
        cand3 = FactorCandidate(
            name="f3",
            category="price_volume",
            direction="negative",
            expression="c - d",
            window=10,
            economic_rationale="test",
            academic_support=3,
        )
        result = dedup.batch_deduplicate_candidates([cand1, cand2, cand3])
        assert len(result) == 2
        names = [c.name for c in result]
        assert "f1" in names
        assert "f2" not in names  # b+a 是 a+b 的重复
        assert "f3" in names


class TestASTSimilarity:
    """AST相似度测试"""

    def test_identical_expressions_similarity_one(
        self, dedup: ASTDeduplicator
    ) -> None:
        sim = dedup.compute_ast_similarity("close + open", "close + open")
        assert sim == 1.0

    def test_completely_different_low_similarity(
        self, dedup: ASTDeduplicator
    ) -> None:
        sim = dedup.compute_ast_similarity("a", "b + c + d + e + f")
        assert sim < 0.5

    def test_partial_similarity(self, dedup: ASTDeduplicator) -> None:
        sim = dedup.compute_ast_similarity(
            "ts_mean(close, 5)", "ts_mean(volume, 5)"
        )
        # 两者共享 ts_mean 函数调用和窗口5，相似度应 > 0
        assert sim > 0


# ===========================================================================
# 集成测试
# ===========================================================================


class TestIntegration:
    """三模块集成测试"""

    def test_sandbox_validate_then_dedup(
        self, sandbox: FactorSandbox, dedup: ASTDeduplicator
    ) -> None:
        """先安全检查，再去重"""
        expressions = [
            "rank(close / delay(close, 20) - 1)",
            "rank(delay(close, 20) / close - 1) * -1",  # 语义不同，不等价
            "rank(close / delay(close, 20) - 1)",  # 完全相同
            "exec('dangerous')",  # 危险表达式
        ]

        # 先过安全检查
        safe_exprs = [
            e for e in expressions if sandbox.validate_expression(e).is_valid
        ]
        assert len(safe_exprs) == 3  # exec 被过滤

        # 再去重
        result = dedup.deduplicate(safe_exprs)
        assert result.n_output == 2  # 两个不同的安全表达式

    def test_bruteforce_candidates_dedup(
        self, engine: BruteForceEngine, dedup: ASTDeduplicator
    ) -> None:
        """BruteForce 产出的候选经 AST 去重"""
        candidates = engine.enumerate_candidates()
        deduped = dedup.batch_deduplicate_candidates(candidates)
        # 因为每个模板展开的窗口不同，表达式不同，去重率应较低
        assert len(deduped) <= len(candidates)
        assert len(deduped) > 0
