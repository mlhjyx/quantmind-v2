"""MVP 3.3 批 1 PlatformSignalPipeline live smoke (铁律 10b).

subprocess 真启动验证 module-top imports 不破 (compose + generate SDK 可访问).
对齐 test_mvp_3_1_risk_live pattern: 显式 sys.path 注入 + LL-052 platform shadow 预热.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _build_smoke_code() -> str:
    """LL-052 shadow 修复 + sys.path 注入 + import 链."""
    return (
        "import platform as _stdlib_platform; "
        "_stdlib_platform.python_implementation(); "
        "import sys; "
        f"sys.path.insert(0, r'{PROJECT_ROOT / 'backend'}'); "
        f"sys.path.insert(0, r'{PROJECT_ROOT}'); "
        "from backend.qm_platform.signal.pipeline import ("
        "PlatformSignalPipeline, UniverseEmpty, FactorStaleError, _COMPOSE_STRATEGY_ID"
        "); "
        "from backend.qm_platform.signal import ("
        "PlatformSignalPipeline as PSP_root, UniverseEmpty as UE_root"
        "); "
        "assert PlatformSignalPipeline is PSP_root, 'export 不一致 pipeline'; "
        "assert UniverseEmpty is UE_root, 'export 不一致 UniverseEmpty'; "
        "assert _COMPOSE_STRATEGY_ID == 'compose:factor_pool', 'sentinel 漂移'; "
        "from engines.signal_engine import PAPER_TRADING_CONFIG; "
        "pipe = PlatformSignalPipeline(); "
        "assert pipe.base_config is PAPER_TRADING_CONFIG, 'default config 不是 SSOT'; "
        "assert callable(pipe.compose), 'compose 未实现'; "
        "assert callable(pipe.generate), 'generate 未实现'; "
        "print('OK signal pipeline boot')"
    )


@pytest.mark.smoke
def test_signal_pipeline_imports_and_construct():
    """subprocess Python 真启动: import + 实例化 + 双入口签名验证."""
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
    assert "OK signal pipeline boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
