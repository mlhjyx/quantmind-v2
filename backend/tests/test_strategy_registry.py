"""MVP 3.2 Strategy Framework 批 1 — DBStrategyRegistry unit tests.

覆盖: register / get_live / get_by_id / update_status + StrategyNotFound +
StrategyRegistryIntegrityError. 用 in-memory mock conn (psycopg2 不启真 DB, 测试纯逻辑).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from backend.platform.strategy import (
    DBStrategyRegistry,
    EqualWeightAllocator,
    RebalanceFreq,
    Strategy,
    StrategyContext,
    StrategyNotFound,
    StrategyRegistryIntegrityError,
    StrategyStatus,
)

# ─── Test helpers ─────────────────────────────────────────────────────

class _FakeStrategy(Strategy):
    """Minimal Strategy for testing — satisfies ABC requirements."""

    def __init__(
        self,
        strategy_id: str,
        name: str = "fake",
        factor_pool: list[str] | None = None,
        rebalance_freq: RebalanceFreq = RebalanceFreq.MONTHLY,
        status: StrategyStatus = StrategyStatus.DRAFT,
        config: dict | None = None,
    ) -> None:
        self.strategy_id = strategy_id
        self.name = name
        # distinguish None (default → sentinel) vs [] (explicit empty for test)
        self.factor_pool = (
            ["turnover_mean_20"] if factor_pool is None else factor_pool
        )
        self.rebalance_freq = rebalance_freq
        self.status = status
        self.config = config or {}

    def generate_signals(self, ctx: StrategyContext):
        return []

    def validate_signals(self, signals, ctx):
        return signals


def _make_mock_conn_factory(
    fetchone_queue: list | None = None, rowcounts: list | None = None
):
    """Build a mock conn_factory that returns queued SELECT results.

    fetchone_queue: sequentially returned from cursor.fetchone()
    rowcounts: ignored for now (UPDATE rowcount), reserved for future.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    # Support `with conn.cursor() as cur:` context manager (reviewer P1 fix)
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.closed = 0

    _fetchone_iter = iter(fetchone_queue or [])

    def _fetchone():
        try:
            return next(_fetchone_iter)
        except StopIteration:
            return None

    cursor.fetchone.side_effect = _fetchone
    cursor.fetchall.return_value = []

    def factory():
        return conn

    factory._conn = conn  # type: ignore[attr-defined]
    factory._cursor = cursor  # type: ignore[attr-defined]
    return factory


# ─── register() tests ────────────────────────────────────────────────

def test_register_first_time_inserts_row_and_audit_log():
    sid = uuid4()
    s = _FakeStrategy(strategy_id=str(sid), name="s1")
    # fetchone returns None (first register, no existing row)
    factory = _make_mock_conn_factory(fetchone_queue=[None])
    reg = DBStrategyRegistry(conn_factory=factory)
    reg.register(s)

    cur = factory._cursor
    # Expect 3 execute calls: SELECT existing, INSERT registry, INSERT status_log
    assert cur.execute.call_count == 3
    calls_sql = [str(c.args[0]).strip() for c in cur.execute.call_args_list]
    assert "SELECT status FROM strategy_registry" in calls_sql[0]
    assert "INSERT INTO strategy_registry" in calls_sql[1]
    assert "INSERT INTO strategy_status_log" in calls_sql[2]
    # cache populated
    assert reg._instances[sid] is s


def test_register_idempotent_upsert_no_audit_log_for_existing():
    sid = uuid4()
    s = _FakeStrategy(strategy_id=str(sid), name="s1")
    # existing row returns ('draft',), second register does NOT insert audit log
    factory = _make_mock_conn_factory(fetchone_queue=[("draft",)])
    reg = DBStrategyRegistry(conn_factory=factory)
    reg.register(s)

    cur = factory._cursor
    # Expect 2 execute calls: SELECT, INSERT registry (no audit insert)
    assert cur.execute.call_count == 2


def test_register_raises_on_empty_factor_pool():
    sid = uuid4()
    s = _FakeStrategy(strategy_id=str(sid), name="s1", factor_pool=[])
    factory = _make_mock_conn_factory()
    reg = DBStrategyRegistry(conn_factory=factory)
    with pytest.raises(ValueError, match="factor_pool is empty"):
        reg.register(s)


def test_register_raises_on_invalid_uuid():
    s = _FakeStrategy(strategy_id="not-a-uuid", name="s1")
    factory = _make_mock_conn_factory()
    reg = DBStrategyRegistry(conn_factory=factory)
    with pytest.raises(ValueError, match="必须是 UUID"):
        reg.register(s)


# ─── get_live() tests ────────────────────────────────────────────────

def test_get_live_returns_registered_live_instances():
    sid1 = uuid4()
    sid2 = uuid4()
    s1 = _FakeStrategy(strategy_id=str(sid1), name="s1")
    s2 = _FakeStrategy(strategy_id=str(sid2), name="s2")

    factory = _make_mock_conn_factory()
    reg = DBStrategyRegistry(conn_factory=factory)
    # manually populate cache (skip register)
    reg._instances[sid1] = s1
    reg._instances[sid2] = s2
    # DB returns both as live
    factory._cursor.fetchall.return_value = [(str(sid1), "s1"), (str(sid2), "s2")]

    live = reg.get_live()
    assert len(live) == 2
    assert s1 in live and s2 in live


def test_get_live_empty_when_no_db_live_rows():
    factory = _make_mock_conn_factory()
    factory._cursor.fetchall.return_value = []
    reg = DBStrategyRegistry(conn_factory=factory)
    assert reg.get_live() == []


