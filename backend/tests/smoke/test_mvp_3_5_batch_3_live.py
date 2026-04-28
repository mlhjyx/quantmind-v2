"""MVP 3.5 batch 3 — Strategy Gates 真启动 smoke (铁律 10b).

subprocess 真启动验证:
  - Strategy Gates concrete (G1' / G2' / G3') + PlatformStrategyEvaluator + helpers import
  - default_strategy_pipeline factory 可构造
  - ADR-014 文件存在 (静态 marker)
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
        # batch 3 Strategy Gates + evaluator + helper import
        "from qm_platform.eval import ("
        "    PlatformStrategyEvaluator, build_strategy_context, "
        "    StrategyG1SharpeGate, StrategyG2MaxDrawdownGate, StrategyG3RegressionGate, "
        "    STRATEGY_G1_PVALUE_THRESHOLD, STRATEGY_G2_DEFAULT_MAX_DD, "
        "    default_strategy_pipeline, GateContext"
        "); "
        "assert STRATEGY_G1_PVALUE_THRESHOLD == 0.05; "
        "assert STRATEGY_G2_DEFAULT_MAX_DD == -0.30; "
        "assert callable(PlatformStrategyEvaluator); "
        "assert callable(build_strategy_context); "
        "assert callable(default_strategy_pipeline); "
        # default_strategy_pipeline 真构造 + 3 gate
        "ctx = build_strategy_context('S1_smoke'); "
        "assert ctx.factor_name == 'S1_smoke'; "
        "p = default_strategy_pipeline(context_loader=lambda n: ctx); "
        "names = [g.name for g in p._gates]; "
        "assert 'G1prime_sharpe_bootstrap' in names; "
        "assert 'G2prime_max_drawdown' in names; "
        "assert 'G3prime_regression_max_diff' in names; "
        "assert len(names) == 3, f'expected 3 strategy gates, got {len(names)}: {names}'; "
        # ADR-014 文件存在
        "from pathlib import Path; "
        f"adr_path = Path(r'{project_root_str}') / 'docs' / 'adr' / 'ADR-014-evaluation-gate-contract.md'; "
        "assert adr_path.exists(), 'ADR-014 文件缺失'; "
        "adr_src = adr_path.read_text(encoding='utf-8'); "
        "assert 'G1prime' in adr_src or 'G1\\'' in adr_src, 'ADR-014 缺 G1prime/G1 标识'; "
        "assert '铁律 15' in adr_src, 'ADR-014 缺铁律 15 引用 (G3prime regression)'; "
        # 关键源码 marker
        f"sg_path = Path(r'{backend_path_str}') / 'qm_platform' / 'eval' / 'strategy_gates.py'; "
        "sg_src = sg_path.read_text(encoding='utf-8'); "
        "assert 'STRATEGY_G2_DEFAULT_MAX_DD' in sg_src; "
        "assert 'StrategyG3RegressionGate' in sg_src; "
        f"se_path = Path(r'{backend_path_str}') / 'qm_platform' / 'eval' / 'strategy_evaluator.py'; "
        "assert se_path.exists(), 'strategy_evaluator.py 缺失'; "
        "print('OK mvp_3_5_batch_3 boot')"
    )


@pytest.mark.smoke
def test_mvp_3_5_batch_3_strategy_gates_imports_and_markers():
    """subprocess Python 真启动: Strategy Gates SDK + ADR-014 + 静态 marker."""
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
    assert "OK mvp_3_5_batch_3 boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
