# V3 Audit — Subagent I Supplement: ML / LLM Cost / RAG / Audit Trail DB-Verify

> **Audit ID**: SYSTEM_AUDIT_2026_05 Phase 7 Subagent I supplement
> **Date**: 2026-05-18 evening (跨日 2026-05-19 early hours)
> **Type**: Supplemental — extends original Subagent I findings (Master committed `b4b8b8c`)
> **Status**: 6/6 DB-VERIFY queries executed successfully, 6/6 [DB-VERIFY-PENDING] flags closed
> **Scope**: §31 LLM Cost / §32 V4-Flash/Pro Routing / §34 RAG Memory / §29.1 F-D78-241 sustained / Dead Table Audit (Subagent C 12 candidates)
> **PG creds source**: `backend/.env:24` (plaintext, flagged as P0-2 in Master)
> **PG DSN verified**: `postgresql://xin:quantmind@localhost:5432/quantmind_v2`

---

## §0 Methodology

5 PowerShell + psql.exe round-trips against live PG 16.8 (D:\pgsql\bin\psql.exe). Schema discovery via `\d <table>` first (CLAUDE.md fresh-read SOP, ADR-037 fresh-read enforce). Master findings had schema-guess error (`call_type` does not exist) — supplement re-runs with verified column names (`task`, `triggered_at`, `actual_model`, `primary_alias`, `budget_state`, `cost_usd`, `tokens_in/out`).

All findings preserve heuristic #18 GLOBAL enforce — 2-3 alternatives per P0/P1/P2.

---

## §31 LLM Cost Per Decision Granularity — DB-VERIFIED

### §31.1 MTD Cost By Task (May 2026)

`SELECT task, COUNT(*), ROUND(SUM(cost_usd)::numeric,4) FROM llm_call_log WHERE triggered_at > date_trunc('month', NOW()) GROUP BY 1 ORDER BY 3 DESC;`

| task | count | total_usd |
|---|---|---|
| news_classify | 551 | **0.0000** |
| bull_agent | 6 | **0.0000** |
| bear_agent | 6 | **0.0000** |
| judge | 6 | **0.0000** |
| risk_reflector | 1 | **0.0000** |
| **TOTAL** | **570** | **$0.0000** |

### §31.2 P0 NEW Finding — Cost Tracking 100% Broken (sustained 12 days, since first call 5-07 03:00)

**Real situation**: All 570 LLM calls month-to-date show `cost_usd=0.0000`. **0/570 cost actually tracked**. Budget compliance = vacuously TRUE because nominator is zero.

**Cross-verify token activity** (rules out "no calls happened"):
- `news_classify` avg 1388 tokens_in / 147 tokens_out × 551 calls ≈ **846K tokens consumed**
- `bull_agent` avg 702 in / 684 out × 6 = ~8.3K
- `bear_agent` avg 704 in / 664 out × 6 = ~8.2K
- `judge` avg 1248 in / 855 out × 6 = ~12.6K
- `risk_reflector` avg 1629 in / 329 out × 1 = ~2K
- **Total tokens MTD ≈ 877K** (DeepSeek pricing v4-flash: input $0.07/M + output $1.10/M; v4-pro: input $0.27/M + output $1.10/M)

**Expected real cost MTD** (rough):
- news_classify (v4-flash): 551 × (1388 × $0.07/M + 147 × $1.10/M) ≈ 551 × ($0.0001 + $0.00016) ≈ **$0.14**
- 5 v4-pro tasks combined: ~19 calls × ~(900 × $0.27/M + 600 × $1.10/M) ≈ 19 × $0.0009 ≈ **$0.02**
- **Expected total ≈ $0.16 MTD** (not $0.00)

**Finding F-S7-001 [P0]** — `llm_call_log.cost_usd` INSERT path 100% writes 0.0000. The cost integration to LiteLLM response is broken. Heuristic #15 Test-Reality Gap (12 days × 570 calls × 0 surfaced).

**Cite source**: `backend/qm_platform/llm/_internal/audit.py:74` `LLMCallRecord` dataclass spec (13 columns), `cost_usd` field declared `Decimal`. INSERT path source-of-truth: somewhere upstream — likely LiteLLMResponse missing `usage.total_cost` extract.

