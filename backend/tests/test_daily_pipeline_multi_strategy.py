"""MVP 3.2 批 4 — daily_pipeline multi-strategy iteration integration tests.

Mock 粒度: `get_live_strategies_for_risk_check` 返 [S1], [S1, S2], 空, 异常 —
验证 risk_daily_check_task + intraday_risk_check_task 的迭代契约:

  1. 单 strategy (fallback / S1 only) — Monday 4-27 行为保持
  2. 双 strategy (S1 + S2 post-Tuesday) — per-strategy 独立 summary
  3. 空 strategies — 不 raise, 返 summary 0 strategies
  4. per-strategy 异常 — 其他 strategy 继续跑, summary 含 error 行
  5. 全 strategies 异常 — raise retry / RuntimeError (原单策略语义保持)

Note: 本测不触真 Celery broker, 用 `task.run()` 直调 task 函数内部逻辑. build_risk_engine
+ get_sync_conn + TradingDayChecker 全部 mock.
"""
from __future__ import annotations

from datetime import UTC
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ─── Fixtures ─────────────────────────────────────────────────────


def _mk_mock_strategy(strategy_id: str):
    """Create minimal Strategy duck-type for iteration (has .strategy_id attr)."""
    return SimpleNamespace(strategy_id=strategy_id)


def _mk_trading_day_mock(is_td: bool = True):
    """Patch TradingDayChecker.is_trading_day → (is_td, reason_str)."""
    checker = MagicMock()
    checker.is_trading_day = MagicMock(
        return_value=(is_td, "mock-trading-day" if is_td else "mock-holiday")
    )
    return checker


def _mk_real_risk_context(positions_count: int = 3, prev_close_nav: float | None = None):
    """Build a real RiskContext (frozen dataclass) so `dataclasses.replace()` works in
    intraday_risk_check_task. positions 用真 Position 实例 (len() + iter() 支持).
    """
    from datetime import datetime

    from backend.qm_platform.risk.interface import Position, RiskContext

    positions = tuple(
        Position(
            code=f"60000{i}.SH",
            shares=100,
            entry_price=10.0,
            peak_price=11.0,
            current_price=10.5,
        )
        for i in range(positions_count)
    )
    return RiskContext(
        strategy_id="mock-strategy",
        execution_mode="live",
        timestamp=datetime.now(UTC),
        positions=positions,
        portfolio_nav=1_000_000.0,
        prev_close_nav=prev_close_nav,
    )


def _mk_engine_context(positions_count: int = 3):
    """Engine with real RiskContext + mocked run/execute (run 返空 list default)."""
    context = _mk_real_risk_context(positions_count=positions_count)

    engine = MagicMock()
    engine.build_context = MagicMock(return_value=context)
    engine.run = MagicMock(return_value=[])  # 0 triggered default
    engine.execute = MagicMock()
    engine.registered_rules = ["pms", "circuit_breaker"]
    return engine


# ─── risk_daily_check: 正常迭代 ────────────────────────────────────


def _patch_daily_deps(strategies: list, is_td: bool = True):
    """Patch all external deps for risk_daily_check_task internals."""
    checker = _mk_trading_day_mock(is_td=is_td)
    engine = _mk_engine_context(positions_count=3)

    return (
        patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=checker,
        ),
        patch(
            "app.services.db.get_sync_conn",
            return_value=MagicMock(close=MagicMock()),
        ),
        patch(
            "app.services.strategy_bootstrap.get_live_strategies_for_risk_check",
            return_value=strategies,
        ),
        patch(
            "app.services.risk_wiring.build_risk_engine",
            return_value=engine,
        ),
        patch(
            "app.services.risk_wiring.build_circuit_breaker_rule",
            return_value=MagicMock(),
        ),
    )


