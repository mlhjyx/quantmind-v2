# Plan v8 Master Findings Register — 13 Doc × Findings × Closure Status (2026-05-19 evening)

> **触发**: User 5-19 ~20:00 SH 反向 challenge: "plan v8 产出了很多 doc, 一个个 doc 通读 + 一个个解决问题 / 建议. plan v8 不是审计完就结束, 出现的问题或更改方案需要探讨执行的".
>
> **本 doc 性质**: Plan v8 13 sediment doc 全 cold-read + 每 P0/P1/P2 finding × **当前 closure status** cross-reference + 5d 窗口期 autonomous action queue + user touchpoint queue.
>
> **范围**: MASTER + S1 + S2 (Inventory + Doc Status + Design Gap) + S3 + S4 + S5 + S6 + S7 + S9 + Frontend v3 + Revised v2 + Design Spec + Design Proposal = **13 doc + 3 HTML mockup** total ~4500 lines audit content + ~810 line frontend spec.
>
> **方法**: 每 finding 对照: (a) commit 历史 5-18 → 5-19 (是否已 close), (b) 当前 .env / schtask / Beat 真值, (c) 5d 窗口期 autonomous-可做 vs 必 user 触发 vs Phase B-2 后.
>
> **沿用 heuristic #17 Audit Self-Audit + #18 Alternative Path** — 反 plan v8 sediment-then-forget pattern (LL-187/LL-190 候选).

---

## §0 Executive Summary (Closure Status)

### §0.1 真值统计 (Master Top 50 + Cross-doc findings 综合)

| Category | Count | % |
|---|---|---|
| **✅ CLOSED since 5-18** | ~18 items | ~36% |
| **🟡 PARTIAL** | ~7 items | ~14% |
| **❌ OPEN P0/P1 (autonomous-actionable in 5d window)** | ~12 items | ~24% |
| **⏸ OPEN P0/P1 (user touchpoint OR multi-session)** | ~13 items | ~26% |
| **Total tracked findings** | ~50 items | 100% |

### §0.2 5d 窗口期 (5-19 evening → 5-26 Tue) autonomous CC 可close ~12 items

(See §3 for full list with cite)

### §0.3 User touchpoint queue (~13 items, 需 user 决议触发)

(See §4 for full list)

### §0.4 Plan v8 §VIII #26-30 5 suggestion status

| # | Suggestion | Status | This Session action |
|---|---|---|---|
| 26 | Decision Log (non-ADR fork rationale) | ❌ 0 traction | Phase B-2 后 sediment 候选 |
| 27 | Living Documentation (design + smoke test) | ❌ 0 traction | Phase J 候选 |
| 28 | Auto System Diagram (AST → mermaid) | ❌ 0 traction | Phase J 候选 (script 一次性) |
| 29 | Audit Cadence Calendar | ❌ 0 traction | **THIS Session sediment** (low cost) |
| 30 | Reverse Traceability Index (code↔doc) | ❌ 0 traction | Phase J 候选 (script 一次性) |

### §0.5 §3-bis Strategic Alternatives Alt A-E status

| Alt | Status | Trajectory |
|---|---|---|
| A (Harden current monolith) | ✅ Current trajectory | Path B + LL-188/189 + Memory cleanup + Frontend v3 W1-W6 |
| B (Split 3 services) | ❌ 0 follow-up | Phase J post Path B-2 评估 |
| C (Event-sourcing trade_log) | ❌ 0 follow-up | Phase J 评估 |
| D (QMT process pool) | ❌ 0 follow-up | Phase J 高价值候选 (LL-180/182 永久 fix) |
| E (Conservative defer) | ❌ rejected (Path B 选 active path) | — |

---

## §1 Closed Since 5-18 (~18 items, 真值 cross-cite)

### §1.1 From Master Top 24 P0

