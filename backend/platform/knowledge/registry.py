"""MVP 1.4 Framework #10 Knowledge Registry — 3 concrete 实现 (PG + sqlite 双路径).

DBExperimentRegistry  — platform_experiments 表 + API (register / complete / search_similar)
DBFailedDirectionDB   — failed_directions 表 + API (add / check_similar / list_all)
DBADRRegistry         — adr_records 表 + API (register / supersede / get_by_id / list_by_ironlaw)

依赖注入保 MVP 1.1 Platform 严格隔离 (Platform 不 import `backend.app/engines/data`):
  - `conn_factory: Callable[[], DBConnection]` — 每次调用返回新连接
  - `paramstyle: str` — "%s" (psycopg2) / "?" (sqlite 测试)

关联铁律:
  - 22: 文档跟随代码 (ADR 双源, md 为权威 DB 为索引)
  - 33: 禁 silent failure (异常向上 raise)
  - 38: Blueprint 真相源 (ADRRegistry 补充细粒度决策)
  - 40: 测试债务不增长

Usage:
    from backend.app.services.db import get_sync_conn
    from .registry import (
        DBExperimentRegistry, DBFailedDirectionDB, DBADRRegistry,
    )

    exp = DBExperimentRegistry(conn_factory=get_sync_conn)
    fd = DBFailedDirectionDB(conn_factory=get_sync_conn)
    adr = DBADRRegistry(conn_factory=get_sync_conn)
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID, uuid4

from .interface import (
    ADRRecord,
    ADRRegistry,
    ExperimentRecord,
    ExperimentRegistry,
    FailedDirectionDB,
    FailedDirectionRecord,
)

# ---------- 错误类型 ----------


class KnowledgeError(RuntimeError):
    """Platform Knowledge 基类异常."""


class ExperimentNotFound(KnowledgeError):  # noqa: N818 — KnowledgeError 含 Error 后缀, 子类走语义名
    """experiment_id 在 platform_experiments 中不存在."""


class ADRNotFound(KnowledgeError):  # noqa: N818
    """adr_id 在 adr_records 中不存在."""


class WriteNotConfigured(KnowledgeError):  # noqa: N818
    """未注入 conn_factory, 无法执行写路径."""


# ---------- DB 鸭子类型 ----------


class _DBConnection(Protocol):
    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


# ---------- 辅助: 关键词提取 (LIKE search 用) ----------


_KEYWORD_RE = re.compile(r"\w+", re.UNICODE)


def _extract_keywords(text: str, max_k: int = 5) -> list[str]:
    """提取 LIKE 搜索关键词 — 分词 + 去重 + 长度 > 2.

    用于 search_similar / check_similar. MVP 1.4 简路径 (LIKE + ILIKE),
    Wave 2+ 若记录超 1000 行考虑升级 pg_trgm / pgvector.
    """
    tokens = _KEYWORD_RE.findall(text or "")
    # 保序去重 + 过滤短词
    seen: dict[str, None] = {}
    for t in tokens:
        if len(t) > 2 and t not in seen:
            seen[t] = None
            if len(seen) >= max_k:
                break
    return list(seen.keys())


def _json_dumps(value: Any) -> str:
    """jsonb 列: psycopg2 + sqlite 都接受 str, 手动 dump 避免 adapter 依赖."""
    import json

    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    """jsonb / text: 兼容 psycopg2 (直接 dict/list) / sqlite (str)."""
    import json

    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value  # psycopg2 自动解 jsonb


def _parse_tags(value: Any) -> list[str]:
    """text[] / JSON list 兼容解析."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        # sqlite TEXT: 存 JSON 字符串
        try:
            loaded = _json_loads(value)
            return [str(x) for x in loaded] if isinstance(loaded, list) else []
        except (ValueError, TypeError):
            return []
    return []


def _parse_ironlaws(value: Any) -> list[int]:
    """integer[] / JSON list 兼容解析."""
    if value is None:
        return []
    if isinstance(value, list):
        return [int(x) for x in value]
    if isinstance(value, str):
        try:
            loaded = _json_loads(value)
            return [int(x) for x in loaded] if isinstance(loaded, list) else []
        except (ValueError, TypeError):
            return []
    return []


