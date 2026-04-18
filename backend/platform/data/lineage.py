"""MVP 2.2 Sub2 — Data Lineage (U3) Platform primitive.

跨表血缘 (factor_values / signals / orders / backtest_run 未来) 统一存储.
本模块提供 3 个 dataclass (LineageRef / CodeRef / Lineage) + 3 个 DB API
(write_lineage / get_lineage / get_lineage_for_row).

设计要点:
  - Lineage 序列化为 JSONB (单行 data_lineage.lineage_data), 不拆字段
  - `schema_version=1` 预留未来 Lineage dataclass 结构演进的 upgrader hook
  - Platform primitive: **bypass DataPipeline** 避免 ingest(lineage=...) 递归
    (类比 factor_compute_version 不走 DataPipeline, 铁律 17 Platform 例外)
  - 驱动无关: `paramstyle` 参数 "%s" (psycopg2) / "?" (sqlite) 统一占位符
  - `Json` wrap (psycopg2) 与 `json.dumps` 字符串 (sqlite) 统一走 json.dumps payload,
    PG JSONB 列自动把 text 解析为 JSONB, sqlite TEXT 列直存
  - Commit 由调用方管 (铁律 32 Service 不 commit)

关联铁律:
  - 17: DataPipeline 入库 — 本模块是 Platform 基础设施原语, 例外允许
  - 23: 每个任务独立可执行 — 本模块不依赖 MVP 2.1 DataSource concrete
  - 24: 设计文档按抽象层级聚焦 — docs/mvp/MVP_2_2_data_lineage.md §D2
  - 30: 缓存一致性 — lineage 与 cache 协同推 MVP 3.3 Event Sourcing
  - 36: 代码变更前必核 precondition — factor_compute_version 已存, 不改表结构

Usage (典型 FactorCompute 集成):
    from backend.platform.data.lineage import Lineage, LineageRef, CodeRef, write_lineage

    lineage = Lineage(
        inputs=[LineageRef(table="klines_daily", pk_values={"code": "...", "trade_date": ...})],
        code=CodeRef(git_commit="abc...", module="backend.engines.factor_engine"),
        params={"factor": "turnover_mean_20", "version": 1},
    )
    pipeline.ingest(df, FACTOR_VALUES, lineage=lineage)   # DataPipeline 自动补 outputs + write_lineage
"""
from __future__ import annotations

import json
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

LINEAGE_SCHEMA_VERSION = 1


# ---------- 3 dataclass (frozen 不可变契约) ----------


@dataclass(frozen=True)
class LineageRef:
    """单一源或输出数据引用 (跨表).

    Args:
      table: 表名 (e.g. "klines_daily", "factor_values")
      pk_values: 主键字典 (e.g. {"code": "000001.SZ", "trade_date": "2026-04-18"})
      version_hash: 源数据 md5 (可选, Wave 3 Event Sourcing 再落)
    """

    table: str
    pk_values: dict[str, Any]
    version_hash: str | None = None


@dataclass(frozen=True)
class CodeRef:
    """代码版本引用."""

    git_commit: str
    module: str
    function: str | None = None


@dataclass(frozen=True)
class Lineage:
    """统一血缘记录 (存 data_lineage.lineage_data JSONB)."""

    lineage_id: _uuid.UUID = field(default_factory=_uuid.uuid4)
    inputs: list[LineageRef] = field(default_factory=list)
    code: CodeRef | None = None
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_lineage_ids: list[_uuid.UUID] = field(default_factory=list)
    outputs: list[LineageRef] = field(default_factory=list)
    schema_version: int = LINEAGE_SCHEMA_VERSION


# ---------- 序列化 helpers ----------