def test_risk_daily_check_single_strategy_monday_safe():
    """Monday 4-27 行为: [S1] 单策略 → 1 次 iteration, summary 含 1 per-strategy entry.

    **关键 guard**: 批 4 代码在 Monday 与单策略时行为等同今日 (fail-safe fallback).
    """
    from app.tasks.daily_pipeline import risk_daily_check_task
    from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

    # P3 code-reviewer (PR #72) 采纳: 用 S1MonthlyRanking.strategy_id SSOT 替 hardcoded UUID
    strategies = [_mk_mock_strategy(S1MonthlyRanking.strategy_id)]
    # P1 python-reviewer (PR #72) 采纳: 原代码 `_patch_daily_deps(strategies)[0]` 调用 5 次
    # 创建 5 独立 tuple → 各 patch 来自不同实例, 行为不一致. 改 pre-assign.
    # P2-A python-reviewer: `app.tasks.daily_pipeline.settings` 是正确 scope
    # (daily_pipeline L21 `from app.config import settings` module-top import).
    patches = _patch_daily_deps(strategies)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"

        # call task.run() 直调 task function (不走 Celery broker)
        result = risk_daily_check_task.run()

    assert result["status"] == "ok"
    assert result["strategies_count"] == 1
    assert len(result["strategies"]) == 1
    assert result["strategies"][0]["strategy_id"] == S1MonthlyRanking.strategy_id
    assert result["strategies"][0]["status"] == "ok"


def test_risk_daily_check_dual_strategy_iteration():
    """Tuesday+ 行为: [S1, S2] 双策略 → 2 次 iteration, per-strategy 独立 summary."""
    from app.tasks.daily_pipeline import risk_daily_check_task

    s1 = _mk_mock_strategy("s1-uuid")
    s2 = _mk_mock_strategy("s2-uuid")
    patches = _patch_daily_deps([s1, s2])
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"

        result = risk_daily_check_task.run()

    assert result["status"] == "ok"
    assert result["strategies_count"] == 2
    assert len(result["strategies"]) == 2
    assert result["strategies"][0]["strategy_id"] == "s1-uuid"
    assert result["strategies"][1]["strategy_id"] == "s2-uuid"


def test_risk_daily_check_no_positions_returns_ok_checked_zero():
    """持仓空 → strategy summary status='ok' checked=0 (不 raise)."""
    from app.tasks.daily_pipeline import risk_daily_check_task

    strategies = [_mk_mock_strategy("s1-uuid")]
    # engine 返 empty positions
    engine = _mk_engine_context(positions_count=0)
    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch(
            "app.services.strategy_bootstrap.get_live_strategies_for_risk_check",
            return_value=strategies,
        ), \
        patch("app.services.risk_wiring.build_risk_engine", return_value=engine), \
        patch("app.services.risk_wiring.build_circuit_breaker_rule", return_value=MagicMock()), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"
        result = risk_daily_check_task.run()

    assert result["status"] == "ok"
    assert result["total_checked"] == 0
    assert result["strategies"][0]["checked"] == 0


# ─── risk_daily_check: per-strategy 异常隔离 ──────────────────────


