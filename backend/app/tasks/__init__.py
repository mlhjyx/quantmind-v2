"""Celery 任务模块。

启动 Worker:
    celery -A app.tasks.celery_app worker --loglevel=info

启动 Beat（Sprint 1.1 激活）:
    celery -A app.tasks.celery_app beat --loglevel=info

手动触发任务:
    from app.tasks.daily_pipeline import daily_signal_task
    daily_signal_task.delay("2026-03-21")
"""
