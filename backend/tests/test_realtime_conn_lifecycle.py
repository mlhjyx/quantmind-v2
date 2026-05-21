"""realtime.py 连接生命周期回归测试 — idle-in-transaction 泄漏修复。

背景: backend/app/api/realtime.py 的 _lazy_conn 是 worker 级长生命周期连接,
原 _get_conn() 仅在请求*开始*时 rollback, 请求间 / 无流量期连接长期
idle-in-transaction 阻塞 autovacuum (2026-05-22 实测 pg_stat_activity
pid 19996 idle-in-txn ~48h; uvicorn --workers 2 → 2 条泄漏连接)。

修复: _make_conn() 设 autocommit=True (只读连接, 每条 SELECT 自动收尾);
_get_conn() 探活改用 SELECT 1 查询往返 (autocommit 下 rollback 不往返服务端)。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import app.api.realtime as realtime


@pytest.fixture(autouse=True)
def _reset_lazy_conn():
    """每个测试前后复位 realtime.py 模块级懒连接状态, 防测试间污染。"""
    realtime._lazy_conn = None
    realtime._conn_tried = False
    yield
    realtime._lazy_conn = None
    realtime._conn_tried = False


def test_make_conn_sets_autocommit(monkeypatch):
    """_make_conn() 必须把连接设为 autocommit — 防 idle-in-transaction 泄漏。"""
    fake_conn = MagicMock()
    monkeypatch.setattr("app.services.db.get_sync_conn", lambda: fake_conn)

    conn = realtime._make_conn()

    assert conn is fake_conn
    assert fake_conn.autocommit is True


def test_make_conn_failure_returns_none(monkeypatch):
    """get_sync_conn 抛异常时 _make_conn 返回 None (沿用原 fail-soft 行为)。"""

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.services.db.get_sync_conn", _boom)

    assert realtime._make_conn() is None


def test_get_conn_liveness_probe_runs_query(monkeypatch):
    """_get_conn() 探活用 SELECT 1 查询往返, 而非 autocommit 下不往返的 rollback()。"""
    fake_conn = MagicMock()
    monkeypatch.setattr(realtime, "_lazy_conn", fake_conn)
    monkeypatch.setattr(realtime, "_conn_tried", True)

    result = realtime._get_conn()

    assert result is fake_conn
    fake_conn.cursor.assert_called()  # 探活执行了 cursor 查询
    fake_conn.rollback.assert_not_called()  # 不再依赖 rollback 探活


def test_get_conn_reconnects_when_probe_fails(monkeypatch):
    """探活查询失败 (连接已断) → _get_conn() 重连。"""
    dead_conn = MagicMock()
    dead_conn.cursor.side_effect = RuntimeError("connection closed")
    fresh_conn = MagicMock()
    monkeypatch.setattr(realtime, "_lazy_conn", dead_conn)
    monkeypatch.setattr(realtime, "_conn_tried", True)
    monkeypatch.setattr(realtime, "_make_conn", lambda: fresh_conn)

    result = realtime._get_conn()

    assert result is fresh_conn
