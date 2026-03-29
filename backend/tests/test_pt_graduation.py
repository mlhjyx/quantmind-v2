"""PT毕业评估脚本核心逻辑单元测试 (Sprint 1.21 T3)。

测试 scripts/pt_graduation_assessment.py 中的纯函数：
- calc_sharpe
- calc_mdd
- calc_slippage_deviation
- calc_running_days

不依赖数据库，无 asyncio fixture。
"""

import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# 将 scripts/ 目录加入 sys.path 以便直接导入
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from pt_graduation_assessment import (  # noqa: E402
    MDD_THRESHOLD,
    SHARPE_THRESHOLD,
    SLIPPAGE_DEV_THRESHOLD,
    TRADING_DAYS_PER_YEAR,
    calc_mdd,
    calc_running_days,
    calc_sharpe,
    calc_slippage_deviation,
)

# ─────────────────────────────────────────────────────────────
# calc_sharpe
# ─────────────────────────────────────────────────────────────

class TestCalcSharpe:
    def test_empty_returns_zero(self):
        assert calc_sharpe([]) == 0.0

    def test_single_element_returns_zero(self):
        assert calc_sharpe([0.01]) == 0.0

    def test_zero_std_returns_zero(self):
        """所有收益相同 → std=0 → Sharpe=0（避免除零）。"""
        assert calc_sharpe([0.01, 0.01, 0.01]) == 0.0

    def test_positive_sharpe(self):
        """正收益低波动 → Sharpe > 0。"""
        returns = [0.001] * 100 + [-0.0005] * 20
        result = calc_sharpe(returns)
        assert result > 0.0

    def test_annualization_formula(self):
        """验证公式: Sharpe = (mean/std) * sqrt(244)。"""
        returns = [0.01, -0.005, 0.008, -0.003, 0.006]
        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(variance)
        expected = (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)
        assert calc_sharpe(returns) == pytest.approx(expected, rel=1e-6)

    def test_negative_sharpe(self):
        """负均值收益 → Sharpe < 0。"""
        returns = [-0.01, -0.02, -0.005, -0.015, -0.008]
        assert calc_sharpe(returns) < 0.0

    def test_returns_float(self):
        result = calc_sharpe([0.01, -0.005, 0.008])
        assert isinstance(result, float)

    def test_graduation_threshold(self):
        """构造一个 Sharpe ≥ 0.72 的序列，验证评估逻辑。"""
        # 日均收益 0.003, std ≈ 0.005 → Sharpe ≈ 0.003/0.005 * sqrt(244) ≈ 9.4
        returns = [0.003 + (0.001 if i % 3 == 0 else -0.001) for i in range(50)]
        result = calc_sharpe(returns)
        assert result >= SHARPE_THRESHOLD


# ─────────────────────────────────────────────────────────────
# calc_mdd
# ─────────────────────────────────────────────────────────────

class TestCalcMdd:
    def test_empty_returns_zero(self):
        assert calc_mdd([]) == 0.0

    def test_single_element_returns_zero(self):
        assert calc_mdd([1.0]) == 0.0

    def test_monotone_rising_zero_mdd(self):
        """单调上涨，MDD=0。"""
        assert calc_mdd([1.0, 1.01, 1.02, 1.03]) == pytest.approx(0.0, abs=1e-9)

    def test_single_trough(self):
        """1.0 → 1.2 → 0.9 → 1.1，MDD = (1.2-0.9)/1.2 = 25%。"""
        nav = [1.0, 1.2, 0.9, 1.1]
        result = calc_mdd(nav)
        assert result == pytest.approx(0.25, abs=1e-6)

    def test_all_decline(self):
        """从 1.0 直线跌到 0.6，MDD = 40%。"""
        nav = [1.0, 0.9, 0.8, 0.7, 0.6]
        result = calc_mdd(nav)
        assert result == pytest.approx(0.40, abs=1e-6)

    def test_multiple_troughs_takes_max(self):
        """两个回撤取较大值。"""
        # 第一回撤: 1.0→0.8 = 20%; 第二回撤: 1.2→0.84 = 30%
        nav = [1.0, 0.8, 1.2, 0.84]
        result = calc_mdd(nav)
        assert result == pytest.approx(0.30, abs=1e-4)

    def test_returns_float(self):
        result = calc_mdd([1.0, 0.9, 1.1])
        assert isinstance(result, float)

    def test_mdd_threshold_35pct(self):
        """MDD < 35% 才毕业: 构造 30% 回撤的序列应 PASS。"""
        nav = [1.0, 1.1, 0.77, 1.05]   # 回撤 = (1.1 - 0.77)/1.1 ≈ 30%
        result = calc_mdd(nav)
        assert result < MDD_THRESHOLD


# ─────────────────────────────────────────────────────────────
# calc_slippage_deviation
# ─────────────────────────────────────────────────────────────

