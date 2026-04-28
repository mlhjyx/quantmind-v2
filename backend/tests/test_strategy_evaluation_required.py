"""MVP 3.5.1 — DBStrategyRegistry record_evaluation + update_status(LIVE) 守门 tests.

跨 PR follow-up from MVP 3.5 batch 3 (Session 42, 2026-04-28).
设计意图: 防止策略未经 PlatformStrategyEvaluator 评估直接升 LIVE 真金事故.

覆盖 (~13 tests):
  - record_evaluation (4): inserts row / serializes / invalid subject / empty evaluator_class
  - update_status(LIVE) 守门 (6): no eval / failed / stale / fresh passed / LIVE→non-LIVE skip
    / non-LIVE target skip
  - 配置 (2): freshness_days 必 > 0 / EvaluationRequired 消息含 blockers
  - Edge (1): naive datetime defensive
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from backend.qm_platform._types import Verdict
from backend.qm_platform.strategy import (
    DEFAULT_LIVE_EVAL_FRESHNESS_DAYS,
    DBStrategyRegistry,
    EvaluationRequired,
    StrategyStatus,
)

# ─── helpers (镜像 test_strategy_registry.py 模式) ─────────────────────


def _make_mock_conn_factory(fetchone_queue: list | None = None):
    """Build a mock conn_factory returning a MagicMock with cursor context manager.

    fetchone_queue: sequentially returned from cursor.fetchone() each call.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.closed = 0

    _it = iter(fetchone_queue or [])

    def _fetchone():
        try:
            return next(_it)
        except StopIteration:
            return None

    cursor.fetchone.side_effect = _fetchone
    cursor.fetchall.return_value = []

    def factory():
        return conn

    factory._conn = conn  # type: ignore[attr-defined]
    factory._cursor = cursor  # type: ignore[attr-defined]
    return factory


def _make_verdict(
    sid: str,
    *,
    passed: bool = True,
    blockers: list[str] | None = None,
    p_value: float | None = None,
    details: dict | None = None,
) -> Verdict:
    return Verdict(
        subject=sid,
        passed=passed,
        p_value=p_value,
        blockers=blockers or [],
        details=details or {"evaluation_years": 5, "decision": "accept"},
    )


# ─── record_evaluation tests ──────────────────────────────────────────


def test_record_evaluation_inserts_row_with_passed_true():
    sid = uuid4()
    factory = _make_mock_conn_factory()
    reg = DBStrategyRegistry(conn_factory=factory)
    verdict = _make_verdict(str(sid), passed=True, p_value=0.001)

    reg.record_evaluation(verdict)

    cur = factory._cursor
    assert cur.execute.call_count == 1
    sql = str(cur.execute.call_args_list[0].args[0])
    assert "INSERT INTO strategy_evaluations" in sql
    args = cur.execute.call_args_list[0].args[1]
    assert args[0] == str(sid)
    assert args[1] is True  # passed
    assert args[2] == "[]"  # blockers JSON
    assert args[3] == 0.001  # p_value
    assert "evaluation_years" in args[4]  # details JSON
    assert args[5] == "PlatformStrategyEvaluator"  # evaluator_class default


def test_record_evaluation_serializes_blockers_and_details_to_json():
    sid = uuid4()
    factory = _make_mock_conn_factory()
    reg = DBStrategyRegistry(conn_factory=factory)
    verdict = _make_verdict(
        str(sid),
        passed=False,
        blockers=["G1prime_sharpe_bootstrap", "G3prime_regression_max_diff"],
        details={"max_diff": 0.001, "sharpe_observed": 0.42},
    )

    reg.record_evaluation(verdict, evaluator_class="CustomEvaluator")

    args = factory._cursor.execute.call_args_list[0].args[1]
    blockers_json = args[2]
    details_json = args[4]
    # JSON 反序列化校验 — 不依赖具体 key 顺序
    import json as _json
    assert _json.loads(blockers_json) == [
        "G1prime_sharpe_bootstrap",
        "G3prime_regression_max_diff",
    ]
    parsed_details = _json.loads(details_json)
    assert parsed_details["max_diff"] == 0.001
    assert parsed_details["sharpe_observed"] == 0.42
    assert args[5] == "CustomEvaluator"


