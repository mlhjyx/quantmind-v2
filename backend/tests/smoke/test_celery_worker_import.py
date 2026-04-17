"""Smoke test — Celery worker 模块能从项目根 CWD subprocess 导入 + 关键 task 注册.

不启动 Celery worker (需要 Redis broker), 但以生产相同方式导入 celery_app 模块,
确认:
  1. 整个 task 发现链无 ImportError (celery.imports 里所有模块能加载)
  2. 关键 task 'daily_pipeline.factor_lifecycle' 注册成功 (今日 KeyError 根因)
  3. beat_schedule 加载无异常

运行: `pytest backend/tests/smoke/test_celery_worker_import.py -v -m smoke`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.smoke
def test_celery_app_imports_cleanly() -> None:
    """subprocess 从项目根 `import app.tasks.celery_app` 不应异常."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.tasks.celery_app import celery_app; "
            "print('Celery app:', celery_app.main)",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"`import celery_app` failed (exit={result.returncode}):\n"
            f"stderr[:1500]:\n{result.stderr[:1500]}"
        )
    assert "Celery app:" in result.stdout


@pytest.mark.smoke
def test_critical_celery_tasks_registered() -> None:
    """verify factor_lifecycle + daily tasks 注册 — 今日 KeyError 根因.

    Celery app 的 `imports=[...]` 是 worker 启动时执行, 单纯 `from celery_app`
    不触发. 显式 import 各 task 模块模拟 worker 真启动路径.
    """
    code = (
        "from app.tasks.celery_app import celery_app; "
        # 显式触发所有 imports (模拟 worker 启动)
        "import app.tasks.daily_pipeline; "
        "import app.tasks.mining_tasks; "
        "import app.tasks.onboarding_tasks; "
        "import app.tasks.backtest_tasks; "
        "names = set(celery_app.tasks.keys()); "
        "must = ['daily_pipeline.factor_lifecycle']; "
        "missing = [n for n in must if n not in names]; "
        "assert not missing, f'missing: {missing}, registered: {sorted(n for n in names if not n.startswith(\"celery.\"))[:10]}'; "
        "print('OK', len(names), 'tasks registered')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"Task registration smoke failed:\n"
            f"stderr[:1500]:\n{result.stderr[:1500]}\n"
            f"stdout[:500]:\n{result.stdout[:500]}"
        )
    assert "OK" in result.stdout


@pytest.mark.smoke
def test_celery_beat_schedule_imports() -> None:
    """beat_schedule 模块导入 + CELERY_BEAT_SCHEDULE 非空."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE; "
            "assert len(CELERY_BEAT_SCHEDULE) > 0, 'empty beat schedule'; "
            "print('beat schedule entries:', len(CELERY_BEAT_SCHEDULE))",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"beat_schedule import failed:\n"
            f"stderr[:1500]:\n{result.stderr[:1500]}"
        )
    assert "beat schedule entries" in result.stdout
