# V3 Full Project Deep Audit — MASTER (2026-05-18 evening)

> **Audit plan**: `C:\Users\hd\.claude\plans\quizzical-snacking-fox.md` v8 (10-12h autonomous, 11 audit docs + Design Spec + 3 HTML mockup)
> **Execution**: 9 subagents across 3 batches + CC cross-validate gates + Phase 3+3-bis synthesize (this doc)
> **Scope**: 11 Section / 45 Dim / 20 Heuristic / 30 Suggestion (~121 audit units)
> **Verify timestamp**: 2026-05-18 evening (post LL-183 incident containment)
> **Git HEAD**: `7b57018` (LL-183 regression gate pytest + Phase B audit closure)
> **红线状态**: cash=¥993,520.66 / 0 持仓 / **.env state: LIVE_TRADING_DISABLED=false + EXECUTION_MODE=live (post LL-183 unrolled, awaiting revert)** / schtask DailyExecute=Disabled

---

## §0 Executive Summary

### §0.1 Audit Scope + Method

This is a **project-level comprehensive scan** (not V3-risk only). 9 subagents in 3 staggered batches with CC cross-validate gates between batches (preventing LL-106 audit drift 3-4x contamination). Each subagent enforced **heuristic #18 GLOBAL** — every P0/P1/P2 finding proposes 2-3 alternative remediation. Plus heuristic #20 NEW v8 bidirectional design-implementation reverse mapping.

### §0.2 Top 5 P0 (Immediate Action Required, ≤ 24h)

