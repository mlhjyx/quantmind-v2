# Scheduler vs V3 §9 24h-Cycle Drift Audit (2026-05-25)

> **Scope**: 3-way drift audit — `docs/DEV_SCHEDULER.md` §〇+§二 declared schedule  vs `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` §9.1 24h-cycle 时序  vs production truth `backend/app/tasks/beat_schedule.py` (24 active entries).
> **NO commit / NO push** — read-only audit per user prompt.

---

## §1 DEV_SCHEDULER.md 时序 inventory

§〇 (iter 76 refresh) declares 24 Beat entries + 27 Windows schtask. PT 主 chain via schtask, V3 风控/ML/news via Beat.

§二 (legacy + P1 review patch §249-292) declares:
- **T日盘后** (P1 patch): T0 16:00 healthcheck → T1 16:30 data → T2 17:00 quality → T3 17:05 universe → T4 17:10 factor → T5 17:25 lifecycle (Mon) → T6 17:35 ML → T7 17:40 signal → T8 17:45 rebalance → T9 17:50 report.
- **T+1 盘前**: T10 08:30 read instructions → T11 09:30 execute → T12 11:30 fill check → T13 15:00 close → T14 15:30 perf.
- **夜间**: T16 Sun 22:00 AI pipeline / T17 Sun 03:00 DB maint.
- **P6 (Sprint 1.9)**: 09:25 集合竞价跳空 + 每日 16:30 PnL check + 盘中 monitor.

§二 P1 patch does **not** mention V3 layered: L0 news cadence / L1 realtime / L2 regime / L3 dynamic threshold / L4 STAGED / L5 reflector.

---

## §2 V3 §9.1 24h-cycle 时序 inventory (from sequenceDiagram)

| 窗口 | 任务 | Layer |
|---|---|---|
| Pre-Market 08:30 | News 6src overnight ingest + V4-Flash classify; Bull/Bear regime update; L3 threshold refresh; P0 push overnight | L0 / L2 / L3 |
| Open Auction 09:15-09:25 | GapDownOpen check (集合竞价 tick) | L1 |
| Trading 09:30-15:00 | 8 RealtimeRiskRule via subscribe_quote; L2 context query on trigger; L4 STAGED prepare (14:55 挂限); broker exec | L1 / L2 / L4 |
| Daily Beat 14:30 | 10 sustained PMSRule eval + P2 daily summary | L1 |
| Close 15:00-16:00 | fundamental_context_daily ingest; outcome tracking | L0 / L4 |
| Sunday 19:00 | RiskReflector V4-Pro (5维) + RAG embed + weekly push + user approve | L5 |
| Monthly 1st 09:00 | (implied) monthly reflection | L5 |

V3 §9.1 omits **08:00 monthly LLM cost** + **02:00 Q-start slippage** + **30s outbox** + **News 6×daily 3/7/11/15/19/23** + **announcement 9/11/13/15/17:15** + **fundamental 16:00** + **dynamic threshold 5min** + **L4 sweep 1min** + **broker-stuck 5min** + **meta-monitor 5min** + **regime 09:00/14:30/16:00** — these are real Beat entries but not in §9.1 sequenceDiagram (which is a narrative trace, not exhaustive).

---

## §3 beat_schedule.py 24 entries 时序 inventory

Full 24 entries enumerated in DEV_SCHEDULER §〇 table (verified line-by-line vs `backend/app/tasks/beat_schedule.py:48-489`). No drift between §〇 table and code.

---

## §4 3-way drift table

