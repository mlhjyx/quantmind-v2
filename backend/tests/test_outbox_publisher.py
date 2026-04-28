"""MVP 3.4 batch 2 — OutboxPublisher unit + integration tests.

测试覆盖 (16 tests, 5 类):
  1. happy path: 单行 publish 成功 → published_at 写, retries 不变
  2. batch path: 多行 FIFO 顺序, 各 row 独立 publish
  3. 失败重试: publish 返 None → retries+1, 不写 published_at
  4. DLQ 终结: retries 达 max → DLQ publish + 标 published_at + 高 retries
  5. 参数校验: max_retries < 1 / batch_size < 1 raise
  6. tick task: Celery task 入口能调通 (smoke level), 异常 raise

铁律:
  - 32 (Service 不 commit): publisher 是 Celery task 顶层 owner, 自管 commit (例外明示)
  - 33 (fail-loud): publish exception → DLQ + 终结, 不 silent

Notes:
  - Unit tests 用 mock conn + mock stream_publisher (无 DB / Redis 依赖)
  - Integration tests 走真 DB (event_outbox + StreamBus stub) — 标 @integration
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# scripts/ + backend/ sys.path hack
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture
def mock_conn():
    """Mock psycopg2 conn 给单元测试 (with cursor 上下文管理器一致)."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    conn.cursor.return_value = cursor
    return conn


@pytest.fixture
def publisher_module():
    from app.tasks import outbox_publisher  # noqa: PLC0415
    return outbox_publisher


def _row(event_id=None, aggregate_type="signal", aggregate_id="sig-1",
         event_type="generated", payload=None, retries=0):
    """构造 SELECT 返回行 tuple (与 publisher SELECT 列顺序一致)."""
    return (
        event_id or uuid.uuid4(),
        aggregate_type,
        aggregate_id,
        event_type,
        payload if payload is not None else {"k": "v"},
        retries,
    )


# ─── 1. Happy path: 单行 publish 成功 ─────────────────────────


class TestPublishHappyPath:
    def test_single_row_published_marks_published_at(
        self, mock_conn, publisher_module
    ) -> None:
        row = _row(aggregate_type="signal", event_type="generated")
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = [row]

        stream_pub = MagicMock(return_value="msg-id-1")
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=stream_pub,
        )
        result = pub.publish_batch()

        assert result == {
            "selected": 1, "published": 1, "retried": 0, "dlq": 0,
            "publisher_exceptions": 0,
        }
        # publish_sync 调一次, stream 名拼接正确
        stream_pub.assert_called_once()
        call_stream, call_data = stream_pub.call_args[0]
        assert call_stream == "qm:signal:generated"
        assert call_data["event_id"] == str(row[0])
        assert call_data["aggregate_id"] == "sig-1"
        assert call_data["payload"] == {"k": "v"}
        # P1.2 reviewer 采纳: source 必须 keyword-only (StreamBus.publish_sync 契约).
        # 守此 contract gap 防 production wiring 改 callable wrapper 时 silently 丢 source.
        assert stream_pub.call_args.kwargs.get("source") == "outbox_publisher", (
            "source 必须 keyword-only 传, 用 positional 会破 StreamBus contract"
        )

        # UPDATE published_at = NOW() 写一次
        update_calls = [
            c for c in cur.execute.call_args_list
            if "UPDATE event_outbox" in c[0][0] and "published_at = NOW()" in c[0][0]
        ]
        assert len(update_calls) == 1
        # commit 调用
        mock_conn.commit.assert_called_once()

    def test_batch_select_uses_skip_locked(self, mock_conn, publisher_module) -> None:
        """SELECT FOR UPDATE SKIP LOCKED 是 publisher 并发安全 contract."""
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = []
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=MagicMock(return_value="msg"),
            batch_size=50,
        )
        pub.publish_batch()

        first_sql = cur.execute.call_args_list[0][0][0]
        assert "FOR UPDATE SKIP LOCKED" in first_sql
        assert "WHERE published_at IS NULL" in first_sql
        assert "ORDER BY created_at" in first_sql
        # batch_size 传参
        assert cur.execute.call_args_list[0][0][1] == (50,)


