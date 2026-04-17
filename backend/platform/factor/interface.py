"""Framework #2 Factor — 因子全生命周期 (idea → active → warning → retired).

目标: 因子元数据机器可控, 替代散落 5+ 处的 hardcoded DIRECTION dict.

关联铁律:
  - 11: IC 必须有可追溯的入库记录
  - 12: G9 Gate 新颖性可证明性
  - 13: G10 Gate 市场逻辑可解释性
  - 34: 配置 single source of truth (direction/pool 只有一处真相)

实施时机:
  - MVP 1.3 Factor Framework: FactorRegistry + FactorOnboardingPipeline 完整实施
  - MVP A (已落地): FactorLifecycleMonitor 纯规则 engine, 迁移到此 interface 作 Phase C 任务
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID


class FactorStatus(Enum):
    """因子生命周期状态.

    - CANDIDATE: idea 阶段, 未跑 IC
    - TESTING: 正在跑 IC / 中性化 / G_robust
    - WARNING: 活跃因子衰减 (ratio < 0.5 vs 历史均值)
    - ACTIVE: 生产在用
    - DEPRECATED: 被替代 (e.g. CORE5 → CORE3+dv_ttm)
    - INVALIDATED: 证伪 (e.g. mf_divergence)
    - RETIRED: 主动退役
    """

    CANDIDATE = "candidate"
    TESTING = "testing"
    WARNING = "warning"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    INVALIDATED = "invalidated"
    RETIRED = "retired"


@dataclass(frozen=True)
class FactorSpec:
    """因子规格 (onboarding 输入).

    Args:
      name: 唯一因子名 (snake_case, e.g. "turnover_mean_20")
      hypothesis: 经济机制假设 (铁律 13 必填)
      expression: 计算表达式 (FactorDSL 或 Python function 引用)
      direction: +1 / -1 (IC 符号预期)
      category: "量价" / "基本面" / "事件" / "微结构"
      pool: "CORE" / "CORE5_baseline" / "PASS" / "CANDIDATE" 等
      author: 提出人 / Agent ID
    """

    name: str
    hypothesis: str
    expression: str
    direction: int
    category: str
    pool: str
    author: str


@dataclass(frozen=True)
class FactorMeta:
    """因子注册后的完整元数据 (对齐 live PG factor_registry 18 字段).

    MVP 1.3a: 字段对齐 DB (之前设计与 DB 有 6 处 drift, MVP 1.3a 修正):
      - 新增 `pool` (生命周期池, 替代原 FactorSpec.pool, MVP 1.3a ALTER TABLE 加)
      - 新增 `expression/code_content/source/lookback_days/gate_*` (DB 原有, interface 补)
      - 字段名对齐 DB: `registered_at` → `created_at`, `ic_mean` → `gate_ic`

    Args:
      factor_id: UUID 主键
      name: 因子名 (从 FactorSpec 提升到 Meta 顶层, 消费方常用)
      category: 细分类 (risk / liquidity / fundamental / microstructure / ...)
      direction: +1 / -1 (IC 符号预期)
      expression: 计算表达式 (FactorDSL / Python 引用)
      code_content: 代码实现 (若有, GP 生成的因子)
      hypothesis: 经济机制假设 (铁律 13 必填)
      source: 来源标识 (builtin / gp / llm / manual)
      lookback_days: 计算所需历史窗口 (默认 60)
      status: 生命周期状态
      pool: 生命周期池 (CORE/PASS/CANDIDATE/INVALIDATED/DEPRECATED/LEGACY)
      gate_ic: 历史 IC 均值 (neutral, T+1 excess, spearman, 铁律 19)
      gate_ir: IC / IC std (信息比率)
      gate_mono: 单调性 (decile monotone 得分)
      gate_t: t 统计量 (Harvey Liu Zhu t>2.5 硬下限检查)
      ic_decay_ratio: 近期 IC / 历史 IC 绝对值比 (lifecycle <0.5 → WARNING)
      created_at: DB 记录创建时间 (ISO)
      updated_at: 最后更新时间
    """

    factor_id: UUID
    name: str
    category: str
    direction: int
    expression: str | None
    code_content: str | None
    hypothesis: str | None
    source: str
    lookback_days: int | None
    status: FactorStatus
    pool: str
    gate_ic: float | None
    gate_ir: float | None
    gate_mono: float | None
    gate_t: float | None
    ic_decay_ratio: float | None
    created_at: str
    updated_at: str

    @property
    def registered_at(self) -> str:
        """向后兼容 alias — 老代码用 `.registered_at`, DB 真实字段是 `created_at`."""
        return self.created_at

    @property
    def ic_mean(self) -> float | None:
        """向后兼容 alias — 老代码用 `.ic_mean`, DB 真实字段是 `gate_ic`."""
        return self.gate_ic


@dataclass(frozen=True)
class OnboardResult:
    """FactorOnboardingPipeline.onboard 输出.

    Args:
      factor_id: 注册后的 UUID
      passed_gates: 通过的 Gate 清单 (G1..G10)
      blockers: 未过的 Gate 清单
      ic_clean: 去中性化前 raw IC
      ic_neutral: 中性化后 IC (决策依据, 铁律 19)
      g_robust_retention_20pct: 20% 噪声下 retention (铁律 20)
      details: 扩展字段 (如 行业 IC 分布 / regime IC)
    """

    factor_id: UUID
    passed_gates: list[str]
    blockers: list[str]
    ic_clean: float | None
    ic_neutral: float | None
    g_robust_retention_20pct: float | None
    details: dict[str, Any]


@dataclass(frozen=True)
class TransitionDecision:
    """生命周期状态转换决策 (FactorLifecycleMonitor 输出).

    Args:
      factor_name: 被评估因子
      from_status: 当前状态
      to_status: 建议新状态
      reason: 变更原因 (人类可读, e.g. "IC decay ratio=0.43 < 0.5")
      metrics: 支撑数据 (ic_recent / ic_hist_mean / corr_with_active 等)
    """

    factor_name: str
    from_status: FactorStatus
    to_status: FactorStatus
    reason: str
    metrics: dict[str, Any]


class FactorRegistry(ABC):
    """因子注册表 — 替代散落的 DIRECTION / FACTOR_POOL hardcoded dict.

    关联铁律 12 / 13 / 34.
    """

    @abstractmethod
    def register(self, spec: FactorSpec) -> UUID:
        """注册新因子, 返回 UUID.

        Raises:
          DuplicateFactor: spec.name 已注册
          NoveltyViolation: G9 Gate 未过 (AST 相似度 > 0.7)
        """

    @abstractmethod
    def get_active(self) -> list[FactorMeta]:
        """返回当前 ACTIVE 状态的所有因子 (PT 生产在用)."""

    @abstractmethod
    def get_direction(self, name: str) -> int:
        """读因子方向 +1 / -1.

        铁律 34: 这是 direction 的唯一真相源, 替代所有 _constants.py hardcoded.
        """

    @abstractmethod
    def update_status(self, name: str, new_status: FactorStatus, reason: str) -> None:
        """变更因子状态 (带审计日志).

        Raises:
          FactorNotFound: name 未注册
          InvalidTransition: 非法转换 (e.g. RETIRED → ACTIVE)
        """

    @abstractmethod
    def novelty_check(self, spec: FactorSpec) -> bool:
        """G9 Gate — AST 相似度 + 语义相似度.

        Returns:
          True 若新颖 (相似度 < 0.7), False 若与现有因子近似
        """


class FactorOnboardingPipeline(ABC):
    """因子入库一条龙 — register → compute → neutralize → IC → G_robust → gate.

    新因子走此路径强制 onboarding, 不能绕路 (铁律 17).
    """

    @abstractmethod
    def onboard(self, spec: FactorSpec) -> OnboardResult:
        """执行完整 onboarding 流程.

        步骤 (严格顺序):
          1. FactorRegistry.novelty_check (G9, 铁律 12)
          2. 经济机制 review (G10, 铁律 13, 当前人工)
          3. 计算 raw_value → 走 DataPipeline 入 factor_values
          4. 中性化 (MAD → fill → WLS industry+ln_mcap → zscore → clip)
          5. IC (neutral_value, T+1 excess, spearman, 铁律 19)
          6. G_robust 噪声鲁棒性 (铁律 20)
          7. paired bootstrap p < 0.05 (铁律 5)
          8. BH-FDR 累积校正 (t > 2.5 硬下限)

        Raises:
          OnboardingBlocked: 任一 Gate 失败, blockers 列出原因
        """


class FactorLifecycleMonitor(ABC):
    """生命周期周期性巡检 — 检测衰减 / 晋升 / 退役.

    触发: Celery Beat 每周五 19:00 (已在 MVP A 落地, backend/engines/factor_lifecycle.py).
    """

    @abstractmethod
    def evaluate_all(self) -> list[TransitionDecision]:
        """扫描所有 ACTIVE + WARNING 因子, 产出状态转换建议.

        规则:
          - ACTIVE → WARNING: ic_decay_ratio < 0.5 持续 ≥ 2 个月
          - WARNING → DEPRECATED: 持续 ≥ 3 个月无恢复
          - CANDIDATE → ACTIVE: onboarding 全过 + 纳入 PT 配置
        """
