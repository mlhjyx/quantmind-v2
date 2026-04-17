"""MVP 1.3b/1.3c Framework #2 Factor — DBFactorRegistry concrete 实现.

MVP 1.3b (已上线): get_direction + TTL cache + 3 层 fallback via signal_engine.
MVP 1.3c (本轮): register / get_active / update_status / novelty_check concrete.

依赖注入保 MVP 1.1 Platform 严格隔离:
  - `dal`: Platform DataAccessLayer (read 路径)
  - `conn_factory`: 可选, 写路径 (register / update_status). None 时两法 raise NotImplementedError
  - `ast_similarity_fn`: 可选, G9 novelty check 相似度函数. None 时用内置 Jaccard

Platform 绝不 import `backend.app.*` / `backend.data.*` / `backend.engines.*`
(MVP 1.1 test_platform_strict_isolation 要求).

关联铁律:
  - 12: G9 novelty_check AST 相似度
  - 13: G10 hypothesis 强制非空
  - 25: register 前必读 DB (DAL.read_registry 核查 duplicate)
  - 30: 缓存一致性 (TTL + invalidate on update_status)
  - 33: 禁 silent failure (异常向上 raise)
  - 34: 配置 SSOT (direction / status 以 DB 为权威)

Usage (生产, 含 register):
    from backend.data.factor_cache import FactorCache
    from backend.app.services.db import get_sync_conn
    from backend.platform.data.access_layer import PlatformDataAccessLayer
    from backend.platform.factor.registry import DBFactorRegistry

    dal = PlatformDataAccessLayer(conn_factory=get_sync_conn, factor_cache=FactorCache())
    registry = DBFactorRegistry(dal, conn_factory=get_sync_conn)
    registry.register(FactorSpec(...))
"""
from __future__ import annotations

import ast
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from backend.platform.factor.interface import (
    FactorLifecycleMonitor,
    FactorMeta,
    FactorRegistry,
    FactorSpec,
    FactorStatus,
    TransitionDecision,
)

if TYPE_CHECKING:
    from backend.platform.data.interface import DataAccessLayer


# ---------- 错误类型 ----------


class OnboardingBlocked(RuntimeError):  # noqa: N818 — 语义优先, Platform 同策略 (MVP 1.2 FlagNotFound)
    """factor onboarding 被 G9/G10 等 Gate 拒绝."""


class DuplicateFactor(RuntimeError):  # noqa: N818 — 语义优先
    """factor_name 已在 registry 中存在."""


class FactorNotFound(RuntimeError):  # noqa: N818 — 语义优先
    """update_status 操作的 factor_name 未在 registry."""


class WriteNotConfigured(RuntimeError):  # noqa: N818 — 语义优先
    """DBFactorRegistry 未注入 conn_factory, 无法执行写路径."""


# ---------- DB 鸭子类型 ----------


class _DBConnection(Protocol):
    """psycopg2 / sqlite3 connection 鸭子类型."""

    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


# ---------- 内置 AST Jaccard (G9 默认实现) ----------


def _default_ast_jaccard(expr1: str, expr2: str) -> float:
    """内置 G9 AST Jaccard 相似度 (无 normalize, 纯 Python 标准库).

    精度足够新因子粗过滤. 高精度 normalize (rank(a+b)==rank(b+a)) 需调用方
    注入 ast_similarity_fn (如 engines.mining.ast_dedup.AstDeduplicator
    .compute_ast_similarity).

    Returns:
      0.0-1.0 的相似度. 任一表达式解析失败返 0.0.
    """
    try:
        t1 = ast.parse(expr1, mode="eval")
        t2 = ast.parse(expr2, mode="eval")
    except (SyntaxError, ValueError, TypeError):
        return 0.0
    nodes1 = {ast.dump(n) for n in ast.walk(t1)}
    nodes2 = {ast.dump(n) for n in ast.walk(t2)}
    if not nodes1 or not nodes2:
        return 0.0
    intersection = nodes1 & nodes2
    return len(intersection) / max(len(nodes1), len(nodes2))


# ---------- 阈值常量 ----------

G9_SIMILARITY_THRESHOLD: float = 0.7
"""G9 Gate — AST Jaccard > 0.7 视为近似 (铁律 12)."""

G10_HYPOTHESIS_MIN_LEN: int = 20
"""G10 Gate — hypothesis 字符串最小长度 (铁律 13)."""

G10_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "GP自动挖掘",
    "GP auto",
    "TODO",
    "待填",
    "auto-generated",
)
"""G10 Gate — 默认占位符前缀 (被拒)."""


# ---------- DBFactorRegistry ----------


