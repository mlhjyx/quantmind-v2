"""Plan v10 — Beat task wire smoke test (铁律 10b subprocess 真启动验证).

subprocess 从生产启动路径真启动, 验证 Plan v10 闭环的 2 个 Beat task wrapper:
- `app.tasks.llm_cost_audit_tasks.monthly_audit`            (llm-cost-monthly-audit)
- `app.tasks.slippage_calibration_tasks.quarterly_recalibrate` (slippage-calibration-quarterly)

核心验证 (反 Plan v9 matrix §3.3 真根因 — 模块 orphaned 漏注册 celery_app
imports list → Celery worker 不 import → task 不注册 → Beat 触发抛
`Received unregistered task`):
  以 worker 真启动方式 (import celery_app 加载 + 显式 import 2 task 模块复现
  worker imports list 加载) 验证 2 个 task 注册成功, 且 beat_schedule 中对应
  entry 的 task 字段命中已注册 task 名.

不实际跑审计/校准脚本 (留单元测试 mock). 仅验证 Beat → task 注册链闭合.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

_REPO = Path(__file__).resolve().parents[3]


def test_plan_v10_beat_task_wrappers_registered() -> None:
    """subprocess: 2 个 Plan v10 task wrapper 生产启动路径下注册成功 + Beat entry 命中.

    复现 Celery worker 启动: `from celery_app import celery_app` 不触发 imports
    list 加载, 须显式 import task 模块 (沿用 test_celery_worker_import.py 体例).
    """
    code = (
        "import sys, platform as _stdlib_platform; "
        "_ = _stdlib_platform.python_implementation(); "
        "from app.tasks.celery_app import celery_app; "
        "import app.tasks.llm_cost_audit_tasks; "
        "import app.tasks.slippage_calibration_tasks; "
        "from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE; "
        "names = set(celery_app.tasks.keys()); "
        "must = ["
        "'app.tasks.llm_cost_audit_tasks.monthly_audit', "
        "'app.tasks.slippage_calibration_tasks.quarterly_recalibrate']; "
        "missing = [n for n in must if n not in names]; "
        "assert not missing, f'unregistered task: {missing}'; "
        "beat_keys = ('llm-cost-monthly-audit', 'slippage-calibration-quarterly'); "
        "beat_tasks = [CELERY_BEAT_SCHEDULE[k]['task'] for k in beat_keys]; "
        "unreg = [t for t in beat_tasks if t not in names]; "
        "assert not unreg, f'beat entry task unregistered: {unreg}'; "
        "print('PLAN_V10_BEAT_WIRE_OK', len(names), 'tasks registered')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        # cwd = backend/ —— 复现生产 Celery worker (Servy QuantMind-Celery) 的 cwd,
        # 使 `app.*` 直接可导入 (项目无 .pth, 系统 Python 运行).
        cwd=str(_REPO / "backend"),
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"Plan v10 Beat task wire smoke failed (exit={result.returncode}):\n"
            f"STDOUT:\n{result.stdout[:800]}\n"
            f"STDERR:\n{result.stderr[:1500]}"
        )
    assert "PLAN_V10_BEAT_WIRE_OK" in result.stdout
