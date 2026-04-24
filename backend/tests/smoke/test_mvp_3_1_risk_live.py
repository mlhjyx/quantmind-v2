"""Smoke: MVP 3.1 批 1 Risk Framework 生产入口真启动验证 (铁律 10b).

验证链路 (subprocess 隔离, 避母进程 import 污染):
  1. `backend.platform.risk` (engine + interface + sources + rules) 可 import
  2. `app.services.risk_wiring` 可 import (wiring 层 DI 契约)
  3. `app.tasks.daily_pipeline.risk_daily_check_task` Celery task 已注册
  4. `app.tasks.beat_schedule.risk-daily-check` schedule 已注册

铁律 10b 意图: 单测 CWD=project root 永远绿不等于生产可用, smoke 必须从生产启动
路径 subprocess 真启动, 捕 import-time / top-level 执行错误. 本 smoke 不跑 L4 逻辑
(无 QMT / Redis / DB), 仅验证 import 不炸 — 具体行为覆盖在 L1 unit tests
(test_risk_engine.py / test_risk_rules_pms.py / test_risk_sources.py PR #57).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.smoke
def test_mvp_3_1_risk_framework_imports() -> None:
    """Platform risk + wiring + Celery task 链路 subprocess import 不炸.

    断言:
      - PlatformRiskEngine / PMSRule / QMTPositionSource 可 import
      - build_risk_engine factory 可 import
      - Celery task daily_pipeline.risk_check 注册
      - Beat schedule risk-daily-check 14:30 MoFr 配置正确
    """
    project_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                # MVP 1.1b LL-052 shadow 修复: 预热 stdlib platform 入 sys.modules 再
                # 添加 backend/ 到 sys.path. 否则 backend.platform 会劫持后续 pandas/structlog
                # 间接 `import platform` 调用 (AttributeError: python_implementation).
                "import platform as _stdlib_platform; "
                "_stdlib_platform.python_implementation(); "
                "import sys; "
                f"sys.path.insert(0, r'{project_root / 'backend'}'); "
                f"sys.path.insert(0, r'{project_root}'); "
                # 1. Platform risk 核心导出
                "from backend.platform.risk import ("
                "PlatformRiskEngine, Position, PositionSource, "
                "PositionSourceError, RiskContext, RiskRule, RuleResult"
                "); "
                "from backend.platform.risk.rules.pms import PMSRule, PMSThreshold; "
                "from backend.platform.risk.sources import ("
                "QMTPositionSource, DBPositionSource"
                "); "
                # 2. App wiring 层
                "from app.services.risk_wiring import ("
                "build_risk_engine, LoggingSellBroker, "
                "DingTalkRiskNotifier, build_pms_thresholds"
                "); "
                # 3. Celery task 注册 (不真调 — 仅验 task 对象存在)
                "from app.tasks.daily_pipeline import risk_daily_check_task; "
                "assert risk_daily_check_task.name == 'daily_pipeline.risk_check', "
                "f'task name drifted: {risk_daily_check_task.name}'; "
                # 4. Beat schedule 注册
                "from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE; "
                "assert 'risk-daily-check' in CELERY_BEAT_SCHEDULE, "
                "'risk-daily-check missing from CELERY_BEAT_SCHEDULE'; "
                "entry = CELERY_BEAT_SCHEDULE['risk-daily-check']; "
                "assert entry['task'] == 'daily_pipeline.risk_check', "
                "f\"task mismatch: {entry['task']}\"; "
                "sched = entry['schedule']; "
                # reviewer P3 采纳: {14}/{30}/{1,2,3,4,5} 是 Python set 字面量 (非 f-string
                # 插值), celery.schedules.crontab.hour/minute/day_of_week 内部存 set.
                # 外层字符串非 f-string 所以 `{14}` 直接传 subprocess -c 原样执行.
                "assert sched.hour == {14}, f'hour drifted: {sched.hour}'; "
                "assert sched.minute == {30}, f'minute drifted: {sched.minute}'; "
                "assert sched.day_of_week == {1, 2, 3, 4, 5}, "
                "f'day_of_week drifted: {sched.day_of_week}'; "
                # 5. PMSRule 实例化 + action/severity 契约
                "pr = PMSRule(); "
                "assert pr.rule_id == 'pms', f'rule_id drifted: {pr.rule_id}'; "
                "assert pr.action == 'sell', f'action drifted: {pr.action}'; "
                # 6. LoggingSellBroker 契约验证 (批 1 占位)
                "lsb = LoggingSellBroker(); "
                "res = lsb.sell(code='000001.SZ', shares=100, reason='smoke'); "
                "assert res['status'] == 'logged_only', f'broker drifted: {res}'; "
                "print('OK')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(project_root),
    )
    assert result.returncode == 0, (
        f"MVP 3.1 risk framework smoke import failed:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    assert "OK" in result.stdout, f"Assertion(s) missing: {result.stdout}"
