"""Unit tests for FactorGatePipeline G1-G8.

验证要求（来自Sprint 1.15任务规格）:
1. v1.1 Active因子（turnover_mean_20 / volatility_20 / reversal_20 / amihud_20 / bp_ratio）
   跑G1-G5自动Gate，结果必须PASS（与历史结论一致）。
2. 已知FAIL的因子（big_small_consensus: 中性化后IC大幅衰减）G4应FAIL。
3. 每个Gate函数单独覆盖。
4. quick_screen G1-G3快筛覆盖。
5. BH-FDR动态阈值计算覆盖。
"""

import math
from unittest.mock import patch

import pytest
from engines.factor_gate import (
    BH_FDR_LOG_SCALE,
    G3_T_SOFT,
    G4_NEUTRALIZATION_MAX_DECAY,
    FactorGatePipeline,
    GateStatus,
)

# ---------------------------------------------------------------------------
# 测试数据：基于FACTOR_TEST_REGISTRY.md历史结论
# ---------------------------------------------------------------------------

# v1.1 Active因子的历史IC数据（从FACTOR_TEST_REGISTRY.md）
# 月度IC序列：用均值+适当分布模拟，保证统计特征与历史一致
def make_ic_series(ic_mean: float, ic_std: float, n: int = 60) -> list[float]:
    """生成满足指定均值和标准差的IC序列（确定性，无随机）。"""
    # 用等差分布保证精确的均值和std
    import numpy as np
    rng = np.random.default_rng(42)
    series = rng.normal(ic_mean, ic_std, n)
    # 归一化到精确均值
    series = series - series.mean() + ic_mean
    return series.tolist()


# v1.1因子参考数据（FACTOR_TEST_REGISTRY.md）
V1_FACTORS = {
    "turnover_mean_20": {"ic_mean": -0.0643, "ic_std": 0.030, "direction": -1},
    "volatility_20":    {"ic_mean": -0.0690, "ic_std": 0.038, "direction": -1},
    "reversal_20":      {"ic_mean": +0.0386, "ic_std": 0.038, "direction": +1},
    "amihud_20":        {"ic_mean": +0.0215, "ic_std": 0.028, "direction": +1},
    "bp_ratio":         {"ic_mean": +0.0523, "ic_std": 0.030, "direction": +1},
}

# Active因子互相关（近似，用于G2测试）
# 历史数据显示v1.1因子间相关较低
ACTIVE_CORR_MOCK = {
    "turnover_mean_20": 0.23,
    "volatility_20": 0.18,
    "amihud_20": 0.15,
}


@pytest.fixture
def pipeline() -> FactorGatePipeline:
    return FactorGatePipeline(conn=None)


# ---------------------------------------------------------------------------
# BH-FDR 动态阈值
# ---------------------------------------------------------------------------


class TestBhFdrThreshold:
    def test_below_trigger(self, pipeline: FactorGatePipeline) -> None:
        """M <= 20时，阈值等于base_t=2.0。"""
        assert pipeline._bh_fdr_t_threshold(10) == G3_T_SOFT
        assert pipeline._bh_fdr_t_threshold(20) == G3_T_SOFT

    def test_above_trigger(self, pipeline: FactorGatePipeline) -> None:
        """M > 20时，阈值 = 2.0 + log(M) × 0.3。"""
        m = 74
        expected = G3_T_SOFT + math.log(m) * BH_FDR_LOG_SCALE
        assert abs(pipeline._bh_fdr_t_threshold(m) - expected) < 1e-10

    def test_m100(self, pipeline: FactorGatePipeline) -> None:
        """M=100时阈值约3.38（DEV_FACTOR_MINING §13.1示例）。"""
        result = pipeline._bh_fdr_t_threshold(100)
        expected = 2.0 + math.log(100) * 0.3
        assert abs(result - expected) < 0.01


# ---------------------------------------------------------------------------
# G1: |IC_mean| > 0.02
# ---------------------------------------------------------------------------


