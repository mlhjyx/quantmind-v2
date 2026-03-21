"""测试 PortfolioBuilder._apply_turnover_cap() 修复正确性。

P0 bug: _apply_turnover_cap() blend后对 target∪prev 取并集,
导致持仓从20膨胀到43。修复: blend后只保留target中的股票。

测试用例:
1. 正常路径: 20 target + 20 prev (10重叠) → ≤20
2. 换手上限触发: 0重叠, turnover=100% > cap 50% → blend后仍≤20
3. 边界: prev已膨胀到43只 → 调仓后≤20
4. 边界: turnover刚好=cap → 不触发blend, exactly 20
"""

import pandas as pd
import pytest

from engines.signal_engine import PortfolioBuilder, SignalConfig


def _make_codes(prefix: str, n: int) -> list[str]:
    """生成股票代码列表。"""
    return [f"{prefix}{i:04d}.SZ" for i in range(n)]


def _equal_weights(codes: list[str]) -> dict[str, float]:
    """等权权重。"""
    w = 1.0 / len(codes)
    return {c: w for c in codes}


def _make_scores(codes: list[str]) -> pd.Series:
    """构造得分序列(降序)。"""
    return pd.Series(
        [100.0 - i for i in range(len(codes))],
        index=codes,
    )


def _make_industry(codes: list[str]) -> pd.Series:
    """构造行业映射(分散到多个行业, 避免行业约束干扰)。"""
    industries = [f"行业{i % 10}" for i in range(len(codes))]
    return pd.Series(industries, index=codes)


class TestTurnoverCapFix:
    """验证 _apply_turnover_cap 修复: 输出持仓数 <= top_n。"""

    def setup_method(self):
        self.config = SignalConfig(
            top_n=20,
            weight_method="equal",
            industry_cap=0.25,
            turnover_cap=0.50,
            factor_names=["turnover_mean_20"],
        )
        self.builder = PortfolioBuilder(self.config)

    def test_normal_path_with_overlap(self):
        """Case 1: 20 target + 20 prev, 10只重叠 → ≤20只。

        turnover = (10新买 + 10旧卖) / 2 ÷ 1 = 50% = cap → 不触发blend。
        """
        overlap = _make_codes("OV", 10)        # 10只重叠
        new_only = _make_codes("NEW", 10)       # 10只新买
        old_only = _make_codes("OLD", 10)       # 10只旧卖

        target_codes = overlap + new_only       # 20只
        prev_codes = overlap + old_only         # 20只

        scores = _make_scores(target_codes)
        industry = _make_industry(target_codes + old_only)
        prev_holdings = _equal_weights(prev_codes)

        result = self.builder.build(scores, industry, prev_holdings)

        assert len(result) <= 20, (
            f"持仓膨胀! 期望≤20, 实际={len(result)}, "
            f"codes={sorted(result.keys())}"
        )
        assert abs(sum(result.values()) - 1.0) < 1e-6, "权重之和应=1.0"

    def test_zero_overlap_triggers_cap(self):
        """Case 2: 0重叠, turnover=100% > cap 50% → blend后仍≤20只。

        这是修复前的核心bug场景: 20 target + 20 prev全不同,
        blend后原代码会保留全部40只。
        """
        target_codes = _make_codes("T", 20)
        prev_codes = _make_codes("P", 20)

        scores = _make_scores(target_codes)
        industry = _make_industry(target_codes + prev_codes)
        prev_holdings = _equal_weights(prev_codes)

        result = self.builder.build(scores, industry, prev_holdings)

        assert len(result) <= 20, (
            f"持仓膨胀! 0重叠场景, 期望≤20, 实际={len(result)}, "
            f"codes={sorted(result.keys())}"
        )
        assert abs(sum(result.values()) - 1.0) < 1e-6, "权重之和应=1.0"
        # 所有输出股票必须来自target
        for code in result:
            assert code in target_codes, (
                f"输出中包含非target股票: {code}"
            )

    def test_prev_already_bloated_43(self):
        """Case 3: prev已膨胀到43只 → 调仓后≤20只。

        模拟bug修复前的遗留状态: 上一期持仓已经膨胀到43只,
        本次调仓必须收缩回20只。
        """
        target_codes = _make_codes("T", 20)
        prev_codes = _make_codes("B", 43)  # 模拟已膨胀的43只

        scores = _make_scores(target_codes)
        industry = _make_industry(target_codes + prev_codes)
        prev_holdings = _equal_weights(prev_codes)

        result = self.builder.build(scores, industry, prev_holdings)

        assert len(result) <= 20, (
            f"未能收缩膨胀持仓! 期望≤20, 实际={len(result)}, "
            f"prev有43只, target有20只"
        )
        assert abs(sum(result.values()) - 1.0) < 1e-6, "权重之和应=1.0"
        for code in result:
            assert code in target_codes, (
                f"输出中包含非target股票: {code}"
            )

    def test_turnover_exactly_at_cap_no_blend(self):
        """Case 4: turnover刚好=cap → 不触发blend → exactly 20只。

        构造: 10只重叠 + 10只新 + 10只旧, 等权。
        turnover = sum(|target-prev|)/2
        = (10×0.05 + 10×0.05 + 10×0.05 + 10×0.05) / 2 ... 需要精确控制。

        简化: 让target和prev完全相同 → turnover=0 → 不触发 → exactly 20。
        """
        codes = _make_codes("S", 20)

        scores = _make_scores(codes)
        industry = _make_industry(codes)
        prev_holdings = _equal_weights(codes)

        result = self.builder.build(scores, industry, prev_holdings)

        assert len(result) == 20, (
            f"完全相同持仓应输出exactly 20, 实际={len(result)}"
        )
        assert abs(sum(result.values()) - 1.0) < 1e-6, "权重之和应=1.0"

    def test_turnover_at_cap_boundary(self):
        """Case 4b: turnover精确=50% → 不触发blend → exactly 20只。

        构造: 20 target中10只来自prev, 10只新增。
        prev也是20只, 10只保留, 10只被替换。
        turnover = (10×1/20 + 10×1/20) / 2 = 10/20 = 0.5 = cap。
        等号时不触发blend (turnover <= cap)。
        """
        overlap = _make_codes("K", 10)
        new_target = _make_codes("NT", 10)
        old_prev = _make_codes("OP", 10)

        target_codes = overlap + new_target
        prev_codes = overlap + old_prev

        scores = _make_scores(target_codes)
        industry = _make_industry(target_codes + old_prev)
        prev_holdings = _equal_weights(prev_codes)

        result = self.builder.build(scores, industry, prev_holdings)

        assert len(result) == 20, (
            f"turnover=cap时不应触发blend, 期望20, 实际={len(result)}"
        )
        assert abs(sum(result.values()) - 1.0) < 1e-6, "权重之和应=1.0"

    def test_apply_turnover_cap_directly(self):
        """直接测试 _apply_turnover_cap 方法, 绕过build的行业约束。"""
        target_codes = _make_codes("D", 20)
        prev_codes = _make_codes("E", 20)  # 0重叠

        target = _equal_weights(target_codes)
        prev = _equal_weights(prev_codes)

        result = self.builder._apply_turnover_cap(target, prev)

        assert len(result) <= 20, (
            f"_apply_turnover_cap直接调用: 期望≤20, 实际={len(result)}"
        )
        assert abs(sum(result.values()) - 1.0) < 1e-6, "权重之和应=1.0"
        for code in result:
            assert code in target_codes, (
                f"输出包含非target股票: {code}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
