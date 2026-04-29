"""MVP 4.1 batch 3.3 — ic_monitor + monitor_factor_ic Platform SDK 迁移 live smoke."""
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
        # 1. ic_monitor module 可 import
        "import ic_monitor as im; "
        "assert hasattr(im, '_send_alert_via_platform_sdk'); "
        "assert hasattr(im, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(im, '_get_rules_engine'); "
        "assert hasattr(im, '_send_dingtalk'); "
        # 2. monitor_factor_ic module 可 import
        "import monitor_factor_ic as mfi; "
        "assert hasattr(mfi, '_send_alert_via_platform_sdk'); "
        "assert hasattr(mfi, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(mfi, '_get_rules_engine'); "
        "assert hasattr(mfi, 'send_dingtalk'); "
        # 3. yaml 含新规则
        "from pathlib import Path; "
        "from qm_platform.observability import AlertRulesEngine; "
        f"yaml_path = Path(r'{project_root_str}') / 'configs' / 'alert_rules.yaml'; "
        "engine = AlertRulesEngine.from_yaml(yaml_path); "
        "rule_names = {r.name for r in engine.rules}; "
        "assert 'p0_ic_monitor_reversal' in rule_names; "
        "assert 'p1_ic_monitor_drop' in rule_names; "
        "assert 'p0_monitor_factor_ic_retired' in rule_names; "
        "assert 'p1_monitor_factor_ic_warning' in rule_names; "
        "assert 'info_monitor_factor_ic_health' in rule_names; "
        # 4. 静态 marker
        f"src_im = (Path(r'{scripts_path}') / 'ic_monitor.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_im; "
        "assert 'AlertDispatchError' in src_im; "
        "assert 'ic_monitor:summary:' in src_im; "
        f"src_mfi = (Path(r'{scripts_path}') / 'monitor_factor_ic.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_mfi; "
        "assert 'AlertDispatchError' in src_mfi; "
        "assert 'monitor_factor_ic:summary:' in src_mfi; "
        "print('OK mvp_4_1_batch_3_3 boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_3_3_ic_monitors_sdk_migration():
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
    assert "OK mvp_4_1_batch_3_3 boot" in result.stdout
