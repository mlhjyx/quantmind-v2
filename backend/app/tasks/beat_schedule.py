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
    # ── 每周日 22:00 GP因子挖掘 ──
    # NOTE: 周日非交易日，不影响盘前/盘后交易链路。
    # 配置: population=100, generations=50, time_budget_minutes=120, islands=4
    # 任务内部会生成 run_id（格式: gp_{YYYY}w{WW}_{hash8}）并写入 pipeline_runs。
    "gp-weekly-mining": {
        "task": "app.tasks.mining_tasks.run_gp_mining",
        "schedule": crontab(hour=22, minute=0, day_of_week="0"),  # 0=周日
        "kwargs": {
            "run_id": None,  # None 表示 task 内部自动生成 run_id
            "config": {
                "population": 100,
                "generations": 50,
                "time_budget_minutes": 120,
                "islands": 4,
            },
        },
        "options": {
            "queue": "default",
            "expires": 7200,  # 2小时内未执行则过期（避免错过周日后积压）
        },
    },
    # ── [已移除] PT主链任务由Task Scheduler驱动，Beat不再触发 ──
    # daily-health-check: 移除(2026-04-06) — 由Task Scheduler QM-HealthCheck 16:25触发
    # daily-signal: 移除(2026-04-06) — 由Task Scheduler QuantMind_DailySignal 16:30触发
    # ── [已停止] pms-daily-check: DEPRECATED per ADR-010 (Session 21 2026-04-21) ──
    # PMS v1.0 整体死码 (F27-F31 5 重失效), 并入 Wave 3 MVP 3.1 Risk Framework 重构.
    # 老 task function (daily_pipeline.pms_check) 保留 1 sprint 供紧急回滚,
    # 批 3 CB adapter 完成后与 pms_engine.py 一并物理删除.
    # 过渡期保护: scripts/intraday_monitor.py 单股急跌告警 (-8% 阈值).

    # ── T日 14:30 Risk Framework 日检 (MVP 3.1 批 1 PR 3, Session 29 2026-04-24) ──
    # 替代老 pms-daily-check, 走 PlatformRiskEngine + PMSRule (ADR-010 D3).
    # 批 1 行为保持 v1 语义 (LoggingSellBroker 仅记录不实盘卖), 批 2 接真 broker.
    # risk_event_log 完整记录触发上下文 (session 28 PR #55 migration).
    "risk-daily-check": {
        "task": "daily_pipeline.risk_check",
        "schedule": crontab(hour=14, minute=30, day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 1200,  # 20min 内未执行则过期 (市场 15:00 收盘窗口对齐)
        },
    },
    # ── [已移除] daily-execute: 移除(2026-04-06) — 由Task Scheduler QuantMind_DailyExecute 09:31触发 ──

    # ── T日 17:40 数据质量报告 (DATA_SYSTEM_V1 P1-2) ──
    "daily-quality-report": {
        "task": "daily_pipeline.data_quality_report",
        "schedule": crontab(hour=17, minute=40, day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 1200,  # 20min 内未执行则过期
        },
    },
    # ── 周五 19:00 因子生命周期状态转换 (Phase 3 MVP A) ──
    # DEV_AI_EVOLUTION V2.1 §3.1: active↔warning / warning→critical
    # 避开 17:40 质量报告 + 20:00 ic_monitor + 22:00 gp-weekly-mining (周日)
    "factor-lifecycle-weekly": {
        "task": "daily_pipeline.factor_lifecycle",
        "schedule": crontab(hour=19, minute=0, day_of_week="5"),  # 5=周五
        "options": {
            "queue": "default",
            "expires": 3600,
        },
    },
    # dual-write-check-daily 已退役 (MVP 2.1c Sub3.5, 2026-04-18):
    #   老 3 fetcher (fetch_base_data/fetch_minute_bars/qmt 直 xtdata) 已删, dual-write 监控无必要
    #   Session 6 backfill 19/19 PASS 完成历史硬门, 新路径 (pt_data_service/QMTDataSource) 已生产
}