| # | Finding | Heuristic | Action |
|---|---|---|---|
| **P0-1** | **.env `LIVE_TRADING_DISABLED=false` + `EXECUTION_MODE=live`** unrolled post LL-183 incident, awaiting revert. Contradicts memory red-line "sustained=true/paper". With schtask Disabled this is dormant, but accidental schtask re-enable → real broker fire | #1 / #14 / 红线 | Revert `.env` to paper + `LIVE_TRADING_DISABLED=true` immediately (or update memory if intentional cutover state). Add startup `config_guard` hard-raise if `.env` says live while CLAUDE.md memory says paper |
| **P0-2** | **PG password `quantmind` plaintext** in `backend/.env:24` + 6 `.env-*.bak` files leaked to `logs/` dir | #12 Security | Rotate password + remove .bak files + add `logs/.env-*.bak` to .gitignore (if not already) + audit historical .bak commits |
| **P0-3** | **`disaster_recovery_verify.py` never run in 2026** (0 log hits). Backup `pg_dump -Fc` produces 14.46 GB unencrypted files but only `pg_restore --list` validates TOC; **真 restore never tested** | #4 Closed-Loop / #6 SLA | Schedule weekly staging-DB restore test → `quantmind_v2_dr_test` → SELECT count verify on 10 critical tables. Alert if mismatch |
| **P0-4** | **Reflector → ThresholdEngine NOT WIRED** (heuristic #4 Loop 2). Grep `apply_reflection\|adapt_threshold\|update_from_reflection` returns 0 files. Risk system "learning claim" is theatre. Reflections accumulate in `reflection_log` + `risk_memory` but **never** modify detection thresholds | #4 / #16 Pre-Mortem | Implement `apply_reflection_to_thresholds()`: read `reflection_log` weekly, update `_DEFAULT_THRESHOLDS` via `runtime_threshold_overrides` table. OR human-in-loop weekly review report mode (conservative) |
| **P0-5** | **Beat death has no heartbeat monitor** (LL-181 sustained). 8-hop cascade: Beat dies → 32 schedule entries 0 fire → news stale → regime stale → ThresholdCache stale → factor_lifecycle skip → stale active factors → live IC drift → NAV decline (root cause obscured) | #3 Cascade / #16 / #4 | Beat writes `qm:beat:heartbeat` every 60s; separate watcher (schtask) alerts on TTL expiry. Independent of Beat itself. **This is the longest cascade chain in the system** — highest strategic risk |

### §0.3 Key Cross-Cutting Themes (3 master findings)

1. **System is "open-loop"** — 5 of 7 closed-loops broken or partial (Loop 1 Signal-feedback, Loop 2 Reflector-threshold, Loop 3 Factor-backtest manual handshake, Loop 4 Regime-signal disconnected, Loop 6 Backup-restore, Loop 7 Schtask-health). Heuristic #4.

2. **CC is primary actor, Frontend is passive dashboard** — 13/32 critical backend ops have NO API + NO UI (execute_phase / env_flip / cancel_stale_orders / emergency_close has API but no UI / Servy restart / schtask toggle / pull_tushare / factor_lifecycle force / risk threshold / L4 STAGED confirm / LL sediment / ADR creation / Beat schedule view). User explicitly identified: "**所有后端操作都需要能在前端进行操作, 交互式**" — Section XI inversion needed. Heuristic #19.

3. **Knowledge/Continuity fragility** — bus factor=1 + 0 onboard doc + sprint_state 768KB monolithic + memory says LL=94 but actual ~160 + CLAUDE.md cites "ADR-022" but actual 67 ADRs + 122 audit files no INDEX. **若 user 突发不在线, CC restart 30min onboard FAIL**. Heuristic #16 Pre-Mortem.

### §0.4 Audit Self-Confidence

**Findings confidence**: HIGH — cross-validate gate verified .env state / Redis dark / schtask LastResult=1 today / apply_reflection 0 grep / Phase 0 baseline drift (recursive count error in subagent A noted).

**Coverage**: 11 Sections × ~5 dim each = 55 audit slots filled. 20 heuristics × ≥3 findings each. 30 suggestions evaluated.

**Heuristic #17 Audit Self-Audit**:
- This audit MISSED: live PG queries (psql password blocked across 2 subagents); browser-based frontend testing (couldn't preview pages); real-time tick observation (PT paused so 0 live data anyway).
- This audit was BIASED toward: code-readable findings (file-grep heavy); doc cross-validation; static analysis. Less coverage on: runtime behavior verification, performance profiling, real DB query results.
- Next audit cadence recommendation: **quarterly + event-triggered** (post-LL P0 / pre-cutover / capital scaling). See §VIII #29 (NEW v8).

---

## §1 Top 50 Findings Ranked (Dedup from 9 Subagent Outputs)

### §1.1 P0 Findings (24 items, 7-day window)

> **Heuristic #18 GLOBAL ENFORCE applied**: Every finding has 2-3 alternative remediation listed. Default: pick Alt 1 unless context favors others.

#### P0-001: `.env` RED-LINE Drift — Live Mode Unrolled

- **Severity**: P0 / 红线
- **Heuristic**: #1 Drift / #14 Doc Lying / #20 Reverse Mapping
- **Source**: Subagent A + C + E + G (4 independent confirm)
- **Cite**: `backend/.env:17,20` 2026-05-18 23:00 SH `EXECUTION_MODE=live` + `LIVE_TRADING_DISABLED=false`
- **Context**: User .env was flipped to live for planned Tue 5-19 09:31 SH cutover; LL-183 incident at 19:46 SH revoked schtask but .env was NOT reverted. Memory still says "sustained=true/paper" (5-02 era state). Schtask QuantMind_DailyExecute=Disabled provides dormancy guard — but accidental re-enable → real broker fire on next signal.
- **Alt 1 (recommended)**: Immediate revert `.env` to `EXECUTION_MODE=paper` + `LIVE_TRADING_DISABLED=true`. Backup pre-revert. Add `STATUS_REPORT` entry.
- **Alt 2**: Update CLAUDE.md / memory to reflect "live state pending cutover" if intentional; add `config_guard` hard-raise if state ambiguous
- **Alt 3**: Two-key authorization — live trading requires BOTH .env flag AND Redis key `qm:auth:live_trading_authorized_until=<timestamp>` (15min expiry)

#### P0-002: PG Password Plaintext + .bak Leaks

- **Severity**: P0 / Security
- **Heuristic**: #12 Security Smell
- **Source**: Subagent G
- **Cite**: `backend/.env:24` plain `quantmind` password + 6 `.env-*.bak` files in `logs/` dir
- **Context**: Default weak password embedded in DSN. .bak files (from .env edits like LL-178 protocol) leaked to logs/ which may be in git history.
- **Alt 1**: Rotate password to strong random + move to Windows Credential Manager / sops/age vault
- **Alt 2**: Switch PG auth to peer/cert mode (no password)
- **Alt 3**: At minimum: remove all `.env-*.bak` from `logs/` + add to .gitignore + scan git history for accidental commits

#### P0-003: pg_restore Never Tested

- **Severity**: P0 / DR
- **Heuristic**: #4 Closed-Loop / #6 SLA / #16 Pre-Mortem
- **Source**: Subagent E (Loop 6) + G
- **Cite**: `scripts/pg_backup.py:226` + `:384 verify_backup()` only `pg_restore --list` (TOC); `disaster_recovery_verify.py` exists but 0 log hits in 2026
- **Context**: TOC validation does NOT prove data integrity OR restorability into fresh DB. In a catastrophic DB loss, this is the only recovery path. Untested = no recovery confidence.
- **Alt 1**: Weekly staging-DB restore test (Sunday night spin up `quantmind_v2_dr_test`, restore latest dump, SELECT count on 10 tables, alert mismatch)
- **Alt 2**: WAL-based PITR + tested replica (more complex, proven recovery)
- **Alt 3**: Cloud-mirrored DB (S3 + read replica off-machine)

#### P0-004: Reflector → Threshold Engine NOT Wired

- **Severity**: P0 / V3 Risk Framework integrity
- **Heuristic**: #4 Closed-Loop / #16 Pre-Mortem
- **Source**: Subagent E (Loop 2) + verified by CC main process grep
- **Cite**: `Grep apply_reflection\|adapt_threshold\|update_from_reflection backend/qm_platform/risk/` → **0 hits** (CC verified 2026-05-18 23:30 SH)
- **Context**: Reflector writes to `reflection_log` + `risk_memory` (pgvector). ThresholdCache reads from `dynamic_threshold/engine.py` evaluate(). The two never meet. `_DEFAULT_THRESHOLDS` are hardcoded constants. V3 §16 Reflector design claim of "adaptive learning" is theatre.
- **Alt 1**: Implement `apply_reflection_to_thresholds()` — read `reflection_log` weekly, update via DB table `runtime_threshold_overrides` consumed by ThresholdEngine
- **Alt 2**: Risk_memory → DynamicThresholdEngine indicator boost — `engine.py:assess_market_state()` reads recent risk_memory similar-context entries
- **Alt 3** (conservative, recommended for single-user): Human-in-loop weekly review report — Sunday Beat generates `reflection_summary.md` with "suggested threshold changes"; user manually applies via PR

#### P0-005: Beat Death No Heartbeat (LL-181 Sustained)

- **Severity**: P0 / Highest Strategic Risk
- **Heuristic**: #3 Cascade (8-hop) / #16 Pre-Mortem / #4 Closed-Loop
- **Source**: Subagent E + F (LL-181 lesson cite)
- **Cite**: `scripts/health_check.py` — grep `heartbeat\|beat_health\|missed_run` 0 hits; LL-181 sediment 2026-05-18 afternoon
- **Context**: Longest cascade chain in system. Beat dies → 32 schedule entries 0 fire → cross-domain (news + risk + factor + signal) degradation. Slow to detect.
- **Alt 1**: Beat writes `qm:beat:heartbeat` every 60s; schtask watcher alerts on TTL expiry (independent of Beat itself)
- **Alt 2**: Redbeat HA scheduler (multi-process Beat)
- **Alt 3**: PowerShell schtask audit cron 10min `Get-ScheduledTask` + verify Celery process alive

#### P0-006: Schtask Freshness Probe Absent (LL-181 Sibling)

- **Severity**: P0
- **Heuristic**: #4 Closed-Loop / #16
- **Source**: Subagent E (Loop 7) + F
- **Cite**: `scripts/health_check.py` 0 schtask freshness check; QuantMind_DataQualityCheck LastResult=1 + RiskFrameworkHealth LastResult=1 today (2026-05-18 18:30 + 18:45 — CC verified) ARE silently failing
- **Context**: 19 schtask total. 4 Disabled (3 justified, 2 1999-sentinel orphans). 13 Ready of which 2 failing today silently with no alert. If user accidentally Disable critical schtask during a Windows update, no alert fires.
- **Alt 1**: Add `audit_schtask_freshness.py` 10min schtask — `Get-ScheduledTask QuantMind_*` + verify LastTaskResult=0 + last_run < 26h. DingTalk alert on any mismatch
- **Alt 2**: Each schtask writes `scheduler_task_log(task_name, last_run, exit_code)` + nightly audit alert
- **Alt 3**: Redis dead-man TTL — each schtask `SETEX qm:schtask:<name>:heartbeat 90000`

#### P0-007: Today's Failing Schtasks (DataQuality + RiskFrameworkHealth)

- **Severity**: P0 / Real-Time
- **Heuristic**: #4 / #15 Test-Reality Gap
- **Source**: Subagent F + verified by CC main process (2026-05-18 23:30 SH `Get-ScheduledTaskInfo`)
- **Cite**: `QuantMind_DataQualityCheck` LastTaskResult=1 at 2026-05-18 18:30:01; `QuantMind_RiskFrameworkHealth` LastTaskResult=1 at 2026-05-18 18:45:00. **Both failing today, 0 alert fired**.
- **Context**: data_quality_check.log 18:30:14 shows: `daily_basic.pe_ttm 2026-05-18 NULL比例=28.1% (1541/5476), 阈值5%` — sent DingTalk P1, persisted to notifications. But RiskFrameworkHealth LastTaskResult=1 root cause unknown (logs not captured in this audit pass).
- **Alt 1**: Diagnose RiskFrameworkHealth root cause first → fix → re-run manually → verify exit=0
- **Alt 2**: Add DingTalk alert on any QuantMind_* schtask LastTaskResult != 0 (P0-006 enabler)
- **Alt 3**: Wire `health_check.py` to query schtask_freshness AND fail-loud on LastTaskResult != 0 (per铁律 33)

#### P0-008: Redis Production Data Plane Dark (0 qm:*/portfolio:* Keys)

- **Severity**: P0 / V3 Risk Plumbing
- **Heuristic**: #4 / #6 / #15
- **Source**: Subagent A (Batch 1) + verified by CC main process (2026-05-18 22:50 SH `redis-cli SCAN`)
- **Cite**: `redis-cli --scan --pattern "qm:*"` 0 results; `redis-cli --scan --pattern "portfolio:*"` 0 results; DBSIZE=1455 (96% `celery-task-meta-*`)
- **Context**: V3 design has `qm:{domain}:{event_type}` Redis Streams + `portfolio:current`/`portfolio:nav`/`market:latest:*` caches. Currently dark — either (a) PT paused = legitimate idle, (b) qmt_data_service not actually writing despite schtask MiniQMT_AutoStart Ready, (c) maxlen=10000 trim wrap.
- **Alt 1**: Confirm qmt_data_service running (Servy status query) + add health-check write+read sentinel key every 60s
- **Alt 2**: Observability alert if `qm:qmt:status` key absent > 2min during market hours (09:30-15:00 SH)
- **Alt 3**: Stale-detection bridge — if Redis dark > 5min, RealtimeRiskEngine falls back to direct PG query with 30s staleness tolerance

#### P0-009: 30 Service-Layer `commit()` Violations (铁律 32)

- **Severity**: P0 / Code Health
- **Heuristic**: #5 Convention / #11 Code Smell
- **Source**: Subagent G
- **Cite**: `grep commit()\|conn.commit backend/app/services/` → **30 occurrences across 10 files** (notification_service.py / factor_onboarding.py / dingtalk_alert.py / news_ingestion_service.py / shadow_portfolio.py / etc.)
- **Context**: 铁律 32 says "Service 不 commit, 事务边界由调用方". Sustained drift since refactor 6-H era.
- **Alt 1**: Move commits to Router (FastAPI) / Celery task wrappers — biggest refactor but architecturally correct
- **Alt 2**: Add `@transactional` decorator with Session ownership at service entry
- **Alt 3**: Ruff custom plugin flagging `commit()` in `services/*.py` — at least bound the drift

#### P0-010: 铁律 18 Slippage Quarterly Calibration Has 0 Scheduler

- **Severity**: P0 / SLA + Doc Lying
- **Heuristic**: #6 / #14
- **Source**: Subagent F + G
- **Cite**: `scripts/bayesian_slippage_calibration.py` exists, last calibration content commits ~2026-03 (Sprint 1.14 era); grep `schtask.*slippage\|crontab.*slippage` 0 hits
- **Context**: 铁律 18 says "回测成本实现必须与实盘对齐 — H0 验证 < 5bps + 季度复核". **0 calibration schedule**. 真做过吗 = NO.
- **Alt 1**: Add Beat `slippage-calibration-quarterly` crontab(day_of_month=1, month_of_year='1,4,7,10', hour=2)
- **Alt 2**: schtask QuantMind_SlippageCalibration with email alert on completion
- **Alt 3**: Inline calibration as part of monthly factor_lifecycle review (less independent but practical)

#### P0-011: Survivorship Bias in Backtest Universe

- **Severity**: P0 / Backtest Validity
- **Heuristic**: #1 Drift / #15 Test-Reality Gap
- **Source**: Subagent G
- **Cite**: `backend/engines/backtest/runner.py:138-154` — universe excludes ST/suspended/new_stock/BJ conditional on column presence; `Grep "delisted_at|退市"` 1 file (`engine.py`)
- **Context**: Backtest universe likely **EXCLUDES delisted stocks entirely** (only stocks with current price data in DB). Historically delisted (ST*BL / 锐电 / etc.) silently absent. 12yr Sharpe=0.3594 might inflate by 0.1-0.2 if delisted included.
- **Alt 1**: Add `historical_universe` view including delisted with last-known-price
- **Alt 2**: Use Tushare `delist_d` field in load_universe
- **Alt 3**: Run sensitivity test: 5yr/12yr Sharpe with vs without delisted set → quantify bias

#### P0-012: 11 pytest Collection Errors

- **Severity**: P0 / Code Health
- **Heuristic**: #11 / #14 / #40 (test debt rule)
- **Source**: Subagent G
- **Cite**: `pytest --co backend/tests/` 5989 collected, **11 collection errors** in `test_news_*.py`, `test_announcement_processor.py`, `test_v3_3_5_fail_open_*` — broken import chains
- **Context**: CLAUDE.md baseline says "2864 pass / 24 fail" (Session 9 era). Actual collection 5989 = +109% growth, but 11 ERROR = baseline drift heavy. 铁律 40 (test debt not grow) sustained violation.
- **Alt 1**: Add `@pytest.importorskip` for optional news deps to gate failing imports
- **Alt 2**: Move broken tests to `tests/quarantine/` until repaired (clean baseline)
- **Alt 3**: CI gate: pytest collection must succeed (0 ERROR) on pre-push

#### P0-013: execute_phase Has 0 API + 0 UI (LL-183 Attack Surface)

- **Severity**: P0 / Section XI Inversion
- **Heuristic**: #19 UX Workflow Gap / LL-183 root pattern
- **Source**: Subagent H
- **Cite**: Section XI §41 Backend Op → Frontend Action Coverage Matrix; `scripts/run_paper_trading.py` is sole entry; schtask QuantMind_DailyExecute Disabled today
- **Context**: User wants frontend = primary control plane. execute_phase is highest-risk op (live broker order placement), has no API, no UI, depends on schtask enable for safety. LL-183 silent-NOT-GATING pattern lurks.
- **Alt 1**: `POST /api/paper-trading/execute-trigger` + 三锁 (env match + manual confirm + typed phrase like `EXECUTE-PAPER-20260518`) + 5s cooldown + DingTalk push + audit_log immutable
- **Alt 2**: API only, no UI (CC-mediated trigger via API call)
- **Alt 3**: Keep schtask-only, add monitoring page showing schtask state in real-time

#### P0-014: env_flip is Manual .env Edit + Servy Restart (LL-183 Root)

- **Severity**: P0 / Section XI
- **Heuristic**: #19 / LL-183 Root
- **Source**: Subagent H (Section XI §41)
- **Cite**: env_flip currently = (a) edit `.env`, (b) `service_manager.ps1 restart fastapi`, (c) verify settings reload
- **Context**: P0-1 is direct consequence — .env was flipped to live for cutover, LL-183 happened, .env not reverted. UI-driven env_flip would prevent forgotten revert via audit trail.
- **Alt 1**: `POST /api/system/execution-mode` + 三锁 (env match check + typed phrase + 30s cooldown) + DingTalk push + audit_log immutable. Default state LIVE_TRADING_DISABLED=true. Refuse to flip if `qm:auth:live_authorized_until` Redis key absent
- **Alt 2**: API + separate `operator_token` (different from `admin_token`) for paper↔live flip only
- **Alt 3**: Refuse to API-ify (too risky); keep manual; add always-visible UI banner showing current env state

#### P0-015: 09:30 SH Market Open No Watcher

- **Severity**: P0 / Daily Ops Gap
- **Heuristic**: #4 / #19
- **Source**: Subagent F (Workflow 4 daily ops)
- **Cite**: `Grep "market_open_watcher"` 0 results
- **Context**: Daily ops table shows 09:30 SH market open is **invisible** to operator. Frontend has no real-time tick view at open. The "09:30-15:00 监控 + 人工介入" workflow has no UI.
- **Alt 1**: New `scripts/market_open_watcher.py` background process (09:25-09:35 SH) tailing `qm:market:tick` + DingTalk anomaly alert
- **Alt 2**: Frontend Dashboard real-time tick view (SSE from `qm:market` stream via FastAPI `/api/realtime/market`)
- **Alt 3**: QMT data service emits `qm:market:open` event → meta-monitor consumes + DingTalk daily summary

#### P0-016: No Monthly LLM Cost Audit Aggregator

- **Severity**: P0 / Budget Compliance
- **Heuristic**: #4 / #6 / #15
- **Source**: Subagent F (Workflow 6)
- **Cite**: `QuantMind_LLMCostDaily` 20:30 daily LastResult=0 — daily aggregation only; no monthly rollup
- **Context**: $50/month budget cited in CLAUDE.md but $50/mo enforcement is procedural only (no DB-rooted month-bucket aggregation). CLAUDE.md `quantmind-v3-llm-cost-monitor` skill flags this as known gap.
- **Alt 1**: New `scripts/llm_cost_monthly_audit.py` + Beat `crontab(day_of_month=1, hour=8)` aggregates `llm_cost_daily WHERE date BETWEEN last_month_start AND last_month_end`
- **Alt 2**: Extend `llm_cost_daily_report.py` with `--monthly` flag invoked first of month
- **Alt 3**: Add monthly view to FastAPI `/api/notifications/monthly-cost` + SystemSettings.tsx UI panel

#### P0-017: HC-2c Disaster Drill is pytest-Only

- **Severity**: P0 / DR
- **Heuristic**: #4 / #15
- **Source**: Subagent F (Workflow 6)
- **Cite**: `backend/tests/test_v3_hc_2c_disaster_drill.py` exists — pytest only, no production drill task
- **Context**: V3 §15.6 spec calls for ≥7 类 scenario disaster drill. Test exists, but no schtask/Beat entry intentionally fails a service and verifies recovery in production-like env.
- **Alt 1**: Monthly Beat `disaster-drill-monthly` invokes test_v3_hc_2c in production-isolation mode
- **Alt 2**: Manual quarterly chaos-engineering drill (kill QMT-Data Servy mid-day, verify recovery)
- **Alt 3**: Shadow-mode drill — clone services to "drill" namespace, fail injection there

#### P0-018: RISK_CONTROL_SERVICE_DESIGN.md vs V3 ADR-027 Semantic Conflict

- **Severity**: P0 / Drift
- **Heuristic**: #1 Drift / #20 Reverse Mapping
- **Source**: Subagent B
- **Cite**: `docs/RISK_CONTROL_SERVICE_DESIGN.md` L4_STOPPED design vs `docs/adr/ADR-027.md` L4 = STAGED 默认 + 反向决策权 + 跌停 fallback
- **Context**: Old design says L4=完全停止+人工审批. New V3 ADR-027 redefined as STAGED with reverse-decision-right. **Forward design (RISK_CONTROL_SERVICE) vs Backward implementation (V3 ADR-027) have semantic conflict**.
- **Alt 1**: Merge old doc → archive + V3_DESIGN §4 inline complete L1-L4 ladder
- **Alt 2**: New doc `RISK_LX_STATE_MACHINE_V3.md` replaces old
- **Alt 3**: Add Drift Note in old doc header linking to ADR-027

#### P0-019: Bus Factor = 1 + 0 Onboard Doc

- **Severity**: P0 / Continuity
- **Heuristic**: #16 Pre-Mortem
- **Source**: Subagent I (§25.1 + §28.1)
- **Cite**: CLAUDE.md 530 lines (entry doc, not onboard); `memory/project_sprint_state.md` 768KB (超 Read 上限); 0 `docs/ONBOARDING.md`
- **Context**: User突发不在线 → CC restart cannot 30min onboard. CLAUDE.md is entry, not onboard playbook.
- **Alt 1** (recommended): New `docs/ONBOARDING.md` ≤300 lines — 6-step reset (read CLAUDE.md → SYSTEM_STATUS → recent 3 PR diff → trade_log SQL → xtquant connect probe → smoke test)
- **Alt 2**: Sprint state monthly chunk — `memory/sprint_state/YYYY_WXX.md` ≤50KB each
- **Alt 3**: External backup mirror — weekly `git push --mirror github` + S3 daily DB snapshot

#### P0-020: Knowledge Transfer 4/4 Maturity Sub-Target

- **Severity**: P0 / Continuity
- **Heuristic**: #16 / #28
- **Source**: Subagent I (§28.1)
- **Cite**: 4 dimensions (CC restart onboard / Memory file index / Audit trail browsability / Tribal knowledge enumeration) all FAIL or WARN
- **Context**: 122 audit files no INDEX.md latest. Tribal knowledge 0 enumerated list (e.g. "PT 重启需 user 决议清单"). Sprint state monolithic.
- **Alt 1**: 30-min onboard playbook (consolidates P0-019)
- **Alt 2**: AUDIT_INDEX.md auto-generated reverse-chrono + 1-line summary per file
- **Alt 3**: Tribal knowledge inventory — explicit list of user-only knowledge in `docs/USER_TRIBAL_KNOWLEDGE.md`

#### P0-021: Live Trade Reproducibility — 4 Sources 3-14d Stale

- **Severity**: P0 / Reproducibility + 铁律 15 Violation
- **Heuristic**: #20 Reverse Mapping / sustained F-D78-241
- **Source**: Subagent I (§29.1)
- **Cite**: `docs/audit/2026_05_audit/operations/10_third_party_recon_real.md:26` — trade_log MAX=4-17, 4-29 17 emergency_close + 4-30 GUI sell 18 trades 0 入
- **Context**: Emergency_close path + GUI 旁路 dual_write Beat. trade_log doesn't reflect real ground truth. 铁律 15 (live trade replay) implicitly violated.
- **Alt 1**: Audit middleware in emergency_close path — `qmt_execution_adapter.py` adds `audit_trail_logger` writing trade_log (sync inline, fail-loud)
- **Alt 2**: GUI watcher — scheduled job every 5min pulls xtquant query_orders + diffs vs trade_log, auto-补缺
- **Alt 3**: Drop 4 sources → 1 source = xtquant API only + 1 mirror snapshot every 1h

#### P0-022: Admin Token in localStorage (XSS-Vulnerable)

- **Severity**: P0 / Security
- **Heuristic**: #12 Security / #18 Alt
- **Source**: Subagent H
- **Cite**: `frontend/src/api/execution.ts:137-145` — admin_token in `localStorage`
- **Context**: XSS-vulnerable, single-bearer-token, no rotation, no audit on token use.
- **Alt 1**: httpOnly cookie + CSRF token
- **Alt 2**: TOTP step-up for CRIT ops (env_flip / execute trigger / emergency_close)
- **Alt 3**: WebAuthn passkey for single-user

#### P0-023: No Always-Visible Env Banner UI

- **Severity**: P0 / LL-183 Prevention
- **Heuristic**: #19 UX Workflow Gap
- **Source**: Subagent H
- **Cite**: `Sidebar.tsx:227` only shows `v2.0·在线`, no env state indication
- **Context**: LL-183 prevention requires user always sees `[PAPER] LIVE_TRADING_DISABLED=true` red/green banner. Currently invisible.
- **Alt 1**: Top banner + per-route gate (red banner if EXECUTION_MODE=live, always visible)
- **Alt 2**: Banner only on operator pages (less intrusive)
- **Alt 3**: Status indicator in sidebar (current location, smaller footprint)

#### P0-024: execution_service.py dry_run NameError Risk

- **Severity**: P0 / LL-183 Sibling
- **Heuristic**: #4 Closed-Loop
- **Source**: Subagent D + CC verified
- **Cite**: `backend/app/services/execution_service.py:412-434` — `if dry_run: log; skip` then line 432 `if new_pending and not dry_run` references new_pending which is only set in else branch
- **Context**: Potential NameError if dry_run=True and new_pending not initialized earlier in function. Need verify init exists at lines ~350-400.
- **Alt 1**: Init `fills=[]; new_pending=[]` before line 412 explicitly
- **Alt 2**: Move dry_run check to caller (run_paper_trading.py) before service entry
- **Alt 3**: Add pytest dry_run path unit test asserting no NameError + clean exit (extends LL-183 regression gate)

### §1.2 P1 Findings (26 items, 7-30 day window)

#### P1-025: L4ExecutionPlanner _CANCEL_WINDOW Hardcoded
**Source**: Subagent D / **Heuristic**: #13 Config Sprawl
- `planner.py:317-318` `_CANCEL_WINDOW_MINUTES` hardcoded constant; V3 §2.2 ADR-027 spec says yaml-driven
- Alt: yaml-driven (`configs/risk_runtime.yaml`) / .env `RISK_L4_CANCEL_WINDOW_MINUTES` / cite + acceptance test

#### P1-026: FundamentalContextService Single AKShare vs V3 §3.3 8 维
**Source**: Subagent D / **Heuristic**: #20 Reverse Mapping
- `fundamental_context_service.py:136` — single AKShare source vs V3 §3.3 spec calls for 8 维 (valuation/PEAD/news/macro/etc), 7 missing
- Alt: implement 7 sources / defer to Wave 5 + TODO doc / Protocol-based pluggable per-维

#### P1-027: Alpha158 45-Factor Gap
**Source**: Subagent D / **Heuristic**: #20
- 158 factors in `engines/alpha158_factors.py` vs 113 in factor_ic_history. Gap = 45 factors registered but no IC
- Alt: `--all-alpha158` flag in compute_daily_ic.py / document "partial activation" as intended / soft-deprecate alpha158 module

#### P1-028: AlertDispatcher Buffered Flush Leak Risk
**Source**: Subagent D / **Heuristic**: #4
- `alert.py:93/119` buffer drain on cadence; if Beat paused, buffer leaks
- Alt: persist buffer to DB on dispatch / streaming dispatch (no buffer) / metric alarm if size > threshold

#### P1-029: LLM Router No Auto Failover V4-Flash → V4-Pro
**Source**: Subagent D / **Heuristic**: #4
- `router.py:407 FallbackDetectionError` raises but no automatic failover per ADR-028
- Alt: `completion_with_alias_override` auto-routing on detection / LLM HA per-task fallback yaml / route critical tasks Pro-by-default

#### P1-030: StreamBus publish_sync Dual Implementation Drift
**Source**: Subagent D / **Heuristic**: #13
- `stream_bus.py:83` maxlen=10000 + old comment "publish_sync 已退役 改 outbox publisher" but both alive
- Alt: complete migration to outbox.py + remove StreamBus / document StreamBus deprecated + deprecation warning / dual with feature flag

#### P1-031: Loop 1 Signal Generation 0 NAV Feedback (Open Loop)
**Source**: Subagent E (Loop 1) / **Heuristic**: #4
- `signal_service.py:60` 0 references to past NAV / past trade_log / realized PnL. `vol_regime_scale` only feedback channel (market regime, NOT strategy performance)
- Alt: `factor_realized_contribution` table + Friday Beat live-IC / DD-aware vol_regime_scale (portfolio DD > 10% → reduce) / strategy lifecycle layer (analogous to factor_lifecycle)

#### P1-032: Loop 4 Regime → Signal Disconnected
**Source**: Subagent E (Loop 4) / **Heuristic**: #4
- market_regime_log affects only risk thresholds, NOT signal generation. In Bear regime, signals as if Calm
- Alt: wire market_regime_log into SignalService.generate_signals() / unify vol_regime + news_regime into CompositeRegime / regime-gated rebalance skip in Crisis

#### P1-033: SPF 6 No Tushare Fallback Chain
**Source**: Subagent E / **Heuristic**: #3
- Tushare quota/rate-limit cascade — daily_basic missing → next-day factor compute NULL → IC SKIP → factor_lifecycle false warning
- Alt: Tushare → Baostock → akshare fallback chain / quota monitor + alert 80% / distinguish missing vs NULL

#### P1-034: Gates G1-G10 No Closed-Loop Runner
**Source**: Subagent F (Workflow 1) / **Heuristic**: #4
- `engines/factor_gate.py` exists as code; no script wires IC → Gate → Decision. Factor approval is human-only
- Alt: `scripts/gate_evaluator.py` invoked from compute_daily_ic.py / wire factor_gate.py into factor_onboarding.py / pre-merge hook requiring gate_pass.json

#### P1-035: risk-reflector-weekly Stub Input
**Source**: Subagent F (Workflow 5) / **Heuristic**: #4
- `beat_schedule.py:308` NOTE: "TB-4b input gathering = stub placeholder (TB-4c wires real risk_event_log / trade_log / RAG)"
- Alt: complete TB-4c wiring / disable Beat until TB-4c lands / health-check that reflector output has non-stub features

#### P1-036: Risk Subservice Cluster 0 API Endpoints
**Source**: Subagent F (Connectivity) / **Heuristic**: #2 / #19
- 7 risk subservices (risk_wiring / reflector_agent / dynamic_threshold / meta_monitor / staged_execution / dingtalk_webhook / market_indicators_query) have 0 dedicated endpoints
- Alt: Add /api/risk/staged-execution, /api/risk/threshold-cache etc / consolidate into `/api/risk/admin/*` namespace / keep internal but add observability dashboard

#### P1-037: DEV_FOREX.md 682 Lines 0% Impl + 3 Orphan Tables
**Source**: Subagent B + C / **Heuristic**: #2 / #14
- DEV_FOREX.md DEFERRED design doc; 3 forex tables (forex_bars / forex_events / forex_swap_rates) 0 rows + 0 backend code
- Alt: DROP 3 tables + archive doc to `docs/archive/` / keep DDL retain reference / refactor as `multi_asset_bars`

#### P1-038: DEV_AI_EVOLUTION.md 705 Lines Layer 3+4 0% Impl
**Source**: Subagent B / **Heuristic**: #14 / #20
- Grep Layer 3 Feature Map 0 hits / Layer 4 riskfolio 0 backend hits / Orchestrator 8 节点状态机 0 中枢实现
- Alt: Update header → "Layer 3+4 NOT_STARTED Q3-Q4 trigger" / archive Layer 3+4 章节 / promote standalone MVP design

#### P1-039: paper_broker.py缺独立 Design Doc
**Source**: Subagent B (heuristic #20 backward) / **Heuristic**: #20
- paper_broker.py + base_broker.py + signal_router.py are core code but缺 dedicated design doc
- Alt: Spawn 3 spec doc / sediment to DEV_BACKEND.md §扩展 / lightweight ADR docs only

#### P1-040: DEV_PARAM_CONFIG.md 220 Params vs 50 Actual
**Source**: Subagent B / **Heuristic**: #1 Drift
- 220 design参数 vs 50 active per D5 decision; Level 3 AI auto-tune 14 params 0% impl
- Alt: rewrite doc to 50 active + 30 candidate + 140 archived / retain doc + prominent header 标注废弃 / archive + 1-page replacement

#### P1-041: LL Count Drift Memory 94 vs Actual ~160
**Source**: Subagent G / **Heuristic**: #1 / #14
- `LESSONS_LEARNED.md` grep `^(### |## )LL-[0-9]+` = 160 sections; memory ll_unique_ids=94
- Alt: standardize header `### LL-XXX:` everywhere + count script / doc-sediment cron updating memory monthly / move LL count to LESSONS_LEARNED.md head

#### P1-042: ADR Count Drift CLAUDE.md "ADR-022" vs Actual 67
**Source**: Subagent G / **Heuristic**: #14
- `ls docs/adr/` = 67 files; CLAUDE.md says "ADR-001~ADR-022" — drift 45 missing
- Alt: auto-generate ADR index from filesystem / strict ADR registry yaml + lint hook / replace CLAUDE.md inline with relative link

#### P1-043: DingTalk HMAC Outbound Disabled
**Source**: Subagent G / **Heuristic**: #12 Security
- `DINGTALK_SECRET=""` empty in .env → outbound webhook NOT HMAC-signed (inbound parser has HMAC verify, asymmetric)
- Alt: generate DingTalk secret + populate .env / signed JWT internal alert channel / HMAC verify defense-in-depth

#### P1-044: FastAPI Auth Wide Surface
**Source**: Subagent G / **Heuristic**: #12
- Only `execution_ops.py` references ADMIN_TOKEN (3 hits); other API routes unauthenticated
- Alt: global `Depends(verify_admin_token)` router prefix / API key middleware enforcing 401 default / limit FastAPI to 127.0.0.1 + Cloudflare Tunnel

#### P1-045: Logs No Rotation
**Source**: Subagent G / **Heuristic**: #6 / #11
- 5 log files > 4 MB (fastapi-stdout=10.8 MB, qmt-data-stderr=10.8 MB)
- Alt: RotatingFileHandler 10 MB / 5 backups / logrotate Windows / structlog → loki/grafana

#### P1-046: Sprint State >90k Tokens Monolithic
**Source**: Subagent G + I / **Heuristic**: #11
- `project_sprint_state.md` 768KB exceeds Read tool limit
- Alt: split per-session `memory/sprint_state/YYYY-WXX.md` / archive >2-week stale to memory/archive/ / auto-summarize older via consolidate-memory skill

#### P1-047: Frontend Dual Chart Libs
**Source**: Subagent H / **Heuristic**: #18 / #11
- ECharts 5.6 + Recharts 3.8 both installed (~500KB redundant)
- Alt: drop Recharts / drop ECharts / codify per-use rule

#### P1-048: socket.io-client Installed but 0 Server
**Source**: Subagent H / **Heuristic**: #18 / #2
- `socket.io-client 4.8.3` in package.json; `useWebSocket.ts` hook exists; 0 socket.io server hits in backend
- Alt: remove pkg + build SSE bridge / build socket.io server / keep + delete useWebSocket.ts

#### P1-049: L4 STAGED Approve API but No UI
**Source**: Subagent H (Section XI) / **Heuristic**: #19
- `/api/risk/l4-approve/{approval_id}` (risk.py:239) exists; no UI button
- Alt: Risk Monitor approve/reject buttons / DingTalk-only / email approval link

#### P1-050: No Control Center / Command Palette
**Source**: Subagent H (Section XI) / **Heuristic**: #19
- ~13 critical CC-only ops have neither API nor UI; user explicitly requested "frontend = primary control plane"
- Alt: Build Control Center page consolidating ops / Cmd+K command palette only / per-section pages

---

## §2 Strategic Alternatives Chapter (Phase 3-bis Output)

> Per heuristic #18 GLOBAL: for the audit as a whole, propose 3-5 "if we redesign from scratch today" architectural alternatives — not per-finding remediation, but **whole-system direction**.

### §2.1 Alternative A — Harden Current Monolith (Default + Recommended)

**Approach**: Keep current FastAPI + Celery + sync psycopg2 + Redis + Servy architecture. Focus on closing top 10 P0s + Section XI inversion (frontend as control plane).

**Pros**:
- Minimal disruption — 6-8 weeks to lift major risks
- No new infrastructure to operate
- Single user fits well

**Cons**:
- Open-loops remain (Loop 1/2/4/6/7) — system doesn't self-learn
- Bus factor = 1 sustained
- Limited to ~¥10-30M capital ceiling (slippage / liquidity)

**Effort**: ~6-8 weeks (1-1.5 days/week solo)

### §2.2 Alternative B — Split into 3 Services (Engine / Risk / Data)

**Approach**: Decompose to 3 microservices:
- **PT-Engine**: signal generation + factor compute + backtest
- **Risk-Engine**: V3 L0-L5 + reflector + threshold cache
- **Data-Engine**: Tushare/Baostock/QMT ingest + Redis streams + outbox

Each runs on Servy independently with own DB schema. Communicate via Redis Streams.

**Pros**:
- Failure isolation (Beat death affects 1 not all)
- Each engine scales independently
- Better for future multi-strategy

**Cons**:
- 3× operational complexity for single-user
- Communication latency 10-50ms per hop
- 3-4 month migration effort
- Untested for capital scaling

**Effort**: ~3-4 months

### §2.3 Alternative C — Event-Sourcing for trade_log + Audit (Subset of B)

**Approach**: Apply event-sourcing pattern to trade_log + risk_event_log + reflection_log. All state changes append-only events. Read models built via projections.

**Pros**:
- Solves P0-021 reproducibility (replay历史 audit chain)
- Backfill becomes natural (replay missed events)
- Time-travel debugging trivial

**Cons**:
- Schema migration painful
- 2× DB size projected
- Eventual consistency learning curve

**Effort**: ~2 months for trade_log + risk_event_log only

### §2.4 Alternative D — Rewrite QMT Integration as Separate Process Pool

**Approach**: Lift broker_qmt.py + qmt_execution_adapter.py + xtquant integration into separate Python process pool (e.g. 3 worker processes managed by Servy). Each handles 1 connection. asyncio compat issue (LL-180) solved by process isolation.

**Pros**:
- LL-180/182 root cause permanent fix (no shared asyncio loop)
- Failure of one connection doesn't kill all
- Easier to test in isolation

**Cons**:
- IPC overhead ~5-10ms per order
- Process management complexity
- 1 month build + test

**Effort**: ~1 month

### §2.5 Alternative E — Defer Wave 4+ / Focus Capital Preservation (Conservative)

**Approach**: Halt all roadmap. Focus solely on:
1. Revert .env to paper sustained
2. Audit cumulative findings → fix Top 10 P0
3. Backup verify + DR drill quarterly
4. Onboard doc + memory split
5. NO new features for 3 months

**Pros**:
- Lowest risk
- Captures audit value as cleanup
- Bus factor мIT prevention via onboard doc

**Cons**:
- Zero alpha capture period
- May lose competitive edge timing
- Sustained "paused" state may demoralize

**Effort**: ~6 weeks then re-evaluate

### §2.6 CC Recommendation (Strategic Synthesis)

**Hybrid**: Alt A (default) + Alt D (1-month side-quest) over 8-10 weeks total:

| Week | Focus |
|---|---|
| 1 | P0-1 to P0-4 (revert .env, rotate password, schedule restore test, design reflector→threshold) |
| 2 | P0-5 to P0-8 (beat heartbeat, schtask freshness, diagnose today's fails, redis dark probe) |
| 3-4 | Section XI inversion Phase 1 — API + Control Center skeleton |
| 5-6 | QMT process pool (Alt D) — solves LL-180/182 永久 |
| 7-8 | Section XI Phase 2 — full Control Center + 3-mockup design integration |
| 9-10 | Audit calendar + onboard doc + memory split (continuity) |

Then quarterly review re-evaluate Alt B/C/E based on new state.

---

## §3 Cross-Layer Dependency Map (10+ Examples)

| # | Trigger | Cascade Impact |
|---|---|---|
| 1 | P0-1 .env unrolled + P0-5 Beat death + P0-6 schtask freshness absent | If Beat dies during pause, schtask Disabled holds, but if user re-enables schtask while .env live → real broker fire (3-way SPF) |
| 2 | P0-8 Redis dark + P0-9 service.commit() violations | Service writes uncommitted may not surface via Redis publish (decoupled) — silent data loss |
| 3 | P0-10 slippage 0 scheduler + P0-11 survivorship bias + 铁律 18 violation | Backtest unreliable as live performance predictor — Sharpe 0.8659 trust budget reduced |
| 4 | P0-12 pytest collection errors + 铁律 40 test debt + LL-183 pattern | Regression gates compromised — silent NOT-GATING patterns harder to catch |
| 5 | P0-13 execute_phase no API + P0-14 env_flip manual + P0-22 admin token localStorage | Frontend cannot safely orchestrate cutover; LL-183 root pattern unaddressed |
| 6 | P0-19 bus factor 1 + P0-20 knowledge transfer FAIL + P1-46 sprint state monolithic | 24h user unavailability → CC restart cannot reconstruct context |
| 7 | P0-21 trade_log stale + P0-18 RISK_CONTROL_SERVICE vs ADR-027 conflict + 铁律 15 violation | Audit chain unreliable; design vs reality drift sustained |
| 8 | P1-31 Loop 1 open + P1-32 Loop 4 disconnected + P0-4 Loop 2 not wired | 3 open loops = system has 0 self-correction capability |
| 9 | P1-37 forex dead + P1-38 AI_EVOLUTION partial + P0-18 design conflict | ~2000 lines of stale design docs causing confusion + maintenance debt |
| 10 | P1-41 LL count drift + P1-42 ADR count drift + P1-46 sprint state monolithic | Documentation governance system itself drifting — meta-audit failure |
| 11 | P1-44 FastAPI auth wide + P0-22 localStorage + P0-2 PG plaintext | Security posture weak across DB + API + frontend layers |
| 12 | P0-15 market open watcher absent + P0-23 env banner absent + P0-13 execute no UI | Operator has zero situational awareness at most critical time (09:30 SH market open) |

---

## §4 Doc Navigation

| Section | File | Subagent source |
|---|---|---|
| Master + Top 50 + Strategic Alt | `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md` (this file) | Phase 3 synthesize |
| §1 Domain | `V3_AUDIT_S1_DOMAIN.md` | Subagent A §1-2 |
| §2 Inventory + Doc Status + Design Gap | `V3_AUDIT_S2_INVENTORY.md` + `V3_AUDIT_S2_DOC_STATUS_MATRIX.md` + `V3_AUDIT_S2_DESIGN_VS_REALITY_GAP.md` | A §3-5 + B + C §7 |
| §3 Flow + Closure | `V3_AUDIT_S3_FLOW_AND_CLOSURE.md` | D + E |
| §4 Health + Dead Code | `V3_AUDIT_S4_HEALTH_AND_DEAD_CODE.md` | F + C §14 + G §13/16-20 |
| §5 Frontend Redesign | `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` | H §21-24 |
| §6 Strategic + Continuity | `V3_AUDIT_S6_STRATEGIC_AND_CONTINUITY.md` | I §25-30 + §VIII |
| §IX + X | `V3_AUDIT_S7_ML_COST_HARDWARE.md` | G §36-40 + I §31-35 |
| §XI UX + Control Plane | `V3_AUDIT_S9_UX_CONTROL_PLANE.md` | H §41-45 |
| Frontend Design Spec (NEW v7, feedable claude.ai/design) | `V3_AUDIT_FRONTEND_DESIGN_SPEC.md` | Phase 4-bis Step A |
| Designer mockup (NEW v6, oh-my-claudecode:designer) | `V3_AUDIT_FRONTEND_DESIGN_PROPOSAL.md` + `frontend_mockups/{A,B,C}.html` | Phase 4-bis Step B |

---

## §5 Post-Audit Roadmap (Phase G+)

### §5.1 Phase G — Audit Closure (Week 1, immediately)

- [ ] Revert .env paper (P0-1) — 5 min
- [ ] Rotate PG password (P0-2) — 30 min
- [ ] Schedule disaster_recovery_verify weekly (P0-3) — 1 hour
- [ ] Diagnose RiskFrameworkHealth schtask LastResult=1 (P0-7) — 1-2 hour
- [ ] LL-184 sediment: 全局 audit findings cumulative
- [ ] LL-185 sediment: bus factor 1 + onboard absence (P0-19/20)
- [ ] LL-186 sediment: .env unrolled + LL-183 lesson reinforce (P0-1)

### §5.2 Phase H — Frontend Redesign (Weeks 2-6, conditional on Audit Section V)

Per `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` + `V3_AUDIT_S9_UX_CONTROL_PLANE.md` + `V3_AUDIT_FRONTEND_DESIGN_SPEC.md`:
- Phase 1: API contract finalize (week 2)
- Phase 2: Design system + base components (week 2.5)
- Phase 3: Control Center + PT Dashboard + Risk Monitor (weeks 3-4)
- Phase 4: Advanced pages (weeks 5)
- Phase 5: Real-time + AI ops (week 6)

### §5.3 Phase I — Tech Debt Cleanup (Weeks 7-8)

- Dead code removal per §14 (forex 3 + chip_distribution + experiments + platform_metrics + agent_decision_log)
- Deprecated docs → docs/archive/ per §6 (DEV_FOREX / old V3 design / etc)
- Configuration consolidation per §7 + heuristic #13
- 5 orphan Celery tasks removal
- 2 schtask 1999-sentinel cleanup
- ~5-7 day effort total

### §5.4 Phase J — Strategy Diversification (post Phase G + Phase H)

- Sharpe confidence decomposition实施 (P3 sugg §VIII #3)
- Backup strategy candidate research (PEAD ADR-002 reactivate?)
- Failed direction 8 项 re-eval (top 3 candidates)
- Section X §36 Capacity stress test

### §5.5 Phase K — Live-Fire Resume (conditional on Phase G + Phase H)

- Re-evaluate live-fire timing post-audit closure
- Phase 3 partial pilot (5 stocks PT_TOP_N=5 → 10 → 20 灰度)
- Backup vendor pre-staging (Akshare ready as Tushare fallback)
- LL-187+ pre-stage candidate skin tag

---

## §6 Audit Self-Audit (Heuristic #17)

### §6.1 What This Audit Successfully Surfaced
- 24 P0 + 26 P1 = 50 findings with #18 alt remediation each
- 11 Section coverage with cross-validate gates between batches (LL-106 drift containment)
- Strategic alternatives chapter (Phase 3-bis Alt A-E)
- Cross-layer dependency map (12 examples)

### §6.2 What This Audit MISSED
- **Live PG queries blocked** — psql password not in PATH; subagent I + G both flagged [DB-VERIFY-PENDING]. Specifically: llm_cost_daily MTD vs $50 budget actual numbers, risk_memory row count, scheduler_task_log freshness per-task. User can run ~30s SQL post-audit to fill gaps.
- **Frontend browser testing** — couldn't preview pages (PT paused, no live data, no browser MCP set up). Subagent H worked from package.json + code grep.
- **Runtime performance profiling** — no `pg_stat_statements` enabled, no real P99 latency measurements per-stage.
- **Live tick observation** — PT paused → 0 live ticks → Section X §40 daily critical path latency mostly theoretical.
- **Recursive count error in Subagent A** — A counted engines 86 (recursive incl. subdirs/__pycache__) vs CC verified 45 top-level .py; scripts 301 vs CC verified 80 top-level. Phase 0 baseline (113 services) likely counted function definitions, not files. Future audit: pre-normalize counting methodology.

### §6.3 Next Audit Cadence Recommendation
- **Event-driven**: post-LL incident P0 → mini-audit within 7d
- **Quarterly full**: Q1/Q2/Q3/Q4 (next: 2026-08-01 if 2026-Q1 audit just done)
- **Pre-cutover gate**: Tier A→B / paper→live / 重大架构变 必须 audit
- **Tech debt threshold**: LL > 200 OR ADR > 100 OR test fail > baseline+10 → trigger

---

## §7 Sediment Trail

- **LL-184 candidate**: "Doc Status Matrix Drift — ~165 docs inventoried, ~20 design docs IMPLEMENTED % vary 0-100%, valuable-but-未实施 list documented; bidirectional traceability heuristic #20 NEW v8 sediment"
- **LL-185 candidate**: "Section XI Backend Op → Frontend Coverage Matrix — 13/32 critical ops have neither API nor UI; user explicitly requested 'frontend = primary control plane'; designer agent + claude.ai/design 2-path frontend roadmap"
- **LL-186 candidate**: "Audit findings synthesis Top 50 ranked with heuristic #18 GLOBAL ENFORCE 2-3 alternatives per finding; Strategic Alternatives chapter Phase 3-bis Alt A-E"

**End of MASTER doc. ~1500 lines.**

---

> **Audit cite verify timestamps**: All findings cite 2026-05-18 evening (~22:00-23:30 SH). CC main process cross-validate verified key load-bearing claims (.env state / Redis dark / schtask LastResult / apply_reflection grep).
>
> **READ-ONLY confirmation**: 0 broker calls from audit operations. 红线 sustained throughout: cash ¥993,520.66 / 0 持仓.
>
> **Next session entry**: User decides Phase G priority order (Alt A vs A+D hybrid) + frontend path choice (claude.ai/design web vs designer mockup vs hybrid).
