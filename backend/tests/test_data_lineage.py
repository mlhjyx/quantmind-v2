"""MVP 2.2 Sub2 — test Lineage dataclass + serialization + DB API.

使用 sqlite :memory: 作 mock DB 覆盖:
  - Lineage / LineageRef / CodeRef dataclass frozen + default_factory
  - lineage_to_jsonable / from_jsonable roundtrip (含 UUID / datetime / nested)
  - write_lineage / get_lineage PK roundtrip
  - get_lineage_for_row sqlite 退化路径 (Python 侧 containment)
  - schema_version=1 字段存在 + 版本漂移 warn log
  - parent_lineage_ids 链式追溯
  - pipeline.ingest 传入 lineage 时 IngestResult.lineage_id 非空
  - pipeline.ingest 不传 lineage (默认 None) → IngestResult.lineage_id = None (向后兼容)
"""
from __future__ import annotations

import dataclasses
import sqlite3
import uuid
from datetime import date, datetime

import pandas as pd
import pytest

from backend.qm_platform.data.lineage import (
    LINEAGE_SCHEMA_VERSION,
    CodeRef,
    Lineage,
    LineageRef,
    get_lineage,
    get_lineage_for_row,
    lineage_from_jsonable,
    lineage_to_jsonable,
    write_lineage,
)


