"""RiskControlService — 4级熔断风控Service。

DESIGN_V5 §8.1 定义的4级熔断状态机:
  L1: 单策略日亏>3% → 暂停1天(次日自动恢复)
  L2: 总组合日亏>5% → 全部暂停(次日自动恢复)
  L3: 滚动5日亏>7% OR 滚动20日亏>10% → 降仓50%, 恢复条件: 连续3天盈利>1.5%
  L4: 累计亏>25% → 停止所有交易, 人工审批

遵循CLAUDE.md: async/await + 类型注解 + Google docstring(中文) + Depends注入。
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.risk_repository import RiskRepository
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 枚举 & 数据结构
# ─────────────────────────────────────────────


class CircuitBreakerLevel(enum.IntEnum):
    """熔断级别。数值越大越严重。"""

    NORMAL = 0
    L1_PAUSED = 1  # 单策略日亏>3%, 暂停1天
    L2_HALTED = 2  # 总组合日亏>5%, 全部暂停
    L3_REDUCED = 3  # 月亏>10%, 降仓50%
    L4_STOPPED = 4  # 累计>25%, 停止交易


class TransitionType(enum.StrEnum):
    """状态变更类型。"""

    ESCALATE = "escalate"  # 升级(恶化)
    RECOVER = "recover"  # 自动恢复
    MANUAL = "manual"  # 人工审批恢复/强制重置


@dataclass(frozen=True)
class CircuitBreakerState:
    """熔断状态快照。"""

    level: CircuitBreakerLevel
    entered_date: date
    trigger_reason: str
    trigger_metrics: dict[str, Any]
    position_multiplier: Decimal
    recovery_streak_days: int
    recovery_streak_return: Decimal
    can_rebalance: bool
    approval_id: UUID | None

    @property
    def is_normal(self) -> bool:
        """是否处于正常状态。"""
        return self.level == CircuitBreakerLevel.NORMAL

    @property
    def requires_manual_approval(self) -> bool:
        """是否需要人工审批才能恢复。"""
        return self.level == CircuitBreakerLevel.L4_STOPPED


@dataclass(frozen=True)
class RiskMetrics:
    """每日风控指标，由调用方组装后传入。"""

    trade_date: date
    daily_return: Decimal  # 当日策略收益率
    nav: Decimal  # 当日净值
    initial_capital: Decimal  # 初始资金
    cumulative_return: Decimal  # 累计收益率 (nav/initial - 1)
    rolling_5d_return: Decimal | None = None  # 滚动5日累计收益率(不足5日传None)
    rolling_20d_return: Decimal | None = None  # 滚动20日累计收益率(不足20日传None)
    portfolio_vol_20d: float | None = None  # 组合近20日年化波动率(用于自适应阈值)


@dataclass(frozen=True)
class CircuitBreakerTransition:
    """一次状态变更事件。"""

    strategy_id: UUID
    execution_mode: str
    trade_date: date
    prev_level: CircuitBreakerLevel
    new_level: CircuitBreakerLevel
    transition_type: TransitionType
    reason: str
    metrics: dict[str, Any]


@dataclass(frozen=True)
class CircuitBreakerThresholds:
    """熔断阈值配置。

    硬编码默认值来自 DESIGN_V5 §8.1, AI无权修改(Level 0硬编码)。
    """

    l1_daily_loss: Decimal = Decimal("-0.03")
    l2_daily_loss: Decimal = Decimal("-0.05")
    l3_rolling_loss: Decimal = Decimal("-0.10")
    l3_rolling_5d_loss: Decimal = Decimal("-0.07")  # 滚动5日亏损>7%触发L3
    l3_rolling_window: int = 20
    l4_cumulative_loss: Decimal = Decimal("-0.25")
    l3_position_multiplier: Decimal = Decimal("0.5")
    l3_recovery_days: int = 5       # CLAUDE.md: 连续5个交易日
    l3_recovery_return: Decimal = Decimal("0.02")  # CLAUDE.md: 累计盈利>2%

    # 波动率自适应参数
    vol_baseline: float = 0.1485  # 基准年化波动率(沪深300长期均值)
    vol_clip_min: float = 0.5  # vol_ratio下限(低波时不过度放松)
    vol_clip_max: float = 2.0  # vol_ratio上限(高波时不过度收紧)


# ─────────────────────────────────────────────
# 级别 → 行为映射
# ─────────────────────────────────────────────

_LEVEL_CAN_REBALANCE: dict[CircuitBreakerLevel, bool] = {
    CircuitBreakerLevel.NORMAL: True,
    CircuitBreakerLevel.L1_PAUSED: False,
    CircuitBreakerLevel.L2_HALTED: False,
    CircuitBreakerLevel.L3_REDUCED: True,  # 只允许减仓，由调用方控制
    CircuitBreakerLevel.L4_STOPPED: False,
}

_LEVEL_POSITION_MULTIPLIER: dict[CircuitBreakerLevel, Decimal] = {
    CircuitBreakerLevel.NORMAL: Decimal("1.0"),
    CircuitBreakerLevel.L1_PAUSED: Decimal("1.0"),
    CircuitBreakerLevel.L2_HALTED: Decimal("1.0"),
    CircuitBreakerLevel.L3_REDUCED: Decimal("0.5"),
    CircuitBreakerLevel.L4_STOPPED: Decimal("0.0"),
}

_LEVEL_ALERT: dict[CircuitBreakerLevel, str] = {
    CircuitBreakerLevel.NORMAL: "P3",
    CircuitBreakerLevel.L1_PAUSED: "P2",
    CircuitBreakerLevel.L2_HALTED: "P0",
    CircuitBreakerLevel.L3_REDUCED: "P0",
    CircuitBreakerLevel.L4_STOPPED: "P0",
}


# ─────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────


class RiskControlService:
    """4级熔断风控Service。

    职责:
      1. 每日检查熔断触发条件, 更新状态机
      2. 管理L3降仓/恢复的仓位系数
      3. 管理L4人工审批流程
      4. 持久化状态到DB
      5. 状态变更时发送通知

    依赖:
      - AsyncSession (FastAPI Depends注入)
      - NotificationService (发送通知)

    调用时机:
      - 每日调度链路中, 在信号生成之后、执行调仓之前调用
    """

    def __init__(
        self,
        session: AsyncSession,
        notification_service: NotificationService,
        thresholds: CircuitBreakerThresholds | None = None,
    ) -> None:
        """初始化风控Service。

        Args:
            session: SQLAlchemy异步会话(通过Depends注入)。
            notification_service: 通知服务实例(通过Depends注入)。
            thresholds: 熔断阈值配置, None时使用DESIGN_V5默认值。
        """
        self.repo = RiskRepository(session)
        self.notification_service = notification_service
        self.thresholds = thresholds or CircuitBreakerThresholds()
        self._tables_ensured = False

    async def _ensure_tables(self) -> None:
        """延迟建表(首次调用时)。"""
        if not self._tables_ensured:
            await self.repo.ensure_tables()
            self._tables_ensured = True

    # ── 核心方法 ──

    async def check_and_update(
        self,
        strategy_id: UUID,
        execution_mode: str,
        metrics: RiskMetrics,
    ) -> CircuitBreakerState:
        """每日熔断检查: 评估触发条件 + 恢复条件 + 更新状态 + 发通知。

        步骤:
          1. 从DB加载当前状态(首次运行自动初始化为NORMAL)
          2. 如果当前非NORMAL, 先检查恢复条件
          3. 恢复条件满足则降级到NORMAL
          4. 不管是否刚恢复, 都重新检查触发条件(防止恢复当日又触发)
          5. 如果状态变更, 写入log + 更新state
          6. 如果状态变更, 发送通知

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            metrics: 当日风控指标。

        Returns:
            更新后的当前状态。

        Raises:
            ValueError: metrics参数不合法。
        """
        await self._ensure_tables()

        # 1. 加载当前状态
        db_state = await self.repo.get_state(strategy_id, execution_mode)
        if db_state is None:
            # 首次运行，初始化
            return await self.initialize_state(strategy_id, execution_mode)

        current_level = CircuitBreakerLevel(db_state["current_level"])
        entered_date = (
            date.fromisoformat(db_state["entered_date"])
            if isinstance(db_state["entered_date"], str)
            else db_state["entered_date"]
        )

        # 2. 如果当前非NORMAL，先检查恢复
        recovered = False
        if current_level != CircuitBreakerLevel.NORMAL:
            recovered = await self._check_recovery_conditions(
                current_level, entered_date, db_state, metrics
            )

        if recovered:
            # 3. 执行恢复
            prev_level = current_level
            current_level = CircuitBreakerLevel.NORMAL

            transition = CircuitBreakerTransition(
                strategy_id=strategy_id,
                execution_mode=execution_mode,
                trade_date=metrics.trade_date,
                prev_level=prev_level,
                new_level=CircuitBreakerLevel.NORMAL,
                transition_type=TransitionType.RECOVER,
                reason=f"从L{prev_level.value}恢复: 满足恢复条件",
                metrics=_metrics_to_dict(metrics),
            )
            await self._persist_transition(
                strategy_id,
                execution_mode,
                transition,
                entered_date=metrics.trade_date,
                position_multiplier=Decimal("1.0"),
                recovery_streak_days=0,
                recovery_streak_return=Decimal("0"),
                approval_id=None,
            )
            await self._notify_transition(transition)

            logger.info(
                "[RiskControl] %s 从L%d恢复到NORMAL (日期=%s)",
                strategy_id,
                prev_level.value,
                metrics.trade_date,
            )

        # 4. 不管是否恢复，都检查触发条件
        triggered_level, trigger_reason, trigger_metrics_dict = self._check_trigger_conditions(
            metrics
        )

        if triggered_level > current_level:
            # 升级
            prev_level = current_level
            new_level = triggered_level

            transition = CircuitBreakerTransition(
                strategy_id=strategy_id,
                execution_mode=execution_mode,
                trade_date=metrics.trade_date,
                prev_level=prev_level,
                new_level=new_level,
                transition_type=TransitionType.ESCALATE,
                reason=trigger_reason,
                metrics=trigger_metrics_dict,
            )

            new_multiplier = _LEVEL_POSITION_MULTIPLIER[new_level]
            await self._persist_transition(
                strategy_id,
                execution_mode,
                transition,
                entered_date=metrics.trade_date,
                position_multiplier=new_multiplier,
                recovery_streak_days=0,
                recovery_streak_return=Decimal("0"),
                approval_id=None,
            )
            await self._notify_transition(transition)

            logger.warning(
                "[RiskControl] %s 升级到L%d: %s (日期=%s)",
                strategy_id,
                new_level.value,
                trigger_reason,
                metrics.trade_date,
            )
            current_level = new_level

        # 5. 如果处于L3且未升级也未恢复，更新recovery streak
        if current_level == CircuitBreakerLevel.L3_REDUCED and not recovered:
            await self._update_recovery_streak(strategy_id, execution_mode, metrics.daily_return)

        # 6. 返回最新状态
        return await self.get_current_state(strategy_id, execution_mode)

    async def get_current_state(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
    ) -> CircuitBreakerState:
        """获取当前熔断状态(只读, 不触发检查)。

        用于前端展示、其他Service查询当前风控状态。
        如果DB中无记录(首次), 返回NORMAL默认状态。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。

        Returns:
            当前状态快照。
        """
        await self._ensure_tables()

        db_state = await self.repo.get_state(strategy_id, execution_mode)
        if db_state is None:
            return _make_default_state()

        return _db_state_to_dataclass(db_state)

    # ── 恢复管理 ──

    async def request_l4_recovery(
        self,
        strategy_id: UUID,
        execution_mode: str,
        reviewer_note: str,
    ) -> UUID:
        """发起L4人工审批恢复请求。

        创建一条approval_queue记录, 关联到当前circuit_breaker_state。
        审批通过后, 下次check_and_update会自动检测并恢复到NORMAL。

        前置条件: 当前状态必须是L4_STOPPED。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            reviewer_note: 审批请求说明。

        Returns:
            approval_queue记录ID。

        Raises:
            ValueError: 当前不是L4状态。
        """
        await self._ensure_tables()

        db_state = await self.repo.get_state(strategy_id, execution_mode)
        if db_state is None or db_state["current_level"] != CircuitBreakerLevel.L4_STOPPED:
            raise ValueError(f"策略 {strategy_id} 当前不是L4_STOPPED状态，无法发起恢复审批")

        # 插入approval_queue记录
        row = await self.repo.fetch_one(
            """INSERT INTO approval_queue
                   (approval_type, reference_id, payload, submitted_by, notes)
               VALUES
                   ('circuit_breaker_l4_recovery', :strategy_id,
                    '{}', 'system', :notes)
               RETURNING id""",
            {
                "strategy_id": str(strategy_id),
                "notes": reviewer_note,
            },
        )
        approval_id = row[0]

        # 关联到circuit_breaker_state
        await self.repo.execute(
            """UPDATE circuit_breaker_state
               SET approval_id = :approval_id, updated_at = NOW()
               WHERE strategy_id = :strategy_id
                 AND execution_mode = :execution_mode""",
            {
                "approval_id": str(approval_id),
                "strategy_id": str(strategy_id),
                "execution_mode": execution_mode,
            },
        )

        logger.info(
            "[RiskControl] L4恢复审批已创建: strategy=%s approval=%s",
            strategy_id,
            approval_id,
        )
        return approval_id

    async def approve_l4_recovery(
        self,
        approval_id: UUID,
        approved: bool,
        reviewer_note: str = "",
    ) -> CircuitBreakerState | None:
        """审批L4恢复请求。

        如果approved=True, 立即更新circuit_breaker_state为NORMAL。
        如果approved=False, 更新approval_queue为rejected。

        Args:
            approval_id: approval_queue记录ID。
            approved: 是否批准。
            reviewer_note: 审批意见。

        Returns:
            审批通过时返回新状态; 拒绝时返回None。
        """
        new_status = "approved" if approved else "rejected"
        await self.repo.execute(
            """UPDATE approval_queue
               SET status = :status, reviewed_at = NOW(), reviewer_notes = :notes
               WHERE id = :id""",
            {
                "status": new_status,
                "notes": reviewer_note,
                "id": str(approval_id),
            },
        )

        if not approved:
            logger.info("[RiskControl] L4恢复审批被拒绝: approval=%s", approval_id)
            return None

        # 找到关联的策略并恢复
        row = await self.repo.fetch_one(
            """SELECT strategy_id, execution_mode
               FROM circuit_breaker_state
               WHERE approval_id = :approval_id""",
            {"approval_id": str(approval_id)},
        )
        if not row:
            logger.warning("[RiskControl] 审批ID %s 未关联到任何策略", approval_id)
            return None

        strategy_id = UUID(str(row[0]))
        execution_mode = row[1]

        from datetime import date as date_type

        today = date_type.today()

        transition = CircuitBreakerTransition(
            strategy_id=strategy_id,
            execution_mode=execution_mode,
            trade_date=today,
            prev_level=CircuitBreakerLevel.L4_STOPPED,
            new_level=CircuitBreakerLevel.NORMAL,
            transition_type=TransitionType.MANUAL,
            reason=f"L4人工审批通过: {reviewer_note}" if reviewer_note else "L4人工审批通过",
            metrics={},
        )
        await self._persist_transition(
            strategy_id,
            execution_mode,
            transition,
            entered_date=today,
            position_multiplier=Decimal("1.0"),
            recovery_streak_days=0,
            recovery_streak_return=Decimal("0"),
            approval_id=None,
        )
        await self._notify_transition(transition)

        logger.info("[RiskControl] L4恢复审批通过: strategy=%s", strategy_id)
        return await self.get_current_state(strategy_id, execution_mode)

    # ── L3 仓位管理 ──

    async def get_position_multiplier(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
    ) -> Decimal:
        """获取当前仓位系数。

        NORMAL=1.0, L3=0.5, L4=0.0, L1/L2=1.0(不调仓但不改系数)。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。

        Returns:
            仓位系数 (0.0 ~ 1.0)。
        """
        state = await self.get_current_state(strategy_id, execution_mode)
        return state.position_multiplier

    # ── 查询 & 审计 ──

    async def get_transition_history(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
        limit: int = 50,
    ) -> list[CircuitBreakerTransition]:
        """获取熔断状态变更历史。

        从circuit_breaker_log读取, 按trade_date降序。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            limit: 最大返回条数。

        Returns:
            变更历史列表(最新在前)。
        """
        await self._ensure_tables()

        logs = await self.repo.get_logs(strategy_id, execution_mode, limit)
        result: list[CircuitBreakerTransition] = []
        for log_row in logs:
            result.append(
                CircuitBreakerTransition(
                    strategy_id=UUID(log_row["strategy_id"]),
                    execution_mode=log_row["execution_mode"],
                    trade_date=(
                        date.fromisoformat(log_row["trade_date"])
                        if isinstance(log_row["trade_date"], str)
                        else log_row["trade_date"]
                    ),
                    prev_level=CircuitBreakerLevel(log_row["prev_level"]),
                    new_level=CircuitBreakerLevel(log_row["new_level"]),
                    transition_type=TransitionType(log_row["transition_type"]),
                    reason=log_row["reason"],
                    metrics=log_row["metrics"] or {},
                )
            )
        return result

    async def get_risk_summary(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
    ) -> dict[str, Any]:
        """获取风控概览摘要, 供前端Dashboard展示。

        返回:
          - current_level: 当前熔断级别
          - days_in_current_state: 在当前状态已持续天数
          - total_escalations: 历史升级次数
          - last_escalation_date: 最近一次升级日期
          - l3_recovery_progress: L3恢复进度
          - thresholds: 当前使用的阈值配置

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。

        Returns:
            风控概览字典。
        """
        await self._ensure_tables()

        state = await self.get_current_state(strategy_id, execution_mode)
        total_escalations = await self.repo.count_escalations(strategy_id, execution_mode)
        last_escalation = await self.repo.get_last_escalation_date(strategy_id, execution_mode)

        days_in_state = (date.today() - state.entered_date).days

        # L3恢复进度
        l3_progress: str | None = None
        if state.level == CircuitBreakerLevel.L3_REDUCED:
            l3_progress = (
                f"{state.recovery_streak_days}/{self.thresholds.l3_recovery_days}天, "
                f"{float(state.recovery_streak_return) * 100:.1f}%/"
                f"{float(self.thresholds.l3_recovery_return) * 100:.1f}%"
            )

        return {
            "current_level": state.level.value,
            "current_level_name": state.level.name,
            "can_rebalance": state.can_rebalance,
            "position_multiplier": float(state.position_multiplier),
            "days_in_current_state": days_in_state,
            "entered_date": state.entered_date.isoformat(),
            "trigger_reason": state.trigger_reason,
            "total_escalations": total_escalations,
            "last_escalation_date": (last_escalation.isoformat() if last_escalation else None),
            "l3_recovery_progress": l3_progress,
            "thresholds": {
                "l1_daily_loss": float(self.thresholds.l1_daily_loss),
                "l2_daily_loss": float(self.thresholds.l2_daily_loss),
                "l3_rolling_loss": float(self.thresholds.l3_rolling_loss),
                "l3_rolling_5d_loss": float(self.thresholds.l3_rolling_5d_loss),
                "l4_cumulative_loss": float(self.thresholds.l4_cumulative_loss),
                "l3_recovery_days": self.thresholds.l3_recovery_days,
                "l3_recovery_return": float(self.thresholds.l3_recovery_return),
            },
        }

    # ── 初始化 & 工具 ──

    async def initialize_state(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
    ) -> CircuitBreakerState:
        """初始化熔断状态(首次运行时)。

        在circuit_breaker_state表中插入NORMAL状态记录。
        如果记录已存在, 直接返回现有状态(幂等)。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。

        Returns:
            初始状态。
        """
        await self._ensure_tables()

        existing = await self.repo.get_state(strategy_id, execution_mode)
        if existing is not None:
            return _db_state_to_dataclass(existing)

        today = date.today()
        await self.repo.upsert_state(
            strategy_id=strategy_id,
            execution_mode=execution_mode,
            current_level=CircuitBreakerLevel.NORMAL,
            entered_date=today,
            trigger_reason="初始化",
            trigger_metrics=None,
            recovery_streak_days=0,
            recovery_streak_return=Decimal("0"),
            position_multiplier=Decimal("1.0"),
            approval_id=None,
        )

        logger.info(
            "[RiskControl] 状态已初始化: strategy=%s mode=%s",
            strategy_id,
            execution_mode,
        )
        return await self.get_current_state(strategy_id, execution_mode)

    async def force_reset(
        self,
        strategy_id: UUID,
        execution_mode: str,
        reason: str,
    ) -> CircuitBreakerState:
        """强制重置到NORMAL状态(运维用, 需记录审计日志)。

        仅限运维紧急情况使用。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            reason: 强制重置原因(必填, 用于审计)。

        Returns:
            重置后状态。

        Raises:
            ValueError: reason为空。
        """
        if not reason.strip():
            raise ValueError("强制重置必须提供原因")

        await self._ensure_tables()

        db_state = await self.repo.get_state(strategy_id, execution_mode)
        prev_level = (
            CircuitBreakerLevel(db_state["current_level"])
            if db_state
            else CircuitBreakerLevel.NORMAL
        )

        today = date.today()
        transition = CircuitBreakerTransition(
            strategy_id=strategy_id,
            execution_mode=execution_mode,
            trade_date=today,
            prev_level=prev_level,
            new_level=CircuitBreakerLevel.NORMAL,
            transition_type=TransitionType.MANUAL,
            reason=f"强制重置: {reason}",
            metrics={},
        )
        await self._persist_transition(
            strategy_id,
            execution_mode,
            transition,
            entered_date=today,
            position_multiplier=Decimal("1.0"),
            recovery_streak_days=0,
            recovery_streak_return=Decimal("0"),
            approval_id=None,
        )
        await self._notify_transition(transition)

        logger.warning(
            "[RiskControl] 强制重置: strategy=%s 从L%d→NORMAL 原因=%s",
            strategy_id,
            prev_level.value,
            reason,
        )
        return await self.get_current_state(strategy_id, execution_mode)

    # ── 内部方法 ──

    def _calc_vol_ratio(self, metrics: RiskMetrics) -> float:
        """计算波动率自适应比率。

        vol_ratio = clip(portfolio_vol_20d / vol_baseline, clip_min, clip_max)

        高波时vol_ratio > 1, 阈值放宽(更难触发熔断, 允许更大波动);
        低波时vol_ratio < 1, 阈值收紧(更容易触发, 保护低波时期收益)。

        风控保守原则: 当波动率数据缺失或异常时, 返回vol_clip_max(最保守值),
        使阈值放到最宽, 等价于"不确定就假设高波动"。
        宁可误杀(多触发熔断)不可漏杀(漏掉真正的风险)。

        Args:
            metrics: 当日风控指标, 需包含portfolio_vol_20d。

        Returns:
            vol_ratio, 范围[vol_clip_min, vol_clip_max]。
            如果portfolio_vol_20d缺失或<=0, 返回vol_clip_max(保守假设)。
        """
        if metrics.portfolio_vol_20d is None or metrics.portfolio_vol_20d <= 0:
            logger.warning(
                "[RiskControl] portfolio_vol_20d缺失或非正(值=%s), 按保守假设返回vol_clip_max=%.2f",
                metrics.portfolio_vol_20d,
                self.thresholds.vol_clip_max,
            )
            return self.thresholds.vol_clip_max

        if self.thresholds.vol_baseline <= 0:
            return self.thresholds.vol_clip_max

        # 极大值告警: 年化波动率>100%属于异常, 记录警告
        if metrics.portfolio_vol_20d > 1.0:
            logger.warning(
                "[RiskControl] portfolio_vol_20d=%.4f (年化>100%%), 波动率异常偏高, "
                "请检查数据质量或市场是否出现极端行情",
                metrics.portfolio_vol_20d,
            )

        raw_ratio = metrics.portfolio_vol_20d / self.thresholds.vol_baseline
        return max(
            self.thresholds.vol_clip_min,
            min(raw_ratio, self.thresholds.vol_clip_max),
        )

    def _check_trigger_conditions(
        self,
        metrics: RiskMetrics,
    ) -> tuple[CircuitBreakerLevel, str, dict[str, Any]]:
        """评估熔断触发条件(纯计算, 不写DB)。

        按严重程度从高到低检查: L4 → L3 → L2 → L1 → NORMAL。
        四级阈值均乘以vol_ratio进行波动率自适应调整。

        Args:
            metrics: 当日风控指标。

        Returns:
            (触发级别, 原因描述, 指标快照)。
        """
        metrics_dict = _metrics_to_dict(metrics)
        vol_ratio = self._calc_vol_ratio(metrics)

        # 自适应阈值: 原始阈值 × vol_ratio
        # 注意: 阈值是负数, 乘以vol_ratio后绝对值变大 → 更难触发
        l1_threshold = self.thresholds.l1_daily_loss * Decimal(str(vol_ratio))
        l2_threshold = self.thresholds.l2_daily_loss * Decimal(str(vol_ratio))
        l3_20d_threshold = self.thresholds.l3_rolling_loss * Decimal(str(vol_ratio))
        l3_5d_threshold = self.thresholds.l3_rolling_5d_loss * Decimal(str(vol_ratio))
        l4_threshold = self.thresholds.l4_cumulative_loss * Decimal(str(vol_ratio))

        if vol_ratio != 1.0:
            logger.debug(
                "[RiskControl] 波动率自适应: vol_ratio=%.3f, "
                "L1=%.1f%%, L2=%.1f%%, L3_5d=%.1f%%, L3_20d=%.1f%%, L4=%.1f%%",
                vol_ratio,
                float(l1_threshold) * 100,
                float(l2_threshold) * 100,
                float(l3_5d_threshold) * 100,
                float(l3_20d_threshold) * 100,
                float(l4_threshold) * 100,
            )

        # L4: 累计亏损超阈值
        if metrics.cumulative_return <= l4_threshold:
            return (
                CircuitBreakerLevel.L4_STOPPED,
                f"累计亏损{float(metrics.cumulative_return) * 100:.1f}%"
                f"(自适应阈值{float(l4_threshold) * 100:.1f}%, vol_ratio={vol_ratio:.2f})，停止交易",
                metrics_dict,
            )

        # L3: OR条件 — 滚动5日 < -7% OR 滚动20日 < -10% (均受波动率自适应)
        l3_triggered_5d = (
            metrics.rolling_5d_return is not None and metrics.rolling_5d_return <= l3_5d_threshold
        )
        l3_triggered_20d = (
            metrics.rolling_20d_return is not None
            and metrics.rolling_20d_return <= l3_20d_threshold
        )

        if l3_triggered_5d or l3_triggered_20d:
            # 构造触发原因: 说明哪个条件触发
            reasons: list[str] = []
            if l3_triggered_5d:
                reasons.append(
                    f"滚动5日亏损{float(metrics.rolling_5d_return) * 100:.1f}%"
                    f"(阈值{float(l3_5d_threshold) * 100:.1f}%)"
                )
            if l3_triggered_20d:
                reasons.append(
                    f"滚动20日亏损{float(metrics.rolling_20d_return) * 100:.1f}%"
                    f"(阈值{float(l3_20d_threshold) * 100:.1f}%)"
                )
            return (
                CircuitBreakerLevel.L3_REDUCED,
                f"{' + '.join(reasons)}(vol_ratio={vol_ratio:.2f})，降仓50%",
                metrics_dict,
            )

        # L2: 单日亏损>自适应阈值
        if metrics.daily_return <= l2_threshold:
            return (
                CircuitBreakerLevel.L2_HALTED,
                f"单日亏损{float(metrics.daily_return) * 100:.1f}%"
                f"(自适应阈值{float(l2_threshold) * 100:.1f}%, vol_ratio={vol_ratio:.2f})，全部暂停",
                metrics_dict,
            )

        # L1: 单日亏损>自适应阈值
        if metrics.daily_return <= l1_threshold:
            return (
                CircuitBreakerLevel.L1_PAUSED,
                f"单日亏损{float(metrics.daily_return) * 100:.1f}%"
                f"(自适应阈值{float(l1_threshold) * 100:.1f}%, vol_ratio={vol_ratio:.2f})，暂停1天",
                metrics_dict,
            )

        # NORMAL
        return (
            CircuitBreakerLevel.NORMAL,
            "正常",
            metrics_dict,
        )

    async def _check_recovery_conditions(
        self,
        current_level: CircuitBreakerLevel,
        entered_date: date,
        db_state: dict[str, Any],
        metrics: RiskMetrics,
    ) -> bool:
        """评估恢复条件(纯计算, 不写DB)。

        L1/L2: entered_date < metrics.trade_date (已过1个交易日冷却)
        L3: recovery_streak_days >= 3 且 recovery_streak_return > 1.5%
        L4: 关联的approval_queue.status == 'approved'

        Args:
            current_level: 当前熔断级别。
            entered_date: 进入当前状态的交易日。
            db_state: DB中的状态字典。
            metrics: 当日风控指标。

        Returns:
            是否满足恢复条件。
        """
        if current_level in (
            CircuitBreakerLevel.L1_PAUSED,
            CircuitBreakerLevel.L2_HALTED,
        ):
            # 次日自动恢复: 当前交易日 > 进入状态的交易日
            return metrics.trade_date > entered_date

        if current_level == CircuitBreakerLevel.L3_REDUCED:
            # 连续5天盈利 且 累计收益>2%
            streak_days = db_state.get("recovery_streak_days", 0) or 0
            streak_return = Decimal(str(db_state.get("recovery_streak_return", 0) or 0))
            return (
                streak_days >= self.thresholds.l3_recovery_days
                and streak_return >= self.thresholds.l3_recovery_return
            )

        if current_level == CircuitBreakerLevel.L4_STOPPED:
            # 人工审批: 检查关联的approval_queue
            approval_id_str = db_state.get("approval_id")
            if not approval_id_str:
                return False
            status = await self.repo.get_approval_status(UUID(approval_id_str))
            return status == "approved"

        return False

    async def _update_recovery_streak(
        self,
        strategy_id: UUID,
        execution_mode: str,
        daily_return: Decimal,
    ) -> None:
        """更新L3恢复追踪的连续盈利计数。

        规则:
          - 当日盈利(daily_return > 0): streak_days += 1, streak_return 累积
          - 当日亏损(daily_return <= 0): streak 重置为 0
          - streak_days >= 5 且 streak_return > 2%: 满足恢复条件

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            daily_return: 当日收益率。
        """
        db_state = await self.repo.get_state(strategy_id, execution_mode)
        if db_state is None:
            return

        if daily_return > Decimal("0"):
            new_days = (db_state.get("recovery_streak_days", 0) or 0) + 1
            prev_return = Decimal(str(db_state.get("recovery_streak_return", 0) or 0))
            new_return = prev_return + daily_return
        else:
            # 亏损或持平: 重置
            new_days = 0
            new_return = Decimal("0")

        await self.repo.update_recovery_streak(strategy_id, execution_mode, new_days, new_return)

        logger.debug(
            "[RiskControl] L3恢复追踪: strategy=%s streak=%d天 累计=%.4f%%",
            strategy_id,
            new_days,
            float(new_return) * 100,
        )

    async def _persist_transition(
        self,
        strategy_id: UUID,
        execution_mode: str,
        transition: CircuitBreakerTransition,
        entered_date: date,
        position_multiplier: Decimal,
        recovery_streak_days: int,
        recovery_streak_return: Decimal,
        approval_id: UUID | None,
    ) -> None:
        """持久化状态变更: 更新state表 + 追加log表。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            transition: 变更事件。
            entered_date: 进入新状态的交易日。
            position_multiplier: 新仓位系数。
            recovery_streak_days: 恢复连续天数。
            recovery_streak_return: 恢复累计收益。
            approval_id: L4审批ID。
        """
        # 更新state表
        await self.repo.upsert_state(
            strategy_id=strategy_id,
            execution_mode=execution_mode,
            current_level=transition.new_level,
            entered_date=entered_date,
            trigger_reason=transition.reason,
            trigger_metrics=transition.metrics,
            recovery_streak_days=recovery_streak_days,
            recovery_streak_return=recovery_streak_return,
            position_multiplier=position_multiplier,
            approval_id=approval_id,
        )

        # 追加log
        await self.repo.insert_log(
            strategy_id=strategy_id,
            execution_mode=execution_mode,
            trade_date=transition.trade_date,
            prev_level=transition.prev_level,
            new_level=transition.new_level,
            transition_type=transition.transition_type.value,
            reason=transition.reason,
            metrics=transition.metrics,
        )

    async def _notify_transition(
        self,
        transition: CircuitBreakerTransition,
    ) -> None:
        """状态变更通知。

        通知规则:
          - L1: P2级别
          - L2/L3/L4: P0级别
          - 恢复到NORMAL: P2级别
        """
        if transition.transition_type in (
            TransitionType.RECOVER,
            TransitionType.MANUAL,
        ):
            level = "P2"
            title = f"[风控恢复] 策略从L{transition.prev_level.value}恢复到正常"
        else:
            level = _LEVEL_ALERT.get(transition.new_level, "P2")
            title = f"[风控L{transition.new_level.value}] {transition.reason}"

        content = (
            f"**策略**: {transition.strategy_id}\n"
            f"**模式**: {transition.execution_mode}\n"
            f"**日期**: {transition.trade_date}\n"
            f"**变更**: L{transition.prev_level.value} → L{transition.new_level.value}\n"
            f"**原因**: {transition.reason}"
        )

        try:
            await self.notification_service.send(
                level=level,
                category="risk",
                title=title,
                content=content,
                market="astock",
                force=level == "P0",  # P0强制发送
            )
        except Exception as e:
            # 通知失败不影响主流程
            logger.error("[RiskControl] 通知发送失败: %s", e)


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────


def _make_default_state() -> CircuitBreakerState:
    """创建NORMAL默认状态（未初始化时使用）。"""
    return CircuitBreakerState(
        level=CircuitBreakerLevel.NORMAL,
        entered_date=date.today(),
        trigger_reason="初始化",
        trigger_metrics={},
        position_multiplier=Decimal("1.0"),
        recovery_streak_days=0,
        recovery_streak_return=Decimal("0"),
        can_rebalance=True,
        approval_id=None,
    )


def _db_state_to_dataclass(db_state: dict[str, Any]) -> CircuitBreakerState:
    """将DB字典转为CircuitBreakerState数据类。"""
    level = CircuitBreakerLevel(db_state["current_level"])
    entered = db_state["entered_date"]
    if isinstance(entered, str):
        entered = date.fromisoformat(entered)

    multiplier = Decimal(str(db_state.get("position_multiplier", "1.0") or "1.0"))
    approval_id_str = db_state.get("approval_id")

    return CircuitBreakerState(
        level=level,
        entered_date=entered,
        trigger_reason=db_state.get("trigger_reason", "") or "",
        trigger_metrics=db_state.get("trigger_metrics") or {},
        position_multiplier=multiplier,
        recovery_streak_days=db_state.get("recovery_streak_days", 0) or 0,
        recovery_streak_return=Decimal(str(db_state.get("recovery_streak_return", 0) or 0)),
        can_rebalance=_LEVEL_CAN_REBALANCE[level],
        approval_id=UUID(approval_id_str) if approval_id_str else None,
    )


def _metrics_to_dict(metrics: RiskMetrics) -> dict[str, Any]:
    """将RiskMetrics转为可序列化字典。"""
    return {
        "trade_date": metrics.trade_date.isoformat(),
        "daily_return": float(metrics.daily_return),
        "nav": float(metrics.nav),
        "initial_capital": float(metrics.initial_capital),
        "cumulative_return": float(metrics.cumulative_return),
        "rolling_5d_return": (
            float(metrics.rolling_5d_return) if metrics.rolling_5d_return is not None else None
        ),
        "rolling_20d_return": (
            float(metrics.rolling_20d_return) if metrics.rolling_20d_return is not None else None
        ),
        "portfolio_vol_20d": metrics.portfolio_vol_20d,
    }


# ─────────────────────────────────────────────
# Sync 方法（scripts/run_paper_trading.py 调用）
# ─────────────────────────────────────────────
# 以下函数使用 psycopg2 同步连接，逻辑与 scripts 版完全一致。
# 调用方管理事务（除 _ensure_cb_tables_sync 的 DDL 自行 commit）。

# 熔断阈值（DESIGN_V5 §8.1 硬编码，AI无权修改）
CB_THRESHOLDS: dict[str, float | int] = {
    "l1_daily_loss": -0.03,     # L1: 单日亏>3% → 暂停1天
    "l2_daily_loss": -0.05,     # L2: 单日亏>5% → 全部暂停
    "l3_rolling_5d": -0.07,     # L3: 滚动5日亏>7% → 降仓50%
    "l3_rolling_20d": -0.10,    # L3: 滚动20日亏>10% → 降仓50%
    "l4_cumulative": -0.25,     # L4: 累计亏>25% → 停止交易+人工审批
    "l3_recovery_days": 5,      # L3恢复: 连续5交易日盈利
    "l3_recovery_return": 0.02, # L3恢复: 且累计>2%
}

# 级别 → 仓位系数
CB_POSITION_MULTIPLIER: dict[int, float] = {0: 1.0, 1: 1.0, 2: 1.0, 3: 0.5, 4: 0.0}


def _ensure_cb_tables_sync(conn: Any) -> None:
    """确保circuit_breaker_state和circuit_breaker_log表存在（幂等）。

    DDL操作自行commit，不依赖调用方事务。

    Args:
        conn: psycopg2同步连接。
    """
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS circuit_breaker_state (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id            UUID NOT NULL,
            execution_mode         VARCHAR(10) NOT NULL DEFAULT 'paper',
            current_level          SMALLINT NOT NULL DEFAULT 0,
            entered_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            entered_date           DATE NOT NULL DEFAULT CURRENT_DATE,
            trigger_reason         TEXT,
            trigger_metrics        JSONB,
            recovery_streak_days   INT DEFAULT 0,
            recovery_streak_return DECIMAL(12,8) DEFAULT 0,
            position_multiplier    DECIMAL(4,2) DEFAULT 1.0,
            approval_id            UUID,
            updated_at             TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(strategy_id, execution_mode)
        );
        CREATE TABLE IF NOT EXISTS circuit_breaker_log (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id       UUID NOT NULL,
            execution_mode    VARCHAR(10) NOT NULL DEFAULT 'paper',
            trade_date        DATE NOT NULL,
            prev_level        SMALLINT NOT NULL,
            new_level         SMALLINT NOT NULL,
            transition_type   VARCHAR(10) NOT NULL,
            reason            TEXT NOT NULL,
            metrics           JSONB,
            created_at        TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_cb_log_strategy_date
            ON circuit_breaker_log(strategy_id, trade_date DESC);
    """)
    conn.commit()


