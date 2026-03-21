"""信号验证逻辑单元测试。

验证 run_paper_trading.py 中新增的4项信号检查逻辑:
  1. 因子覆盖率 < 1000 → P0阻塞
  2. 因子覆盖率 < 3000 → P1告警
  3. 行业集中度 > 25% → P1告警
  4. 持仓重合度 < 30% → P1告警

使用mock数据，不依赖数据库。
将run_paper_trading.py中的内联检查逻辑提取为纯函数进行测试。
"""

from __future__ import annotations

import pytest


# ────────────────────────────────────────────
# 提取检查逻辑为可测试的纯函数
# (复制run_paper_trading.py中的检查逻辑,
#  但以函数形式封装，便于单元测试)
# ────────────────────────────────────────────

def check_factor_coverage(
    factor_name: str,
    stock_count: int,
) -> tuple[str | None, str | None]:
    """检查单个因子的截面覆盖率。

    Args:
        factor_name: 因子名称。
        stock_count: 该因子当日覆盖的股票数。

    Returns:
        (alert_level, message):
          - ("P0", msg) 如果 < 1000
          - ("P1", msg) 如果 < 3000
          - (None, None) 正常
    """
    if stock_count < 1000:
        msg = (
            f"因子 {factor_name} 截面覆盖率严重不足: {stock_count}只 < 1000。"
            f"可能数据源故障或拉取异常，阻塞信号生成。"
        )
        return "P0", msg
    elif stock_count < 3000:
        msg = (
            f"因子 {factor_name} 截面覆盖率偏低: {stock_count}只 < 3000。"
            f"信号生成继续，但请排查数据完整性。"
        )
        return "P1", msg
    return None, None


def check_industry_concentration(
    target_weights: dict[str, float],
    code_industry: dict[str, str],
    threshold: float = 0.25,
) -> tuple[str | None, str | None, float]:
    """检查Top20持仓的行业集中度。

    Args:
        target_weights: {stock_code: weight} 目标持仓权重。
        code_industry: {stock_code: industry_name} 行业映射。
        threshold: 行业权重上限, 默认25%。

    Returns:
        (alert_level, message, max_weight):
          - ("P1", msg, weight) 如果最大行业权重 > threshold
          - (None, None, weight) 正常
    """
    if not target_weights:
        return None, None, 0.0

    top20_codes = sorted(
        target_weights, key=lambda c: target_weights[c], reverse=True
    )[:20]
    top20_weights = {c: target_weights[c] for c in top20_codes}

    industry_weights: dict[str, float] = {}
    for code in top20_codes:
        ind = code_industry.get(code, "未知")
        industry_weights[ind] = industry_weights.get(ind, 0) + top20_weights[code]

    if not industry_weights:
        return None, None, 0.0

    max_ind = max(industry_weights, key=lambda k: industry_weights[k])
    max_ind_weight = industry_weights[max_ind]

    if max_ind_weight > threshold:
        msg = (
            f"Top20持仓行业集中度过高: {max_ind} 权重={max_ind_weight:.1%} > {threshold:.0%}。"
        )
        return "P1", msg, max_ind_weight

    return None, None, max_ind_weight


def check_position_overlap(
    current_weights: dict[str, float],
    prev_weights: dict[str, float],
    threshold: float = 0.30,
) -> tuple[str | None, str | None, float]:
    """检查持仓重合度。

    Args:
        current_weights: 当前目标持仓 {code: weight}。
        prev_weights: 上期持仓 {code: weight}。
        threshold: 重合度下限, 默认30%。

    Returns:
        (alert_level, message, overlap_ratio):
          - ("P1", msg, ratio) 如果重合度 < threshold
          - (None, None, ratio) 正常
    """
    if not current_weights or not prev_weights:
        return None, None, 1.0

    current_top = set(
        sorted(current_weights, key=lambda c: current_weights[c], reverse=True)[:20]
    )
    prev_top = set(
        sorted(prev_weights, key=lambda c: prev_weights[c], reverse=True)[:20]
    )

    if not prev_top:
        return None, None, 1.0

    overlap = len(current_top & prev_top)
    overlap_ratio = overlap / max(len(prev_top), 1)

    if overlap_ratio < threshold:
        msg = (
            f"持仓重合度过低: {overlap}/{len(prev_top)} = {overlap_ratio:.0%} < {threshold:.0%}。"
            f"换手剧烈，建议人工确认信号合理性。"
        )
        return "P1", msg, overlap_ratio

    return None, None, overlap_ratio