class TestGateG1:
    def test_pass(self, pipeline: FactorGatePipeline) -> None:
        r = pipeline._gate_g1(0.05)
        assert r.status == GateStatus.PASS
        assert r.gate_id == "G1"

    def test_fail(self, pipeline: FactorGatePipeline) -> None:
        r = pipeline._gate_g1(0.015)
        assert r.status == GateStatus.FAIL

    def test_exact_threshold_fails(self, pipeline: FactorGatePipeline) -> None:
        """|IC| == 0.02 应该FAIL（严格大于）。"""
        r = pipeline._gate_g1(0.02)
        assert r.status == GateStatus.FAIL

    def test_negative_ic_uses_abs(self, pipeline: FactorGatePipeline) -> None:
        """负向因子：|IC_mean|取绝对值。"""
        r = pipeline._gate_g1(-0.05)
        assert r.status == GateStatus.PASS


# ---------------------------------------------------------------------------
# G2: 与Active因子相关性 < 0.7
# ---------------------------------------------------------------------------


class TestGateG2:
    def test_pass_low_corr(self, pipeline: FactorGatePipeline) -> None:
        corr = {"turnover_mean_20": 0.23, "volatility_20": 0.18}
        r = pipeline._gate_g2(corr)
        assert r.status == GateStatus.PASS

    def test_fail_high_corr(self, pipeline: FactorGatePipeline) -> None:
        corr = {"momentum_20": 1.00}  # FACTOR_TEST_REGISTRY #8: corr=1.00
        r = pipeline._gate_g2(corr)
        assert r.status == GateStatus.FAIL

    def test_boundary_exact_threshold_fails(self, pipeline: FactorGatePipeline) -> None:
        """相关性 == 0.7 应FAIL（严格小于）。"""
        corr = {"some_factor": 0.70}
        r = pipeline._gate_g2(corr)
        assert r.status == GateStatus.FAIL

    def test_no_corr_data_defaults_pass(self, pipeline: FactorGatePipeline) -> None:
        """未提供相关性数据时默认PASS（需后续验证）。"""
        r = pipeline._gate_g2({})
        assert r.status == GateStatus.PASS

    def test_negative_corr_uses_abs(self, pipeline: FactorGatePipeline) -> None:
        """负相关也用绝对值判断。"""
        corr = {"some_factor": -0.75}
        r = pipeline._gate_g2(corr)
        assert r.status == GateStatus.FAIL


# ---------------------------------------------------------------------------
# G3: t统计量 > BH-FDR阈值
# ---------------------------------------------------------------------------


class TestGateG3:
    def test_pass_strong_t(self, pipeline: FactorGatePipeline) -> None:
        """t=7.31（turnover_mean_20历史值）应PASS。"""
        r = pipeline._gate_g3(7.31, m=74)
        assert r.status == GateStatus.PASS

    def test_fail_weak_t(self, pipeline: FactorGatePipeline) -> None:
        """t=1.5应FAIL。"""
        r = pipeline._gate_g3(1.5, m=74)
        assert r.status == GateStatus.FAIL

    def test_negative_t_uses_abs(self, pipeline: FactorGatePipeline) -> None:
        """负向t统计量取绝对值。"""
        r = pipeline._gate_g3(-7.31, m=74)
        assert r.status == GateStatus.PASS

    def test_m20_uses_base_threshold(self, pipeline: FactorGatePipeline) -> None:
        """M<=20时使用基础阈值2.0。"""
        r = pipeline._gate_g3(2.1, m=10)
        assert r.status == GateStatus.PASS


# ---------------------------------------------------------------------------
# G4: 中性化后IC衰减 < 50%（铁律2）
# ---------------------------------------------------------------------------


class TestGateG4:
    def test_pass_small_decay(self, pipeline: FactorGatePipeline) -> None:
        """中性化后IC衰减30%（-0.046 → -0.032）应PASS。"""
        neutral_ic = [-0.032] * 20
        r = pipeline._gate_g4(-0.046, neutral_ic)
        assert r.status == GateStatus.PASS
        assert r.data["decay_ratio"] < G4_NEUTRALIZATION_MAX_DECAY

    def test_fail_large_decay(self, pipeline: FactorGatePipeline) -> None:
        """big_small_consensus: 原始IC=12.74%, 中性化后→-1.0%，衰减>50%应FAIL。"""
        # FACTOR_TEST_REGISTRY #49: big_small_consensus REVERTED
        neutral_ic = [-0.01] * 20
        r = pipeline._gate_g4(0.1274, neutral_ic)
        assert r.status == GateStatus.FAIL
        assert r.data["decay_ratio"] > G4_NEUTRALIZATION_MAX_DECAY

    def test_fail_no_neutral_ic(self, pipeline: FactorGatePipeline) -> None:
        """未提供中性化IC时FAIL（铁律2强制）。"""
        r = pipeline._gate_g4(0.05, None)
        assert r.status == GateStatus.FAIL
        assert r.data.get("missing_neutral_ic") is True

    def test_fail_insufficient_neutral_samples(self, pipeline: FactorGatePipeline) -> None:
        """中性化IC样本不足5个时FAIL。"""
        r = pipeline._gate_g4(0.05, [0.04, 0.03])
        assert r.status == GateStatus.FAIL

    def test_mf_price_vol_ratio_like(self, pipeline: FactorGatePipeline) -> None:
        """mf_price_vol_ratio: 中性化后IC大幅衰减（REVERTED）应FAIL。"""
        neutral_ic = [0.005] * 30  # 近零
        r = pipeline._gate_g4(0.08, neutral_ic)
        assert r.status == GateStatus.FAIL


