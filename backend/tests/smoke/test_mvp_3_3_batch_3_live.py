"""MVP 3.3 batch 3 StubExecutionAuditTrail live smoke (铁律 10b).

subprocess 真启动验证: import + 实例化 + record() + trace() raise.
对齐 batch 1/2 smoke pattern: LL-052 platform shadow + sys.path 注入.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _build_smoke_code() -> str:
    """LL-052 shadow + sys.path 注入 + import + record + trace 验证."""
    backend_path_str = str(PROJECT_ROOT / "backend")
    project_root_str = str(PROJECT_ROOT)
    return "\n".join(
        [
            "import platform as _stdlib_platform",
            "_stdlib_platform.python_implementation()",
            "import sys",
            f"sys.path.insert(0, r'{backend_path_str}')",
            f"sys.path.insert(0, r'{project_root_str}')",
            "from backend.qm_platform.signal.audit import (",
            "    StubExecutionAuditTrail, AuditMissing,",
            ")",
            "from backend.qm_platform.signal import (",
            "    StubExecutionAuditTrail as Stub_root,",
            "    AuditMissing as AuditMissing_root,",
            ")",
            "assert StubExecutionAuditTrail is Stub_root, 'export 不一致 audit'",
            "assert AuditMissing is AuditMissing_root, 'export 不一致 AuditMissing'",
            # 实例化 + record
            "stub = StubExecutionAuditTrail()",
            "assert stub.record_count == 0, 'initial record_count 不为 0'",
            "stub.record('signal.composed', {'strategy_id': 's1'})",
            "stub.record('order.routed', {'order_id': 'abc', 'strategy_id': 's1'})",
            "assert stub.record_count == 2, f'expected 2 records, got {stub.record_count}'",
            # trace() 必 raise
            "try:",
            "    stub.trace('fill-1')",
            "    raise AssertionError('trace 应 raise NotImplementedError')",
            "except NotImplementedError:",
            "    pass",
            # AuditMissing 可 raise (RuntimeError 子类)
            "assert issubclass(AuditMissing, RuntimeError), 'AuditMissing 必 RuntimeError 子类'",
            "print('OK audit stub boot')",
        ]
    )


@pytest.mark.smoke
def test_audit_stub_imports_and_record():
    """subprocess Python 真启动: import + record + trace raise."""
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
    assert "OK audit stub boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
