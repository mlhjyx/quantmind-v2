"""因子生命周期状态转换 — 纯规则 (铁律 31).

根据 DEV_AI_EVOLUTION V2.1 §3.1 实现 L1-auto 状态转换:
    active  →  warning    (|IC_MA20| < |IC_MA60| × 0.8)
    warning →  critical   (|IC_MA20| < |IC_MA60| × 0.5 持续 20 天)
    warning →  active     (恢复: ratio 回到 ≥ 0.8)

critical → retired 需 L2 人确认, 本模块不包含.

状态值与 DDL factor_registry.status 对齐:
    candidate / active / warning / critical / retired

输入/输出均为原生 Python 类型, 可单元测试, 无 IO.

MVP 3.5 batch 2 (Session 42 2026-04-28) 双路径并存接 PlatformEvaluationPipeline:
  - 老路径 (本文件 evaluate_transition / count_days_below_critical) 不破, 4 周观察期内决策权威
  - 新路径 (default_lifecycle_pipeline + build_lifecycle_context + compare_paths)
    调 qm_platform.eval Pipeline (G1 IC t>2.5 + G3 paired bootstrap + G10 hypothesis), 仅 log
  - mismatch 由 monitor 告警, 4 周比对 < 5% 后 batch 3+ sunset 老路径
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qm_platform.eval import GateContext, PlatformEvaluationPipeline


class FactorStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    WARNING = "warning"
    CRITICAL = "critical"
    RETIRED = "retired"


# Thresholds per DEV_AI_EVOLUTION V2.1 §3.1
WARNING_RATIO = 0.8   # |IC_MA20|/|IC_MA60| < 0.8 → warning (轻度衰减)
CRITICAL_RATIO = 0.5  # |IC_MA20|/|IC_MA60| < 0.5 → critical (需持续)
CRITICAL_PERSISTENCE_DAYS = 20
MIN_ABS_IC_MA60 = 1e-6  # 基线 IC ≈ 0 时比率无意义


@dataclass(frozen=True)
class TransitionDecision:
    """状态转换决策."""

    factor_name: str
    from_status: str
    to_status: str
    reason: str
    ic_ma20: float
    ic_ma60: float
    ratio: float


def evaluate_transition(
    factor_name: str,
    current_status: str,
    ic_ma20: float | None,
    ic_ma60: float | None,
    days_below_critical: int = 0,
) -> TransitionDecision | None:
    """判定因子状态转换.

    Args:
        factor_name: 因子名.
        current_status: 当前状态 (candidate/active/warning/critical/retired).
        ic_ma20: 最新 20 日 IC 移动平均, None 表示无数据.
        ic_ma60: 最新 60 日 IC 移动平均, None 表示无数据.
        days_below_critical: 最近连续满足 |IC_MA20| < |IC_MA60|×0.5 的天数,
            用于 warning → critical 的持续性判定.

    Returns:
        TransitionDecision 如需转换, None 如无变化或数据不足.
    """
    if ic_ma20 is None or ic_ma60 is None:
        return None
    if abs(ic_ma60) < MIN_ABS_IC_MA60:
        return None  # 基线 IC ≈ 0, 比率不稳定

    ratio = abs(ic_ma20) / abs(ic_ma60)

    if current_status == FactorStatus.ACTIVE.value:
        if ratio < WARNING_RATIO:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=current_status,
                to_status=FactorStatus.WARNING.value,
                reason=f"|IC_MA20|/|IC_MA60|={ratio:.3f} < {WARNING_RATIO}",
                ic_ma20=ic_ma20,
                ic_ma60=ic_ma60,
                ratio=ratio,
            )
        return None

    if current_status == FactorStatus.WARNING.value:
        if ratio < CRITICAL_RATIO and days_below_critical >= CRITICAL_PERSISTENCE_DAYS:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=current_status,
                to_status=FactorStatus.CRITICAL.value,
                reason=(
                    f"|IC_MA20|/|IC_MA60|={ratio:.3f} < {CRITICAL_RATIO} "
                    f"持续 {days_below_critical} 天"
                ),
                ic_ma20=ic_ma20,
                ic_ma60=ic_ma60,
                ratio=ratio,
            )
        if ratio >= WARNING_RATIO:
            return TransitionDecision(
                factor_name=factor_name,
                from_status=current_status,
                to_status=FactorStatus.ACTIVE.value,
                reason=f"|IC_MA20|/|IC_MA60|={ratio:.3f} ≥ {WARNING_RATIO} (恢复)",
                ic_ma20=ic_ma20,
                ic_ma60=ic_ma60,
                ratio=ratio,
            )
        return None

    # candidate / critical / retired: 不做 L1 自动转换
    return None


def count_days_below_critical(ic_ratios: list[float], lookback_days: int = 30) -> int:
    """计算最近 lookback_days 天中连续 ratio < CRITICAL_RATIO 的天数 (从最新往回数).

    用于 warning → critical 的持续性判定.

    Args:
        ic_ratios: 时间序列的 |IC_MA20|/|IC_MA60| 比率, 从旧到新.
        lookback_days: 最多回溯天数.

    Returns:
        从最新一天向前数, 连续满足 ratio < CRITICAL_RATIO 的天数.
    """
    if not ic_ratios:
        return 0
    tail = ic_ratios[-lookback_days:]
    count = 0
    for r in reversed(tail):
        if r < CRITICAL_RATIO:
            count += 1
        else:
            break
    return count


# ============================================================================
# MVP 3.5 batch 2 (Session 42 2026-04-28) — 双路径接 PlatformEvaluationPipeline
# ============================================================================
#
# 设计意图:
#   - 老路径 (上方 evaluate_transition) 4 周观察期内决策权威, 不破
#   - 新路径 (下方 default_lifecycle_pipeline + build_lifecycle_context + compare_paths)
#     调 qm_platform.eval 跑 G1 + G3 + G10, 仅 log + mismatch 告警
#   - lazy import qm_platform.eval (避免 engines/ import 时 transitively 拉 platform 链路)


@dataclass(frozen=True)
class DualPathComparison:
    """双路径比对结果 (batch 2 4 周观察期).

    Args:
      factor_name: 因子名.
      old_label: 老路径等价 label ('keep' / 'demote').
      new_label: 新路径等价 label ('keep' / 'demote' / 'unknown').
      old_decision: 原始 TransitionDecision (None 表示老路径无变化).
      new_decision_value: 新路径 EvaluationReport.decision.value (accept/reject/warning).
      consistent: True 若 old_label == new_label (含 unknown 视为不一致).
      mismatch_summary: 不一致时的简短描述, 一致时为 None.
    """

    factor_name: str
    old_label: str
    new_label: str
    old_decision: TransitionDecision | None
    new_decision_value: str
    consistent: bool
    mismatch_summary: str | None


def _old_path_label(decision: TransitionDecision | None) -> str:
    """老路径 TransitionDecision → 等价 label.

    - None (无变化): 'keep'
    - to=active (warning→active 恢复): 'keep' (因子健康)
    - to=warning / critical: 'demote'
    """
    if decision is None:
        return "keep"
    if decision.to_status == FactorStatus.ACTIVE.value:
        return "keep"
    return "demote"


def _new_path_label(report: Any) -> str:
    """新路径 EvaluationReport → 等价 label.

    - decision=ACCEPT (全 Gate PASS): 'keep'
    - decision=REJECT (≥1 hard fail): 'demote'
    - decision=WARNING (data_unavailable): 'unknown' (不下定论, 比对中视为 mismatch)
    - 其他 / None: 'unknown'
    """
    decision = getattr(report, "decision", None)
    if decision is None:
        return "unknown"
    val = decision.value if hasattr(decision, "value") else str(decision)
    return {"accept": "keep", "reject": "demote", "warning": "unknown"}.get(val, "unknown")


def compare_paths(
    factor_name: str,
    old_decision: TransitionDecision | None,
    new_report: Any,
) -> DualPathComparison:
    """比对双路径决策 (纯函数, 不 raise, 调用方负责告警).

    一致条件: _old_path_label(old) == _new_path_label(new) (含 'unknown' 视为不一致).

    Args:
      factor_name: 因子名 (用于 log).
      old_decision: 老路径输出 (None 表示老路径无变化).
      new_report: 新路径输出 (EvaluationReport, 鸭子类型 — 取 decision.value).

    Returns:
      DualPathComparison frozen dataclass.
    """
    old_label = _old_path_label(old_decision)
    new_label = _new_path_label(new_report)
    consistent = old_label == new_label
    new_decision_value = "unknown"
    decision_attr = getattr(new_report, "decision", None)
    if decision_attr is not None:
        new_decision_value = (
            decision_attr.value if hasattr(decision_attr, "value") else str(decision_attr)
        )
    summary = (
        None
        if consistent
        else f"old={old_label} vs new={new_label} (new_decision={new_decision_value})"
    )
    return DualPathComparison(
        factor_name=factor_name,
        old_label=old_label,
        new_label=new_label,
        old_decision=old_decision,
        new_decision_value=new_decision_value,
        consistent=consistent,
        mismatch_summary=summary,
    )


def build_lifecycle_context(
    factor_name: str,
    *,
    ic_series: Any = None,
    ic_baseline_series: Any = None,
    factor_meta: Any = None,
    registry: Any = None,
) -> GateContext:
    """构造 lifecycle 评估的 GateContext (engines/ 层 helper).

    Args:
      factor_name: 因子名.
      ic_series: 时间序列 IC (np.ndarray, G1 / G3 用).
      ic_baseline_series: baseline IC 时间序列 (G3 用, 缺则 G3 → data_unavailable).
      factor_meta: FactorMeta (G10 用 hypothesis 字段).
      registry: FactorRegistry (G9 用 — 默认 lifecycle pipeline 不含 G9, 留扩展).

    Returns:
      qm_platform.eval.GateContext.
    """
    from qm_platform.eval import GateContext  # lazy import 避 engines top-import 拉 platform

    return GateContext(
        factor_name=factor_name,
        factor_meta=factor_meta,
        ic_series=ic_series,
        ic_baseline_series=ic_baseline_series,
        registry=registry,
    )


# ============================================================================
# MVP 3.5 Follow-up B (Session 43 2026-04-28) — OR 复合决策规则
# ============================================================================
#
# 来源: PR #127 12 周历史回放发现老/新路径测互补现象 (225 P1 reverse: 老 demote/
# 新 keep, 新漏掉 decay 信号). 不能 sunset 老路径, 应改 OR 复合 (任一 demote → demote).
#
# 设计意图:
#   - 老路径 evaluate_transition 测 IC decay (regime/crowding 检测)
#   - 新路径 G1 测 IC 绝对显著性 (Harvey 2016 t > 2.5), G10 测 hypothesis 完整性
#   - OR 复合: 任一路径判 demote → demote
#   - 模式分级: off (本 PR 默认, 兼容生产) / g1-only (仅 G1 fail 触发, 防 hypothesis
#     缺失因子降级) / strict (G1 OR G10 fail 触发)
#
# 本 PR 仅交付**纯函数 + replay 分析支持**, 不改生产 run() 行为. Phase 2 单独 PR
# wire 到 production (要求实战 replay 见 demote count 合理).


class CompositeMode(StrEnum):
    """OR 复合决策模式."""

    OFF = "off"          # 仅老路径 (生产兼容默认)
    G1_ONLY = "g1-only"  # 老 OR (G1 fail) — 防 G10 hypothesis 缺失批量降级
    STRICT = "strict"    # 老 OR (G1 OR G10 fail)


# Gate names matching qm_platform.eval.gates.{g1_ic_significance,g10_hypothesis}.name
G1_GATE_NAME = "G1_ic_significance"
G10_GATE_NAME = "G10_hypothesis"


def extract_failed_gate_names(report: Any) -> set[str]:
    """从 EvaluationReport 提取未通过 Gate 名集合.

    Args:
      report: qm_platform.eval.EvaluationReport (鸭子类型 — 取 .gate_results).
        每 GateResult 必有 .gate_name 和 .passed 属性.

    Returns:
      未通过 Gate 名集合 (e.g. {"G1_ic_significance"}). report=None 或缺
      gate_results → 空集合 (fail-safe).
    """
    if report is None:
        return set()
    results = getattr(report, "gate_results", None)
    if not results:
        return set()
    return {r.gate_name for r in results if not getattr(r, "passed", True)}


def compute_composite_decision(
    factor_name: str,
    current_status: str,
    old_decision: TransitionDecision | None,
    new_report: Any,
    mode: CompositeMode = CompositeMode.OFF,
    *,
    ic_ma20: float | None = None,
    ic_ma60: float | None = None,
) -> TransitionDecision | None:
    """OR 复合决策 — 老路径 OR 新路径任一 demote → demote.

    决策语义:
      - mode=OFF: 直接返 old_decision (老路径权威, 生产 backward-compat)
      - mode=G1_ONLY: 老 demote OR (G1_ic_significance fail) → 老 demote 时返
        old_decision; 新路径 G1 fail 但老路径 keep 时合成 active→warning
        (TransitionDecision reason 标 'composite_g1_only').
      - mode=STRICT: 老 demote OR (G1 OR G10 fail) → 同上但 G10 也参与触发.

    Args:
      factor_name: 因子名 (合成决策用).
      current_status: 当前状态 (active/warning/critical/...). 仅 active 状态新路径
        可触发 demote (warning/critical 已是 demoted, 由老路径主导持续性升级).
      old_decision: 老路径输出 (None 或 TransitionDecision).
      new_report: 新路径 EvaluationReport (取 gate_results).
      mode: 复合模式.
      ic_ma20 / ic_ma60: 合成决策时填入 TransitionDecision 字段 (审计/log 用),
        缺省 NaN. 不参与判定.

    Returns:
      TransitionDecision (老或合成) 或 None (无变化).
    """
    # OFF mode: 透传老决策, 生产兼容
    if mode == CompositeMode.OFF:
        return old_decision

    # 计算新路径触发集 (G1_ONLY 仅 G1 / STRICT 含 G10)
    failed_gates = extract_failed_gate_names(new_report)
    triggers: set[str] = set()
    if mode == CompositeMode.G1_ONLY:
        if G1_GATE_NAME in failed_gates:
            triggers.add(G1_GATE_NAME)
    elif mode == CompositeMode.STRICT:
        if G1_GATE_NAME in failed_gates:
            triggers.add(G1_GATE_NAME)
        if G10_GATE_NAME in failed_gates:
            triggers.add(G10_GATE_NAME)

    # P1.1 fix (reviewer 2026-04-28 PR #128): 老路径 warning→active recovery 路径
    # 若新路径 triggers 非空 → suppress recovery (因子留在 warning, 不应自动恢复).
    # 设计意图: ratio 已恢复 (decay 逆转) 但 G1 仍 fail (absolute insignificance) → 保守
    # 保持 demoted, 防 "ratio 假恢复 + 真无效" 的误恢复.
    if (
        old_decision is not None
        and old_decision.from_status == FactorStatus.WARNING.value
        and old_decision.to_status == FactorStatus.ACTIVE.value
        and triggers
    ):
        return None  # suppress recovery, factor stays in warning

    # 老路径已 demote (warning/critical) → 直接返 (老路径优先权: 含 ic_ma20/60/ratio 实数据)
    if old_decision is not None and old_decision.to_status != FactorStatus.ACTIVE.value:
        return old_decision

    # 新路径合成只在 active 状态 (warning/critical 已是 demoted, 由老路径主导持续性升级)
    if current_status != FactorStatus.ACTIVE.value:
        return old_decision  # 可能 None (active→active 无变化, 或 warning→active recovery 无 trigger)

    if not triggers:
        # 新路径未触发, 老路径也无变化 → 透传
        return old_decision

    # 合成 active → warning (新路径检测到 absolute insignificance / hypothesis 缺失)
    # P2.2 fix (reviewer 2026-04-28 PR #128): 显式 math.isnan 检查 (NaN 截true 但
    # 比较 False, 原 `if safe_ma60` 真路径 coincidental).
    import math as _math

    safe_ma20 = float(ic_ma20) if ic_ma20 is not None else float("nan")
    safe_ma60 = float(ic_ma60) if ic_ma60 is not None else float("nan")
    safe_ratio = (
        abs(safe_ma20) / abs(safe_ma60)
        if not _math.isnan(safe_ma60) and abs(safe_ma60) >= MIN_ABS_IC_MA60
        else float("nan")
    )
    reason = f"composite_{mode.value} triggered by {sorted(triggers)}"

    return TransitionDecision(
        factor_name=factor_name,
        from_status=current_status,
        to_status=FactorStatus.WARNING.value,
        reason=reason,
        ic_ma20=safe_ma20,
        ic_ma60=safe_ma60,
        ratio=safe_ratio,
    )


def default_lifecycle_pipeline(
    context_loader: Any,
) -> PlatformEvaluationPipeline:
    """构造 lifecycle 默认评估 pipeline (G1 + G10) — batch 2 双路径用.

    选择 Gate 集理由 (lifecycle 上下文可用数据):
      - G1 IC 显著性 t > 2.5 (Harvey Liu Zhu 2016) — ic_series 来自 factor_ic_history
      - G10 hypothesis 描述 (铁律 13) — factor_registry.hypothesis 字段

    G3 paired bootstrap 需 ic_baseline_series (lifecycle 上下文无现成 CORE baseline,
    若强加会导致所有因子 G3 data_unavailable → WARNING → 与老路径 demote 比对全 mismatch),
    故 G3 留 SDK 给有 baseline 的 caller (如 onboarding pipeline). 同理跳过 G2/G4/G8/G9.

    调用方可自构 PlatformEvaluationPipeline 添加更多 Gate.

    Args:
      context_loader: Callable[[str], GateContext] — 调用方按 factor_name 提供 ctx.

    Returns:
      PlatformEvaluationPipeline 实例 (含 G1 + G10).
    """
    from qm_platform.eval import (  # lazy import (engines top-import 不拉 platform)
        G1IcSignificanceGate,
        G10HypothesisGate,
        PlatformEvaluationPipeline,
    )

    return PlatformEvaluationPipeline(
        gates=[
            G1IcSignificanceGate(),
            G10HypothesisGate(),
        ],
        context_loader=context_loader,
    )