| Task / 窗口 | DEV §二 says | V3 §9.1 says | beat_schedule.py says | Drift |
|---|---|---|---|---|
| Pre-market 08:30 news + regime | absent | "News 6src ingest + V4-Flash + regime update" | news cron 03/07/.../23 (6×/day, 07:00 closest), regime 09:00 | ⚠️ V3 narrative 08:30 vs prod 07:00 news + 09:00 regime — narrative-only drift, prod consistent with V3 §3/§5 cadence |
| 09:25 集合竞价 gap check | T+1 P6 "09:25" | "Open Auction 09:15-09:25 GapDownOpen" | absent (no Beat entry) | ❌ Both DEV + V3 say 09:25, prod 0 Beat entry — implementation gap |
| Daily PMS 14:30 | absent | "Daily PMS Beat 14:30 — 10 sustained PMSRule" | absent (risk-daily-check retired 2026-05-15 per IC-2b) | ⚠️ V3 §9.1 stale — V3 chain now covers it via L1 RealtimeRiskEngine (sustained), §9.1 diagram not refreshed |
| L4 sweep 1min | absent | absent (only "14:55 挂限" mentioned) | `risk-l4-sweep-1min` `* 9-14 * * 1-5` | ⚠️ V3 §9.1 doesn't show the periodic sweep tick |
| Dynamic threshold 5min | absent | "L3 update thresholds" (no cadence) | `risk-dynamic-threshold-5min` `*/5 9-14 * * 1-5` | ⚠️ V3 §9.1 omits cadence |
| 30s outbox publisher | absent | absent | `outbox-publisher-tick` 30s | ⚠️ Cross-cutting, neither narrative documents |
| Announcement 9/11/13/15/17:15 | absent | "公告流" mentioned in §3.4 | `announcement-ingest-trading-hours` 9,11,13,15,17 minute=15 | ⚠️ Not in V3 §9.1 narrative |
| Fundamental 16:00 | absent | "Close 15:00-16:00 fundamental_context_daily ingest" | `fundamental-context-daily-1600` 16:00 | ✅ match |
| Regime 09:00/14:30/16:00 | absent | "Pre-Market regime update" (single, not 3 daily) | 3 entries 09:00 / 14:30 / 16:00 | ⚠️ V3 §9.1 shows 1, prod fires 3× per V3 §5.3 line 664 |
| Reflector Sun 19:00 | T16 Sun 22:00 "AI pipeline" | "Sunday 19:00 RiskReflector V4-Pro" | `risk-reflector-weekly` Sun 19:00 | ❌ DEV §二 conflates Reflector with GP mining at 22:00 — actually 2 separate tasks (Reflector 19:00 + GP mining 22:00) |
| Monthly reflector 1st 09:00 | absent | implied by §8.1 weekly+monthly | `risk-reflector-monthly` 1st 09:00 | ⚠️ V3 §9.1 omits, prod has it |
| Monthly LLM cost 1st 08:00 | absent | absent | `llm-cost-monthly-audit` 1st 08:00 | ⚠️ Cross-cutting, neither documents |
| Quarterly slippage Q-start 02:00 | absent | absent | `slippage-calibration-quarterly` 1日 02:00 Q1/Q2/Q3/Q4 | ⚠️ Cross-cutting, neither documents |
| Daily attribution 16:30 | absent | absent | `daily-attribution-compute` 16:30 Mon-Fri (MVP 4.2 iter 65) | ⚠️ Wave 4 sediment not yet in V3 §9.1 |
| Daily backup 02:30 | absent | absent | `daily-backup-run` 02:30 (MVP 4.4 iter 75) | ⚠️ Wave 4 sediment not yet in V3 §9.1 |
| Weekly backup verify Sun 04:00 | absent | absent | `weekly-backup-verify` Sun 04:00 (MVP 4.4 iter 75) | ⚠️ Wave 4 sediment not yet in V3 §9.1 |
| Reports cleanup Sun 04:30 | absent | absent | `reports-cleanup-weekly` Sun 04:30 (iter 30/31) | ⚠️ Cross-cutting, neither documents |
| Meta-monitor 5min | absent | absent | `meta-monitor-tick` `*/5 * * * *` (HC-1b) | ⚠️ V3 §13.3 has it, §9.1 narrative omits |
| Broker-stuck 5min | absent | absent | `risk-l4-broker-stuck-sweep` `*/5 * * * *` (HC-2b2 G7) | ⚠️ V3 §14 mode 12 has it, §9.1 omits |
| Factor lifecycle Fri 19:00 | T5 "Mon 17:25" | absent | `factor-lifecycle-weekly` Fri 19:00 | ❌ DEV §二 says Mon, prod Fri |
| Daily quality 17:40 | T9 "17:50 report" | absent | `daily-quality-report` 17:40 Mon-Fri | ⚠️ DEV time drift (17:50 vs 17:40), task name drift |
| PT main chain (HealthCheck/Signal/Execute) | T0/T7/T11 in P1 patch | absent | schtask 16:25/16:30/09:31 (NOT Beat) | ✅ DEV §〇 architecture note documents schtask, §二 P1 patch times match |

---

## §5 Recommendation

