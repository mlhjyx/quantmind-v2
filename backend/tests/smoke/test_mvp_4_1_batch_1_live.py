"""MVP 4.1 batch 1 — PostgresAlertRouter live smoke (铁律 10b).

subprocess 真启动验证: qm_platform.observability.alert 在生产入口可被 import 不破,
所有 SDK 导出符号可访问 (Application 调 SDK 路径 OK).

Note: ``python -c`` 多语句通过 ``;`` 分隔, 不能含 ``try:`` 块 (语法限制). fail-loud
        行为由 unit test (test_platform_alert_router.py) 覆盖, 此 smoke 验证 import +
        ABC 关系 + 静态契约 markers + migration 文件存在.
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
        # 1. SDK 导出符号可 import (核心硬门, 任何 import 错则全部失败)
        # 注: Channel Protocol 不导出 (设计稿禁 App 自实现 channel 旁路).
        "from qm_platform.observability import ("
        "    AlertRouter, Alert, AlertFireResult, AlertDispatchError, "
        "    PostgresAlertRouter, DingTalkChannel, "
        "    get_alert_router, reset_alert_router, "
        "    OutboxWriter, MetricExporter, EventBus, Metric"
        "); "
        "from qm_platform._types import Severity; "
        # 2. ABC 关系正确 (Liskov 契约)
        "assert issubclass(PostgresAlertRouter, AlertRouter), "
        "'PostgresAlertRouter 必须实现 AlertRouter ABC'; "
        # 3. 接口三方法都暴露 (interface fire + Blueprint alert + history)
        "assert hasattr(PostgresAlertRouter, 'fire'), 'fire() 必须存在'; "
        "assert hasattr(PostgresAlertRouter, 'alert'), 'alert(severity, payload) 必须存在'; "
        "assert hasattr(PostgresAlertRouter, 'get_history'), 'get_history 必须存在'; "
        # 4. AlertDispatchError 是 RuntimeError (interface 契约)
        "assert issubclass(AlertDispatchError, RuntimeError); "
        # 5. Severity enum 完整 (P0/P1/P2/INFO)
        "assert {s.value for s in Severity} == {'p0', 'p1', 'p2', 'info'}; "
        # 6. 静态 marker — 防 dual-path 退役未替换 + 防 fail-loud 实现回退
        "from pathlib import Path; "
        f"alert_path = Path(r'{backend_path_str}') / 'qm_platform' / 'observability' / 'alert.py'; "
        "src = alert_path.read_text(encoding='utf-8'); "
        "assert 'ON CONFLICT (dedup_key) DO UPDATE' in src, "
        "'PG dedup ON CONFLICT 路径必存'; "
        "assert 'AlertDispatchError' in src and 'fail-loud' in src.lower(), "
        "'fail-loud 实现必存 (铁律 33)'; "
        "assert 'FOR UPDATE' in src, 'SELECT FOR UPDATE 行锁必存 (跨进程并发安全)'; "
        # 7. Migration SQL + rollback 文件存在 + 含 ON CONFLICT-friendly schema
        f"mig = Path(r'{backend_path_str}') / 'migrations' / 'alert_dedup.sql'; "
        "assert mig.exists(), 'migration 文件丢失'; "
        "mig_src = mig.read_text(encoding='utf-8'); "
        "assert 'PRIMARY KEY' in mig_src and 'dedup_key' in mig_src; "
        "assert 'TIMESTAMP WITH TIME ZONE' in mig_src, "
        "'tz-aware timestamp (铁律 41) 必存'; "
        f"rb = Path(r'{backend_path_str}') / 'migrations' / 'alert_dedup_rollback.sql'; "
        "assert rb.exists(), 'rollback 文件丢失'; "
        "assert 'DROP TABLE' in rb.read_text(encoding='utf-8'); "
        # 8. MVP 4.1 设计稿存在 + 引 Blueprint Framework #7
        f"design = Path(r'{project_root_str}') / 'docs' / 'mvp' / 'MVP_4_1_observability.md'; "
        "assert design.exists(), 'MVP 4.1 设计稿必存'; "
        "design_src = design.read_text(encoding='utf-8'); "
        "assert 'Framework #7' in design_src or 'framework #7' in design_src.lower(); "
        "print('OK mvp_4_1_batch_1_alert_router boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_1_alert_router_imports_and_contracts():
    """subprocess Python 真启动: SDK 导出 + ABC 关系 + 静态 markers + migration 文件."""
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
    assert "OK mvp_4_1_batch_1_alert_router boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
