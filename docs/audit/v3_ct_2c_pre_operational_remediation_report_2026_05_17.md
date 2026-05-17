# V3 CT-2c-pre — Operational Health Remediation Report (2026-05-17)

**Status**: ✅ FULLY COMPLETE — `QuantMind_DailyExecute` ENABLED for Mon 2026-05-18 09:31 SH live-fire

**Main HEAD at sediment**: `fc809c0` (post CT-2b apply)
**Sediment branch**: (docs-only sub-PR, sustained CT-1c precedent)

**Plan**: V3 PT Cutover Plan v0.4 §A CT-2c (operational layer remediation surfaced via comprehensive Phase 0 active discovery during CT-2c kickoff)

---

## §0 Overview

CT-2c kickoff Phase 0 active discovery surfaced **8+ P0/P1 operational defects PRE-EXISTING from before CT-2 cycle** but never detected because:
1. Paper-mode (LIVE_TRADING_DISABLED=true sustained 4-29~5-17) masked consequences
2. 0 持仓 since 4-29 emergency_close meant no real trading triggered downstream checks
3. CT-1b operational readiness harness scope verified services/Redis/PG/DingTalk/RSSHub but NOT data freshness / scheduler success rate / schtask state alignment
4. Multiple silent-failure 4-tuples (exec / log / alert / dashboard) cascading

This is the **15-th cumulative实证 of LL-098 X10 "Gate ✅ ≠ 充分条件"** pattern — CT-2a Gate E charter verify 5/5 PASS + CT-2b .env apply ✅ did NOT mean operational pipeline is alive.

Without comprehensive testing tonight (post user 主动思考 directive), Monday 09:31 SH would have surfaced live-fire failures with 90min runway to market open.

---

## §1 Phase 0 active discovery findings (34 cumulative)

### Pre-restart inventory (Findings #1-#5)

| # | Finding | Resolution |
|---|---|---|
| 1 | LL-170 cite drift Plan §A → 真值 LL-175 | append-only amend (deferred Step 10b) |
| 2 | Constitution §L10.5 5 prereq verified READY | sediment Step 10b |
| 3 | Pre-CT-2b services ran stale paper-mode .env | resolved via restart (Step 0) |
| 4 | `service_manager.ps1` PG16 probe stale (cosmetic) | ops debt filed BAU |
| 5 | Servy FastAPI declared dep on PG16 Windows service blocked restart | **FIXED in this session** (uninstall + import without PG16 dep) |

### Schema/cite drifts (Findings #6-#9)

| # | Finding | Resolution |
|---|---|---|
| 6 | trading_calendar column = `is_trading_day` (not `is_open`) | sediment |
| 7 | beat_schedule.py header "不激活" comment stale | sediment |
| 8 | IC-3a/b/TB-5b scripts hardcode "EXECUTION_MODE=paper" report text | future cite drift hazard sediment |
| 9 | sys.path drift: `from backend.qm_platform._types` requires PROJECT_ROOT on path | **sustained pattern** — recurred in Finding #32 |

### Data pipeline silent failures (Findings #10-#22)