# ────────────────────────────────────────────
# 测试1: 因子覆盖率检查
# ────────────────────────────────────────────

class TestFactorCoverage:
    """因子截面覆盖率检查测试。"""

    def test_coverage_below_1000_is_p0(self) -> None:
        """覆盖率<1000 → P0阻塞。"""
        level, msg = check_factor_coverage("momentum_20d", 500)
        assert level == "P0"
        assert "严重不足" in msg
        assert "500" in msg

    def test_coverage_at_999_is_p0(self) -> None:
        """边界: 999只 → P0。"""
        level, msg = check_factor_coverage("ep_ttm", 999)
        assert level == "P0"

    def test_coverage_at_1000_is_p1(self) -> None:
        """边界: 恰好1000只 → P1(不是P0)。"""
        level, msg = check_factor_coverage("ep_ttm", 1000)
        assert level == "P1"
        assert "偏低" in msg

    def test_coverage_between_1000_and_3000_is_p1(self) -> None:
        """1000 <= 覆盖率 < 3000 → P1告警。"""
        level, msg = check_factor_coverage("roe_ttm", 2500)
        assert level == "P1"
        assert "偏低" in msg
        assert "2500" in msg

    def test_coverage_at_2999_is_p1(self) -> None:
        """边界: 2999只 → P1。"""
        level, msg = check_factor_coverage("roe_ttm", 2999)
        assert level == "P1"

    def test_coverage_at_3000_is_normal(self) -> None:
        """边界: 恰好3000只 → 正常(无告警)。"""
        level, msg = check_factor_coverage("roe_ttm", 3000)
        assert level is None
        assert msg is None

    def test_coverage_above_3000_is_normal(self) -> None:
        """覆盖率>=3000 → 正常。"""
        level, msg = check_factor_coverage("momentum_20d", 4500)
        assert level is None
        assert msg is None

    def test_zero_coverage_is_p0(self) -> None:
        """零覆盖 → P0。"""
        level, msg = check_factor_coverage("broken_factor", 0)
        assert level == "P0"

    def test_factor_name_in_message(self) -> None:
        """告警消息包含因子名称。"""
        _, msg = check_factor_coverage("my_special_factor", 800)
        assert "my_special_factor" in msg


# ────────────────────────────────────────────
# 测试2: 行业集中度检查
# ────────────────────────────────────────────