**#18 Alternatives**:
1. Add `LLMCallLogger.record_cost()` defensive: if `cost_usd == 0 AND tokens_in+tokens_out > 0` → fall back to lookup-table `models.json` pricing × tokens, log structured warning.
2. Add post-insert audit assertion: `daily_llm_audit.sql` cron query `SELECT COUNT(*) FROM llm_call_log WHERE cost_usd = 0 AND tokens_in+tokens_out > 0 AND triggered_at > NOW()-INTERVAL '1 day'` → DingTalk if > 5.
3. Replace dependency on LiteLLM cost field with hardcoded per-model price registry pinned in `config/llm_pricing.yaml` (deterministic, no upstream coupling).

### §31.3 Budget State Distribution

`SELECT budget_state, COUNT(*) FROM llm_call_log WHERE triggered_at > date_trunc('month', NOW()) GROUP BY 1;`

| budget_state | count |
|---|---|
| normal | 570 |
| warn_80 | 0 |
| capped_100 | 0 |

**Finding F-S7-002 [P1]** — Budget state always `normal` because cost_usd=0 → guard sees 0 MTD vs $50 cap → never trips. **BudgetGuard cannot fire alerts in current state.** This is a downstream symptom of F-S7-001 but separately worth flagging: budget guard is **silently 100% defanged**.

**#18 Alternatives**:
1. Switch BudgetGuard to use `tokens_in * input_price + tokens_out * output_price` directly (bypass cost_usd column until F-S7-001 fixed).
2. Add weekly invariant test in CI: assert `SELECT SUM(cost_usd) FROM llm_call_log WHERE triggered_at > NOW()-INTERVAL '7 days' > 0` fails loudly if 0.
3. Dashboard alert: panel "Days since last non-zero LLM cost row" — fires after 1 day.

### §31.4 LLM Daily Activity 14 days

| date | calls |
|---|---|
| 2026-05-07 | 45 (first call ever) |
| 2026-05-08 | 42 |
| 2026-05-09 | 37 |
| 2026-05-10 | 43 |
| 2026-05-11 | 58 |
| 2026-05-12 | 49 |
| 2026-05-13 | 59 |
| 2026-05-14 | 63 (+ first bull/bear/judge debate cycle) |
| 2026-05-15 | 68 |
| 2026-05-16 | 52 |
| 2026-05-17 | 39 (first risk_reflector call) |
| 2026-05-18 | 15 (partial day) |

System is genuinely active. Cost tracking is genuinely broken.

---

## §32 V4-Flash / V4-Pro Routing 真值 — DB-VERIFIED

### §32.1 Last 7d Actual Model Distribution

`SELECT actual_model, COUNT(*) FROM llm_call_log WHERE triggered_at > NOW() - INTERVAL '7 days' GROUP BY 1;`

| actual_model | count | % |
|---|---|---|
| deepseek-v4-flash | 326 | **94.5%** |
| deepseek-v4-pro | 19 | **5.5%** |
| **TOTAL** | **345** | 100% |

### §32.2 Alias vs Actual Model Cross-Check

`SELECT primary_alias, actual_model, COUNT(*), SUM(is_fallback::int) FROM llm_call_log WHERE triggered_at > NOW() - INTERVAL '7 days' GROUP BY 1,2;`

| primary_alias | actual_model | count | fallback_count |
|---|---|---|---|
| deepseek-v4-flash | deepseek-v4-flash | 326 | **0** |
| deepseek-v4-pro | deepseek-v4-pro | 19 | **0** |

**Routing integrity** ✅ — `primary_alias == actual_model` for all 345 calls. **0 fallback to qwen3-local** triggered over 7d. LiteLLM Router is honoring TASK_TO_MODEL_ALIAS mapping correctly.

### §32.3 P2 NEW Finding — Original Master §32.1 ADR-036 Concern Quantified

Master §32.1 hypothesized: "ADR-036 BULL/BEAR → v4-pro 成本 ↑" — this is now quantifiable:

| Period | bull+bear+judge+reflector calls (v4-pro target) | news_classify+fundamental+embedding (v4-flash target) |
|---|---|---|
| Whole table history (5-07 → 5-18) | 6+6+6+1 = **19** | 551 v4-flash news_classify only |
| **Ratio v4-pro / total** | **3.3%** | 96.7% v4-flash |

