"""MVP 4.1 batch 2.1 — PostgresMetricExporter live smoke (铁律 10b).

subprocess 真启动: SDK 导出 + ABC 关系 + 静态契约 marker + migration 文件存在.
fail-loud / NaN reject 由 unit 覆盖.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _build_smoke_code() -> str:
    backend_path = PROJECT_ROOT / "backend"
    backend_path_str = str(backend_path)
    project_root_str = str(PROJECT_ROOT)
    return (
        "import platform as _stdlib_platform; "
        "_stdlib_platform.python_implementation(); "
        "import sys; "
        f"sys.path.insert(0, r'{backend_path_str}'); "
        f"sys.path.insert(0, r'{project_root_str}'); "
        # 1. SDK 导出符号 (含 batch 1 + batch 2.1)
        "from qm_platform.observability import ("
        "    MetricExporter, Metric, "
        "    PostgresMetricExporter, MetricExportError, "
        "    get_metric_exporter, reset_metric_exporter, "
        "    AlertRouter, Alert, AlertFireResult, AlertDispatchError, "
        "    PostgresAlertRouter, DingTalkChannel, "
        "    get_alert_router, reset_alert_router, "
        "    OutboxWriter, EventBus"
        "); "
        # 2. ABC 关系
        "assert issubclass(PostgresMetricExporter, MetricExporter), "
        "'PostgresMetricExporter 必须实现 MetricExporter ABC'; "
        # 3. 三方法都存在 + Blueprint emit
        "assert hasattr(PostgresMetricExporter, 'gauge'); "
        "assert hasattr(PostgresMetricExporter, 'counter'); "
        "assert hasattr(PostgresMetricExporter, 'histogram'); "
        "assert hasattr(PostgresMetricExporter, 'emit'), 'Blueprint #7 emit() 签名必存'; "
        "assert hasattr(PostgresMetricExporter, 'query_recent'); "
        # 4. MetricExportError 是 RuntimeError
        "assert issubclass(MetricExportError, RuntimeError); "
        # 5. 静态 marker (防 fail-loud / NaN 防御被回退)
        "from pathlib import Path; "
        f"metric_path = Path(r'{backend_path_str}') / 'qm_platform' / 'observability' / 'metric.py'; "
        "src = metric_path.read_text(encoding='utf-8'); "
        "assert 'MetricExportError' in src and 'fail-loud' in src.lower(), "
        "'fail-loud 实现必存 (铁律 33)'; "
        "assert 'value != value' in src, 'NaN 防护必存 (铁律 29)'; "
        "assert 'tzinfo == UTC' in src or 'datetime.now(UTC)' in src, "
        "'UTC tz-aware 必存 (铁律 41)'; "
        # 6. Migration 文件 + hypertable + retention
        f"mig = Path(r'{backend_path_str}') / 'migrations' / 'platform_metrics.sql'; "
        "assert mig.exists(); "
        "mig_src = mig.read_text(encoding='utf-8'); "
        "assert 'create_hypertable' in mig_src, 'TimescaleDB hypertable 必存'; "
        "assert 'add_retention_policy' in mig_src, '30d retention 必存'; "
        "assert 'TIMESTAMP WITH TIME ZONE' in mig_src, 'tz-aware ts 必存'; "
        "assert \"CHECK (metric_type IN ('gauge', 'counter', 'histogram'))\" in mig_src, "
        "'metric_type CHECK 必存'; "
        f"rb = Path(r'{backend_path_str}') / 'migrations' / 'platform_metrics_rollback.sql'; "
        "assert rb.exists(); "
        "print('OK mvp_4_1_batch_2_1_metric_exporter boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_2_1_metric_exporter_imports_and_contracts():
    result = subprocess.run(
        [sys.executable, "-c", _build_smoke_code()],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"smoke failed (exit={result.returncode}): "
        f"stderr={result.stderr}\nstdout={result.stdout}"
    )
    assert "OK mvp_4_1_batch_2_1_metric_exporter boot" in result.stdout
