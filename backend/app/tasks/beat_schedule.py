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
    # ── [PAUSE T1_SPRINT_2026_04_29] risk-daily-check 暂停 ──
    # 撤销见: docs/audit/link_paused_2026_04_29.md
    # 暂停理由: T1 sprint 期间 .env=paper / DB 全 live 命名空间漂移持续, 14:30 Beat
    # 触发后 entry_price=0 silent skip 全规则 + LL-081 三段 guard 触 ALL_SKIPPED ERROR
    # → 钉钉每日刷屏. 真金保护已转挂 LIVE_TRADING_DISABLED=true (broker 层),
    # Beat 暂停后避免误告警噪音, 启动断言 (D 层) + 数据链 (C 层) 仍保留漂移可见.
    # 还原前置: T1.4 完成 / 批 2 写路径漂移修 / .env 改 live 收敛
    # "risk-daily-check": {
    #     "task": "daily_pipeline.risk_check",
    #     "schedule": crontab(hour=14, minute=30, day_of_week="1-5"),
    #     "options": {
    #         "queue": "default",
    #         "expires": 1200,
    #     },
    # },
    # ── [PAUSE T1_SPRINT_2026_04_29] intraday-risk-check 暂停 ──
    # 撤销见: docs/audit/link_paused_2026_04_29.md
    # 同 risk-daily-check 理由, 5min 高频 72 次/日 钉钉刷屏更甚.
    # "intraday-risk-check": {
    #     "task": "daily_pipeline.intraday_risk_check",
    #     "schedule": crontab(minute="*/5", hour="9-14", day_of_week="1-5"),
    #     "options": {
    #         "queue": "default",
    #         "expires": 240,
    #     },
    # },
    # ── [已移除] daily-execute: 移除(2026-04-06) — 由Task Scheduler QuantMind_DailyExecute 09:31触发 ──
    # ── 高频 30s — Outbox Publisher (MVP 3.4 batch 2) ──
    # event_outbox 表 → Redis Streams `qm:{aggregate_type}:{event_type}`.
    # 周期 30s 高频但 B-Tree partial 索引 cheap (WHERE published_at IS NULL),
    # 0 backlog 时 SELECT 几 ms 即返. 加锁走 SKIP LOCKED 防多 worker 等待.
    # 详见 outbox_publisher.py + docs/mvp/MVP_3_4_event_sourcing_outbox.md.
    "outbox-publisher-tick": {
        "task": "app.tasks.outbox_publisher.outbox_publisher_tick",
        "schedule": 30.0,  # Celery 接受 float 秒, 等价 timedelta(seconds=30)
        "options": {
            "queue": "default",
            "expires": 25,  # 25s 内未执行则过期 (30s 周期内必执行或丢)
        },
    },
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
    # ── 4-hour News ingestion (ADR-043 §Decision #1+#2, sub-PR 8b-cadence-B) ──
    # cron offset 3h: 03:00 / 07:00 / 11:00 / 15:00 / 19:00 / 23:00 Asia/Shanghai (6/day).
    # 软 conflict Fri 19:00 factor-lifecycle-weekly tolerated (Beat sequential dispatch +
    # Worker --pool=solo --concurrency=1 Windows 单 worker queue 等待真**反 hard collision**).
    # 反 hard collision: PT chain (Task Scheduler) 16:25 HealthCheck / 16:30 DailySignal /
    # 09:31 DailyExecute + Beat 17:40 daily-quality-report / 22:00 Sun gp-weekly / 30s outbox.
    # 5 sources: Zhipu/Anspire/Marketaux/GDELT/Xinhua (RSSHub 走独立 entry below, sub-PR 6 design).
    # Default query="A股 财经" + limit_per_source=2 (cost throttle ~$0.02-0.05/run).
    "news-ingest-5-source-cadence": {
        "task": "app.tasks.news_ingest_tasks.news_ingest_5_sources",
        "schedule": crontab(hour="3,7,11,15,19,23", minute=0),
        "options": {
            "queue": "default",
            "expires": 3600,  # 1h within next 4h cron window
        },
    },
    # ── 4-hour RSSHub route_path standalone caller (PR #254 sediment, ADR-043 §Decision #3) ──
    # Same cron as 5-source for cumulative 12 task-trigger/day; 真 cost ~$0 (Self-hosted localhost:1200).
    # Explicit kwargs route_path="/jin10/news" (1/4 working baseline, 4 working routes total
    # /jin10/news + /jin10/0 + /jin10/1 + /eastmoney/search/A股 sustained chunk C-RSSHub Path A
    # closure + chunk C-ADR PR #267 + chunk C-LL PR #268). 7 routes 503 sediment 待 sub-PR 9
    # investigation (RSSHub upstream config / cache / authentication 体例).
    # Capacity expansion (multi-route dispatch) 待预约 独立 sub-PR (architecture decision:
    # multi-Beat-entry vs task-iterator vs route-list-arg, sustained LL-115 sediment).
    "news-ingest-rsshub-cadence": {
        "task": "app.tasks.news_ingest_tasks.news_ingest_rsshub",
        "schedule": crontab(hour="3,7,11,15,19,23", minute=0),
        "kwargs": {"route_path": "/jin10/news"},  # explicit intent (沿用 LL-115)
        "options": {
            "queue": "default",
            "expires": 3600,
        },
    },
    # ── trading-hours 公告流 ingestion (sub-PR 11b sediment per ADR-049 §1 Decision 4) ──
    # cron `9,11,13,15,17 minute=15` Asia/Shanghai (5/day during 9:00-17:00 disclosure window)
    # 反 23:00/03:00 cron waste (公告流 typically published 9:00-17:00 trading hours)
    # 反 hard collision PT chain (16:25/16:30/09:31) + news_ingest (minute=0) — minute=15 buffer
    # Default symbol_id="600519" (贵州茅台 baseline, real production multi-symbol Beat dispatch
    # architecture decision deferred per ADR-049 §2 Finding #3 sustained pattern, sub-PR 12+ candidate).
    # Default source="cninfo" (1/3 working baseline per ADR-049 §1 Decision 3, sse/szse reserved
    # 待 S5 paper-mode 5d period verify per ADR-049 §2 Finding #1).
    # 真 cost ~$0 (RSSHub Self-hosted localhost:1200 anonymous sustained sub-PR 6).
    # 铁律 44 X9 post-merge ops checklist sustained: `Servy restart QuantMind-CeleryBeat` after merge
    # (沿用 ADR-043 + LL-097 sediment, sub-PR 11b post-PR ops).
    "announcement-ingest-trading-hours": {
        "task": "app.tasks.announcement_ingest_tasks.announcement_ingest",
        "schedule": crontab(hour="9,11,13,15,17", minute=15),
        "kwargs": {"symbol_id": "600519", "source": "cninfo"},  # explicit intent (沿用 LL-115)
        "options": {
            "queue": "default",
            "expires": 3600,  # 1h within next 2h cron window
        },
    },
    # ── sub-PR 14 fundamental_context daily 16:00 ingestion (ADR-053 §1 Decision 4) ──
    # V3 §3.3 line 426 cite "更新 cadence: 每日 16:00 (盘后入库)" — sub-PR 14 (minimal) baseline.
    # Default symbol_id="600519" (贵州茅台 baseline, sustained sub-PR 11b Beat 体例; real production
    # multi-symbol Beat dispatch architecture decision deferred per ADR-053 §2 Finding 1, sub-PR 15+ candidate).
    # Source: AKShare stock_value_em (sub-PR 14 1 source minimal scope, sustained ADR-053 §1 Decision 1).
    # 真 cost ~$0 (AKShare free, sustained sub-PR 13 AkshareCninfoFetcher 体例).
    # cron `0 16 * * *` Asia/Shanghai (反 PT chain 16:25/16:30 collision + 反 announcement 16:15 collision).
    # 铁律 44 X9 + LL-141 4-step post-merge ops checklist enforce: apply migration + verify celery_app
    # imports list 含本 task module + Servy restart QuantMind-CeleryBeat AND QuantMind-Celery + 1:1 simulation.
    "fundamental-context-daily-1600": {
        "task": "app.tasks.fundamental_ingest_tasks.fundamental_context_ingest",
        "schedule": crontab(hour=16, minute=0),
        "kwargs": {"symbol_id": "600519"},  # explicit intent (沿用 LL-115)
        "options": {
            "queue": "default",
            "expires": 3600,  # 1h within next 2h window
        },
    },
    # ── S7 audit fix: 5min Beat DynamicThresholdEngine compute ──
    # V3 §6 + Plan §A S7 acceptance: "dynamic threshold 5min Beat (`risk-dynamic-threshold-5min`)".
    # crontab `*/5 9-14 * * 1-5` Asia/Shanghai (trading-hours only, ~72 fires/day).
    # 反 hard collision PT chain 16:25/16:30/09:31 (cron hour upper bound 14 excludes).
    # 反 outbox 30s collision (different worker queue cadence + Beat sequential dispatch).
    # 反 news cron `3,7,11,15,19,23 0` (hour offset reserved 9-14 only).
    # task body: DynamicThresholdEngine.evaluate() → RedisThresholdCache.set_batch(TTL=300s)
    #   stub MarketIndicators + empty StockMetrics (sub-PR S7-Beat-wire minimal scope;
    #   production CSI300/holdings/ATR/beta wire deferred to S10 paper-mode 5d dry-run
    #   per Plan §A S10 acceptance + LL-141 4-step sustained).
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`.
    "risk-dynamic-threshold-5min": {
        "task": "app.tasks.dynamic_threshold_tasks.compute_dynamic_thresholds",
        "schedule": crontab(minute="*/5", hour="9-14", day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 240,  # 4min within next 5min cycle
        },
    },
    # ── S8 8c-partial: 1min Beat L4 sweep PENDING_CONFIRM expired ──
    # V3 §S8 8c (Plan §A): Celery Beat sweep PENDING_CONFIRM → TIMEOUT_EXECUTED.
    # crontab `* 9-14 * * 1-5` Asia/Shanghai (every 1min during trading hours,
    # ~360 fires/day). 反 hard collision: PT chain (16:25/16:30/09:31) excluded
    # by hour ≤14; outbox 30s + news cron + dynamic_threshold */5 minute=0 — all
    # cadence-different + Beat sequential dispatch tolerates overlap.
    # task body: SELECT expired PENDING_CONFIRM (LIMIT 100) → race-safe UPDATE
    # WHERE status='PENDING_CONFIRM' AND cancel_deadline < NOW() to TIMEOUT_EXECUTED.
    # **8c-partial scope**: state transition only. Broker_qmt sell wire deferred
    # to 8c-followup PR (5/5 红线 关键点 needs explicit user ack per Plan §A SOP).
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`.
    "risk-l4-sweep-1min": {
        "task": "app.tasks.l4_sweep_tasks.sweep_pending_confirm_plans",
        "schedule": crontab(minute="*", hour="9-14", day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 45,  # 45s within next 60s cycle (反 overlap on slow PG)
        },
    },
    # ── S10 operational: daily metrics extract at 16:30 Asia/Shanghai ──
    # V3 §13.2 元监控 + ADR-062 (S10 setup). Daily aggregator pulls
    # risk_event_log / execution_plans / llm_cost_daily → risk_metrics_daily
    # UPSERT. Fires post-market-close (16:30) so the day is complete.
    # crontab `30 16 * * 1-5` Asia/Shanghai (trading days only; weekend skips
    # are fine since 0 trade activity).
    # Cohort safety: 16:35 DailyMoneyflow (Mon-Fri) + 17:30 pull_moneyflow
    # (sustained PR #46) are SEQUENTIAL — Beat dispatches one-at-a-time, no
    # overlap concern. expires=300 (5min within next 24h cycle).
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND
    # QuantMind-Celery` (sustained pattern from S7 + S8 8c).
    "risk-metrics-daily-extract-16-30": {
        "task": "app.tasks.daily_metrics_extract_tasks.extract_daily_metrics",
        "schedule": crontab(minute=30, hour=16, day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 300,  # 5min within next 24h cycle (反 stale retry on Mon)
        },
    },
    # ── TB-2c: V3 §5.3 Bull/Bear regime detection 3 daily Beat schedules ──
    # V3 §5.3 line 664 cadence: 每日 9:00 + 14:30 + 16:00 (3 次更新, Asia/Shanghai trading days).
    # Task: app.tasks.market_regime_tasks.classify_market_regime
    #   → BullAgent V4-Pro + BearAgent V4-Pro + RegimeJudge V4-Pro (ADR-036 sustained)
    #   → market_regime_log INSERT (PR #333 TB-2a DDL + repository sustained)
    # 反 hard collision (sustained dynamic_threshold_tasks 体例):
    #   - 09:00 — clean (no existing entry; gp-weekly Sun 22:00 / news 03/07/.../23 minute=0 hour-offset)
    #   - 14:30 — risk-l4-sweep-1min (* 9-14 minute=*) sequential queue tolerated (Beat solo dispatch)
    #     + DEPRECATED risk-daily-check (paused per T1_SPRINT_2026_04_29)
    #   - 16:00 — fundamental-context-daily-1600 minute=0 collision; sequential queue tolerated
    #     (independent V4-Pro tasks, ~3-5s combined LLM call latency)
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
    #   per docs/runbook/cc_automation/v3_tb_2c_market_regime_beat_wire.md (LL-141 4-step sediment).
    # IndicatorsProvider TB-2c = StubIndicatorsProvider (all-None numeric fields, 留 TB-2d/5 real wire).
    "risk-market-regime-0900": {
        "task": "app.tasks.market_regime_tasks.classify_market_regime",
        "schedule": crontab(hour=9, minute=0, day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 1800,  # 30min within next 5h window (14:30 cycle)
        },
    },
    "risk-market-regime-1430": {
        "task": "app.tasks.market_regime_tasks.classify_market_regime",
        "schedule": crontab(hour=14, minute=30, day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 1800,  # 30min within next 1.5h window (16:00 cycle)
        },
    },
    "risk-market-regime-1600": {
        "task": "app.tasks.market_regime_tasks.classify_market_regime",
        "schedule": crontab(hour=16, minute=0, day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 1800,  # 30min within next 17h window (next day 09:00)
        },
    },
    # ── TB-4b: V3 §8 RiskReflector 5 维反思 Celery Beat 2 cadence ──
    # V3 §8.1 line 918-921: 每周日 19:00 (周复盘) + 每月 1 日 09:00 (月复盘).
    #   event-triggered 24h post-event has NO Beat entry — dispatched by L1 event
    #   detection (TB-4c+ wire) since trigger is data-driven not time-driven.
    # 反 hard collision:
    #   - Sunday 19:00 — `news-ingest-5-source-cadence` + `news-ingest-rsshub-cadence`
    #     both fire at 19:00 daily (crontab hour="3,7,11,15,19,23", incl Sunday).
    #     Beat sequential dispatch + `--pool=solo` tolerates (independent tasks,
    #     ~5-10s combined queue). `factor-lifecycle-weekly` is Friday 19:00 (NO
    #     overlap), `gp-weekly-mining` is Sunday 22:00 (NO overlap).
    #   - 月 1 日 09:00 — may collide with `risk-market-regime-0900` when 月 1 日 is
    #     a weekday. Beat sequential dispatch + `--pool=solo` Windows tolerates
    #     sub-second queue (independent V4-Pro tasks, ~3-5s combined). Acceptable.
    # post-merge ops: Servy restart QuantMind-CeleryBeat AND QuantMind-Celery
    #   per docs/runbook/cc_automation/v3_tb_4b_reflector_beat_wire.md (LL-141 4-step).
    # TB-4b input gathering = stub placeholder (TB-4c wires real risk_event_log /
    #   execution_plans / trade_log / RiskMemoryRAG).
    "risk-reflector-weekly": {
        "task": "app.tasks.risk_reflector_tasks.weekly_reflection",
        "schedule": crontab(hour=19, minute=0, day_of_week="0"),  # 0=Sunday
        "options": {
            "queue": "default",
            "expires": 3600,  # 1h window — weekly cadence has ample slack
        },
    },
    "risk-reflector-monthly": {
        "task": "app.tasks.risk_reflector_tasks.monthly_reflection",
        "schedule": crontab(hour=9, minute=0, day_of_month="1"),
        "options": {
            "queue": "default",
            "expires": 3600,  # 1h window — monthly cadence has ample slack
        },
    },
    # ── HC-1b: V3 §13.3 元告警 (alert-on-alert) 5min Beat ──
    # V3 §13.3 元监控: every 5min collect 5 风控系统失效场景 snapshot → run 5 PURE
    #   rules (qm_platform/risk/metrics/meta_alert_rules) → push triggered via DingTalk.
    # crontab `*/5 * * * *` Asia/Shanghai — every 5min ALL hours (不限 trading hours,
    #   区别于 risk-dynamic-threshold-5min `9-14`): 风控系统失效可发生在任意时刻
    #   (LiteLLM Beat tasks news/regime/reflector + STAGED cancel_deadline 跨夜).
    #   L1 心跳 collector is no-signal (HC-1b3 wires trading-hours-aware source).
    # 反 hard collision: outbox 30s + dynamic-threshold/l4-sweep (`9-14`) + news cron
    #   (minute=0) + regime/reflector + daily-metrics 16:30 — all cadence-different OR
    #   Beat sequential dispatch + Worker --pool=solo tolerates (cheap 2-query task).
    # task body: MetaMonitorService.collect_and_evaluate (2 real collector llm_call_log +
    #   execution_plans, 3 no-signal L1/DingTalk/News → HC-1b3 real wire) → push_triggered
    #   via channel fallback chain (主 DingTalk → 备 email → 极端 log-P0, HC-1b2).
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
    #   per docs/runbook/cc_automation/v3_hc_1b_meta_monitor_beat_wire.md (LL-141 4-step).
    "meta-monitor-tick": {
        "task": "app.tasks.meta_monitor_tasks.meta_monitor_tick",
        "schedule": crontab(minute="*/5"),  # every 5min, all hours
        "options": {
            "queue": "default",
            "expires": 240,  # 4min within next 5min cycle (反 stale retry pileup)
        },
    },
    # dual-write-check-daily 已退役 (MVP 2.1c Sub3.5, 2026-04-18):
    #   老 3 fetcher (fetch_base_data/fetch_minute_bars/qmt 直 xtdata) 已删, dual-write 监控无必要
    #   Session 6 backfill 19/19 PASS 完成历史硬门, 新路径 (pt_data_service/QMTDataSource) 已生产
}