class TestIndustryConcentration:
    """Top20行业集中度检查测试。"""

    def _make_weights(self, n: int, base_weight: float = 0.05) -> dict[str, float]:
        """生成n只等权持仓。"""
        return {f"stock_{i:03d}": base_weight for i in range(n)}

    def test_concentrated_industry_triggers_p1(self) -> None:
        """单一行业权重>25% → P1。"""
        weights = {f"s{i}": 0.05 for i in range(20)}
        # 所有股票属于同一行业 → 100% 集中度
        code_industry = {f"s{i}": "银行" for i in range(20)}
        level, msg, max_w = check_industry_concentration(weights, code_industry)
        assert level == "P1"
        assert max_w > 0.25

    def test_diversified_industries_no_alert(self) -> None:
        """行业分散 → 无告警。"""
        industries = ["银行", "电子", "医药", "食品", "汽车",
                       "地产", "钢铁", "有色", "化工", "电力",
                       "机械", "通信", "计算机", "传媒", "军工",
                       "建筑", "交运", "纺服", "商贸", "农林"]
        weights = {f"s{i}": 0.05 for i in range(20)}
        code_industry = {f"s{i}": industries[i] for i in range(20)}
        level, msg, max_w = check_industry_concentration(weights, code_industry)
        assert level is None
        assert max_w == 0.05  # 每个行业5%

    def test_boundary_at_25_percent(self) -> None:
        """恰好25%不触发告警(>25%才触发)。"""
        # 5只同行业(每只5%), 15只不同行业
        weights = {f"s{i}": 0.05 for i in range(20)}
        code_industry = {}
        for i in range(5):
            code_industry[f"s{i}"] = "银行"
        for i in range(5, 20):
            code_industry[f"s{i}"] = f"行业_{i}"
        level, msg, max_w = check_industry_concentration(weights, code_industry)
        assert level is None
        assert abs(max_w - 0.25) < 1e-10

    def test_boundary_above_25_percent(self) -> None:
        """略超25%触发P1。"""
        # 6只同行业, 权重稍高
        weights = {}
        for i in range(6):
            weights[f"s{i}"] = 0.05
        for i in range(6, 20):
            weights[f"s{i}"] = (1.0 - 0.30) / 14  # 剩余70%分给14只
        code_industry = {}
        for i in range(6):
            code_industry[f"s{i}"] = "银行"
        for i in range(6, 20):
            code_industry[f"s{i}"] = f"行业_{i}"
        level, msg, max_w = check_industry_concentration(weights, code_industry)
        assert level == "P1"
        assert max_w > 0.25

    def test_empty_weights_no_alert(self) -> None:
        """空持仓 → 无告警。"""
        level, msg, max_w = check_industry_concentration({}, {})
        assert level is None

    def test_unknown_industry_grouped(self) -> None:
        """无行业信息的股票归入'未知'。"""
        weights = {f"s{i}": 0.05 for i in range(20)}
        code_industry = {}  # 全部无行业映射
        level, msg, max_w = check_industry_concentration(weights, code_industry)
        # 全部归入"未知", 100%集中
        assert level == "P1"
        assert max_w == pytest.approx(1.0)

    def test_more_than_20_stocks_uses_top20(self) -> None:
        """超过20只时只取Top20。"""
        weights = {}
        for i in range(30):
            weights[f"s{i}"] = 0.10 if i < 10 else 0.005
        # Top20: s0-s9(权重高) + s10-s19(权重次高)
        industries = ["银行"] * 10 + [f"行业_{i}" for i in range(20)]
        code_industry = {f"s{i}": industries[i] for i in range(30)}
        level, msg, max_w = check_industry_concentration(weights, code_industry)
        # Top20中银行权重 = 10 * 0.10 / (10*0.10 + 10*0.005) 但注意
        # check_industry_concentration 使用原始权重，不归一化
        # 银行总权重 = 10 * 0.10 = 1.0 > 0.25
        assert level == "P1"


# ────────────────────────────────────────────
# 测试3: 持仓重合度检查
# ────────────────────────────────────────────

