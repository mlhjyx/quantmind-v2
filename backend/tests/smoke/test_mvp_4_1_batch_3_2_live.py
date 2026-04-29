"""MVP 4.1 batch 3.2 — pt_audit Platform SDK 迁移 live smoke (铁律 10b)."""
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
    scripts_path = str(PROJECT_ROOT / "scripts")
    return (
        "import platform as _stdlib_platform; "
        "_stdlib_platform.python_implementation(); "
        "import sys; "
        f"sys.path.insert(0, r'{backend_path_str}'); "
        f"sys.path.insert(0, r'{project_root_str}'); "
        f"sys.path.insert(0, r'{scripts_path}'); "
        # 1. pt_audit module 可 import 不破
        "import pt_audit as pa; "
        # 2. SDK 迁移函数都存在
        "assert hasattr(pa, '_send_alert_via_platform_sdk'); "
        "assert hasattr(pa, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(pa, '_build_alert_text'); "
        "assert hasattr(pa, '_get_rules_engine'); "
        "assert hasattr(pa, 'send_aggregated_alert'); "
        # 3. settings flag
        "from app.config import settings; "
        "assert settings.OBSERVABILITY_USE_PLATFORM_SDK is True; "
        # 4. yaml 含 pt_audit P0/P1/P2 显式规则
        "from pathlib import Path; "
        "from qm_platform.observability import AlertRulesEngine; "
        f"yaml_path = Path(r'{project_root_str}') / 'configs' / 'alert_rules.yaml'; "
        "engine = AlertRulesEngine.from_yaml(yaml_path); "
        "rule_names = {r.name for r in engine.rules}; "
        "assert 'p0_pt_audit_findings' in rule_names; "
        "assert 'p1_pt_audit_findings' in rule_names; "
        "assert 'p2_pt_audit_findings' in rule_names; "
        # 5. 静态 marker
        f"src_path = Path(r'{scripts_path}') / 'pt_audit.py'; "
        "src = src_path.read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src; "
        "assert 'get_alert_router' in src; "
        "assert 'AlertRulesEngine' in src; "
        "assert 'AlertDispatchError' in src, 'fail-loud propagation 必存 (铁律 33)'; "
        "assert 'pt_audit:summary:' in src or 'lru_cache' in src; "
        "print('OK mvp_4_1_batch_3_2 boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_3_2_pt_audit_sdk_migration():
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
    assert "OK mvp_4_1_batch_3_2 boot" in result.stdout
