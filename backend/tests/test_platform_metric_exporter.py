"""MVP 4.1 batch 2.1 unit tests — PostgresMetricExporter + emit / gauge / counter / histogram.

Mock-based 单测, 不连真 PG (smoke test_mvp_4_1_batch_2_1_live.py 走真 DB).
覆盖:
  - 合约: MetricExporter ABC 实现, gauge/counter/histogram 三方法 + Blueprint emit
  - validation: name 空/超长 / value NaN/Inf/bool / labels 非 str / labels JSON 超 4KB
  - counter increment 必 >= 0
  - timezone (铁律 41 UTC)
  - reraise=True (default) → MetricExportError; reraise=False → log + 不抛
  - query_recent
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from qm_platform.observability import (
    Metric,
    MetricExporter,
    MetricExportError,
    PostgresMetricExporter,
    reset_metric_exporter,
)
from qm_platform.observability.metric import (
    _LABELS_JSON_MAX_BYTES,
    _METRIC_NAME_MAX_LEN,
)


@pytest.fixture(autouse=True)
def _clear_singleton():
    reset_metric_exporter()
    yield
    reset_metric_exporter()


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC)


def _mock_conn() -> tuple[MagicMock, MagicMock]:
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=None)
    cur.fetchall = MagicMock(return_value=[])
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.close = MagicMock()
    return conn, cur


def _make_exporter(*, conn=None, now=None, reraise=True):
    if conn is None:
        conn, _ = _mock_conn()
    return PostgresMetricExporter(
        conn_factory=lambda: conn,
        now_fn=lambda: now or datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC),
        reraise=reraise,
    )


# ─────────────────────────── 合约 / ABC ───────────────────────────


def test_postgres_exporter_implements_abc():
    assert issubclass(PostgresMetricExporter, MetricExporter)


def test_gauge_inserts_row(fixed_now):
    conn, cur = _mock_conn()
    exp = _make_exporter(conn=conn, now=fixed_now)

    exp.gauge("pt.signal.count", 20.0, labels={"strategy": "S1"})

    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO platform_metrics" in c.args[0]
    ]
    assert len(insert_calls) == 1
    args = insert_calls[0].args[1]
    assert args[0] == "pt.signal.count"
    assert args[1] == 20.0
    assert args[2] == "gauge"
    assert '"strategy": "S1"' in args[3]
    assert args[4] == fixed_now


def test_counter_inserts_with_counter_type(fixed_now):
    conn, cur = _mock_conn()
    exp = _make_exporter(conn=conn, now=fixed_now)

    exp.counter("orders.filled", 3.0, labels={"strategy": "S1"})

    args = cur.execute.call_args_list[-1].args[1]
    assert args[1] == 3.0
    assert args[2] == "counter"


def test_counter_default_increment_is_one(fixed_now):
    conn, cur = _mock_conn()
    exp = _make_exporter(conn=conn, now=fixed_now)
    exp.counter("orders.filled")
    args = cur.execute.call_args_list[-1].args[1]
    assert args[1] == 1.0


def test_counter_zero_or_negative_rejected():
    """reviewer P3 采纳: increment=0 也 reject (heartbeat 应用 gauge, 防 SUM 污染)."""
    exp = _make_exporter()
    with pytest.raises(ValueError, match="counter increment 必须 > 0"):
        exp.counter("orders.filled", -1.0)
    with pytest.raises(ValueError, match="counter increment 必须 > 0"):
        exp.counter("orders.filled", 0.0)


def test_histogram_inserts_with_histogram_type(fixed_now):
    conn, cur = _mock_conn()
    exp = _make_exporter(conn=conn, now=fixed_now)
    exp.histogram("signal.latency_ms", 234.5)
    args = cur.execute.call_args_list[-1].args[1]
    assert args[2] == "histogram"


def test_emit_blueprint_signature_acts_as_gauge(fixed_now):
    """Blueprint #7 字面 emit(metric, value, labels) 默认 gauge 语义."""
    conn, cur = _mock_conn()
    exp = _make_exporter(conn=conn, now=fixed_now)
    exp.emit("custom.metric", 1.0)
    args = cur.execute.call_args_list[-1].args[1]
    assert args[2] == "gauge"


# ─────────────────────────── validation ───────────────────────────


def test_validate_empty_name_rejected():
    exp = _make_exporter()
    with pytest.raises(ValueError, match="metric name 必须非空"):
        exp.gauge("", 1.0)
    with pytest.raises(ValueError, match="metric name 必须非空"):
        exp.gauge("   ", 1.0)


def test_validate_overlong_name_rejected():
    exp = _make_exporter()
    overlong = "x" * (_METRIC_NAME_MAX_LEN + 1)
    with pytest.raises(ValueError, match="超长"):
        exp.gauge(overlong, 1.0)


def test_validate_nan_rejected():
    """铁律 29 防 NaN 入库."""
    exp = _make_exporter()
    with pytest.raises(ValueError, match="不允 NaN"):
        exp.gauge("x", float("nan"))


def test_validate_inf_rejected():
    exp = _make_exporter()
    with pytest.raises(ValueError, match="不允 Inf"):
        exp.gauge("x", float("inf"))
    with pytest.raises(ValueError, match="不允 Inf"):
        exp.gauge("x", float("-inf"))