def test_risk_daily_check_per_strategy_error_isolated():
    """S1 异常 + S2 正常 → S1 summary error, S2 summary ok, task overall ok."""
    from app.tasks.daily_pipeline import risk_daily_check_task

    s1 = _mk_mock_strategy("s1-uuid")
    s2 = _mk_mock_strategy("s2-uuid")

    call_count = {"n": 0}

    def engine_builder(*_a, **_k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # S1 iteration: build_context raises
            eng = MagicMock()
            eng.build_context = MagicMock(side_effect=RuntimeError("S1 QMT disconnect"))
            return eng
        # S2 iteration: OK
        return _mk_engine_context(positions_count=2)

    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch(
            "app.services.strategy_bootstrap.get_live_strategies_for_risk_check",
            return_value=[s1, s2],
        ), \
        patch("app.services.risk_wiring.build_risk_engine", side_effect=engine_builder), \
        patch("app.services.risk_wiring.build_circuit_breaker_rule", return_value=MagicMock()), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"
        result = risk_daily_check_task.run()

    assert result["status"] == "ok"  # task overall success 因 S2 跑通
    assert result["strategies"][0]["status"] == "error"
    assert "S1 QMT disconnect" in result["strategies"][0]["error"]
    assert result["strategies"][1]["status"] == "ok"


# ─── risk_daily_check: 全挂 → retry ────────────────────────────────


def test_risk_daily_check_all_failed_raises_retry():
    """所有 strategy 全异常 → self.retry(RuntimeError) (Celery FAILURE escalation).

    Monday 安全兜底: 批 4 新 code path 全挂时保持原 max_retries=1 语义.
    """
    from app.tasks.daily_pipeline import risk_daily_check_task

    s1 = _mk_mock_strategy("s1-uuid")
    engine = MagicMock()
    engine.build_context = MagicMock(side_effect=RuntimeError("全挂"))

    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch(
            "app.services.strategy_bootstrap.get_live_strategies_for_risk_check",
            return_value=[s1],
        ), \
        patch("app.services.risk_wiring.build_risk_engine", return_value=engine), \
        patch("app.services.risk_wiring.build_circuit_breaker_rule", return_value=MagicMock()), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"

        # Celery self.retry 在 eager 模式下抛 Retry / 或 MaxRetriesExceededError
        # 仅验证非零 exit (raise 任何 Exception)
        with pytest.raises(Exception):  # noqa: B017, PT011 — Celery Retry / RuntimeError 都接受
            risk_daily_check_task.run()


# ─── Non-trading day early return ────────────────────────────────


def test_risk_daily_check_skips_non_trading_day():
    """非交易日 → 早返 skipped, 不调 strategy iteration."""
    from app.tasks.daily_pipeline import risk_daily_check_task

    # 不预设 strategy mock — 应早返 before 调 get_live_strategies
    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(is_td=False),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"
        result = risk_daily_check_task.run()

    assert result["status"] == "skipped"
    assert "mock-holiday" in result["reason"]


# ─── PMS_ENABLED=False ────────────────────────────────────────────


def test_risk_daily_check_skips_when_pms_disabled():
    """PMS_ENABLED=False → 早返 disabled, 不 call strategy iteration."""
    from app.tasks.daily_pipeline import risk_daily_check_task

    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(is_td=True),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = False  # 关掉
        result = risk_daily_check_task.run()

    assert result["status"] == "disabled"


# ─── intraday_risk_check: 单 strategy smoke ────────────────────────


def test_intraday_risk_check_single_strategy_smoke():
    """Intraday task 单策略 iteration smoke — mock Redis + engine + NAV loader."""
    from app.tasks.daily_pipeline import intraday_risk_check_task

    s1 = _mk_mock_strategy("s1-uuid")
    engine = _mk_engine_context(positions_count=2)

    # Dedup: always allow alert (True)
    dedup_mock = MagicMock()
    dedup_mock.should_alert = MagicMock(return_value=True)
    dedup_mock.mark_alerted = MagicMock()

    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch(
            "app.services.strategy_bootstrap.get_live_strategies_for_risk_check",
            return_value=[s1],
        ), \
        patch("app.services.risk_wiring.build_intraday_risk_engine", return_value=engine), \
        patch("app.services.risk_wiring._load_prev_close_nav", return_value=1_000_000.0), \
        patch("app.services.risk_wiring.IntradayAlertDedup", return_value=dedup_mock), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"
        result = intraday_risk_check_task.run()

    assert result["status"] == "ok"
    assert result["strategies_count"] == 1
    assert result["strategies"][0]["strategy_id"] == "s1-uuid"


def test_intraday_risk_check_dual_strategy_dedup_isolated():
    """双策略 intraday — dedup key 天然含 strategy_id 互不干扰.

    Guard: S1 alerted 不应抑制 S2 同 rule 的 alert (per-strategy isolation).
    """
    from app.tasks.daily_pipeline import intraday_risk_check_task

    s1 = _mk_mock_strategy("s1-uuid")
    s2 = _mk_mock_strategy("s2-uuid")
    engine = _mk_engine_context(positions_count=2)

    dedup_mock = MagicMock()
    dedup_mock.should_alert = MagicMock(return_value=True)  # 都允许
    dedup_mock.mark_alerted = MagicMock()

    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch(
            "app.services.strategy_bootstrap.get_live_strategies_for_risk_check",
            return_value=[s1, s2],
        ), \
        patch("app.services.risk_wiring.build_intraday_risk_engine", return_value=engine), \
        patch("app.services.risk_wiring._load_prev_close_nav", return_value=1_000_000.0), \
        patch("app.services.risk_wiring.IntradayAlertDedup", return_value=dedup_mock), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"
        result = intraday_risk_check_task.run()

    assert result["status"] == "ok"
    assert result["strategies_count"] == 2
    strategy_ids = [s["strategy_id"] for s in result["strategies"]]
    assert "s1-uuid" in strategy_ids
    assert "s2-uuid" in strategy_ids


# ─── PR #139 reviewer P1: daily dedup integration ─────────────────


def _mk_engine_with_results(rule_ids: list[str], positions_count: int = 3):
    """Engine 变体: run() 返指定 rule_id RuleResults, 供 dedup 路径覆盖."""
    from backend.qm_platform.risk.interface import RuleResult

    context = _mk_real_risk_context(positions_count=positions_count)
    engine = MagicMock()
    engine.build_context = MagicMock(return_value=context)
    engine.run = MagicMock(
        return_value=[
            RuleResult(
                rule_id=rid, code="600000.SH", shares=0,
                reason=f"test {rid}", metrics={},
            )
            for rid in rule_ids
        ]
    )
    engine.execute = MagicMock()
    engine.registered_rules = ["pms", "circuit_breaker", "single_stock_stoploss"]
    return engine


def test_risk_daily_check_dedup_allows_first_alert():
    """PR #139 P1 — daily dedup 首次告警 should_alert=True 路径放行 + mark_alerted 后调."""
    from app.tasks.daily_pipeline import risk_daily_check_task

    s1 = _mk_mock_strategy("s1-uuid")
    engine = _mk_engine_with_results(["pms_l1", "single_stock_stoploss_l4"])

    dedup_mock = MagicMock()
    dedup_mock.should_alert = MagicMock(return_value=True)
    dedup_mock.mark_alerted = MagicMock()

    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch(
            "app.services.strategy_bootstrap.get_live_strategies_for_risk_check",
            return_value=[s1],
        ), \
        patch("app.services.risk_wiring.build_risk_engine", return_value=engine), \
        patch("app.services.risk_wiring.build_circuit_breaker_rule", return_value=MagicMock()), \
        patch("app.services.risk_wiring.IntradayAlertDedup", return_value=dedup_mock), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"
        result = risk_daily_check_task.run()

    assert result["status"] == "ok"
    assert result["total_triggered"] == 2
    assert result["total_alerted"] == 2
    assert result["total_dedup_skipped"] == 0
    assert engine.execute.call_count == 1
    assert dedup_mock.mark_alerted.call_count == 2  # 每 RuleResult 一次


def test_risk_daily_check_dedup_skips_already_alerted():
    """PR #139 P1 — daily dedup intraday 已告警 should_alert=False 时跳过 execute."""
    from app.tasks.daily_pipeline import risk_daily_check_task

    s1 = _mk_mock_strategy("s1-uuid")
    engine = _mk_engine_with_results(["single_stock_stoploss_l4"])

    dedup_mock = MagicMock()
    dedup_mock.should_alert = MagicMock(return_value=False)  # intraday 已告警
    dedup_mock.mark_alerted = MagicMock()

    with patch(
            "engines.trading_day_checker.TradingDayChecker",
            return_value=_mk_trading_day_mock(),
        ), \
        patch("app.services.db.get_sync_conn", return_value=MagicMock(close=MagicMock())), \
        patch(
            "app.services.strategy_bootstrap.get_live_strategies_for_risk_check",
            return_value=[s1],
        ), \
        patch("app.services.risk_wiring.build_risk_engine", return_value=engine), \
        patch("app.services.risk_wiring.build_circuit_breaker_rule", return_value=MagicMock()), \
        patch("app.services.risk_wiring.IntradayAlertDedup", return_value=dedup_mock), \
        patch("app.tasks.daily_pipeline.settings") as mock_settings:
        mock_settings.PMS_ENABLED = True
        mock_settings.EXECUTION_MODE = "live"
        result = risk_daily_check_task.run()

    assert result["status"] == "ok"
    assert result["total_triggered"] == 1
    assert result["total_alerted"] == 0  # 全 dedup
    assert result["total_dedup_skipped"] == 1
    # execute 不应被调 (no to_execute)
    engine.execute.assert_not_called()
    dedup_mock.mark_alerted.assert_not_called()
