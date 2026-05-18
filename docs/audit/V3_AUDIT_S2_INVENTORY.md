# V3 Audit Section II — Complete Inventory (2026-05-18 evening)

> **Source**: Subagent A §3-5 + Subagent C §7 / Cross-validated by CC main process
> **Sub-docs**: `V3_AUDIT_S2_DOC_STATUS_MATRIX.md` + `V3_AUDIT_S2_DESIGN_VS_REALITY_GAP.md`
> **Master**: `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`

---

## §3 Code Inventory Verified

### §3.1 backend/app (CC top-level verified, NOT recursive)

| Directory | Phase 0 claim | CC verified (top-level .py) | Drift | Notes |
|---|---|---|---|---|
| backend/app/api/ | 23 routers | 22 .py files; **132 endpoints** (grep `@router.(get\|post\|put\|delete\|patch)`) | Phase 0 said 121 — **+11 actual** | #1 Drift |
| backend/app/services/ | 113 services | **40 .py top-level** + subdirs | -64% top-level | Phase 0 likely counted function defs |
| backend/app/tasks/ | 34 task files | 17 .py top-level | -50% | Similar |
| backend/app/core/ | 12 | 6 top-level | -50% | |
| backend/app/data_fetcher/ | 11 | 5 top-level | -55% | |
| backend/app/schemas/ | 8 | 8 | OK | |
| backend/app/utils/ | 7 | 5 | -29% | |
| backend/app/websocket/ | 6 | 3 | -50% | |
| backend/app/security/ | 4 | 2 | -50% | |
| backend/app/repositories/ | 22 | 12 | -45% | |
| backend/app/models/ | 20 | 10 | -50% | |

**Pattern**: Phase 0 baseline likely counted function definitions or recursive subdirs. CC top-level counts are更 accurate metric.

### §3.2 backend/engines

- **CC verified**: 45 .py top-level (matches Phase 0 claim)
- Subagent A counted 86 recursive (includes subdirs/__pycache__)
- **45 active engines**: factor_engine (now `factor_engine/` package per Phase C refactor) / backtest / config_guard / slippage_model / broker_qmt (LL-182 fix) / paper_broker / sim_broker / qmt_execution_adapter / walk_forward / mining / factor_lifecycle / ic_calculator / factor_profiler / factor_gate / ...

### §3.3 backend/qm_platform

- **CC verified**: 18 directories (including `__pycache__`) → ~15 actual frameworks
- Frameworks: backtest / backup / ci / config / data / eval / factor / knowledge / llm / news / observability / resource / risk / signal / strategy
- CLAUDE.md says "12 Framework + 6 升维" but actual count differs
- Phase 0 said "12 frameworks, 15 found" — matches CC verification

### §3.4 backend/migrations

- 54 .sql files (matches Phase 0)
- Idempotent + rollback pair check: not done in audit
- Most migrations follow `<timestamp>_<description>.sql` pattern

### §3.5 backend/tests

- 350 .py test files (per Subagent A)
- **5989 test functions** (CC verified via pytest --co)
- **11 collection errors** today (P0-12)
- CLAUDE.md baseline "2864 pass / 24 fail" (Session 9 era) — **drift +109% growth**
- 41 `*live*.py` files (live trading specific tests)

### §3.6 scripts/

- **CC verified**: 80 .py top-level (matches Phase 0 80+)
- Subagent A counted 301 recursive (includes scripts/archive/)
- Categories per CLAUDE.md: run_paper_trading / run_backtest / qmt_data_service / health_check / pt_watchdog / pg_backup / approve_l4 / cancel_stale_orders / data_quality_check / monitor_factor_ic / registry / knowledge / archive / research / 17 v3_*_*.py one-shot V3 sprint deliverables / disaster_recovery_verify.py (never run 2026)

### §3.7 frontend/src/