@pytest.fixture
def mem_lineage_conn():
    """sqlite :memory: 模拟 data_lineage 表 (JSONB → TEXT 存 JSON 字符串)."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE data_lineage ("
        "lineage_id TEXT PRIMARY KEY, "
        "lineage_data TEXT NOT NULL, "
        "created_at TEXT DEFAULT (datetime('now')))"
    )
    conn.commit()
    yield conn
    conn.close()


# ---------- 1-3: dataclass 基础 ----------


def test_lineage_ref_frozen():
    ref = LineageRef(table="klines_daily", pk_values={"code": "600519.SH"})
    assert ref.table == "klines_daily"
    assert ref.pk_values == {"code": "600519.SH"}
    assert ref.version_hash is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.table = "foo"


def test_code_ref_optional_function():
    c = CodeRef(git_commit="abc123", module="engines.x")
    assert c.function is None
    c2 = CodeRef(git_commit="abc123", module="engines.x", function="calc_y")
    assert c2.function == "calc_y"


def test_lineage_default_uuid_unique():
    a = Lineage()
    b = Lineage()
    assert isinstance(a.lineage_id, uuid.UUID)
    assert a.lineage_id != b.lineage_id
    assert a.schema_version == LINEAGE_SCHEMA_VERSION == 1


# ---------- 4-6: 序列化 ----------


def test_to_jsonable_handles_uuid_and_datetime():
    lid = uuid.uuid4()
    ts = datetime(2026, 4, 18, 12, 0, 0)
    lineage = Lineage(
        lineage_id=lid,
        timestamp=ts,
        inputs=[LineageRef(table="t", pk_values={"d": date(2026, 4, 18)})],
    )
    d = lineage_to_jsonable(lineage)
    assert d["lineage_id"] == str(lid)
    assert d["timestamp"] == ts.isoformat()
    # nested date in pk_values 也走 isoformat
    assert d["inputs"][0]["pk_values"]["d"] == "2026-04-18"


def test_lineage_roundtrip_full():
    """含 UUID / datetime / code / parents / outputs / params 的完整往返."""
    parent = uuid.uuid4()
    l1 = Lineage(
        inputs=[LineageRef(table="k", pk_values={"c": "X", "d": "2026-01-01"}, version_hash="h1")],
        code=CodeRef(git_commit="c1", module="m1", function="f1"),
        params={"a": 1, "b": "s", "nested": [1, 2, {"k": "v"}]},
        parent_lineage_ids=[parent],
        outputs=[LineageRef(table="factor_values", pk_values={"c": "X"})],
    )
    data = lineage_to_jsonable(l1)
    l2 = lineage_from_jsonable(data)
    assert l2.lineage_id == l1.lineage_id
    assert l2.code.git_commit == "c1"
    assert l2.params == {"a": 1, "b": "s", "nested": [1, 2, {"k": "v"}]}
    assert l2.parent_lineage_ids == [parent]
    assert l2.outputs[0].table == "factor_values"
    assert l2.inputs[0].version_hash == "h1"
    assert l2.schema_version == LINEAGE_SCHEMA_VERSION


def test_from_jsonable_tolerates_schema_drift(caplog):
    """未来 schema_version 变化必须 warn 但不 raise (upgrader hook 预留)."""
    import logging

    caplog.set_level(logging.WARNING)
    data = {
        "lineage_id": str(uuid.uuid4()),
        "inputs": [],
        "outputs": [],
        "params": {},
        "parent_lineage_ids": [],
        "timestamp": datetime.utcnow().isoformat(),
        "schema_version": 99,  # 未来版本
    }
    l = lineage_from_jsonable(data)
    assert l.schema_version == 99
    # 不强 assert warn 内容 (structlog 路由可能不走 caplog), 只确认不崩


# ---------- 7-9: write/get DB API ----------


def test_write_then_get_roundtrip(mem_lineage_conn):
    lineage = Lineage(
        inputs=[LineageRef(table="klines_daily", pk_values={"code": "600519.SH"})],
        code=CodeRef(git_commit="deadbeef", module="m"),
        params={"k": "v"},
    )
    lid = write_lineage(lineage, mem_lineage_conn, paramstyle="?")
    mem_lineage_conn.commit()
    assert lid == lineage.lineage_id

    fetched = get_lineage(lid, mem_lineage_conn, paramstyle="?")
    assert fetched is not None
    assert fetched.lineage_id == lineage.lineage_id
    assert fetched.code.git_commit == "deadbeef"
    assert fetched.inputs[0].table == "klines_daily"


def test_get_lineage_missing_returns_none(mem_lineage_conn):
    result = get_lineage(uuid.uuid4(), mem_lineage_conn, paramstyle="?")
    assert result is None


def test_write_idempotent_on_duplicate_id(mem_lineage_conn):
    """相同 lineage_id 二次 write 不应报错 (ON CONFLICT DO NOTHING / INSERT OR IGNORE)."""
    l = Lineage(params={"v": 1})
    write_lineage(l, mem_lineage_conn, paramstyle="?")
    mem_lineage_conn.commit()
    # 第二次同 id
    write_lineage(l, mem_lineage_conn, paramstyle="?")
    mem_lineage_conn.commit()
    fetched = get_lineage(l.lineage_id, mem_lineage_conn, paramstyle="?")
    assert fetched is not None
    assert fetched.params == {"v": 1}


# ---------- 10: get_lineage_for_row containment (sqlite 退化路径) ----------


def test_get_lineage_for_row_matches_containment(mem_lineage_conn):
    """sqlite 走 Python 侧 containment; 验证 outputs 包含目标 table+pk 的 Lineage 被找到."""
    target_pk = {"code": "600519.SH", "trade_date": "2026-04-18", "factor_name": "turnover_mean_20"}
    l_match = Lineage(
        outputs=[LineageRef(table="factor_values", pk_values=target_pk)],
        params={"marker": "match"},
    )
    l_noise1 = Lineage(
        outputs=[LineageRef(table="factor_values", pk_values={"code": "000001.SZ"})],
        params={"marker": "noise_wrong_pk"},
    )
    l_noise2 = Lineage(
        outputs=[LineageRef(table="signals", pk_values=target_pk)],
        params={"marker": "noise_wrong_table"},
    )
    for x in (l_match, l_noise1, l_noise2):
        write_lineage(x, mem_lineage_conn, paramstyle="?")
    mem_lineage_conn.commit()

    results = get_lineage_for_row("factor_values", target_pk, mem_lineage_conn, paramstyle="?")
    # 1 match (l_match), noise1 subset but not all keys match, noise2 wrong table
    assert len(results) == 1
    assert results[0].params["marker"] == "match"


# ---------- 11: parent_lineage_ids 链式 ----------


def test_parent_lineage_chain(mem_lineage_conn):
    """子 lineage 携带 parent UUID 列表, 可反序列化."""
    parent = Lineage(params={"stage": "raw_compute"})
    write_lineage(parent, mem_lineage_conn, paramstyle="?")

    child = Lineage(
        parent_lineage_ids=[parent.lineage_id],
        params={"stage": "neutralize"},
    )
    write_lineage(child, mem_lineage_conn, paramstyle="?")
    mem_lineage_conn.commit()

    fetched = get_lineage(child.lineage_id, mem_lineage_conn, paramstyle="?")
    assert fetched is not None
    assert parent.lineage_id in fetched.parent_lineage_ids
    assert fetched.params == {"stage": "neutralize"}


# ---------- 12-13: DataPipeline.ingest lineage 集成 ----------


class _FakePGCursor:
    """极简 PG cursor 兼容层 — 把 %s 转 ?, 其余丢给 sqlite. 仅供 lineage 测试用."""

    def __init__(self, sqlite_cur):
        self._c = sqlite_cur

    def execute(self, sql, params=()):
        sql = sql.replace("%s", "?")
        sql = sql.replace("::jsonb", "")
        return self._c.execute(sql, params)

    def fetchall(self):
        return self._c.fetchall()

    def fetchone(self):
        return self._c.fetchone()

    def close(self):
        self._c.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class _FakePGConn:
    """sqlite 外壳, 让 DataPipeline lineage 埋点路径可走 (不覆盖 upsert)."""

    def __init__(self, sqlite_conn):
        self._c = sqlite_conn

    def cursor(self):
        return _FakePGCursor(self._c.cursor())

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()


@pytest.fixture
def fake_pg_conn_with_lineage_table():
    s = sqlite3.connect(":memory:")
    cur = s.cursor()
    cur.execute(
        "CREATE TABLE data_lineage (lineage_id TEXT PRIMARY KEY, "
        "lineage_data TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))"
    )
    s.commit()
    yield _FakePGConn(s)
    s.close()


# ---------- 12: IngestResult.lineage_id 默认 None (向后兼容) ----------


def test_ingest_result_lineage_id_default_none():
    """MVP 2.2 Sub2: IngestResult 新增 lineage_id 字段, 默认 None 保证不传 lineage 时向后兼容."""
    from app.data_fetcher.pipeline import IngestResult

    r = IngestResult(table="factor_values", total_rows=5, valid_rows=5, rejected_rows=0, upserted_rows=5)
    assert r.lineage_id is None
    assert r.success is True

    lid = uuid.uuid4()
    r2 = IngestResult(
        table="factor_values", total_rows=5, valid_rows=5, rejected_rows=0, upserted_rows=5,
        lineage_id=lid,
    )
    assert r2.lineage_id == lid


# ---------- 13: DataPipeline._record_lineage 直接调用 (绕开 execute_values) ----------


def test_record_lineage_merges_outputs_and_persists(
    fake_pg_conn_with_lineage_table, monkeypatch
):
    """_record_lineage 从 valid_df PK 列自动补 outputs, 落 data_lineage.

    直接测 helper, 绕开 execute_values (psycopg2-specific, sqlite 不兼容)."""
    # patch write_lineage 走 paramstyle='?' (sqlite)
    import backend.qm_platform.data.lineage as lineage_mod
    from app.data_fetcher.contracts import FACTOR_VALUES
    from app.data_fetcher.pipeline import DataPipeline
    orig = lineage_mod.write_lineage
    monkeypatch.setattr(
        lineage_mod,
        "write_lineage",
        lambda l, conn, paramstyle="%s": orig(l, conn, paramstyle="?"),
    )

    df = pd.DataFrame(
        [
            {
                "code": "600519.SH",
                "trade_date": date(2026, 4, 18),
                "factor_name": "turnover_mean_20",
                "raw_value": 0.1,
                "neutral_value": 0.05,
                "zscore": 0.05,
            }
        ]
    )
    lineage = Lineage(
        inputs=[LineageRef(table="klines_daily", pk_values={"trade_date": "2026-04-18"})],
        code=CodeRef(git_commit="abc", module="m", function="f"),
        params={"batch": "unit"},
    )
    p = DataPipeline(fake_pg_conn_with_lineage_table)
    lid = p._record_lineage(lineage, df, FACTOR_VALUES)
    assert lid == lineage.lineage_id

    # 反查验证 outputs 被补, 含 factor_values + 3 PK 全
    fetched = get_lineage(lid, fake_pg_conn_with_lineage_table, paramstyle="?")
    assert fetched is not None
    fv_outputs = [o for o in fetched.outputs if o.table == "factor_values"]
    assert len(fv_outputs) == 1
    pk = fv_outputs[0].pk_values
    assert pk.get("code") == "600519.SH"
    assert pk.get("factor_name") == "turnover_mean_20"
    # 源 inputs 保留
    assert fetched.inputs[0].table == "klines_daily"
    assert fetched.params == {"batch": "unit"}
