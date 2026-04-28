"""MVP 4.1 batch 3.1 — data_quality_check Platform SDK 迁移 live smoke (铁律 10b)."""
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
        f"sys.path.insert(0, r'{PROJECT_ROOT / 'scripts'}'); "
        # 1. data_quality_check module 可 import 不破 (铁律 10b)
        "import data_quality_check as dq; "
        # 2. SDK 迁移函数都存在
        "assert hasattr(dq, '_send_alert_via_platform_sdk'); "
        "assert hasattr(dq, '_send_alert_via_legacy_dingtalk'); "
        "assert hasattr(dq, '_max_severity'); "
        "assert hasattr(dq, '_build_alert_content'); "
        "assert hasattr(dq, 'send_dingtalk_alert'); "
        # 3. settings flag 存在 + 默认 True
        "from app.config import settings; "
        "assert hasattr(settings, 'OBSERVABILITY_USE_PLATFORM_SDK'); "
        "assert settings.OBSERVABILITY_USE_PLATFORM_SDK is True, '默认必走 SDK path'; "
        # 4. severity 提取正确
        "assert dq._max_severity(['[P0] x']) == 'p0'; "
        "assert dq._max_severity(['[P1] x']) == 'p1'; "
        "assert dq._max_severity(['plain']) == 'p1'; "
        # 5. yaml rule 含 data_quality_check 显式规则
        "from pathlib import Path; "
        "from qm_platform.observability import AlertRulesEngine; "
        f"yaml_path = Path(r'{project_root_str}') / 'configs' / 'alert_rules.yaml'; "
        "engine = AlertRulesEngine.from_yaml(yaml_path); "
        "rule_names = {r.name for r in engine.rules}; "
        "assert 'p0_data_quality_pre_signal' in rule_names; "
        "assert 'p1_data_quality_pre_signal' in rule_names; "
        # 6. 静态 marker
        f"dq_path = Path(r'{PROJECT_ROOT / 'scripts'}') / 'data_quality_check.py'; "
        "src = dq_path.read_text(encoding='utf-8'); "
        "assert 'OBSERVABILITY_USE_PLATFORM_SDK' in src; "
        "assert 'PostgresAlertRouter' in src or 'get_alert_router' in src; "
        "assert 'AlertRulesEngine' in src; "
        "assert 'AlertDispatchError' in src, 'fail-loud propagation 必存 (铁律 33)'; "
        "print('OK mvp_4_1_batch_3_1 boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_3_1_data_quality_check_sdk_migration():
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
    assert "OK mvp_4_1_batch_3_1 boot" in result.stdout
