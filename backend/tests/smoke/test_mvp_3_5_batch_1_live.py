"""MVP 3.5 batch 1 — EvaluationPipeline 真启动 smoke (铁律 10b).

subprocess 真启动验证 qm_platform.eval 全套 import + 7 Gate concrete + Pipeline 跑.
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
        # 验 SDK package import
        "from qm_platform.eval import ("
        "    PlatformEvaluationPipeline, EvaluationReport, EvaluationDecision, "
        "    G1IcSignificanceGate, G2CorrelationFilterGate, G3PairedBootstrapGate, "
        "    G4WalkForwardGate, G8BhFdrGate, G9NoveltyAstGate, G10HypothesisGate, "
        "    GateContext, paired_bootstrap_pvalue, t_statistic, benjamini_hochberg_threshold"
        "); "
        # 验 7 Gate 全部 callable + 暴露 .name
        "gates = [G1IcSignificanceGate(), G2CorrelationFilterGate(), G3PairedBootstrapGate(rng_seed=42), "
        "         G4WalkForwardGate(), G8BhFdrGate(), G9NoveltyAstGate(), G10HypothesisGate()]; "
        "names = [g.name for g in gates]; "
        "assert len(set(names)) == 7, f'Gate name dup: {names}'; "
        # 验 Pipeline 构造
        "pipeline = PlatformEvaluationPipeline(gates=gates[:1], context_loader=lambda n: GateContext(factor_name=n)); "
        "assert pipeline is not None; "
        # 验 utils 函数 callable
        "assert callable(paired_bootstrap_pvalue); "
        "assert callable(t_statistic); "
        "assert callable(benjamini_hochberg_threshold); "
        # 验 EvaluationDecision enum 完整
        "assert EvaluationDecision.ACCEPT.value == 'accept'; "
        "assert EvaluationDecision.REJECT.value == 'reject'; "
        "assert EvaluationDecision.WARNING.value == 'warning'; "
        # 验关键源码 marker (静态防新文件被误删)
        "from pathlib import Path; "
        f"util_path = Path(r'{backend_path_str}') / 'qm_platform' / 'eval' / 'utils.py'; "
        "assert 'paired_bootstrap_pvalue' in util_path.read_text(encoding='utf-8'), 'utils.py 关键函数缺失'; "
        f"pipeline_path = Path(r'{backend_path_str}') / 'qm_platform' / 'eval' / 'pipeline.py'; "
        "assert 'PlatformEvaluationPipeline' in pipeline_path.read_text(encoding='utf-8'), 'pipeline.py 关键类缺失'; "
        f"gates_dir = Path(r'{backend_path_str}') / 'qm_platform' / 'eval' / 'gates'; "
        "assert gates_dir.is_dir(), 'gates/ 包目录缺失'; "
        "assert (gates_dir / 'g9_novelty_ast.py').exists(), 'g9_novelty_ast.py 缺失'; "
        "assert (gates_dir / 'g10_hypothesis.py').exists(), 'g10_hypothesis.py 缺失'; "
        "print('OK mvp_3_5_batch_1 boot')"
    )


@pytest.mark.smoke
def test_mvp_3_5_batch_1_pipeline_imports_and_constructs():
    """subprocess Python 真启动: SDK 全套 import + 7 Gate + Pipeline 构造 + 静态 marker."""
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
    assert "OK mvp_3_5_batch_1 boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