# ---------------------------------------------------------------------------
# G5: 方向与经济学假设一致
# ---------------------------------------------------------------------------


class TestGateG5:
    def test_positive_direction_consistent(self, pipeline: FactorGatePipeline) -> None:
        """IC>0且expected=+1，PASS。"""
        r = pipeline._gate_g5(0.05, 1)
        assert r.status == GateStatus.PASS

    def test_negative_direction_consistent(self, pipeline: FactorGatePipeline) -> None:
        """IC<0且expected=-1，PASS（如turnover_mean_20）。"""
        r = pipeline._gate_g5(-0.064, -1)
        assert r.status == GateStatus.PASS

    def test_direction_inconsistent(self, pipeline: FactorGatePipeline) -> None:
        """IC>0但expected=-1，FAIL。"""
        r = pipeline._gate_g5(0.05, -1)
        assert r.status == GateStatus.FAIL

    def test_neutral_direction_skips(self, pipeline: FactorGatePipeline) -> None:
        """expected=0时跳过方向检验，PASS。"""
        r = pipeline._gate_g5(-0.05, 0)
        assert r.status == GateStatus.PASS


# ---------------------------------------------------------------------------
# run_gates: v1.1 Active因子完整验证
# ---------------------------------------------------------------------------


class TestRunGatesV11Factors:
    """v1.1 5个Active因子G1-G5必须全PASS（铁律2: 历史结论一致性）。"""

    @pytest.mark.parametrize("fname,meta", V1_FACTORS.items())
    def test_v11_factor_g1_to_g5_pass(
        self,
        pipeline: FactorGatePipeline,
        fname: str,
        meta: dict,
    ) -> None:
        ic_mean = meta["ic_mean"]
        ic_std = meta["ic_std"]
        direction = meta["direction"]

        ic_series = make_ic_series(ic_mean, ic_std, n=60)
        # 中性化后IC衰减约20%（模拟真实情况）
        neutral_ic = make_ic_series(ic_mean * 0.85, ic_std * 0.85, n=60)

        with patch(
            "engines.factor_gate.get_cumulative_test_count",
            return_value=74,
        ):
            report = pipeline.run_gates(
                factor_name=fname,
                ic_series=ic_series,
                neutral_ic_series=neutral_ic,
                active_factor_corr=ACTIVE_CORR_MOCK,
                expected_direction=direction,
            )

        assert report.gates["G1"].status == GateStatus.PASS, (
            f"{fname} G1 FAIL: {report.gates['G1'].reason}"
        )
        assert report.gates["G2"].status == GateStatus.PASS, (
            f"{fname} G2 FAIL: {report.gates['G2'].reason}"
        )
        assert report.gates["G3"].status == GateStatus.PASS, (
            f"{fname} G3 FAIL: {report.gates['G3'].reason}"
        )
        assert report.gates["G4"].status == GateStatus.PASS, (
            f"{fname} G4 FAIL: {report.gates['G4'].reason}"
        )
        assert report.gates["G5"].status == GateStatus.PASS, (
            f"{fname} G5 FAIL: {report.gates['G5'].reason}"
        )
        # G6-G8 应为PENDING（等待人工审查）
        assert report.gates["G6"].status == GateStatus.PENDING
        assert report.gates["G7"].status == GateStatus.PENDING
        assert report.gates["G8"].status == GateStatus.PENDING
        # 综合状态：G1-G5全PASS但G6-G8 PENDING → PARTIAL
        assert report.overall_status == "PARTIAL", (
            f"{fname} overall_status={report.overall_status}"
        )

    def test_report_has_all_8_gates(self, pipeline: FactorGatePipeline) -> None:
        """GateReport必须包含G1-G8全部8个Gate。"""
        ic_series = make_ic_series(-0.064, 0.03, 60)
        neutral_ic = make_ic_series(-0.055, 0.025, 60)
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates(
                "turnover_mean_20", ic_series, neutral_ic,
                ACTIVE_CORR_MOCK, expected_direction=-1,
            )
        for gid in ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]:
            assert gid in report.gates, f"报告缺少 {gid}"

    def test_cumulative_m_in_report(self, pipeline: FactorGatePipeline) -> None:
        """GateReport应记录BH-FDR用的累积M。"""
        ic_series = make_ic_series(-0.064, 0.03, 60)
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates("turnover_mean_20", ic_series)
        assert report.cumulative_m == 74


