"""MVP 3.4 batch 2 OutboxPublisher live smoke (铁律 10b).

subprocess 真启动验证: app.tasks.outbox_publisher module-top imports 不破,
OutboxPublisher 可实例化, beat_schedule outbox-publisher-tick 注册成功.

对齐 test_mvp_3_3_batch_1_live pattern.
"""
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
        # 不实例化 (会拉 redis/db conn), 只验类 + tick 可访问
        "from app.tasks.outbox_publisher import "
        "OutboxPublisher, outbox_publisher_tick, DLQ_STREAM, "
        "DEFAULT_BATCH_SIZE, DEFAULT_MAX_RETRIES; "
        "assert DLQ_STREAM == 'qm:dlq:outbox', 'DLQ stream name 漂移'; "
        "assert DEFAULT_MAX_RETRIES == 10, 'max_retries default 漂移'; "
        "assert DEFAULT_BATCH_SIZE == 100, 'batch_size default 漂移'; "
        "assert callable(OutboxPublisher), 'OutboxPublisher 类不可调'; "
        # 验 beat schedule entry 存在 (Celery beat 启动会读)
        "from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE; "
        "assert 'outbox-publisher-tick' in CELERY_BEAT_SCHEDULE, "
        "'beat schedule 没注册 outbox-publisher-tick'; "
        "entry = CELERY_BEAT_SCHEDULE['outbox-publisher-tick']; "
        "assert entry['task'] == 'app.tasks.outbox_publisher.outbox_publisher_tick'; "
        "assert entry['schedule'] == 30.0, 'schedule 不是 30s'; "
        # 验 celery_app imports 含 outbox_publisher (worker 启动会注册 task)
        "from app.tasks.celery_app import celery_app; "
        "task_names = list(celery_app.tasks.keys()); "
        "assert 'app.tasks.outbox_publisher.outbox_publisher_tick' in task_names, "
        "f'task 未注册到 celery_app: {[t for t in task_names if \"outbox\" in t]}'; "
        "print('OK outbox_publisher boot')"
    )


@pytest.mark.smoke
def test_outbox_publisher_imports_and_beat_registered():
    """subprocess Python 真启动: import + beat schedule + celery task 注册."""
    result = subprocess.run(
        [sys.executable, "-c", _build_smoke_code()],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"smoke failed (exit={result.returncode}): stderr={result.stderr}"
    )
    assert "OK outbox_publisher boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
