"""BH-FDR多重检验校正 单元测试。

测试项:
1. get_cumulative_test_count: 正确解析FACTOR_TEST_REGISTRY.md表格行数
2. get_cumulative_test_count: 排除重复验证条目
3. get_cumulative_test_count: 文件不存在时raise FileNotFoundError
4. get_cumulative_test_count: 空文件raise ValueError
5. bh_fdr_adjusted_threshold: 数学正确性 threshold = alpha * rank / M
6. bh_fdr_adjusted_threshold: 参数校验（alpha范围、rank范围）
7. bh_fdr_check_significance: BH步进法正确性
8. bh_fdr_check_significance: 空输入返回空字典
9. set_registry_path: 测试注入路径功能
10. 与真实FACTOR_TEST_REGISTRY.md集成测试
"""

import pytest
from pathlib import Path
from textwrap import dedent

from engines.config_guard import (
    bh_fdr_adjusted_threshold,
    bh_fdr_check_significance,
    get_cumulative_test_count,
    set_registry_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_registry(tmp_path: Path) -> Path:
    """创建一个包含5个因子的样本注册表。"""
    content = dedent("""\
    # FACTOR_TEST_REGISTRY — 因子测试注册表

    > BH-FDR校正基础。

    | # | 因子名 | IC_mean | t-stat | p-value | 测试日期 | 批次 | 结果 | 原因 |
    |---|--------|---------|--------|---------|----------|------|------|------|
    | 1 | factor_a | +0.0500 | +5.00 | <0.001 | 2026-03-20 | Batch1 | PASS | 强因子 |
    | 2 | factor_b | +0.0300 | +3.00 | 0.003 | 2026-03-20 | Batch1 | PASS | 通过 |
    | 3 | factor_c | +0.0100 | +1.00 | 0.320 | 2026-03-20 | Batch1 | FAIL | IC不显著 |
    | 4 | factor_d | -0.0200 | -2.00 | 0.048 | 2026-03-21 | Batch2 | CONDITIONAL | 边界 |
    | 5 | factor_e | +0.0050 | +0.50 | 0.620 | 2026-03-21 | Batch2 | FAIL | 不显著 |
    """)
    p = tmp_path / "FACTOR_TEST_REGISTRY.md"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def registry_with_duplicates(tmp_path: Path) -> Path:
    """创建一个含重复验证条目的注册表。"""
    content = dedent("""\
    # FACTOR_TEST_REGISTRY

    | # | 因子名 | IC_mean | t-stat | p-value | 测试日期 | 批次 | 结果 | 原因 |
    |---|--------|---------|--------|---------|----------|------|------|------|
    | 1 | factor_a | +0.0500 | +5.00 | <0.001 | 2026-03-20 | Batch1 | PASS | 强因子 |
    | 2 | factor_b | +0.0300 | +3.00 | 0.003 | 2026-03-20 | Batch1 | PASS | 通过 |
    | 3 | factor_a (验证) | +0.0510 | +5.10 | <0.001 | 2026-03-21 | Batch2-验证 | PASS | 重复验证条目(见#1), 不计入独立测试 |
    """)
    p = tmp_path / "FACTOR_TEST_REGISTRY.md"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def empty_registry(tmp_path: Path) -> Path:
    """创建一个没有数据行的注册表。"""
    content = dedent("""\
    # FACTOR_TEST_REGISTRY

    | # | 因子名 | IC_mean | t-stat | p-value | 测试日期 | 批次 | 结果 | 原因 |
    |---|--------|---------|--------|---------|----------|------|------|------|
    """)
    p = tmp_path / "FACTOR_TEST_REGISTRY.md"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def reset_registry_path():
    """每个测试后重置全局注册表路径。"""
    yield
    set_registry_path(None)


# ---------------------------------------------------------------------------
# get_cumulative_test_count 测试
# ---------------------------------------------------------------------------

class TestGetCumulativeTestCount:
    """get_cumulative_test_count 测试。"""

    def test_counts_data_rows(self, sample_registry: Path) -> None:
        """正确统计5个数据行。"""
        count = get_cumulative_test_count(registry_path=sample_registry)
        assert count == 5

    def test_excludes_duplicate_verification(self, registry_with_duplicates: Path) -> None:
        """排除标注为'重复验证'或'不计入'的条目。"""
        count = get_cumulative_test_count(registry_path=registry_with_duplicates)
        assert count == 2  # 只有factor_a和factor_b，第3行被排除

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """文件不存在时raise FileNotFoundError。"""
        fake_path = tmp_path / "nonexistent.md"
        with pytest.raises(FileNotFoundError, match="未找到"):
            get_cumulative_test_count(registry_path=fake_path)

    def test_empty_table_raises(self, empty_registry: Path) -> None:
        """表格无数据行时raise ValueError。"""
        with pytest.raises(ValueError, match="未找到有效"):
            get_cumulative_test_count(registry_path=empty_registry)

    def test_set_registry_path_injection(self, sample_registry: Path) -> None:
        """通过set_registry_path注入路径后，无参调用也能读到。"""
        set_registry_path(sample_registry)
        count = get_cumulative_test_count()
        assert count == 5


# ---------------------------------------------------------------------------
# bh_fdr_adjusted_threshold 测试
# ---------------------------------------------------------------------------

class TestBhFdrAdjustedThreshold:
    """bh_fdr_adjusted_threshold 测试。"""

    def test_basic_calculation(self, sample_registry: Path) -> None:
        """threshold = alpha * rank / M。M=5, rank=1, alpha=0.05 → 0.01。"""
        threshold = bh_fdr_adjusted_threshold(
            alpha=0.05, rank=1, registry_path=sample_registry
        )
        assert threshold == pytest.approx(0.05 * 1 / 5, rel=1e-9)

    def test_rank_2(self, sample_registry: Path) -> None:
        """rank=2时，threshold = 0.05 * 2 / 5 = 0.02。"""
        threshold = bh_fdr_adjusted_threshold(
            alpha=0.05, rank=2, registry_path=sample_registry
        )
        assert threshold == pytest.approx(0.02, rel=1e-9)

    def test_rank_equals_m(self, sample_registry: Path) -> None:
        """rank=M时，threshold = alpha（最宽松）。"""
        threshold = bh_fdr_adjusted_threshold(
            alpha=0.05, rank=5, registry_path=sample_registry
        )
        assert threshold == pytest.approx(0.05, rel=1e-9)

    def test_different_alpha(self, sample_registry: Path) -> None:
        """alpha=0.10, rank=1, M=5 → 0.02。"""
        threshold = bh_fdr_adjusted_threshold(
            alpha=0.10, rank=1, registry_path=sample_registry
        )
        assert threshold == pytest.approx(0.10 / 5, rel=1e-9)

    def test_invalid_alpha_zero(self, sample_registry: Path) -> None:
        """alpha=0 raise ValueError。"""
        with pytest.raises(ValueError, match="alpha"):
            bh_fdr_adjusted_threshold(alpha=0, rank=1, registry_path=sample_registry)

    def test_invalid_alpha_one(self, sample_registry: Path) -> None:
        """alpha=1 raise ValueError。"""
        with pytest.raises(ValueError, match="alpha"):
            bh_fdr_adjusted_threshold(alpha=1, rank=1, registry_path=sample_registry)

    def test_invalid_alpha_negative(self, sample_registry: Path) -> None:
        """alpha=-0.05 raise ValueError。"""
        with pytest.raises(ValueError, match="alpha"):
            bh_fdr_adjusted_threshold(alpha=-0.05, rank=1, registry_path=sample_registry)

    def test_invalid_rank_zero(self, sample_registry: Path) -> None:
        """rank=0 raise ValueError。"""
        with pytest.raises(ValueError, match="rank"):
            bh_fdr_adjusted_threshold(alpha=0.05, rank=0, registry_path=sample_registry)

    def test_rank_exceeds_m(self, sample_registry: Path) -> None:
        """rank > M raise ValueError。"""
        with pytest.raises(ValueError, match="rank.*不能超过"):
            bh_fdr_adjusted_threshold(alpha=0.05, rank=100, registry_path=sample_registry)

    def test_m_increases_strictness(self, tmp_path: Path) -> None:
        """M越大，同一rank的阈值越严格。"""
        # M=5的注册表
        content_5 = dedent("""\
        # Registry
        | # | 因子名 | IC_mean | t-stat | p-value | 测试日期 | 批次 | 结果 | 原因 |
        |---|--------|---------|--------|---------|----------|------|------|------|
        | 1 | f1 | +0.05 | +5.0 | <0.001 | 2026-03-20 | B1 | PASS | ok |
        | 2 | f2 | +0.04 | +4.0 | 0.001 | 2026-03-20 | B1 | PASS | ok |
        | 3 | f3 | +0.03 | +3.0 | 0.003 | 2026-03-20 | B1 | PASS | ok |
        | 4 | f4 | +0.02 | +2.0 | 0.048 | 2026-03-20 | B1 | FAIL | ns |
        | 5 | f5 | +0.01 | +1.0 | 0.320 | 2026-03-20 | B1 | FAIL | ns |
        """)
        p5 = tmp_path / "reg5.md"
        p5.write_text(content_5, encoding="utf-8")

        # M=10的注册表
        rows = "\n".join(
            f"| {i} | f{i} | +0.01 | +1.0 | 0.5 | 2026-03-20 | B1 | FAIL | ns |"
            for i in range(1, 11)
        )
        content_10 = (
            "# Registry\n"
            "| # | 因子名 | IC_mean | t-stat | p-value | 测试日期 | 批次 | 结果 | 原因 |\n"
            "|---|--------|---------|--------|---------|----------|------|------|------|\n"
            + rows + "\n"
        )
        p10 = tmp_path / "reg10.md"
        p10.write_text(content_10, encoding="utf-8")

        t5 = bh_fdr_adjusted_threshold(alpha=0.05, rank=1, registry_path=p5)
        t10 = bh_fdr_adjusted_threshold(alpha=0.05, rank=1, registry_path=p10)

        # M=10的阈值更严格（更小）
        assert t10 < t5
        assert t5 == pytest.approx(0.01, rel=1e-9)    # 0.05/5
        assert t10 == pytest.approx(0.005, rel=1e-9)   # 0.05/10


# ---------------------------------------------------------------------------
# bh_fdr_check_significance 测试
# ---------------------------------------------------------------------------

class TestBhFdrCheckSignificance:
    """bh_fdr_check_significance BH步进法测试。"""

    def test_empty_input(self, sample_registry: Path) -> None:
        """空字典输入返回空字典。"""
        result = bh_fdr_check_significance({}, registry_path=sample_registry)
        assert result == {}

    def test_all_significant(self, sample_registry: Path) -> None:
        """所有p-value都极小时，全部通过。M=5, alpha=0.05。"""
        p_values = {
            "f1": 0.001,   # 阈值: 0.05*1/5=0.01 → pass
            "f2": 0.005,   # 阈值: 0.05*2/5=0.02 → pass
            "f3": 0.008,   # 阈值: 0.05*3/5=0.03 → pass
        }
        result = bh_fdr_check_significance(
            p_values, alpha=0.05, registry_path=sample_registry
        )
        assert all(result.values())
        assert len(result) == 3

    def test_none_significant(self, sample_registry: Path) -> None:
        """所有p-value都很大时，全部不通过。"""
        p_values = {
            "f1": 0.50,
            "f2": 0.80,
        }
        result = bh_fdr_check_significance(
            p_values, alpha=0.05, registry_path=sample_registry
        )
        assert not any(result.values())

    def test_partial_significance(self, sample_registry: Path) -> None:
        """部分通过的BH步进法验证。M=5, alpha=0.05。

        排序后:
        rank=1: f_a p=0.001, 阈值=0.05*1/5=0.01 → 0.001<=0.01 pass
        rank=2: f_b p=0.015, 阈值=0.05*2/5=0.02 → 0.015<=0.02 pass
        rank=3: f_c p=0.500, 阈值=0.05*3/5=0.03 → 0.500>0.03 fail

        max_passing_rank=2, 所以f_a和f_b通过，f_c不通过。
        """
        p_values = {
            "f_a": 0.001,
            "f_b": 0.015,
            "f_c": 0.500,
        }
        result = bh_fdr_check_significance(
            p_values, alpha=0.05, registry_path=sample_registry
        )
        assert result["f_a"] is True
        assert result["f_b"] is True
        assert result["f_c"] is False

    def test_bh_step_up_property(self, sample_registry: Path) -> None:
        """BH步进法的关键属性: 如果rank=k通过，则所有rank<k也通过。

        M=5, alpha=0.05:
        rank=1: p=0.002, 阈值=0.01 → pass
        rank=2: p=0.018, 阈值=0.02 → pass
        rank=3: p=0.025, 阈值=0.03 → pass
        rank=4: p=0.800, 阈值=0.04 → fail
        """
        p_values = {
            "f1": 0.002,
            "f2": 0.018,
            "f3": 0.025,
            "f4": 0.800,
        }
        result = bh_fdr_check_significance(
            p_values, alpha=0.05, registry_path=sample_registry
        )
        assert result["f1"] is True
        assert result["f2"] is True
        assert result["f3"] is True
        assert result["f4"] is False

    def test_single_factor(self, sample_registry: Path) -> None:
        """单因子测试。M=5, rank=1, 阈值=0.01。"""
        # p=0.005 < 0.01 → pass
        result = bh_fdr_check_significance(
            {"only_factor": 0.005}, alpha=0.05, registry_path=sample_registry
        )
        assert result["only_factor"] is True

        # p=0.02 > 0.01 → fail
        result = bh_fdr_check_significance(
            {"only_factor": 0.02}, alpha=0.05, registry_path=sample_registry
        )
        assert result["only_factor"] is False


# ---------------------------------------------------------------------------
# 与真实FACTOR_TEST_REGISTRY.md集成测试
# ---------------------------------------------------------------------------

class TestRealRegistry:
    """与项目根目录的FACTOR_TEST_REGISTRY.md集成测试。"""

    @pytest.fixture
    def real_registry(self) -> Path:
        """真实注册表路径。"""
        p = Path(__file__).resolve().parent.parent.parent / "FACTOR_TEST_REGISTRY.md"
        if not p.exists():
            pytest.skip("FACTOR_TEST_REGISTRY.md不存在，跳过集成测试")
        return p

    def test_real_registry_count_positive(self, real_registry: Path) -> None:
        """真实注册表的M值为正整数。"""
        count = get_cumulative_test_count(registry_path=real_registry)
        assert count > 0
        assert isinstance(count, int)

    def test_real_registry_count_range(self, real_registry: Path) -> None:
        """真实注册表M值在合理范围（当前约64-70）。"""
        count = get_cumulative_test_count(registry_path=real_registry)
        assert 50 <= count <= 200, f"M={count}不在预期范围[50, 200]"

    def test_real_registry_threshold_reasonable(self, real_registry: Path) -> None:
        """真实M下，rank=1的阈值在合理范围。

        M~67时，阈值 = 0.05/67 ≈ 0.000746
        """
        threshold = bh_fdr_adjusted_threshold(
            alpha=0.05, rank=1, registry_path=real_registry
        )
        assert 0.0001 < threshold < 0.005
