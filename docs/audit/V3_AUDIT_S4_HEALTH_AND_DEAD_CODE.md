# V3 Audit Section IV — Health + Dead Code + Connectivity (2026-05-18 evening)

> **Source**: Subagent G §13/§16-20 + Subagent C §14 (Dead Code) + Subagent F §15 (Connectivity)
> **Master**: `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`

---

## §13 Code Health Baseline

### §13.1 Linting + Type Checking
- **ruff**: 17 errors (`backend/ scripts/`) — 12 auto-fixable (unused `json`/`uuid` imports in 2 V3 one-shot scripts). **NOT clean baseline**.
- **pytest --co**: **5989 tests collected**, **11 collection errors** in test_news_*.py / test_announcement_processor.py / test_v3_3_5_fail_open_*. Baseline "2864 pass / 24 fail" per CLAUDE.md (Session 9) **stale by ~3120 tests**. P0-12.
- **mypy baseline**: not configured project-wide.

### §13.2 铁律 Compliance Sample
- 铁律 1 (no guess) — held in slippage_model docstrings citing R4
- 铁律 11 (IC唯一入库) — `factor_ic_history` confirmed PK `(factor_name, trade_date)`
- 铁律 17 (DataPipeline) — partial (subset UPSERT exception in LL-066/PR #43-45)
- 铁律 32 (Service 不 commit) — **30 occurrences across 10 files VIOLATED** (notification_service.py / factor_onboarding.py / dingtalk_alert.py / news_ingestion_service.py / shadow_portfolio.py / etc.). P0-9.
- 铁律 35 (secrets env唯一) — partial; `backend/.env` exists with cleartext PG password `quantmind` (P0-2).
- 铁律 40 (test debt not grow) — **VIOLATED**: 11 collection errors today.

### §13.3 Architecture Violations
- Engine layer reading IO: not systematically verified, but Phase C 重构 (factor_engine.py → engines/factor_engine/) suggests recent cleanup
- Service committing transaction: 30 violations P0-9 (above)

---

## §14 Dead Code / Orphan Inventory

### §14.1 Orphan DB Tables (confirmed 0 rows via psql COUNT)

| Table | Size | Status |
|---|---|---|
| forex_bars | 8KB | DEAD (P1-37) |
| forex_events | 16KB | DEAD |
| forex_swap_rates | 8KB | DEAD |
| chip_distribution | 8KB | DEAD |
| approval_queue | 16KB | DEAD |
| gp_approval_queue | n/a | likely dead |
| agent_decision_log | 16KB | DEAD (AI evolution V2.1 partial) |
| experiments | 16KB | DEAD (superseded by `platform_experiments` 25 rows) |
| platform_metrics | 32KB | DEAD (despite MVP 4.1 platform SDK) |
| factor_mining_task | 16KB | likely dead (GP uses pipeline_runs) |
| backtest_holdings / backtest_wf_windows | 8/16KB | likely dead |

**Total 11 dead tables.** Recommended action: DROP after staging validation. Alt: ALTER TABLE add `archived_at` + auto-drop 6mo.

### §14.2 Orphan Celery Tasks (last fire 2026-04-07 to 2026-04-30)

| Task | Last fire | Notes |
|---|---|---|
| pending_monthly_rebalance | 2026-04-30 | likely dead since清仓 |
| data_fetch | 2026-04-08 | DEAD 40d |
| factor_calc | 2026-04-07 | DEAD |
| nav_update | 2026-04-07 | DEAD |
| signal_gen | 2026-04-07 | DEAD |
| circuit_breaker | 2026-03-23 | DEAD |
| execute_phase_paper | 2026-04-16 | DEAD (PT paused) |
| execute_phase_live | 2026-04-17 | DEAD |
| pending_buy_orders | 2026-04-17 | DEAD |

**Action**: Verify Celery worker `--inspect registered` has 0 stale + clear Redis `celery-task-meta-*` backlog (>50 keys).

**Active 8 Celery tasks (last fire 2026-05-18)**: announcement_ingest / factor_health_daily / fundamental_context_ingest / news_ingest_5_sources / news_ingest_rsshub / pt_audit / reconciliation / signal_phase.

### §14.3 Orphan Schtask (Windows Task Scheduler)

| Task | Last fire | Status |
|---|---|---|
| QuantMind_CancelStaleOrders | 2026-04-02 | Disabled 46d (legitimate post-pause) |
| QuantMind_DailyDataIngest_Preopen | 1999-11-30 sentinel | **NEVER FIRED**, LastResult=267011. Delete. |
| QuantMind_DailyDataIngest_Postclose | 1999-11-30 sentinel | **NEVER FIRED**, LastResult=267011. Delete. |
| QuantMind_DailyExecute | 2026-04-19 | Disabled per LL-183 pause — justified |

**Action**: Unregister 2 sentinel orphans + re-evaluate CancelStaleOrders.

### §14.4 Orphan Redis Keys

11 namespace prefixes detected: most have grep matches in `backend/`. Suspect orphan: `_kombu.binding.factor_calc` (task `factor_calc` dead since 2026-04-07). 1454 `celery-task-meta-*` keys ~96% of Redis content — suggest no result TTL.

**Action**: Set `CELERY_RESULT_EXPIRES=3600` in celery_app config.

### §14.5 Unused Python Imports

`ruff F401`: 0 errors in production code (`backend/app/ backend/engines/`). 3 errors in 2 one-shot V3 scripts only.

### §14.6 Orphan Scripts (sample 80 total)

Likely orphan based on no schtask + no doc cite + no runbook ref:
- `_verify_account_oneshot.py` (one-shot diag with unused imports)
- `fix_nan_cleanup.py` (one-shot 2026-04)
- `fix_st_cleanup_20260414.py` (one-shot)
- `setup_paper_trading.py` (PT setup done 4-29)
- `v3_ct_* / v3_ic_* / v3_hc_* / v3_tb_*` (15 V3 sprint scripts, one-shot)

**Action**: Move to `scripts/archive/` (~20 scripts at-glance review).

### §14.7 Deprecated Docs (Still in docs/)

15 files match `DEPRECATED|OBSOLETE|ARCHIVED`. Top archive candidates:
- `docs/audit/link_paused_2026_04_29.md` (historical link-pause audit)
- `docs/audit/factor_count_drift_2026_05_01.md` (sediment closed)
- `docs/adr/ADR-005-critical-not-db-event.md` (potentially stale)
- `docs/audit/2026_05_audit/snapshot/03_services_schedule.md` (5-month-old)

### §14.8 Frontend Unused Components

13 root tsx + 8 subdirs (~25 sub-components). Risk LOW — small surface. `knip` not invoked. Manual review recommended in Phase H.

---

## §15 Connectivity Audit (Subagent F)

### §15.1 Backend Service → API Exposure

| Service | API endpoint? | Status |
|---|---|---|
| paper_trading_service | /api/paper-trading/* 5 ep | ✅ |
| backtest_service | /api/backtest/* 16 ep | ✅ |
| factor_service (4 services) | /api/factors/* 8 ep | ✅ partial — 4 services / 8 endpoints |
| mining_service | /api/mining/* 5 ep | ✅ |
| execution_service | /api/execution/* 3 + /api/execution-ops/* 17 | ✅ overlapped |
| dashboard_service | /api/dashboard/* 8 ep | ✅ |
| risk_control_service | /api/risk/* 10 ep | ✅ |
| **7 risk subservices** (risk_wiring / reflector_agent / dynamic_threshold / meta_monitor / staged_execution / dingtalk_webhook / market_indicators_query) | **0 dedicated API endpoints** | ❌ P1-36 |
| signal_service | internal only (Celery task path) | ⚠️ partial |
| pms_engine | /api/pms/* 4 ep | ✅ |
| qmt_reconciliation_service | internal only | ⚠️ |
| notification_service (5 services) | /api/notifications/* 5 ep | ✅ |
| param_service | /api/params/* 5 ep | ✅ |
| trading_calendar / shadow_portfolio / fundamental_context_service / t0_19_audit | 0 endpoints | ⚠️ internal |
| news services (3) | /api/news/* 4 ep | ✅ |

**Coverage**: ~36 services / ~21 have API surfaces (58%). **Risk subservice cluster has 0 dedicated endpoints** (P1-36).

### §15.2 API → Frontend Consumption

132 endpoints total. Orphan APIs (0 frontend usage):

| Endpoint | Frontend? | Status |
|---|---|---|
| /api/approval/queue + 5 sub-endpoints | ❌ no grep on /approval | Orphan #2 |
| /api/notifications/unread-count + read/test (5) | ❌ no notification UI page | Orphan #2 |
| /api/news/ingest_rsshub + /ingest_announcement | ❌ no news UI | Orphan #2 |
| /api/remote_status/ping + /status | ❌ | possibly heartbeat |
| /api/portfolio/* (3) | ✅ Portfolio.tsx | OK |
| /api/strategies/{id}/* (10) | ✅ StrategyLibrary | OK |
| /api/params/* (5) | ✅ SystemSettings | OK |

### §15.3 DB Table → Service Usage

| Table | INSERT/SELECT service | Status |
|---|---|---|
| factor_ic_history | factor_repository.py (9 refs) + compute_daily_ic.py + factor_onboarding.py (48 refs) | ✅ alive |
| factor_values | factor_compute_service / factor_repository / data_orchestrator | ✅ alive |
| factor_lifecycle | engines/factor_lifecycle.py + daily_pipeline.factor_lifecycle | ✅ alive |
| trade_log | repositories/trade_repository.py (5 refs) | ✅ alive |
| risk_event_log | qm_platform/risk/sources/_enricher.py (8 refs) + risk_repository.py (3) | ✅ alive (PR #212 first real write) |
| approval_queue | api/approval.py (9) + models/approval_queue.py (6) + risk_control_service (11) | ⚠️ **backend-only, no UI** |
| chip_distribution / forex_bars / agent_decision_log / experiments | 0 service refs | ❌ **Orphan** (P1-37 + sibling) |
| platform_metrics | migrations/*.sql + qm_platform/observability/metric.py (5) | ⚠️ **write-only, no UI/dashboard** |

### §15.4 Celery Task → Beat Trigger

Active 17 Celery tasks → mostly wired to Beat. 5 orphan tasks (no Beat entry, last fire 2026-04-07 to 2026-04-30 — P1-56 candidate).

### §15.5 External API Quota Tracking

| API | Quota tracking | Coverage |
|---|---|---|
| Tushare | No explicit usage tracker found (Grep `tushare.*quota` 0) | ❌ P1-33 |
| DingTalk webhook | dingtalk_webhook_service.py + alert_dedup table | ✅ partial (dedup, no quota) |
| 6 news APIs | Per-source limit_per_source in beat config | ⚠️ partial (rate limit, no cost) |
| DeepSeek (LLM_BUDGET) | llm_call_log + llm_cost_daily + daily report 20:30 | ✅ daily, ❌ **no monthly aggregator P0-16** |

---

## §16 Observability + Operations

### §16.1 Servy Services State
- **4 RUNNING**: FastAPI / Celery / CeleryBeat / QMTData
- **Redis not Servy-managed** (Windows native service)
- Beat heartbeat fresh 1.3min ago per services_healthcheck.log 22:30

### §16.2 Log Inventory (Top 5)
- `fastapi-stdout.log` 10.82 MB
- `qmt-data-stderr.log` 10.81 MB
- `fastapi-stderr.log` 8.83 MB
- `celery-beat-stderr.log` 7.84 MB
- `app.log` 4.11 MB
- **No rotation evident** (P1-45). Largest last write 18:22:44 (active).

### §16.3 Metrics + Traces
- risk_metrics_daily / scheduler_task_log / llm_call_log tables present
- alert_dedup + qm:* streams (verified dark P0-8)

### §16.4 SLI/SLO Monitoring
- V3 §13.1 6 SLA — dashboard 真存在吗? Not surfaced in audit
- meta_monitor 5min Beat — 7 polled rules

### §16.5 Alerting Channel Chain
- DingTalk active (webhook tested today via DataQualityCheck alert)
- Email backup (config exists, not in .env)
- 弹窗 (frontend) — not e2e tested

---

## §17 Security / Compliance

### §17.1 Findings (Reference Master P0-2, P0-22, P1-43, P1-44)

- **P0-2**: PG password `quantmind` plaintext in .env + 6 .bak files leaked to logs/
- **P0-22**: Admin token in localStorage XSS-vulnerable
- **P1-43**: DingTalk outbound HMAC disabled (SECRET empty)
- **P1-44**: FastAPI auth only `execution_ops.py` references ADMIN_TOKEN (3 hits) — wide surface
- **Backup encryption**: `backups/daily/quantmind_v2_20260518.dump` 14.46 GB unencrypted, no off-site copy

### §17.2 红线 + 双锁 Enforcement
- LIVE_TRADING_DISABLED: ✅ wired; **P0-1 DRIFT (=false)**
- L4_AUTO_MODE_ENABLED: ⚠️ NOT in production code (only test) — citation as 双锁 misleading
- DINGTALK_ALERTS_ENABLED: ✅ wired
- QMT_ACCOUNT_ID=81001102: ✅
- EXECUTION_MODE: ✅ wired; **DRIFT: =live**

### §17.3 Audit Log Immutability
- Not specifically tested in audit. risk_event_log + trade_log + scheduler_task_log are append-only via INSERT.
- PR #212 (5-02 sediment) demonstrated audit row backfill SQL write 5-condition SOP — pattern established.

---

## §18 Data Health

### §18.1 Freshness Per Table
- `daily_basic` latest=2026-05-18 confirmed by DataQualityCheck log
- `klines_daily` latest=2026-05-18
- `moneyflow_daily` latest=2026-05-18
- `factor_values` last verified 2026-04-30 (Session 45 sediment, stale 18+ days for audit)
- `trade_log` last entry 2026-04-17 (PT paused since)

### §18.2 Backup Chain
- 5 daily dumps 0514→0518: 1375 MB → 14460 MB (10x growth in 4 days — anomalous)
- monthly: only `20260501.dump`
- **pg_restore never tested in 2026 (P0-3 CRITICAL)**

### §18.3 Integrity
- FK/NULL/dtype: not systematically audited this pass
- TimescaleDB hypertables (factor_values 152 chunks / klines 53) auto-managed

---

## §19 Performance + Resources (Verify 2026-05-18 22:00)

| Resource | Status | Headroom |
|---|---|---|
| **RAM** | 22 GB used / 31 GB total (70%) | 9.4 GB free; tight for 2-process limit during peak 09:30 SH market open (expected 28 GB peak ~90%) |
| **GPU** RTX 5070 | 1412/12227 MB (11.5%), 47°C, 39W, 4% util | Plenty headroom |
| **Disk D:** | 418 GB used / 655 GB free (38%) | pgdata16=227 GB (35% of used) |
| **Redis** | 3.00M used / 0B max | streams dark (verified P0-8) |

---

## §20 Governance / Audit

### §20.1 LL Count Drift
- Memory says 94 (sustained sediment 5-14)
- Actual `grep -E "^(### |## )LL-[0-9]+" LESSONS_LEARNED.md` = 160 sections
- Either header pattern shift or drift unrepaired — P1-41

### §20.2 ADR Count Drift
- 67 ADR files in `docs/adr/`
- CLAUDE.md says "ADR-001~ADR-022" — drift 45 missing — P1-42

### §20.3 STATUS_REPORT Chain
- 31 STATUS_REPORT*.md exist
- Latest 2026-05-02 19:23 — **16 days stale** given LL-183 today
- Recommendation: write 2026-05-18 evening STATUS_REPORT cumulative (audit + LL-180/181/182/183)

### §20.4 Memory Hooks Effectiveness
- LL-098 X10 forcing function — intact in commit history
- LL-106 4-doc fresh read SOP — partial (this audit's cross-validate gates implement)
- Sprint state >90k tokens — P1-46

---

**End Section IV.**