def _to_jsonable(obj: Any) -> Any:
    """递归把 UUID / datetime / date 转成 JSON 安全类型."""
    if isinstance(obj, _uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    # date (非 datetime) 也走 isoformat
    if hasattr(obj, "isoformat") and not isinstance(obj, (str, bytes)):
        try:
            return obj.isoformat()
        except TypeError:
            pass
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    return obj


def lineage_to_jsonable(lineage: Lineage) -> dict[str, Any]:
    """Lineage → JSON-safe dict (for JSONB storage)."""
    return _to_jsonable(asdict(lineage))


def lineage_from_jsonable(data: dict[str, Any]) -> Lineage:
    """JSON-safe dict → Lineage (roundtrip inverse).

    未来 schema_version 不匹配时走 upgrader chain (目前仅 v1).
    """
    sv = int(data.get("schema_version", 1))
    if sv != LINEAGE_SCHEMA_VERSION:
        logger.warning(
            "lineage schema_version mismatch: got=%d expected=%d", sv, LINEAGE_SCHEMA_VERSION
        )

    inputs = [LineageRef(**r) for r in data.get("inputs", []) or []]
    outputs = [LineageRef(**r) for r in data.get("outputs", []) or []]
    code_d = data.get("code")
    code = CodeRef(**code_d) if code_d else None

    ts_raw = data.get("timestamp")
    if isinstance(ts_raw, str):
        ts = datetime.fromisoformat(ts_raw)
    elif isinstance(ts_raw, datetime):
        ts = ts_raw
    else:
        ts = datetime.utcnow()

    lid_raw = data.get("lineage_id")
    if isinstance(lid_raw, _uuid.UUID):
        lid = lid_raw
    elif isinstance(lid_raw, str):
        lid = _uuid.UUID(lid_raw)
    else:
        lid = _uuid.uuid4()

    parents_raw = data.get("parent_lineage_ids") or []
    parents = [_uuid.UUID(x) if isinstance(x, str) else x for x in parents_raw]

    return Lineage(
        lineage_id=lid,
        inputs=inputs,
        code=code,
        params=dict(data.get("params") or {}),
        timestamp=ts,
        parent_lineage_ids=parents,
        outputs=outputs,
        schema_version=sv,
    )


# ---------- DB API (driver-agnostic via paramstyle) ----------


def _ph(paramstyle: str) -> str:
    """Placeholder: %s (psycopg2) / ? (sqlite)."""
    return paramstyle


def write_lineage(lineage: Lineage, conn, *, paramstyle: str = "%s") -> _uuid.UUID:
    """落 data_lineage 表, 返回 lineage_id.

    Platform primitive: bypass DataPipeline, 避免 ingest 递归.
    Commit 由调用方管理 (铁律 32).
    """
    payload = json.dumps(lineage_to_jsonable(lineage), ensure_ascii=False)
    ph = _ph(paramstyle)
    # ON CONFLICT 仅 PG 支持; sqlite 用 INSERT OR IGNORE
    if paramstyle == "%s":
        sql = (
            f"INSERT INTO data_lineage (lineage_id, lineage_data) VALUES ({ph}, {ph}) "
            f"ON CONFLICT (lineage_id) DO NOTHING"
        )
    else:
        sql = (
            f"INSERT OR IGNORE INTO data_lineage (lineage_id, lineage_data) "
            f"VALUES ({ph}, {ph})"
        )
    cur = conn.cursor()
    try:
        cur.execute(sql, (str(lineage.lineage_id), payload))
    finally:
        if hasattr(cur, "close"):
            cur.close()
    return lineage.lineage_id


def get_lineage(lineage_id: _uuid.UUID, conn, *, paramstyle: str = "%s") -> Lineage | None:
    """按 lineage_id 反查 Lineage, 不存在返 None."""
    ph = _ph(paramstyle)
    sql = f"SELECT lineage_data FROM data_lineage WHERE lineage_id = {ph}"
    cur = conn.cursor()
    try:
        cur.execute(sql, (str(lineage_id),))
        row = cur.fetchone()
    finally:
        if hasattr(cur, "close"):
            cur.close()
    if row is None:
        return None
    raw = row[0]
    # PG psycopg2 with JSONB returns dict; sqlite TEXT returns str
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    return lineage_from_jsonable(data)


def get_lineage_for_row(
    table: str, pk: dict[str, Any], conn, *, paramstyle: str = "%s"
) -> list[Lineage]:
    """反查写入指定 (table, pk) 的所有 Lineage.

    Args:
      table: 目标表名
      pk: 主键字典 (所有 pk_values 必须匹配)
      conn: DB connection (PG 生产 / sqlite 测试)
      paramstyle: "%s" (PG) / "?" (sqlite)

    Returns:
      list[Lineage], 按 created_at DESC 排列, 空匹配返 [].

    Implementation:
      - PG: JSONB `@>` containment + GIN 索引 (idx_lineage_jsonb_gin)
      - sqlite: 退化为全扫 + Python 侧过滤 (测试 only, 不上生产)
    """
    jsonable_pk = _to_jsonable(pk)
    ph = _ph(paramstyle)

    if paramstyle == "%s":
        # PG 路径: JSONB containment via @>
        query_doc = {"outputs": [{"table": table, "pk_values": jsonable_pk}]}
        payload = json.dumps(query_doc, ensure_ascii=False)
        sql = (
            f"SELECT lineage_data FROM data_lineage WHERE lineage_data @> {ph}::jsonb "
            f"ORDER BY created_at DESC"
        )
        cur = conn.cursor()
        try:
            cur.execute(sql, (payload,))
            rows = cur.fetchall()
        finally:
            if hasattr(cur, "close"):
                cur.close()
    else:
        # sqlite 测试路径: 全扫 + Python 过滤 (无 GIN)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT lineage_data FROM data_lineage ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
        finally:
            if hasattr(cur, "close"):
                cur.close()

    results: list[Lineage] = []
    for (raw,) in rows:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if paramstyle != "%s":
            # sqlite 侧做 containment 模拟
            outputs = data.get("outputs") or []
            if not any(
                o.get("table") == table
                and all(o.get("pk_values", {}).get(k) == v for k, v in jsonable_pk.items())
                for o in outputs
            ):
                continue
        results.append(lineage_from_jsonable(data))
    return results