# ─── 2. Batch path: 多行 publish ──────────────────────────────


class TestBatchPublish:
    def test_multiple_rows_each_published(self, mock_conn, publisher_module) -> None:
        rows = [
            _row(aggregate_type="signal", event_type="generated"),
            _row(aggregate_type="order", event_type="routed"),
            _row(aggregate_type="fill", event_type="executed"),
        ]
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = rows

        stream_pub = MagicMock(side_effect=["m1", "m2", "m3"])
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=stream_pub,
        )
        result = pub.publish_batch()

        assert result["selected"] == 3
        assert result["published"] == 3
        assert stream_pub.call_count == 3
        # stream 名各异
        names = [c[0][0] for c in stream_pub.call_args_list]
        assert names == [
            "qm:signal:generated",
            "qm:order:routed",
            "qm:fill:executed",
        ]

    def test_empty_batch_skips_commit(
        self, mock_conn, publisher_module
    ) -> None:
        """P2.7 reviewer 采纳: 0 unpublished rows → 早退出, 不 commit (省 round-trip).

        Steady-state (0 backlog) 是 publisher 常态 (30s × 24h = 2880 ticks/日),
        每次空 commit 走 PG 来回是无谓开销.
        """
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = []

        stream_pub = MagicMock()
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=stream_pub,
        )
        result = pub.publish_batch()

        assert result == {
            "selected": 0, "published": 0, "retried": 0, "dlq": 0,
            "publisher_exceptions": 0,
        }
        stream_pub.assert_not_called()
        # 空 batch 早退出 → commit 不应被调 (P2.7 优化)
        mock_conn.commit.assert_not_called()


# ─── 3. 失败重试: publish 返 None ─────────────────────────────


class TestRetryOnFailure:
    def test_publish_returns_none_increments_retries(
        self, mock_conn, publisher_module
    ) -> None:
        row = _row(retries=2)
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = [row]

        stream_pub = MagicMock(return_value=None)  # publish 失败
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=stream_pub,
            max_retries=10,
        )
        result = pub.publish_batch()

        assert result["retried"] == 1
        assert result["published"] == 0
        assert result["dlq"] == 0
        # UPDATE retries=3 (不写 published_at)
        update_calls = [
            c for c in cur.execute.call_args_list
            if "UPDATE event_outbox" in c[0][0] and "retries = %s" in c[0][0]
            and "published_at" not in c[0][0]
        ]
        assert len(update_calls) == 1
        assert update_calls[0][0][1][0] == 3  # retries+1

    def test_publish_exception_caught_as_failure(
        self, mock_conn, publisher_module
    ) -> None:
        """publisher 直接 raise (非 StreamBus 默认行为) → 视为失败计 publisher_exceptions+retried.

        P1.4 reviewer 采纳: counter 重命名 errors → publisher_exceptions
        语义明确: 仅计 stream_publisher 调 raise 的次数, publish_sync 返 None
        不计入 (走 retried/dlq 分支). 监控告警可基于此区分 "Redis API 不通"
        vs "publish 静默失败" 两类问题.
        """
        row = _row(retries=0)
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = [row]

        stream_pub = MagicMock(side_effect=RuntimeError("redis down"))
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=stream_pub,
            max_retries=10,
        )
        result = pub.publish_batch()

        assert result["publisher_exceptions"] == 1
        assert result["retried"] == 1
        assert result["published"] == 0


# ─── 4. DLQ 终结: retries 达 max ──────────────────────────────


