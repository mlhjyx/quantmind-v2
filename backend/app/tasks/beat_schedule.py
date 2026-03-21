"""Celery Beat 调度配置 — A股 Paper Trading 日调度。

Sprint 1.0: 定义调度表但**不激活**（当前仍用 crontab 触发）。
Sprint 1.1: 启动 celery beat，正式切换为 Celery 调度。

激活方式（Sprint 1.1）:
    celery -A app.tasks.celery_app beat --loglevel=info
    celery -A app.tasks.celery_app worker --loglevel=info -c 4

时序（北京时间，工作日）:
    16:25  健康预检
    16:30  信号生成（T日盘后）
    09:00  执行调仓（T+1日盘前）

NOTE:
    - Beat 只负责定时触发，交易日判断在 task 内部做
      （非交易日 task 会快速退出，不执行业务逻辑）
    - crontab day_of_week='1-5' 过滤周末，但节假日仍需 task 内部判断
    - trade_date_str 参数由 task 内部用 date.today() 生成
      （Beat 触发时不传日期，task 自行计算当日/前日）
"""

from celery.schedules import crontab

# ── Sprint 1.1 激活后生效的调度表 ──
# 当前 celery_app.py 会 import 此变量，但 Beat 未启动时不会实际触发。

CELERY_BEAT_SCHEDULE: dict = {
    # ── T日 16:25 健康预检 ──
    "daily-health-check": {
        "task": "daily_pipeline.health_check",
        "schedule": crontab(hour=16, minute=25, day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 300,  # 5分钟内未执行则过期
        },
    },
    # ── T日 16:30 信号生成 ──
    # NOTE: trade_date_str 不通过 Beat args 传入，
    # 改为 task 内部获取 date.today()（确保取到当日日期）。
    # 如需手动指定日期，用 send_task() 传参。
    "daily-signal": {
        "task": "daily_pipeline.signal",
        "schedule": crontab(hour=16, minute=30, day_of_week="1-5"),
        "args": [],  # task 内部计算 trade_date
        "options": {
            "queue": "default",
            "expires": 3600,  # 1小时内未执行则过期
        },
    },
    # ── T+1日 09:00 执行调仓 ──
    "daily-execute": {
        "task": "daily_pipeline.execute",
        "schedule": crontab(hour=9, minute=0, day_of_week="1-5"),
        "args": [],
        "options": {
            "queue": "default",
            "expires": 1800,
        },
    },
}