def test_validate_bool_rejected():
    """bool 是 int 子类, 显式 reject 防 metric.gauge('x', True) 静默写入."""
    exp = _make_exporter()
    with pytest.raises(ValueError, match="不允 bool"):
        exp.gauge("x", True)
    with pytest.raises(ValueError, match="不允 bool"):
        exp.gauge("x", False)


def test_validate_labels_non_dict_rejected():
    exp = _make_exporter()
    with pytest.raises(TypeError, match="labels 必须 dict"):
        exp.gauge("x", 1.0, labels=["a", "b"])  # type: ignore[arg-type]


def test_validate_label_value_non_str_rejected():
    """label value 必 str (caller 自行 stringify, 避免 silent JSON 序列化怪 type)."""
    exp = _make_exporter()
    with pytest.raises(TypeError, match="label value 必须 str"):
        exp.gauge("x", 1.0, labels={"k": 42})  # type: ignore[dict-item]


def test_validate_labels_oversized_rejected():
    exp = _make_exporter()
    huge = {"k": "x" * (_LABELS_JSON_MAX_BYTES + 100)}
    with pytest.raises(ValueError, match="labels JSON 超") as exc_info:
        exp.gauge("x", 1.0, labels=huge)
    # reviewer P2 采纳: 错误信息报 bytes 而非 chars (多字节字符不误导)
    assert "bytes" in str(exc_info.value).split("got")[1]


def test_validate_labels_oversized_multibyte_reports_bytes():
    """中文 label value 超 4KB bytes 时 error message 报 bytes 不是 chars (多字节差异)."""
    exp = _make_exporter()
    # 中文 char 在 UTF-8 占 3 bytes, 1500 中文字 = ~4500 bytes 超 4KB
    huge_zh = {"k": "中" * 1500}
    with pytest.raises(ValueError, match="labels JSON 超") as exc_info:
        exp.gauge("x", 1.0, labels=huge_zh)
    err = str(exc_info.value)
    # bytes 计数应远大于 chars (中文 1 char ≈ 3 bytes)
    assert " bytes" in err.split("got")[1], f"Error must report bytes, got: {err}"


# ─────────────────────────── reraise / fail-loud ───────────────────────────


def test_emit_reraise_true_raises_metric_export_error():
    """默认 reraise=True: 任何 PG 错误 raise MetricExportError (铁律 33)."""
    failing_conn = MagicMock()
    failing_conn.cursor = MagicMock(side_effect=RuntimeError("PG down"))
    failing_conn.close = MagicMock()
    exp = PostgresMetricExporter(
        conn_factory=lambda: failing_conn,
        now_fn=lambda: datetime(2026, 4, 29, tzinfo=UTC),
        reraise=True,
    )
    with pytest.raises(MetricExportError, match="Failed to emit"):
        exp.gauge("x", 1.0)


def test_emit_reraise_false_logs_but_no_raise(caplog):
    """reraise=False: caller 显式选择不打断主路径, 仍 log error (非 silent failure)."""
    failing_conn = MagicMock()
    failing_conn.cursor = MagicMock(side_effect=RuntimeError("PG down"))
    failing_conn.close = MagicMock()
    exp = PostgresMetricExporter(
        conn_factory=lambda: failing_conn,
        now_fn=lambda: datetime(2026, 4, 29, tzinfo=UTC),
        reraise=False,
    )
    # 不 raise
    exp.gauge("x", 1.0)
    # 但 log error 必有
    assert any("emit failed" in rec.message for rec in caplog.records)


# ─────────────────────────── timezone ───────────────────────────


def test_emit_uses_utc_tzaware(fixed_now):
    conn, cur = _mock_conn()
    exp = _make_exporter(conn=conn, now=fixed_now)
    exp.gauge("x", 1.0)
    ts_arg = cur.execute.call_args_list[-1].args[1][4]
    assert ts_arg == fixed_now
    assert ts_arg.tzinfo == UTC


# ─────────────────────────── query_recent ───────────────────────────


def test_query_recent_returns_metrics(fixed_now):
    conn, cur = _mock_conn()
    cur.fetchall.return_value = [
        ("pt.signal.count", 20.0, {"strategy": "S1"}, fixed_now),
        ("pt.signal.count", 18.0, {"strategy": "S1"}, fixed_now),
    ]
    exp = _make_exporter(conn=conn, now=fixed_now)

    rows = exp.query_recent("pt.signal.count", limit=10)

    assert len(rows) == 2
    assert all(isinstance(r, Metric) for r in rows)
    assert rows[0].name == "pt.signal.count"
    assert rows[0].value == 20.0
    assert rows[0].labels == {"strategy": "S1"}


def test_query_recent_validates_inputs():
    exp = _make_exporter()
    with pytest.raises(ValueError, match="非空"):
        exp.query_recent("", limit=10)
    with pytest.raises(ValueError, match="1..10000"):
        exp.query_recent("x", limit=0)
    with pytest.raises(ValueError, match="1..10000"):
        exp.query_recent("x", limit=10_001)


def test_query_recent_handles_null_labels(fixed_now):
    """JSONB labels 为 None / empty dict 时 return labels={}."""
    conn, cur = _mock_conn()
    cur.fetchall.return_value = [("x", 1.0, None, fixed_now)]
    exp = _make_exporter(conn=conn, now=fixed_now)
    rows = exp.query_recent("x")
    assert rows[0].labels == {}
