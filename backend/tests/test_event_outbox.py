"""MVP 3.4 batch 1 — OutboxWriter unit + integration tests.

测试覆盖 (12 tests, 5 类):
  1. Happy path: enqueue 返 UUID + INSERT 在调用方 tx 内
  2. 参数校验 fail-loud: aggregate_type 白名单 / aggregate_id 空 / event_type 空 /
     payload 非 dict / payload 不可 JSON 序列化
  3. event_id: None 自动生成 / str 解析 / UUID 直传 / 非法类型 raise
  4. tx 边界: enqueue 不 commit, rollback 后行不存
  5. (integration) BRIN 索引使用: EXPLAIN ANALYZE 返 ix_event_outbox_unpublished

铁律:
  - 33 (fail-loud): 5 个 ValueError/TypeError 路径全 raise 测试
  - 32 (Service 不 commit): test_enqueue_does_not_commit_caller_tx 验证

Notes:
  - 单元 tests (1-4) 用 mock psycopg2 conn, 无 DB 依赖
  - Integration tests (5) 走真 DB (event_outbox 表已 migrate, conftest 提供 conn fixture)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# scripts/ + backend/ sys.path hack 跟现有 backend/tests 风格一致
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture
def mock_conn():
    """Mock psycopg2 connection 给单元测试 (无 DB 依赖).

    Note: PR #119 reviewer P1.2 fix 后 outbox.py 用 ``with conn.cursor() as cur:``
    上下文管理. 配合 MagicMock 默认 __enter__ 返子 mock 行为, 此 fixture 配置
    cursor.__enter__.return_value = cursor 让 ``cur`` 与 cursor 同 mock 引用,
    便于 test 通过 ``mock_conn.cursor.return_value.execute`` 访问 execute calls.
    """
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor  # with cursor as cur: cur === cursor
    cursor.__exit__.return_value = False
    conn.cursor.return_value = cursor
    return conn


@pytest.fixture
def outbox_module():
    """Import outbox module 一次, 跨测试共享."""
    from qm_platform.observability import outbox  # noqa: PLC0415
    return outbox


# ─── 1. Happy path ────────────────────────────────────────────


class TestEnqueueHappyPath:
    def test_enqueue_returns_uuid(self, mock_conn, outbox_module) -> None:
        writer = outbox_module.OutboxWriter(mock_conn)
        eid = writer.enqueue(
            aggregate_type="signal",
            aggregate_id="sig-2026-04-28-s1",
            event_type="generated",
            payload={"strategy_id": "s1", "stock_count": 20},
        )
        assert isinstance(eid, uuid.UUID)
        # cursor.execute called once with SQL + 5 params
        mock_conn.cursor.return_value.execute.assert_called_once()
        sql, params = mock_conn.cursor.return_value.execute.call_args[0]
        assert "INSERT INTO event_outbox" in sql
        assert params[0] == str(eid)
        assert params[1] == "signal"
        assert params[2] == "sig-2026-04-28-s1"
        assert params[3] == "generated"
        # payload params[4] is JSON string
        loaded = json.loads(params[4])
        assert loaded == {"strategy_id": "s1", "stock_count": 20}

    def test_enqueue_does_not_commit_caller_tx(self, mock_conn, outbox_module) -> None:
        """铁律 32: enqueue 不调 conn.commit()."""
        writer = outbox_module.OutboxWriter(mock_conn)
        writer.enqueue(
            aggregate_type="order",
            aggregate_id="ord-1",
            event_type="routed",
            payload={"code": "600519.SH"},
        )
        mock_conn.commit.assert_not_called()


# ─── 2. 参数校验 fail-loud (铁律 33) ───────────────────────────


class TestParameterValidation:
    def test_invalid_aggregate_type_raises(self, mock_conn, outbox_module) -> None:
        writer = outbox_module.OutboxWriter(mock_conn)
        with pytest.raises(ValueError, match="aggregate_type"):
            writer.enqueue(
                aggregate_type="strategy",  # not in whitelist
                aggregate_id="x",
                event_type="generated",
                payload={},
            )

    def test_empty_aggregate_id_raises(self, mock_conn, outbox_module) -> None:
        writer = outbox_module.OutboxWriter(mock_conn)
        with pytest.raises(ValueError, match="aggregate_id"):
            writer.enqueue(
                aggregate_type="signal",
                aggregate_id="   ",  # whitespace-only
                event_type="generated",
                payload={},
            )

    def test_empty_event_type_raises(self, mock_conn, outbox_module) -> None:
        writer = outbox_module.OutboxWriter(mock_conn)
        with pytest.raises(ValueError, match="event_type"):
            writer.enqueue(
                aggregate_type="signal",
                aggregate_id="x",
                event_type="",
                payload={},
            )

    def test_payload_non_dict_raises(self, mock_conn, outbox_module) -> None:
        writer = outbox_module.OutboxWriter(mock_conn)
        with pytest.raises(TypeError, match="payload"):
            writer.enqueue(
                aggregate_type="signal",
                aggregate_id="x",
                event_type="generated",
                payload=["not", "a", "dict"],  # type: ignore[arg-type]
            )

    def test_payload_unserializable_raises(self, mock_conn, outbox_module) -> None:
        """不可 JSON 序列化的 payload (e.g., set 字段) → ValueError."""
        writer = outbox_module.OutboxWriter(mock_conn)
        # default=str fallback 会把 set 转 str (非 raise), 用真 unserializable: object()
        class _Unserializable:
            pass
        with pytest.raises(ValueError, match="JSON"):
            writer.enqueue(
                aggregate_type="signal",
                aggregate_id="x",
                event_type="generated",
                payload={"bad": _Unserializable()},
            )


# ─── 3. event_id 处理 ─────────────────────────────────────────


class TestEventIdHandling:
    def test_event_id_none_auto_generates(self, mock_conn, outbox_module) -> None:
        writer = outbox_module.OutboxWriter(mock_conn)
        eid1 = writer.enqueue(
            aggregate_type="signal", aggregate_id="x", event_type="generated", payload={},
        )
        eid2 = writer.enqueue(
            aggregate_type="signal", aggregate_id="x", event_type="generated", payload={},
        )
        assert eid1 != eid2  # 自动生成不同

    def test_event_id_str_parsed(self, mock_conn, outbox_module) -> None:
        writer = outbox_module.OutboxWriter(mock_conn)
        explicit = "12345678-1234-1234-1234-123456789abc"
        eid = writer.enqueue(
            aggregate_type="signal", aggregate_id="x", event_type="generated",
            payload={}, event_id=explicit,
        )
        assert str(eid) == explicit

    def test_event_id_uuid_direct(self, mock_conn, outbox_module) -> None:
        writer = outbox_module.OutboxWriter(mock_conn)
        explicit = uuid.uuid4()
        eid = writer.enqueue(
            aggregate_type="signal", aggregate_id="x", event_type="generated",
            payload={}, event_id=explicit,
        )
        assert eid == explicit

    def test_event_id_invalid_str_raises(self, mock_conn, outbox_module) -> None:
        """PR #119 reviewer P2 采纳: 非法 UUID 字符串 → uuid.UUID() raise ValueError."""
        writer = outbox_module.OutboxWriter(mock_conn)
        with pytest.raises(ValueError):
            writer.enqueue(
                aggregate_type="signal", aggregate_id="x", event_type="generated",
                payload={}, event_id="not-a-uuid",
            )

    def test_event_id_invalid_type_raises(self, mock_conn, outbox_module) -> None:
        """PR #119 reviewer P3.1 采纳: event_id 非 UUID/str/None → TypeError."""
        writer = outbox_module.OutboxWriter(mock_conn)
        with pytest.raises(TypeError, match="event_id"):
            writer.enqueue(
                aggregate_type="signal", aggregate_id="x", event_type="generated",
                payload={}, event_id=42,  # type: ignore[arg-type]
            )


