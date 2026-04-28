"""MVP 3.4 batch 4 — 4 域 dual-write live smoke (铁律 10b).

subprocess 真启动验证: signal_service / execution_service / risk_engine 都 import
qm_platform.observability.OutboxWriter 不破, 关键 dual-write 注入点存在.
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
        # 验 3 个 dual-write target service module 都 import 成功
        "import app.services.signal_service as sig_svc; "
        "import app.services.execution_service as exec_svc; "
        "import qm_platform.risk.engine as risk_eng; "
        # 验 OutboxWriter 可访问 (3 服务 lazy import 都依赖此入口)
        "from qm_platform.observability import OutboxWriter; "
        "assert callable(OutboxWriter), 'OutboxWriter 必须 callable'; "
        # 验 batch 4 注入 marker 文本在 source 中 (静态防 dual-write 被移除)
        "from pathlib import Path; "
        f"signal_path = Path(r'{backend_path_str}') / 'app' / 'services' / 'signal_service.py'; "
        "assert 'MVP 3.4 batch 4 dual-write' in signal_path.read_text(encoding='utf-8'), "
        "'signal_service.py batch 4 dual-write marker 丢失'; "
        f"exec_path = Path(r'{backend_path_str}') / 'app' / 'services' / 'execution_service.py'; "
        "assert exec_path.read_text(encoding='utf-8').count('MVP 3.4 batch 4 dual-write') == 2, "
        "'execution_service.py 应有 2 个 batch 4 dual-write block (paper + live)'; "
        f"risk_path = Path(r'{backend_path_str}') / 'qm_platform' / 'risk' / 'engine.py'; "
        "assert 'MVP 3.4 batch 4 dual-write' in risk_path.read_text(encoding='utf-8'), "
        "'risk/engine.py batch 4 dual-write marker 丢失'; "
        "print('OK 4domain_dual_write boot')"
    )


@pytest.mark.smoke
def test_4domain_dual_write_imports_and_markers():
    """subprocess Python 真启动: 3 service imports + OutboxWriter + 静态 marker."""
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
    assert "OK 4domain_dual_write boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