- **Last commit on `frontend/`**: 2026-04-17 15:19:08 `6f57180` (`git log -1 -- frontend/`)
- **31 days stale** as of audit date
- React 18.3.1 + TypeScript 5.7.2 + Vite 6.3.1 + Tailwind 4.1.3 + Zustand 5.0.12 + ECharts 5.6.0 + Recharts 3.8.1 + socket.io-client 4.8.3 (no server)
- Pages: 35 .tsx / Components: 54 / Hooks: 4 / Stores: 4 / Theme: 2

### §3.8 configs/

- 6 files: alert_rules.yaml / backtest_12yr_sn050.yaml / backtest_12yr.yaml / backtest_5yr.yaml / pt_live.yaml / sw_industry_mapping.json

### §3.9 .claude/

- **DRIFT**: `.claude/CLAUDE.md` says "11 agents 全删除 (2026-04-15)"
- **Reality**: 7 V3 governance agents present (quantmind-cite-source-verifier / -prompt-iteration-evaluator / -redline-guardian / -risk-domain-expert / -v3-sprint-closure-gate-evaluator / -v3-sprint-orchestrator / -v3-tier-a-mvp-gate-evaluator)
- **#14 Doc Lying / #20 Reverse Mapping** — new V3 governance layer added post-deletion claim

---

## §4 API/Interface Inventory

### §4.1 FastAPI 132 Endpoints (by router)

| Router | Endpoints |
|---|---|
| backtest.py | 16 |
| execution_ops.py | 17 |
| strategies.py | 10 |
| risk.py | 10 |
| dashboard.py | 8 |
| factors.py | 8 |
| approval.py | 6 |
| system.py | 5 |
| mining.py | 5 |
| pipeline.py | 5 |
| params.py | 5 |
| paper_trading.py | 5 |
| notifications.py | 5 |
| news.py | 4 |
| pms.py | 4 |
| portfolio.py | 3 |
| market.py | 3 |
| health.py | 3 |
| execution.py | 3 |
| report.py | 3 |
| remote_status.py | 2 |
| realtime.py | 2 |