def _load_cb_state_sync(conn: Any, strategy_id: str) -> dict[str, Any] | None:
    """从circuit_breaker_state读取当前状态。

    Args:
        conn: psycopg2同步连接。
        strategy_id: 策略UUID字符串。

    Returns:
        状态字典，无记录时返回None。
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT current_level, entered_date, trigger_reason,
                  recovery_streak_days, recovery_streak_return,
                  position_multiplier, approval_id
           FROM circuit_breaker_state
           WHERE strategy_id = %s AND execution_mode = 'paper'""",
        (strategy_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "current_level": row[0],
        "entered_date": row[1],
        "trigger_reason": row[2],
        "recovery_streak_days": row[3] or 0,
        "recovery_streak_return": float(row[4] or 0),
        "position_multiplier": float(row[5] or 1.0),
        "approval_id": row[6],
    }


def _upsert_cb_state_sync(
    conn: Any,
    strategy_id: str,
    level: int,
    entered_date: date,
    reason: str,
    metrics: dict[str, Any] | None,
    recovery_streak_days: int,
    recovery_streak_return: float,
    position_multiplier: float,
    approval_id: Any = None,
) -> None:
    """插入或更新circuit_breaker_state（UPSERT）。

    不commit，由调用方管理事务。

    Args:
        conn: psycopg2同步连接。
        strategy_id: 策略UUID字符串。
        level: 熔断级别(0-4)。
        entered_date: 进入当前状态日期。
        reason: 触发原因。
        metrics: 指标快照（可选）。
        recovery_streak_days: L3恢复连续盈利天数。
        recovery_streak_return: L3恢复累计收益率。
        position_multiplier: 仓位系数。
        approval_id: L4审批ID（可选）。
    """
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO circuit_breaker_state
               (strategy_id, execution_mode, current_level,
                entered_at, entered_date, trigger_reason, trigger_metrics,
                recovery_streak_days, recovery_streak_return,
                position_multiplier, approval_id, updated_at)
           VALUES (%s, 'paper', %s, NOW(), %s, %s, %s::jsonb,
                   %s, %s, %s, %s, NOW())
           ON CONFLICT (strategy_id, execution_mode)
           DO UPDATE SET
                current_level = EXCLUDED.current_level,
                entered_at = CASE
                    WHEN circuit_breaker_state.current_level != EXCLUDED.current_level
                    THEN NOW() ELSE circuit_breaker_state.entered_at END,
                entered_date = CASE
                    WHEN circuit_breaker_state.current_level != EXCLUDED.current_level
                    THEN EXCLUDED.entered_date ELSE circuit_breaker_state.entered_date END,
                trigger_reason = EXCLUDED.trigger_reason,
                trigger_metrics = EXCLUDED.trigger_metrics,
                recovery_streak_days = EXCLUDED.recovery_streak_days,
                recovery_streak_return = EXCLUDED.recovery_streak_return,
                position_multiplier = EXCLUDED.position_multiplier,
                approval_id = EXCLUDED.approval_id,
                updated_at = NOW()""",
        (strategy_id, level, entered_date, reason,
         json.dumps(metrics) if metrics else None,
         recovery_streak_days, recovery_streak_return,
         position_multiplier,
         str(approval_id) if approval_id else None),
    )


def _insert_cb_log_sync(
    conn: Any,
    strategy_id: str,
    trade_date: date,
    prev_level: int,
    new_level: int,
    transition_type: str,
    reason: str,
    metrics: dict[str, Any] | None,
) -> None:
    """追加circuit_breaker_log审计记录。

    不commit，由调用方管理事务。

    Args:
        conn: psycopg2同步连接。
        strategy_id: 策略UUID字符串。
        trade_date: 交易日期。
        prev_level: 变更前级别。
        new_level: 变更后级别。
        transition_type: 变更类型("escalate"/"recover")。
        reason: 变更原因。
        metrics: 指标快照（可选）。
    """
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO circuit_breaker_log
               (strategy_id, execution_mode, trade_date,
                prev_level, new_level, transition_type, reason, metrics)
           VALUES (%s, 'paper', %s, %s, %s, %s, %s, %s::jsonb)""",
        (strategy_id, trade_date, prev_level, new_level,
         transition_type, reason,
         json.dumps(metrics) if metrics else None),
    )