def test_record_evaluation_invalid_subject_uuid_raises():
    factory = _make_mock_conn_factory()
    reg = DBStrategyRegistry(conn_factory=factory)
    verdict = _make_verdict("not-a-uuid", passed=True)

    with pytest.raises(ValueError, match="必须是 UUID"):
        reg.record_evaluation(verdict)
    # 不应触发 INSERT
    assert factory._cursor.execute.call_count == 0


def test_record_evaluation_empty_evaluator_class_raises():
    sid = uuid4()
    factory = _make_mock_conn_factory()
    reg = DBStrategyRegistry(conn_factory=factory)
    verdict = _make_verdict(str(sid), passed=True)

    with pytest.raises(ValueError, match="evaluator_class"):
        reg.record_evaluation(verdict, evaluator_class="   ")
    assert factory._cursor.execute.call_count == 0


# ─── update_status(LIVE) 守门 tests ───────────────────────────────────


def test_update_status_to_live_without_any_evaluation_raises():
    """无 strategy_evaluations 行 → EvaluationRequired."""
    sid = uuid4()
    # Sequence:
    #   1) SELECT status FROM strategy_registry → ('draft',)
    #   2) SELECT ... FROM strategy_evaluations → None
    factory = _make_mock_conn_factory(fetchone_queue=[("draft",), None])
    reg = DBStrategyRegistry(conn_factory=factory)

    with pytest.raises(EvaluationRequired, match="无 strategy_evaluations 记录"):
        reg.update_status(str(sid), StrategyStatus.LIVE, reason="promote to live")

    cur = factory._cursor
    # SELECT status + SELECT eval, NO UPDATE / INSERT log
    assert cur.execute.call_count == 2
    calls = [str(c.args[0]) for c in cur.execute.call_args_list]
    assert "SELECT status FROM strategy_registry" in calls[0]
    assert "FROM strategy_evaluations" in calls[1]


def test_update_status_to_live_with_failed_verdict_raises():
    """最新 evaluation passed=False → EvaluationRequired with blockers in message."""
    sid = uuid4()
    fresh_ts = datetime.now(UTC) - timedelta(hours=1)
    factory = _make_mock_conn_factory(
        fetchone_queue=[
            ("draft",),
            (False, ["G1prime_sharpe_bootstrap"], fresh_ts),
        ]
    )
    reg = DBStrategyRegistry(conn_factory=factory)

    with pytest.raises(EvaluationRequired) as excinfo:
        reg.update_status(str(sid), StrategyStatus.LIVE, reason="promote")
    msg = str(excinfo.value)
    assert "未通过" in msg
    assert "G1prime_sharpe_bootstrap" in msg


def test_update_status_to_live_with_stale_evaluation_raises():
    """最新 evaluation evaluated_at 过期 → EvaluationRequired."""
    sid = uuid4()
    stale_ts = datetime.now(UTC) - timedelta(days=60)  # > 30 day default
    factory = _make_mock_conn_factory(
        fetchone_queue=[
            ("draft",),
            (True, [], stale_ts),
        ]
    )
    reg = DBStrategyRegistry(conn_factory=factory)

    with pytest.raises(EvaluationRequired, match="已过期"):
        reg.update_status(str(sid), StrategyStatus.LIVE, reason="promote")


def test_update_status_to_live_with_fresh_passed_evaluation_succeeds():
    """最新 evaluation passed=True 且 fresh → UPDATE + INSERT log 正常执行."""
    sid = uuid4()
    fresh_ts = datetime.now(UTC) - timedelta(days=1)
    factory = _make_mock_conn_factory(
        fetchone_queue=[
            ("draft",),
            (True, [], fresh_ts),
        ]
    )
    reg = DBStrategyRegistry(conn_factory=factory)

    reg.update_status(str(sid), StrategyStatus.LIVE, reason="MVP 3.5.1 promote test")

    cur = factory._cursor
    # 4 calls: SELECT status + SELECT eval + UPDATE registry + INSERT log
    assert cur.execute.call_count == 4
    calls = [str(c.args[0]) for c in cur.execute.call_args_list]
    assert "SELECT status FROM strategy_registry" in calls[0]
    assert "FROM strategy_evaluations" in calls[1]
    assert "UPDATE strategy_registry" in calls[2]
    assert "INSERT INTO strategy_status_log" in calls[3]


