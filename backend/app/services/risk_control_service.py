"""RiskControlService — 4级熔断风控Service。

DESIGN_V5 §8.1 定义的4级熔断状态机:
  L1: 单策略日亏>3% → 暂停1天(次日自动恢复)
  L2: 总组合日亏>5% → 全部暂停(次日自动恢复)
  L3: 月亏(滚动20日)>10% → 降仓50%, 恢复条件: 连续5天盈利>2%
  L4: 累计亏>25% → 停止所有交易, 人工审批

遵循CLAUDE.md: async/await + 类型注解 + Google docstring(中文) + Depends注入。
"""

from __future__ import annotations

import enum
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
    L1_PAUSED = 1   # 单策略日亏>3%, 暂停1天
    L2_HALTED = 2   # 总组合日亏>5%, 全部暂停
    L3_REDUCED = 3  # 月亏>10%, 降仓50%
    L4_STOPPED = 4  # 累计>25%, 停止交易


class TransitionType(enum.StrEnum):
    """状态变更类型。"""

    ESCALATE = "escalate"  # 升级(恶化)
    RECOVER = "recover"    # 自动恢复
    MANUAL = "manual"      # 人工审批恢复/强制重置


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
    daily_return: Decimal              # 当日策略收益率
    nav: Decimal                       # 当日净值
    initial_capital: Decimal           # 初始资金
    cumulative_return: Decimal         # 累计收益率 (nav/initial - 1)
    rolling_20d_return: Decimal | None  # 滚动20日累计收益率(不足20日传None)


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
    l3_rolling_window: int = 20
    l4_cumulative_loss: Decimal = Decimal("-0.25")
    l3_position_multiplier: Decimal = Decimal("0.5")
    l3_recovery_days: int = 5
    l3_recovery_return: Decimal = Decimal("0.02")


# ─────────────────────────────────────────────
# 级别 → 行为映射
# ─────────────────────────────────────────────