| Master # | Finding | Closure | Commit/PR |
|---|---|---|---|
| **P0-1** | .env LIVE_TRADING_DISABLED=false + EXECUTION_MODE=live drift | ✅ **REPAIRED via Path B Phase B-1** (5-19 19:13 SH) — `.env=paper/true` | Step1 script + ADR-085 |
| **P0-22** | Admin token in localStorage XSS-vulnerable | ✅ httpOnly cookie + CSRF | Session 57+1 round-2 `ae4b70d` + retroactive `0e26ac8` + `5a58ef0` |
| **P0-23** | No always-visible env banner UI | ✅ EnvStateBanner | Frontend v3 W1 Session 57+1 |
| **P0-13** | execute_phase has 0 API + 0 UI (LL-183 attack surface) | 🟡 **PARTIAL** — schtask gating sustained (Path B Phase B-1 Enable + 灰度 PT_TOP_N=5). 0 UI 仍然 gap | — |
| **P0-14** | env_flip is manual .env edit | 🟡 PARTIAL — step1/step2 scripts sediment (atomic backup + verify) | Session 58+1 `3323cd4` |
| **P0-7** | DataQualityCheck + RiskFrameworkHealth LastResult=1 today | ❓ **UNKNOWN** — need re-check post 5-18 evening | — |

### §1.2 From Master Top 26 P1

| Master # | Finding | Closure |
|---|---|---|
| P1-49 | L4 STAGED approve API but no UI | ✅ SafetyControlPanel (Frontend v3 W1) |
| P1-37 | DEV_FOREX 3 orphan tables | 🟡 PARTIAL — ADR-083 KEEP decision (`5a25d78`), forex_* sustain (DEFERRED feature) |
| P1-44 | FastAPI auth wide surface | 🟡 PARTIAL — S1 admin httpOnly cookie + S3 LLM rate-limit closed parts |
| P1-46 | Sprint state >90k tokens monolithic | 🟡 PARTIAL — L8 Memory archive 754→320KB |
| P1-48 | socket.io-client no server | 🟡 PARTIAL — ADR-084 sediment (real-time architecture decision, Phase 2 deferred) |

### §1.3 Session 58 round 1-6 closures (NOT in Master Top 50, surfaced during retroactive review)

| # | Finding | Closure commit |
|---|---|---|
| S1 | admin_token httpOnly cookie | `ae4b70d` |
| F1 | LLM cost forward-only (DeepSeek pricing fallback) | `23ebea5` |
| F3 | VACUUM schtask register | `15a7d93` |
| A4 | AgentConfig PUT no-op | `506a2cf` + `e5edae5` |
| A5/C4/H4 | Calendar wire (4 Beat tasks gated, is_trading_day_today_or_skip) | `df79ec4` |
| D1 | DB 4-28 stale | `b644ad1` |
| G1 | 8 DEV docs sync | `be0a6de` |
| H1 | Silent UI lie (RiskManagement hardcoded "LOW") | `b644ad1` + round-2 |
| L7 | v4-flash/pro alias | `b644ad1` |
| L8 | Memory archive | `15a7d93` |
| S3 | LLM rate-limit | `9ecd588` |
| C2 | Silent failure 4 `# silent_ok:` annotations | `9ecd588` |
| L1 | Bundle splitting | (pre-done vite.config.ts) |
| L2 | VITE_API_BASE_URL runtime | `9ecd588` |
| L3 | useWebSocket lifecycle | `9ecd588` |
| A3 | Notification partial 4→2 | `9ecd588` |
| P4 | SSE endpoint scaffold | `be00471` |
| P7 | Audit middleware | `be00471` |
| P2 | prompt_history | `506a2cf` |
| P3 | httpOnly cookie | `ae4b70d` |
| P8 | 12 dead tables | ADR-083 KEEP |
| P9 | LLM cache-hit fallback | `6d51a77` |
| H3 | AssistPanel dark launch | startup guard |
| L5 | Alias drift | INTENTIONAL (LEGACY) |
| L10/L11 | Dashboard duplication | INTENTIONAL (audit over-claim) |

### §1.4 Session 58+1 (today) closures

| Item | Closure |
|---|---|
| Memory leak (Celery worker 43.9GB) | ✅ +15.3GB recovered, task_default_queue config, LL-189 sediment |
| Orphan celery queue 288 messages | ✅ Flushed + root cause fix (task_default_queue) |
| LL-188 step 0 pre-commit hook | ✅ `9dea1cc` |
| Path B Phase B-1 launched | ✅ paper flip + schtask Enable + Day 0 STATUS_REPORT |
| Comprehensive unresolved audit | ✅ `3385bd8` |

---

## §2 Open P0/P1 (~25 items, by source doc)

### §2.1 Master Top 24 P0 — Still Open (18 items)

