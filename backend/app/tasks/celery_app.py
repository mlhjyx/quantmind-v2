"""Celery 应用实例 — QuantMind V2 调度框架。

Broker/Backend 均使用 Redis，配置从 app.config.settings 读取。
Sprint 1.0: 创建框架 + 任务定义。
Sprint 1.1: 激活 Beat 调度，替换 crontab。
"""

import sys
from pathlib import Path

# 确保 backend/ 在 sys.path 中，使 engines 模块可被 Celery worker 导入
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from celery import Celery

from app.config import settings

celery_app = Celery(
    "quantmind",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # 可靠性: crash 后自动重试
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # 时区（A 股调度用北京时间，Phase 2 外汇调度用 UTC）
    timezone="Asia/Shanghai",
    enable_utc=False,
    # 任务发现
    imports=[
        "app.tasks.daily_pipeline",
        "app.tasks.mining_tasks",
        "app.tasks.onboarding_tasks",
        "app.tasks.backtest_tasks",
    ],
    # 结果过期: 24 小时
    result_expires=86400,
    # Worker 并发: Mac M1 Pro 单机，prefork 4 进程足够
    worker_concurrency=4,
    worker_prefetch_multiplier=1,
    # Beat 调度表（Sprint 1.1 激活）
    # beat_schedule 从 beat_schedule.py 导入，见下方 conf.update
)

# 延迟导入 Beat 配置（避免循环导入）
from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: E402

celery_app.conf.beat_schedule = CELERY_BEAT_SCHEDULE
