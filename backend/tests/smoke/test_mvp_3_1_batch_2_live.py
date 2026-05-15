"""Smoke: MVP 3.1 批 2 Intraday Risk Framework 生产入口真启动验证 (铁律 10b).

验证链路 (subprocess 隔离, 避母进程 import 污染):
  1. `backend.qm_platform.risk.rules.intraday` 4 规则 + Protocol 可 import
  2. `app.services.risk_wiring` 批 2 扩展 (build_intraday_risk_engine / IntradayAlertDedup / _load_prev_close_nav) 可 import
  3. `app.tasks.daily_pipeline.intraday_risk_check_task` Celery task 已注册
  4. `app.tasks.beat_schedule.intraday-risk-check` schedule 已注册 (5min cron, hour=9-14, MoFr)
  5. IntradayAlertDedup key build + TTL 契约 (不真调 Redis)

铁律 10b 意图: 单测 CWD=project root 永远绿不等于生产可用, smoke 必须从生产启动
路径 subprocess 真启动, 捕 import-time / top-level 执行错误. 本 smoke 不跑 L4 逻辑
(无 QMT / Redis / DB), 仅验证 import 不炸 — 具体行为覆盖在 L1 unit tests.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.smoke
@pytest.mark.skip(
    reason="RETIRED 2026-05-15 (V3 PT Cutover Plan v0.4 §A IC-2b): intraday-risk-check "
    "Beat schedule entry physically removed from beat_schedule.py. Post-IC-1c L1 "
    "RealtimeRiskEngine production runner subscribes xtquant tick-by-tick — higher "
    "cadence than 5min Beat. 见 docs/audit/link_paused_2026_04_29.md (FORMAL RETIRE)."
)
def test_mvp_3_1_batch_2_intraday_imports() -> None:
    """Platform intraday + wiring + Celery task + Beat schedule subprocess import 不炸."""
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
                # 1. Platform intraday rules 核心导出
                "from backend.qm_platform.risk.rules.intraday import ("
                "IntradayPortfolioDropRule, "
                "IntradayPortfolioDrop3PctRule, "
                "IntradayPortfolioDrop5PctRule, "
                "IntradayPortfolioDrop8PctRule, "
                "QMTDisconnectRule, "
                "QMTConnectionReader"
                "); "
                # 2. App wiring 批 2 扩展
                "from app.services.risk_wiring import ("
                "build_intraday_risk_engine, IntradayAlertDedup, _load_prev_close_nav"
                "); "
                # 3. Celery task 注册 (不真调 — 仅验 task 对象存在)
                "from app.tasks.daily_pipeline import intraday_risk_check_task; "
                "assert intraday_risk_check_task.name == 'daily_pipeline.intraday_risk_check', "
                "f'task name drifted: {intraday_risk_check_task.name}'; "
                # 4. Beat schedule 注册 + crontab 参数验证
                "from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE; "
                "assert 'intraday-risk-check' in CELERY_BEAT_SCHEDULE, "
                "'intraday-risk-check missing from CELERY_BEAT_SCHEDULE'; "
                "entry = CELERY_BEAT_SCHEDULE['intraday-risk-check']; "
                "assert entry['task'] == 'daily_pipeline.intraday_risk_check', "
                "f\"task mismatch: {entry['task']}\"; "
                "sched = entry['schedule']; "
                # reviewer P2 采纳 python: set equality 替 len 断言, 检测 crontab 展开值漂移
                "assert sched.minute == {0,5,10,15,20,25,30,35,40,45,50,55}, "
                "f'minute set drifted: {sched.minute}'; "
                "assert sched.hour == {9,10,11,12,13,14}, f'hour drifted: {sched.hour}'; "
                "assert sched.day_of_week == {1,2,3,4,5}, f'day_of_week drifted: {sched.day_of_week}'; "
                # 5. IntradayAlertDedup key build + TTL 契约
                "k = IntradayAlertDedup._build_key('pms_l1', 'strat_x', 'paper'); "
                "assert k.startswith('qm:risk:dedup:pms_l1:strat_x:paper:'), "
                "f'dedup key pattern drifted: {k}'; "
                "assert IntradayAlertDedup._TTL_SECONDS == 86400, "
                "f'TTL drifted: {IntradayAlertDedup._TTL_SECONDS}'; "
                # 6. 4 Drop Rules 实例化 + threshold 契约
                "r3 = IntradayPortfolioDrop3PctRule(); "
                "r5 = IntradayPortfolioDrop5PctRule(); "
                "r8 = IntradayPortfolioDrop8PctRule(); "
                "assert (r3.threshold, r5.threshold, r8.threshold) == (0.03, 0.05, 0.08); "
                "assert r3.severity.value == 'p2' and r5.severity.value == 'p1' and r8.severity.value == 'p0'; "
                "print('OK')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(project_root),
    )
    assert result.returncode == 0, (
        f"MVP 3.1 batch 2 intraday smoke import failed:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    assert "OK" in result.stdout, f"Assertion(s) missing: {result.stdout}"