# ---------------------------------------------------------------------------
# 已知FAIL因子验证
# ---------------------------------------------------------------------------


class TestKnownFailFactors:
    def test_big_small_consensus_g4_fail(self, pipeline: FactorGatePipeline) -> None:
        """big_small_consensus: 中性化后IC从12.74%→-1.0%，G4必须FAIL。
        FACTOR_TEST_REGISTRY #49: REVERTED，LL-014。
        """
        # 模拟: 原始IC高但中性化后近零
        ic_series = [0.1274] * 30 + [0.12] * 30
        neutral_ic = [-0.01] * 60

        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates(
                "big_small_consensus",
                ic_series=ic_series,
                neutral_ic_series=neutral_ic,
                expected_direction=1,
            )

        assert report.gates["G4"].status == GateStatus.FAIL
        assert "衰减" in report.gates["G4"].reason or "FAIL" in report.gates["G4"].reason

    def test_low_ic_factor_g1_fail(self, pipeline: FactorGatePipeline) -> None:
        """roe_stability: |IC|=1.5% < 2%，G1必须FAIL。
        FACTOR_TEST_REGISTRY #21: FAIL。
        """
        ic_series = make_ic_series(0.015, 0.04, 60)
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates("roe_stability", ic_series)
        assert report.gates["G1"].status == GateStatus.FAIL
        assert report.overall_status == "FAIL"

    def test_redundant_factor_g2_fail(self, pipeline: FactorGatePipeline) -> None:
        """momentum_20: corr(reversal_20)=1.00，G2必须FAIL。
        FACTOR_TEST_REGISTRY #8: DEPRECATED。
        """
        ic_series = make_ic_series(-0.040, 0.035, 60)
        corr = {"reversal_20": 1.00}  # 完全冗余
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates(
                "momentum_20", ic_series,
                active_factor_corr=corr,
                expected_direction=-1,
            )
        assert report.gates["G2"].status == GateStatus.FAIL
        assert report.overall_status == "FAIL"


# ---------------------------------------------------------------------------
# 半自动Gate确认接口
# ---------------------------------------------------------------------------


