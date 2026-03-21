"""RiskControlService 状态机测试 + 风控API端点测试。

测试策略:
- 状态机核心逻辑: mock RiskRepository + NotificationService，
  验证4级熔断的全路径转换(触发/恢复/跳级/streak重置)。
- API端点: dependency_overrides mock掉 RiskControlService，验证路由层。

覆盖的状态机路径:
  1. NORMAL → L1(日亏>3%) → NORMAL(次日自动恢复)
  2. NORMAL → L2(日亏>5%) → NORMAL(恢复条件满足)
  3. NORMAL → L3(20日累计>10%) → 降仓50% → 连续5天盈利>2% → NORMAL
  4. NORMAL → L4(累计>25%) → 人工审批 → NORMAL
  5. L1 → L3(同时满足两条件直接跳级)
  6. L3 streak重置(当日亏损时streak归零)

API端点(4个):
  7. GET /api/risk/state/{id}
  8. GET /api/risk/summary/{id}
  9. POST /api/risk/l4-recovery/{id}
  10. POST /api/risk/force-reset/{id}
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.risk_control_service import (
    CircuitBreakerLevel,
    CircuitBreakerState,
    CircuitBreakerThresholds,
    RiskControlService,
    RiskMetrics,
    TransitionType,
    _LEVEL_CAN_REBALANCE,
    _LEVEL_POSITION_MULTIPLIER,
)


# ============================================================================
# Helpers
# ============================================================================

STRATEGY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
EXEC_MODE = "paper"
TODAY = date(2026, 3, 20)
YESTERDAY = TODAY - timedelta(days=1)
INITIAL_CAPITAL = Decimal("1000000")


def _make_metrics(
    daily_return: Decimal = Decimal("0.01"),
    cumulative_return: Decimal = Decimal("0.05"),
    rolling_20d_return: Decimal | None = Decimal("0.02"),
    trade_date: date = TODAY,
    nav: Decimal | None = None,
) -> RiskMetrics:
    """构造RiskMetrics测试数据。"""
    if nav is None:
        nav = INITIAL_CAPITAL * (Decimal("1") + cumulative_return)
    return RiskMetrics(
        trade_date=trade_date,
        daily_return=daily_return,
        nav=nav,
        initial_capital=INITIAL_CAPITAL,
        cumulative_return=cumulative_return,
        rolling_20d_return=rolling_20d_return,
    )


def _make_db_state(
    current_level: int = 0,
    entered_date: date = YESTERDAY,
    trigger_reason: str = "初始化",
    trigger_metrics: dict[str, Any] | None = None,
    recovery_streak_days: int = 0,
    recovery_streak_return: Decimal = Decimal("0"),
    position_multiplier: Decimal = Decimal("1.0"),
    approval_id: str | None = None,
) -> dict[str, Any]:
    """构造repo.get_state()返回的字典。"""
    return {
        "id": str(uuid.uuid4()),
        "strategy_id": str(STRATEGY_ID),
        "execution_mode": EXEC_MODE,
        "current_level": current_level,
        "entered_at": "2026-03-19T00:00:00+00:00",
        "entered_date": entered_date,
        "trigger_reason": trigger_reason,
        "trigger_metrics": trigger_metrics or {},
        "recovery_streak_days": recovery_streak_days,
        "recovery_streak_return": recovery_streak_return,
        "position_multiplier": position_multiplier,
        "approval_id": approval_id,
        "updated_at": "2026-03-19T00:00:00+00:00",
    }


def _build_service(
    get_state_returns: list[dict[str, Any] | None] | None = None,
    approval_status: str | None = None,
) -> tuple[RiskControlService, MagicMock, AsyncMock]:
    """构造带mock repo和mock notification的RiskControlService。

    Args:
        get_state_returns: repo.get_state的返回值序列(side_effect)。
        approval_status: repo.get_approval_status的返回值。

    Returns:
        (service, mock_repo, mock_notification)
    """
    mock_session = AsyncMock()
    mock_notification = AsyncMock()
    mock_notification.send = AsyncMock()

    service = RiskControlService(
        session=mock_session,
        notification_service=mock_notification,
    )

    # Mock repository
    mock_repo = MagicMock()
    mock_repo.ensure_tables = AsyncMock()
    mock_repo.upsert_state = AsyncMock(return_value=_make_db_state())
    mock_repo.insert_log = AsyncMock(return_value={})
    mock_repo.update_recovery_streak = AsyncMock()
    mock_repo.get_approval_status = AsyncMock(return_value=approval_status)
    mock_repo.count_escalations = AsyncMock(return_value=0)
    mock_repo.get_last_escalation_date = AsyncMock(return_value=None)
    mock_repo.get_logs = AsyncMock(return_value=[])
    mock_repo.execute = AsyncMock()
    mock_repo.fetch_one = AsyncMock()

    if get_state_returns is not None:
        mock_repo.get_state = AsyncMock(side_effect=get_state_returns)
    else:
        mock_repo.get_state = AsyncMock(return_value=None)

    service.repo = mock_repo
    return service, mock_repo, mock_notification


# ============================================================================
# 状态机测试
# ============================================================================


class TestCircuitBreakerStateMachine:
    """4级熔断状态机全路径覆盖。"""

    # ── 路径1: NORMAL → L1(日亏>3%) → NORMAL(次日自动恢复) ──

    @pytest.mark.asyncio
    async def test_normal_to_l1_on_daily_loss_gt_3pct(self):
        """NORMAL状态下日亏超过3%触发L1_PAUSED。"""
        normal_state = _make_db_state(current_level=0, entered_date=YESTERDAY)
        # get_state被调用: 1)check_and_update开头 2)返回最新状态
        l1_state = _make_db_state(
            current_level=1,
            entered_date=TODAY,
            trigger_reason="单日亏损-3.5%(阈值-3%)，暂停1天",
            position_multiplier=Decimal("1.0"),
        )
        service, mock_repo, mock_notif = _build_service(
            get_state_returns=[normal_state, l1_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.035"),  # -3.5% > L1阈值-3%
            cumulative_return=Decimal("-0.02"),
            rolling_20d_return=Decimal("-0.01"),
            trade_date=TODAY,
        )

        result = await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 验证upsert_state被调用，且new_level=L1
        mock_repo.upsert_state.assert_called()
        call_kwargs = mock_repo.upsert_state.call_args
        assert call_kwargs.kwargs["current_level"] == CircuitBreakerLevel.L1_PAUSED

        # 验证log被记录
        mock_repo.insert_log.assert_called()
        log_kwargs = mock_repo.insert_log.call_args.kwargs
        assert log_kwargs["prev_level"] == CircuitBreakerLevel.NORMAL
        assert log_kwargs["new_level"] == CircuitBreakerLevel.L1_PAUSED
        assert log_kwargs["transition_type"] == "escalate"

        # 验证通知被发送
        mock_notif.send.assert_called()

    @pytest.mark.asyncio
    async def test_l1_recovers_next_day(self):
        """L1状态在次日自动恢复到NORMAL。"""
        # L1 entered yesterday, today is next day → should recover
        l1_state = _make_db_state(
            current_level=1,
            entered_date=YESTERDAY,
            position_multiplier=Decimal("1.0"),
        )
        normal_state = _make_db_state(
            current_level=0,
            entered_date=TODAY,
            position_multiplier=Decimal("1.0"),
        )
        service, mock_repo, mock_notif = _build_service(
            get_state_returns=[l1_state, normal_state]
        )

        # 正常日收益(不触发任何level)
        metrics = _make_metrics(
            daily_return=Decimal("0.005"),
            cumulative_return=Decimal("0.03"),
            rolling_20d_return=Decimal("0.01"),
            trade_date=TODAY,
        )

        result = await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 验证恢复transition被持久化
        assert mock_repo.upsert_state.call_count >= 1
        # 第一次upsert应该是恢复到NORMAL
        first_call = mock_repo.upsert_state.call_args_list[0]
        assert first_call.kwargs["current_level"] == CircuitBreakerLevel.NORMAL
        assert first_call.kwargs["position_multiplier"] == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_l1_does_not_recover_same_day(self):
        """L1当天不恢复(entered_date == trade_date)。"""
        l1_state = _make_db_state(
            current_level=1,
            entered_date=TODAY,  # 同一天
        )
        # get_state: 1) check_and_update 2) final get_current_state
        service, mock_repo, _ = _build_service(
            get_state_returns=[l1_state, l1_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("0.005"),  # 正常
            cumulative_return=Decimal("0.03"),
            rolling_20d_return=Decimal("0.01"),
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 没有恢复transition，upsert不应该被调用(因为无状态变更)
        mock_repo.upsert_state.assert_not_called()

    # ── 路径2: NORMAL → L2(日亏>5%) → NORMAL(次日恢复) ──

    @pytest.mark.asyncio
    async def test_normal_to_l2_on_daily_loss_gt_5pct(self):
        """NORMAL状态下日亏超过5%触发L2_HALTED。"""
        normal_state = _make_db_state(current_level=0, entered_date=YESTERDAY)
        l2_state = _make_db_state(current_level=2, entered_date=TODAY)
        service, mock_repo, mock_notif = _build_service(
            get_state_returns=[normal_state, l2_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.06"),  # -6% > L2阈值-5%
            cumulative_return=Decimal("-0.04"),
            rolling_20d_return=Decimal("-0.03"),
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        call_kwargs = mock_repo.upsert_state.call_args.kwargs
        assert call_kwargs["current_level"] == CircuitBreakerLevel.L2_HALTED

        # L2应该触发P0通知
        mock_notif.send.assert_called()
        notif_kwargs = mock_notif.send.call_args.kwargs
        assert notif_kwargs["level"] == "P0"
        assert notif_kwargs["force"] is True

    @pytest.mark.asyncio
    async def test_l2_recovers_next_day(self):
        """L2状态在次日自动恢复到NORMAL。"""
        l2_state = _make_db_state(
            current_level=2,
            entered_date=YESTERDAY,
        )
        normal_state = _make_db_state(current_level=0, entered_date=TODAY)
        service, mock_repo, _ = _build_service(
            get_state_returns=[l2_state, normal_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("0.01"),
            cumulative_return=Decimal("0.01"),
            rolling_20d_return=Decimal("0.005"),
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        first_call = mock_repo.upsert_state.call_args_list[0]
        assert first_call.kwargs["current_level"] == CircuitBreakerLevel.NORMAL

    # ── 路径3: NORMAL → L3(20日累计>10%) → 降仓 → 连续5天盈利>2% → NORMAL ──

    @pytest.mark.asyncio
    async def test_normal_to_l3_on_rolling_20d_loss(self):
        """NORMAL状态下滚动20日累计亏损>10%触发L3_REDUCED。"""
        normal_state = _make_db_state(current_level=0)
        l3_state = _make_db_state(
            current_level=3,
            entered_date=TODAY,
            position_multiplier=Decimal("0.5"),
        )
        # get_state calls: 1) check_and_update 2) get_current_state at end
        service, mock_repo, _ = _build_service(
            get_state_returns=[normal_state, l3_state, l3_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.02"),
            cumulative_return=Decimal("-0.08"),
            rolling_20d_return=Decimal("-0.12"),  # -12% > L3阈值-10%
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        call_kwargs = mock_repo.upsert_state.call_args.kwargs
        assert call_kwargs["current_level"] == CircuitBreakerLevel.L3_REDUCED
        assert call_kwargs["position_multiplier"] == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_l3_position_multiplier_is_half(self):
        """L3的仓位系数应为0.5。"""
        assert _LEVEL_POSITION_MULTIPLIER[CircuitBreakerLevel.L3_REDUCED] == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_l3_recovery_after_5_day_streak(self):
        """L3恢复: 连续5天盈利且累计>2%后恢复到NORMAL。"""
        # L3 state with streak already at 5 days, 2.5% return
        l3_state = _make_db_state(
            current_level=3,
            entered_date=date(2026, 3, 10),  # 10天前
            position_multiplier=Decimal("0.5"),
            recovery_streak_days=5,
            recovery_streak_return=Decimal("0.025"),  # 2.5% > 2%阈值
        )
        normal_state = _make_db_state(
            current_level=0,
            entered_date=TODAY,
            position_multiplier=Decimal("1.0"),
        )
        service, mock_repo, _ = _build_service(
            get_state_returns=[l3_state, normal_state]
        )

        # 当日收益正常(不触发任何level)
        metrics = _make_metrics(
            daily_return=Decimal("0.005"),
            cumulative_return=Decimal("-0.05"),
            rolling_20d_return=Decimal("-0.03"),  # 20日已恢复到-3%，不再触发L3
            trade_date=TODAY,
        )

        result = await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 验证恢复: 第一次upsert是恢复到NORMAL, multiplier=1.0
        first_call = mock_repo.upsert_state.call_args_list[0]
        assert first_call.kwargs["current_level"] == CircuitBreakerLevel.NORMAL
        assert first_call.kwargs["position_multiplier"] == Decimal("1.0")
        assert first_call.kwargs["recovery_streak_days"] == 0

    @pytest.mark.asyncio
    async def test_l3_streak_increments_on_positive_day(self):
        """L3中当日盈利时streak_days+1。"""
        l3_state = _make_db_state(
            current_level=3,
            entered_date=date(2026, 3, 15),
            position_multiplier=Decimal("0.5"),
            recovery_streak_days=2,
            recovery_streak_return=Decimal("0.008"),
        )
        # 未满足恢复条件(streak_days=2 < 5)，所以不恢复
        # get_state: 1) check_and_update 2) _update_recovery_streak 3) final state
        service, mock_repo, _ = _build_service(
            get_state_returns=[l3_state, l3_state, l3_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("0.003"),  # 盈利
            cumulative_return=Decimal("-0.06"),
            rolling_20d_return=Decimal("-0.08"),  # 仍然在L3范围内但因为已经是L3不会再触发升级
            trade_date=TODAY,
        )

        # 由于L3 rolling还是 <= -0.10 以下面的条件时会重新触发L3
        # 但因为 triggered_level == current_level (不是 >)，不会升级
        # 所以会走到 _update_recovery_streak

        # 修正: rolling_20d_return=-0.08 > -0.10 所以不触发L3
        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 验证streak更新
        mock_repo.update_recovery_streak.assert_called_once()
        call_args = mock_repo.update_recovery_streak.call_args
        assert call_args.args[2] == 3  # streak_days: 2 + 1 = 3
        expected_return = Decimal("0.008") + Decimal("0.003")
        assert call_args.args[3] == expected_return

    # ── 路径6: L3 streak重置 ──

    @pytest.mark.asyncio
    async def test_l3_streak_resets_on_loss_day(self):
        """L3中当日亏损时streak重置为0。"""
        l3_state = _make_db_state(
            current_level=3,
            entered_date=date(2026, 3, 15),
            position_multiplier=Decimal("0.5"),
            recovery_streak_days=3,
            recovery_streak_return=Decimal("0.012"),
        )
        service, mock_repo, _ = _build_service(
            get_state_returns=[l3_state, l3_state, l3_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.001"),  # 亏损
            cumulative_return=Decimal("-0.07"),
            rolling_20d_return=Decimal("-0.05"),  # 不再触发L3
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        mock_repo.update_recovery_streak.assert_called_once()
        call_args = mock_repo.update_recovery_streak.call_args
        assert call_args.args[2] == 0  # streak重置
        assert call_args.args[3] == Decimal("0")

    @pytest.mark.asyncio
    async def test_l3_streak_resets_on_zero_return(self):
        """L3中当日持平(return=0)时streak也重置。"""
        l3_state = _make_db_state(
            current_level=3,
            entered_date=date(2026, 3, 15),
            position_multiplier=Decimal("0.5"),
            recovery_streak_days=4,
            recovery_streak_return=Decimal("0.018"),
        )
        service, mock_repo, _ = _build_service(
            get_state_returns=[l3_state, l3_state, l3_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("0"),  # 持平
            cumulative_return=Decimal("-0.07"),
            rolling_20d_return=Decimal("-0.05"),
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        mock_repo.update_recovery_streak.assert_called_once()
        call_args = mock_repo.update_recovery_streak.call_args
        assert call_args.args[2] == 0  # streak重置

    # ── 路径4: NORMAL → L4(累计>25%) → 人工审批 → NORMAL ──

    @pytest.mark.asyncio
    async def test_normal_to_l4_on_cumulative_loss(self):
        """NORMAL状态下累计亏损>25%触发L4_STOPPED。"""
        normal_state = _make_db_state(current_level=0)
        l4_state = _make_db_state(
            current_level=4,
            entered_date=TODAY,
            position_multiplier=Decimal("0.0"),
        )
        service, mock_repo, mock_notif = _build_service(
            get_state_returns=[normal_state, l4_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.08"),
            cumulative_return=Decimal("-0.28"),  # -28% > L4阈值-25%
            rolling_20d_return=Decimal("-0.15"),
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        call_kwargs = mock_repo.upsert_state.call_args.kwargs
        assert call_kwargs["current_level"] == CircuitBreakerLevel.L4_STOPPED
        assert call_kwargs["position_multiplier"] == Decimal("0.0")

        # L4是最严重的，P0通知
        mock_notif.send.assert_called()

    @pytest.mark.asyncio
    async def test_l4_requires_manual_approval(self):
        """L4状态标记requires_manual_approval=True。"""
        state = CircuitBreakerState(
            level=CircuitBreakerLevel.L4_STOPPED,
            entered_date=TODAY,
            trigger_reason="累计亏损-28%",
            trigger_metrics={},
            position_multiplier=Decimal("0.0"),
            recovery_streak_days=0,
            recovery_streak_return=Decimal("0"),
            can_rebalance=False,
            approval_id=None,
        )
        assert state.requires_manual_approval is True
        assert state.is_normal is False

    @pytest.mark.asyncio
    async def test_l4_recovers_after_approval(self):
        """L4状态: approval approved → 恢复到NORMAL。"""
        approval_uuid = uuid.uuid4()
        l4_state = _make_db_state(
            current_level=4,
            entered_date=date(2026, 3, 15),
            position_multiplier=Decimal("0.0"),
            approval_id=str(approval_uuid),
        )
        normal_state = _make_db_state(
            current_level=0,
            entered_date=TODAY,
            position_multiplier=Decimal("1.0"),
        )
        service, mock_repo, _ = _build_service(
            get_state_returns=[l4_state, normal_state],
            approval_status="approved",
        )

        # 正常指标(不触发任何level)
        metrics = _make_metrics(
            daily_return=Decimal("0.01"),
            cumulative_return=Decimal("-0.20"),  # 累计仍亏但不超过25%
            rolling_20d_return=Decimal("0.02"),
            trade_date=TODAY,
        )

        result = await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 应该触发恢复
        first_call = mock_repo.upsert_state.call_args_list[0]
        assert first_call.kwargs["current_level"] == CircuitBreakerLevel.NORMAL
        assert first_call.kwargs["position_multiplier"] == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_l4_stays_without_approval(self):
        """L4状态: 没有审批 → 保持L4。"""
        l4_state = _make_db_state(
            current_level=4,
            entered_date=date(2026, 3, 15),
            position_multiplier=Decimal("0.0"),
            approval_id=None,  # 无审批ID
        )
        service, mock_repo, _ = _build_service(
            get_state_returns=[l4_state, l4_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("0.01"),
            cumulative_return=Decimal("-0.20"),
            rolling_20d_return=Decimal("0.02"),
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 无恢复、无升级 → upsert不调用
        mock_repo.upsert_state.assert_not_called()

    # ── 路径5: L1 → L3 跳级(同时满足两个条件) ──

    @pytest.mark.asyncio
    async def test_l1_to_l3_skip_escalation(self):
        """L1状态下若同时触发L3条件，直接跳级到L3。

        场景: L1是当天触发的(不恢复)，同时rolling_20d也满足L3。
        由于check_trigger_conditions返回的triggered_level(L3) > current_level(L1)，
        会执行升级。
        """
        l1_state = _make_db_state(
            current_level=1,
            entered_date=TODAY,  # 当天，不恢复
        )
        l3_state = _make_db_state(
            current_level=3,
            entered_date=TODAY,
            position_multiplier=Decimal("0.5"),
        )
        # get_state calls: 1) check_and_update 2) get_current_state at end
        service, mock_repo, _ = _build_service(
            get_state_returns=[l1_state, l3_state, l3_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.035"),  # 触发L1
            cumulative_return=Decimal("-0.08"),
            rolling_20d_return=Decimal("-0.12"),  # 同时触发L3
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 应该直接升级到L3(跳过L2)
        call_kwargs = mock_repo.upsert_state.call_args.kwargs
        assert call_kwargs["current_level"] == CircuitBreakerLevel.L3_REDUCED
        assert call_kwargs["position_multiplier"] == Decimal("0.5")

        log_kwargs = mock_repo.insert_log.call_args.kwargs
        assert log_kwargs["prev_level"] == CircuitBreakerLevel.L1_PAUSED
        assert log_kwargs["new_level"] == CircuitBreakerLevel.L3_REDUCED

    @pytest.mark.asyncio
    async def test_l1_recovers_then_triggers_l3_same_day(self):
        """L1次日恢复后，当天如果触发L3条件，应再次升级。

        check_and_update先恢复到NORMAL，再检查触发条件。
        如果rolling_20d满足L3条件，应当天就升级。
        """
        l1_state = _make_db_state(
            current_level=1,
            entered_date=YESTERDAY,  # 次日，会恢复
        )
        # 恢复后get_state返回NORMAL，再升级后返回L3
        l3_state = _make_db_state(
            current_level=3,
            entered_date=TODAY,
            position_multiplier=Decimal("0.5"),
        )
        service, mock_repo, _ = _build_service(
            get_state_returns=[l1_state, l3_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.02"),  # 不触发L1
            cumulative_return=Decimal("-0.09"),
            rolling_20d_return=Decimal("-0.11"),  # 触发L3
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)

        # 应该有2次upsert: 1)恢复到NORMAL, 2)升级到L3
        assert mock_repo.upsert_state.call_count == 2
        first_call = mock_repo.upsert_state.call_args_list[0]
        assert first_call.kwargs["current_level"] == CircuitBreakerLevel.NORMAL
        second_call = mock_repo.upsert_state.call_args_list[1]
        assert second_call.kwargs["current_level"] == CircuitBreakerLevel.L3_REDUCED

    # ── 边界条件 ──

    @pytest.mark.asyncio
    async def test_exact_l1_threshold_triggers(self):
        """恰好等于L1阈值(-3%)应该触发。"""
        normal_state = _make_db_state(current_level=0)
        l1_state = _make_db_state(current_level=1)
        service, mock_repo, _ = _build_service(
            get_state_returns=[normal_state, l1_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.03"),  # 恰好等于阈值
            cumulative_return=Decimal("-0.02"),
            rolling_20d_return=Decimal("-0.01"),
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)
        call_kwargs = mock_repo.upsert_state.call_args.kwargs
        assert call_kwargs["current_level"] == CircuitBreakerLevel.L1_PAUSED

    @pytest.mark.asyncio
    async def test_just_above_l1_threshold_no_trigger(self):
        """日亏-2.99%不触发L1(未达到阈值)。"""
        normal_state = _make_db_state(current_level=0)
        service, mock_repo, _ = _build_service(
            get_state_returns=[normal_state, normal_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.029"),  # > -0.03, 不触发
            cumulative_return=Decimal("-0.02"),
            rolling_20d_return=Decimal("-0.01"),
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)
        # 不应触发任何升级
        mock_repo.upsert_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_rolling_20d_none_skips_l3_check(self):
        """rolling_20d_return为None时跳过L3检查(不足20日)。"""
        normal_state = _make_db_state(current_level=0)
        l1_state = _make_db_state(current_level=1)
        service, mock_repo, _ = _build_service(
            get_state_returns=[normal_state, l1_state]
        )

        metrics = _make_metrics(
            daily_return=Decimal("-0.035"),  # 触发L1，但不是L3
            cumulative_return=Decimal("-0.02"),
            rolling_20d_return=None,  # 不足20日
            trade_date=TODAY,
        )

        await service.check_and_update(STRATEGY_ID, EXEC_MODE, metrics)
        call_kwargs = mock_repo.upsert_state.call_args.kwargs
        # 应该触发L1，而非L3
        assert call_kwargs["current_level"] == CircuitBreakerLevel.L1_PAUSED

    @pytest.mark.asyncio
    async def test_initialize_state_creates_normal(self):
        """首次运行时初始化为NORMAL状态。"""
        normal_state = _make_db_state(current_level=0, trigger_reason="初始化")
        service, mock_repo, _ = _build_service(
            get_state_returns=[None, normal_state]
        )

        result = await service.initialize_state(STRATEGY_ID, EXEC_MODE)

        mock_repo.upsert_state.assert_called_once()
        call_kwargs = mock_repo.upsert_state.call_args.kwargs
        assert call_kwargs["current_level"] == CircuitBreakerLevel.NORMAL
        assert call_kwargs["position_multiplier"] == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_force_reset_to_normal(self):
        """force_reset将任何状态强制重置到NORMAL。"""
        l3_state = _make_db_state(
            current_level=3,
            position_multiplier=Decimal("0.5"),
        )
        normal_state = _make_db_state(
            current_level=0,
            position_multiplier=Decimal("1.0"),
        )
        service, mock_repo, mock_notif = _build_service(
            get_state_returns=[l3_state, normal_state]
        )

        result = await service.force_reset(STRATEGY_ID, EXEC_MODE, "紧急运维")

        mock_repo.upsert_state.assert_called_once()
        call_kwargs = mock_repo.upsert_state.call_args.kwargs
        assert call_kwargs["current_level"] == CircuitBreakerLevel.NORMAL
        assert call_kwargs["position_multiplier"] == Decimal("1.0")

        log_kwargs = mock_repo.insert_log.call_args.kwargs
        assert log_kwargs["transition_type"] == "manual"
        assert "强制重置" in log_kwargs["reason"]

    @pytest.mark.asyncio
    async def test_force_reset_empty_reason_raises(self):
        """force_reset空原因抛ValueError。"""
        service, _, _ = _build_service()
        with pytest.raises(ValueError, match="强制重置必须提供原因"):
            await service.force_reset(STRATEGY_ID, EXEC_MODE, "  ")

    @pytest.mark.asyncio
    async def test_check_trigger_returns_highest_level(self):
        """同时满足多个条件时，返回最严重的级别(L4 > L3 > L2 > L1)。"""
        service, _, _ = _build_service()

        # 满足L1 + L2 + L3 + L4
        metrics = _make_metrics(
            daily_return=Decimal("-0.08"),  # 触发L1 & L2
            cumulative_return=Decimal("-0.30"),  # 触发L4
            rolling_20d_return=Decimal("-0.15"),  # 触发L3
        )

        level, reason, _ = service._check_trigger_conditions(metrics)
        assert level == CircuitBreakerLevel.L4_STOPPED

    @pytest.mark.asyncio
    async def test_level_properties(self):
        """验证级别映射表的正确性。"""
        # can_rebalance
        assert _LEVEL_CAN_REBALANCE[CircuitBreakerLevel.NORMAL] is True
        assert _LEVEL_CAN_REBALANCE[CircuitBreakerLevel.L1_PAUSED] is False
        assert _LEVEL_CAN_REBALANCE[CircuitBreakerLevel.L2_HALTED] is False
        assert _LEVEL_CAN_REBALANCE[CircuitBreakerLevel.L3_REDUCED] is True
        assert _LEVEL_CAN_REBALANCE[CircuitBreakerLevel.L4_STOPPED] is False

        # position_multiplier
        assert _LEVEL_POSITION_MULTIPLIER[CircuitBreakerLevel.NORMAL] == Decimal("1.0")
        assert _LEVEL_POSITION_MULTIPLIER[CircuitBreakerLevel.L3_REDUCED] == Decimal("0.5")
        assert _LEVEL_POSITION_MULTIPLIER[CircuitBreakerLevel.L4_STOPPED] == Decimal("0.0")

    @pytest.mark.asyncio
    async def test_default_thresholds(self):
        """验证DESIGN_V5默认阈值。"""
        t = CircuitBreakerThresholds()
        assert t.l1_daily_loss == Decimal("-0.03")
        assert t.l2_daily_loss == Decimal("-0.05")
        assert t.l3_rolling_loss == Decimal("-0.10")
        assert t.l4_cumulative_loss == Decimal("-0.25")
        assert t.l3_position_multiplier == Decimal("0.5")
        assert t.l3_recovery_days == 5
        assert t.l3_recovery_return == Decimal("0.02")


# ============================================================================
# API端点测试
# ============================================================================


class TestRiskAPI:
    """风控API路由测试(mock Service层)。"""

    @pytest_asyncio.fixture
    async def api_client(self):
        """带mock的API客户端。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    def _make_mock_state(
        self,
        level: CircuitBreakerLevel = CircuitBreakerLevel.NORMAL,
    ) -> CircuitBreakerState:
        """构造CircuitBreakerState mock返回值。"""
        return CircuitBreakerState(
            level=level,
            entered_date=TODAY,
            trigger_reason="测试",
            trigger_metrics={},
            position_multiplier=_LEVEL_POSITION_MULTIPLIER[level],
            recovery_streak_days=0,
            recovery_streak_return=Decimal("0"),
            can_rebalance=_LEVEL_CAN_REBALANCE[level],
            approval_id=None,
        )

    # ── 7. GET /api/risk/state/{id} ──

    @pytest.mark.asyncio
    async def test_get_risk_state(self, api_client: AsyncClient):
        """GET /api/risk/state/{id} 返回当前状态。"""
        mock_state = self._make_mock_state(CircuitBreakerLevel.L3_REDUCED)

        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.get_current_state = AsyncMock(return_value=mock_state)
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        try:
            resp = await api_client.get(
                f"/api/risk/state/{STRATEGY_ID}?execution_mode=paper"
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == 3
        assert data["level_name"] == "L3_REDUCED"
        assert data["position_multiplier"] == 0.5
        assert data["can_rebalance"] is True

    @pytest.mark.asyncio
    async def test_get_risk_state_invalid_uuid(self, api_client: AsyncClient):
        """GET /api/risk/state/invalid 返回400。"""
        resp = await api_client.get("/api/risk/state/not-a-uuid")
        assert resp.status_code == 400
        assert "无效" in resp.json()["detail"]

    # ── 8. GET /api/risk/summary/{id} ──

    @pytest.mark.asyncio
    async def test_get_risk_summary(self, api_client: AsyncClient):
        """GET /api/risk/summary/{id} 返回风控摘要。"""
        summary_data = {
            "current_level": 0,
            "current_level_name": "NORMAL",
            "can_rebalance": True,
            "position_multiplier": 1.0,
            "days_in_current_state": 5,
            "entered_date": "2026-03-15",
            "trigger_reason": "初始化",
            "total_escalations": 2,
            "last_escalation_date": "2026-03-10",
            "l3_recovery_progress": None,
            "thresholds": {
                "l1_daily_loss": -0.03,
                "l2_daily_loss": -0.05,
                "l3_rolling_loss": -0.10,
                "l4_cumulative_loss": -0.25,
                "l3_recovery_days": 5,
                "l3_recovery_return": 0.02,
            },
        }

        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.get_risk_summary = AsyncMock(return_value=summary_data)
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        try:
            resp = await api_client.get(
                f"/api/risk/summary/{STRATEGY_ID}?execution_mode=paper"
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["current_level"] == 0
        assert data["total_escalations"] == 2
        assert data["thresholds"]["l1_daily_loss"] == -0.03

    # ── 9. POST /api/risk/l4-recovery/{id} ──

    @pytest.mark.asyncio
    async def test_l4_recovery_request_success(self, api_client: AsyncClient):
        """POST /api/risk/l4-recovery/{id} 成功时返回approval_id。"""
        approval_id = uuid.uuid4()
        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.request_l4_recovery = AsyncMock(return_value=approval_id)
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        try:
            resp = await api_client.post(
                f"/api/risk/l4-recovery/{STRATEGY_ID}?execution_mode=paper",
                json={"reviewer_note": "策略已优化，申请恢复交易"},
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_id"] == str(approval_id)
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_l4_recovery_request_not_in_l4(self, api_client: AsyncClient):
        """POST /api/risk/l4-recovery/{id} 不在L4状态时返回400。"""
        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.request_l4_recovery = AsyncMock(
            side_effect=ValueError("策略当前不是L4_STOPPED状态")
        )
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        try:
            resp = await api_client.post(
                f"/api/risk/l4-recovery/{STRATEGY_ID}?execution_mode=paper",
                json={"reviewer_note": "测试"},
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 400
        assert "L4_STOPPED" in resp.json()["detail"]

    # ── 10. POST /api/risk/force-reset/{id} ──

    @pytest.mark.asyncio
    async def test_force_reset_api(self, api_client: AsyncClient):
        """POST /api/risk/force-reset/{id} 成功重置。"""
        mock_state = self._make_mock_state(CircuitBreakerLevel.NORMAL)

        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.force_reset = AsyncMock(return_value=mock_state)
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        try:
            resp = await api_client.post(
                f"/api/risk/force-reset/{STRATEGY_ID}?execution_mode=paper",
                json={"reason": "紧急运维重置"},
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == 0
        assert data["level_name"] == "NORMAL"
        assert data["position_multiplier"] == 1.0
        assert "强制重置" not in data.get("trigger_reason", "")  # mock返回的是"测试"

    @pytest.mark.asyncio
    async def test_force_reset_missing_reason(self, api_client: AsyncClient):
        """POST /api/risk/force-reset/{id} 缺少reason返回422。"""
        resp = await api_client.post(
            f"/api/risk/force-reset/{STRATEGY_ID}?execution_mode=paper",
            json={},
        )
        assert resp.status_code == 422  # Pydantic validation error
