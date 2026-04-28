"""Framework #4 Eval — Gate ABC + GateContext.

Gate 是 pure function, 不 raise (异常包成 GateResult details["error"]).
GateContext frozen dataclass, 所有字段 Optional, gates 缺数据返 GateResult(passed=False, details={"reason": "data_unavailable"}).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from ..interface import GateResult

if TYPE_CHECKING:
    from ...factor.interface import FactorMeta, FactorRegistry


class GateError(RuntimeError):  # noqa: N818 — 语义优先, 与 Platform OnboardingBlocked 同策略
    """Gate evaluation 内部错误 (非 PASS/FAIL, 是数据缺失/IO 失败).

    通常 Gate.evaluate 不 raise, 而是返 GateResult(passed=False, details={"error": str}).
    GateError 仅供 Gate 实现内部使用, Pipeline 顶层捕获包成 GateResult.
    """


@dataclass(frozen=True)
class GateContext:
    """Gate 评估上下文 — 含所有 Gate 可能用到的输入.

    所有字段 Optional, Gate 应检查所需字段是否存在 (None → 返 details["reason"]="data_unavailable").

    Args:
      factor_name: 被评估因子名 (G1/G2/G3/G4/G8 必需).
      factor_meta: 因子元信息 (G9/G10 必需, 含 expression / hypothesis).
      ic_series: 时间序列 IC (np.ndarray, G1/G3 必需).
      ic_baseline_series: 基线 IC 时间序列 (G3 必需, 同长度对齐 ic_series).
      active_corr_max: 与现存 active 因子最大 |corr| (G2 必需).
      monthly_return_corr_max: 选股月收益与 active 池最大 |corr| (G2 可选).
      wf_oos_sharpe: WF 5-fold OOS Sharpe (G4 必需).
      wf_baseline_sharpe: WF baseline Sharpe (G4 必需).
      bh_fdr_rank: 当前因子在累积测试中的 BH 排名 (G8 必需, 1-indexed).
      bh_fdr_m: 累积测试总数 M (G8 必需).
      bh_fdr_p_value: 因子检验 p 值 (G8 必需).
      registry: FactorRegistry 实例 (G9 用 novelty_check 复用 MVP 1.3c).
      extra: 业务特化扩展 (avoid 字段膨胀).
    """

    factor_name: str
    factor_meta: FactorMeta | None = None
    ic_series: np.ndarray | None = None
    ic_baseline_series: np.ndarray | None = None
    active_corr_max: float | None = None
    monthly_return_corr_max: float | None = None
    wf_oos_sharpe: float | None = None
    wf_baseline_sharpe: float | None = None
    bh_fdr_rank: int | None = None
    bh_fdr_m: int | None = None
    bh_fdr_p_value: float | None = None
    registry: FactorRegistry | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Gate(ABC):
    """Gate ABC — 单个评估门.

    实现规范:
      - evaluate() 是 pure function, 不 raise (异常包成 GateResult details["error"])
      - 数据缺失 → GateResult(passed=False, threshold=None, observed=None, details={"reason": "data_unavailable", "missing": [...]})
      - 业务 fail → GateResult(passed=False, threshold=阈值, observed=实测, details={"reason": 理由})
      - PASS → GateResult(passed=True, threshold=阈值, observed=实测, details={...})
    """

    name: str  # subclass 必填, e.g. "G1_ic_significance"
    threshold: float | None = None  # None 表示无单值阈值 (e.g. G9 用相似度)

    @abstractmethod
    def evaluate(self, ctx: GateContext) -> GateResult:
        """评估 Gate, 返 GateResult."""

    def _data_unavailable(self, missing: list[str]) -> GateResult:
        """统一缺数据返回 (gates 共用 helper)."""
        return GateResult(
            gate_name=self.name,
            passed=False,
            threshold=self.threshold,
            observed=None,
            details={"reason": "data_unavailable", "missing": missing},
        )
