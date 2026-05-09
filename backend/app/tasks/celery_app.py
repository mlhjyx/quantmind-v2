"""Celery 应用实例 — QuantMind V2 调度框架。

Broker/Backend 均使用 Redis，配置从 app.config.settings 读取。
Sprint 1.0: 创建框架 + 任务定义。
Sprint 1.1: 激活 Beat 调度，替换 crontab。

⚠️ Windows 生产环境 (S3 F82):
  必须以 `--pool=solo --concurrency=1` 启动 (Windows 不支持 fork/prefork)。
  不要直接 `celery worker -A app.tasks.celery_app`, 使用 Servy 管理的
  QuantMind-Celery 服务 (见 scripts/service_manager.ps1)。
  真正并发需按 docs/research/R6_production_architecture.md §3.2 启动多个
  solo worker 实例 + 不同 queue, 而非调高 worker_concurrency。
"""

import sys
from pathlib import Path

# 确保 backend/ 在 sys.path 中，使 engines 模块可被 Celery worker 导入
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.append(_backend_dir)

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
        "app.tasks.outbox_publisher",  # MVP 3.4 batch 2: 30s outbox publisher tick
        "app.tasks.news_ingest_tasks",  # sub-PR 8b-cadence-B: 4-hour News Beat (ADR-043)
        "app.tasks.announcement_ingest_tasks",  # sub-PR 11b: announcement Beat trading-hours cadence (ADR-050)
        "app.tasks.fundamental_ingest_tasks",  # sub-PR 14: fundamental_context daily 16:00 Beat (ADR-053, LL-141 sustained 4-step post-merge ops)
        # app.tasks.dual_write_tasks 已退役 (MVP 2.1c Sub3.5, 2026-04-18): 老 3 fetcher 退役后
        # dual-write 监控无必要, Celery Beat 条目 + task 已删
    ],
    # 结果过期: 24 小时
    result_expires=86400,
    # Worker 并发: Windows 生产 solo×1 (CLI --pool=solo --concurrency=1 覆盖此值)
    # 此 default 仅在未传 --pool 时生效, 对齐 Windows 实际运行 (S3 F82 修复)
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
    # Beat 调度表（Sprint 1.1 激活）
    # beat_schedule 从 beat_schedule.py 导入，见下方 conf.update
)

# 延迟导入 Beat 配置（避免循环导入）
from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: E402

celery_app.conf.beat_schedule = CELERY_BEAT_SCHEDULE


# MVP 1.3b wiring: Worker 启动时注入 Platform DBFactorRegistry + DBFeatureFlag 到
# signal_engine (backtest_tasks / onboarding_tasks 生成信号时走 Layer 1 DB 路径).
# 幂等 + fail-safe (失败自动回 Layer 0 hardcoded, 3 层 fallback 保底).
from app.core.platform_bootstrap import bootstrap_platform_deps  # noqa: E402

bootstrap_platform_deps()