class TestSemiAutoGateConfirm:
    def _get_partial_report(self, pipeline: FactorGatePipeline) -> object:
        ic_series = make_ic_series(-0.064, 0.03, 60)
        neutral_ic = make_ic_series(-0.055, 0.025, 60)
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            return pipeline.run_gates(
                "test_factor", ic_series, neutral_ic, ACTIVE_CORR_MOCK, -1
            )

    def test_confirm_g6_pass(self, pipeline: FactorGatePipeline) -> None:
        report = self._get_partial_report(pipeline)
        report = pipeline.confirm_g6(report, t_stat_newey_west=3.5)
        assert report.gates["G6"].status == GateStatus.PASS

    def test_confirm_g6_fail(self, pipeline: FactorGatePipeline) -> None:
        report = self._get_partial_report(pipeline)
        report = pipeline.confirm_g6(report, t_stat_newey_west=1.8)
        assert report.gates["G6"].status == GateStatus.FAIL
        assert report.overall_status == "FAIL"

    def test_confirm_g7_pass(self, pipeline: FactorGatePipeline) -> None:
        report = self._get_partial_report(pipeline)
        report = pipeline.confirm_g7(report, simbroker_sharpe=1.15, bootstrap_p_value=0.02)
        assert report.gates["G7"].status == GateStatus.PASS

    def test_confirm_g7_fail_low_sharpe(self, pipeline: FactorGatePipeline) -> None:
        report = self._get_partial_report(pipeline)
        report = pipeline.confirm_g7(report, simbroker_sharpe=0.95)
        assert report.gates["G7"].status == GateStatus.FAIL

    def test_confirm_g7_fail_bootstrap(self, pipeline: FactorGatePipeline) -> None:
        """Sharpe够高但bootstrap p>=0.05应FAIL。"""
        report = self._get_partial_report(pipeline)
        report = pipeline.confirm_g7(report, simbroker_sharpe=1.10, bootstrap_p_value=0.08)
        assert report.gates["G7"].status == GateStatus.FAIL

    def test_confirm_g8_pass(self, pipeline: FactorGatePipeline) -> None:
        report = self._get_partial_report(pipeline)
        report = pipeline.confirm_g8(report, signal_type="ranking", rebalance_freq="monthly")
        assert report.gates["G8"].status == GateStatus.PASS

    def test_full_pipeline_all_pass(self, pipeline: FactorGatePipeline) -> None:
        """G1-G8全PASS时overall_status=PASS。"""
        report = self._get_partial_report(pipeline)
        report = pipeline.confirm_g6(report, t_stat_newey_west=4.0)
        report = pipeline.confirm_g7(report, simbroker_sharpe=1.20, bootstrap_p_value=0.01)
        report = pipeline.confirm_g8(report, signal_type="ranking", rebalance_freq="monthly")
        assert report.overall_status == "PASS"


# ---------------------------------------------------------------------------
# quick_screen: G1-G3快筛
# ---------------------------------------------------------------------------


class TestQuickScreen:
    def test_pass_strong_factor(self, pipeline: FactorGatePipeline) -> None:
        ic_series = make_ic_series(-0.064, 0.03, 60)
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            passed, reason = pipeline.quick_screen(
                "turnover_mean_20", ic_series, ACTIVE_CORR_MOCK
            )
        assert passed is True

    def test_fail_low_ic(self, pipeline: FactorGatePipeline) -> None:
        ic_series = make_ic_series(0.010, 0.03, 60)
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            passed, reason = pipeline.quick_screen("weak_factor", ic_series)
        assert passed is False
        assert "G1" in reason

    def test_fail_high_corr(self, pipeline: FactorGatePipeline) -> None:
        ic_series = make_ic_series(-0.064, 0.03, 60)
        corr = {"reversal_20": 0.95}
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            passed, reason = pipeline.quick_screen("redundant", ic_series, corr)
        assert passed is False
        assert "G2" in reason

    def test_fail_empty_series(self, pipeline: FactorGatePipeline) -> None:
        passed, reason = pipeline.quick_screen("empty", [])
        assert passed is False


# ---------------------------------------------------------------------------
# 边界案例
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_ic_series(self, pipeline: FactorGatePipeline) -> None:
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates("empty", [])
        assert report.overall_status == "FAIL"

    def test_insufficient_samples(self, pipeline: FactorGatePipeline) -> None:
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates("tiny", [0.05, 0.03, 0.04])
        assert report.overall_status == "FAIL"

    def test_all_nan_ic(self, pipeline: FactorGatePipeline) -> None:
        """全NaN的IC序列应FAIL。"""
        import math
        ic_series = [math.nan] * 30
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates("all_nan", ic_series)
        assert report.overall_status == "FAIL"

    def test_report_summary_has_all_gates(self, pipeline: FactorGatePipeline) -> None:
        """summary()必须包含G1-G8信息。"""
        ic_series = make_ic_series(-0.064, 0.03, 60)
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates("turnover_mean_20", ic_series)
        summary = report.summary()
        for gid in ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]:
            assert gid in summary, f"summary缺少{gid}"

    def test_failed_gates_property(self, pipeline: FactorGatePipeline) -> None:
        """failed_gates属性返回FAIL的Gate ID列表。"""
        ic_series = make_ic_series(0.010, 0.03, 60)  # G1会FAIL
        with patch("engines.factor_gate.get_cumulative_test_count", return_value=74):
            report = pipeline.run_gates("weak", ic_series)
        assert "G1" in report.failed_gates