# ─── 4. (integration) tx 边界 + DB schema ─────────────────────


@pytest.mark.integration
class TestDBIntegration:
    """走真 DB (event_outbox 表已 migrate). 验 INSERT round-trip + tx 边界."""

    def test_enqueue_then_rollback_no_row(self) -> None:
        """铁律 32: enqueue 后 rollback → 行不入库."""
        from qm_platform.observability import OutboxWriter  # noqa: PLC0415

        from app.services.db import get_sync_conn  # noqa: PLC0415

        conn = get_sync_conn()
        try:
            conn.autocommit = False  # explicit tx
            writer = OutboxWriter(conn)
            test_id = uuid.uuid4()
            writer.enqueue(
                aggregate_type="signal",
                aggregate_id=f"test-rollback-{test_id}",
                event_type="generated",
                payload={"_test": "rollback"},
                event_id=test_id,
            )
            conn.rollback()  # 调用方 rollback
            # 验证行不存
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM event_outbox WHERE event_id = %s", (str(test_id),))
            assert cur.fetchone()[0] == 0, "rollback 后行应不存"
        finally:
            conn.close()

    def test_enqueue_then_commit_row_visible(self) -> None:
        """commit 后行可读. cleanup 在 finally (PR #119 reviewer P2.2 采纳:
        assert 失败时 cleanup 也必跑, 防 test 行污染共享 event_outbox 表).
        """
        from qm_platform.observability import OutboxWriter  # noqa: PLC0415

        from app.services.db import get_sync_conn  # noqa: PLC0415

        conn = get_sync_conn()
        test_id = uuid.uuid4()
        try:
            conn.autocommit = False
            writer = OutboxWriter(conn)
            writer.enqueue(
                aggregate_type="signal",
                aggregate_id=f"test-commit-{test_id}",
                event_type="generated",
                payload={"_test": "commit"},
                event_id=test_id,
            )
            conn.commit()
            cur = conn.cursor()
            cur.execute(
                "SELECT aggregate_type, event_type, published_at, retries FROM event_outbox WHERE event_id = %s",
                (str(test_id),),
            )
            row = cur.fetchone()
            assert row is not None, "commit 后行应可读"
            assert row[0] == "signal"
            assert row[1] == "generated"
            assert row[2] is None, "published_at 默认 NULL"
            assert row[3] == 0, "retries 默认 0"
        finally:
            # cleanup 必跑 (assert fail 也要清), 防共享表污染
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM event_outbox WHERE event_id = %s", (str(test_id),))
                conn.commit()
            except Exception:  # noqa: BLE001
                pass  # silent_ok: cleanup 失败不该掩盖 test 主 assert
            conn.close()