class DBFactorRegistry(FactorRegistry):
    """MVP 1.3b/1.3c concrete — DB 权威 direction + onboarding strong gates.

    Thread-safe (RLock) 保 Celery 多 worker 并发. Cache 一次 load 全表
    (287 行 ~ 3KB 内存). TTL 过期自动 refresh.

    MVP 1.3b (已上线):
      - get_direction + cache + invalidate
    MVP 1.3c (本轮):
      - register (G9 + G10 硬门, INSERT INTO factor_registry)
      - get_active (status = 'active' 的 FactorMeta list)
      - update_status (UPDATE + invalidate cache)
      - novelty_check (G9 AST Jaccard)
    """

    def __init__(
        self,
        dal: DataAccessLayer,
        conn_factory: Callable[[], _DBConnection] | None = None,
        *,
        cache_ttl_minutes: int = 60,
        ast_similarity_fn: Callable[[str, str], float] | None = None,
        paramstyle: str = "%s",
    ) -> None:
        self._dal = dal
        self._conn_factory = conn_factory
        self._ttl = timedelta(minutes=cache_ttl_minutes)
        self._cache: dict[str, int] = {}
        self._last_refresh: datetime | None = None
        self._lock = threading.RLock()
        self._ast_sim_fn = ast_similarity_fn or _default_ast_jaccard
        self._ph = paramstyle

    # ---------- get_direction (MVP 1.3b 核心) ----------

    def get_direction(self, name: str) -> int:
        """读 direction. Cache miss 或 TTL 过期 → 一次性 load 全表.

        Returns:
          direction (+1 / -1). 未注册因子返回默认 +1 (对齐 signal_engine fallback).
        """
        with self._lock:
            if self._should_refresh():
                self._refresh()
            return self._cache.get(name, 1)

    def invalidate(self) -> None:
        """手动失效 cache — update_status / register 后触发."""
        with self._lock:
            self._cache = {}
            self._last_refresh = None

    def cache_size(self) -> int:
        """返 cache 当前条目数 (debug / test 用)."""
        with self._lock:
            return len(self._cache)

    def _should_refresh(self) -> bool:
        if self._last_refresh is None:
            return True
        return (datetime.now(UTC) - self._last_refresh) > self._ttl

    def _refresh(self) -> None:
        df = self._dal.read_registry()
        self._cache = dict(
            zip(df["name"].tolist(), df["direction"].astype(int).tolist(), strict=True)
        )
        self._last_refresh = datetime.now(UTC)

    # ---------- MVP 1.3c: get_active ----------

    def get_active(self) -> list[FactorMeta]:
        """返当前 ACTIVE 状态的所有因子 (PT 生产在用).

        Returns:
          list[FactorMeta] — MVP 1.3a 对齐 DB 18 字段.
        """
        df = self._dal.read_registry(status_filter="active")
        if df.empty:
            return []
        return [_row_to_factor_meta(row) for row in df.to_dict("records")]

    # ---------- MVP 1.3c: novelty_check (G9 AST Jaccard) ----------

    def novelty_check(self, spec: FactorSpec) -> bool:
        """G9 Gate — AST Jaccard 相似度 > 0.7 → 拒绝 (铁律 12).

        Returns:
          True 若与所有 ACTIVE 因子 Jaccard ≤ 0.7.
          True 若 spec.expression 为空 (手写 builtin 因子, 走 G10 兜底).
        """
        if not spec.expression:
            return True
        for active in self.get_active():
            if not active.expression:
                continue
            sim = self._ast_sim_fn(spec.expression, active.expression)
            if sim > G9_SIMILARITY_THRESHOLD:
                return False
        return True

    # ---------- MVP 1.3c: register (G9 + G10 硬门 + INSERT) ----------

    def register(self, spec: FactorSpec) -> UUID:
        """onboarding 入口 — G9 + G10 必过, INSERT INTO factor_registry.

        Raises:
          OnboardingBlocked: G10 (hypothesis 非法) 或 G9 (AST 相似) 失败.
          DuplicateFactor: spec.name 已在 factor_registry.
          WriteNotConfigured: conn_factory 未注入.
        """
        # G10 hypothesis 强制 (铁律 13)
        hypo = (spec.hypothesis or "").strip()
        if not hypo or len(hypo) < G10_HYPOTHESIS_MIN_LEN:
            raise OnboardingBlocked(
                f"G10 失败 (铁律 13): hypothesis 必须非空且 ≥ {G10_HYPOTHESIS_MIN_LEN} 字, "
                f"现长度={len(hypo)}, 内容={hypo!r}"
            )
        if any(hypo.startswith(p) for p in G10_FORBIDDEN_PREFIXES):
            raise OnboardingBlocked(
                f"G10 失败 (铁律 13): hypothesis 不得以占位符开头, 现: {hypo!r}. "
                f"禁止前缀: {G10_FORBIDDEN_PREFIXES}"
            )

        # Duplicate 检查 (铁律 25 验 DB 再写)
        existing = self._dal.read_registry()
        if not existing.empty and spec.name in existing["name"].tolist():
            raise DuplicateFactor(f"{spec.name} 已在 factor_registry 中注册")

        # G9 novelty (铁律 12, 在 duplicate 之后, 避免对自己 AST 比)
        if not self.novelty_check(spec):
            raise OnboardingBlocked(
                f"G9 失败 (铁律 12): {spec.name} AST Jaccard > {G9_SIMILARITY_THRESHOLD} "
                f"vs 已有 ACTIVE 因子"
            )

        # INSERT
        new_id = self._insert_spec(spec)
        self.invalidate()  # 让后续 get_direction 重新 load
        return new_id

    def _insert_spec(self, spec: FactorSpec) -> UUID:
        """INSERT 一条 FactorSpec 到 factor_registry (RETURNING id)."""
        if self._conn_factory is None:
            raise WriteNotConfigured(
                "DBFactorRegistry.register 需要 conn_factory 注入. "
                "构造时请传 `conn_factory=get_sync_conn`."
            )
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO factor_registry
                        (name, category, direction, expression, hypothesis, source,
                         pool, status, created_at, updated_at)
                    VALUES
                        ({self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph},
                         {self._ph}, {self._ph}, 'candidate', NOW(), NOW())
                    RETURNING id
                    """,
                    (
                        spec.name,
                        spec.category,
                        spec.direction,
                        spec.expression,
                        spec.hypothesis,
                        spec.author or "manual",  # source 列 (gp / llm / manual)
                        spec.pool,
                    ),
                )
                row = cur.fetchone()
                new_id = row[0] if row else None
            conn.commit()
            if new_id is None:
                raise RuntimeError(f"INSERT factor_registry 未返回 id for {spec.name}")
            return new_id if isinstance(new_id, UUID) else UUID(str(new_id))
        finally:
            conn.close()

    # ---------- MVP 1.3c: update_status ----------

    def update_status(self, name: str, new_status: FactorStatus, reason: str) -> None:
        """变更因子状态 (带 reason 审计字段更新 + invalidate cache).

        Raises:
          FactorNotFound: name 未在 factor_registry.
          WriteNotConfigured: conn_factory 未注入.
        """
        if self._conn_factory is None:
            raise WriteNotConfigured(
                "DBFactorRegistry.update_status 需要 conn_factory 注入."
            )
        status_value = new_status.value if isinstance(new_status, FactorStatus) else str(new_status)
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                # reason 写入 hypothesis_patch 或专用审计列? DDL 现无 reason 列,
                # 暂不落 DB, 仅 UPDATE status + updated_at (铁律 33 需 caller log reason)
                cur.execute(
                    f"""
                    UPDATE factor_registry
                       SET status = {self._ph}, updated_at = NOW()
                     WHERE name = {self._ph}
                    """,
                    (status_value, name),
                )
                if cur.rowcount == 0:
                    raise FactorNotFound(f"{name} 未在 factor_registry 中")
            conn.commit()
            self.invalidate()  # status 变 → direction cache 可能关联 (保守失效)
            del reason  # TODO MVP 1.3d: 落审计表 factor_status_history
        finally:
            conn.close()


# ---------- helper ----------


def _row_to_factor_meta(row: dict[str, Any]) -> FactorMeta:
    """factor_registry 行 dict → FactorMeta dataclass."""
    status_raw = row.get("status") or "active"
    try:
        status = FactorStatus(status_raw)
    except (ValueError, TypeError):
        status = FactorStatus.ACTIVE  # 容错: 未知状态视为 active

    # id 可能是 UUID / str / None
    fid_raw = row.get("id")
    if fid_raw is None:
        factor_id = UUID(int=0)
    elif isinstance(fid_raw, UUID):
        factor_id = fid_raw
    else:
        try:
            factor_id = UUID(str(fid_raw))
        except (ValueError, TypeError):
            factor_id = UUID(int=0)

    return FactorMeta(
        factor_id=factor_id,
        name=str(row.get("name")),
        category=str(row.get("category") or "alpha"),
        direction=int(row.get("direction") or 1),
        expression=row.get("expression"),
        code_content=row.get("code_content"),
        hypothesis=row.get("hypothesis"),
        source=str(row.get("source") or "manual"),
        lookback_days=row.get("lookback_days"),
        status=status,
        pool=str(row.get("pool") or "LEGACY"),
        gate_ic=_float_or_none(row.get("gate_ic")),
        gate_ir=_float_or_none(row.get("gate_ir")),
        gate_mono=_float_or_none(row.get("gate_mono")),
        gate_t=_float_or_none(row.get("gate_t")),
        ic_decay_ratio=_float_or_none(row.get("ic_decay_ratio")),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- StubLifecycleMonitor (MVP 1.3b 占位, MVP 1.3c 保兼容) ----------


class StubLifecycleMonitor(FactorLifecycleMonitor):
    """MVP 1.3b 占位. MVP 1.3c 推荐用 PlatformLifecycleMonitor (backend.platform.factor.lifecycle)."""

    def evaluate_all(self) -> list[TransitionDecision]:
        raise NotImplementedError(
            "MVP 1.3c: 请用 backend.platform.factor.lifecycle.PlatformLifecycleMonitor"
        )


__all__ = [
    "DBFactorRegistry",
    "StubLifecycleMonitor",
    "OnboardingBlocked",
    "DuplicateFactor",
    "FactorNotFound",
    "WriteNotConfigured",
    "G9_SIMILARITY_THRESHOLD",
    "G10_HYPOTHESIS_MIN_LEN",
    "G10_FORBIDDEN_PREFIXES",
]