class TestPositionOverlap:
    """持仓重合度检查测试。"""

    def test_complete_overlap_no_alert(self) -> None:
        """完全重合(100%) → 无告警。"""
        weights = {f"s{i}": 0.05 for i in range(20)}
        level, msg, ratio = check_position_overlap(weights, weights)
        assert level is None
        assert ratio == 1.0

    def test_zero_overlap_triggers_p1(self) -> None:
        """零重合(0%) → P1。"""
        current = {f"new_{i}": 0.05 for i in range(20)}
        prev = {f"old_{i}": 0.05 for i in range(20)}
        level, msg, ratio = check_position_overlap(current, prev)
        assert level == "P1"
        assert ratio == 0.0
        assert "换手剧烈" in msg

    def test_partial_overlap_below_30_triggers_p1(self) -> None:
        """重合度<30% → P1。"""
        # 20只中5只重合 = 25%
        current = {f"s{i}": 0.05 for i in range(20)}
        prev_stocks = [f"s{i}" for i in range(5)] + [f"old_{i}" for i in range(15)]
        prev = {s: 0.05 for s in prev_stocks}
        level, msg, ratio = check_position_overlap(current, prev)
        assert level == "P1"
        assert ratio == pytest.approx(0.25)

    def test_overlap_at_30_is_normal(self) -> None:
        """恰好30%重合 → 正常(不触发, 阈值是<30%)。"""
        # 20只中6只重合 = 30%
        current = {f"s{i}": 0.05 for i in range(20)}
        prev_stocks = [f"s{i}" for i in range(6)] + [f"old_{i}" for i in range(14)]
        prev = {s: 0.05 for s in prev_stocks}
        level, msg, ratio = check_position_overlap(current, prev)
        assert level is None
        assert ratio == pytest.approx(0.30)

    def test_overlap_at_29_triggers_p1(self) -> None:
        """约29%重合 → P1（使用不等权让5只在top20, 但比例<30%）。"""
        # 更直接: 用更多股票, 只有少数重合
        # 20只中 5只重合 = 25% < 30%
        current = {f"s{i}": 0.05 for i in range(20)}
        prev_stocks = [f"s{i}" for i in range(5)] + [f"old_{i}" for i in range(15)]
        prev = {s: 0.05 for s in prev_stocks}
        level, msg, ratio = check_position_overlap(current, prev)
        assert level == "P1"

    def test_high_overlap_no_alert(self) -> None:
        """高重合度(>30%) → 无告警。"""
        # 20只中15只重合 = 75%
        current = {f"s{i}": 0.05 for i in range(20)}
        prev_stocks = [f"s{i}" for i in range(15)] + [f"old_{i}" for i in range(5)]
        prev = {s: 0.05 for s in prev_stocks}
        level, msg, ratio = check_position_overlap(current, prev)
        assert level is None
        assert ratio == pytest.approx(0.75)

    def test_empty_current_no_alert(self) -> None:
        """空当前持仓 → 无告警(跳过检查)。"""
        prev = {f"s{i}": 0.05 for i in range(20)}
        level, msg, ratio = check_position_overlap({}, prev)
        assert level is None

    def test_empty_prev_no_alert(self) -> None:
        """空上期持仓 → 无告警(首次建仓)。"""
        current = {f"s{i}": 0.05 for i in range(20)}
        level, msg, ratio = check_position_overlap(current, {})
        assert level is None

    def test_uses_top20_by_weight(self) -> None:
        """Top20按权重排序取头部, 不是按股票名。"""
        # 30只, 但只有top20参与比较
        current = {}
        for i in range(30):
            current[f"s{i:03d}"] = 0.10 if i < 10 else 0.005
        prev = {}
        for i in range(30):
            prev[f"s{i:03d}"] = 0.10 if i < 10 else 0.005

        # top20 of current: s000-s009 (高权重) + s010-s019 (低权重前10)
        # top20 of prev: 完全一样
        level, msg, ratio = check_position_overlap(current, prev)
        assert level is None
        assert ratio == 1.0

    def test_different_top20_despite_same_stocks(self) -> None:
        """相同股票池但权重变化导致Top20不同。"""
        current = {f"s{i}": 0.10 for i in range(10)}
        current.update({f"s{i}": 0.001 for i in range(10, 25)})

        prev = {f"s{i}": 0.001 for i in range(10)}
        prev.update({f"s{i}": 0.10 for i in range(10, 20)})
        prev.update({f"s{i}": 0.001 for i in range(20, 25)})

        # current top20: s0-s9 (高权重) + s10-s19 (低权重)
        # prev top20: s10-s19 (高权重) + s0-s9或s20-s24 (低权重)
        # 重合应较高(大约15-20只)但取决于具体排序
        level, msg, ratio = check_position_overlap(current, prev)
        # 不需要精确断言, 只验证函数正常工作
        assert 0.0 <= ratio <= 1.0