def check_circuit_breaker_sync(
    conn: Any,
    strategy_id: str,
    exec_date: date,
    initial_capital: float,
) -> dict[str, Any]:
    """4级有状态熔断检查 + 恢复追踪 + DB持久化（同步版）。

    状态机（DESIGN_V5 §8.1 + CLAUDE.md确认）:
      L1: 单策略日亏>3% → 暂停1天(次日自动恢复)
      L2: 总组合日亏>5% → 全部暂停(次日自动恢复)+P0告警
      L3: 滚动5日亏>7% OR 滚动20日亏>10% → 降仓50%
          恢复: 连续5个交易日累计盈利>2%
      L4: 累计亏损>25% → 停止所有交易+人工审批
          恢复: 需人工脚本approve后重置

    L1延迟方案C（已确认）: L1触发时月度调仓不跳过，但仓位减半
    → 实际处理在调用方（execute phase），本函数只返回级别。

    逻辑与scripts/run_paper_trading.py L323-538完全一致。

    Args:
        conn: psycopg2同步连接。
        strategy_id: 策略UUID字符串。
        exec_date: 执行日期。
        initial_capital: 初始资金。

    Returns:
        {"level": 0-4, "action": str, "reason": str,
         "position_multiplier": float, "recovery_info": str}
    """
    _ensure_cb_tables_sync(conn)

    # ── 1. 读取performance_series获取指标 ──
    cur = conn.cursor()
    cur.execute(
        """SELECT trade_date, nav::float, daily_return::float
           FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
           ORDER BY trade_date DESC LIMIT 20""",
        (strategy_id,),
    )
    rows = cur.fetchall()
    if not rows:
        # 首次运行，初始化DB状态为NORMAL
        _upsert_cb_state_sync(conn, strategy_id, 0, exec_date,
                              "初始化(首次运行)", None, 0, 0.0, 1.0)
        conn.commit()
        return {"level": 0, "action": "normal", "reason": "无历史数据(首次运行)",
                "position_multiplier": 1.0, "recovery_info": ""}

    latest_nav = rows[0][1]
    latest_ret = rows[0][2]
    cum_loss = (latest_nav / initial_capital) - 1

    # 计算滚动收益
    rolling_5d_loss = None
    if len(rows) >= 5:
        r5 = 1.0
        for r in rows[:5]:
            r5 *= (1 + r[2])
        rolling_5d_loss = r5 - 1

    rolling_20d_loss = None
    if len(rows) >= 5:
        r20 = 1.0
        for r in rows[:20]:
            r20 *= (1 + r[2])
        rolling_20d_loss = r20 - 1

    metrics_snap = {
        "nav": round(latest_nav, 2),
        "daily_return": round(latest_ret, 6),
        "cumulative_return": round(cum_loss, 6),
        "rolling_5d": round(rolling_5d_loss, 6) if rolling_5d_loss is not None else None,
        "rolling_20d": round(rolling_20d_loss, 6) if rolling_20d_loss is not None else None,
    }

    # ── 2. 从DB加载当前持久化状态 ──
    db_state = _load_cb_state_sync(conn, strategy_id)
    prev_level = db_state["current_level"] if db_state else 0
    prev_entered_date = db_state["entered_date"] if db_state else exec_date
    streak_days = db_state["recovery_streak_days"] if db_state else 0
    streak_return = db_state["recovery_streak_return"] if db_state else 0.0

    # ── 3. 如果当前非NORMAL，先检查恢复条件 ──
    recovered = False
    recovery_info = ""

    if prev_level > 0:
        if prev_level in (1, 2):
            # L1/L2: 次日自动恢复（当前exec_date > entered_date）
            if exec_date > prev_entered_date:
                recovered = True
                recovery_info = f"L{prev_level}自动恢复(冷却1天已过)"
                logger.info(
                    "[CB] L%d自动恢复: entered=%s, exec=%s",
                    prev_level, prev_entered_date, exec_date,
                )

        elif prev_level == 3:
            # L3恢复: 连续5日盈利且累计>2%
            if latest_ret > 0:
                streak_days += 1
                streak_return += latest_ret
            else:
                streak_days = 0
                streak_return = 0.0

            recovery_info = (
                f"L3恢复进度: {streak_days}/{CB_THRESHOLDS['l3_recovery_days']}天, "
                f"{streak_return:.2%}/{CB_THRESHOLDS['l3_recovery_return']:.0%}"
            )
            logger.info("[CB] %s", recovery_info)

            if (streak_days >= CB_THRESHOLDS["l3_recovery_days"]
                    and streak_return >= CB_THRESHOLDS["l3_recovery_return"]):
                recovered = True
                recovery_info = (
                    f"L3恢复条件达成: 连续{streak_days}天盈利, "
                    f"累计{streak_return:.2%} >= {CB_THRESHOLDS['l3_recovery_return']:.0%}"
                )
                logger.info("[CB] %s", recovery_info)

        elif prev_level == 4:
            # L4恢复: 检查approval_queue
            if db_state and db_state.get("approval_id"):
                cur.execute(
                    "SELECT status FROM approval_queue WHERE id = %s",
                    (str(db_state["approval_id"]),),
                )
                approval_row = cur.fetchone()
                if approval_row and approval_row[0] == "approved":
                    recovered = True
                    recovery_info = "L4人工审批通过"
                    logger.info("[CB] L4人工审批已通过，恢复到NORMAL")
                else:
                    recovery_info = "L4待人工审批"
            else:
                recovery_info = "L4待人工审批(未创建审批请求)"

    # ── 4. 如果恢复，先降级到NORMAL ──
    if recovered:
        _insert_cb_log_sync(conn, strategy_id, exec_date,
                            prev_level, 0, "recover", recovery_info, metrics_snap)
        _upsert_cb_state_sync(conn, strategy_id, 0, exec_date,
                              recovery_info, metrics_snap, 0, 0.0, 1.0)
        prev_level = 0
        streak_days = 0
        streak_return = 0.0
        logger.info(
            "[CB] 状态变更: L%d -> NORMAL (%s)",
            db_state["current_level"] if db_state else 0, recovery_info,
        )

    # ── 5. 不管是否刚恢复，都重新检查触发条件（防恢复当日又触发）──
    triggered_level = 0
    trigger_reason = "正常"
    trigger_action = "normal"

    # L4: 累计亏损 > 25%
    if cum_loss < CB_THRESHOLDS["l4_cumulative"]:
        triggered_level = 4
        trigger_action = "halt"
        trigger_reason = f"累计亏损{cum_loss:.1%}, NAV={latest_nav:.0f}"

    # L3: 滚动5日亏>7% OR 滚动20日亏>10%
    elif ((rolling_5d_loss is not None and rolling_5d_loss < CB_THRESHOLDS["l3_rolling_5d"])
          or (rolling_20d_loss is not None and rolling_20d_loss < CB_THRESHOLDS["l3_rolling_20d"])):
        triggered_level = 3
        trigger_action = "reduce"
        l3_parts = []
        if rolling_5d_loss is not None and rolling_5d_loss < CB_THRESHOLDS["l3_rolling_5d"]:
            l3_parts.append(f"5日累计{rolling_5d_loss:.1%}")
        if rolling_20d_loss is not None and rolling_20d_loss < CB_THRESHOLDS["l3_rolling_20d"]:
            l3_parts.append(f"20日累计{rolling_20d_loss:.1%}")
        trigger_reason = " + ".join(l3_parts)

    # L2: 单日亏损 > 5%
    elif latest_ret < CB_THRESHOLDS["l2_daily_loss"]:
        triggered_level = 2
        trigger_action = "pause"
        trigger_reason = f"昨日亏损{latest_ret:.1%}"

    # L1: 单日亏损 > 3%
    elif latest_ret < CB_THRESHOLDS["l1_daily_loss"]:
        triggered_level = 1
        trigger_action = "skip_rebalance"
        trigger_reason = f"昨日亏损{latest_ret:.1%}"

    # ── 6. 如果触发级别 > 当前级别，升级 ──
    new_level = max(triggered_level, prev_level) if not recovered else triggered_level
    # 如果已经在L3且没恢复，保持L3（不降回L1/L2，因为L3更严重）
    if not recovered and prev_level > triggered_level:
        new_level = prev_level
        trigger_reason = f"维持L{prev_level}({db_state['trigger_reason'] if db_state else ''})"
        trigger_action = {0: "normal", 1: "skip_rebalance", 2: "pause",
                          3: "reduce", 4: "halt"}[prev_level]

    if new_level != prev_level and new_level > 0:
        # 状态升级
        _insert_cb_log_sync(conn, strategy_id, exec_date,
                            prev_level, new_level, "escalate", trigger_reason, metrics_snap)
        position_mult = CB_POSITION_MULTIPLIER[new_level]
        _upsert_cb_state_sync(conn, strategy_id, new_level, exec_date,
                              trigger_reason, metrics_snap, 0, 0.0, position_mult)
        logger.warning("[CB] 熔断升级: L%d -> L%d (%s)", prev_level, new_level, trigger_reason)

        # 发送通知
        from app.config import settings as app_settings
        from app.services.notification_service import send_alert

        alert_level = "P0" if new_level >= 2 else "P2"
        send_alert(alert_level, f"熔断L{new_level} {exec_date}", trigger_reason,
                   app_settings.DINGTALK_WEBHOOK_URL, app_settings.DINGTALK_SECRET, conn)
    elif new_level == prev_level and new_level == 3 and not recovered:
        # L3维持中，更新恢复追踪
        _upsert_cb_state_sync(conn, strategy_id, 3, prev_entered_date,
                              db_state["trigger_reason"] if db_state else trigger_reason,
                              metrics_snap, streak_days, streak_return, 0.5)
    elif new_level == 0 and prev_level == 0:
        # 保持NORMAL，更新指标
        _upsert_cb_state_sync(conn, strategy_id, 0, exec_date,
                              "正常", metrics_snap, 0, 0.0, 1.0)

    conn.commit()
    position_multiplier = CB_POSITION_MULTIPLIER.get(new_level, 1.0)

    return {
        "level": new_level,
        "action": trigger_action,
        "reason": trigger_reason,
        "position_multiplier": position_multiplier,
        "recovery_info": recovery_info,
    }


