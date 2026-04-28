"""MVP 4.1 Observability Framework batch 2.1 — PostgresMetricExporter concrete.

替代 17 schtask + Celery 脚本散落 print + log 监控数据的统一时间序列后端:
  - gauge / counter / histogram → INSERT 到 platform_metrics (TimescaleDB hypertable)
  - Blueprint #7 字面 emit(metric, value, labels) 签名兼容 (语义同 gauge)
  - 30 天 retention (Wave 5 UI dashboard 数据源, 月度趋势够用)
  - 失败 fail-loud (铁律 33), 不静默吃异常

关联铁律:
  - 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud) / 41 (UTC tz-aware)
  - 17 例外: MetricExporter 是 Platform-internal writer, 不走 DataPipeline
            (类似 outbox.py / alert.py, 是基础设施表非业务事实)

Application Pattern usage:
    >>> from qm_platform.observability import get_metric_exporter
    >>> m = get_metric_exporter()
    >>> m.gauge("pt.signal.count", 20.0, labels={"strategy": "S1"})
    >>> m.counter("orders.filled", 1.0, labels={"strategy": "S1"})
    >>> m.histogram("signal.latency_ms", 234.5, labels={"strategy": "S1"})
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .interface import Metric, MetricExporter

if TYPE_CHECKING:
    import psycopg2.extensions

logger = logging.getLogger(__name__)

# Metric name 长度上限 (对齐 platform_metrics CHECK char_length(name) BETWEEN 1 AND 256)
_METRIC_NAME_MAX_LEN = 256

# Labels JSONB 大小硬上限 (防 caller 滥用塞 MB 级 payload)
_LABELS_JSON_MAX_BYTES = 4096


class MetricExportError(RuntimeError):
    """Metric 写入失败 (铁律 33 fail-loud)."""


def _now_utc() -> datetime:
    """tz-aware UTC now (铁律 41 显式 UTC, 测试可 monkeypatch)."""
    return datetime.now(UTC)


class PostgresMetricExporter(MetricExporter):
    """MetricExporter concrete: PG TimescaleDB-backed 时间序列存储.

    每次 gauge/counter/histogram 调用 = 1 INSERT (append-only). counter 不在内存
    aggregate, 由查询层 SUM (TimescaleDB 时序优化原生支持).

    线程安全: 每次 emit 用独立 conn (conn_factory 注入), 无共享可变状态.
    跨进程安全: PG row-level 写入语义自然支持.

    Args:
      conn_factory: psycopg2 conn factory. None → 默认 app.services.db.get_sync_conn.
      now_fn: 时间注入 (单测 freeze), 默认 _now_utc.
      reraise: True → fail-loud raise MetricExportError (铁律 33). False → log error
               + 静默 (用例: 高频 hot path 不希望 metric 失败破坏主业务). 默认 True.

    Note: reraise=False 是 caller 显式选择的逃生口, 不属于"silent failure" — log
    error 留 trace, 调用方 acknowledge 风险.
    """

    def __init__(
        self,
        conn_factory: Callable[[], psycopg2.extensions.connection] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        *,
        reraise: bool = True,
    ) -> None:
        if conn_factory is None:
            from app.services.db import get_sync_conn as _default_factory
            conn_factory = _default_factory
        self._conn_factory = conn_factory
        self._now_fn = now_fn or _now_utc
        self._reraise = reraise

    # ─────────────────────── interface.py ABC implementations ───────────────────────

    def gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录瞬时值 (e.g. current_nav, signal_count)."""
        self._emit(name, value, "gauge", labels)

    def counter(
        self,
        name: str,
        increment: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """递增计数器 (e.g. orders_filled_total).

        Note: 每次调用 = 1 INSERT (不在内存 aggregate). 查询层 SUM(value) WHERE name=...
        + time range 即 counter 总值. 这避免 counter reset / 进程重启状态丢失问题
        (本地 counter 累计经常因为进程死掉就丢, PG append-only 永不丢).
        """
        if increment < 0:
            raise ValueError(f"counter increment 必须 >= 0, got {increment!r}")
        self._emit(name, float(increment), "counter", labels)

    def histogram(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录分布 (e.g. signal_generation_latency_ms).

        当前 V1: 不做 bucket 化, 每次 INSERT 1 row. 查询层用 percentile_cont() 算 p50/p95/p99.
        Wave 5+ 视频率决定是否引 TimescaleDB continuous aggregates 预计算.
        """
        self._emit(name, value, "histogram", labels)

    # ─────────────────────── Blueprint #7 字面签名 ───────────────────────

    def emit(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Blueprint Framework #7 字面签名 (emit). 默认走 gauge 语义.

        与 ABC gauge/counter/histogram 共存 — caller 不关心 type 时用 emit.
        """
        self.gauge(metric, value, labels)

    # ─────────────────────── 查询接口 (低频 debug + Wave 5 UI 用) ───────────────────────

    def query_recent(
        self,
        name: str,
        limit: int = 100,
    ) -> list[Metric]:
        """读最近 N 条同名 metric (Wave 5 UI / 调试用).

        time-series UI 应直接 SQL 查询 platform_metrics, 此 method 仅小规模 ad-hoc.
        """
        if not name or not isinstance(name, str):
            raise ValueError("name 必须非空字符串")
        if limit <= 0 or limit > 10000:
            raise ValueError(f"limit 必须 1..10000, got {limit}")

        conn = self._conn_factory()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT name, value, labels, ts
                    FROM platform_metrics
                    WHERE name = %s
                    ORDER BY ts DESC
                    LIMIT %s
                    """,
                    (name, limit),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        out: list[Metric] = []
        for row_name, row_value, row_labels, row_ts in rows:
            ts_iso = (
                row_ts.isoformat()
                if isinstance(row_ts, datetime)
                else str(row_ts)
            )
            # row_labels 来自 JSONB → psycopg2 自动 dict, 防 None
            labels_dict: dict[str, str] = (
                {k: str(v) for k, v in (row_labels or {}).items()}
            )
            out.append(
                Metric(
                    name=str(row_name),
                    value=float(row_value),
                    labels=labels_dict,
                    timestamp_utc=ts_iso,
                )
            )
        return out

    # ─────────────────────── 内部 helpers ───────────────────────

    def _emit(
        self,
        name: str,
        value: float,
        metric_type: str,
        labels: dict[str, str] | None,
    ) -> None:
        """内部统一 INSERT helper. fail-loud (reraise=True) 默认.

        Validation:
          - name: 非空, 长度 ≤ 256 (对齐 DB CHECK)
          - value: NaN reject (DB CHECK value=value 也会拦, 但应用层早 fail 节省 round-trip)
          - labels: dict[str, str], JSON ≤ 4KB
        """
        self._validate(name, value, metric_type, labels)
        labels_json = json.dumps(labels or {}, ensure_ascii=False)
        if len(labels_json.encode("utf-8")) > _LABELS_JSON_MAX_BYTES:
            raise ValueError(
                f"labels JSON 超 {_LABELS_JSON_MAX_BYTES} bytes, "
                f"got {len(labels_json)} chars"
            )
        ts = self._now_fn()

        try:
            conn = self._conn_factory()
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO platform_metrics
                            (name, value, metric_type, labels, ts)
                        VALUES (%s, %s, %s, %s::jsonb, %s)
                        """,
                        (name, value, metric_type, labels_json, ts),
                    )
            finally:
                conn.close()
        except Exception as e:
            logger.error(
                "[MetricExporter] emit failed name=%s type=%s value=%s err=%s",
                name,
                metric_type,
                value,
                e,
            )
            if self._reraise:
                raise MetricExportError(
                    f"Failed to emit metric {name!r} (type={metric_type}): {e}"
                ) from e
            # reraise=False: caller 显式选择, 不算 silent failure (已 log error)

    @staticmethod
    def _validate(
        name: str,
        value: float,
        metric_type: str,
        labels: dict[str, str] | None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric name 必须非空字符串")
        if len(name) > _METRIC_NAME_MAX_LEN:
            raise ValueError(
                f"metric name 超长 (>{_METRIC_NAME_MAX_LEN}): {len(name)}"
            )
        # bool 是 int 子类, 显式 reject (避免 metric.gauge('x', True) 静默写入)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"metric value 必须 numeric (int/float, 不允 bool), got {type(value).__name__}"
            )
        # NaN reject (NaN != NaN)
        if value != value:  # noqa: PLR0124  intentional NaN check
            raise ValueError("metric value 不允 NaN (铁律 29)")
        # Inf reject (避免 PG DOUBLE PRECISION 写入 ±Inf 干扰 aggregate)
        if value == float("inf") or value == float("-inf"):
            raise ValueError(f"metric value 不允 Inf, got {value}")
        if metric_type not in ("gauge", "counter", "histogram"):
            raise ValueError(
                f"metric_type 必须 gauge/counter/histogram, got {metric_type!r}"
            )
        if labels is not None:
            if not isinstance(labels, dict):
                raise TypeError(
                    f"labels 必须 dict, got {type(labels).__name__}"
                )
            for k, v in labels.items():
                if not isinstance(k, str):
                    raise TypeError(
                        f"label key 必须 str, got {type(k).__name__} ({k!r})"
                    )
                if not isinstance(v, str):
                    raise TypeError(
                        f"label value 必须 str (caller 自行 stringify), "
                        f"got {type(v).__name__} ({v!r})"
                    )


# ────────────────── 全局单例 + factory ──────────────────

_exporter_singleton: PostgresMetricExporter | None = None
_singleton_lock = threading.Lock()


def get_metric_exporter() -> PostgresMetricExporter:
    """Lazy-init 全局 PostgresMetricExporter 单例.

    Application 调用方:
        from qm_platform.observability import get_metric_exporter
        m = get_metric_exporter()
        m.gauge("pt.signal.count", 20.0, labels={"strategy": "S1"})
    """
    global _exporter_singleton
    if _exporter_singleton is None:
        with _singleton_lock:
            if _exporter_singleton is None:
                _exporter_singleton = PostgresMetricExporter()
    return _exporter_singleton


def reset_metric_exporter() -> None:
    """重置全局单例 (单测用)."""
    global _exporter_singleton
    with _singleton_lock:
        _exporter_singleton = None


__all__ = [
    "PostgresMetricExporter",
    "MetricExportError",
    "get_metric_exporter",
    "reset_metric_exporter",
]
