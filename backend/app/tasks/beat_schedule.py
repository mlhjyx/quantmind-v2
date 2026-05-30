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

H4 fix (2026-05-19, Audit Section X §39 + ISSUES_PENDING_REGISTRY §4 A5/§9 H4):
    Calendar SSOT helper for task-level gate (反 LL-181 节假日 Beat 空跑):

        from backend.qm_platform.calendar import is_trading_day_today_or_skip

        @celery_app.task(name="risk.daily-check")
        def risk_daily_check():
            if not is_trading_day_today_or_skip():
                return  # silent skip 节假日
            # ... real task body ...

    Schtask Python wrapper 同 pattern:
        if not is_trading_day_today_or_skip():
            sys.exit(0)

    Calendar gate Phase I — DONE (Plan 1, 2026-05-20): 7 trading-day-sensitive Beat
    task functions gated via is_trading_day_today_or_skip; 3 deliberately NOT gated
    (sweep_stuck_broker_plans 跨日对账 / meta_monitor_tick 元监控 all-hours /
    announcement_ingest cron 含周末公告); 余下非交易日无关. 详 docs/DEV_SCHEDULER.md §〇.
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
            "queue": "factor_calc",
            "expires": 7200,  # 2小时内未执行则过期（避免错过周日后积压）
        },
    },
    # ── [已移除] PT主链任务由Task Scheduler驱动，Beat不再触发 ──
    # daily-health-check: 移除(2026-04-06) — 由Task Scheduler QM-HealthCheck 16:25触发
    # daily-signal: 移除(2026-04-06) — 由Task Scheduler QuantMind_DailySignal 16:30触发
    # ── [物理退役 iter 50 2026-05-24 ADR-094] pms-daily-check ──
    # PMS v1.0 整体物理退役 (Beat停 4-21 + 7+月0真账户触发 + ADR-010 §C sunset gate 满足).
    # 删除文件: app/services/pms_engine.py + app/api/pms.py + tests/test_pms_engine.py +
    # daily_pipeline.pms_daily_check_task. V3 风控走 qm_platform/risk/rules/pms.py
    # (Wave 3 MVP 3.1 PMSRule) + V3 §7.3 trailing_stop (subscribe_quote 实时).
    # 详 ADR-094 + iter 50 commit message. Git revert 路径完整可逆.
    # ── [RETIRED T1_SPRINT_2026_04_29 → IC-2b 2026-05-15] risk-daily-check + intraday-risk-check ──
    # 历史: T1 sprint 期间 14:30 daily + 5min intraday Beat 因 .env=paper / DB live 命名空间漂移
    # 触发 ALL_SKIPPED ERROR 钉钉刷屏 → 2026-04-29 暂停 (commented-out, 沿用 audit doc).
    # 形式 retire 2026-05-15 (V3 PT Cutover Plan v0.4 §A IC-2b): post-IC-1c L1 RealtimeRiskEngine
    # production runner (PR #363) + meta_monitor L1 heartbeat alert re-activated (PR #364)
    # 已 cover intraday tick-by-tick + daily 14:30 风控路径 — 这 2 paused Beat 在 V3 chain
    # 中 redundant. Commented-out blocks 物理删除避免长期 dead-code visual noise.
    # 详 docs/audit/link_paused_2026_04_29.md (历史 audit) + ADR-079 reserved (IC-2 closure cumulative, IC-2c sediment).
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
    # ── MVP 4.8 (iter 184) — Trade event risk consumer 10s Beat (Phase J §1.5) ──
    # Consumes qm:fill:executed Redis Stream (outbox publisher output, MVP 3.4
    # batch 5 sustained since PR #130 2026-04-28). XREADGROUP at-least-once via
    # consumer group risk-engine-fill-consumer. Triggers RealtimeRiskEngine
    # on_tick per fill event → tick-level risk eval (vs current ~60s
    # l4_sweep_tasks polling gap). Per MVP 4.8 design doc iter 183.
    # Beat cadence 10s via float schedule (Celery crontab min granularity is
    # 1min). expires=8s within next 10s cycle.
    # X9 post-merge ops: Servy restart Celery + CeleryBeat after merge.
    "trade-event-risk-consumer-tick": {
        "task": "risk.trade_event_consumer_tick",
        "schedule": 10.0,
        "options": {
            "queue": "default",
            "expires": 8,
        },
    },
    # ── MVP 4.7 Chunk 1 (iter 174) — BGE-M3 embedding backfill every 6h ──
    # Phase J §1.4 wire: idempotent backfill of risk_memory rows where embedding
    # IS NULL via BGE-M3 EmbeddingService. Self-healing for any future NULL
    # source (reflector transient failure / manual INSERT / 21 historical rows).
    # batch_size=100 keeps GPU+DB time <5s per fire; idempotent re-run safe.
    # Sibling pattern: outbox-publisher-tick (Beat dispatch + caller-owns-conn).
    # X9 post-merge ops: Servy restart Celery + CeleryBeat after merge.
    "embedding-backfill-every-6h": {
        "task": "embedding.backfill",
        "schedule": crontab(hour="*/6", minute=15),  # 00:15 / 06:15 / 12:15 / 18:15
        "kwargs": {"batch_size": 100},
        "options": {
            "queue": "data_fetch",
            "expires": 3600,  # 1h expiry — next fire will retry if missed
        },
    },
    # ── T日 17:40 数据质量报告 (DATA_SYSTEM_V1 P1-2) ──
    "daily-quality-report": {
        "task": "daily_pipeline.data_quality_report",
        "schedule": crontab(hour=17, minute=40, day_of_week="1-5"),
        "options": {
            "queue": "factor_calc",
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
            "queue": "factor_calc",
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
            "queue": "data_fetch",
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
            "queue": "data_fetch",
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
            "queue": "data_fetch",
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
            "queue": "data_fetch",
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
    # ── [Re-enabled 2026-05-18 14:11 SH post M3 broker_qmt asyncio bootstrap fix] ──
    # M1 temp-disable history: 14:02-14:11 SH ~9 min window blocked spam from 14:02 SH
    # P0 DingTalk "V3 L4 STAGED live broker wire FAILED" (RuntimeError: no event loop).
    # M3 fix applied to broker_qmt.py:253-264 — asyncio.set_event_loop bootstrap before
    # xtquant.xttrader API calls. LL-180 候选: 6th 实证 sys.path/asyncio drift sub-class
    # (PR #377 fixed ModuleNotFoundError, this PR fixes asyncio compat).
    "risk-l4-sweep-1min": {
        "task": "app.tasks.l4_sweep_tasks.sweep_pending_confirm_plans",
        "schedule": crontab(minute="*", hour="9-14", day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 45,  # 45s within next 60s cycle (反 overlap on slow PG)
        },
    },
    # ── Phase J §1.1 Chunk 2 (iter 154): L1 RealtimeRiskEngine production wire ──
    # 1min cadence 9-14h trading-hours-only. Instantiate engine + 10 rules + build
    # RiskContext from Redis (QMTClient) + evaluate on_tick + on_5min_beat (when
    # minute % 5 == 0). expires=45 within next 60s cycle (反 overlap on slow
    # context build). Beat sequential dispatch + Worker --pool=solo tolerates
    # collision with risk-l4-sweep-1min (both cheap, no shared lock).
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND
    # QuantMind-Celery`.
    "realtime-risk-tick": {
        "task": "app.tasks.realtime_risk_tasks.realtime_risk_tick",
        "schedule": crontab(minute="*", hour="9-14", day_of_week="1-5"),
        "options": {
            "queue": "default",
            "expires": 45,  # 45s within next 60s cycle
        },
    },
    # ── HC-2b2 G7 (V3 §14 mode 12): broker plan stuck sweep ──
    # Plans stuck in CONFIRMED / TIMEOUT_EXECUTED > 5min = broker 接口故障 signal
    # (execute_plan never completed — broker call 挂 / DB writeback 失败 / worker
    # 中途死). CONFIRMED-stuck 此前 0 retry 路径 (l4_sweep 只扫 PENDING_CONFIRM).
    # Task retries execute_plan (idempotent); plans still stuck → BROKER_PLAN_STUCK
    # 元告警 (P0). crontab `*/5 * * * *` — every 5min ALL hours (区别于
    # risk-l4-sweep-1min `9-14`): a CONFIRMED plan can be confirmed near close +
    # stuck overnight; reconciliation 不应等到次日开盘.
    # 反 hard collision: meta-monitor-tick `*/5` + outbox 30s — Beat sequential
    # dispatch + Worker --pool=solo tolerates (cheap SELECT + per-plan retry).
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`.
    # ── [Re-enabled 2026-05-18 14:11 SH post M3 broker_qmt asyncio bootstrap fix] ──
    "risk-l4-broker-stuck-sweep": {
        "task": "app.tasks.l4_sweep_tasks.sweep_stuck_broker_plans",
        "schedule": crontab(minute="*/5"),
        "options": {
            "queue": "default",
            "expires": 240,  # 4min within next 5min cycle (反 stale retry pileup)
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
    #     (historical risk-daily-check 14:30 retired 2026-05-15 per IC-2b — V3 chain covers it now)
    #   - 16:00 — fundamental-context-daily-1600 minute=0 collision; sequential queue tolerated
    #     (independent V4-Pro tasks, ~3-5s combined LLM call latency)
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
    #   per docs/runbook/cc_automation/v3_tb_2c_market_regime_beat_wire.md (LL-141 4-step sediment).
    # IndicatorsProvider TB-2c = StubIndicatorsProvider (all-None numeric fields, 留 TB-2d/5 real wire).
    "risk-market-regime-0900": {
        "task": "app.tasks.market_regime_tasks.classify_market_regime",
        "schedule": crontab(hour=9, minute=0, day_of_week="1-5"),
        "options": {
            "queue": "data_fetch",
            "expires": 1800,  # 30min within next 5h window (14:30 cycle)
        },
    },
    "risk-market-regime-1430": {
        "task": "app.tasks.market_regime_tasks.classify_market_regime",
        "schedule": crontab(hour=14, minute=30, day_of_week="1-5"),
        "options": {
            "queue": "data_fetch",
            "expires": 1800,  # 30min within next 1.5h window (16:00 cycle)
        },
    },
    "risk-market-regime-1600": {
        "task": "app.tasks.market_regime_tasks.classify_market_regime",
        "schedule": crontab(hour=16, minute=0, day_of_week="1-5"),
        "options": {
            "queue": "data_fetch",
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
            "queue": "data_fetch",
            "expires": 3600,  # 1h window — weekly cadence has ample slack
        },
    },
    "risk-reflector-monthly": {
        "task": "app.tasks.risk_reflector_tasks.monthly_reflection",
        "schedule": crontab(hour=9, minute=0, day_of_month="1"),
        "options": {
            "queue": "data_fetch",
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
    # task body: MetaMonitorService.collect_and_evaluate (7 polled rules — 6 real
    #   collector: llm_call_log + execution_plans + alert_dedup + Redis news-stats +
    #   pg_stat_activity (HC-2b3 G3) + index_daily/klines_daily (HC-2b3 G4); 1
    #   no-signal: L1 heartbeat) → push_triggered via channel fallback chain
    #   (主 DingTalk → 备 email → 极端 log-P0, HC-1b2).
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
    # ── Plan v8 Master P0-16 closure: monthly LLM cost aggregator (Session 58+1, batch 6) ──
    # 沿用 V3 §20.1 #6 budget cap ($50/month + 80% warn + 100% Ollama fallback)
    # crontab `0 8 1 * *` Asia/Shanghai = 月初 1日 08:00 SH (避开 trading hours + Beat 高峰)
    # task body: 沿用 scripts/llm_cost_monthly_audit.py logic via Celery task wrapper
    #   - SELECT month bucket sums from llm_call_log
    #   - Push DingTalk if MoM change > 50% OR MTD > 80% budget
    #   - Output: stdout + 沉淀 to scheduler_log table
    # 反 hard collision: 月初 1日 09:00 SH risk-reflector-monthly (沿用 §risk-reflector-monthly)
    #   sequential queue tolerated (Beat solo dispatch). 月初 08:00 SH no other Beat fires.
    # **IMPLEMENTED Plan v10 (2026-05-20)**: task wrapper
    #   `app.tasks.llm_cost_audit_tasks.monthly_audit` 是 scripts/llm_cost_monthly_audit.py
    #   的 subprocess wrapper (隔离进程, 脚本自管 .env + psycopg2 + exit code). 真根因:
    #   模块 Plan v8 P0-16 时已建但**漏注册 celery_app.py imports** → worker 不 import →
    #   task 不注册. Plan v10 注册 imports list + 单测 (test_llm_cost_audit_tasks.py) +
    #   smoke (test_plan_v10_beat_task_wire_live.py). Plan v9 matrix §3.3 闭环 ——
    #   §8.2 曾误标 closed (仅改本注释未注册模块), Plan v10 真闭环.
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
    #   (沿用 ADR-043 + LL-097 sediment; imports list 变更必须重启 worker 才注册).
    "llm-cost-monthly-audit": {
        "task": "app.tasks.llm_cost_audit_tasks.monthly_audit",  # implemented Plan v10 (subprocess wrapper)
        "schedule": crontab(hour=8, minute=0, day_of_month="1"),
        "options": {
            "queue": "data_fetch",
            "expires": 3600,  # 1h within next month cycle
        },
    },
    # ── Plan v8 Master P0-10 closure: slippage 季度复核 (Session 58+1, batch 6) ──
    # 沿用 铁律 18: 回测成本实现必须与实盘对齐 — H0 验证 < 5bps + 季度复核
    # crontab `0 2 1 1,4,7,10 *` Asia/Shanghai = 每季度第 1 天 02:00 SH (Q1/Q2/Q3/Q4)
    # task body: 沿用 scripts/bayesian_slippage_calibration.py logic via Celery task wrapper
    #   - SELECT recent trade_log + price impact analysis
    #   - Bayesian update Y_small/Y_mid/Y_large slippage coefs
    #   - Compare vs current calibration; alert if drift > 30% per coef
    #   - Output: docs/research/slippage_calibration_YYYYQ.md + 沉淀 calibration_history table
    # 反 hard collision: 02:00 SH 月初 1日 no other Beat fires (gp-weekly Sun 22:00 + outbox 30s only).
    # **IMPLEMENTED Plan v10 (2026-05-20)**: task wrapper
    #   `app.tasks.slippage_calibration_tasks.quarterly_recalibrate` 是
    #   scripts/bayesian_slippage_calibration.py 的 subprocess wrapper. 真根因同
    #   llm-cost-monthly-audit: 模块 Plan v8 P0-10 时已建但漏注册 celery_app.py imports.
    #   Plan v10 注册 imports list + 单测 (test_slippage_calibration_tasks.py) + smoke.
    #   Plan v9 matrix §3.3 闭环 (§8.2 曾误标 closed, Plan v10 真闭环; 铁律 18 季度复核).
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
    #   (沿用 ADR-043 + LL-097 sediment; imports list 变更必须重启 worker 才注册).
    "slippage-calibration-quarterly": {
        "task": "app.tasks.slippage_calibration_tasks.quarterly_recalibrate",  # implemented Plan v10 (subprocess wrapper)
        "schedule": crontab(hour=2, minute=0, day_of_month="1", month_of_year="1,4,7,10"),
        "options": {
            "queue": "factor_calc",
            "expires": 7200,  # 2h within next quarter cycle
        },
    },
    # dual-write-check-daily 已退役 (MVP 2.1c Sub3.5, 2026-04-18):
    #   老 3 fetcher (fetch_base_data/fetch_minute_bars/qmt 直 xtdata) 已删, dual-write 监控无必要
    #   Session 6 backfill 19/19 PASS 完成历史硬门, 新路径 (pt_data_service/QMTDataSource) 已生产
    # ── reports-cleanup-weekly: 周日 04:30 SH (iter 31 — closes iter 30 PR #459 P2-8) ──
    # 消费 backend/app/tasks/report_tasks.cleanup_old_reports — reports/ 目录 retention
    # 2-rule policy (age >90d 或 count >20 per (sid,mode) tuple, union semantic).
    # 时段选择 (反 hard collision):
    #   - 03:00 SH QuantMind_VacuumAnalyze (schtask) — 90min buffer 前, VACUUM 完全独立 (DB ops vs FS ops)
    #   - 22:00 SH gp-weekly-mining (Beat) — 17.5h buffer 后, 完全独立
    #   - 03:30 SH QuantMind_CeleryNightlyRestart (若启用 ADR-086 候选) — 60min buffer 前
    # 04:30 是周日凌晨低峰窗口, FS-only ops, ~0 CPU/IO 影响; weekly cadence 足够
    # (iter 30 默认 keep=20 per (sid, mode), 1 dispatch/day = 20 days retention即上限).
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
    #   (沿用 dynamic_threshold_tasks + market_regime_tasks + slippage-calibration 体例;
    #   新增 Beat schedule entry 必须 restart Beat 才载入, restart Celery 才载入新 task).
    "reports-cleanup-weekly": {
        "task": "app.tasks.report_tasks.cleanup_old_reports",
        "schedule": crontab(hour=4, minute=30, day_of_week="0"),  # 0=周日
        "kwargs": {
            "max_age_days": 90,
            "keep_per_tuple": 20,
        },
        "options": {
            "queue": "data_fetch",
            "expires": 3600,  # 1h within next 23h cycle
        },
    },
    # ── daily-attribution-compute (MVP 4.2 sub-iter 7, iter 65) ──
    # Beat entry 触发 `app.tasks.attribution_tasks.daily_attribution_compute_task`
    # 16:30 Mon-Fri Asia/Shanghai — 在 daily-signal (16:00) + daily-execute 之后,
    # 在 daily-moneyflow (17:30) + data-quality-check (17:45) + daily-IC schtask (18:00) 之前.
    # 反 hard collision: 16:30 当前 SH 仅 risk-daily-check 14:30 + 16:00 daily-signal,
    # 16:30 + 30min buffer 前后无 Beat 触发. crontab day_of_week=1-5 过滤周末.
    # 铁律 44 X9 post-merge ops: `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
    #   (新 Beat entry + 新 task module 必须 restart Beat 才载入, restart Celery 才注册 task).
    # 设计稿: docs/mvp/MVP_4_2_attribution.md §4 step 7 + §6 验收 box 4.
    "daily-attribution-compute": {
        "task": "app.tasks.attribution_tasks.daily_attribution_compute_task",
        "schedule": crontab(hour=16, minute=30, day_of_week="1-5"),
        "options": {
            "queue": "factor_calc",
            "expires": 3600,  # 1h within next trading day cycle
        },
    },
    # ── daily-backup-run (MVP 4.4 sub-iter 7, iter 75) ──
    # 02:30 SH daily — DB pg_dump + Filesystem tar + Config tar batched.
    # 反 hard collision: 03:00 SH QuantMind_VacuumAnalyze schtask (30min buffer);
    # 04:30 SH reports-cleanup-weekly (Sunday only, 2h buffer). 02:30 quiet window.
    # 铁律 44 X9 post-merge ops: Servy restart QuantMind-CeleryBeat + QuantMind-Celery
    "daily-backup-run": {
        "task": "app.tasks.backup_tasks.daily_backup_run_task",
        "schedule": crontab(hour=2, minute=30),
        "options": {
            "queue": "data_fetch",
            "expires": 14400,  # 4h: pg_dump can run up to 1h + tar up to 30min + buffer
        },
    },
    # ── weekly-backup-verify (MVP 4.4 sub-iter 7, iter 75) ──
    # Sunday 04:00 SH — restore verification + RPO/RTO snapshot + alert.
    # 反 hard collision: 04:30 SH reports-cleanup-weekly Sunday (30min buffer after).
    "weekly-backup-verify": {
        "task": "app.tasks.backup_tasks.weekly_backup_verify_task",
        "schedule": crontab(hour=4, minute=0, day_of_week="0"),  # 0=Sunday
        "options": {
            "queue": "data_fetch",
            "expires": 7200,  # 2h within next weekly cycle
        },
    },
}