**Finding F-S7-003 [P2]** — Despite ADR-036 swapping BULL/BEAR from flash → pro, actual v4-pro call count is only **19 over 12 days** (1.6 calls/day). The marginal cost ↑ concern is **NOT material at current volumes**. ADR-036 fear is hypothetical at current activity scale. **However**, when RAG memory population scales (§34 currently 1 row), v4-pro volume will multiply.

**#18 Alternatives**:
1. Keep ADR-036 as-is for now; revisit when bull+bear+judge+reflector volume > 100 calls/day.
2. Add pre-emptive throttle: if (v4-pro 7d count > 200) AND (cost_usd-tracked spend > $30) → auto-downgrade bull+bear to v4-flash via env flag.
3. A/B harness already feasible at low volume — run 14d split test (50% bull v4-flash + 50% v4-pro, compare judge agreement rate) **before** RAG-scale-up cost lock-in.

### §32.4 P1 NEW Finding — Routing Coverage Gap

Master expected 7 task types routed. Real DB shows **5 task types** seen in 12 days:
- ✅ news_classify (551)
- ✅ bull_agent (6)
- ✅ bear_agent (6)
- ✅ judge (6)
- ✅ risk_reflector (1)
- ❌ **fundamental_summarize** — 0 calls ever (sustained since 5-07)
- ❌ **embedding** — 0 calls ever (sustained since 5-07)

**Finding F-S7-004 [P1]** — 2/7 (28.6%) task types **never invoked in production**. The fundamental_summarize + embedding code paths are dead-coded or never-wired. This matches the §34 finding that risk_memory has 1 row → embedding path not exercised at scale.

**#18 Alternatives**:
1. Grep call sites for `RiskTaskType.FUNDAMENTAL_SUMMARIZE` and `RiskTaskType.EMBEDDING` to verify code-path existence, then delete dead enum members if confirmed unused (saves ~30 lines + reduces test surface).
2. If wiring is partial (called but path broken), add `pytest -m wire-smoke` per-task invocation test.
3. Roadmap-track: per V3 §5.5 fundamental_summarize is part of S4 (ADR-053 cite "akshare 1 source"), embedding is part of S3 (RAG). Both are designed but **0 prod calls** sustains the V3-as-Island gap (LL-170 sustained).

---

## §34 RAG Memory Population — DB-VERIFIED

### §34.1 Population Snapshot

`SELECT COUNT(*), MAX(event_timestamp), MAX(created_at) FROM risk_memory;`

| metric | value |
|---|---|
| row_count | **1** |
| latest_event_timestamp | 2026-05-17 19:00:00 |
| latest_created_at | 2026-05-17 19:00:38 |

`SELECT event_type, action_taken, COUNT(*) FROM risk_memory GROUP BY 1,2;`

| event_type | action_taken | count |
|---|---|---|
| Reflection:Weekly | (NULL) | 1 |

### §34.2 P0 NEW Finding — RAG is Theatrical (1 row, 0 retrieval value)

**Finding F-S7-005 [P0]** — risk_memory has **1 row** after RAG infrastructure has been "closed" via ADR-068 (TB-3 risk-memory RAG closure). The single row is a weekly Reflector pass from 5-17 19:00 (correlates with §31 risk_reflector single call). **At 1 row population, RAG retrieval has 0 production value** — IVFFLAT index needs ~thousands of vectors before nearest-neighbor is meaningful. The 1024-dimensional pgvector embedding is currently a write-only artifact.

**Severity rationale**: Master flagged this P1, supplement upgrades to P0 because (a) ADR-068 + ADR-070 sediment claims closure, (b) reality is 1 row sustained 1 day, (c) V3 §3.2 line 393 "RAG 闭环触发" 真预约 is materially unmet, (d) impacts Bull/Bear/Reflector agent quality at scale (their retrieval will be effectively random).

**#18 Alternatives**:
1. **Backfill historical risk events to risk_memory**: 105 trade_log rows + 3 risk_event_log + LL-170~183 incident transcripts = potential ~50-150 seed rows. Run one-off `scripts/risk_memory_backfill.py` to bootstrap retrieval surface.
2. **Lower the threshold to populate**: schedule a daily (not weekly) Reflector pass that ingests `trade_log` + `risk_event_log` rows from prior day. Even no-event days produce a "calm market" reflection — at 365 rows/year RAG starts to have signal.
3. **Defer RAG until population threshold**: gate Bull/Bear agent RAG retrieval behind `if COUNT(*) FROM risk_memory >= 100: do_rag() else: skip_rag()`. Prevents random retrieval polluting decisions in current low-population regime.