class TestCalcSlippageDeviation:
    def test_empty_list_returns_zero(self):
        assert calc_slippage_deviation([], 5.0) == 0.0

    def test_zero_theoretical_returns_zero(self):
        assert calc_slippage_deviation([5.0, 6.0], 0.0) == 0.0

    def test_exact_match_zero_deviation(self):
        """实际均值 = 理论值 → 偏差 = 0。"""
        result = calc_slippage_deviation([5.0, 5.0, 5.0], 5.0)
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_20pct_positive_deviation(self):
        """实际均值 6.0，理论 5.0 → 偏差 = 20%。"""
        result = calc_slippage_deviation([6.0, 6.0, 6.0], 5.0)
        assert result == pytest.approx(0.20, abs=1e-6)

    def test_20pct_negative_deviation_abs(self):
        """实际均值 4.0，理论 5.0 → |偏差| = 20%（取绝对值）。"""
        result = calc_slippage_deviation([4.0, 4.0, 4.0], 5.0)
        assert result == pytest.approx(0.20, abs=1e-6)

    def test_50pct_threshold(self):
        """实际均值 7.5，理论 5.0 → 偏差 50% = 边界（FAIL）。"""
        result = calc_slippage_deviation([7.5, 7.5], 5.0)
        assert result == pytest.approx(0.50, abs=1e-6)
        assert result >= SLIPPAGE_DEV_THRESHOLD  # FAIL: >= 不通过

    def test_pass_under_50pct(self):
        """偏差 40% < 50% → PASS。"""
        result = calc_slippage_deviation([7.0, 7.0], 5.0)
        assert result == pytest.approx(0.40, abs=1e-6)
        assert result < SLIPPAGE_DEV_THRESHOLD

    def test_returns_float(self):
        result = calc_slippage_deviation([5.5], 5.0)
        assert isinstance(result, float)

    def test_averaged_over_all_trades(self):
        """不同滑点取均值后再比较理论值。"""
        # 均值 = (3+7)/2 = 5.0，理论 5.0 → 偏差 0
        result = calc_slippage_deviation([3.0, 7.0], 5.0)
        assert result == pytest.approx(0.0, abs=1e-9)


# ─────────────────────────────────────────────────────────────
# calc_running_days
# ─────────────────────────────────────────────────────────────

class TestCalcRunningDays:
    def test_empty_returns_zero(self):
        assert calc_running_days([]) == 0

    def test_single_date_returns_one(self):
        assert calc_running_days([date(2026, 1, 5)]) == 1

    def test_consecutive_days(self):
        """首末相差 4天 → running_days = 5（含首日）。"""
        dates = [date(2026, 1, 5) + timedelta(days=i) for i in range(5)]
        assert calc_running_days(dates) == 5

    def test_unordered_dates(self):
        """乱序输入，结果与有序相同。"""
        dates = [date(2026, 3, 1), date(2026, 1, 1), date(2026, 2, 1)]
        assert calc_running_days(dates) == 60  # 1/1 → 3/1 = 59天差 + 1

    def test_30_days(self):
        """30天序列。"""
        dates = [date(2026, 1, 5) + timedelta(days=i) for i in range(30)]
        assert calc_running_days(dates) == 30

    def test_returns_int(self):
        result = calc_running_days([date(2026, 1, 1), date(2026, 1, 10)])
        assert isinstance(result, int)


# ─────────────────────────────────────────────────────────────
# 综合场景：毕业 / 不毕业
# ─────────────────────────────────────────────────────────────

class TestGraduationScenarios:
    def test_all_pass_scenario(self):
        """构造三指标全通过的数据组合。"""
        # Sharpe > 0.72
        returns = [0.002 + (0.0005 if i % 2 == 0 else -0.0005) for i in range(60)]
        sharpe = calc_sharpe(returns)
        assert sharpe >= SHARPE_THRESHOLD, f"场景错误: Sharpe={sharpe:.3f}"

        # MDD < 35%
        nav = [1.0 + i * 0.002 for i in range(60)]  # 单调上涨
        mdd = calc_mdd(nav)
        assert mdd < MDD_THRESHOLD

        # 滑点偏差 < 50%
        slippage_dev = calc_slippage_deviation([5.5] * 30, 5.0)
        assert slippage_dev < SLIPPAGE_DEV_THRESHOLD

    def test_mdd_fail_scenario(self):
        """MDD 超过 35% → FAIL。"""
        nav = [1.0, 1.5, 0.9, 1.2]  # (1.5 - 0.9)/1.5 = 40%
        mdd = calc_mdd(nav)
        assert mdd >= MDD_THRESHOLD

    def test_sharpe_fail_scenario(self):
        """Sharpe < 0.72 → FAIL。"""
        # 大波动低收益
        returns = [0.05, -0.05, 0.05, -0.05, 0.01, -0.01] * 10
        sharpe = calc_sharpe(returns)
        assert sharpe < SHARPE_THRESHOLD

    def test_slippage_fail_scenario(self):
        """滑点偏差 ≥ 50% → FAIL。"""
        slippage_dev = calc_slippage_deviation([10.0] * 20, 5.0)  # 100% 偏差
        assert slippage_dev >= SLIPPAGE_DEV_THRESHOLD