_LEVEL_CAN_REBALANCE: dict[CircuitBreakerLevel, bool] = {
    CircuitBreakerLevel.NORMAL: True,
    CircuitBreakerLevel.L1_PAUSED: False,
    CircuitBreakerLevel.L2_HALTED: False,
    CircuitBreakerLevel.L3_REDUCED: True,   # 只允许减仓，由调用方控制
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
                strategy_id, execution_mode, transition,
                entered_date=metrics.trade_date,
                position_multiplier=Decimal("1.0"),
                recovery_streak_days=0,
                recovery_streak_return=Decimal("0"),
                approval_id=None,
            )
            await self._notify_transition(transition)

            logger.info(
                "[RiskControl] %s 从L%d恢复到NORMAL (日期=%s)",
                strategy_id, prev_level.value, metrics.trade_date,
            )

        # 4. 不管是否恢复，都检查触发条件
        triggered_level, trigger_reason, trigger_metrics_dict = (
            self._check_trigger_conditions(metrics)
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
                strategy_id, execution_mode, transition,
                entered_date=metrics.trade_date,
                position_multiplier=new_multiplier,
                recovery_streak_days=0,
                recovery_streak_return=Decimal("0"),
                approval_id=None,
            )
            await self._notify_transition(transition)

            logger.warning(
                "[RiskControl] %s 升级到L%d: %s (日期=%s)",
                strategy_id, new_level.value, trigger_reason, metrics.trade_date,
            )
            current_level = new_level

        # 5. 如果处于L3且未升级也未恢复，更新recovery streak
        if current_level == CircuitBreakerLevel.L3_REDUCED and not recovered:
            await self._update_recovery_streak(
                strategy_id, execution_mode, metrics.daily_return
            )

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
            raise ValueError(
                f"策略 {strategy_id} 当前不是L4_STOPPED状态，无法发起恢复审批"
            )

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
            strategy_id, approval_id,
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
            strategy_id, execution_mode, transition,
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
        total_escalations = await self.repo.count_escalations(
            strategy_id, execution_mode
        )
        last_escalation = await self.repo.get_last_escalation_date(
            strategy_id, execution_mode
        )

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
            "last_escalation_date": (
                last_escalation.isoformat() if last_escalation else None
            ),
            "l3_recovery_progress": l3_progress,
            "thresholds": {
                "l1_daily_loss": float(self.thresholds.l1_daily_loss),
                "l2_daily_loss": float(self.thresholds.l2_daily_loss),
                "l3_rolling_loss": float(self.thresholds.l3_rolling_loss),
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
            strategy_id, execution_mode,
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
            strategy_id, execution_mode, transition,
            entered_date=today,
            position_multiplier=Decimal("1.0"),
            recovery_streak_days=0,
            recovery_streak_return=Decimal("0"),
            approval_id=None,
        )
        await self._notify_transition(transition)

        logger.warning(
            "[RiskControl] 强制重置: strategy=%s 从L%d→NORMAL 原因=%s",
            strategy_id, prev_level.value, reason,
        )
        return await self.get_current_state(strategy_id, execution_mode)

    # ── 内部方法 ──

    def _check_trigger_conditions(
        self,
        metrics: RiskMetrics,
    ) -> tuple[CircuitBreakerLevel, str, dict[str, Any]]:
        """评估熔断触发条件(纯计算, 不写DB)。

        按严重程度从高到低检查: L4 → L3 → L2 → L1 → NORMAL。

        Args:
            metrics: 当日风控指标。

        Returns:
            (触发级别, 原因描述, 指标快照)。
        """
        metrics_dict = _metrics_to_dict(metrics)

        # L4: 累计亏>25%
        if metrics.cumulative_return <= self.thresholds.l4_cumulative_loss:
            return (
                CircuitBreakerLevel.L4_STOPPED,
                f"累计亏损{float(metrics.cumulative_return) * 100:.1f}%"
                f"(阈值{float(self.thresholds.l4_cumulative_loss) * 100:.0f}%)，停止交易",
                metrics_dict,
            )

        # L3: 滚动20日亏>10%
        if (
            metrics.rolling_20d_return is not None
            and metrics.rolling_20d_return <= self.thresholds.l3_rolling_loss
        ):
            return (
                CircuitBreakerLevel.L3_REDUCED,
                f"滚动20日亏损{float(metrics.rolling_20d_return) * 100:.1f}%"
                f"(阈值{float(self.thresholds.l3_rolling_loss) * 100:.0f}%)，降仓50%",
                metrics_dict,
            )

        # L2: 单日亏>5%
        if metrics.daily_return <= self.thresholds.l2_daily_loss:
            return (
                CircuitBreakerLevel.L2_HALTED,
                f"单日亏损{float(metrics.daily_return) * 100:.1f}%"
                f"(阈值{float(self.thresholds.l2_daily_loss) * 100:.0f}%)，全部暂停",
                metrics_dict,
            )

        # L1: 单日亏>3%
        if metrics.daily_return <= self.thresholds.l1_daily_loss:
            return (
                CircuitBreakerLevel.L1_PAUSED,
                f"单日亏损{float(metrics.daily_return) * 100:.1f}%"
                f"(阈值{float(self.thresholds.l1_daily_loss) * 100:.0f}%)，暂停1天",
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
        L3: recovery_streak_days >= 5 且 recovery_streak_return > 2%
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
            streak_return = Decimal(
                str(db_state.get("recovery_streak_return", 0) or 0)
            )
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
            prev_return = Decimal(
                str(db_state.get("recovery_streak_return", 0) or 0)
            )
            new_return = prev_return + daily_return
        else:
            # 亏损或持平: 重置
            new_days = 0
            new_return = Decimal("0")

        await self.repo.update_recovery_streak(
            strategy_id, execution_mode, new_days, new_return
        )

        logger.debug(
            "[RiskControl] L3恢复追踪: strategy=%s streak=%d天 累计=%.4f%%",
            strategy_id, new_days, float(new_return) * 100,
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
        recovery_streak_return=Decimal(
            str(db_state.get("recovery_streak_return", 0) or 0)
        ),
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
        "rolling_20d_return": (
            float(metrics.rolling_20d_return)
            if metrics.rolling_20d_return is not None
            else None
        ),
    }