1. **V3 §9.1 sequenceDiagram refresh** (Tier B candidate, post Wave 4 sediment): add 7 missing cross-cutting Beat (outbox 30s / news 6×/day / announcement 5×/day trading-hours / regime 3 daily / meta-monitor 5min / broker-stuck 5min / dynamic-threshold 5min) + 6 Wave 4 sediment (attribution 16:30 / backup 02:30 / weekly-verify Sun 04:00 / reports-cleanup Sun 04:30 / monthly LLM 1st 08:00 / quarterly slippage Q-start 02:00). Refresh "Daily PMS Beat 14:30" line — retired 2026-05-15 per IC-2b, now via L1 RealtimeRiskEngine sustained.

   **iter 156 ARCHIVE closure (2026-05-26)**: §5 Rec #1 **CLOSED** — fresh grep `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` §9.1 lines 1023-1095 verifies ALL 7 cross-cutting Beats + 6 Wave 4 sediments + PMS 14:30 RETIRED note ALREADY PRESENT in current sequenceDiagram. Doc header line 1018-1020 explicitly states "Last fresh verify 2026-05-25 17:45 SH iter 99 ... Refresh source: docs/audit/SCHEDULER_V3_CYCLE_DRIFT_2026_05_25.md §3+§5 — add 14 missing Beat + retire PMS 14:30 (IC-2b 2026-05-15)". The refresh was completed iter 99 evening 2026-05-25 BEFORE this audit doc was written iter 100+. Sibling to LL-207 + LL-208 anti-pattern (audit recommendations stale, reality already changed 4th W2-3 instance).

2. **DEV_SCHEDULER §二 P1 patch deprecation** (high priority): §二 P1 patch (lines 249-292) is stale March-2026 vintage — T5 says Mon 17:25 (prod Fri 19:00), T9 says 17:50 report (prod 17:40), T16 conflates Reflector+GP mining (actually 2 tasks). Mark §二 P1 patch as **HISTORICAL — see §〇 for truth**, OR refresh in-place.

3. **09:25 集合竞价 gap check 0 Beat entry** (implementation gap): both DEV §二 P6 and V3 §9.1 declare 09:25 GapDownOpen check; production has 0 Beat schedule entry. Either (a) gap check runs inside L1 RealtimeRiskEngine on subscribe_quote tick (need code-trace verify) or (b) genuine missing implementation — recommend grep `GapDownOpen` in backend code as follow-up.

**Iter 127 closure (2026-05-25)**: hypothesis (a) **CONFIRMED**. `GapDownOpen` is implemented in L1 RealtimeRiskEngine — code-trace verify via Grep "GapDownOpen":
   - `backend/qm_platform/risk/realtime/rule_registry.py` (rule registration)
   - `backend/qm_platform/risk/realtime/alert.py` (alert handling)
   - `backend/qm_platform/risk/backtest_adapter.py` + `replay/acceptance.py` (backtest replay)
   - 6 test files cover the rule
   No Beat entry needed — rule fires on `subscribe_quote` tick via L1 RealtimeRiskEngine sustained pattern (V3 §S5). Doc narrative says "09:25" because gap is detectable then but execution is real-time subscription-driven, not scheduled.

**Verdict**: §5 Rec #3 CLOSED (not implementation gap, just narrative-vs-architecture-pattern misalignment).

4. **§〇 table is the operational SSOT** — §二 P1 patch + V3 §9.1 sequenceDiagram are narrative/design artifacts; truth is `beat_schedule.py` 24 entries (already mirrored in §〇 table line-for-line as of iter 76).

---

## §6 4-element cite source

| # | Path | Line# | Section | Verify timestamp |
|---|---|---|---|---|
| 1 | `D:\quantmind-v2\docs\DEV_SCHEDULER.md` | L28-89 | §〇 Beat+Schtask 真实清单 (iter 76 refresh) | 2026-05-25 fresh read this session |
| 2 | `D:\quantmind-v2\docs\DEV_SCHEDULER.md` | L249-292 | §二 P1 patch (T0-T17 timeline) | 2026-05-25 fresh read this session |
| 3 | `D:\quantmind-v2\docs\QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` | L1012-1075 | §9.1 24h cycle sequenceDiagram | 2026-05-25 fresh read this session |
| 4 | `D:\quantmind-v2\backend\app\tasks\beat_schedule.py` | L48-490 | CELERY_BEAT_SCHEDULE 24 active entries | 2026-05-25 fresh read this session |