# ==================================================================
# DBExperimentRegistry
# ==================================================================


class DBExperimentRegistry(ExperimentRegistry):
    """实验登记 concrete (MVP 1.4).

    表: platform_experiments (MVP 1.4 migration, 不是老 `experiments`).

    Args:
      conn_factory: 返回 DB 连接的 callable.
      paramstyle: "%s" (psycopg2) / "?" (sqlite 测试).
    """

    def __init__(
        self,
        conn_factory: Callable[[], _DBConnection] | None = None,
        *,
        paramstyle: str = "%s",
    ) -> None:
        self._conn_factory = conn_factory
        self._ph = paramstyle

    def _require_writer(self) -> Callable[[], _DBConnection]:
        if self._conn_factory is None:
            raise WriteNotConfigured(
                "DBExperimentRegistry 需要 conn_factory 注入. "
                "构造时传 `conn_factory=get_sync_conn`."
            )
        return self._conn_factory

    # ---------- register ----------

    def register(self, record: ExperimentRecord) -> UUID:
        """登记新实验. 返 experiment_id UUID.

        若 record.experiment_id 是 ``UUID(int=0)`` 或全零 UUID, 自动生成新 UUID.
        否则用 record 的 UUID 入库 (允许调用方预生成).

        Raises:
          WriteNotConfigured: conn_factory 未注入.
        """
        factory = self._require_writer()
        exp_id = record.experiment_id if int(record.experiment_id) != 0 else uuid4()

        # 空 started_at / None 走 DEFAULT NOW() — 否则 TIMESTAMPTZ 拒空字符串
        has_started = bool(record.started_at)
        conn = factory()
        try:
            with conn.cursor() as cur:
                if has_started:
                    cur.execute(
                        f"""
                        INSERT INTO platform_experiments
                            (id, hypothesis, status, author, started_at, completed_at,
                             verdict, artifacts, tags)
                        VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph},
                                {self._ph}, {self._ph}, {self._ph}, {self._ph})
                        """,
                        (
                            str(exp_id),
                            record.hypothesis,
                            record.status or "running",
                            record.author,
                            record.started_at,
                            record.completed_at,
                            record.verdict,
                            _json_dumps(record.artifacts or {}),
                            list(record.tags or []),
                        ),
                    )
                else:
                    # 省略 started_at 让 DEFAULT NOW() 生效
                    cur.execute(
                        f"""
                        INSERT INTO platform_experiments
                            (id, hypothesis, status, author, completed_at,
                             verdict, artifacts, tags)
                        VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph},
                                {self._ph}, {self._ph}, {self._ph})
                        """,
                        (
                            str(exp_id),
                            record.hypothesis,
                            record.status or "running",
                            record.author,
                            record.completed_at,
                            record.verdict,
                            _json_dumps(record.artifacts or {}),
                            list(record.tags or []),
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
        return exp_id

    # ---------- complete ----------

    def complete(
        self,
        experiment_id: UUID,
        verdict: str,
        status: str,
        artifacts: dict[str, str],
    ) -> None:
        """标记实验完成.

        Raises:
          ExperimentNotFound: experiment_id 未注册.
          ValueError: status 非法 (非 success/failed/inconclusive).
          WriteNotConfigured: conn_factory 未注入.
        """
        if status not in ("success", "failed", "inconclusive"):
            raise ValueError(
                f"status 必须是 success/failed/inconclusive, 现: {status!r}"
            )
        factory = self._require_writer()
        conn = factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE platform_experiments
                       SET status={self._ph},
                           verdict={self._ph},
                           artifacts={self._ph},
                           completed_at=NOW()
                     WHERE id={self._ph}
                    """,
                    (status, verdict, _json_dumps(artifacts or {}), str(experiment_id)),
                )
                if cur.rowcount == 0:
                    raise ExperimentNotFound(f"{experiment_id} 未在 platform_experiments")
            conn.commit()
        finally:
            conn.close()

    # ---------- search_similar ----------

    def search_similar(self, hypothesis: str, k: int = 5) -> list[ExperimentRecord]:
        """LIKE + 关键词搜相似实验.

        MVP 1.4 简路径: ILIKE 任一关键词命中即收录, started_at DESC 排序.
        Wave 2+ 升级 pg_trgm / pgvector.

        Returns:
          list[ExperimentRecord] 最多 k 条 (按 started_at DESC).
        """
        factory = self._require_writer()
        keywords = _extract_keywords(hypothesis, max_k=5)
        conn = factory()
        try:
            with conn.cursor() as cur:
                base_cols = (
                    "id, hypothesis, status, author, started_at, completed_at, "
                    "verdict, artifacts, tags"
                )
                if not keywords:
                    # 空 hypothesis 返最新 k 条
                    sql = (
                        f"SELECT {base_cols} FROM platform_experiments "
                        f"ORDER BY started_at DESC LIMIT {self._ph}"
                    )
                    cur.execute(sql, (k,))
                else:
                    conditions = " OR ".join(
                        [f"hypothesis ILIKE {self._ph}" for _ in keywords]
                    )
                    sql = (
                        f"SELECT {base_cols} FROM platform_experiments "
                        f"WHERE {conditions} "
                        f"ORDER BY started_at DESC LIMIT {self._ph}"
                    )
                    params = [f"%{w}%" for w in keywords] + [k]
                    cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_experiment(row) for row in rows]


def _row_to_experiment(row: tuple) -> ExperimentRecord:
    """PG/sqlite 行 → ExperimentRecord."""
    (exp_id, hypothesis, status, author, started_at, completed_at,
     verdict, artifacts, tags) = row

    # UUID 兼容 (PG 返 UUID, sqlite 返 str)
    eid = exp_id if isinstance(exp_id, UUID) else UUID(str(exp_id))

    return ExperimentRecord(
        experiment_id=eid,
        hypothesis=str(hypothesis),
        status=str(status),
        author=str(author),
        started_at=str(started_at) if started_at else "",
        completed_at=str(completed_at) if completed_at else None,
        verdict=verdict,
        artifacts=_json_loads(artifacts) or {},
        tags=_parse_tags(tags),
    )


# ==================================================================
# DBFailedDirectionDB
# ==================================================================


class DBFailedDirectionDB(FailedDirectionDB):
    """失败方向库 concrete (MVP 1.4).

    表: failed_directions. direction 是 UNIQUE → ON CONFLICT DO UPDATE 幂等
    (保 migration 可重跑).
    """

    def __init__(
        self,
        conn_factory: Callable[[], _DBConnection] | None = None,
        *,
        paramstyle: str = "%s",
    ) -> None:
        self._conn_factory = conn_factory
        self._ph = paramstyle

    def _require_writer(self) -> Callable[[], _DBConnection]:
        if self._conn_factory is None:
            raise WriteNotConfigured("DBFailedDirectionDB 需要 conn_factory 注入.")
        return self._conn_factory

    # ---------- add (UPSERT) ----------

    def add(self, record: FailedDirectionRecord) -> None:
        """添加失败方向. direction 冲突 → UPDATE reason/evidence/severity (幂等).

        可选字段: source / tags — 从 record.evidence 分离 (interface 无, 用扩展).
        这里仅用 interface 字段, source/tags 在 add_with_source (非 interface) 设.
        """
        self.add_with_source(record)

    def add_with_source(
        self,
        record: FailedDirectionRecord,
        *,
        source: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """扩展 add — 支持 source + tags (migration script 专用).

        interface FailedDirectionRecord 无 source/tags, 但 DB schema 有.
        此方法不违反 interface (是 DBFailedDirectionDB 的额外 concrete API).
        """
        factory = self._require_writer()
        conn = factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO failed_directions
                        (direction, reason, evidence, severity, source, tags, recorded_at)
                    VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph}, NOW())
                    ON CONFLICT (direction) DO UPDATE
                      SET reason=EXCLUDED.reason,
                          evidence=EXCLUDED.evidence,
                          severity=EXCLUDED.severity,
                          source=COALESCE(EXCLUDED.source, failed_directions.source),
                          tags=EXCLUDED.tags
                    """,
                    (
                        record.direction,
                        record.reason,
                        _json_dumps(record.evidence or []),
                        record.severity or "terminal",
                        source,
                        list(tags or []),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    # ---------- check_similar ----------

    def check_similar(self, direction: str, k: int = 3) -> list[FailedDirectionRecord]:
        """LIKE 搜相似失败方向.

        AI Agent 在生成 hypothesis 前必调. Returns 相似度降序 (用 recorded_at DESC 代理).
        """
        factory = self._require_writer()
        keywords = _extract_keywords(direction, max_k=5)
        conn = factory()
        try:
            with conn.cursor() as cur:
                base_cols = "direction, reason, evidence, recorded_at, severity"
                if not keywords:
                    sql = (
                        f"SELECT {base_cols} FROM failed_directions "
                        f"ORDER BY recorded_at DESC LIMIT {self._ph}"
                    )
                    cur.execute(sql, (k,))
                else:
                    conditions = " OR ".join(
                        [f"direction ILIKE {self._ph}" for _ in keywords]
                    )
                    sql = (
                        f"SELECT {base_cols} FROM failed_directions "
                        f"WHERE {conditions} "
                        f"ORDER BY recorded_at DESC LIMIT {self._ph}"
                    )
                    params = [f"%{w}%" for w in keywords] + [k]
                    cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_failed(row) for row in rows]

    # ---------- list_all ----------

    def list_all(self, severity: str | None = None) -> list[FailedDirectionRecord]:
        """列所有失败方向 (按 severity 过滤)."""
        factory = self._require_writer()
        conn = factory()
        try:
            with conn.cursor() as cur:
                base_cols = "direction, reason, evidence, recorded_at, severity"
                if severity is None:
                    cur.execute(
                        f"SELECT {base_cols} FROM failed_directions "
                        f"ORDER BY recorded_at DESC"
                    )
                else:
                    cur.execute(
                        f"SELECT {base_cols} FROM failed_directions "
                        f"WHERE severity={self._ph} "
                        f"ORDER BY recorded_at DESC",
                        (severity,),
                    )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_failed(row) for row in rows]


def _row_to_failed(row: tuple) -> FailedDirectionRecord:
    direction, reason, evidence, recorded_at, severity = row
    return FailedDirectionRecord(
        direction=str(direction),
        reason=str(reason),
        evidence=_json_loads(evidence) or [],
        recorded_at=str(recorded_at) if recorded_at else "",
        severity=str(severity or "terminal"),
    )


# ==================================================================
# DBADRRegistry
# ==================================================================


class DBADRRegistry(ADRRegistry):
    """ADR 注册表 concrete (MVP 1.4).

    表: adr_records. adr_id 是 PK. register ON CONFLICT DO UPDATE (幂等).
    markdown 文件是权威, DB 是索引 (用于 list_by_ironlaw 等查询).
    """

    def __init__(
        self,
        conn_factory: Callable[[], _DBConnection] | None = None,
        *,
        paramstyle: str = "%s",
    ) -> None:
        self._conn_factory = conn_factory
        self._ph = paramstyle

    def _require_writer(self) -> Callable[[], _DBConnection]:
        if self._conn_factory is None:
            raise WriteNotConfigured("DBADRRegistry 需要 conn_factory 注入.")
        return self._conn_factory

    # ---------- register (UPSERT) ----------

    def register(self, record: ADRRecord) -> str:
        """登记 ADR (幂等: 已存在 → 更新 title/status/context/decision).

        Args:
          record: ADRRecord dataclass (adr_id 由调用方指定, e.g. "ADR-001").

        Returns:
          adr_id (同 record.adr_id).
        """
        return self._register_with_file(record, file_path=None)

    def _register_with_file(self, record: ADRRecord, file_path: str | None) -> str:
        """扩展: 支持 file_path (DB 对 md 反查, migration script 专用)."""
        factory = self._require_writer()
        conn = factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO adr_records
                        (adr_id, title, status, context, decision, consequences,
                         related_ironlaws, file_path, recorded_at)
                    VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph},
                            {self._ph}, {self._ph}, {self._ph}, NOW())
                    ON CONFLICT (adr_id) DO UPDATE
                      SET title=EXCLUDED.title,
                          status=EXCLUDED.status,
                          context=EXCLUDED.context,
                          decision=EXCLUDED.decision,
                          consequences=EXCLUDED.consequences,
                          related_ironlaws=EXCLUDED.related_ironlaws,
                          file_path=COALESCE(EXCLUDED.file_path, adr_records.file_path)
                    """,
                    (
                        record.adr_id,
                        record.title,
                        record.status or "accepted",
                        record.context,
                        record.decision,
                        record.consequences,
                        list(record.related_ironlaws or []),
                        file_path,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return record.adr_id

    # ---------- supersede ----------

    def supersede(self, old_adr_id: str, new_adr_id: str) -> None:
        """标记旧 ADR 被新 ADR 取代. 写 `status = 'superseded_by:NEW-ID'`.

        Raises:
          ADRNotFound: old_adr_id 不存在.
        """
        factory = self._require_writer()
        conn = factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE adr_records
                       SET status={self._ph}
                     WHERE adr_id={self._ph}
                    """,
                    (f"superseded_by:{new_adr_id}", old_adr_id),
                )
                if cur.rowcount == 0:
                    raise ADRNotFound(f"{old_adr_id} 不在 adr_records")
            conn.commit()
        finally:
            conn.close()

    # ---------- get_by_id ----------

    def get_by_id(self, adr_id: str) -> ADRRecord:
        """按 ID 取. Raises ADRNotFound if missing."""
        factory = self._require_writer()
        conn = factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT adr_id, title, status, context, decision,
                           consequences, related_ironlaws, recorded_at
                    FROM adr_records
                    WHERE adr_id={self._ph}
                    """,
                    (adr_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            raise ADRNotFound(f"{adr_id} 不在 adr_records")
        return _row_to_adr(row)

    # ---------- list_by_ironlaw ----------

    def list_by_ironlaw(self, ironlaw_id: int) -> list[ADRRecord]:
        """查与指定铁律关联的 ADR 列表. PG GIN 索引加速.

        sqlite 测试无 GIN, 用 json_each 近似 (sqlite 3.38+). 简化版: LIKE %I_ID%.
        """
        factory = self._require_writer()
        conn = factory()
        try:
            with conn.cursor() as cur:
                if self._ph == "%s":
                    # psycopg2: int[] 有 ANY 原语
                    sql = (
                        f"""SELECT adr_id, title, status, context, decision,
                                    consequences, related_ironlaws, recorded_at
                              FROM adr_records
                             WHERE {self._ph} = ANY(related_ironlaws)
                             ORDER BY adr_id"""
                    )
                    cur.execute(sql, (ironlaw_id,))
                else:
                    # sqlite: related_ironlaws 存 JSON 字符串, LIKE 近似查
                    sql = (
                        f"""SELECT adr_id, title, status, context, decision,
                                    consequences, related_ironlaws, recorded_at
                              FROM adr_records
                             WHERE related_ironlaws LIKE {self._ph}
                             ORDER BY adr_id"""
                    )
                    cur.execute(sql, (f"%{ironlaw_id}%",))
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_adr(row) for row in rows]


def _row_to_adr(row: tuple) -> ADRRecord:
    adr_id, title, status, context, decision, consequences, related_ironlaws, recorded_at = row
    return ADRRecord(
        adr_id=str(adr_id),
        title=str(title),
        status=str(status or "accepted"),
        context=str(context or ""),
        decision=str(decision or ""),
        consequences=str(consequences or ""),
        related_ironlaws=_parse_ironlaws(related_ironlaws),
        recorded_at=str(recorded_at) if recorded_at else "",
    )


__all__ = [
    "DBExperimentRegistry",
    "DBFailedDirectionDB",
    "DBADRRegistry",
    "KnowledgeError",
    "ExperimentNotFound",
    "ADRNotFound",
    "WriteNotConfigured",
]