class TestDLQTermination:
    def test_max_retries_reached_publishes_dlq_and_marks_published(
        self, mock_conn, publisher_module
    ) -> None:
        row = _row(retries=9, aggregate_type="risk", event_type="triggered")
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = [row]

        # 第 1 调 (主 publish) 返 None 失败, 第 2 调 (DLQ) 返 dlq-msg-id
        stream_pub = MagicMock(side_effect=[None, "dlq-msg-1"])
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=stream_pub,
            max_retries=10,
        )
        result = pub.publish_batch()

        assert result["dlq"] == 1
        assert result["published"] == 0
        assert result["retried"] == 0
        # 调 publish 2 次: 主 stream + DLQ stream
        assert stream_pub.call_count == 2
        assert stream_pub.call_args_list[0][0][0] == "qm:risk:triggered"
        assert stream_pub.call_args_list[1][0][0] == publisher_module.DLQ_STREAM
        dlq_data = stream_pub.call_args_list[1][0][1]
        assert "_dlq_reason" in dlq_data
        assert "max_retries=10" in dlq_data["_dlq_reason"]
        assert dlq_data["_dlq_retries"] == 10

        # UPDATE 标 published_at + retries=10 (终结防 zombie)
        update_calls = [
            c for c in cur.execute.call_args_list
            if "UPDATE event_outbox" in c[0][0]
            and "published_at = NOW()" in c[0][0]
            and "retries = %s" in c[0][0]
        ]
        assert len(update_calls) == 1
        assert update_calls[0][0][1][0] == 10  # retries 终结值

    def test_dlq_publish_also_fails_still_marks_published(
        self, mock_conn, publisher_module
    ) -> None:
        """DLQ publish 自己失败 → 行仍标 published_at 防 zombie 永久重试.

        P1.3 reviewer 采纳: DLQ publish 异常必须计入 publisher_exceptions counter
        (原代码只 log 不计 → 监控 summary 看不到 DLQ 自身坏掉, 静默失败盲区).
        本 case: 主 publish 返 None (未 raise) + DLQ publish raise → 计 1 次异常.
        """
        row = _row(retries=9)
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = [row]

        stream_pub = MagicMock(side_effect=[None, RuntimeError("dlq stream broken")])
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=stream_pub,
            max_retries=10,
        )
        result = pub.publish_batch()

        assert result["dlq"] == 1
        # P1.3 新增 assertion: DLQ publish 异常被计入 publisher_exceptions
        assert result["publisher_exceptions"] == 1, (
            "DLQ publish raise 必须计入 publisher_exceptions (监控可见 DLQ 自身 broken)"
        )
        # 行仍标 published_at (UPDATE 调用了)
        update_calls = [
            c for c in cur.execute.call_args_list
            if "UPDATE event_outbox" in c[0][0] and "published_at = NOW()" in c[0][0]
        ]
        assert len(update_calls) == 1

    def test_exception_path_dlq_reason_includes_exc_type(
        self, mock_conn, publisher_module
    ) -> None:
        """publisher raise 路径下达 max → DLQ reason 含 exception 类型 (audit)."""
        row = _row(retries=9)
        cur = mock_conn.cursor.return_value
        cur.fetchall.return_value = [row]

        stream_pub = MagicMock(side_effect=[
            ConnectionError("redis timeout"), "dlq-msg",
        ])
        pub = publisher_module.OutboxPublisher(
            conn_factory=lambda: mock_conn,
            stream_publisher=stream_pub,
            max_retries=10,
        )
        result = pub.publish_batch()

        assert result["dlq"] == 1
        dlq_data = stream_pub.call_args_list[1][0][1]
        assert "ConnectionError" in dlq_data["_dlq_reason"]
        assert "redis timeout" in dlq_data["_dlq_reason"]


# ─── 5. 参数校验 ───────────────────────────────────────────


class TestParameterValidation:
    def test_max_retries_zero_raises(self, publisher_module) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            publisher_module.OutboxPublisher(max_retries=0)

    def test_max_retries_negative_raises(self, publisher_module) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            publisher_module.OutboxPublisher(max_retries=-1)

    def test_batch_size_zero_raises(self, publisher_module) -> None:
        with pytest.raises(ValueError, match="batch_size"):
            publisher_module.OutboxPublisher(batch_size=0)

    def test_batch_size_negative_raises(self, publisher_module) -> None:
        with pytest.raises(ValueError, match="batch_size"):
            publisher_module.OutboxPublisher(batch_size=-5)


# ─── 6. Celery task tick 入口 ──────────────────────────────