def create_l4_approval_sync(conn: Any, strategy_id: str, reason: str) -> int | None:
    """L4触发时自动创建审批请求（如果还没有pending的）。

    写入approval_queue表，并关联到circuit_breaker_state。
    人工通过脚本approve后，下次check_circuit_breaker_sync会检测到并恢复。

    Args:
        conn: psycopg2同步连接。
        strategy_id: 策略UUID字符串。
        reason: L4触发原因。

    Returns:
        审批ID，如果已存在pending审批则返回None。
    """
    cur = conn.cursor()

    # 检查是否已有pending审批
    cur.execute(
        """SELECT id FROM approval_queue
           WHERE approval_type = 'circuit_breaker_l4_recovery'
             AND reference_id = %s AND status = 'pending'
           LIMIT 1""",
        (strategy_id,),
    )
    existing = cur.fetchone()
    if existing:
        logger.info("[L4] 审批请求已存在: %s", existing[0])
        return None

    # 创建审批请求
    try:
        cur.execute(
            """INSERT INTO approval_queue
                   (approval_type, reference_id, payload, submitted_by, notes, status)
               VALUES
                   ('circuit_breaker_l4_recovery', %s, '{}'::jsonb, 'system', %s, 'pending')
               RETURNING id""",
            (strategy_id, f"L4自动创建: {reason}"),
        )
        approval_row = cur.fetchone()
        if approval_row:
            approval_id = approval_row[0]
            # 关联到circuit_breaker_state
            cur.execute(
                """UPDATE circuit_breaker_state
                   SET approval_id = %s, updated_at = NOW()
                   WHERE strategy_id = %s AND execution_mode = 'paper'""",
                (str(approval_id), strategy_id),
            )
            conn.commit()
            logger.info("[L4] 审批请求已创建: %s", approval_id)

            from app.config import settings as app_settings
            from app.services.notification_service import send_alert

            send_alert("P0", "L4审批请求已创建",
                       f"策略{strategy_id}触发L4熔断，需人工审批。\n原因: {reason}\n"
                       f"审批ID: {approval_id}\n"
                       f"恢复命令: python scripts/approve_l4.py --approval-id {approval_id}",
                       app_settings.DINGTALK_WEBHOOK_URL, app_settings.DINGTALK_SECRET, conn)
            return approval_id
    except Exception as e:
        logger.error("[L4] 创建审批请求失败: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
    return None


def run_daily_risk_check_sync(
    holdings: dict[str, int],
    cash: float,
    nav: float,
    today_close: dict[str, float],
) -> list[str]:
    """风控日检（同步版，risk评审blocking要求#2）。

    检查: 单股权重/现金比例/持仓数量。
    返回异常列表（空=全部正常）。

    Args:
        holdings: 当前持仓 {code: shares}。
        cash: 当前现金。
        nav: 当前净值。
        today_close: 当日收盘价 {code: price}。

    Returns:
        异常警告列表。
    """
    warnings: list[str] = []

    # 单股最大权重 > 15%
    if holdings and nav > 0:
        max_weight = max(
            shares * today_close.get(code, 0) / nav
            for code, shares in holdings.items()
        )
        if max_weight > 0.15:
            warnings.append(f"单股权重超限: {max_weight:.1%} > 15%")

    # 现金比例异常
    cash_ratio = cash / nav if nav > 0 else 1
    if cash_ratio > 0.15:
        warnings.append(f"现金比例过高: {cash_ratio:.1%}")
    elif cash_ratio < 0.005 and holdings:
        warnings.append(f"现金比例过低: {cash_ratio:.1%}")

    # 持仓数量异常
    pos_count = len(holdings)
    if pos_count < 15 and pos_count > 0:
        warnings.append(f"持仓不足: {pos_count}只 < 15")
    elif pos_count > 25:
        warnings.append(f"持仓过多: {pos_count}只 > 25")

    return warnings
