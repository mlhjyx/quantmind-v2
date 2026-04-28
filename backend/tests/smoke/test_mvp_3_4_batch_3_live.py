"""MVP 3.4 batch 3 OutboxBackedAuditTrail live smoke (铁律 10b).

subprocess 真启动验证: qm_platform.signal.audit module-top imports 不破,
OutboxBackedAuditTrail 可访问 + AuditMissing exception class 导出 + 双 audit
模式共存 (Stub + Outbox 都通过 ABC).
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
        "from qm_platform.signal import ("
        "OutboxBackedAuditTrail, StubExecutionAuditTrail, "
        "AuditMissing, AuditChain, ExecutionAuditTrail"
        "); "
        "assert issubclass(OutboxBackedAuditTrail, ExecutionAuditTrail), "
        "'OutboxBackedAuditTrail 必须实现 ExecutionAuditTrail ABC'; "
        "assert issubclass(StubExecutionAuditTrail, ExecutionAuditTrail), "
        "'Stub 也必须实现 ABC (双模式互补 contract)'; "
        "assert issubclass(AuditMissing, RuntimeError), "
        "'AuditMissing 必须是 RuntimeError 子类'; "
        # 不实例化 (会拉 DB conn), 仅验类 + ABC 关系
        "trail = OutboxBackedAuditTrail(conn_factory=lambda: None); "
        "assert callable(trail.record), 'record() 未实现'; "
        "assert callable(trail.trace), 'trace() 未实现'; "
        "print('OK audit_outbox_concrete boot')"
    )


@pytest.mark.smoke
def test_outbox_audit_imports_and_abc():
    """subprocess Python 真启动: import + ABC + 实例化."""
    result = subprocess.run(
        [sys.executable, "-c", _build_smoke_code()],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"smoke failed (exit={result.returncode}): stderr={result.stderr}"
    )
    assert "OK audit_outbox_concrete boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
