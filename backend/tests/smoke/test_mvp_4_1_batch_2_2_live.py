"""MVP 4.1 batch 2.2 — AlertRulesEngine + HealthReport live smoke (铁律 10b)."""
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
        # 1. SDK 导出符号 (含 batch 1 + 2.1 + 2.2)
        "from qm_platform.observability import ("
        "    AlertRule, AlertRuleError, AlertRulesEngine, "
        "    HealthReport, HealthStatus, safe_check, aggregate_status, "
        "    PostgresMetricExporter, MetricExportError, "
        "    PostgresAlertRouter, DingTalkChannel, AlertDispatchError, "
        "    OutboxWriter, MetricExporter, AlertRouter, EventBus"
        "); "
        # 2. yaml 默认规则集 load 真跑
        "from pathlib import Path; "
        f"yaml_path = Path(r'{project_root_str}') / 'configs' / 'alert_rules.yaml'; "
        "assert yaml_path.exists(), 'configs/alert_rules.yaml 必存'; "
        "engine = AlertRulesEngine.from_yaml(yaml_path); "
        "assert len(engine.rules) >= 10, f'默认规则集应 >= 10 条, got {len(engine.rules)}'; "
        # 3. catchall 规则存在 (3 severity 全覆盖)
        "rule_names = {r.name for r in engine.rules}; "
        "assert 'catchall_p0' in rule_names; "
        "assert 'catchall_p1' in rule_names; "
        "assert 'catchall_p2' in rule_names; "
        # 4. HealthReport 实例化
        "r = HealthReport(framework='x', status='ok'); "
        "assert r.to_dict()['status'] == 'ok'; "
        # 5. safe_check 不抛
        "boom = lambda: (_ for _ in ()).throw(RuntimeError('x')); "
        "rep = safe_check('test', boom); "
        "assert rep.status == 'down'; "
        # 6. aggregate_status 三档
        "assert aggregate_status([HealthReport(framework='a', status='ok')]) == 'ok'; "
        "assert aggregate_status([HealthReport(framework='a', status='down')]) == 'down'; "
        "assert aggregate_status([]) == 'down'; "
        # 7. 静态 marker
        f"rules_path = Path(r'{backend_path_str}') / 'qm_platform' / 'observability' / 'rules.py'; "
        "src = rules_path.read_text(encoding='utf-8'); "
        "assert 'AlertRulesEngine' in src and 'from_yaml' in src; "
        "assert 'AlertRuleError' in src; "
        f"health_path = Path(r'{backend_path_str}') / 'qm_platform' / 'observability' / 'health.py'; "
        "h_src = health_path.read_text(encoding='utf-8'); "
        "assert 'safe_check' in h_src and 'aggregate_status' in h_src; "
        "assert 'datetime.now(UTC)' in h_src or 'tzinfo == UTC' in h_src or 'UTC)' in h_src, "
        "'UTC tz-aware 必存 (铁律 41)'; "
        "print('OK mvp_4_1_batch_2_2 boot')"
    )


@pytest.mark.smoke
def test_mvp_4_1_batch_2_2_rules_health_imports_and_yaml_load():
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
    assert "OK mvp_4_1_batch_2_2 boot" in result.stdout
