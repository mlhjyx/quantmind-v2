"""pytest共享fixtures — 异步DB session + API测试client + LLM singleton reset。

连接真实PostgreSQL: quantmind_v2。
每个测试用例创建独立connection+transaction，结束后ROLLBACK。

S4 PR #226 sediment: autouse fixture _reset_llm_singleton 反 cross-test pollution
(沿用 backend/qm_platform/observability/alert.py reset_alert_router 体例 + ADR-032).
"""

import sys
import uuid
from pathlib import Path

import pytest

# 确保backend目录和项目根目录在sys.path中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


@pytest.fixture(autouse=True)
def _reset_llm_singleton():
    """LLM Router 全局 singleton 跨 test reset (沿用 alert.py reset_*() 体例).

    yield 后跑 reset_llm_router() 反 singleton 状态污染 (e.g. 上 test mock
    monkeypatch litellm.Router.completion → 下 test 沿用 mock 漂移).

    沿用 reviewer Chunk B P1 hardening (defensive try/except ImportError):
    LiteLLM SDK 真**0 装** 时 (e.g. fork checkout 反 install) 跨 test teardown 真
    fail-safe (反 ModuleNotFoundError break 全 4222 非 LLM tests). 沿用铁律 33
    silent_ok 注释 (反 silent miss). 实测沿用 PR #226 真 litellm 已装真路径,
    仅 fork checkout 真**未来 break risk** 真防御.

    沿用 ADR-032 + LL-098 X10 (反 silent cross-test 污染 silent miss).
    """
    yield
    try:
        from backend.qm_platform.llm import reset_llm_router

        reset_llm_router()
    except ImportError:
        # silent_ok: litellm SDK 0 装时 reset 真 noop (反 break 4222 非 LLM tests).
        # 沿用铁律 33 silent_ok 注释 + Chunk B P1 reviewer hardening.
        pass


try:
    import pytest_asyncio
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        create_async_engine,
    )

    from app.main import app

    DATABASE_URL = "postgresql+asyncpg://xin:quantmind@localhost:5432/quantmind_v2"

    @pytest_asyncio.fixture
    async def db_session():
        """每个测试用例获得独立AsyncSession + ROLLBACK。

        每个测试用例:
        1. 创建独立engine (pool_size=1避免连接泄漏)
        2. 获取connection -> 开启事务
        3. 测试结束 -> rollback -> 关闭
        """
        engine = create_async_engine(DATABASE_URL, echo=False, pool_size=1, max_overflow=0)
        async with engine.connect() as conn:
            # 开启显式事务
            txn = await conn.begin()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
                await txn.rollback()
        await engine.dispose()

    @pytest_asyncio.fixture
    async def client():
        """异步HTTP客户端，用于API路由测试。

        通过httpx ASGITransport直接调用FastAPI app，无需启动服务器。
        """
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest_asyncio.fixture
    async def strategy_id(db_session: AsyncSession):
        """创建一个测试用strategy，返回其UUID。"""
        sid = uuid.uuid4()
        await db_session.execute(
            text(
                """INSERT INTO strategy (id, name, market, mode, active_version, status)
                   VALUES (:id, :name, 'astock', 'visual', 1, 'draft')"""
            ),
            {"id": sid, "name": f"test_strategy_{sid.hex[:8]}"},
        )
        return sid

except ImportError:
    # fastapi/sqlalchemy/pytest_asyncio not installed — skip DB/API fixtures
    pass


# ───────────────────────────────────────────────────────────────
# iter 110 (2026-05-25): MagicMock-based psycopg2 conn fixtures (Option A pilot)
# per docs/audit/MAKE_MOCK_CONN_REFACTOR_BLUEPRINT_2026_05_25.md §6 — canonical
# replacement for 12 module-local `_make_mock_conn` definitions (LL-198 root).
#
# Migration is incremental — pilot lands fixture infrastructure here without
# touching any existing test file. Future iter migrates test_*.py files one
# cluster at a time + deletes module-local definitions per blueprint §7.
#
# Key design (cures B1-B5 from blueprint §3):
#   - Fresh MagicMock per test invocation (no module-global state → kills B3+B5)
#   - NO default fetchone return value (test MUST opt-in via builder → kills B1)
#   - __enter__/__exit__ on cursor (with conn.cursor() as cur: 体例 works → kills B4)
#   - assert_no_db_writes() helper codifies LL-198 fix point 2 (write-only assert)
# ───────────────────────────────────────────────────────────────