def test_update_status_live_to_paused_skips_eval_check():
    """LIVE→PAUSED 是降级路径, 不查 strategy_evaluations 表."""
    sid = uuid4()
    factory = _make_mock_conn_factory(fetchone_queue=[("live",)])
    reg = DBStrategyRegistry(conn_factory=factory)

    reg.update_status(str(sid), StrategyStatus.PAUSED, reason="降级 PAUSE")

    cur = factory._cursor
    # SELECT status + UPDATE + INSERT log = 3, 不查 evaluations
    assert cur.execute.call_count == 3
    calls = [str(c.args[0]) for c in cur.execute.call_args_list]
    assert all("FROM strategy_evaluations" not in q for q in calls)


def test_update_status_to_draft_skips_eval_check():
    """target != LIVE 时不查 strategy_evaluations 表."""
    sid = uuid4()
    factory = _make_mock_conn_factory(fetchone_queue=[("backtest",)])
    reg = DBStrategyRegistry(conn_factory=factory)

    reg.update_status(str(sid), StrategyStatus.DRY_RUN, reason="进入 dry_run")

    cur = factory._cursor
    assert cur.execute.call_count == 3
    calls = [str(c.args[0]) for c in cur.execute.call_args_list]
    assert all("FROM strategy_evaluations" not in q for q in calls)


# ─── 配置 + edge cases ─────────────────────────────────────────────────


def test_freshness_days_must_be_positive():
    factory = _make_mock_conn_factory()
    with pytest.raises(ValueError, match="必须 > 0"):
        DBStrategyRegistry(conn_factory=factory, live_eval_freshness_days=0)
    with pytest.raises(ValueError, match="必须 > 0"):
        DBStrategyRegistry(conn_factory=factory, live_eval_freshness_days=-5)


def test_freshness_days_configurable_short_window():
    """live_eval_freshness_days=1: 2 天前的 eval 算 stale."""
    sid = uuid4()
    ts = datetime.now(UTC) - timedelta(days=2)
    factory = _make_mock_conn_factory(
        fetchone_queue=[("draft",), (True, [], ts)]
    )
    reg = DBStrategyRegistry(conn_factory=factory, live_eval_freshness_days=1)

    with pytest.raises(EvaluationRequired, match="已过期"):
        reg.update_status(str(sid), StrategyStatus.LIVE, reason="short window test")


def test_default_freshness_days_constant_is_30():
    """API contract: 默认 30 天 (锁防意外漂移)."""
    assert DEFAULT_LIVE_EVAL_FRESHNESS_DAYS == 30


def test_evaluation_required_message_contains_remediation_path():
    """EvaluationRequired 错误消息必须告知调用方修复路径 (operator-friendly)."""
    sid = uuid4()
    factory = _make_mock_conn_factory(fetchone_queue=[("draft",), None])
    reg = DBStrategyRegistry(conn_factory=factory)

    with pytest.raises(EvaluationRequired) as excinfo:
        reg.update_status(str(sid), StrategyStatus.LIVE, reason="promote")
    msg = str(excinfo.value)
    # 必含调用顺序
    assert "evaluate_strategy" in msg
    assert "record_evaluation" in msg


def test_naive_datetime_treated_as_utc_defensive():
    """defensive: psycopg2 应永远返 tz-aware, 但 mock / 老 driver 若 naive 当 UTC.

    fresh naive ts (now - 1 day, naive) 应正常通过 freshness check.
    """
    sid = uuid4()
    naive_fresh = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    factory = _make_mock_conn_factory(
        fetchone_queue=[("draft",), (True, [], naive_fresh)]
    )
    reg = DBStrategyRegistry(conn_factory=factory)

    # 应不抛 (naive 当 UTC, 1 天前在 30 天窗口内)
    reg.update_status(str(sid), StrategyStatus.LIVE, reason="naive ts test")
    assert factory._cursor.execute.call_count == 4  # full path


def test_non_datetime_evaluated_at_raises_evaluation_required():
    """defensive: evaluated_at 非 datetime (e.g. None / str) → fail-loud."""
    sid = uuid4()
    factory = _make_mock_conn_factory(
        fetchone_queue=[("draft",), (True, [], "not-a-datetime")]
    )
    reg = DBStrategyRegistry(conn_factory=factory)

    with pytest.raises(EvaluationRequired, match="非 datetime"):
        reg.update_status(str(sid), StrategyStatus.LIVE, reason="bad ts test")