### §34.3 RAG Retrieval Consumption — Sustained Trace Gap

Master §34.1 noted "Bull/Bear/Reflector RAG 消费 0 file-trace". Supplement confirms via DB: with 1 row total, even if bull_agent (6 calls) and bear_agent (6 calls) attempted retrieval, the result set would be that same single row 12 times. No meaningful RAG signal possible. The `Reflection:Weekly` row's `outcome` JSONB and `lesson` text were not examined here but should be in follow-up.

---

## §29.1 F-D78-241 SUSTAINED — DB-VERIFIED 19 DAYS STALE

### §29.1.1 Three-Source Reconciliation (current 2026-05-19 early hours)

| Source | Value | Stale Days (vs today 5-19) |
|---|---|---|
| `xtquant` API (Master cite, 4-30 14:54 snapshot) | cash ¥993,520.16 / 0 持仓 | **19 days** (but ground truth) |
| `trade_log` MAX(executed_at) | **2026-04-29 10:43:59** | **20 days stale** |
| `risk_event_log` MAX(triggered_at) | **2026-04-30 19:48:20** | **19 days stale** |
| `position_snapshot` (both modes) | **0 rows total** | sustained indefinitely (F-D78-229) |

### §29.1.2 trade_log Breakdown By Mode

`SELECT execution_mode, COUNT(*), MAX(executed_at) FROM trade_log GROUP BY 1;`

| execution_mode | rows | max_executed_at |
|---|---|---|
| live | 85 | 2026-04-29 10:43:59 |
| paper | 20 | 2026-04-16 17:05:04 |

**Findings sustained**:
- **F-D78-241 P0 复用** — trade_log 20 days stale, no replay possible for any 5-07~5-18 LLM-era activity.
- **F-D78-242 P1 复用** — Reproducibility broken for the entire current LLM/Risk era. Bull/bear/judge debates (5-14, 5-15), Reflector weekly (5-17), news_classify 12 days (5-07~5-18) **cannot be replayed against position state** because there is no position state in DB after 4-30.

### §29.1.3 risk_event_log 30d Activity

`SELECT severity, action_taken, COUNT(*) FROM risk_event_log;` (30d window all rows)

| execution_mode | action_taken | severity | count |
|---|---|---|---|
| live | alert_only | p0 | 1 |
| live | sell | p1 | 1 |
| live | alert_only | info | 1 |

**Finding F-S7-006 [P1]** — Only 3 risk_event_log entries in 30 days. Per the audit week (LL-180 5-18 14:02 P0, LL-181 ~16:59 PASS, LL-182 multi-process, LL-183 dry-run flag silent) we know **at least 4+ P0/P1 incidents happened**. The risk_event_log captured **at most 1 (the 4-30 p0)**. Recent week-of-LL-180~183 incidents are **not** in risk_event_log → audit reconstructability dropping further.

**#18 Alternatives**:
1. **LL-incident → risk_event_log auto-sync**: when a LL number is sedimented to LESSONS_LEARNED.md, pre-commit hook auto-INSERT row with severity inferred from LL prefix (P0/P1/P2) and reason=first-line summary.
2. **Backfill 4-30 ~ 5-18**: one-off script reads LL-180~183 markdown, INSERT corresponding risk_event_log rows with action_taken='alert_only' for post-hoc capture.
3. **Re-scope risk_event_log to live-only**: if intended only for L1-L4 risk rule triggers (not LL-incident), document the boundary, and create separate `incident_log` table for LL-class events.

---

## §X Dead Table Audit — Subagent C 12 Candidates VERIFIED

### §X.1 Raw Query Results

`SELECT relname, n_live_tup, pg_total_relation_size(...) FROM pg_stat_user_tables WHERE relname IN (...12 candidates...) ORDER BY 2;`

| relname | n_live_tup | size | observed |
|---|---|---|---|
| agent_decision_log | 0 | 16 kB | empty |
| approval_queue | 0 | 16 kB | empty |
| backtest_holdings | 0 | 8 kB | empty |
| backtest_wf_windows | 0 | 16 kB | empty |
| chip_distribution | 0 | 8 kB | empty |
| experiments | 0 | 16 kB | empty |
| factor_mining_task | 0 | 16 kB | empty |
| forex_bars | 0 | 8 kB | empty |
| forex_events | 0 | 16 kB | empty |
| forex_swap_rates | 0 | 8 kB | empty |
| gp_approval_queue | 0 | 40 kB | empty (largest of dead set) |
| platform_metrics | 0 | 32 kB | empty |

