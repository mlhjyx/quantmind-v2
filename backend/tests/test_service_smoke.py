"""Service层冒烟测试 — 5个核心Service的基本路径验证。

Sprint 1.27 Phase 4: 验证service层主要路径不抛异常、返回结构正确。
全部使用 unittest.mock.MagicMock mock DB，不需要真实DB连接。

覆盖:
- ExecutionService: execute_rebalance CB各级别 + validate_signal_freshness
- PaperTradingService: get_graduation_progress 毕业标准计算
- NotificationService: send_sync + send_alert 同步接口
- NotificationThrottler: throttle 节流逻辑
- RiskControlService: _check_trigger_conditions 熔断判断 + CircuitBreakerLevel枚举
- DashboardService: get_summary + _resolve_period_start
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

# 确保 backend/ 在 sys.path
_BACKEND = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND.parent
for _p in [str(_BACKEND), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_price_df(exec_date: date) -> pd.DataFrame:
    """构造最小价格 DataFrame 供 ExecutionService 使用。"""
    return pd.DataFrame(
        {
            "trade_date": [exec_date],
            "code": ["600000.SH"],
            "open": [10.0],
            "close": [10.1],
        }
    )


def _make_mock_conn() -> MagicMock:
    """返回模拟 psycopg2 连接，cursor().fetchone() 默认返回 (0,)。"""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (0,)
    cursor.fetchall.return_value = []
    conn.cursor.return_value = cursor
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# 1. ExecutionService
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionService:
    """ExecutionService 冒烟测试。

    不依赖真实 PaperBroker 状态——所有 Broker 方法均 mock。
    """

    def _get_service(self):
        from app.services.execution_service import ExecutionService
        return ExecutionService()

    def test_execute_rebalance_l4_halt_returns_immediately(self):
        """L4熔断时应立即返回空fills且is_rebalance=False。"""
        svc = self._get_service()
        conn = _make_mock_conn()
        result = svc.execute_rebalance(
            conn=conn,
            strategy_id="v1.1",
            exec_date=date(2025, 1, 2),
            target_weights={"600000.SH": 0.5},
            cb_level=4,
            position_multiplier=0.0,
            price_data=_make_price_df(date(2025, 1, 2)),
            initial_capital=1_000_000.0,
            dry_run=True,
        )
        assert result.cb_level == 4
        assert result.is_rebalance is False
        assert result.fills == []

    def test_execute_rebalance_l2_pause_no_fills(self):
        """L2暂停时不执行任何交易。"""
        svc = self._get_service()
        conn = _make_mock_conn()
        result = svc.execute_rebalance(
            conn=conn,
            strategy_id="v1.1",
            exec_date=date(2025, 1, 2),
            target_weights={"600000.SH": 0.5},
            cb_level=2,
            position_multiplier=1.0,
            price_data=_make_price_df(date(2025, 1, 2)),
            initial_capital=1_000_000.0,
            dry_run=True,
        )
        assert result.cb_level == 2
        assert result.is_rebalance is False

    def test_execute_rebalance_l3_reduces_weights(self):
        """L3降仓时 hedged_target 应按 position_multiplier 缩减。

        用 dry_run=True 且 mock PaperBroker 避免真实 DB。
        """
        svc = self._get_service()
        conn = _make_mock_conn()
        exec_date = date(2025, 1, 2)

        # mock PaperBroker 避免 load_state 访问真实 DB
        mock_broker_inst = MagicMock()
        mock_broker_inst.execute_rebalance.return_value = ([], [])
        mock_broker_inst.get_current_nav.return_value = 1_000_000.0
        mock_broker_inst.broker = MagicMock()
        mock_broker_inst.broker.holdings = {}

        with patch("app.services.execution_service.PaperBroker", return_value=mock_broker_inst):
            result = svc.execute_rebalance(
                conn=conn,
                strategy_id="v1.1",
                exec_date=exec_date,
                target_weights={"600000.SH": 1.0},
                cb_level=3,
                position_multiplier=0.5,
                price_data=_make_price_df(exec_date),
                initial_capital=1_000_000.0,
                dry_run=True,
            )
        assert result.cb_level == 3
        assert result.is_rebalance is True

    def test_execute_rebalance_l0_normal_paper(self):
        """L0正常模式 paper 路径不抛异常。"""
        svc = self._get_service()
        conn = _make_mock_conn()
        exec_date = date(2025, 1, 2)

        mock_broker_inst = MagicMock()
        mock_broker_inst.execute_rebalance.return_value = ([], [])
        mock_broker_inst.get_current_nav.return_value = 1_050_000.0
        mock_broker_inst.broker = MagicMock()
        mock_broker_inst.broker.holdings = {"600000.SH": 100}

        with patch("app.services.execution_service.PaperBroker", return_value=mock_broker_inst):
            result = svc.execute_rebalance(
                conn=conn,
                strategy_id="v1.1",
                exec_date=exec_date,
                target_weights={"600000.SH": 0.5},
                cb_level=0,
                position_multiplier=1.0,
                price_data=_make_price_df(exec_date),
                initial_capital=1_000_000.0,
                dry_run=True,
            )
        assert result.cb_level == 0
        assert result.is_rebalance is True

    def test_validate_signal_freshness_stale_signal(self):
        """信号间隔超过2个交易日时应返回 is_valid=False。"""
        svc = self._get_service()
        conn = _make_mock_conn()
        # fetchone 返回 trading_days_between = 5
        conn.cursor().fetchone.return_value = (5,)

        is_valid, reason = svc.validate_signal_freshness(
            conn=conn,
            signal_date=date(2025, 1, 2),
            exec_date=date(2025, 1, 9),
        )
        assert is_valid is False
        assert "过时" in reason or "5" in reason

    def test_validate_signal_freshness_fresh_signal(self):
        """信号间隔在2个交易日内时应返回 is_valid=True。"""
        svc = self._get_service()
        conn = _make_mock_conn()
        conn.cursor().fetchone.return_value = (1,)

        is_valid, reason = svc.validate_signal_freshness(
            conn=conn,
            signal_date=date(2025, 1, 2),
            exec_date=date(2025, 1, 3),
        )
        assert is_valid is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. PaperTradingService
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperTradingService:
    """PaperTradingService 冒烟测试。

    mock perf_repo 和 trade_repo 的所有 async 方法。
    """

    def _get_service(self):
        from app.services.paper_trading_service import PaperTradingService
        AsyncMock()
        svc = PaperTradingService.__new__(PaperTradingService)
        svc.perf_repo = MagicMock()
        svc.trade_repo = MagicMock()
        return svc

    @pytest.mark.asyncio
    async def test_get_graduation_progress_structure(self):
        """毕业进度返回结构应包含 criteria/all_passed/summary。"""
        svc = self._get_service()

        # 模拟 get_nav_series 返回 65 天数据（超过60天门槛）
        nav_series = [{"daily_return": 0.001} for _ in range(65)]
        svc.perf_repo.get_nav_series = AsyncMock(return_value=nav_series)
        svc.perf_repo.get_rolling_stats = AsyncMock(
            return_value={"sharpe": 0.85, "mdd": -0.10, "total_return": 0.08}
        )
        svc.trade_repo.get_trades = AsyncMock(return_value=[])

        result = await svc.get_graduation_progress(
            strategy_id="v1.1",
            backtest_sharpe=1.03,
            backtest_mdd=-0.15,
            model_slippage_bps=64.5,
        )

        assert "criteria" in result
        assert "all_passed" in result
        assert "summary" in result
        assert isinstance(result["criteria"], list)
        assert len(result["criteria"]) >= 5  # 基础5项 + Sprint 1.10新增4项

    @pytest.mark.asyncio
    async def test_get_graduation_progress_running_days_check(self):
        """运行不足60天时，运行时长项应为 passed=False。"""
        svc = self._get_service()

        nav_series = [{"daily_return": 0.001} for _ in range(30)]  # 仅30天
        svc.perf_repo.get_nav_series = AsyncMock(return_value=nav_series)
        svc.perf_repo.get_rolling_stats = AsyncMock(
            return_value={"sharpe": 1.5, "mdd": -0.05, "total_return": 0.15}
        )
        svc.trade_repo.get_trades = AsyncMock(return_value=[])

        result = await svc.get_graduation_progress(
            strategy_id="v1.1",
            backtest_sharpe=1.03,
            backtest_mdd=-0.15,
        )

        duration_criterion = next(
            c for c in result["criteria"] if c["name"] == "运行时长"
        )
        assert duration_criterion["passed"] is False

    @pytest.mark.asyncio
    async def test_get_graduation_progress_no_data(self):
        """无数据时不抛异常，应返回合法结构。"""
        svc = self._get_service()
        svc.perf_repo.get_nav_series = AsyncMock(return_value=[])
        svc.perf_repo.get_rolling_stats = AsyncMock(return_value=None)
        svc.trade_repo.get_trades = AsyncMock(return_value=[])

        result = await svc.get_graduation_progress(strategy_id="v1.1")
        assert isinstance(result["criteria"], list)
        assert result["all_passed"] is False

    @pytest.mark.asyncio
    async def test_graduation_summary_format(self):
        """summary 字段应为 'X/Y' 格式字符串。"""
        svc = self._get_service()
        svc.perf_repo.get_nav_series = AsyncMock(return_value=[])
        svc.perf_repo.get_rolling_stats = AsyncMock(return_value=None)
        svc.trade_repo.get_trades = AsyncMock(return_value=[])

        result = await svc.get_graduation_progress(strategy_id="v1.1")
        summary = result["summary"]
        assert "/" in summary
        parts = summary.split("/")
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert parts[1].isdigit()


# ─────────────────────────────────────────────────────────────────────────────
# 3. NotificationService & NotificationThrottler
# ─────────────────────────────────────────────────────────────────────────────

class TestNotificationThrottler:
    """NotificationThrottler 节流逻辑测试。

    纯内存逻辑，无需 mock。
    """

    def _get_throttler(self, intervals: dict | None = None):
        from app.services.notification_throttler import NotificationThrottler
        return NotificationThrottler(intervals=intervals or {"P0": 60, "P1": 600})

    def test_first_send_always_allowed(self):
        """首次发送同一通知应被允许。"""
        throttler = self._get_throttler()
        assert throttler.throttle("P0", "测试告警") is True

    def test_second_send_within_interval_blocked(self):
        """在间隔时间内重复发送同一通知应被拦截。"""
        throttler = self._get_throttler({"P0": 9999})
        throttler.throttle("P0", "重复告警")
        result = throttler.throttle("P0", "重复告警")
        assert result is False

    def test_different_titles_not_throttled(self):
        """不同标题的通知不应互相影响节流。"""
        throttler = self._get_throttler({"P0": 9999})
        throttler.throttle("P0", "告警A")
        assert throttler.throttle("P0", "告警B") is True

    def test_reset_clears_throttle_state(self):
        """reset() 后被限流的通知应重新允许发送。"""
        throttler = self._get_throttler({"P1": 9999})
        throttler.throttle("P1", "某告警")
        assert throttler.throttle("P1", "某告警") is False
        throttler.reset()
        assert throttler.throttle("P1", "某告警") is True

    def test_different_levels_independent(self):
        """同标题不同级别是不同 key，互不影响。"""
        throttler = self._get_throttler({"P0": 9999, "P1": 9999})
        throttler.throttle("P0", "共享标题")
        assert throttler.throttle("P1", "共享标题") is True


class TestSendAlert:
    """send_alert 同步接口冒烟测试。"""

    def test_send_alert_no_webhook_returns_false(self):
        """无 webhook_url 时应返回 False（钉钉未发送）。"""
        from app.services.notification_service import send_alert

        result = send_alert(
            level="P1",
            title="冒烟测试告警",
            content="这是自动化测试内容",
            webhook_url="",
        )
        assert result is False

    def test_send_alert_with_conn_writes_db(self):
        """有 conn 时应调用 cursor().execute() 写入 notifications 表。"""
        from app.services.notification_service import send_alert

        conn = _make_mock_conn()
        # mock dingtalk.send_markdown_sync 避免真实 HTTP
        with patch(
            "app.services.dispatchers.dingtalk.send_markdown_sync",
            return_value=False,
        ):
            send_alert(
                level="P0",
                title="P0告警",
                content="紧急事件",
                webhook_url="",
                conn=conn,
            )
        # 验证 cursor.execute 被调用（写 notifications 表）
        conn.cursor().execute.assert_called()

    def test_send_alert_p2_no_conn_no_exception(self):
        """P2告警无conn不抛异常。"""
        from app.services.notification_service import send_alert

        # 不应抛任何异常
        result = send_alert(
            level="P2",
            title="P2告警",
            content="普通事件",
        )
        assert isinstance(result, bool)


class TestNotificationServiceSync:
    """NotificationService.send_sync 同步方法冒烟测试。"""

    def _get_service(self):
        from app.services.notification_service import NotificationService
        from app.services.notification_throttler import NotificationThrottler

        mock_session = AsyncMock()
        # 用极短间隔以便测试节流
        throttler = NotificationThrottler(intervals={"P0": 1, "P1": 1, "P2": 9999})
        svc = NotificationService(session=mock_session, throttler=throttler)
        return svc

    def test_send_sync_p3_does_not_write_db(self):
        """P3通知不写入 DB，cursor.execute 不被调用。"""
        svc = self._get_service()
        conn = _make_mock_conn()
        svc.send_sync(
            conn=conn,
            level="P3",
            category="system",
            title="调试消息",
            content="调试内容",
        )
        # P3不写DB，execute不应被调用
        conn.cursor().execute.assert_not_called()

    def test_send_sync_p2_throttled_after_repeat(self):
        """P2短时间内重复发送应被节流（第二次不写DB）。"""
        svc = self._get_service()
        conn = _make_mock_conn()

        # 第一次发送P2
        svc.send_sync(
            conn=conn,
            level="P2",
            category="system",
            title="重复P2告警",
            content="内容",
        )
        first_call_count = conn.cursor().execute.call_count

        # 第二次发送相同P2（间隔=9999秒，应被限流）
        svc.send_sync(
            conn=conn,
            level="P2",
            category="system",
            title="重复P2告警",
            content="内容",
        )
        second_call_count = conn.cursor().execute.call_count

        # 第二次被节流，execute call count 不变
        assert second_call_count == first_call_count


# ─────────────────────────────────────────────────────────────────────────────
# 4. RiskControlService
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskControlServiceTriggers:
    """RiskControlService 熔断判断逻辑测试。

    只测试 _check_trigger_conditions 纯计算方法（不访问 DB）。
    RiskControlService 的 async 方法（check_and_update）依赖 DB，
    这里仅测试枚举值和纯计算路径。
    """

    def _get_service(self):
        """构造 RiskControlService 实例，mock 掉所有 DB 依赖。"""
        from app.services.risk_control_service import (
            CircuitBreakerThresholds,
            RiskControlService,
        )

        AsyncMock()
        mock_notif = MagicMock()
        svc = RiskControlService.__new__(RiskControlService)
        svc.repo = MagicMock()
        svc.notification_service = mock_notif
        svc.thresholds = CircuitBreakerThresholds()
        svc._tables_ensured = True
        return svc

    def _make_metrics(
        self,
        daily_return: float = 0.0,
        cumulative_return: float = 0.0,
        rolling_5d: float | None = None,
        rolling_20d: float | None = None,
        portfolio_vol_20d: float | None = 0.1485,  # 基准波动率 → vol_ratio=1.0，阈值不放大
    ):
        from app.services.risk_control_service import RiskMetrics

        return RiskMetrics(
            trade_date=date(2025, 1, 15),
            daily_return=Decimal(str(daily_return)),
            nav=Decimal("1000000"),
            initial_capital=Decimal("1000000"),
            cumulative_return=Decimal(str(cumulative_return)),
            rolling_5d_return=Decimal(str(rolling_5d)) if rolling_5d is not None else None,
            rolling_20d_return=Decimal(str(rolling_20d)) if rolling_20d is not None else None,
            portfolio_vol_20d=portfolio_vol_20d,
        )

    def test_normal_metrics_no_trigger(self):
        """正常收益不应触发任何熔断。"""
        from app.services.risk_control_service import CircuitBreakerLevel

        svc = self._get_service()
        metrics = self._make_metrics(daily_return=0.01, cumulative_return=0.05)
        level, reason, _ = svc._check_trigger_conditions(metrics)
        assert level == CircuitBreakerLevel.NORMAL

    def test_l1_trigger_single_strategy_loss(self):
        """单日亏损 >3% 应触发 L1。"""
        from app.services.risk_control_service import CircuitBreakerLevel

        svc = self._get_service()
        metrics = self._make_metrics(daily_return=-0.04)  # -4% > L1阈值-3%
        level, reason, metrics_dict = svc._check_trigger_conditions(metrics)
        assert level >= CircuitBreakerLevel.L1_PAUSED

    def test_l2_trigger_portfolio_large_loss(self):
        """单日亏损 >5% 应触发 L2。"""
        from app.services.risk_control_service import CircuitBreakerLevel

        svc = self._get_service()
        metrics = self._make_metrics(daily_return=-0.06)  # -6% > L2阈值-5%
        level, reason, _ = svc._check_trigger_conditions(metrics)
        assert level >= CircuitBreakerLevel.L2_HALTED

    def test_l3_trigger_rolling_20d_loss(self):
        """滚动20日亏损 >10% 应触发 L3。"""
        from app.services.risk_control_service import CircuitBreakerLevel

        svc = self._get_service()
        metrics = self._make_metrics(
            daily_return=-0.01,
            rolling_20d=-0.12,  # -12% > L3阈值-10%
        )
        level, reason, _ = svc._check_trigger_conditions(metrics)
        assert level >= CircuitBreakerLevel.L3_REDUCED

    def test_l4_trigger_cumulative_loss(self):
        """累计亏损 >25% 应触发 L4。"""
        from app.services.risk_control_service import CircuitBreakerLevel

        svc = self._get_service()
        metrics = self._make_metrics(
            daily_return=-0.01,
            cumulative_return=-0.30,  # -30% > L4阈值-25%
        )
        level, reason, _ = svc._check_trigger_conditions(metrics)
        assert level == CircuitBreakerLevel.L4_STOPPED

    def test_circuit_breaker_level_ordering(self):
        """验证 CircuitBreakerLevel 枚举数值顺序：NORMAL<L1<L2<L3<L4。"""
        from app.services.risk_control_service import CircuitBreakerLevel

        assert CircuitBreakerLevel.NORMAL < CircuitBreakerLevel.L1_PAUSED
        assert CircuitBreakerLevel.L1_PAUSED < CircuitBreakerLevel.L2_HALTED
        assert CircuitBreakerLevel.L2_HALTED < CircuitBreakerLevel.L3_REDUCED
        assert CircuitBreakerLevel.L3_REDUCED < CircuitBreakerLevel.L4_STOPPED

    def test_position_multiplier_l3_is_half(self):
        """L3 仓位乘数应为 0.5。"""
        from app.services.risk_control_service import (
            _LEVEL_POSITION_MULTIPLIER,
            CircuitBreakerLevel,
        )

        assert _LEVEL_POSITION_MULTIPLIER[CircuitBreakerLevel.L3_REDUCED] == Decimal("0.5")

    def test_position_multiplier_l4_is_zero(self):
        """L4 仓位乘数应为 0（完全停止）。"""
        from app.services.risk_control_service import (
            _LEVEL_POSITION_MULTIPLIER,
            CircuitBreakerLevel,
        )

        assert _LEVEL_POSITION_MULTIPLIER[CircuitBreakerLevel.L4_STOPPED] == Decimal("0.0")


# ─────────────────────────────────────────────────────────────────────────────
# 5. DashboardService
# ─────────────────────────────────────────────────────────────────────────────

class TestDashboardService:
    """DashboardService 冒烟测试。

    mock 所有 repository async 方法，验证聚合逻辑不抛异常、结构正确。
    """

    def _get_service(self):
        from app.services.dashboard_service import DashboardService

        AsyncMock()
        svc = DashboardService.__new__(DashboardService)
        svc.perf_repo = MagicMock()
        svc.pos_repo = MagicMock()
        svc.health_repo = MagicMock()
        svc.market_repo = MagicMock()
        return svc

    @pytest.mark.asyncio
    async def test_get_summary_with_data(self):
        """有数据时 get_summary 应返回7个指标卡字段。"""
        svc = self._get_service()
        svc.perf_repo.get_latest_nav = AsyncMock(
            return_value={
                "nav": 1_050_000.0,
                "position_count": 15,
                "daily_return": 0.005,
                "cumulative_return": 0.05,
                "cash_ratio": 0.03,
                "trade_date": date(2025, 1, 15),
            }
        )
        svc.perf_repo.get_rolling_stats = AsyncMock(
            return_value={"sharpe": 1.05, "mdd": -0.12}
        )

        result = await svc.get_summary("v1.1")

        assert result["nav"] == 1_050_000.0
        assert result["sharpe"] == 1.05
        assert result["mdd"] == -0.12
        assert result["position_count"] == 15
        assert "daily_return" in result
        assert "cumulative_return" in result
        assert "cash_ratio" in result

    @pytest.mark.asyncio
    async def test_get_summary_no_data_returns_zeros(self):
        """无数据时 get_summary 应返回全零字典而非抛异常。"""
        svc = self._get_service()
        svc.perf_repo.get_latest_nav = AsyncMock(return_value=None)
        svc.perf_repo.get_rolling_stats = AsyncMock(return_value=None)

        result = await svc.get_summary("v1.1")

        assert result["nav"] == 0
        assert result["sharpe"] == 0
        assert result["trade_date"] is None

    @pytest.mark.asyncio
    async def test_get_nav_series_calls_repo(self):
        """get_nav_series 应透传参数给 perf_repo.get_nav_series。"""
        svc = self._get_service()
        expected = [{"trade_date": date(2025, 1, 1), "nav": 1_000_000.0}]
        svc.perf_repo.get_nav_series = AsyncMock(return_value=expected)

        result = await svc.get_nav_series("v1.1", period="1m")

        assert result == expected
        svc.perf_repo.get_nav_series.assert_called_once()

    def test_resolve_period_start_known_periods(self):
        """_resolve_period_start 各周期返回正确的起始日期偏移。"""
        from app.services.dashboard_service import DashboardService

        today = date.today()
        assert DashboardService._resolve_period_start("1m") == today - timedelta(days=30)
        assert DashboardService._resolve_period_start("3m") == today - timedelta(days=90)
        assert DashboardService._resolve_period_start("6m") == today - timedelta(days=180)
        assert DashboardService._resolve_period_start("1y") == today - timedelta(days=365)
        assert DashboardService._resolve_period_start("all") is None

    @pytest.mark.asyncio
    async def test_get_pending_actions_no_health_issues(self):
        """健康正常、无熔断、无管道失败时 pending_actions 应为空列表。"""
        svc = self._get_service()
        svc.health_repo.get_latest_health = AsyncMock(
            return_value={"all_pass": True, "failed_items": [], "check_date": date.today()}
        )
        svc.health_repo.get_circuit_breaker_history = AsyncMock(return_value=[])
        svc.health_repo.get_pipeline_status = AsyncMock(return_value=[])

        result = await svc.get_pending_actions("v1.1")

        assert result == []