from unittest.mock import MagicMock  # noqa: E402


@pytest.fixture
def mock_conn() -> MagicMock:
    """Yield a fresh MagicMock psycopg2-like connection per test invocation.

    Default state:
      - conn.cursor() returns a context-manager-capable MagicMock cursor
        (supports both `cur = conn.cursor()` and `with conn.cursor() as cur:`).
      - NO default fetchone / fetchall return value — test MUST explicitly set
        via `mock_conn.cursor().fetchone.return_value = ...` or similar.

    This intentional null-default cures LL-198 root (default (0,) tuple
    mis-classified by prod code expecting None / multi-column row).

    Usage:
        def test_foo(mock_conn):
            mock_conn.cursor().fetchone.return_value = ("draft",)
            service = MyService()
            result = service.process(conn=mock_conn)
            assert result.status == "ok"

    Sibling helpers (below) provide common shapes for fetchone queues + write
    counting.
    """
    conn = MagicMock(name="mock_conn")
    cursor = MagicMock(name="mock_cursor")
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor = MagicMock(return_value=cursor)
    return conn


@pytest.fixture
def mock_conn_factory_builder():
    """Yield a callable that builds conn-factory functions with fetchone queue.

    Some prod code (e.g. DBStrategyRegistry) takes `conn_factory` callable
    rather than conn directly — this builder mirrors test_strategy_registry's
    `_make_mock_conn_factory` pattern but lives in conftest as canonical.

    Usage:
        def test_bar(mock_conn_factory_builder):
            factory = mock_conn_factory_builder(fetchone_queue=[None, ("draft",)])
            registry = DBStrategyRegistry(conn_factory=factory)
            ...
            # factory._conn / factory._cursor attributes expose the underlying
            # mocks for assertion (sustained sibling pattern).
    """

    def _build(
        fetchone_queue: list | None = None,
        rowcounts: list | None = None,
    ):
        """Build a conn_factory callable returning a fresh MagicMock per call.

        Args:
            fetchone_queue: list of fetchone return values consumed iter-style.
                None → fetchone returns None always.
            rowcounts: list of cursor.rowcount values consumed iter-style.
                None → rowcount returns 1 (typical UPSERT success).
        """
        conn = MagicMock(name="mock_factory_conn")
        cursor = MagicMock(name="mock_factory_cursor")
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        if fetchone_queue is not None:
            cursor.fetchone = MagicMock(side_effect=list(fetchone_queue))
        if rowcounts is not None:
            # rowcount is property-like; PropertyMock + side_effect for queue
            from unittest.mock import PropertyMock

            type(cursor).rowcount = PropertyMock(side_effect=list(rowcounts))
        else:
            cursor.rowcount = 1
        conn.cursor = MagicMock(return_value=cursor)

        def _factory():
            return conn

        # Expose underlying mocks for test-side assertion (sustained体例)
        _factory._conn = conn  # type: ignore[attr-defined]
        _factory._cursor = cursor  # type: ignore[attr-defined]
        return _factory

    return _build


def _assert_no_db_writes_impl(conn: MagicMock) -> None:
    """Implementation of write-only assertion (separated from fixture for direct call).

    Codifies LL-198 fix point 2: SELECT-read is NOT a write side effect.
    Walks `conn.cursor().execute.call_args_list` and asserts every executed
    SQL starts with a read-only verb (SELECT / WITH / SHOW / EXPLAIN).
    """
    cursor = conn.cursor.return_value
    write_prefixes = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER")
    bad_calls: list[str] = []
    for call in cursor.execute.call_args_list:
        sql = call.args[0] if call.args else ""
        sql_upper = str(sql).lstrip().upper()
        if sql_upper.startswith(write_prefixes):
            bad_calls.append(str(sql)[:80])
    assert not bad_calls, (
        f"Expected no DB writes but found {len(bad_calls)}: {bad_calls!r}"
    )


@pytest.fixture
def assert_no_db_writes():
    """Yield assert_no_db_writes(conn) callable — write-only assert helper.

    Codifies LL-198 fix point 2: SELECT-read is NOT a write side effect.
    Tests inject this as a fixture and call directly.

    Usage:
        def test_no_writes(mock_conn, assert_no_db_writes):
            service = MyService()
            service.read_only_op(conn=mock_conn)
            assert_no_db_writes(mock_conn)
    """
    return _assert_no_db_writes_impl