class TestTickTask:
    def test_tick_task_runs_publish_batch_returns_summary(
        self, monkeypatch, publisher_module
    ) -> None:
        """outbox_publisher_tick 入口: 调 OutboxPublisher.publish_batch 并返 summary+elapsed."""
        # monkey patch OutboxPublisher 走 mock
        fake_summary = {
            "selected": 5, "published": 4, "retried": 1, "dlq": 0,
            "publisher_exceptions": 0,
        }
        fake_publisher = MagicMock()
        fake_publisher.publish_batch.return_value = fake_summary

        monkeypatch.setattr(
            publisher_module, "OutboxPublisher",
            MagicMock(return_value=fake_publisher),
        )

        # 直接调 task function 内部 (不走 Celery broker)
        task = publisher_module.outbox_publisher_tick
        result = task.run()

        assert result["selected"] == 5
        assert result["published"] == 4
        assert "elapsed_s" in result
        assert isinstance(result["elapsed_s"], float)
        fake_publisher.publish_batch.assert_called_once()

    def test_tick_task_propagates_exception(
        self, monkeypatch, publisher_module
    ) -> None:
        """publisher 抛异常 → task raise (Celery acks_late 标 failed, max_retries=0 不重派)."""
        fake_publisher = MagicMock()
        fake_publisher.publish_batch.side_effect = RuntimeError("DB down")
        monkeypatch.setattr(
            publisher_module, "OutboxPublisher",
            MagicMock(return_value=fake_publisher),
        )

        task = publisher_module.outbox_publisher_tick
        with pytest.raises(RuntimeError, match="DB down"):
            task.run()


# ─── 7. (integration) 真 DB round-trip ─────────────────────


@pytest.mark.integration
class TestDBIntegration:
    """走真 DB (event_outbox 表已 migrate). 验 SELECT FOR UPDATE SKIP LOCKED + UPDATE 完整路径."""

    def test_publish_then_published_at_set(self) -> None:
        """enqueue → publish_batch → 行 published_at 非 NULL."""
        from qm_platform.observability import OutboxWriter  # noqa: PLC0415

        from app.services.db import get_sync_conn  # noqa: PLC0415
        from app.tasks.outbox_publisher import OutboxPublisher  # noqa: PLC0415

        # 1. enqueue 一行 (用真 conn)
        test_id = uuid.uuid4()
        conn = get_sync_conn()
        try:
            conn.autocommit = False
            writer = OutboxWriter(conn)
            writer.enqueue(
                aggregate_type="signal",
                aggregate_id=f"int-test-{test_id}",
                event_type="generated",
                payload={"_test": "integration", "id": str(test_id)},
                event_id=test_id,
            )
            conn.commit()
        finally:
            conn.close()

        # 2. publish_batch (mock stream_publisher 模拟成功 Redis xadd)
        stream_pub = MagicMock(return_value="mock-msg-id")
        publisher = OutboxPublisher(
            conn_factory=get_sync_conn,
            stream_publisher=stream_pub,
            batch_size=100,
        )
        try:
            summary = publisher.publish_batch()
            assert summary["selected"] >= 1
            assert summary["published"] >= 1

            # 3. 验 published_at 已写
            verify_conn = get_sync_conn()
            try:
                cur = verify_conn.cursor()
                cur.execute(
                    "SELECT published_at, retries FROM event_outbox WHERE event_id = %s",
                    (str(test_id),),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] is not None, "published_at 应被 publisher 标"
                assert row[1] == 0, "成功 publish 不增 retries"
            finally:
                verify_conn.close()
        finally:
            # cleanup (PR #119 P2.2 pattern)
            try:
                cleanup_conn = get_sync_conn()
                cur = cleanup_conn.cursor()
                cur.execute(
                    "DELETE FROM event_outbox WHERE event_id = %s", (str(test_id),)
                )
                cleanup_conn.commit()
                cleanup_conn.close()
            except Exception:  # noqa: BLE001
                pass  # silent_ok: cleanup 失败不该掩盖 test 主 assert
