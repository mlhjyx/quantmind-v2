"""Tests for ``_TrackedConnection`` counter accuracy (Session 40 LL-088 fix).

Background: MVP 3.1 真生产首日 (2026-04-27 10:10 起) celery worker 频繁告警
``sync连接数达到上限(15)，可能存在连接泄漏``. 实测 PG ``pg_stat_activity``
active+idle conns = 2, 非真 PG 资源泄漏 — counter logic 漏洞 (调用方未显式
``conn.close()``, GC ``__del__`` 关闭 socket 但 wrapper.close() 未调
→ ``_counted=True`` 永不 decrement).

Fix (Session 40, 2026-04-28): 加 ``__del__`` finalizer 兜底 GC 路径.

测试覆盖:
  - test_close_explicit_decrements: 显式 close() 减计数 (regression baseline)
  - test_close_idempotent_no_double_decrement: 重复 close() 不双减 (regression baseline)
  - test_del_decrements_when_not_explicitly_closed: GC __del__ 兜底减计数 (Session 40 新增)
  - test_del_no_op_after_explicit_close: 已 close 后 __del__ 不重复减 (Session 40 新增)
  - test_get_sync_conn_increments: get_sync_conn 增计数 (regression baseline)
  - test_attribute_passthrough: __getattr__ / __setattr__ 透传 (regression baseline)
"""
from __future__ import annotations

import gc
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# backend/ sys.path hack 跟现有 backend/tests 风格一致
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture
def db_module():
    """Reset _active_count between tests (module-level state)."""
    from app.services import db  # noqa: PLC0415

    original = db._active_count
    db._active_count = 0
    yield db
    db._active_count = original


# ─── close() explicit path ────────────────────────────────────


class TestCloseExplicit:
    def test_close_explicit_decrements(self, db_module) -> None:
        """显式 close() decrement counter."""
        mock_conn = MagicMock()
        wrapper = db_module._TrackedConnection(mock_conn)
        db_module._active_count = 1  # simulate get_sync_conn already incremented
        wrapper.close()
        assert db_module._active_count == 0
        mock_conn.close.assert_called_once()

    def test_close_idempotent_no_double_decrement(self, db_module) -> None:
        """重复 close() 不双减 (regression baseline, _counted gate)."""
        mock_conn = MagicMock()
        wrapper = db_module._TrackedConnection(mock_conn)
        db_module._active_count = 1
        wrapper.close()
        wrapper.close()
        assert db_module._active_count == 0  # not -1


# ─── __del__ GC finalizer (Session 40 LL-088) ─────────────────


class TestDelFinalizer:
    def test_del_decrements_when_not_explicitly_closed(self, db_module) -> None:
        """Session 40 新增: GC __del__ 兜底 decrement counter (调用方未显式 close).

        触发 __del__ 通过 del + gc.collect() (CPython refcount + cyclic GC).
        """
        mock_conn = MagicMock()
        wrapper = db_module._TrackedConnection(mock_conn)
        db_module._active_count = 1
        # 模拟调用方未显式 close, GC 处理
        del wrapper
        gc.collect()
        assert db_module._active_count == 0

    def test_del_no_op_after_explicit_close(self, db_module) -> None:
        """已 close 后 __del__ 不重复减 (_counted=False gate)."""
        mock_conn = MagicMock()
        wrapper = db_module._TrackedConnection(mock_conn)
        db_module._active_count = 1
        wrapper.close()  # _counted=False
        assert db_module._active_count == 0
        del wrapper
        gc.collect()
        assert db_module._active_count == 0  # 不变 (无双减)


# ─── get_sync_conn integration ─────────────────────────────────


class TestGetSyncConn:
    def test_get_sync_conn_increments(self, db_module) -> None:
        """get_sync_conn 增计数 (regression baseline)."""
        with patch("psycopg2.connect", return_value=MagicMock()):
            assert db_module._active_count == 0
            conn = db_module.get_sync_conn()
            assert db_module._active_count == 1
            conn.close()
            assert db_module._active_count == 0

    def test_get_sync_conn_via_gc_path(self, db_module) -> None:
        """Session 40 LL-088 场景重现: get_sync_conn 后调用方未 close, GC 兜底."""
        with patch("psycopg2.connect", return_value=MagicMock()):
            assert db_module._active_count == 0
            conn = db_module.get_sync_conn()
            assert db_module._active_count == 1
            del conn
            gc.collect()
            assert db_module._active_count == 0  # __del__ 兜底


# ─── Attribute passthrough (regression baseline) ──────────────


class TestAttributePassthrough:
    def test_getattr_passthrough(self, db_module) -> None:
        """__getattr__ 透传到底层 psycopg2 conn."""
        mock_conn = MagicMock()
        mock_conn.encoding = "UTF8"
        wrapper = db_module._TrackedConnection(mock_conn)
        assert wrapper.encoding == "UTF8"

    def test_setattr_passthrough(self, db_module) -> None:
        """__setattr__ 透传 (e.g., conn.autocommit=True)."""
        mock_conn = MagicMock()
        wrapper = db_module._TrackedConnection(mock_conn)
        wrapper.autocommit = True
        # MagicMock spec 不阻止 setattr, 验 mock_conn 上 attribute 设置
        assert mock_conn.autocommit is True

    def test_setattr_internal_slots_not_passthrough(self, db_module) -> None:
        """_conn / _counted 内部 slot 不透传到底层 conn."""
        mock_conn = MagicMock()
        wrapper = db_module._TrackedConnection(mock_conn)
        # _counted 应 wrapper-level set, 不透传
        wrapper._counted = False
        # mock_conn._counted 不该被 set (但 MagicMock 会 auto-create attr, 仅验 wrapper)
        assert wrapper._counted is False
