"""Smoke: MVP 3.1 批 3 CircuitBreaker Rule Adapter 生产入口真启动验证 (铁律 10b).

验证链路 (subprocess 隔离, 避母进程 import 污染):
  1. `backend.platform.risk.rules.circuit_breaker.CircuitBreakerRule` 可 import
  2. `app.services.risk_wiring.build_circuit_breaker_rule` factory 可 import
  3. CircuitBreakerRule 实例化 (注入 get_sync_conn + PAPER_INITIAL_CAPITAL)
  4. root_rule_id_for 契约 (cb_escalate_l4 → 'circuit_breaker')
  5. `daily_pipeline.risk_daily_check_task` 内部含 `build_circuit_breaker_rule`
     (source 反射 check, 不真调 task — 避免真 DB 依赖)

铁律 10b 意图: 单测 CWD=project root 永远绿不等于生产可用, smoke 必须从生产启动
路径 subprocess 真启动, 捕 import-time / top-level 执行错误. 本 smoke 不跑 L4 逻辑
(无 risk_control_service DB), 仅验证 import + 契约 — 具体行为覆盖在 L1 unit tests.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.smoke
def test_mvp_3_1_batch_3_circuit_breaker_imports() -> None:
    """Platform CB rule + wiring factory + daily task 注入 subprocess import 不炸."""
    project_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                # MVP 1.1b LL-052 shadow 修复: 预热 stdlib platform 再添加 backend/
                "import platform as _stdlib_platform; "
                "_stdlib_platform.python_implementation(); "
                "import sys; "
                f"sys.path.insert(0, r'{project_root / 'backend'}'); "
                f"sys.path.insert(0, r'{project_root}'); "
                # 1. Platform CB rule 可 import
                "from backend.platform.risk.rules.circuit_breaker import CircuitBreakerRule; "
                # 2. App wiring factory 可 import
                "from app.services.risk_wiring import build_circuit_breaker_rule; "
                # 3. Factory 实例化 (注入真 get_sync_conn + settings.PAPER_INITIAL_CAPITAL)
                "rule = build_circuit_breaker_rule(); "
                "assert rule.rule_id == 'circuit_breaker', "
                "f'rule_id drifted: {rule.rule_id}'; "
                "assert rule.action == 'alert_only', "
                "f'action drifted: {rule.action}'; "
                "assert rule.severity.value == 'p1', "
                "f'severity drifted: {rule.severity}'; "
                # 4. root_rule_id_for 契约 (ownership + passthrough)
                "assert rule.root_rule_id_for('cb_escalate_l4') == 'circuit_breaker', "
                "'escalate ownership drifted'; "
                "assert rule.root_rule_id_for('cb_recover_l0') == 'circuit_breaker', "
                "'recover ownership drifted'; "
                "assert rule.root_rule_id_for('pms_l1') == 'pms_l1', "
                "'passthrough drifted (should not claim pms)'; "
                # 5. daily_pipeline 注入 CB 反射验证 (source contains build_circuit_breaker_rule)
                "from app.tasks.daily_pipeline import risk_daily_check_task; "
                "import inspect; "
                "src = inspect.getsource(risk_daily_check_task); "
                "assert 'build_circuit_breaker_rule' in src, "
                "'risk_daily_check_task 未注入 CB adapter (expected extra_rules=[build_circuit_breaker_rule()])'; "
                # 6. rules package __all__ 含 CircuitBreakerRule
                "from backend.platform.risk.rules import CircuitBreakerRule as _CB2; "
                "assert _CB2 is CircuitBreakerRule; "
                "print('OK')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(project_root),
    )
    assert result.returncode == 0, (
        f"MVP 3.1 batch 3 CB smoke import failed:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    assert "OK" in result.stdout, f"Assertion(s) missing: {result.stdout}"