| # | Finding | 5d Window-Doable? | User Touchpoint? |
|---|---|---|---|
| P0-2 | PG password plaintext + 6 .bak leaks | 🟡 PARTIAL (CC can rotate password but needs Servy restart) | YES (rotate decision + .env edit) |
| P0-3 | pg_restore never tested 2026 | ✅ CC can schedule weekly Beat OR schtask | YES (decision: which schtask cadence) |
| P0-4 | Reflector → ThresholdEngine NOT wired | ❌ multi-day implement | YES (alt decision: auto wire vs human-in-loop weekly report) |
| P0-5 | Beat death no heartbeat (LL-181 sustained) | ✅ CC can wire qm:beat:heartbeat write + schtask probe (~2h) | NO (autonomous-doable) |
| P0-6 | Schtask freshness probe absent | ✅ CC can write `audit_schtask_freshness.py` (~2h) | NO (autonomous-doable) |
| P0-7 | DataQuality+RiskFrameworkHealth failing today | ✅ CC can re-check + diagnose root cause | NO (read-only diag autonomous) |
| P0-8 | Redis production data plane dark | 🟡 Path B Phase B-1 active 后可能复活 (qmt_data_service running) — verify on 5-20 Day 1 | NO |
| P0-9 | 30 service-layer commit() violations | ❌ 多文件 refactor, 高风险 | YES (architectural decision Alt 1/2/3) |
| P0-10 | 铁律 18 slippage quarterly 0 scheduler | ✅ CC can add Beat entry crontab(month=1,4,7,10) | NO (autonomous-doable, just add Beat entry) |
| P0-11 | Survivorship bias 12yr universe | ✅ **FALSE ALARM** (5-19 B3 audit verify, `docs/research/SURVIVORSHIP_BIAS_AUDIT_2026_05_19_final.md`) — factor_values + klines_daily + stock_status_daily 三层 sediment 含 5743 stocks (含 241/322 退市 / 12.1M ST 行 / 12.5 年 sediment), Subagent G 假设错. 残余 §3.1/§3.2/§3.3 留 5-yr backtest sample run | NO |
| P0-12 | 11 pytest collection errors | ✅ CC can quarantine (Alt 2) | NO (autonomous-doable) |
| P0-15 | 09:30 SH market open no watcher | ✅ CC can write script + schtask (~3h) | NO (autonomous) |
| P0-16 | No monthly LLM cost audit aggregator | ✅ CC can write script + Beat (~2h) | NO (autonomous-doable, Plan v8 #29 audit cadence subset) |
| P0-17 | HC-2c disaster drill pytest-only | ❌ production drill 复杂 | YES (decision) |
| P0-18 | RISK_CONTROL_SERVICE_DESIGN vs ADR-027 conflict | ✅ CC can sediment merge doc (~30min) | NO (autonomous doc edit) |
| P0-19 | Bus factor=1 + 0 onboard doc | ✅ CC can write ONBOARDING.md ~300 lines (~2h) | NO (autonomous) |
| P0-20 | Knowledge transfer 4/4 FAIL | 🟡 CC can write AUDIT_INDEX.md + USER_TRIBAL_KNOWLEDGE.md (~3h) | NO (autonomous) |
| P0-21 | Live trade reproducibility 4 sources stale | ❌ Phase J multi-week | YES (alt decision) |
| P0-24 | execution_service.py dry_run NameError risk | ✅ CC can verify + test (~30min) | NO (verify autonomous) |

### §2.2 Master P1 — Still Open (~12 items)

| # | Finding | 5d Window-Doable? |
|---|---|---|
| P1-25 | L4 _CANCEL_WINDOW hardcoded | ✅ yaml-driven refactor (~1h) |
| P1-26 | FundamentalContextService 1/8 维 | ❌ V3 §3.3 8 维 implement multi-week |
| P1-27 | Alpha158 45-factor gap | 🟡 (autonomous: --all-alpha158 flag) |
| P1-28 | AlertDispatcher buffered flush leak | ✅ CC can add DB persist (~2h) |
| P1-29 | LLM Router no failover | ✅ CC can add `completion_with_alias_override` auto-routing (~3h) |
| P1-30 | StreamBus publish_sync drift | ✅ CC can deprecation warning (~30min) |
| P1-31 | Loop 1 Signal 0 NAV feedback | ❌ Phase J |
| P1-32 | Loop 4 Regime → Signal disconnect | ❌ Phase J |
| P1-33 | SPF 6 no Tushare fallback chain | ❌ multi-week (Baostock/akshare backup) |
| P1-34 | Gates G1-G10 no closed-loop runner | ✅ CC can wire factor_gate.py to factor_onboarding.py (~2h) |
| P1-35 | risk-reflector-weekly stub input | ✅ CC can wire TB-4c real input (~3h) |
| P1-36 | Risk subservice cluster 0 API | ❌ 7 services × API design |
| P1-38 | DEV_AI_EVOLUTION Layer 3+4 0% impl | ❌ Phase J |
| P1-39 | paper_broker缺独立 design doc | ✅ CC sediment 3 spec doc (~3h) |
| P1-40 | DEV_PARAM_CONFIG 220 vs 50 | ✅ CC rewrite doc (~2h) |
| P1-41 | LL count drift 94 vs ~160 | ✅ CC can fix CLAUDE.md cite (~10min) |
| P1-42 | ADR count drift 022 vs 67 | ✅ CC can fix CLAUDE.md cite (~10min) |
| P1-43 | DingTalk HMAC outbound disabled | YES (user generate secret + .env edit) |
| P1-45 | Logs no rotation | ✅ CC add RotatingFileHandler (~2h) |
| P1-47 | Frontend dual chart libs ECharts+Recharts | ❌ Frontend Phase H/I multi-day |
| P1-50 | No Control Center / Cmd palette | ❌ DEFERRED (v2/v3 direction correction: embed in existing pages) |

### §2.3 Doc-specific findings 未在 Master Top 50 enumerate

**From S2 Design vs Reality Gap §1 (20 design docs)**:
- DEV_FOREX archive (Recommended (c)) — ✅ CC can move to docs/archive/ (~10min)
- DEV_PARAM_CONFIG rewrite (Recommended (c)) — ✅ CC can rewrite (~2h)
- RISK_CONTROL_SERVICE_DESIGN merge with ADR-027 (Recommended (d)) — ✅ same as P0-18

**From S2 Doc Status Matrix §3 (per-category recommendations)**:
- AUDIT_MASTER_INDEX needed for 122 audit files — ✅ CC can generate (~1h)

**From S4 §20 governance drift**:
- LL count drift (P1-41) + ADR count drift (P1-42) + research-kb count drift — ✅ CC fix (~15min)
- STATUS_REPORT 16d stale (per audit, but Session 58/58+1 已 sediment 多份, drift closed)

**From S6 §VIII 30 suggestions**:
- #1 Project Onboarding Doc MISSING — ✅ CC write (P0-19 alt 1, ~2h)
- #29 Audit Cadence Calendar — ✅ CC sediment (~30min, easy)
- #30 Reverse Traceability Index — script-based, ~3h

**From Frontend v3 §7 (15 NEW backend endpoints)**:
- Many already 已 done (e.g. `/api/system/env-state` exists, EnvStateBanner consumes)
- Frontend Phase H W7-W15 (P2 enhance + P3 cleanup) deferred 4-6 weeks

---

## §3 5d Window Autonomous Action Queue (~12 items)

**Priority ordering** (this Session + Day 1-5 incremental):

### §3.1 This Session (5-19 evening, ~1-1.5h remaining)

| # | Action | Effort | Cite |
|---|---|---|---|
| A1 | **LL-189 promote to LESSONS_LEARNED.md** (currently STATUS_REPORT only) | 30min | LL-187 sediment SOP 体例 |
| A2 | **LL-190 sediment** (plan v8 sediment-then-forget pattern) | 30min | UNRESOLVED_COMPREHENSIVE_AUDIT_2026_05_19 §6 |
| A3 | **ADR-086 promote** (Celery周期 restart + memory monitor + Servy limit hardening) | 30min | LL-189 sediment §5 hardening roadmap |
| A4 | **CLAUDE.md count drift fix** (ADR 022→67, LL 94→~160, research-kb 38→41) | 15min | P1-41/P1-42, S4 §20 |
| A5 | **PHASE_B_2_PREFLIGHT_CHECKLIST_2026_05_27.md sediment** (5-26 Tue gate evidence + 5-27 Wed live flip prep) | 30min | ADR-085 §2.1 Phase B-2 + Guardian §5 verdict "B-2 fresh re-gate" |
| A6 | **5d_PASS_GATE_CRITERIA + EARLY_ROLLBACK_DECISION_TREE sediment** | 30min | UNRESOLVED §1.1 C4+C5 |

**Sub-total this Session**: ~3 hours work (compressible by parallel sediment)

### §3.2 Day 1-5 incremental (5-20 → 5-26)

| # | Action | Day | Effort |
|---|---|---|---|
| A7 | DEV_FOREX archive (c) | Day 1 | 10min |
| A8 | DEV_PARAM_CONFIG rewrite (50 active + 30 candidate + 140 archived) | Day 1 | 2h |
| A9 | RISK_CONTROL_SERVICE_DESIGN merge with ADR-027 (P0-18) | Day 2 | 1h |
| A10 | ONBOARDING.md ≤300 lines (P0-19) | Day 2 | 2h |
| A11 | Audit Cadence Calendar doc (plan v8 #29) | Day 3 | 30min |
| A12 | AUDIT_MASTER_INDEX.md (122 files reverse-chrono summary) | Day 3 | 1h |
| A13 | USER_TRIBAL_KNOWLEDGE.md (P0-20) | Day 4 | 1.5h |
| A14 | Beat death heartbeat probe (P0-5 alt 1) | Day 4 | 2h |
| A15 | Schtask freshness probe script (P0-6 alt 1) | Day 4 | 2h |
| A16 | LLM cost monthly Beat (P0-16) | Day 5 | 2h |
| A17 | Slippage quarterly Beat (P0-10) | Day 5 | 1h |

**Sub-total Day 1-5**: ~16h, fits Phase B-1 observation period

---

## §4 User Touchpoint Queue (~13 items, 需 user 决议触发)

### §4.1 Critical (Phase B-2 5-27 Wed 前需决议)

| # | Item | Why critical |
|---|---|---|
| U1 | PG password rotate timing (P0-2) | Phase B-2 前 OR 后 |
| U2 | gp-weekly disable for 5d window? (Gap #3 from UNRESOLVED audit) | 5-24 Sun 22:00 ambush prevention |
| U3 | Phase B-2 5-27 Wed live flip "你执行" trigger 3 | Sustained ADR-027 §7 双 trigger 体例 |
| U4 | meta-monitor memory rule wire (C3 from UNRESOLVED) | ADR-086 subset implement now? |

### §4.2 Phase J Strategic (post Phase B-2 5-27 Wed live restart)

| # | Item | Cite |
|---|---|---|
| U5 | B1 WF Sharpe heterogeneity audit (0.86 WF vs 0.36 12yr 2.4×) | S1 §1.3 + S6 §25 |
| U6 | B2 backup strategy (single Alpha SPOF) | S6 §25 |
| U7 | B3 Survivorship bias audit (P0-11) | S1 §1.4 + S7 §37 |
| U8 | B4 Slippage 季度复核 (铁律 18 violation, P0-10) | S7 §38 |
| U9 | C1 LL-182 long-run verify post Phase B-2 | LL-182 sediment |
| U10 | C3 sim-to-real gap verify (4-29 incident OOS) | S7 §37 / ADR-028 §2.4 |
| U11 | D2 Backtest replay 12yr (V3 §15.5) | ADR-028 §2.4 |

### §4.3 Plan v8 §9.3 14 Open Q (long-term, post Phase J)

(See plan v8 quizzical-snacking-fox.md §9.3 for full list)

---

## §5 13 Doc Per-Doc Top Findings Summary (一个个 doc)

> **目的**: User 显式 "一个个 doc 通读 + 解决问题". 本节是真 per-doc 通读 sediment.

### §5.1 MASTER (`V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`, 686 lines)

- **Top 5 P0**: P0-1 (.env drift) ✅ + P0-2 (PG pwd) ❌ + P0-3 (pg_restore) ❌ + P0-4 (Reflector wire) ❌ + P0-5 (Beat heartbeat) ❌
- **Strategic Alt**: Alt A (current trajectory) + Alt D (QMT process pool) hybrid 推荐 (Phase J 候选)
- **Cross-layer 12 cascade**: SPF 4 Beat death 8-hop = longest, P0-5/P0-6 first 2 P0s
- **5 LL candidate**: LL-184/185/186 ✅ all referenced in subsequent Session work (LL-187/188/189 sediment chain)

### §5.2 S1 Domain (`V3_AUDIT_S1_DOMAIN.md`, 101 lines)

- **5 findings**: dv_ttm warning 30+ days unmanaged (P1, 仍 sustained) + single-strategy concentration (P1) + A股 T+1/集合竞价 enforcement MISSING (P1) + OOS heterogeneity underdisclosed (P2) + Capacity scaling impact (P2)
- **All 5 OPEN**, Phase J 候选 multi-week research

### §5.3 S2 Inventory (`V3_AUDIT_S2_INVENTORY.md`, 305 lines)

- **Phase 0 baseline drift**: subagent A recursive count vs CC top-level verify (drift -50% to -64%)
- **132 endpoints / 17 task modules / 32 Beat entries / 19 schtask** (Phase 0 said 121 / 11 / 15+ / 14, all +drift)
- **Redis dark 0 qm:* keys** (P0-8, may resolved post Path B-1)
- **5 hardcoded values in beat_schedule.py** (symbol_id="600519" × 2, route_path × 1 — P1 sustained)

### §5.4 S2 Doc Status Matrix (`V3_AUDIT_S2_DOC_STATUS_MATRIX.md`, 98 lines)

- **165 docs total**: 9 DEV (1 ✅ / 6 🟡 / 1 ⏸ / 1 ⚪) + 23 MVP (19 ✅) + 67 ADR (63 ✅) + 14 V3 + ...
- **Count drift 4 items** (ADR 67 vs CLAUDE.md "022", LL ~160 vs memory 94, research-kb 41 vs cite 38, framework 15 vs "12+6")
- **Disposition recommendations** 5 groups (Implement now / Revisit Q3-Q4 / Archive / Merge / Audit chain follow-up)

### §5.5 S2 Design vs Reality Gap (`V3_AUDIT_S2_DESIGN_VS_REALITY_GAP.md`, 121 lines)

- **20 priority design docs × IMPL %**: lowest = DEV_FOREX 0% (P1-37) / DEV_PARAM_CONFIG 25% / DEV_AI_EVOLUTION 25% / DEV_SCHEDULER 25%
- **Top 10 findings**: P0-18 (RISK_CONTROL_SERVICE conflict) + P1-37/38/39/40 + P2 各
- **Heuristic #20 backward Code Orphan**: paper_broker / base_broker / signal_router 缺独立 design doc (P1-39)

### §5.6 S3 Flow + Closure (`V3_AUDIT_S3_FLOW_AND_CLOSURE.md`, 303 lines)

- **6+ business flow text-diagram** (Data / Signal / Trade / Risk / Factor / Recon / News / Reflector)
- **5 of 7 closed-loops broken** (Loop 1/2/4/6/7) ← strategic finding
- **9 SPF cascade map** (SPF 4 Beat death 8-hop longest, SPF 8 .env unrolled 3-hop CRITICAL — REPAIRED via Path B)
- **16 broken-links** sediment across flows

### §5.7 S4 Health + Dead Code (`V3_AUDIT_S4_HEALTH_AND_DEAD_CODE.md`, 287 lines)

- **铁律 32 (Service 不 commit) 30 violations across 10 files** (P0-9) ← code architecture finding
- **11 dead tables** (ADR-083 KEEP 决议)
- **9 orphan Celery tasks** (last fire 4-07 to 4-30, 40d+ DEAD)
- **2 orphan schtask** (sentinel 1999-11-30, P1)
- **Top 5 log files > 4MB, no rotation** (P1-45)
- **Sprint state 768KB super Read limit** (P1-46, L8 archive partial)

### §5.8 S5 Frontend Redesign Proposal (`V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md`, 220 lines)

- ⚠️ **DEPRECATED per user feedback 5-19** ("偏离我的设计, 不要 12 页 from-scratch")
- Canonical: Frontend v3 (sister doc)

### §5.9 S6 Strategic + Continuity (`V3_AUDIT_S6_STRATEGIC_AND_CONTINUITY.md`, 151 lines)

- **8 SPF sediment**: 单 user (bus factor=1) / 单 strategy / 单 machine / 单 ISP / 单 broker / 单 Tushare / 单 LLM / 单 DingTalk
- **Process maturity L1 Reactive** (avg) — gap to L2 Proactive
- **30 suggestions status**: ~17 MISSING / ~7 PARTIAL / ~6 STRONG
- **Plan v8 #26-30 (NEW v8) ALL MISSING** (sediment-then-forget pattern, LL-190 候选 root cause)

### §5.10 S7 ML/Cost/HW (`V3_AUDIT_S7_ML_COST_HARDWARE.md`, 280 lines)

- **§31-35 ML/AI**: LLM cost (P0-16 monthly aggregator missing) + V4 routing (ADR-036 cost risk) + Prompt v2 not sediment (P1) + RAG memory population unknown + V4→V5 fallback chain 2-hop not 3-hop (P2)
- **§36-40 HW/Cost**: capacity scaling ¥10M-30M ceiling estimate / Survivorship bias (P0-11) / Slippage quarterly 0 scheduler (P0-10) / Calendar SSOT good (25 callers) / Daily critical path 22GB used / 31GB peak

### §5.11 S9 UX/Control Plane (`V3_AUDIT_S9_UX_CONTROL_PLANE.md`, 174 lines)

- **32 ops matrix**: 14 (44%) have both API+UI / 5 have API no UI / 13 (41%) have NEITHER
- **Control Center 单页 deprecated per v2/v3** — instead embed in existing pages
- **4 safety tiers** (LOW/MED/HIGH/CRIT 三锁) — ConfirmModal 4-tier ✅ implemented in Frontend v3 W1
- **AI Boundary**: CRIT ops NEVER LLM-triggered (execute / env_flip / emergency_close / pause_trading / L4 force-reset)

### §5.12 Frontend v3 (`V3_AUDIT_FRONTEND_DESIGN_v3.md`, 410 lines)

- **canonical Phase H plan**: 14500 LOC baseline / 10 高频页 P0+P1 / 5 new components / 15 backend endpoints / ~154h / 4-6 weeks
- **Status**: W1-W6 ✅ 已 close (LL-187 sediment), W7+ deferred multi-session
- **5 NEW components**: EnvStateBanner ✅ + ShutdownBanner ✅ + SafetyControlPanel ✅ + ConfirmModal 4-tier ✅ + AssistPanel ✅
- **AI Boundary 4 entry points wired** ✅

### §5.13 Frontend Revised v2 (`V3_AUDIT_FRONTEND_DESIGN_REVISED_v2.md`, 206 lines)

- Direction correction from v1: "现有 35 pages incremental refactor + AI 辅助 panel"
- A/B/C HTML mockup retained as exploratory artifact (not canonical)
- Phase H REVISED 4-6 weeks roadmap (sustained in v3)

---

## §6 Action Plan This Session (autonomous, no user trigger needed)

### §6.1 Sediment 6 docs (~2.5h)

1. ✅ This master register (this file)
2. Promote LL-189 to LESSONS_LEARNED.md (worker leak + orphan queue)
3. Sediment LL-190 (plan v8 sediment-then-forget pattern)
4. Promote ADR-086 (Celery周期 restart + memory monitor + Servy limit)
5. PHASE_B_2_PREFLIGHT_CHECKLIST_2026_05_27.md
6. 5d_PASS_GATE_CRITERIA + EARLY_ROLLBACK_DECISION_TREE

### §6.2 Doc edits (~30min)

7. CLAUDE.md ADR count drift fix (022 → 67)
8. CLAUDE.md LL count fix (drift 94 → ~160 + plan v8 sediment 184/185/186/187/188/189/190)
9. CLAUDE.md research-kb count fix (38 → 41)

### §6.3 Commit batch (~5 commits)

Single ATOMIC commit per concern (沿用 铁律 42 docs/** 直 push 体例):
- Commit 1: master register (this file)
- Commit 2: LL-189 + LL-190 promote (LESSONS_LEARNED.md edit)
- Commit 3: ADR-086 promote + REGISTRY.md update
- Commit 4: PHASE_B_2 preflight + 5d gate criteria + rollback tree (3 new docs)
- Commit 5: CLAUDE.md count drift fix

---

## §7 Surface Plan (post §6 batch closure)

### §7.1 User decision queue priorities

1. **U4 meta-monitor memory rule wire**: 5d window 期内 active recommend
2. **U2 gp-weekly disable 5d 期**: 5-24 Sun 22:00 ambush prevention
3. **U1 PG password rotate**: Phase B-2 前 OR 后?
4. **U3 Phase B-2 "你执行" trigger 3**: 5-27 Wed 时点决议

### §7.2 Phase J 7 research items priority recommendation

CC 推荐 priority (post Phase B-2 5-27 Wed):
1. **U7 B3 Survivorship bias** (高 leverage, 短期 ~1-2 week, 真值 Sharpe confidence anchor)
2. **U10 C3 sim-to-real gap verify** (高 leverage, ~2 week, sediment LL-188/189 跨域 lesson)
3. **U5 B1 WF Sharpe heterogeneity** (decision-driving, ~2 week)
4. **U8 B4 Slippage 季度复核** (铁律 18 enforce, ~1 week)
5. **U9 C1 LL-182 long-run verify** (Phase B-2 自然 sustained, 5-10d post-restart)
6. **U6 B2 Backup strategy** (multi-month research, post all above)
7. **U11 D2 Backtest replay 12yr** (long-term, ADR-028 §2.4 prerequisite)

### §7.3 Plan v8 §VIII #26-30 sediment timing

- #29 Audit Cadence Calendar — **Day 3 of 5d window** (autonomous-doable)
- #26 Decision Log — Phase B-2 后 sediment
- #27 Living Documentation — Phase J 候选
- #28 Auto System Diagram — Phase J 候选 (script-based)
- #30 Reverse Traceability Index — Phase J 候选 (script-based)

---

## §8 Honest meta-finding (sustained LL-190 candidate)

**Session 58+1 task user 5-19 ~20:00 SH challenge "一个个 doc 通读 + 解决问题" 暴露 plan v8 sediment-then-forget pattern**:

- Plan v8 5-18 evening 沉淀 11 docs + 3 HTML mockup (~5000 lines audit)
- Frontend v3 W1-W6 closed (LL-187 sediment)
- Session 58 round 1-6 closed ~25 sub-items
- Session 58+1 today: Memory cleanup + Path B Phase B-1

**BUT — 我从 5-18 → 今 全程 reactive (issue → fix → next), 缺**:
- 每 P0/P1 systematic "alternative path thinking" (heuristic #18 GLOBAL)
- §VIII 30 suggestions #26-30 5/30 (NEW v8) 全 dormant
- §3-bis Strategic Alt A-E 0 follow-up
- Phase 4-bis-C user touchpoint frontend mockup 选择 0 triggered
- 5d window 期内 hardening (ADR-086 subset) 未 wire
- Phase B-2 fresh re-gate prereq 未 sediment

**Root cause**: 我把 plan v8 看作 "sediment complete = audit framework active". 反 §VII heuristic #17 "Audit Self-Audit + Cadence" 自己 first failure. Plan v8 sediment 后**需 enforcement mechanism** (schtask / Beat / DingTalk reminder), 单 sediment 不够.

**LL-190 候选 sediment** (this session):
"Plan v8 audit sediment alone ≠ sustained audit enforcement. each plan v8 sediment + corresponding **enforcement schtask / Beat rule / DingTalk reminder / audit cadence calendar tick**."

---

## §9 关联

- Plan v8 (`C:\Users\hd\.claude\plans\quizzical-snacking-fox.md`) framework
- LL-184/185/186 candidates (plan v8 sediment cycle)
- LL-187 (Frontend v3 W1-W6 sediment-then-forget pattern parent)
- LL-188 (sediment drift forensic)
- LL-189 (worker leak + orphan queue, today)
- LL-190 候选 (本 doc surface)
- ADR-027 (L4 STAGED + 反向决策权)
- ADR-028 (AUTO + V4-Pro X + RAG + backtest replay)
- ADR-083 (dead table KEEP)
- ADR-084 (real-time architecture)
- ADR-085 (Path B Phase B-1 launched)
- ADR-086 候选 (Celery 周期 restart + monitor)
- UNRESOLVED_COMPREHENSIVE_AUDIT_2026_05_19_session_58_plus_1.md
- PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19.md
- STATUS_REPORT 2026-05-19 memory_cleanup + pt_paper_dryrun_day0

---

**End Master Findings Register. 50+ findings tracked × 4 closure states × 5d autonomous action queue × user touchpoint queue × Phase J priority. Awaiting user 决议 on §4 critical items OR autonomous 接力 in this Session per §6.**