**Orphan candidates (#2)**:
- `remote_status.py` (2 ep) — unclear consumer
- `pms.py` (4 ep) — deprecated per CLAUDE.md (旧版 PMS Beat停 PR #34)
- `execution.py` (3 ep) vs execution_ops.py (17 ep) — overlap likely
- `pipeline.py` (5 ep) — DataOrchestrator now centralized
- `realtime.py` (2 ep) — possibly merged into websocket layer

### §4.2 Celery Task Modules (17, Phase 0 said 11 — +55% drift)

`announcement_ingest_tasks` / `backtest_tasks` / `beat_schedule` / `celery_app` / `daily_metrics_extract_tasks` / `daily_pipeline` / `dynamic_threshold_tasks` / `fundamental_ingest_tasks` / `l4_sweep_tasks` / `market_regime_tasks` / `meta_monitor_tasks` / `mining_tasks` / `news_ingest_tasks` / `onboarding_tasks` / `outbox_publisher` / `risk_reflector_tasks`

### §4.3 Beat Schedule — 32 Entries (Phase 0 said 15+, +113% drift)

Cite `backend/app/tasks/beat_schedule.py`. Sample:
- `gp-weekly-mining` Sun 22:00
- `outbox-publisher-tick` every 30s
- `daily-quality-report` Mon-Fri 17:40
- `factor-lifecycle-weekly` Fri 19:00
- `news-ingest-5-source-cadence` 6×/day
- `risk-dynamic-threshold-5min` 5min trading hours
- `risk-l4-sweep-1min` 1min trading hours
- `risk-l4-broker-stuck-sweep` */5 all hours
- `risk-market-regime-0900/1430/1600` 3×/day
- `risk-metrics-daily-extract-16-30` Mon-Fri 16:30
- `risk-reflector-weekly` Sun 19:00
- `risk-reflector-monthly` Day-1 09:00 (cadence mismatch with "Last Sun" per Plan)
- `meta-monitor-tick` 5min all hours
- `fundamental-context-daily-1600` 16:00

### §4.4 Windows Schtask — 19 QuantMind_* (verified 2026-05-18 22:55)

| State | Tasks |
|---|---|
| **Ready (13)** | DailyIC / DailyMoneyflow / DailyReconciliation / DailySignal / DataQualityCheck (LastResult=1 today, P0) / FactorHealthDaily / IcRolling / IntradayMonitor / LLMCostDaily / MiniQMT_AutoStart / MVP31SunsetMonitor / PTAudit / PT_Watchdog / RiskFrameworkHealth (LastResult=1 today, P0) / ServicesHealthCheck |
| **Disabled (4)** | CancelStaleOrders (last 2026-04-02) / DailyDataIngest_Postclose (last 1999-11-30, never ran P1) / DailyDataIngest_Preopen (last 1999-11-30, never ran P1) / DailyExecute (last 2026-04-19, LL-183 revoke) |

### §4.5 Redis Streams + Cache Keys (Verified Dark)

**Per CC main process verify 2026-05-18 22:50 SH**:
- `redis-cli --scan --pattern "qm:*"` → **0 results**
- `redis-cli --scan --pattern "portfolio:*"` → **0 results**
- DBSIZE = 1455 keys (96%+ `celery-task-meta-*` orphan backlog)

| Pattern | Definition cite | Producer | Consumer | Live? |
|---|---|---|---|---|
| `qm:signal:generated` | `stream_bus.py:28-29`, `signal_service.py:287` | signal_service | outbox_publisher / observability | **0 keys** |
| `qm:fill:executed` | `stream_bus.py:29-30` | broker | observability | 0 |
| `qm:execution:order_failed` | `stream_bus.py:32` | broker | risk | 0 |
| `qm:factor:computed` | `stream_bus.py:33` | factor compute | observability | 0 |
| `qm:qmt:status` | `stream_bus.py:36`, `intraday.py:33` | qmt_data_service | risk | 0 |
| `qm:pms:protection_triggered` | `stream_bus.py:39`, `pms_engine.py:8` | pms_engine | — | 0 (0 消费者) |
| `qm:dlq:outbox` | `outbox_publisher.py:38` | outbox failed retry max=10 | — | 0 |
| `qm:risk:l1_triggered` | `runtime_keys.py:46` | risk realtime | — | 0 |
| `qm:risk:dedup:*` | `risk_wiring.py:261, 292` | risk_wiring | risk | 0 |
| `qm:news:last_run_stats` | `meta_alert_interface.py:48` | news ingest | meta_monitor | 0 |
| `portfolio:current/nav` `market:latest:*` | `qm_platform/risk/interface.py:30, 106` | qmt_data_service | risk/strategy | 0 |
| `celery-task-meta-*` | celery default | celery workers | celery results | **1454 keys** |

**P0-008**: Production data plane dark. PT paused legitimately or qmt_data_service not writing despite Ready schtask.

### §4.6 External APIs

| API | Cite | Status |
|---|---|---|
| Tushare | `backend/app/data_fetcher/tushare_api.py` | active token in .env:6 |
| DingTalk | `backend/app/services/dingtalk_alert.py` + 42 files grep | active; outbound HMAC=DISABLED (DINGTALK_SECRET empty) |
| DeepSeek | `backend/.env:9` `DEEPSEEK_API_KEY=sk-ad4c1...` | live key plaintext (P0-2) |
| akshare/baostock | `qm_platform/data/sources/*` | active |
| 6 news APIs | `qm_platform/news/*` (Anspire/GDELT/MarketAux/RSSHub/Tavily/Zhipu) | active per test files |
| xtquant | **DRIFT**: CLAUDE.md says "唯一允许 import = scripts/qmt_data_service.py"; **Actual**: `qmt_data_service.py:11-13` says "不再本脚本直接 import xtquant, lazy via QMTDataSource". 2 archive scripts still import | #14 Doc Lying |

---

## §5 Data Inventory

### §5.1 PG Tables (psql password blocked across audit; baseline per CLAUDE.md 2026-04-30 Session 45)

| Table | Rows | Size | Status |
|---|---|---|---|
| factor_values | 840,478,083 | ~172 GB hypertable 152 chunks | stale 18+ days |
| factor_ic_history | 145,894 | ~36 MB | last verified 4-30 |
| minute_bars | 190,885,634 | ~36 GB | 5yr Baostock 2537 stocks |
| klines_daily | 11,776,616 | ~4 GB hypertable 53 chunks | |
| daily_basic | 11,681,799 | ~3.7 GB | |

**Subagent C confirmed 11 dead tables (0 rows / 0 service refs)**:
- forex_bars / forex_events / forex_swap_rates (P1-37)
- chip_distribution
- approval_queue / gp_approval_queue
- agent_decision_log
- experiments
- platform_metrics (despite MVP 4.1)
- factor_mining_task
- backtest_holdings / backtest_wf_windows

### §5.2 TimescaleDB Hypertables

- `factor_values` 152 chunks (per CLAUDE.md)
- `klines_daily` 53 chunks
- Other tables traditional non-hypertable

### §5.3 Parquet Cache (按年分区)

- `backend/data/parquet_cache.py` — `_load_shared_data` 30min → 1.6s (1000× speedup)
- Local snapshot, 按日期分区
- Last successful date 2026-04-28 per Session 50 sediment (20 trading days stale)
- Auto-detect cache validity

### §5.4 Redis Cardinality

- `used_memory_human` 3.00M
- `maxmemory_human` 0B (no cap — risk)
- DBSIZE 1455
- 96%+ `celery-task-meta-*` (Celery task result backend, possibly leaking memory without TTL)
- 0 production data plane keys (qm:* / portfolio:*)

---

## §7 Config + 红线 Inventory

### §7.1 .env Field Inventory (Sample, masked secrets)

| Field | Purpose | Reader (config.py) | Default | Current |
|---|---|---|---|---|
| DATABASE_URL | PG DSN | :24 | `postgresql+asyncpg://xin:REPLACE@localhost:5432/quantmind_v2` | `postgresql+asyncpg://xin:****@localhost:5432/quantmind_v2` (P0-2: weak `quantmind` plaintext) |
| REDIS_URL | Redis URI | :25 | `redis://localhost:6379/0` | same |
| TUSHARE_TOKEN | Tushare API | :28 | "" | `5513****ea` set |
| DEEPSEEK_API_KEY | DeepSeek LLM | :31 | "" | `sk-ad****d6a` set |
| ZHIPU_API_KEY / TAVILY_API_KEY / ANSPIRE_API_KEY / MARKETAUX_API_KEY | News APIs | :36-47 | "" | All set |
| LLM_MONTHLY_BUDGET_USD | LLM cap | :62 | `50.0` | default |
| LLM_BUDGET_WARN_THRESHOLD | warn ratio | :63 | `0.80` | default (vs CLAUDE.md cite "50%" #14 drift) |
| LLM_BUDGET_CAP_THRESHOLD | cap ratio | :64 | `1.00` | default |
| **EXECUTION_MODE** | paper/live | :69 | `paper` | **`live`** (P0-1 DRIFT) |
| **LIVE_TRADING_DISABLED** | 真金硬开关 | :82 | `True` (fail-secure) | **`false`** (P0-1 DRIFT) |
| PT_TOP_N | 选股数 | :85 | `20` | **`5`** (LL-183 灰度) |
| PT_INDUSTRY_CAP | 行业上限 | :86 | `1.0` | `1.0` |
| PT_SIZE_NEUTRAL_BETA | SN beta | :91 | `0.50` | `0.50` |
| DINGTALK_WEBHOOK_URL | webhook | :107 | "" | `https://....94f75****` set |
| **DINGTALK_ALERTS_ENABLED** | 钉钉双锁 | :111 | `False` | **`true`** (Phase C C1a flip 5-17) |
| DINGTALK_SECRET | outbound sign | :114 | "" | **empty** (P1-43 HMAC disabled) |
| DINGTALK_KEYWORD | 关键词 | :115 | "" | `xin` |
| QMT_PATH / QMT_ACCOUNT_ID / QMT_EXE_PATH | xtquant | :145-147 | "" | Set, QMT_ACCOUNT_ID=`81001102` ✅ |
| QMT_ALWAYS_CONNECT | 强连接 | :148 | `False` | `true` |
| PAPER_STRATEGY_ID | strategy id | :151 | "" | `28fc37e5-...` |
| PAPER_INITIAL_CAPITAL | seed | :152 | `1_000_000.0` | `1000000` |
| ADMIN_TOKEN | API auth | :155 | "" | `5Beal****fBLA` set |
| ADMIN_PASSWORD | password | implicit | n/a | weak default risk |
| L4_SWEEP_BATCH_LIMIT | L4 cap | :136 | `100` | default |
| OBSERVABILITY_USE_PLATFORM_SDK | SDK toggle | :142 | `True` | default |

### §7.2 5/5 红线 + V3 §17.2 双锁 Enforcement (verify 2026-05-18 21:00 SH)

| 红线 | Enforcement | Status |
|---|---|---|
| LIVE_TRADING_DISABLED | `backend/app/security/live_trading_guard.py` + `broker_qmt.py` + `config_guard.py` (15 prod + 8 test files) | ✅ wired; **P0-1 DRIFT** (=false vs CLAUDE.md "=true sustained") |
| L4_AUTO_MODE_ENABLED | **0 production code grep** — only test/audit. **NOT a runtime gate in config.py** | ⚠️ P1 cited as red-line but missing enforcement |
| DINGTALK_ALERTS_ENABLED | `dingtalk_alert.py` + `config_guard.py` + 42 files | ✅ wired |
| QMT_ACCOUNT_ID=81001102 | `.env:13` | ✅ matches memory |
| EXECUTION_MODE | `qm_platform/config/loader.py` + `config_guard.py` + 42 files | ✅ wired; **DRIFT: =live** |

### §7.3 V3 Threshold SSOT (verify)

| Threshold | Current | SSOT location | Grep refs | Sprawl |
|---|---|---|---|---|
| PT_TOP_N | 5 | config.py:85 | 12 hits | LOW |
| PT_INDUSTRY_CAP | 1.0 | config.py:86 | 8 | LOW |
| PT_SIZE_NEUTRAL_BETA | 0.50 | config.py:91 | 6 | LOW |
| heartbeat 300s | not located | **no SSOT in config.py** | 0 | ⚠️ likely hardcoded in Servy XML |
| LiteLLM throttle 50% | **MEMORY says 50%, actual config.py 80% warn / 100% cap** | budget.py:63-64 | 0 | ❌ **#14 Doc Lying** |
| cancel_deadline 2100s | **0 grep hits** | **no SSOT** | 0 | ❌ Plan-cited but absent (P1-25) |
| pg slow query 50 conn | 0 grep | unknown | 0 | unverifiable |
| MarketRegime -7% | yaml-driven likely (15 files ref'd) | unknown | unknown | likely yaml |

### §7.4 Hardcoded Values (Top 15 picks)

| Code location | Value | Should be config? | Recommendation |
|---|---|---|---|
| beat_schedule.py:147 | `symbol_id="600519"` hardcoded for announcement_ingest | **YES** — production multi-symbol blocker | yaml strategy_universe / DB query |
| beat_schedule.py:165 | `symbol_id="600519"` for fundamental_context | **YES** same | yaml / DB query |
| beat_schedule.py:127 | `route_path="/jin10/news"` hardcoded | YES (LL-115 sediment) | yaml route_list |
| 4 v3 scripts | "5d paper-mode" duration | LIKELY | settings.PAPER_MODE_DAYS |
| beat_schedule.py:77/187/212/248 | various expires + cron | LOW | leave / settings |
| config.py:127 | SMTP_PORT=587 | OK default | — |

---

## §6 Doc Inventory — Reference

See sub-docs:
- `V3_AUDIT_S2_DOC_STATUS_MATRIX.md` — 165 docs status matrix
- `V3_AUDIT_S2_DESIGN_VS_REALITY_GAP.md` — 20 design docs IMPLEMENTED % + valuable-but-未实施 + recommendation (NEW v8)

---

**End Section II.**
