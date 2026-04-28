"""MVP 3.4 batch 3 — OutboxBackedAuditTrail unit + integration tests.

测试覆盖 (18 tests, 6 类):
  1. record() 参数校验 (5 tests): event_type 非 string / 无 '.' / 空 subtype /
     payload 非 dict / 缺 aggregate_id key
  2. record() happy path (3 tests): order.routed / signal.generated / fill.executed
     调 OutboxWriter.enqueue 参数正确
  3. record() tx 边界 (2 tests): commit on success / rollback on enqueue raise
  4. trace() 链断 (3 tests): fill 不存在 / order 不存在 / signal 不存在 → AuditMissing
  5. trace() payload 缺 key (2 tests): fill.payload 缺 order_id / order.payload 缺 signal_id
  6. trace() happy path mock (1 test): 4 events 完整链 → AuditChain
  7. (integration) record + trace round-trip (2 tests): 真 DB seed → trace → 验链

铁律:
  - 32 例外: OutboxBackedAuditTrail 自管短 tx, docstring 显式声明
  - 33 fail-loud: event_type / aggregate_id / 链断 全 raise
"""
from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts/ + backend/ sys.path hack
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture
def mock_conn():
    """Mock psycopg2 conn 给单元测试."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    conn.cursor.return_value = cursor
    return conn


@pytest.fixture
def audit_module():
    from qm_platform.signal import audit  # noqa: PLC0415
    return audit


# ─── 1. record() 参数校验 ─────────────────────────────────────


class TestRecordValidation:
    def test_event_type_not_string_raises(self, mock_conn, audit_module) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(ValueError, match="event_type 必须 string"):
            trail.record(123, {"order_id": "x"})  # type: ignore[arg-type]

    def test_event_type_no_dot_raises(self, mock_conn, audit_module) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(ValueError, match="aggregate_type"):
            trail.record("invalid_format", {"order_id": "x"})

    def test_event_type_empty_subtype_raises(self, mock_conn, audit_module) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(ValueError, match="空 aggregate_type 或 subtype"):
            trail.record("order.", {"order_id": "x"})

    def test_payload_non_dict_raises(self, mock_conn, audit_module) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(TypeError, match="payload 必须是 dict"):
            trail.record("order.routed", ["not", "dict"])  # type: ignore[arg-type]

    def test_payload_missing_aggregate_id_raises(self, mock_conn, audit_module) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(ValueError, match="必含 'order_id'"):
            trail.record("order.routed", {"signal_id": "sig-1"})  # 缺 order_id


# ─── 2. record() happy path ──────────────────────────────────


class TestRecordHappyPath:
    def test_order_routed_calls_enqueue(
        self, mock_conn, audit_module
    ) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with patch("qm_platform.observability.OutboxWriter") as MockWriter:
            mock_writer = MagicMock()
            mock_writer.enqueue.return_value = uuid.uuid4()
            MockWriter.return_value = mock_writer
            trail.record(
                "order.routed",
                {"order_id": "ord-1", "signal_id": "sig-1", "code": "600519.SH"},
            )
        mock_writer.enqueue.assert_called_once()
        kwargs = mock_writer.enqueue.call_args.kwargs
        assert kwargs["aggregate_type"] == "order"
        assert kwargs["aggregate_id"] == "ord-1"
        assert kwargs["event_type"] == "routed"  # subtype, 非全 event_type
        assert kwargs["payload"]["signal_id"] == "sig-1"

    def test_signal_generated_calls_enqueue(
        self, mock_conn, audit_module
    ) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with patch("qm_platform.observability.OutboxWriter") as MockWriter:
            mock_writer = MagicMock()
            mock_writer.enqueue.return_value = uuid.uuid4()
            MockWriter.return_value = mock_writer
            trail.record(
                "signal.generated",
                {"signal_id": "sig-2", "strategy_id": "s1"},
            )
        kwargs = mock_writer.enqueue.call_args.kwargs
        assert kwargs["aggregate_type"] == "signal"
        assert kwargs["aggregate_id"] == "sig-2"
        assert kwargs["event_type"] == "generated"

    def test_fill_executed_calls_enqueue(
        self, mock_conn, audit_module
    ) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with patch("qm_platform.observability.OutboxWriter") as MockWriter:
            mock_writer = MagicMock()
            mock_writer.enqueue.return_value = uuid.uuid4()
            MockWriter.return_value = mock_writer
            trail.record(
                "fill.executed",
                {"fill_id": "fill-1", "order_id": "ord-1", "qty": 100},
            )
        kwargs = mock_writer.enqueue.call_args.kwargs
        assert kwargs["aggregate_type"] == "fill"
        assert kwargs["aggregate_id"] == "fill-1"


# ─── 3. record() tx 边界 ─────────────────────────────────────


class TestRecordTxBoundary:
    def test_record_commits_on_success(self, mock_conn, audit_module) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with patch("qm_platform.observability.OutboxWriter") as MockWriter:
            MockWriter.return_value.enqueue.return_value = uuid.uuid4()
            trail.record("order.routed", {"order_id": "ord-1"})
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()
        mock_conn.rollback.assert_not_called()

    def test_record_rollbacks_on_enqueue_raise(
        self, mock_conn, audit_module
    ) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with patch("qm_platform.observability.OutboxWriter") as MockWriter:
            MockWriter.return_value.enqueue.side_effect = RuntimeError("DB fail")
            with pytest.raises(RuntimeError, match="DB fail"):
                trail.record("order.routed", {"order_id": "ord-1"})
        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()


# ─── 4. trace() 链断 ─────────────────────────────────────────


def _no_row_cursor(mock_conn):
    """配 cursor.fetchone 返 None (row 不存在)."""
    cur = mock_conn.cursor.return_value
    cur.fetchone.return_value = None
    return cur


def _seq_rows_cursor(mock_conn, rows: list):
    """配 cursor.fetchone 按顺序返 rows (None 表 0 row)."""
    cur = mock_conn.cursor.return_value
    cur.fetchone.side_effect = rows
    return cur


class TestTraceChainBreaks:
    def test_fill_event_missing_raises(self, mock_conn, audit_module) -> None:
        _no_row_cursor(mock_conn)
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(audit_module.AuditMissing, match="链断点 1: fill"):
            trail.trace("fill-missing")

    def test_order_event_missing_raises(self, mock_conn, audit_module) -> None:
        # fill 存在, 拿到 order_id, order 0 行
        ts = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
        _seq_rows_cursor(mock_conn, [
            ({"order_id": "ord-x"}, ts),  # fill payload + ts
            None,  # order 0 row
        ])
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(audit_module.AuditMissing, match="链断点 2: order"):
            trail.trace("fill-1")

    def test_signal_event_missing_raises(self, mock_conn, audit_module) -> None:
        ts = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
        _seq_rows_cursor(mock_conn, [
            ({"order_id": "ord-x"}, ts),  # fill
            ({"signal_id": "sig-y"}, ts),  # order
            None,  # signal 0 row
        ])
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(audit_module.AuditMissing, match="链断点 3: signal"):
            trail.trace("fill-1")


# ─── 5. trace() payload 缺 key ───────────────────────────────


class TestTracePayloadMissingKey:
    def test_fill_payload_missing_order_id_raises(
        self, mock_conn, audit_module
    ) -> None:
        ts = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
        _seq_rows_cursor(mock_conn, [
            ({"some_other_key": 1}, ts),  # fill payload 无 order_id
        ])
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(audit_module.AuditMissing, match="fill payload 缺 order_id"):
            trail.trace("fill-1")

    def test_order_payload_missing_signal_id_raises(
        self, mock_conn, audit_module
    ) -> None:
        ts = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
        _seq_rows_cursor(mock_conn, [
            ({"order_id": "ord-x"}, ts),
            ({"some_other_key": 1}, ts),  # order payload 无 signal_id
        ])
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(audit_module.AuditMissing, match="order payload 缺 signal_id"):
            trail.trace("fill-1")


# ─── 6. trace() happy path ──────────────────────────────────


class TestTraceHappyPath:
    def test_full_chain_returns_audit_chain(self, mock_conn, audit_module) -> None:
        ts_fill = datetime(2026, 4, 28, 10, 30, tzinfo=UTC)
        ts_order = datetime(2026, 4, 28, 10, 25, tzinfo=UTC)
        ts_signal = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
        _seq_rows_cursor(mock_conn, [
            ({"order_id": "ord-1", "qty": 100, "price": 50.5}, ts_fill),
            ({"signal_id": "sig-1", "code": "600519.SH"}, ts_order),
            (
                {
                    "strategy_id": "s1_monthly_ranking",
                    "factor_contributions": {
                        "turnover_mean_20": 0.25,
                        "volatility_20": 0.25,
                        "bp_ratio": 0.25,
                        "dv_ttm": 0.25,
                    },
                    "trade_date": "2026-04-28",
                    "code": "600519.SH",
                },
                ts_signal,
            ),
        ])
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        chain = trail.trace("fill-1")

        assert chain.fill_id == "fill-1"
        assert chain.order_id == "ord-1"
        assert chain.strategy_id == "s1_monthly_ranking"
        assert chain.factor_contributions == {
            "turnover_mean_20": 0.25,
            "volatility_20": 0.25,
            "bp_ratio": 0.25,
            "dv_ttm": 0.25,
        }
        assert chain.signal_trace["code"] == "600519.SH"
        assert chain.timestamps["fill"] == ts_fill.isoformat()
        assert chain.timestamps["order"] == ts_order.isoformat()
        assert chain.timestamps["signal"] == ts_signal.isoformat()


# ─── 7. trace() 输入校验 ─────────────────────────────────────


class TestTraceInputValidation:
    def test_empty_fill_id_raises(self, mock_conn, audit_module) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(ValueError, match="fill_id 必须非空"):
            trail.trace("")

    def test_whitespace_fill_id_raises(self, mock_conn, audit_module) -> None:
        trail = audit_module.OutboxBackedAuditTrail(conn_factory=lambda: mock_conn)
        with pytest.raises(ValueError, match="fill_id 必须非空"):
            trail.trace("   ")


# ─── 8. (integration) 真 DB round-trip ─────────────────────


@pytest.mark.integration
class TestDBIntegration:
    """走真 DB. record() 写 outbox + trace() 读 outbox 反向链."""

    def test_record_then_query_event_outbox(self) -> None:
        """record 'order.routed' → event_outbox 行可读 + 字段对."""
        from qm_platform.signal import OutboxBackedAuditTrail  # noqa: PLC0415

        from app.services.db import get_sync_conn  # noqa: PLC0415

        order_id = f"int-test-order-{uuid.uuid4()}"
        trail = OutboxBackedAuditTrail()  # 默认 conn_factory=get_sync_conn
        try:
            trail.record(
                "order.routed",
                {"order_id": order_id, "signal_id": "sig-int", "code": "600519.SH"},
            )
            # 验 row 写入
            verify_conn = get_sync_conn()
            try:
                cur = verify_conn.cursor()
                cur.execute(
                    """SELECT aggregate_type, event_type, payload
                       FROM event_outbox WHERE aggregate_id = %s""",
                    (order_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "order"
                assert row[1] == "routed"
                assert row[2]["signal_id"] == "sig-int"
            finally:
                verify_conn.close()
        finally:
            # cleanup
            try:
                cleanup_conn = get_sync_conn()
                cur = cleanup_conn.cursor()
                cur.execute(
                    "DELETE FROM event_outbox WHERE aggregate_id = %s", (order_id,),
                )
                cleanup_conn.commit()
                cleanup_conn.close()
            except Exception:  # noqa: BLE001
                pass  # silent_ok: cleanup 失败不掩盖主 assert

    def test_full_chain_record_then_trace(self) -> None:
        """seed 3 events (signal/order/fill) → trace fill_id → 验 AuditChain 完整."""
        from qm_platform.signal import OutboxBackedAuditTrail  # noqa: PLC0415

        from app.services.db import get_sync_conn  # noqa: PLC0415

        # 唯一 ID 防 test 行污染
        suffix = uuid.uuid4()
        signal_id = f"int-sig-{suffix}"
        order_id = f"int-ord-{suffix}"
        fill_id = f"int-fill-{suffix}"

        trail = OutboxBackedAuditTrail()
        try:
            # seed 3 events 顺序: signal → order → fill
            trail.record("signal.generated", {
                "signal_id": signal_id,
                "strategy_id": "s1_monthly_ranking",
                "factor_contributions": {"turnover_mean_20": 0.5, "volatility_20": 0.5},
                "code": "600519.SH",
            })
            trail.record("order.routed", {
                "order_id": order_id,
                "signal_id": signal_id,
                "code": "600519.SH",
                "qty": 100,
            })
            trail.record("fill.executed", {
                "fill_id": fill_id,
                "order_id": order_id,
                "qty": 100,
                "price": 1500.5,
            })

            # trace
            chain = trail.trace(fill_id)
            assert chain.fill_id == fill_id
            assert chain.order_id == order_id
            assert chain.strategy_id == "s1_monthly_ranking"
            assert chain.factor_contributions == {
                "turnover_mean_20": 0.5, "volatility_20": 0.5,
            }
            assert chain.signal_trace["code"] == "600519.SH"
            assert "fill" in chain.timestamps
            assert "order" in chain.timestamps
            assert "signal" in chain.timestamps
        finally:
            # cleanup
            try:
                cleanup_conn = get_sync_conn()
                cur = cleanup_conn.cursor()
                for agg_id in (signal_id, order_id, fill_id):
                    cur.execute(
                        "DELETE FROM event_outbox WHERE aggregate_id = %s",
                        (agg_id,),
                    )
                cleanup_conn.commit()
                cleanup_conn.close()
            except Exception:  # noqa: BLE001
                pass  # silent_ok: cleanup 失败不掩盖主 assert