| # | Finding | Severity | Resolution |
|---|---|---|---|
| 10 | API path drift (portfolio/risk/pt 404, dashboard/execution worked) | P3 | sediment |
| 11 | /api/dashboard/alerts stale P0 for retired risk_daily_check + intraday_risk_check | P3 cosmetic | sediment |
| 12 | klines_daily latest 2026-05-07 (6 days stale per dashboard) | **P0** | **RESOLVED Step 2** |
| 13 | /api/execution/drift returns stale position state | P1 | RESOLVED Step 7 (drift recomputes from fresh truth) |
| 14 | position_snapshot DB latest 4-17 vs xtquant 0 持仓 reality | **P1** | **RESOLVED Step 7** (162 row DELETE) |
| 15 | factor_values latest 2026-04-28 (19 days stale) | **P0** | **RESOLVED Step 4** (4 factors fresh through 5-15) |
| 16 | signal_phase status=FAILED 5/5 last weekdays (5-11~5-15); 健康预检失败 | **P0** | **RESOLVED Step 6 v2** (full chain green) |
| 17 | NO klines / daily_pipeline / factor_compute schtask | **P0** | partial (Step 2 manual backfill); permanent fix Step 11 BAU |
| 18 | QuantMind_DailyExecute schtask DISABLED since 4-19 | **P0 procedural** | **RESOLVED Step 9** (enabled for Mon 09:31) |
| 19 | schtask Result=0 vs scheduler_task_log status=failed disconnect | P2 audit risk | sediment |
| 20 | signal_phase failure no error_message captured | P2 silent failure | sediment |
| 21 | minute_bars 1+ month stale (replay-only impact) | P2 | defer post-Monday |
| 22 | QuantMind_DataQualityCheck + PT_Watchdog + RiskFrameworkHealth schtask Result=1 sustained | P2 BAU | Step 12 BAU |

### Architectural debt (Findings #23-#26)

| # | Finding |
|---|---|
| 23 | DataOrchestrator "部分实施 4-17" replacement for archived pull_full_data.py (4-08) NEVER completed → 19-day data ingestion gap |
| 24 | QuantMind_DataQualityCheck 4-layer silent failure: schtask Result=1 / 0 scheduler_task_log entries / 0 DingTalk push / dashboard surfaced but unattended |
| 25 | No schtask exists for klines / daily_basic / adj_factor / stk_limit ingestion (only moneyflow migrated) |
| 26 | Tushare timing per official docs: daily 15:00-16:00 / daily_basic 15:00-17:00 / adj_factor 09:15-09:20 next-day / stk_limit 08:40 next-day → schtask must split pre-open + post-close passes |

### Tonight's remediation surfacing (Findings #27-#34)

| # | Finding |
|---|---|
| 27 | `compute_batch_factors` silently skips factor_names not in factor_set (dv_ttm in PHASE0_FULL not PHASE0_CORE) — 铁律 33 fail-loud violation |
| 28 | `DataOrchestrator.neutralize_factors` PipelineResult status="FAILED" when all factors skipped via incremental=True (should be NO_OP) |
| 29 | `build_stock_status.py` is full-only (no `--start/--end` incremental mode) — should grow flags for BAU |
| 30 | `_assert_positions_not_evaporated` false-positive when CT-1a cutover cleanup scope didn't include pre-rebalance 4-17 baseline |
| 31 | Shadow LightGBM model `fold_7.txt` missing (signal_phase warns, non-blocker) |
| 32 | `services_healthcheck.py` had **same sys.path drift as Finding #9** (TB-5b recurrence) → silent Result=1 every 15min for weeks → masked Finding #33 |
| 33 | CeleryBeat silent death 2026-05-17 12:51-15:34 (2h45min zombie). Caught by services_healthcheck.py POST sys.path fix. Without Finding #32 fix, this would have stayed silent through Monday open |
| 34 | DingTalk push fired successfully despite earlier assumption "DINGTALK_ALERTS_ENABLED=false sustained" — alert dispatch active, env path control needs verify |

---

## §2 10-step remediation execution + verdicts

