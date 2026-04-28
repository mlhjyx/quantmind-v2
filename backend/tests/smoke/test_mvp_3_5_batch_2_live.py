"""MVP 3.5 batch 2 — factor_lifecycle 双路径接入真启动 smoke (铁律 10b).

subprocess 真启动验证:
  - engines.factor_lifecycle 5 个新 API import (DualPathComparison/build_lifecycle_context/
    compare_paths/default_lifecycle_pipeline + 老 evaluate_transition 不破)
  - scripts/factor_lifecycle_monitor.py argparse 新增 --compare flag
  - 静态 marker (防注入点被回退)
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
        # batch 2 新 API import
        "from engines.factor_lifecycle import ("
        "    DualPathComparison, build_lifecycle_context, compare_paths, "
        "    default_lifecycle_pipeline, "
        "    evaluate_transition, count_days_below_critical, "  # 老路径不破
        "    FactorStatus, TransitionDecision, "
        "    WARNING_RATIO, CRITICAL_RATIO"
        "); "
        "assert callable(default_lifecycle_pipeline); "
        "assert callable(compare_paths); "
        "assert callable(build_lifecycle_context); "
        # 老路径仍可调用
        "assert callable(evaluate_transition); "
        # context_loader 注入实测
        "ctx = build_lifecycle_context('x'); "
        "assert ctx.factor_name == 'x'; "
        "p = default_lifecycle_pipeline(context_loader=lambda n: ctx); "
        "names = [g.name for g in p._gates]; "
        "assert 'G1_ic_significance' in names and 'G10_hypothesis' in names, names; "
        # monitor.py 静态 marker
        "from pathlib import Path; "
        f"monitor_path = Path(r'{project_root_str}') / 'scripts' / 'factor_lifecycle_monitor.py'; "
        "src = monitor_path.read_text(encoding='utf-8'); "
        "assert '--compare' in src, '--compare flag 缺失'; "
        "assert 'DUAL_PATH_EVENT_TYPE' in src, 'DUAL_PATH_EVENT_TYPE 缺失'; "
        "assert '_evaluate_new_path' in src, '_evaluate_new_path 缺失'; "
        "assert 'compare_paths' in src, 'compare_paths import 缺失'; "
        # factor_lifecycle.py 静态 marker
        f"lc_path = Path(r'{backend_path_str}') / 'engines' / 'factor_lifecycle.py'; "
        "lc_src = lc_path.read_text(encoding='utf-8'); "
        "assert 'MVP 3.5 batch 2' in lc_src, 'batch 2 marker 缺失'; "
        "assert 'DualPathComparison' in lc_src, 'DualPathComparison 缺失'; "
        "assert 'default_lifecycle_pipeline' in lc_src, 'default_lifecycle_pipeline 缺失'; "
        "print('OK mvp_3_5_batch_2 boot')"
    )


@pytest.mark.smoke
def test_mvp_3_5_batch_2_lifecycle_dual_path_imports_and_markers():
    """subprocess Python 真启动: 5 新 API + 老路径未破 + monitor --compare flag + 静态 marker."""
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
    assert "OK mvp_3_5_batch_2 boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