def test_get_live_raises_integrity_error_when_db_has_live_but_cache_missing():
    """DB 有 live UUID 但 in-memory cache 没 register → fail-loud 禁静默跳过."""
    sid = uuid4()
    factory = _make_mock_conn_factory()
    factory._cursor.fetchall.return_value = [(str(sid), "ghost_strategy")]
    reg = DBStrategyRegistry(conn_factory=factory)  # cache 空

    with pytest.raises(StrategyRegistryIntegrityError, match="cache 未 register"):
        reg.get_live()


# ─── get_by_id() tests ────────────────────────────────────────────────

def test_get_by_id_returns_instance():
    sid = uuid4()
    s = _FakeStrategy(strategy_id=str(sid), name="s1")
    factory = _make_mock_conn_factory(fetchone_queue=[(1,)])  # WHERE strategy_id=... returns 1
    reg = DBStrategyRegistry(conn_factory=factory)
    reg._instances[sid] = s

    got = reg.get_by_id(str(sid))
    assert got is s


def test_get_by_id_raises_when_not_in_db():
    sid = uuid4()
    factory = _make_mock_conn_factory(fetchone_queue=[None])
    reg = DBStrategyRegistry(conn_factory=factory)
    with pytest.raises(StrategyNotFound, match="不在 strategy_registry DB"):
        reg.get_by_id(str(sid))


def test_get_by_id_raises_when_db_ok_but_cache_missing():
    sid = uuid4()
    factory = _make_mock_conn_factory(fetchone_queue=[(1,)])
    reg = DBStrategyRegistry(conn_factory=factory)
    # cache intentionally empty
    with pytest.raises(StrategyNotFound, match="cache 未 register"):
        reg.get_by_id(str(sid))


# ─── update_status() tests ───────────────────────────────────────────

def test_update_status_writes_audit_log():
    sid = uuid4()
    factory = _make_mock_conn_factory(fetchone_queue=[("draft",)])
    reg = DBStrategyRegistry(conn_factory=factory)
    reg.update_status(str(sid), StrategyStatus.LIVE, reason="manual promote S1 to live")

    cur = factory._cursor
    # Expect 3 execute: SELECT status, UPDATE, INSERT log
    assert cur.execute.call_count == 3
    calls_sql = [str(c.args[0]).strip() for c in cur.execute.call_args_list]
    assert "SELECT status" in calls_sql[0]
    assert "UPDATE strategy_registry" in calls_sql[1]
    assert "INSERT INTO strategy_status_log" in calls_sql[2]


def test_update_status_no_op_when_same_status():
    sid = uuid4()
    factory = _make_mock_conn_factory(fetchone_queue=[("live",)])
    reg = DBStrategyRegistry(conn_factory=factory)
    reg.update_status(str(sid), StrategyStatus.LIVE, reason="idempotent no-op test")

    # Only 1 execute (SELECT), no UPDATE + no audit log
    assert factory._cursor.execute.call_count == 1


def test_update_status_raises_on_empty_reason():
    sid = uuid4()
    factory = _make_mock_conn_factory()
    reg = DBStrategyRegistry(conn_factory=factory)
    with pytest.raises(ValueError, match="reason"):
        reg.update_status(str(sid), StrategyStatus.LIVE, reason="  ")


def test_update_status_raises_when_not_in_db():
    sid = uuid4()
    factory = _make_mock_conn_factory(fetchone_queue=[None])
    reg = DBStrategyRegistry(conn_factory=factory)
    with pytest.raises(StrategyNotFound, match="先调 register"):
        reg.update_status(str(sid), StrategyStatus.LIVE, reason="promote")


# ─── EqualWeightAllocator tests ───────────────────────────────────────

def test_equal_weight_2_strategies_1M_total():
    s1 = _FakeStrategy(strategy_id=str(uuid4()))
    s2 = _FakeStrategy(strategy_id=str(uuid4()))
    alloc = EqualWeightAllocator()
    result = alloc.allocate([s1, s2], Decimal("1000000"), regime="bull")
    assert len(result) == 2
    assert all(v == Decimal("500000.00") for v in result.values())
    assert sum(result.values()) == Decimal("1000000")


def test_equal_weight_3_strategies_rounding_absorbs_tail():
    s1 = _FakeStrategy(strategy_id=str(uuid4()))
    s2 = _FakeStrategy(strategy_id=str(uuid4()))
    s3 = _FakeStrategy(strategy_id=str(uuid4()))
    alloc = EqualWeightAllocator()
    result = alloc.allocate([s1, s2, s3], Decimal("1000000"), regime="neutral")
    # 1M / 3 = 333333.33..., 尾差归最后一个
    assert sum(result.values()) == Decimal("1000000")
    # 前 2 个是 333333.33, 最后一个吸收 0.01 tail
    values = list(result.values())
    assert values[0] == Decimal("333333.33")
    assert values[1] == Decimal("333333.33")
    assert values[2] == Decimal("333333.34")


def test_equal_weight_empty_strategies():
    alloc = EqualWeightAllocator()
    result = alloc.allocate([], Decimal("1000000"), regime="bull")
    assert result == {}


def test_equal_weight_raises_on_non_positive_capital():
    s1 = _FakeStrategy(strategy_id=str(uuid4()))
    alloc = EqualWeightAllocator()
    with pytest.raises(ValueError, match="必须 > 0"):
        alloc.allocate([s1], Decimal("0"), regime="bull")
    with pytest.raises(ValueError, match="必须 > 0"):
        alloc.allocate([s1], Decimal("-100"), regime="bull")