| # | Step | Time | Mutation | Verdict |
|---|---|---|---|---|
| 0 | Service restart (CT-2b post-flip .env reload) | ~30s | Servy restart 4 services + FastAPI dep fix | ✅ runtime live mode |
| 1 | backfill_klines_2026_05.py written + dry-run | code | NEW script + dry-run | ✅ |
| 2 | klines + daily_basic backfill 5-08~5-15 (--apply) | ~10s | 6 dates × 2 tables, +33K rows each | ✅ both fresh through 5-15 |
| 3 | DB freshness verify | inline | none | ✅ |
| 4 | factor_values CORE3+dv_ttm recompute (2 apply runs incl. dv_ttm fix) | ~30min | +131K raw + neutral + zscore | ✅ all 4 factors fresh |
| 5 | stock_status_daily full backfill (idempotent UPSERT) | 205s | 11.83M rows (102.4% klines coverage) | ✅ fresh through 5-15 |
| 6 | signal_phase 2026-05-15 verify (2 attempts: v1 surfaced #14, v2 post Step 7) | 78s | writes to signals table | ✅ 20 target signals stored |
| 7 | position_snapshot pre-cutover cleanup (162 row atomic DELETE + JSON rollback snapshot) | 0.04s | 162 row DELETE | ✅ 0 rows remain |
| 8 | E2E Monday-readiness verify | inline | none | ✅ ALL critical checks pass |
| 8b | services_healthcheck.py sys.path fix + CeleryBeat restart | ~5s | code edit + Servy restart | ✅ Beat heartbeat fresh 0.1min |
| 9 | Enable QuantMind_DailyExecute schtask | ~2s | Enable-ScheduledTask | ✅ State=Ready / NextRun=Mon 09:31 |

---

## §3 Defense-in-depth evidence (LL-098 X10 cumulative)

**5 defense-in-depth wins demonstrated tonight**:

1. **Q2 (B) "restart now" recommendation**: caught Finding #5 (Servy PG16 dep) with 30h buffer (Monday 08:00 alternative = 90min pre-market)
2. **Step 6 v1 fail-loud**: `_assert_positions_not_evaporated` fired correctly → surfaced Finding #14 → led to Step 7 cleanup
3. **Step 8b services_healthcheck**: just-fixed script immediately caught Finding #33 Beat zombie (would have stayed silent through Monday)
4. **Step 4 v1 partial**: compute_batch_factors silent-skip of dv_ttm surfaced as 1-of-4 factor still stale → led to Finding #27 fix + Step 4 v2 re-run
5. **Step 2 backfill idempotent UPSERT**: safe to retry on any sub-day failure (DataPipeline ON CONFLICT) — no risk of partial state corruption

**Sustained --dry-run/--apply/--rollback 3-mode runner体例** demonstrated across 4 sub-PR sediment cumulative (CT-1a apply / CT-2b apply / CT-2c-pre cleanup / recompute_factor_values_2026_05). Atomic-snapshot-then-mutate pattern with JSON rollback always available.

---

## §4 BAU follow-up items (Step 11/12 + deferred sediment)

### Critical BAU (must do post-Monday open if going to BAU mode)

| # | Item | Effort | Cite |
|---|---|---|---|
| 11 | Build `QuantMind_DailyDataIngest` 2-pass schtask | medium | Findings #25+#26: pre-open 08:50 SH for stk_limit+adj_factor (T-day) + post-close 17:30 SH for daily+daily_basic (T-day) |
| 12 | Fix `QuantMind_DataQualityCheck` 4-layer silent failure | medium | Finding #24: schtask Result=1 / 0 log / 0 alert / dashboard unattended |

### Deferred sediment (Step 10b, low priority — state is already true; sediment captures it)

| Item | Cite |
|---|---|
| Plan v0.4 §A CT-2c closure blockquote | LL-170 cite drift append-only amend → 真值 LL-175 |
| Constitution §L10.5 amend | 5 prereq [x] + .env 授权 ✅ + closure blockquote + version v0.12→v0.13 |
| ADR-077 reserved→committed | Plan v0.4 closure cumulative + Gate E formal close |
| ADR-082 reserved→committed | Post-cutover ongoing monitoring体例 (3 carried Gate-E deferrals: LiteLLM 月成本 / RAG retrieval / lesson 后置 — all reframed POST-cutover monthly review) |
| Skeleton §2.X patch | Plan v0.4 sprint chain row |
| PR creation + reviewers + AI self-merge | Sustained LL-059 #75 incremental |

### Other BAU items filed for post-Monday

- Finding #21: minute_bars 1+ month stale (replay-only)
- Finding #22: 3 schtask Result=1 sustained (DataQualityCheck / PT_Watchdog / RiskFrameworkHealth)
- Finding #28: DataOrchestrator.neutralize_factors PipelineResult status FAILED→NO_OP mapping
- Finding #29: build_stock_status.py grow --start/--end flags
- Finding #34: DingTalk dispatch env path verify

---

## §5 红线 5/5 sustained verification

| # | 红线 | Pre-CT-2c-pre | Post-CT-2c-pre |
|---|---|---|---|
| 1 | cash | ¥993,520.66 | ¥993,520.66 (sustained xtquant truth) |
| 2 | 持仓 | 0 | 0 (sustained) |
| 3 | LIVE_TRADING_DISABLED | false (post-CT-2b) | false (sustained) |
| 4 | EXECUTION_MODE | live (post-CT-2b) | live (sustained) |
| 5 | QMT_ACCOUNT_ID | 81001102 | 81001102 (sustained) |

红线 5/5 unchanged. CT-2c-pre was pure operational hygiene; 0 broker / 0 .env / 0 yaml / 0 LLM call.

---

## §6 Monday morning watch checklist

**For 2026-05-18 SH operator**:

```
09:00  Pre-open. Verify 4 Servy services + Beat alive:
       powershell -File scripts\service_manager.ps1 status
       python scripts\services_healthcheck.py

09:30  Market open. xtquant Data Service publishes ticks.
       Monitor: qm:qmt:status XLEN growing

09:31  QuantMind_DailyExecute fires.
       Watch:
         - scheduler_task_log new "execute_phase" entry
         - trade_log new rows (execution_mode='live')
         - xtquant query: cash decreases, positions populate
         - /api/dashboard/summary nav update

15:00  Market close.
15:40  QuantMind_DailyReconciliation
16:30  QuantMind_DailySignal generates Tue target
17:30  QuantMind_DailyMoneyflow
```

**Emergency rollback** (if Mon surfaces P0):

```powershell
Disable-ScheduledTask -TaskName QuantMind_DailyExecute
# Optionally: python scripts/v3_ct_2b_env_flip_apply.py --rollback  # .env back to paper
# powershell -File scripts\service_manager.ps1 restart all
# Optionally: python scripts/v3_ct_2c_pre_position_snapshot_cleanup.py --rollback
```

---

## §7 关联

- V3 Plan v0.4 §A CT-2c (operational health remediation surfaced via Phase 0)
- Constitution §L10.5 Gate E (5 prereq + .env 授权 5/5 ✅)
- ADR-022 (反 retroactive content edit, append-only sediment)
- ADR-027 (L4 STAGED sustained OFF) / ADR-028 (L4_AUTO_MODE_ENABLED sustained OFF)
- ADR-063 (replay-as-gate transferable methodology)
- 铁律 9 (重数据 max 2 并发) / 17 (DataPipeline) / 33 (silent failure prohibition) / 41 (timezone)
- LL-059 (AI self-merge体例) / LL-066 (DataPipeline subset UPSERT 例外) / LL-074 (Beat zombie watchdog SOP) / LL-098 X10 (forward-progress STOP gate) / LL-100 chunked SOP / LL-173 lesson 1 (replay-as-gate) / LL-174 lesson 2 (3-step user gate)
- **LL-175 NEW**: CT-2c-pre cycle lessons cumulative (sediment append below)

---

## §8 Pre-PR state sustainability

- 0 broker call / 0 .env mutation / 0 yaml mutation / 0 LLM call / 0 真 DingTalk push (other than DingTalk recovery alert from CeleryBeat restart — operational, not strategic)
- 红线 5/5 sustained throughout CT-2c-pre
- 4 new scripts + 1 patched script + 1 rollback snapshot JSON + this report
- 162 row DELETE applied atomically (Step 7) + reversible via --rollback
