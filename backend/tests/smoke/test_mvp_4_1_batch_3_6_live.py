"""MVP 4.1 batch 3.6 — rolling_wf + services_healthcheck Platform SDK live smoke."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _build_smoke_code() -> str:
    backend_path_str = str(PROJECT_ROOT / "backend")
    project_root_str = str(PROJECT_ROOT)
    scripts_path = str(PROJECT_ROOT / "scripts")
    return (
        "import platform as _stdlib_platform; "
        "_stdlib_platform.python_implementation(); "
        "import sys; "
        f"sys.path.insert(0, r'{backend_path_str}'); "
        f"sys.path.insert(0, r'{project_root_str}'); "
        f"sys.path.insert(0, r'{scripts_path}'); "
        # 1. rolling_wf imports OK
        "import rolling_wf as rwf; "
        "assert hasattr(rwf, '_send_alert_via_platform_sdk'); "
        "assert hasattr(rwf, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(rwf, '_get_rules_engine'); "
        "assert hasattr(rwf, '_send_dingtalk'); "
        # 2. services_healthcheck imports OK
        "import services_healthcheck as svc; "
        "assert hasattr(svc, '_send_alert_via_platform_sdk'); "
        "assert hasattr(svc, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(svc, '_get_rules_engine'); "
        "assert hasattr(svc, '_build_alert_body'); "
        "assert hasattr(svc, 'send_alert'); "
        # 3. yaml 含新规则
        "from pathlib import Path; "
        "from qm_platform.observability import AlertRulesEngine; "
        f"yaml_path = Path(r'{project_root_str}') / 'configs' / 'alert_rules.yaml'; "
        "engine = AlertRulesEngine.from_yaml(yaml_path); "
        "rule_names = {r.name for r in engine.rules}; "
        "assert 'p0_services_healthcheck_critical' in rule_names; "
        # batch 3.6 code-reviewer P2.1: p2_services_healthcheck_degraded 删 (dead rule, SDK 永远 P0)
        "assert 'p2_services_healthcheck_degraded' not in rule_names; "
        "assert 'p1_rolling_wf_regression' in rule_names; "
        "assert 'p2_rolling_wf_regression' in rule_names; "
        # 4. 静态 marker
        f"src_rwf = (Path(r'{scripts_path}') / 'rolling_wf.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_rwf; "
        "assert 'AlertDispatchError' in src_rwf; "
        "assert 'rolling_wf:summary:' in src_rwf; "
        f"src_svc = (Path(r'{scripts_path}') / 'services_healthcheck.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_svc; "
        "assert 'AlertDispatchError' in src_svc; "
        "assert 'services_healthcheck:' in src_svc; "
        "print('OK mvp_4_1_batch_3_6 boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_3_6_rolling_wf_services_sdk_migration():
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
    assert "OK mvp_4_1_batch_3_6 boot" in result.stdout
