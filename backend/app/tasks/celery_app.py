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

⚠️ Solo pool memory leak — LL-189 候选 (2026-05-19 Session 58+1):
  `--pool=solo` = 单 process, 不 fork = 内存累积 24h+ 不释放.
  实测 5-19 18:30 SH: worker_main@XIN 24h runtime → WS 43.9GB / private 1.4GB
  (Windows 报告 94% RAM Used, available 1.7GB, 接近 OOM, 沿用 LL-009 4-03
  PG OOM 教训). Root cause: pandas/numpy 用 glibc malloc, factor_calc /
  data_fetch queue task 累积. Beat 22 entries (outbox 30s + L4 sweep 1min +
  meta_monitor 5min + ...) ≈ 5000+ task/day fed solo worker.

  **Hardening 选项** (solo pool 不支持 `worker_max_memory_per_child`,
  仅 prefork 有效, 沿用 celery 5.x source `celery.concurrency.asynpool`
  vs `celery.concurrency.solo` 区分):

  1. **Periodic restart schtask** (RECOMMENDED): Windows Task Scheduler
     `QuantMind_CeleryNightlyRestart` 每日 03:30 SH 触发
     `Restart-Service QuantMind-Celery` (~30s graceful + auto-restart 沿用
     Servy AutoRestart=true). 反 24h+ 累积.

  2. **Memory monitor rule**: Beat `meta-monitor-tick` 5min Beat 加 rule
     `Available MBytes < 2000 → P1 DingTalk alert` (V3 §13.3 第 8 元告警).

  3. **Servy memory limit**: Servy `--memory-limit=4096` (4GB) 触发
     auto-restart if 超 (Servy v7.6 支持). 沿用 docs/audit/STATUS_REPORT
     体例.

  4. **Backend hardening**: pandas explicit `gc.collect() + del df` 模式
     in factor_calc task body. 沿用铁律 33 fail-loud + explicit release.

  Immediate fix: 直接 restart `QuantMind-Celery` service (graceful 30s
  shutdown). 长期 sediment ADR-086 候选 (Periodic restart + monitor wire,
  5-19 Session 58+1 sediment driver).
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
    # ⭐ Default queue routing (LL-189 候选 fix, 2026-05-19 Session 58+1):
    #   Producers (.delay() / .apply_async()/ Beat) without explicit queue= 走 "default"
    #   而非默认 "celery". 反 worker `-Q default,factor_calc,data_fetch` 不订阅 "celery"
    #   导致 orphan 累积 (实测 5-19 18:30 SH 288 orphan, 286/288 = run_backtest from
    #   api/backtest.py:202 + services/backtest_service.py:94 `.delay()` no-queue calls).
    #   沿用 ADR-086 候选 hardening sediment + celery 5.x doc canonical 体例.
    task_default_queue="default",
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
        "app.tasks.dynamic_threshold_tasks",  # S7 audit fix: 5min Beat wiring DynamicThresholdEngine → ThresholdCache (LL-145/149 + ADR-055)
        "app.tasks.l4_sweep_tasks",  # S8 8c-partial: 1min Beat sweep PENDING_CONFIRM expired → TIMEOUT_EXECUTED (ADR-058 + LL-152, broker_qmt wire deferred to 8c-followup)
        "app.tasks.daily_metrics_extract_tasks",  # S10 operational: daily 16:30 Beat extract → risk_metrics_daily (ADR-062 + LL-156)
        "app.tasks.market_regime_tasks",  # TB-2c: 3 daily Beat schedules (9:00/14:30/16:00) Bull/Bear/Judge V4-Pro → market_regime_log (ADR-036 + ADR-064 + ADR-066 cumulative)
        "app.tasks.risk_reflector_tasks",  # TB-4b: 2 Beat cadence (Sunday 19:00 weekly + 月 1 日 09:00 monthly) + event_reflection (L1 dispatch, no Beat) RiskReflector V4-Pro 5 维反思 → docs/risk_reflections/ + DingTalk push (ADR-064 + ADR-069 候选)
        "app.tasks.meta_monitor_tasks",  # HC-1b: 5min Beat 元告警 (alert-on-alert) — 5 风控系统失效场景 snapshot → 5 PURE rules → DingTalk push (V3 §13.3, ADR-072 + ADR-073 候选)
        "app.tasks.llm_cost_audit_tasks",  # Plan v10: 月度 LLM cost audit Beat wire (P0-16 闭环, subprocess wrapper of scripts/llm_cost_monthly_audit.py)
        "app.tasks.slippage_calibration_tasks",  # Plan v10: 季度滑点校准 Beat wire (P0-10 闭环, 铁律 18 季度复核, subprocess wrapper of scripts/bayesian_slippage_calibration.py)
        # iter 31 closes iter 30 hidden defect — PR #459 shipped report_tasks module
        # without registering it here, so generate_performance_report.delay() would
        # dispatch but worker would never see the task. Iter 31 surfaced + fixed.
        # Sustained pattern from Plan v10 P0-10 + P0-16 sediment (same failure mode).
        "app.tasks.report_tasks",  # iter 30/31: generate_performance_report + cleanup_old_reports (PR #459 + this PR)
        "app.tasks.attribution_tasks",  # MVP 4.2 sub-iter 7 (iter 65): daily-attribution-compute Beat (16:30 Mon-Fri) — DailyAttribution persist + residual alert
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