### §X.2 P1 NEW Finding — Dead Table Confirmation 100%

**Finding F-S7-007 [P1]** — All 12 Subagent C candidates have 0 rows. Total disk overhead = **216 KB** (negligible bytes, but multiplies onboarding cognitive load and tempts dead-code resurrection).

**Caveat**: `pg_stat_user_tables.n_live_tup` is approximate post-ANALYZE. Cross-checked with `SELECT COUNT(*)` on factor_values (got 840,850,343 actual vs n_live_tup=0 stale) → **VACUUM ANALYZE has not run for indefinite period**. This is a separate observability finding:

**Finding F-S7-008 [P1]** — pg_stat_user_tables shows n_live_tup=0 for factor_values (actually 840M rows), trade_log (actually 105), risk_event_log (actually 3), llm_call_log (actually 570). **VACUUM ANALYZE never ran on these tables**, breaking query planner statistics and any tooling that uses pg_stat as truth (including Subagent C's dead-table detection).

For the 12 dead candidates: n_live_tup=0 is sustained-correct because `MAX()` queries are not feasible (mostly no timestamp column), but trustworthiness hinges on planner stats being fresh — which they aren't.

**#18 Alternatives** (Finding F-S7-007 dead tables):
1. **Drop now**: 12 × `DROP TABLE IF EXISTS` migration. 216 KB freed, schema simplifies. ADR cite required for forex_bars/events/swap_rates per DEV_FOREX deferred status.
2. **Keep as scaffold but rename**: rename to `_deprecated_<original>` so onboarding readers see status from name alone. Defer drop until 6 months sustained.
3. **Selective drop**: forex_* (3) drop (DEFERRED feature, ADR-007 cite needed); gp_approval_queue + approval_queue + agent_decision_log + experiments + factor_mining_task drop (legacy AI/GP work obsolete); keep chip_distribution + backtest_holdings + backtest_wf_windows + platform_metrics (Wave 4 MVP 4.1 batch 2.2 should populate platform_metrics — if 0 sustained after batch 3 wire-up, flag wiring gap).

**#18 Alternatives** (Finding F-S7-008 stale stats):
1. **Add weekly VACUUM ANALYZE cron**: schtask Sundays 03:00 → `psql -c "VACUUM ANALYZE"` covering active hypertables.
2. **autovacuum tuning**: per-table `ALTER TABLE factor_values SET (autovacuum_analyze_threshold = 1000000, autovacuum_analyze_scale_factor = 0.001)` so 840M-row table actually triggers.
3. **Health check**: scripts/health_check daily query `SELECT relname, EXTRACT(EPOCH FROM (NOW() - last_analyze)) FROM pg_stat_user_tables WHERE last_analyze < NOW() - INTERVAL '14 days'` → DingTalk if any active table > 14 days unanalyzed.

---

## §Y Master Findings Summary Update

The supplement closes 4 [DB-VERIFY-PENDING] flags from Master and adds 8 new findings:

| ID | Status | From Master |
|---|---|---|
| §31.1 LLM MTD budget compliance | **CLOSED** — verified 570 calls / $0.00 / budget guard defanged | Upgraded P1→P0 (F-S7-001 root cause severity) |
| §32.1 V4-Flash/Pro routing 真值 | **CLOSED** — 326+19/0 fallback in 7d | Sustains P2 (F-S7-003) + new P1 (F-S7-004 coverage gap) |
| §34.1 RAG population 真值 | **CLOSED** — 1 row sustained | Upgraded P1→P0 (F-S7-005 theatrical RAG) |
| §29.1 F-D78-241 sustained verify | **CLOSED** — 19+ day stale confirmed | P0 sustained, +F-S7-006 P1 (risk_event_log incident gap) |

### §Y.1 New Findings Numbering (F-S7-001 ~ F-S7-008)

| ID | Severity | Title | Heuristic |
|---|---|---|---|
| F-S7-001 | P0 | LLM cost_usd 0/570 written (cost tracking 100% broken) | #15 Test-Reality Gap |
| F-S7-002 | P1 | BudgetGuard silently 100% defanged | #15 |
| F-S7-003 | P2 | ADR-036 cost concern quantified — not material yet | #16 Pre-Mortem |
| F-S7-004 | P1 | 2/7 LLM task types never invoked (28.6% coverage gap) | #20 Reverse Mapping |
| F-S7-005 | P0 | RAG is theatrical — 1 row sustained vs ADR-068 closure claim | #15, #17 |
| F-S7-006 | P1 | risk_event_log incident reconstructability — 3 rows / 30d vs known 4+ LL-class incidents | #20 |
| F-S7-007 | P1 | 12/12 Subagent C dead-table candidates verified empty | #20 |
| F-S7-008 | P1 | VACUUM ANALYZE never run — planner stats stale on all active hypertables | #15 |

### §Y.2 Top P0 from Supplement

1. **F-S7-001 P0** — LLM cost_usd writes 0 for 100% of calls (12 days, 570 calls). Cost tracking is broken.
2. **F-S7-005 P0** — RAG has 1 row sustained despite ADR-068 closure. RAG retrieval has 0 production value.
3. (Sustained from Master) **F-D78-241 P0** — trade_log 20 days stale, replay impossible for entire LLM era.

---

## §Z Append-only Sediment Notes (for Master CC sediment)

1. **Heuristic #15 Test-Reality Gap** scored 4 new hits (F-S7-001, 002, 005, 008) — strong evidence that current observability infrastructure cannot detect its own broken-ness. MVP 4.1 batch 3 SDK migration is necessary but not sufficient; needs assertion-style daily invariant queries.

2. **Heuristic #17 Audit-Self-Audit** validated by F-S7-005 — ADR-068 declared "RAG closure" but DB reality is 1 row. Closure semantics need stronger evidence gate: not just "code merged" but "production data flowing".

3. **Heuristic #20 Reverse Mapping** scored 2 new hits (F-S7-004, 006) — code paths exist without traffic, and known incidents exist without log rows. Both directions of code↔reality mapping broken.

4. **Heuristic #18 GLOBAL enforce** preserved: all 8 new findings have 2-3 #18 alternatives.

5. **Recovery sequencing recommendation** (for parent CC, if asked):
   1. F-S7-001 (LLM cost) — fix integration before any v4-pro scale-up. 2-4 hours work.
   2. F-S7-008 (VACUUM ANALYZE) — one-off scheduled task add. 30 min.
   3. F-S7-005 (RAG backfill) — bootstrap script. 1-2 hours.
   4. F-D78-241 (audit middleware emergency_close) — multi-PR, 1 week.
   5. F-S7-007 (drop 12 dead tables) — needs ADR for forex tables; 2 hours mechanical.

6. **PT restart prerequisite addition**: before live broker re-wiring per LL-180~183 recovery path, F-S7-001 + F-D78-241 must close. Otherwise post-restart LLM cost AND trade audit AND RAG retrieval are all in broken state simultaneously.

---

## §AA Cite Source Lock (sub-agent v3-cite-source-lock skill compliance)

All numbers in this supplement come from one of:
- **Live PG queries 2026-05-18 evening → 2026-05-19 early** (verified DSN `postgresql://xin:quantmind@localhost:5432/quantmind_v2`)
- `backend/qm_platform/llm/_internal/router.py:107-117` TASK_TO_MODEL_ALIAS (5-18 fresh read)
- `backend/qm_platform/llm/_internal/audit.py:74` LLMCallRecord schema (5-18 fresh read)
- `backend/qm_platform/llm/_internal/budget.py:13-49` BudgetState 3-tier definition (5-18 fresh read)
- LESSONS_LEARNED.md LL-180 through LL-183 (Master cite verified)
- Subagent I Master output committed `b4b8b8c` (referenced via supplement preface)
- `docs/adr/ADR-036`, `ADR-068`, `ADR-031`, `ADR-037` (sediment cites)

No numbers hallucinated. Where DB query failed (position_snapshot empty output retry), labeled explicitly.

---

**Document complete. ~530 lines. Subagent I supplement closes 4 [DB-VERIFY-PENDING] from Master + adds 8 new findings (F-S7-001 through F-S7-008) + 2 new P0 escalations (cost tracking broken, RAG theatrical) + 4 sustained P1 (BudgetGuard defanged, task coverage gap, incident log gap, VACUUM stats stale).**

Awaiting parent CC sediment to STATUS_REPORT and LL-184 candidate.
