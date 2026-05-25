# L4R Audit Week 2 Manifest (2026-05-26, iter 130)

> **Cadence**: Week 1 (2026-05-25 cluster, ~11 audit docs) PASSED — pattern strongly validated. Week 2 extends to next subsystems per §3 ⑥/⑪/⑬ + §3.3 priority.
> **Trigger**: iter 130 phase opener (post Session 5+1 conftest migration close); user `/loop` + "全面+主动" directive.
> **Output**: ≤5 candidate audit subsystems for iter 131-150 多-iter campaign; each surfaces concrete finding catalog → drives subsequent IMPLEMENT/DEFER/ARCHIVE iters → §4.5 ratio rebalance enabler.
> **Source**: L4R_LOOP_SPEC §3 backlog ⑥ (DEV_*.md "未实施") + ⑪ (项目特性 audit) + ⑬ (CC 主动 propose) + §4.2 reality re-grounding.

---

## §1 Week 1 Retrospective (implicit cluster, 2026-05-25)

11 audit docs shipped (per `docs/audit/*_2026_05_25.md` glob); themes:

| Theme | Audit doc(s) | Closure verdict |
|---|---|---|
| V3 doc-vs-prod drift | SCHEDULER_V3_CYCLE_DRIFT (§5 Rec #1+#2+#3 — #2/#3 closed iter 126/127, #1 deferred to V3 §9.1 sequenceDiagram refresh) + DEV_AI_V21_V3_DRIFT | 2/3 closed + 1 deferred-with-cite |
| SSOT consolidation | V3_SSOT_RISK_CONTROL_RETIRE (physical archive 711-LOC → redirect stub) + ADR_094_PMS_RETIRE_CONSISTENCY | Closed |
| Cite source consistency | ADR_014_TERMINOLOGY_CITE (Strategy gate path + Risk V3 G1/G2 token collision) | Closed |
| Pool / lifecycle health | FACTOR_POOL_HEALTH (4 active + dv_ttm warning sustained) + FACTOR_LIFECYCLE_ROOT_CAUSE + FACTOR_LIFECYCLE_BEAT | Closed (root cause = silent dispatch, fix shipped PR #479) |
| Frontend silent UI lie | W14_PIPELINE_CONSOLE_PLAN (EMPTY_STATUS mock anti-pattern) | Closed (PR #480 fail-loud guard + LL-205 canonical sediment) |
| Test infra canonical | MAKE_MOCK_CONN_REFACTOR_BLUEPRINT (conftest fixture migration 12/12 scoped) | Closed (LL-206 canonical sediment) |
| Strategy gate coverage | STRATEGY_GATE_COVERAGE | Closed |

**Net Week 1 finding closure**: ~17 audit findings closed (5 governance / 4 doc / 4 code / 4 test). 2 sustained as Week 2 entry (V3 §9.1 sequenceDiagram refresh + 2 Plan-mode conftest migrations per LL-206 §closure status).

---

## §2 Week 2 Candidate Audits

### W2-A: OBSERVABILITY_MVP41_RUNTIME_VERIFY
**Scope**: Wave 4 MVP 4.1 Observability deliverables (17 unit tests + 5 NEW Beat entries per QPB v1.17 §Wave 4 + SYSTEM_STATUS §0.6). Reality re-grounding per L4R §4.2 — "runtime-true 不只 STATUS_REPORT-true" 直击 LL-179.

**Concrete questions**:
1. Are all 5 NEW Wave 4 Beat entries (`daily-attribution-compute` 16:30 / `daily-backup-run` 02:30 / `weekly-backup-verify` Sun 04:00 / `reports-cleanup-weekly` Sun 04:30 / `meta-monitor-tick` */5min) actually firing daily? Read `scheduler_task_log` rows for ≥5d window post-iter 75 (2026-05-25).
2. Do MVP 4.1 17 unit tests still PASS in current main HEAD `34c70a3`? Targeted `pytest backend/tests/test_*observability* test_*backup* test_*attribution*`.
3. Is `audit_outbox` / `event_outbox` consumer wire actively draining? Check `qm:audit:*` / `qm:event:*` Redis stream XLEN + consumer-side draining cadence.
4. Are 4-domain outbox integration tests (`test_outbox_4domain_integration.py`) still green?
5. meta-monitor-tick — 0 P0 alert sustained post Wave 4 launch? scheduler_task_log evidence.

**Effort**: 1-2 iter (psql query + targeted pytest run + Redis XLEN check + scheduler_task_log SQL).
**Cite**: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` §Wave 4 + `backend/app/tasks/beat_schedule.py:48-490` + `scheduler_task_log` table + `audit_outbox` / `event_outbox` tables.
**Defer/Archive candidates surfaced**:
- Beat entry firing but consumer not draining → DEFER fix + ADR-DRAFT
- 5-day window 0 scheduler_task_log row for any of 5 Beat entries → P0 silent-dispatch repeat anti-pattern (escalate to next iter implement)
- meta-monitor 0 P0 → strong runtime-true signal (cite + sediment LL "Wave 4 launch verified runtime-true")

---

### W2-B: L4_STAGED_EXECUTION_AUDIT
**Scope**: V3 §7 L4 STAGED execution flow code-vs-spec drift. ADR-027 §L4 STAGED + 反向决策权 + 跌停 fallback (Session 50 sediment). Audit implementation completeness post sub-PR campaign.

**Concrete questions**:
1. `backend/qm_platform/risk/l4/staged.py` (or equivalent canonical path) — exists? Implements 14:55 挂限 → execution gate path per V3 §7.3.2?
2. ADR-027 §C 反向决策权 — code-level enforcement point? Where does L4 STAGED defer to reverse-decision veto?
3. 跌停 fallback (ADR-027 §D) — implementation path? Test coverage?
4. `risk-l4-sweep-1min` Celery Beat (`*/1 9-14 * * 1-5`) — actively firing post Wave 4 cutover? scheduler_task_log evidence.
5. `risk-l4-broker-stuck-sweep` 5min Beat (per V3 §14 mode 12 / HC-2b2 G7) — sustained 0 stuck? Or pending stuck rows?
6. STAGED status state machine (READY/ARMED/DISPATCHED/REJECTED/EXPIRED) — DDL exists? Transition logic clean?

**Effort**: 2-3 iter (code-trace + DDL grep + test coverage matrix + scheduler_task_log SQL).
**Cite**: ADR-027 + V3 §7.3 + `backend/qm_platform/risk/l4/*` + `scheduler_task_log` table.
**Defer/Archive candidates surfaced**:
- 跌停 fallback not implemented (defer to next cycle + ADR-DRAFT)
- State machine partial (defer)
- broker-stuck sustained 0 = strong runtime-true signal (cite)

---

### W2-C: OUTBOX_PUBLISHER_DRIFT
**Scope**: V3 §S6 `outbox-publisher-tick` 30s Celery Beat + 4-domain integration (audit / event / trade / risk_event). Check sustained sentinel-vs-tail draining.

**Concrete questions**:
1. `outbox-publisher-tick` 30s Beat firing? scheduler_task_log evidence ≥5d (post Wave 4 close).
2. 4-domain outbox tables — backlog depth per table? Stuck rows >24h (since published_at IS NULL)?
3. Stream consumer side (`audit_log_consumer` / `event_consumer` / `trade_consumer` / `risk_event_consumer`) — actively draining? PID alive?
4. PR #169 emergency_close cascade outbox row — drained? (audit chain Step C3 1/18 long-tail per Session 50 handoff = 17/18 = 94.4%).
5. 30s tick + 4-domain integration test (`test_outbox_4domain_integration.py`) still PASSING in current main HEAD `34c70a3`?
6. `qm:*` Redis stream maxlen=10000 (per CLAUDE.md §Redis Streams 规则) — actually enforced?

**Effort**: 1-2 iter (psql backlog query + Redis XLEN check + pytest targeted + PID check).
**Cite**: V3 §S6 + `backend/app/services/outbox/` + `audit_outbox` / `event_outbox` / `trade_outbox` / `risk_event_outbox` tables + CLAUDE.md §Redis Streams 规则.
**Defer/Archive candidates surfaced**:
- Silent draining stall (defer fix + LL sediment)
- Orphan stream entries >24h (archive)
- Step C3 1/18 long-tail = user portal export gap (defer to Phase J user touchpoint)

---

### W2-D: FACTOR_VALUES_172GB_HYPERTABLE_AUDIT
**Scope**: `factor_values` 841M rows / 172 GB / 152 TimescaleDB chunks (per CLAUDE.md §因子存储 iter 52 fresh verify 2026-05-25). Maintenance pattern: compression policy / retention policy / chunk_time_interval / hot vs cold storage / query plan baseline.

**Concrete questions**:
1. Is compression enabled on `factor_values` hypertable? `timescaledb_information.compression_settings` — segmentby / orderby?
2. Are older chunks (>1 yr) compressed? Compression ratio achieved? Disk savings vs uncompressed estimate?
3. Retention policy — any `drop_chunks` policy? Or sustained full-history (12 yr+) retention?
4. `chunk_time_interval` — current value? Optimal vs ingest cadence (daily IC backfill + daily Baostock pull)?
5. Slowest queries hitting `factor_values` — query plan / index usage / chunk exclusion working? `pg_stat_statements` top 10.
6. iter 52 fresh verify noted 1.67x diff vs stale SYSTEM_STATUS.md 4-07 snapshot — confirms cite that SYSTEM_STATUS stale not CLAUDE.md error. Audit可 sediment 此 cross-doc drift as Week 2 finding.
7. `_load_shared_data` 1000x perf gain (30min → 1.6s, per CLAUDE.md §性能规范) — sustained? Parquet cache invalidation OK?

**Effort**: 2 iter (TimescaleDB metadata SQL + query plan + perf baseline + Parquet cache check).
**Cite**: CLAUDE.md §因子存储 + §性能规范 + `timescaledb_information.*` views + `pg_stat_statements`.
**Defer/Archive candidates surfaced**:
- Compression policy not enabled (defer + ADR-DRAFT)
- Retention drop policy decision (defer to Phase B-2 post-restart, 12yr 数据保留 vs ML 训练复用 trade-off)
- Stale SYSTEM_STATUS.md numeric drift (implement refresh in same iter)

---

### W2-E: DEV_NOTIFICATIONS_IMPL_STATUS
**Scope**: `docs/DEV_NOTIFICATIONS.md` vs PlatformAlertRouter SDK reality. Wave 4 batch 3.x 17/17 SDK migration complete (digest #11 milestone), but DEV_NOTIFICATIONS doc 未必同步.

**Concrete questions**:
1. DEV_NOTIFICATIONS describes which transport channels? (DingTalk / WeCom / Email / WebSocket?) Sustained vs new SDK abstraction?
2. PlatformAlertRouter SDK API surface (`backend/qm_platform/notifications/sdk` 等价 path) — documented in DEV_NOTIFICATIONS or 仅 inline code?
3. 17 migrated scripts (per digest #11) — DEV_NOTIFICATIONS reflects new contract or sustained legacy spec?
4. WebSocket implementation status per `loop_state.md` iter 45 finding "DEV_NOTIFICATIONS WebSocket未实现" — sustained? Or now implemented (frontend api/realtime.ts + useWebSocket)?
5. Alert dedup_key + suppress_minutes contract (per Wave 4 batch 3.x template) — DEV_NOTIFICATIONS has examples?
6. iter 51 reviewer P2 yaml rule declined per precedent — sustained or refresh?

**Effort**: 1 iter (read DEV_NOTIFICATIONS + grep SDK adoption + 17 script verify + frontend WebSocket trace).
**Cite**: `docs/DEV_NOTIFICATIONS.md` + `backend/qm_platform/notifications/` SDK + `scripts/*` 17 migrated.
**Defer/Archive candidates surfaced**:
- Doc-rot refresh (implement same iter, ≤30 LOC edit)
- WebSocket 未实现 sustained (defer to Phase J, cross-ref ADR if needed)

---

### W2-F: FRONTEND_INTEGRATION_AUDIT (added iter 135, user-driven Tier A§2)
**Scope**: 后端 features 在前端的集成 status (user 5-26 显式 ask "后端的功能没有在前端进行集成"). Enumerate V3 风控 / Wave 4 Observability+Attribution / Approval queue + audit log / PT operator core 4 area backend surface → frontend consumer status (LIVE / DARK / PARTIAL).

**Concrete questions**:
1. V3 §S5/§S6/§S7/§S8 风控 framework backend endpoints (risk.py / approval.py / sse.py) — frontend page (RiskManagement.tsx / SafetyControlPanel.tsx) 是否消费? L4 recovery flow 完整?
2. Wave 4 MVP 4.1 Observability + 4.2 Attribution backend (observability/* + eval/attribution.py) — UI dashboard 存在? api endpoint surface 完整?
3. Approval queue (approval.py 6 endpoints) — frontend 有页面消费? V3 §S5/§S6/§S7/§S8 merged main 但 UI surface?
4. PT operator (paper_trading.py / dashboard.py / portfolio.py) — NAV / positions / cash / trade log 全 wire 到 PTGraduation + Dashboard?

**Effort**: 1 iter audit (iter 135 ✅ done) + 10-12 iter wire campaign (F1-F10 catalog → iter 136-147).
**Cite**: `docs/audit/W2_F_FRONTEND_INTEGRATION_AUDIT_2026_05_26.md` (NEW iter 135) + `backend/app/api/risk.py` + `backend/app/api/approval.py` + `frontend/src/pages/*.tsx`.
**Defer/Archive candidates surfaced** (per W2_F §4):
- F1 Approval queue UI (V3 §S5-§S8 closure) — Tier A§2 P0 iter 136
- F2 L4 Recovery completion — Tier A§2 P0 iter 137
- F3 Risk event stream consumer — Tier A§2 P0 iter 138
- F4-F10 — Tier B Wave 5 MVP 5.x candidates iter 139-147

---

## §3 Selection Recommendation (§3.3 priority)

Top order for iter 131+ execution (**iter 135 update**: W2-F user-driven Tier A§2 surfaced, bumps to #1):

| # | Audit | Tier | Effort | Priority Rationale | §4.5 rebalance value |
|---|---|---|---|---|---|
| 1 | **W2-F FRONTEND_INTEGRATION_AUDIT** (iter 135 ✅) → **F1-F10 wire campaign** | A§2 | 1 audit + 10-12 wire iter | **User 5-26 显式 ask** "后端的功能没有在前端进行集成" + v9.6 Tier A§2 prerequisite. iter 135 audit ✅ done — 21/32 (66%) DARK or PARTIAL surfaced. F1+F2+F3 P0 unblocks PT restart gate UX. | Surfaces 10 implement (F1-F10) → strong implement-bias balanced by Tier A§2 mandate. |
| 2 | W2-A OBSERVABILITY_MVP41_RUNTIME_VERIFY (iter 131-134 ✅ closed PR #484) | C | done | §4.2 reality re-grounding closed iter 132+134 PR #484 Wave 4 audit envelope. | Closed |
| 3 | W2-D FACTOR_VALUES_172GB_HYPERTABLE_AUDIT | C | 2 iter | MID-priority backlog sustained. Touches data layer hygiene. Surfaces compression policy ADR-DRAFT candidate (paired DEFER for §4.5 rebalance). | Surfaces ≥1 defer (compression ADR) + 1 implement (SYSTEM_STATUS refresh) |
| 4 | W2-C OUTBOX_PUBLISHER_DRIFT | C | 1-2 iter | Audit Step C3 1/18 long-tail per Session 50 handoff. Touches event-sourcing core. Real-time data check. | Surfaces ≥1 defer (Step C3 user portal) |
| 5 | W2-B L4_STAGED_EXECUTION_AUDIT | C | 2-3 iter | ADR-027 implementation completeness. Higher friction (multi-file code-trace). Defer if Week 2 budget tight. | Surfaces 1-2 defer (跌停 fallback / state machine partial) |
| 6 | W2-E DEV_NOTIFICATIONS_IMPL_STATUS | C | 1 iter | Doc-rot follow-on after Wave 4 batch 3.x 100% milestone. Low-friction. | Surfaces 1 implement (doc refresh) + 1 defer (WebSocket sustained) |

**Recommended Week 2 budget revision** (iter 135 post-W2-F): focus W2-F F1-F10 wire campaign first (Tier A§2 user-driven mandate); W2-D / W2-C / W2-B / W2-E sustained as Week 3 candidates.

**Rebalance projection**: assuming Week 2 surfaces 3-5 defer + 2-3 archive candidates across 3 audits, §4.5 ratio currently ~74%+ trends back toward mid-band 65-70% by Week 2 close.

---

## §4 4-element cite source (sustained §v9.7 mandate)

| # | Path | Line# | Section | Verify timestamp |
|---|---|---|---|---|
| 1 | `D:\quantmind-v2\docs\L4R_LOOP_SPEC.md` | L30 | §3 13 backlog source ⑥/⑪/⑬ | 2026-05-26 iter 130 fresh read |
| 2 | `D:\quantmind-v2\docs\L4R_LOOP_SPEC.md` | L36 | §4.2 reality re-grounding + LL-179 anti-pattern | 2026-05-26 iter 130 fresh read |
| 3 | `D:\quantmind-v2\.omc\state\l4r_loop_state.md` | L22-26 | iter 110+ next candidates (factor_values 172GB ref + W7-W15) | 2026-05-26 iter 130 fresh read |
| 4 | `D:\quantmind-v2\docs\audit\SCHEDULER_V3_CYCLE_DRIFT_2026_05_25.md` | L74-78 | §5 Rec #1 V3 §9.1 sequenceDiagram refresh deferred (Week 2 sediment-ready) | 2026-05-26 iter 130 fresh read |
| 5 | `D:\quantmind-v2\backend\.env` | L17, 20 | EXECUTION_MODE=paper / LIVE_TRADING_DISABLED=true (红线 sustained) | 2026-05-26 iter 130 fresh verify |
| 6 | `D:\quantmind-v2\docs\audit\L4R_DIGEST_LOG.md` | tail (digest #11) | Wave 4 batch 3.x 17/17 milestone + ratio 34:3:9=74.5% | 2026-05-26 iter 130 fresh read |

---

## §5 iter 130 sediment context

- **iter 130 deliverable**: 3 sediment docs (this manifest + digest #12 consolidated cross-compaction + l4r_loop_state.md Current refresh).
- **TIER routing**: All TIER C docs direct push per 铁律 42 docs/** precedent (sustained iter 28/29 / iter 45 / iter 52 / iter 53 / iter 55 / iter 56 / iter 57 / iter 125-128 lineage).
- **Red lines 5/5 sustained verify** (2026-05-26 iter 130 .env fresh read): EXECUTION_MODE=paper (L17) / LIVE_TRADING_DISABLED=true (L20) / PT_TOP_N=5 sustained灰度 (L33) / PT_INDUSTRY_CAP=1.0 (L34) / cash ¥993,520.66 sustained 27 days 0 trading.
- **Phase opening**: user `/loop` + "全面+主动" directive → iter 130 produces manifest → iter 131+ executes W2-A first.
- **Next iter signal**: iter 131 picks W2-A OBSERVABILITY_MVP41_RUNTIME_VERIFY (§3.3 #1, §4.2 reality re-grounding overdue, highest governance value).
