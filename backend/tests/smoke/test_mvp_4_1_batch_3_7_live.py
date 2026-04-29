"""MVP 4.1 batch 3.7 — pull_moneyflow + pg_backup Platform SDK live smoke."""
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
        # 1. pull_moneyflow imports OK
        "import pull_moneyflow as pmf; "
        "assert hasattr(pmf, '_send_alert_via_platform_sdk'); "
        "assert hasattr(pmf, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(pmf, '_get_rules_engine'); "
        "assert hasattr(pmf, '_send_moneyflow_alert'); "
        # 2. pg_backup imports OK
        "import pg_backup as pgb; "
        "assert hasattr(pgb, '_send_alert_via_platform_sdk'); "
        "assert hasattr(pgb, '_send_alert_via_legacy_notification'); "
        "assert hasattr(pgb, '_get_rules_engine'); "
        "assert hasattr(pgb, 'send_alert'); "
        # 3. yaml 含新规则
        "from pathlib import Path; "
        "from qm_platform.observability import AlertRulesEngine; "
        f"yaml_path = Path(r'{project_root_str}') / 'configs' / 'alert_rules.yaml'; "
        "engine = AlertRulesEngine.from_yaml(yaml_path); "
        "rule_names = {r.name for r in engine.rules}; "
        "assert 'p0_pull_moneyflow_data_delay' in rule_names; "
        "assert 'p0_pg_backup_failed' in rule_names; "
        # 4. 静态 marker
        f"src_pmf = (Path(r'{scripts_path}') / 'pull_moneyflow.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_pmf; "
        "assert 'AlertDispatchError' in src_pmf; "
        "assert 'pull_moneyflow:summary:' in src_pmf; "
        f"src_pgb = (Path(r'{scripts_path}') / 'pg_backup.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_pgb; "
        "assert 'AlertDispatchError' in src_pgb; "
        "assert 'pg_backup:summary:' in src_pgb; "
        "print('OK mvp_4_1_batch_3_7 boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_3_7_moneyflow_pgbackup_sdk_migration():
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
    assert "OK mvp_4_1_batch_3_7 boot" in result.stdout
