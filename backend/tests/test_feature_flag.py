"""MVP 1.2 test — DBFeatureFlag (sqlite in-memory 隔离, 不碰 live PG)."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from backend.platform.config.feature_flag import (
    DBFeatureFlag,
    FlagExpired,
    FlagNotFound,
)


@pytest.fixture
def sqlite_conn_factory() -> tuple:
    """提供 sqlite in-memory + 预建 feature_flags 表.

    返回 (conn_factory, shared_conn) — shared_conn 是持有整个 in-memory
    DB 的唯一实例 (sqlite :memory: 关闭即销毁, 必须复用).
    """
    # :memory: 每个 connect() 独立, 用文件 URI + shared cache 共享.
    db = sqlite3.connect(":memory:")
    db.execute(
        """
        CREATE TABLE feature_flags (
            name TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT 0,
            removal_date TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.commit()

    class _SharedConnWrapper:
        """包装 shared conn, close() no-op 避免销毁 in-memory DB."""

        def __init__(self, inner: sqlite3.Connection):
            self._inner = inner

        def cursor(self):
            return self._inner.cursor()

        def commit(self):
            self._inner.commit()

        def close(self):
            pass  # keep alive for test fixture

    def factory():
        return _SharedConnWrapper(db)

    yield factory
    db.close()


def test_register_and_is_enabled(sqlite_conn_factory) -> None:
    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    future = (date.today() + timedelta(days=30)).isoformat()
    flag.register("test_on", default=True, removal_date=future, description="enable test")
    flag.register("test_off", default=False, removal_date=future, description="disable test")
    assert flag.is_enabled("test_on") is True
    assert flag.is_enabled("test_off") is False


def test_register_upsert(sqlite_conn_factory) -> None:
    """重复 register 同名 → UPSERT 覆盖."""
    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    future = (date.today() + timedelta(days=30)).isoformat()
    flag.register("upsert_flag", default=False, removal_date=future, description="v1")
    assert flag.is_enabled("upsert_flag") is False
    flag.register("upsert_flag", default=True, removal_date=future, description="v2")
    assert flag.is_enabled("upsert_flag") is True


def test_flag_not_found(sqlite_conn_factory) -> None:
    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    with pytest.raises(FlagNotFound, match="nonexistent"):
        flag.is_enabled("nonexistent")


def test_flag_expired(sqlite_conn_factory) -> None:
    """removal_date 过期 → raise FlagExpired (即使 register 时 future, 此处直接注入过期数据模拟)."""
    conn = sqlite_conn_factory()
    past = (date.today() - timedelta(days=1)).isoformat()
    cur = conn.cursor()
    try:
        # bypass register() validation 直接写入过期 flag 模拟 "本月内到期没清"
        cur.execute(
            "INSERT INTO feature_flags (name, enabled, removal_date, description) VALUES (?, ?, ?, ?)",
            ("expired_flag", True, past, "simulate expired"),
        )
    finally:
        cur.close()
    conn.commit()

    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    with pytest.raises(FlagExpired, match="expired_flag"):
        flag.is_enabled("expired_flag")


def test_register_rejects_past_removal_date(sqlite_conn_factory) -> None:
    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    past = (date.today() - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="removal_date"):
        flag.register("bad", default=False, removal_date=past, description="past")


def test_register_accepts_date_object(sqlite_conn_factory) -> None:
    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    future = date.today() + timedelta(days=30)
    flag.register("date_obj", default=True, removal_date=future, description="date")
    assert flag.is_enabled("date_obj") is True


def test_list_all_sorted(sqlite_conn_factory) -> None:
    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    future = (date.today() + timedelta(days=30)).isoformat()
    flag.register("zeta", default=True, removal_date=future, description="z")
    flag.register("alpha", default=False, removal_date=future, description="a")
    flag.register("mike", default=True, removal_date=future, description="m")
    flags = flag.list_all()
    assert [f["name"] for f in flags] == ["alpha", "mike", "zeta"]


def test_list_all_returns_typed_dict(sqlite_conn_factory) -> None:
    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    future = date.today() + timedelta(days=30)
    flag.register("only", default=True, removal_date=future, description="typed")
    (entry,) = flag.list_all()
    assert entry["name"] == "only"
    assert entry["enabled"] is True
    assert isinstance(entry["removal_date"], date)
    assert entry["description"] == "typed"


def test_is_enabled_ignores_context_mvp(sqlite_conn_factory) -> None:
    """MVP 1.2 不做 bucketing, context 参数忽略."""
    flag = DBFeatureFlag(sqlite_conn_factory, paramstyle="?")
    future = (date.today() + timedelta(days=30)).isoformat()
    flag.register("binary_only", default=True, removal_date=future, description="ignore ctx")
    assert flag.is_enabled("binary_only", context={"user": "x"}) is True
    assert flag.is_enabled("binary_only", context=None) is True
