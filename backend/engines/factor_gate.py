"""Factor Gate Pipeline G1-G8 — 因子质量门控流水线。

将因子候选从BruteForce/DEAP GP/LLM引擎产出，经8个Gate逐级筛选，
输出完整GateReport供人工审查和FACTOR_TEST_REGISTRY.md记录。

Gate定义（DEV_FACTOR_MINING.md §13.1 + 宪法§3 + R2研究）:

  自动Gate（代码执行，不需人工）:
    G1: |IC_mean| > 0.02  — 快筛宽松阈值
    G2: 与现有Active因子截面相关性 < 0.7  — 正交性
    G3: t统计量 > 2.0  — 宽松显著性（BH-FDR动态校正）
    G4: 中性化后IC衰减 < 50%  — 铁律2中性化验证
    G5: 方向与经济学假设一致

  半自动Gate（需factor/quant/strategy审查，提供自动化数据）:
    G6: BH-FDR多重检验校正（Harvey Liu Zhu 2016, t>2.5硬性标准）
    G7: SimBroker回测Sharpe ≥ 基线1.03（铁律3）
    G8: strategy策略匹配确认（铁律8，FactorClassifier输出）

设计文档:
  - DEV_FACTOR_MINING.md §13.1: Gate 8项完整定义
  - R2_factor_mining_frontier.md §7: Gate Pipeline整体架构
  - TEAM_CHARTER_V3.3.md §3: 因子审批链+BH-FDR硬性标准
  - config_guard.py: get_cumulative_test_count() BH-FDR用
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import structlog

from engines.config_guard import get_cumulative_test_count

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 常量与阈值
# ---------------------------------------------------------------------------

# 自动Gate阈值
G1_IC_THRESHOLD = 0.02          # |IC_mean| 快筛宽松阈值
G2_CORR_THRESHOLD = 0.70        # 与现有Active因子最大相关性
G3_T_SOFT = 2.0                 # t统计量宽松下限（BH-FDR动态调整）
G3_T_HARD = 2.5                 # Harvey Liu Zhu 2016硬性下限（G6用）
G4_NEUTRALIZATION_MAX_DECAY = 0.50  # 中性化后IC衰减上限（铁律2）

# 半自动Gate阈值
G7_SHARPE_BASELINE = 1.03       # v1.1基线Sharpe（CLAUDE.md 宪法）

# BH-FDR动态调整：基础t阈值 + log(N) × 0.3（DEV_FACTOR_MINING §13.1）
BH_FDR_BASE_T = 2.0
BH_FDR_LOG_SCALE = 0.3
BH_FDR_N_TRIGGER = 20           # N>20时开始动态调整


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class GateStatus(StrEnum):
    """Gate结果状态。"""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"       # 前置Gate失败时跳过
    PENDING = "PENDING"  # 半自动Gate等待人工


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    """单个Gate的检验结果。"""
    gate_id: str            # "G1" ~ "G8"
    status: GateStatus
    metric_name: str        # 被检验的指标名
    metric_value: float | None
    threshold: float | None
    reason: str             # 人类可读的原因
    data: dict[str, Any] = field(default_factory=dict)  # 附加数据

    def __str__(self) -> str:
        val_str = f"{self.metric_value:.4f}" if self.metric_value is not None else "N/A"
        thr_str = f"{self.threshold:.4f}" if self.threshold is not None else "N/A"
        return f"{self.gate_id}[{self.status}] {self.metric_name}={val_str} (threshold={thr_str}): {self.reason}"


@dataclass
class GateReport:
    """完整8个Gate的检验报告。"""
    factor_name: str
    gates: dict[str, GateResult] = field(default_factory=dict)
    overall_status: str = "PENDING"   # PASS / FAIL / PARTIAL / PENDING
    cumulative_m: int = 0             # BH-FDR用，当前累积测试总数
    notes: str = ""

    @property
    def auto_gates_passed(self) -> bool:
        """G1-G5全部通过（自动Gate）。"""
        return all(
            self.gates.get(f"G{i}", GateResult(f"G{i}", GateStatus.FAIL, "", None, None, "")).status == GateStatus.PASS
            for i in range(1, 6)
        )

    @property
    def failed_gates(self) -> list[str]:
        """返回FAIL状态的Gate ID列表。"""
        return [gid for gid, r in self.gates.items() if r.status == GateStatus.FAIL]

    @property
    def pending_gates(self) -> list[str]:
        """返回PENDING状态的Gate ID列表（需人工）。"""
        return [gid for gid, r in self.gates.items() if r.status == GateStatus.PENDING]

    def summary(self) -> str:
        """输出简洁摘要字符串。"""
        lines = [f"GateReport: {self.factor_name} [{self.overall_status}]"]
        for gid in ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]:
            r = self.gates.get(gid)
            if r:
                lines.append(f"  {r}")
        if self.notes:
            lines.append(f"  Notes: {self.notes}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FactorGatePipeline
# ---------------------------------------------------------------------------


class FactorGatePipeline:
    """因子Gate Pipeline G1-G8。

    用法:
        pipeline = FactorGatePipeline(conn)
        report = pipeline.run_gates(
            factor_name="my_factor",
            ic_series=[0.03, 0.02, -0.01, ...],   # 月度IC序列
            neutral_ic_series=[0.025, 0.018, ...], # 中性化后IC序列
            active_factor_corr={"turnover_mean_20": 0.23, ...},  # 与Active因子相关系数
            expected_direction=1,                  # 1=正向, -1=负向
        )
        print(report.summary())

    对于G6/G7/G8（半自动），pipeline输出PENDING状态和数据，
    等待factor/quant/strategy人工审查后调用:
        pipeline.confirm_g6(report, t_stat_newey_west=3.2)
        pipeline.confirm_g7(report, simbroker_sharpe=1.15)
        pipeline.confirm_g8(report, signal_type="ranking", rebalance_freq="monthly")
    """

    def __init__(self, conn: Any | None = None) -> None:
        """初始化。

        Args:
            conn: psycopg2数据库连接（用于因子相关矩阵查询，可选）。
        """
        self.conn = conn

    # ----------------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------------

    def run_gates(
        self,
        factor_name: str,
        ic_series: list[float],
        neutral_ic_series: list[float] | None = None,
        active_factor_corr: dict[str, float] | None = None,
        expected_direction: int = 1,
        coverage_ratio: float | None = None,
        ic_win_rate: float | None = None,
        registry_path: str | None = None,
    ) -> GateReport:
        """执行G1-G5自动Gate，G6-G8标记PENDING等待人工。

        所有Gate按序执行，任何Gate FAIL不中断，继续运行输出完整报告。
        G1 FAIL时，G2-G5仍运行；但G4需要neutral_ic_series。

        Args:
            factor_name: 因子名称。
            ic_series: 月度Rank IC序列（原始，未中性化）。
            neutral_ic_series: 中性化后月度IC序列（G4用，铁律2）。
            active_factor_corr: 与Active池因子的截面Spearman相关系数 {fname: corr}。
            expected_direction: 经济学假设方向（1=正，-1=负）。G5用。
            coverage_ratio: 因子覆盖率（非NaN股票占比）。可选。
            ic_win_rate: IC胜率（IC>0的比例）。可选，默认从ic_series计算。
            registry_path: FACTOR_TEST_REGISTRY.md路径，None用默认。

        Returns:
            GateReport: 包含G1-G8结果（G6-G8为PENDING）。
        """
        report = GateReport(factor_name=factor_name)

        # 读取累积测试总数M（BH-FDR用）
        try:
            m = get_cumulative_test_count(registry_path=registry_path)
        except (FileNotFoundError, ValueError) as e:
            logger.warning("无法读取FACTOR_TEST_REGISTRY.md: %s，使用默认M=74", e)
            m = 74
        report.cumulative_m = m

        if not ic_series:
            report.overall_status = "FAIL"
            report.notes = "ic_series为空，无法执行Gate检验"
            for gid in [f"G{i}" for i in range(1, 9)]:
                report.gates[gid] = GateResult(gid, GateStatus.FAIL, "ic_series", None, None, "ic_series为空")
            return report

        ic_arr = np.array(ic_series, dtype=float)
        ic_arr = ic_arr[~np.isnan(ic_arr)]

        if len(ic_arr) < 5:
            report.overall_status = "FAIL"
            report.notes = f"有效IC样本不足（n={len(ic_arr)}<5），统计检验不可靠"
            for gid in [f"G{i}" for i in range(1, 9)]:
                report.gates[gid] = GateResult(
                    gid, GateStatus.FAIL, "sample_size", float(len(ic_arr)), 5.0,
                    f"IC样本n={len(ic_arr)}不足5个"
                )
            return report

        # 基本统计
        ic_mean = float(np.mean(ic_arr))
        ic_std = float(np.std(ic_arr, ddof=1))
        n = len(ic_arr)
        t_stat = ic_mean / (ic_std / math.sqrt(n)) if ic_std > 0 else 0.0
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0.0

        # IC胜率：若未提供则从序列计算
        if ic_win_rate is None:
            # 方向统一化：根据expected_direction判断"正确方向"
            if expected_direction >= 0:
                ic_win_rate = float(np.sum(ic_arr > 0) / n)
            else:
                ic_win_rate = float(np.sum(ic_arr < 0) / n)

        # ---- G1: |IC_mean| > 0.02 ----
        report.gates["G1"] = self._gate_g1(ic_mean)

        # ---- G2: 与Active因子相关性 < 0.7 ----
        report.gates["G2"] = self._gate_g2(active_factor_corr or {})

        # ---- G3: t统计量 > 2.0（BH-FDR动态调整）----
        report.gates["G3"] = self._gate_g3(t_stat, m)

        # ---- G4: 中性化后IC衰减 < 50% （铁律2）----
        report.gates["G4"] = self._gate_g4(ic_mean, neutral_ic_series)

        # ---- G5: 方向与经济学假设一致 ----
        report.gates["G5"] = self._gate_g5(ic_mean, expected_direction)

        # ---- G6: BH-FDR（半自动，PENDING）----
        report.gates["G6"] = GateResult(
            "G6", GateStatus.PENDING,
            "t_stat_newey_west", t_stat, G3_T_HARD,
            f"需quant审查: Newey-West t统计量>2.5硬性标准 (Harvey Liu Zhu 2016). "
            f"当前原始t={t_stat:.3f}, 累积M={m}, 调整阈值≈{self._bh_fdr_t_threshold(m):.3f}",
            data={
                "raw_t_stat": t_stat,
                "cumulative_m": m,
                "adjusted_t_threshold": self._bh_fdr_t_threshold(m),
                "ic_mean": ic_mean,
                "ic_ir": ic_ir,
                "n_obs": n,
            },
        )

        # ---- G7: SimBroker回测Sharpe ≥ 基线（半自动，铁律3）----
        report.gates["G7"] = GateResult(
            "G7", GateStatus.PENDING,
            "simbroker_sharpe", None, G7_SHARPE_BASELINE,
            f"需SimBroker回测: Sharpe ≥ {G7_SHARPE_BASELINE} (v1.1基线). "
            "paired bootstrap p<0.05 required.",
            data={"baseline_sharpe": G7_SHARPE_BASELINE},
        )

        # ---- G8: strategy策略匹配（半自动，铁律8）----
        report.gates["G8"] = GateResult(
            "G8", GateStatus.PENDING,
            "strategy_match", None, None,
            "需strategy审查: FactorClassifier输出信号类型+调仓频率+铁律8确认",
            data={"expected_direction": expected_direction, "ic_ir": ic_ir},
        )

        # 综合状态
        report.overall_status = self._compute_overall_status(report)

        logger.info(
            "GateReport[%s]: overall=%s, failed=%s, pending=%s",
            factor_name, report.overall_status,
            report.failed_gates, report.pending_gates,
        )
        return report

    # ----------------------------------------------------------------
    # 单个Gate函数（可独立调用）
    # ----------------------------------------------------------------

    def _gate_g1(self, ic_mean: float) -> GateResult:
        """G1: |IC_mean| > 0.02 快筛。"""
        abs_ic = abs(ic_mean)
        passed = abs_ic > G1_IC_THRESHOLD
        return GateResult(
            "G1", GateStatus.PASS if passed else GateStatus.FAIL,
            "ic_mean_abs", abs_ic, G1_IC_THRESHOLD,
            f"|IC_mean|={abs_ic:.4f} {'>' if passed else '<='} {G1_IC_THRESHOLD}",
        )

    def _gate_g2(self, active_factor_corr: dict[str, float]) -> GateResult:
        """G2: 与现有Active因子截面相关性 < 0.7。"""
        if not active_factor_corr:
            return GateResult(
                "G2", GateStatus.PASS,
                "max_active_corr", 0.0, G2_CORR_THRESHOLD,
                "无Active因子相关性数据，默认PASS（需后续验证）",
                data={"warning": "no_active_corr_provided"},
            )

        max_corr_abs = max(abs(v) for v in active_factor_corr.values())
        most_correlated = max(active_factor_corr, key=lambda k: abs(active_factor_corr[k]))
        passed = max_corr_abs < G2_CORR_THRESHOLD

        return GateResult(
            "G2", GateStatus.PASS if passed else GateStatus.FAIL,
            "max_active_corr", max_corr_abs, G2_CORR_THRESHOLD,
            f"最高相关={max_corr_abs:.4f} with {most_correlated} "
            f"({'< 0.7, PASS' if passed else '>= 0.7, FAIL冗余'})",
            data={
                "all_correlations": active_factor_corr,
                "max_corr_factor": most_correlated,
                "max_corr_value": max_corr_abs,
            },
        )

    def _gate_g3(self, t_stat: float, m: int) -> GateResult:
        """G3: t统计量 > 2.0，BH-FDR动态调整阈值。"""
        threshold = self._bh_fdr_t_threshold(m)
        abs_t = abs(t_stat)
        passed = abs_t > threshold

        return GateResult(
            "G3", GateStatus.PASS if passed else GateStatus.FAIL,
            "t_stat_abs", abs_t, threshold,
            f"|t|={abs_t:.3f} {'>' if passed else '<='} {threshold:.3f} "
            f"(base={G3_T_SOFT}, M={m}, log({m})×{BH_FDR_LOG_SCALE}={math.log(m) * BH_FDR_LOG_SCALE:.3f} "
            f"if M>{BH_FDR_N_TRIGGER})",
            data={
                "raw_t_stat": t_stat,
                "threshold_used": threshold,
                "cumulative_m": m,
                "bh_fdr_adjustment": threshold - G3_T_SOFT,
            },
        )

    def _gate_g4(
        self,
        raw_ic_mean: float,
        neutral_ic_series: list[float] | None,
    ) -> GateResult:
        """G4: 中性化后IC衰减 < 50%（铁律2: 中性化验证）。

        衰减定义: (|raw_IC| - |neutral_IC|) / |raw_IC|
        """
        if neutral_ic_series is None or len(neutral_ic_series) == 0:
            return GateResult(
                "G4", GateStatus.FAIL,
                "neutralization_decay", None, G4_NEUTRALIZATION_MAX_DECAY,
                "未提供中性化IC数据（铁律2强制要求），标记FAIL",
                data={"missing_neutral_ic": True},
            )

        neutral_arr = np.array(neutral_ic_series, dtype=float)
        neutral_arr = neutral_arr[~np.isnan(neutral_arr)]

        if len(neutral_arr) < 5:
            return GateResult(
                "G4", GateStatus.FAIL,
                "neutralization_decay", None, G4_NEUTRALIZATION_MAX_DECAY,
                f"中性化IC样本不足（n={len(neutral_arr)}<5），铁律2验证失败",
            )

        neutral_ic_mean = float(np.mean(neutral_arr))
        abs_raw = abs(raw_ic_mean)
        abs_neutral = abs(neutral_ic_mean)

        if abs_raw < 1e-8:
            return GateResult(
                "G4", GateStatus.FAIL,
                "neutralization_decay", None, G4_NEUTRALIZATION_MAX_DECAY,
                "原始|IC_mean|≈0，无法计算衰减比率",
            )

        decay_ratio = (abs_raw - abs_neutral) / abs_raw
        passed = decay_ratio < G4_NEUTRALIZATION_MAX_DECAY

        return GateResult(
            "G4", GateStatus.PASS if passed else GateStatus.FAIL,
            "neutralization_decay", decay_ratio, G4_NEUTRALIZATION_MAX_DECAY,
            f"中性化后IC衰减={decay_ratio:.1%} ({'< 50%, PASS' if passed else '>= 50%, FAIL虚假alpha'}). "
            f"原始|IC|={abs_raw:.4f} → 中性化|IC|={abs_neutral:.4f}",
            data={
                "raw_ic_mean": raw_ic_mean,
                "neutral_ic_mean": neutral_ic_mean,
                "decay_ratio": decay_ratio,
            },
        )

    def _gate_g5(self, ic_mean: float, expected_direction: int) -> GateResult:
        """G5: 方向与经济学假设一致。

        expected_direction: 1=因子值越高收益越高（正向），-1=因子值越高收益越低（负向）。
        IC均值符号应与expected_direction一致。
        """
        if expected_direction == 0:
            return GateResult(
                "G5", GateStatus.PASS,
                "direction_consistency", float(ic_mean), None,
                "expected_direction=0（方向中性），跳过方向检验",
            )

        actual_direction = 1 if ic_mean > 0 else -1
        consistent = actual_direction == expected_direction

        return GateResult(
            "G5", GateStatus.PASS if consistent else GateStatus.FAIL,
            "direction_consistency", float(ic_mean), float(expected_direction),
            f"IC均值={ic_mean:.4f}（方向={'+' if actual_direction > 0 else '-'}），"
            f"期望方向={'+' if expected_direction > 0 else '-'}，"
            f"{'一致PASS' if consistent else '方向相反FAIL（需重新检验经济学假设）'}",
            data={
                "ic_mean": ic_mean,
                "expected_direction": expected_direction,
                "actual_direction": actual_direction,
            },
        )

    # ----------------------------------------------------------------
    # 半自动Gate确认接口（人工审查后调用）
    # ----------------------------------------------------------------

    def confirm_g6(
        self,
        report: GateReport,
        t_stat_newey_west: float,
        p_value: float | None = None,
    ) -> GateReport:
        """G6 BH-FDR确认（quant审查后调用）。

        Args:
            report: 待更新的GateReport。
            t_stat_newey_west: Newey-West HAC调整后的t统计量。
            p_value: 对应p值（可选）。

        Returns:
            更新后的GateReport（原地修改+返回）。
        """
        m = report.cumulative_m
        threshold = max(G3_T_HARD, self._bh_fdr_t_threshold(m))
        abs_t = abs(t_stat_newey_west)
        passed = abs_t > threshold

        report.gates["G6"] = GateResult(
            "G6", GateStatus.PASS if passed else GateStatus.FAIL,
            "t_stat_newey_west", abs_t, threshold,
            f"Newey-West |t|={abs_t:.3f} {'>' if passed else '<='} {threshold:.3f} "
            f"(Harvey Liu Zhu 2016, M={m})",
            data={
                "t_stat_newey_west": t_stat_newey_west,
                "p_value": p_value,
                "threshold": threshold,
                "cumulative_m": m,
            },
        )
        report.overall_status = self._compute_overall_status(report)
        return report

    def confirm_g7(
        self,
        report: GateReport,
        simbroker_sharpe: float,
        bootstrap_p_value: float | None = None,
    ) -> GateReport:
        """G7 SimBroker回测确认（铁律3）。

        Args:
            report: 待更新的GateReport。
            simbroker_sharpe: SimBroker回测Sharpe比率。
            bootstrap_p_value: paired bootstrap显著性p值（要求<0.05）。

        Returns:
            更新后的GateReport。
        """
        sharpe_pass = simbroker_sharpe >= G7_SHARPE_BASELINE
        bootstrap_pass = bootstrap_p_value is None or bootstrap_p_value < 0.05
        passed = sharpe_pass and bootstrap_pass

        reason_parts = [
            f"Sharpe={simbroker_sharpe:.3f} {'≥' if sharpe_pass else '<'} {G7_SHARPE_BASELINE}(基线)",
        ]
        if bootstrap_p_value is not None:
            reason_parts.append(
                f"bootstrap p={bootstrap_p_value:.3f} {'< 0.05 OK' if bootstrap_pass else '>= 0.05 FAIL'}"
            )

        report.gates["G7"] = GateResult(
            "G7", GateStatus.PASS if passed else GateStatus.FAIL,
            "simbroker_sharpe", simbroker_sharpe, G7_SHARPE_BASELINE,
            " | ".join(reason_parts),
            data={
                "simbroker_sharpe": simbroker_sharpe,
                "baseline_sharpe": G7_SHARPE_BASELINE,
                "bootstrap_p_value": bootstrap_p_value,
            },
        )
        report.overall_status = self._compute_overall_status(report)
        return report

    def confirm_g8(
        self,
        report: GateReport,
        signal_type: str,
        rebalance_freq: str,
        strategy_notes: str = "",
    ) -> GateReport:
        """G8 strategy策略匹配确认（铁律8）。

        Args:
            report: 待更新的GateReport。
            signal_type: FactorClassifier输出的信号类型（ranking/event/modifier等）。
            rebalance_freq: 推荐调仓频率（daily/weekly/monthly/event）。
            strategy_notes: strategy角色的审查备注。

        Returns:
            更新后的GateReport。
        """
        confirmed = bool(signal_type) and bool(rebalance_freq)

        report.gates["G8"] = GateResult(
            "G8", GateStatus.PASS if confirmed else GateStatus.FAIL,
            "strategy_match", 1.0 if confirmed else 0.0, 1.0,
            f"signal_type={signal_type}, rebalance_freq={rebalance_freq}. {strategy_notes}",
            data={
                "signal_type": signal_type,
                "rebalance_freq": rebalance_freq,
                "strategy_notes": strategy_notes,
            },
        )
        report.overall_status = self._compute_overall_status(report)
        return report

    # ----------------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------------

    def _bh_fdr_t_threshold(self, m: int) -> float:
        """计算BH-FDR动态t统计量阈值。

        DEV_FACTOR_MINING §13.1: adjusted_t = base_t + log(N) × 0.3 (N>20时)
        base_t = 2.0（G3宽松筛选用）。
        """
        if m <= BH_FDR_N_TRIGGER:
            return BH_FDR_BASE_T
        return BH_FDR_BASE_T + math.log(m) * BH_FDR_LOG_SCALE

    def _compute_overall_status(self, report: GateReport) -> str:
        """计算综合状态。

        逻辑:
        - 任何自动Gate (G1-G5) FAIL → "FAIL"
        - 所有G1-G5 PASS但有PENDING → "PARTIAL"（等待人工审查）
        - 所有G1-G8 PASS → "PASS"
        - 混合FAIL+PENDING → "FAIL"
        """
        statuses = {gid: r.status for gid, r in report.gates.items()}

        auto_statuses = [statuses.get(f"G{i}") for i in range(1, 6)]
        semi_statuses = [statuses.get(f"G{i}") for i in range(6, 9)]

        # 任何自动Gate FAIL → 整体FAIL
        if any(s == GateStatus.FAIL for s in auto_statuses if s is not None):
            return "FAIL"

        # 半自动Gate中有FAIL → 整体FAIL
        if any(s == GateStatus.FAIL for s in semi_statuses if s is not None):
            return "FAIL"

        # 有PENDING → PARTIAL
        if any(s == GateStatus.PENDING for s in semi_statuses if s is not None):
            return "PARTIAL"

        # 全PASS
        all_pass = all(
            statuses.get(f"G{i}") == GateStatus.PASS
            for i in range(1, 9)
        )
        return "PASS" if all_pass else "PARTIAL"

    # ----------------------------------------------------------------
    # 批量验证接口（BruteForce引擎集成）
    # ----------------------------------------------------------------

    def quick_screen(
        self,
        factor_name: str,
        ic_series: list[float],
        active_factor_corr: dict[str, float] | None = None,
        registry_path: str | None = None,
    ) -> tuple[bool, str]:
        """G1-G3快筛（BruteForce引擎用，<1ms per factor）。

        Returns:
            (passed, reason): passed=True表示通过G1-G3快筛。
        """
        if not ic_series:
            return False, "ic_series空"

        ic_arr = np.array(ic_series, dtype=float)
        ic_arr = ic_arr[~np.isnan(ic_arr)]
        if len(ic_arr) < 5:
            return False, f"样本不足n={len(ic_arr)}"

        ic_mean = float(np.mean(ic_arr))
        ic_std = float(np.std(ic_arr, ddof=1))
        n = len(ic_arr)
        t_stat = ic_mean / (ic_std / math.sqrt(n)) if ic_std > 0 else 0.0

        # G1
        if abs(ic_mean) <= G1_IC_THRESHOLD:
            return False, f"G1 FAIL: |IC|={abs(ic_mean):.4f}<={G1_IC_THRESHOLD}"

        # G2
        if active_factor_corr:
            max_corr = max(abs(v) for v in active_factor_corr.values())
            if max_corr >= G2_CORR_THRESHOLD:
                return False, f"G2 FAIL: max_corr={max_corr:.4f}>={G2_CORR_THRESHOLD}"

        # G3（宽松）
        try:
            m = get_cumulative_test_count(registry_path=registry_path)
        except (FileNotFoundError, ValueError):
            m = 74
        threshold = self._bh_fdr_t_threshold(m)
        if abs(t_stat) <= threshold:
            return False, f"G3 FAIL: |t|={abs(t_stat):.3f}<={threshold:.3f}"

        return True, f"G1-G3 PASS: |IC|={abs(ic_mean):.4f}, |t|={abs(t_stat):.3f}"
