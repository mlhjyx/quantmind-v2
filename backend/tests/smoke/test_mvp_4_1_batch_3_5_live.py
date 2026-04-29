"""MVP 4.1 batch 3.5 — daily_reconciliation + factor_health_daily Platform SDK live smoke."""
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
        # 1. daily_reconciliation imports OK
        "import daily_reconciliation as dr; "
        "assert hasattr(dr, '_send_alert_via_platform_sdk'); "
        "assert hasattr(dr, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(dr, '_get_rules_engine'); "
        "assert hasattr(dr, 'send_alert'); "
        # 2. factor_health_daily imports OK
        "import factor_health_daily as fhd; "
        "assert hasattr(fhd, '_send_alert_via_platform_sdk'); "
        "assert hasattr(fhd, '_send_alert_unified'); "
        "assert hasattr(fhd, '_get_rules_engine'); "
        # 3. yaml 含新规则
        "from pathlib import Path; "
        "from qm_platform.observability import AlertRulesEngine; "
        f"yaml_path = Path(r'{project_root_str}') / 'configs' / 'alert_rules.yaml'; "
        "engine = AlertRulesEngine.from_yaml(yaml_path); "
        "rule_names = {r.name for r in engine.rules}; "
        "assert 'p0_factor_health_decay' in rule_names; "
        "assert 'p1_factor_health_decay' in rule_names; "
        "assert 'p0_daily_reconciliation_drift' in rule_names; "
        "assert 'p1_daily_reconciliation_drift' in rule_names; "
        # 4. 静态 marker
        f"src_dr = (Path(r'{scripts_path}') / 'daily_reconciliation.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_dr; "
        "assert 'AlertDispatchError' in src_dr; "
        "assert 'daily_reconciliation:summary:' in src_dr; "
        f"src_fhd = (Path(r'{scripts_path}') / 'factor_health_daily.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_fhd; "
        "assert 'AlertDispatchError' in src_fhd; "
        "assert 'factor_health:summary:' in src_fhd; "
        "print('OK mvp_4_1_batch_3_5 boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_3_5_recon_health_sdk_migration():
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
    assert "OK mvp_4_1_batch_3_5 boot" in result.stdout
