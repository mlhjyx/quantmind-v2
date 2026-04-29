"""MVP 4.1 batch 3.8 — intraday_monitor Platform SDK live smoke."""
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
        # 1. intraday_monitor imports OK
        "import intraday_monitor as im; "
        "assert hasattr(im, '_send_alert_via_platform_sdk'); "
        "assert hasattr(im, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(im, '_get_rules_engine'); "
        "assert hasattr(im, '_load_rules_engine_cached'); "
        "assert hasattr(im, 'send_alert'); "
        # 2. send_alert 签名含 kind / details_extra
        "import inspect; "
        "sig = inspect.signature(im.send_alert); "
        "assert 'kind' in sig.parameters; "
        "assert 'details_extra' in sig.parameters; "
        # 3. yaml 含新规则
        "from pathlib import Path; "
        "from qm_platform.observability import AlertRulesEngine; "
        f"yaml_path = Path(r'{project_root_str}') / 'configs' / 'alert_rules.yaml'; "
        "engine = AlertRulesEngine.from_yaml(yaml_path); "
        "rule_names = {r.name for r in engine.rules}; "
        "assert 'p0_intraday_portfolio_drop' in rule_names; "
        "assert 'p1_intraday_alerts' in rule_names; "
        # 4. 静态 marker
        f"src_im = (Path(r'{scripts_path}') / 'intraday_monitor.py').read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src_im; "
        "assert 'AlertDispatchError' in src_im; "
        "assert 'kind=\"qmt_disconnect\"' in src_im; "
        "assert 'kind=\"portfolio_drop\"' in src_im; "
        "assert 'kind=\"emergency_stock_batch\"' in src_im; "
        "print('OK mvp_4_1_batch_3_8 boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_3_8_intraday_monitor_sdk_migration():
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
    assert "OK mvp_4_1_batch_3_8 boot" in result.stdout
