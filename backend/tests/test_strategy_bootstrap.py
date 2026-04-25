"""MVP 3.2 批 4 — strategy_bootstrap.py unit tests.

覆盖 get_live_strategies_for_risk_check 的 5 场景:
  1. Happy path: DB 返 [S1] live row → 返 [S1 instance]
  2. Fallback: registry.register 抛异常 → 返 [S1MonthlyRanking()] + rollback
  3. Fallback: DB conn 挂 → 返 [S1MonthlyRanking()]
  4. Fallback: get_live() empty → 返 [S1MonthlyRanking()] (S1 status 非 'live')
  5. Fallback: DB 返 live UUID 但 cache 未 register → IntegrityError → 返 [S1]

纯 mock 测试, 不触真 DB. 对齐 test_s2_pead_event.py / test_strategy_registry.py 模式.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

# ─── Happy path ────────────────────────────────────────────────────


def test_happy_path_returns_db_live_strategies():
    """DB 有 S1 status='live' → register + get_live 返 [S1 instance]."""
    from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

    # P2-B python-reviewer (PR #72) 采纳: 用文档化 CM pattern (documented in unittest.mock
    # docs) 替原 manual `cursor.__enter__ = MagicMock(...)`. 原 pattern 依赖 MagicMock
    # __getattr__ 拦截 dunder, 非文档行为.
    # `conn.cursor.return_value.__enter__.return_value = cursor` 是官方 CM 模式.
    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=None)  # register() existing_status lookup
    cursor.fetchall = MagicMock(
        return_value=[(S1MonthlyRanking.strategy_id, "s1_monthly_ranking")]
    )

    conn = MagicMock()
    # `with conn.cursor() as cur:` → __enter__ 返 cursor. conn.cursor() 返 MagicMock
    # instance, 其 __enter__ 默认 MagicMock (auto-spec), .return_value = cursor 设置
    # context manager enter value.
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    with patch("app.services.strategy_bootstrap.get_sync_conn", return_value=conn):
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        result = get_live_strategies_for_risk_check()

    assert len(result) == 1
    assert isinstance(result[0], S1MonthlyRanking)
    assert result[0].strategy_id == S1MonthlyRanking.strategy_id
    # commit 调用了 (铁律 32 wiring 层管事务)
    assert conn.commit.called
    assert conn.close.called


# ─── Fallback: register 异常 ───────────────────────────────────────


def test_fallback_on_register_exception(caplog):
    """register() 抛 psycopg2 异常 → rollback + fallback [S1MonthlyRanking()] + log."""
    from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

    conn = MagicMock()
    conn.cursor = MagicMock(side_effect=RuntimeError("simulated DB write fail"))
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    with patch("app.services.strategy_bootstrap.get_sync_conn", return_value=conn), \
        caplog.at_level(logging.ERROR, logger="app.services.strategy_bootstrap"):
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        result = get_live_strategies_for_risk_check()

    assert len(result) == 1
    assert isinstance(result[0], S1MonthlyRanking)
    # Fallback 语义: logger.error 暴露 root cause (铁律 33)
    assert any("FALLBACK to [S1]" in r.message for r in caplog.records)
    # rollback 调用 (铁律 32 异常事务清理)
    assert conn.rollback.called
    assert conn.close.called


# ─── Fallback: conn 挂 ────────────────────────────────────────────


def test_fallback_on_conn_failure(caplog):
    """get_sync_conn() 抛 connection error → fallback [S1MonthlyRanking()]."""
    from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

    with patch(
        "app.services.strategy_bootstrap.get_sync_conn",
        side_effect=ConnectionError("simulated PG unreachable"),
    ), caplog.at_level(logging.ERROR, logger="app.services.strategy_bootstrap"):
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        result = get_live_strategies_for_risk_check()

    assert len(result) == 1
    assert isinstance(result[0], S1MonthlyRanking)
    assert any("FALLBACK" in r.message for r in caplog.records)


# ─── Fallback: get_live() empty ────────────────────────────────────


def test_fallback_on_empty_live(caplog):
    """DB 返 0 live strategies (S1 status != 'live') → fallback + warning."""
    from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

    # P2-B python-reviewer 文档化 CM pattern
    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=None)  # register existing_status None
    cursor.fetchall = MagicMock(return_value=[])  # get_live empty

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    with patch("app.services.strategy_bootstrap.get_sync_conn", return_value=conn), \
        caplog.at_level(logging.WARNING, logger="app.services.strategy_bootstrap"):
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        result = get_live_strategies_for_risk_check()

    assert len(result) == 1
    assert isinstance(result[0], S1MonthlyRanking)
    # Warning 明确 "empty after register" 说明 S1 status 非 live
    assert any(
        "get_live() empty" in r.message or "fallback" in r.message.lower()
        for r in caplog.records
    )


# ─── Fallback: IntegrityError (DB live UUID 但 cache 未 register) ──


def test_fallback_on_integrity_error(caplog):
    """DB 有 live UUID 但 cache 未 register → IntegrityError → fallback.

    这理论上不会发生 (register 走在 get_live 前), 但 guard 必须覆盖以防 registry
    被绕过. 铁律 33 fail-loud 不 silent.
    """
    from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

    # P2-B python-reviewer 文档化 CM pattern
    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=None)
    # get_live 返 UUID 但 cache 未 register (模拟 register 绕过)
    # 本 test 通过 patch DBStrategyRegistry.get_live 直接抛 IntegrityError
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    from backend.qm_platform.strategy.registry import StrategyRegistryIntegrityError

    with patch("app.services.strategy_bootstrap.get_sync_conn", return_value=conn), \
        patch(
            "backend.qm_platform.strategy.registry.DBStrategyRegistry.get_live",
            side_effect=StrategyRegistryIntegrityError("cache miss"),
        ), \
        caplog.at_level(logging.ERROR, logger="app.services.strategy_bootstrap"):
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        result = get_live_strategies_for_risk_check()

    assert len(result) == 1
    assert isinstance(result[0], S1MonthlyRanking)
    assert any("FALLBACK" in r.message for r in caplog.records)


# ─── S1 strategy_id 稳定性 (Monday 4-27 安全守门) ─────────────────


def test_fallback_s1_strategy_id_matches_live_pt():
    """Fallback S1 instance 的 strategy_id 必须 = 当前 PT live UUID.

    铁律 34 SSOT: S1.strategy_id 与 settings.PAPER_STRATEGY_ID 必须一致 (Monday
    4-27 首次触发 zero 干扰).

    P3 code-reviewer (PR #72) 采纳: 用 S1MonthlyRanking.strategy_id SSOT 替 hardcoded
    UUID — 若 UUID 迁移此 test fail message 清晰, 非 `"28fc37e5..." != "..."` 含混.
    """
    from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

    with patch(
        "app.services.strategy_bootstrap.get_sync_conn",
        side_effect=ConnectionError("force fallback"),
    ):
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        result = get_live_strategies_for_risk_check()

    assert result[0].strategy_id == S1MonthlyRanking.strategy_id


# ─── Return type contract ───────────────────────────────────────


def test_always_returns_nonempty_list():
    """不管发生什么, 永远返非空 list (下游 loop 保证至少迭代 1 次)."""
    with patch(
        "app.services.strategy_bootstrap.get_sync_conn",
        side_effect=Exception("catastrophic failure"),
    ):
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        result = get_live_strategies_for_risk_check()

    assert isinstance(result, list)
    assert len(result) >= 1, "fail-safe 保底 [S1MonthlyRanking()] 不得为空"


@pytest.mark.parametrize(
    "exception_class",
    [
        RuntimeError,
        ConnectionError,
        ValueError,
        KeyError,
    ],
)
def test_fallback_catches_any_exception(exception_class):
    """参数化: 任意 Exception 子类都触发 fallback, 不 propagate."""
    from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

    with patch(
        "app.services.strategy_bootstrap.get_sync_conn",
        side_effect=exception_class("simulated"),
    ):
        from app.services.strategy_bootstrap import get_live_strategies_for_risk_check

        # 必不 raise
        result = get_live_strategies_for_risk_check()
        assert isinstance(result[0], S1MonthlyRanking)
