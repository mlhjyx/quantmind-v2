# Comprehensive Unresolved Items Audit — Session 58 / 58+1 Retrospective (2026-05-19 evening)

> **触发**: User 5-19 ~19:35 SH 反向 challenge: "plan v8 设计时要求**主动思考** + 更好方案 + 建议, 你 Session 58 / 58+1 全程 reactive, 没做 audit-style 全局思考. 脑补我说的, 真去想."
>
> **本 doc 性质**: Session 58 + 58+1 **真 retrospective** + 主动 audit gap surfacing. 反 LL-187 pattern (W1-W6 ✅ 后未系统 audit W7-W15) 跨域 recurrence.
>
> **范围**: Plan v8 (quizzical-snacking-fox.md) 11 sediment docs + CC_ACTIONS_FOR_USER §1-§4 + ISSUES_PENDING_REGISTRY 41 items + Session 58 round 1-6 + Session 58+1 PT restart + memory cleanup, **全局 unresolved 30+ items**, 主动延伸 5-10 我没想到的 P0/P1 gaps.
>
> **Heuristic enforce 沿用 plan v8 §VII**: #18 Alternative Path (每 P0/P1 ≥ 2 alt) / #16 Pre-Mortem / #17 Audit Self-Audit / #20 Design-Implementation Reverse Mapping.

---

## §0 TL;DR (真 meta-finding)

**Session 58 / 58+1 work was tactically successful but strategically incomplete**:
- ✅ 18 commits cumulative since 5-15 cutover
- ✅ Memory cleanup (+15.3 GB recovered)
- ✅ Path B Phase B-1 launched
- ✅ Multiple ADRs sedimented (085 + 086 candidate)
- ❌ **plan v8 §IX `Alternative Solutions Synthesis Pass` 实质未应用 to Session 58 work** — 每 P0/P1 finding 应 ≥2 alt remediation, 实际 mostly single-fix
- ❌ **Plan v8 §VIII 30 suggestions 中 5 项 (#26-#30) 完全 0 trigger** — Decision Log / Living Doc / Auto Diagram / Audit Cadence / Reverse Trace
- ❌ **Section IX/X/XI 的 cross-cutting issues 0 后续 traction** — LL-186 sediment 完成后 audit 出的 strategic findings 几乎 dormant
- ❌ **Frontend Design Spec v3 doc + 3 mockup HTML 完成后 0 user touchpoint** — 14 open Q + Phase H W7-W15 未启动

**这是 reactive vs proactive 的真讽刺 — plan v8 第 §VII heuristic #18 是为防止"单解 bias", 我自己 Session 58+1 全程犯了**.

---

## §1 Unresolved Items 全局清单 (30 items)

### §1.1 CRITICAL — 5d window (5-20 Wed → 5-26 Tue) 期内可能引爆

| # | Item | Severity | Current state | Why critical |
|---|---|---|---|---|
| **C1** | Cron session-only, 5d 自动 wake 不可靠 | P0 | CronCreate `83e3c350` in-memory only, durable=true 被忽略 | 若 CC 终端晚上关 → 明早 Day 1 sediment fail → 5d cadence 断 |
| **C2** | LL-189 worker leak 可能 recur in 5d window | P0 | Worker fresh PID 37836, 0 leak data, 但 5-22 Fri 19:00 factor-lifecycle Beat + 5-24 Sun 22:00 gp-weekly mining (2h budget) 两个 heavy task fire 在 window 内 | gp-weekly mining 是 typical leak trigger (population=100, generations=50, factor_calc 大量 pandas), 24h+ 累积可能再撑爆 worker before 5-26 gate |
| **C3** | Meta-monitor memory rule 未 wire (ADR-086 sediment 但 0 implement) | P1 | Beat 22 entries 全 fire, 但 meta_monitor_tick 仅检 7 rules, NOT 含 memory | 5d window 内若 worker leak 再爆 → 无元告警 trigger → 用户/CC 又得手动 catch |
| **C4** | 5d "PASS" 阈值定义模糊 | P1 | observation_template 10-dim checklist 列出, 但"PASS"标准 0 显式 | Day 3 单 outage / 单 P1 fire 算 PASS 还是 FAIL? 5-26 Tue gate 决策时 ambiguous |
| **C5** | 早 rollback criteria 0 sediment | P1 | "anytime rollback" cmds 列出, 但 trigger 条件 (e.g. Day 2 LLM cost > $X / Day 3 Beat fire 率 < 80% / 等) 0 sediment | 决议 contingent 留 user 临时判断, 反 plan v8 §VIII #29 audit cadence calendar 体例 |
| **C6** | gp-weekly Sun 22:00 与 5d 观察 collision | P1 | gp-weekly 周日 22:00 fire (5-24 Sun), 2h budget, population=100, generations=50, factor_calc 重 | 5d 期内最大 memory spike trigger source, 必 anticipate OR temp disable gp-weekly during 5d |

### §1.2 HIGH — 应在 5-27 Wed Phase B-2 trigger 3 前 closed

| # | Item | Severity | Current state | Plan v8 reference |
|---|---|---|---|---|
| H1 | PT_START_DATE .env audit | P1 | CC_ACTIONS §3.1 sediment, 0 verify | Section X §39 calendar SSOT |
| H2 | Phase B-2 fresh re-gate prerequisite | P1 | Redline guardian §5 verdict "B-2 needs fresh re-gate", 0 sediment script (vs step1 has DryRun mode) | 沿用 ADR-085 §2.1 Phase B-2 |
| H3 | Slippage 季度复核 (铁律 18 violation) | P1 | CC_ACTIONS §2.4 sediment, "last execution time unknown" — actually a 铁律 18 violation | Section X §38 |
| H4 | Survivorship bias audit (CC_ACTIONS §2.3) | P1 | 0 verify, 0.86 WF vs 0.36 12yr 2.4× heterogeneity unexplained | Section X §37 |
| H5 | LL-189 promote to LESSONS_LEARNED.md | P2 | 仅 STATUS_REPORT sediment, NOT LL entry | 沿用 LL-184/185/186 plan v8 cadence |
| H6 | ADR-086 promote (周期 restart schtask + monitor + Servy limit) | P2 | ADR-086 sediment as candidate, 0 promote | Plan v8 §IX §1 Section III §10 |
| H7 | 5d observation 自动化 script (vs 手动 verify) | P2 | observation_template 列出 cmds, 0 wrapper script | Heuristic #18 alternative |

### §1.3 MEDIUM — Plan v8 §VIII suggestions #26-#30 全 0 trigger

| # | Item | Plan v8 reference | Current state | Effort estimate |
|---|---|---|---|---|
| M1 | **#26 Decision Log** (non-ADR fork rationale) | §VIII #26 | 0 file 创建 | ~30min initial + per-decision cite |
| M2 | **#27 Living Documentation** (design doc smoke test auto-align) | §VIII #27 | 0 wired | ~4-6h (CI integration) |
| M3 | **#28 Auto-Generated System Diagram** (AST → graphviz) | §VIII #28 | 0 wired | ~6-8h (Python AST tooling) |
| M4 | **#29 Audit Cadence Calendar** (event-driven + quarterly + tech debt) | §VIII #29 | 0 schtask / 0 cron, sediment only in plan v8 | ~1h schtask + ~30min cadence sediment |
| M5 | **#30 Reverse Traceability Index** (code ↔ design 50 module bidirectional) | §VIII #30 + Heuristic #20 | 0 doc 创建, plan v8 §IV deliverable 13 list 但 file 0 | ~4-6h (50 module audit) |

### §1.4 STRATEGIC RESEARCH — Phase J 7 items (multi-week, ADR-085 §3.4 unblocked after Phase B-2)

| # | Item | Plan v8 reference | Why strategic |
|---|---|---|---|
| S1 | B1 WF Sharpe heterogeneity (2.4× 0.86 vs 0.36) | Section X §37 | 真 alpha confidence 取决于这 |
| S2 | B2 Backup strategy (single Alpha SPOF) | Section VI §25 + Section IX §32 | LL-185 finding sediment 后 0 行动 |
| S3 | B3 Survivorship bias audit | Section X §37 | 铁律 7 (universe alignment) potential violation |
| S4 | B4 Slippage 季度复核 | Section X §38 | 铁律 18 violation (last exec unknown) |
| S5 | C1 LL-182 long-run verify (PT restart 后 5-10d) | LL-182 sediment | Path B-2 后 sustained verify |
| S6 | C3 sim-to-real gap verify (4-29 incident 不在 fold) | Section IX §34 | LL-188 forensic 衍生 |
| S7 | D2 Backtest replay 12yr (V3 §15.5) | ADR-028 §2.4 | 长期 RAG / AUTO prerequisite |

### §1.5 LONG-TERM — Plan v8 §9.3 14 Open Questions (user 决议 blocks)

| # | Open Q | Current state |
|---|---|---|
| L1 | Frontend stack (React 18 vs SvelteKit/Vue 3/Solid) | 0 决议, sediment in plan v8 |
| L2 | Frontend hosting (local dev vs Servy persistent) | 0 决议 |
| L3 | Mobile support level | 0 决议 |
| L4 | Auth model upgrade (ADMIN_TOKEN → OAuth/RBAC) | 0 决议 |
| L5 | Real-time updates (now superseded ADR-084 hybrid) | partial — Phase 1 done |
| L6 | AI-assisted ops boundary (NLP cancel order? threshold change?) | 0 决议 |
| L7-L14 | ... (full list in plan v8 §9.3) | 0 决议 |

---

## §2 我主动 surface 的额外 5 个 gaps (脑补 — plan v8 没明列但应有)

### §2.1 Gap #1 — **5d window 期 Beat 22 entries 真消费率 0 track**

**Description**: Beat 22 entries cron fire 时间已 sediment, 但**真 dispatch + 真 worker pick up + 真 complete** 三 stage 都 0 metric. 每个 stage 之间任一环 fail (network / Redis / 序列化 / 等) → silent drop.

**Why care**: meta-monitor-tick 检 alert-on-alert 但**不检 self heartbeat — Beat 自身 fire 率**. 即 meta-monitor 自己 fail 也不知道.

**Alt remediation** (heuristic #18):
- A) Add `celery inspect active` + `celery inspect scheduled` query to Day 1+ sediment
- B) Wire dedicated Beat heartbeat self-check rule in meta_monitor (recursive but bounded)
- C) Track Redis Stream `qm:celery:beat:tick` event publish (沿用 ADR-003 StreamBus)

**Recommend**: A (lowest effort, sufficient for 5d window). B for long-term.

### §2.2 Gap #2 — **CronCreate session-only is exactly the LL-187 sediment pattern**

**Description**: Phase H Frontend W1-W6 sediment 跟 Session 58+1 cron Day 1 wake 体例同 — 都是 "sediment done assumption" 跨 session 不 sustained. 真 5d 全自动 cadence 需 OS-level persistence (Windows Task Scheduler), NOT CC-internal cron.

**Why care**: 5d 中任一晚 CC 终端关闭 → 跨 day cadence 断 → 用户必手动 catch up. 反"全自动" sediment claim.

**Alt remediation** (heuristic #18):
- A) Create Windows schtask `QuantMind_PT_Paper_Day_N_Sediment_Wakeup` 触发 PowerShell call to local script + write STATUS_REPORT skeleton, user 接力 sediment via CC
- B) Add automated `scripts/pt_paper_observe_day.py --day=N` script that runs without CC, writes STATUS_REPORT raw, user opens CC to review/commit
- C) Use Windows Task Scheduler to send DingTalk reminder daily 10:07 SH, user manually triggers CC

**Recommend**: B + C hybrid (script does 95% work, user just triggers commit + review on phone via DingTalk).

### §2.3 Gap #3 — **GP-weekly mining 5-24 Sun 22:00 = leak 重演 ambush**

**Description**: GP mining task fire 周日 22:00 with 2h budget, population=100, generations=50, factor_calc heavy pandas — exactly the leak pattern 5-18 → 5-19 24h accumulation root cause.

**Why care**: 5d window 内最 likely OOM recurrence trigger. Day 5 (5-26 Tue) gate decision 时 worker memory 累积 24-30h 已含 gp-weekly fire — could derail PASS threshold.

**Alt remediation** (heuristic #18):
- A) Temp disable gp-weekly Beat entry for 5d window (edit beat_schedule.py temp comment, restart Beat). Risk: cuts GP factor mining 1 week, low strategic cost.
- B) Pre-restart worker 5-24 Sun 23:30 SH (post gp-weekly fire) via schtask. Risk: 不 hardening, just delay.
- C) Add hard `worker_concurrency` cap + dedicated gp_mining_worker process (split queue). Risk: 1d effort, mid-window architecture change risky.

**Recommend**: A — temp disable gp-weekly during 5d (1 sprint of GP miss is acceptable trade-off vs 5d gate confidence).

### §2.4 Gap #4 — **Phase B-2 5-27 Wed flip 0 pre-flight checklist sediment**

**Description**: ADR-085 §2.1 Phase B-2 sequence 列出, step2.ps1 DryRun fail-fast verified, 但 PRE-flip 5d gate evaluation 真 checklist (10-dim PASS threshold + rollback decision tree + first-fire live execute monitor protocol) 0 single source sediment.

**Why care**: 5-26 Tue evening gate evaluation 时, CC + user 需 single source 真 evidence cite. Currently scattered (observation_template + ADR-085 §3.4 + STATUS_REPORT Day 5).

**Alt remediation**:
- A) Create `docs/audit/PHASE_B_2_PREFLIGHT_CHECKLIST.md` ahead of time (5-19 evening Today)
- B) Use existing observation_template Day 5 instance as gate evidence
- C) Spawn redline-guardian subagent 5-27 Wed morning before flip (fresh re-gate per Guardian §5)

**Recommend**: A + C (sediment now + fresh guardian on flip day).

### §2.5 Gap #5 — **Plan v8 §VIII #29 Audit Cadence Calendar 应在 Session 58+1 实施**

**Description**: Plan v8 §VIII #29 提"event-driven (post-LL incident) + quarterly + pre-cutover gate + tech debt threshold" 4 audit trigger conditions calendar. LL-188 + LL-189 + Path B Phase B-2 cutover 都是 cadence trigger event. 沉淀但 0 schtask / 0 cron / 0 reminder.

**Why care**: Plan v8 整套 audit framework 自检 cadence (heuristic #17 Audit Self-Audit) 应该有自己的 enforcement. 没 enforcement = sediment 后 drift, 跟我现在 sessoin 58+1 reactive 模式同 root cause.

**Alt remediation**:
- A) Create Windows schtask `QuantMind_AuditCadenceTick` quarterly 1st Mon 03:00 SH + 触发 STATUS_REPORT skeleton
- B) Add Beat entry `audit-cadence-quarterly` Celery sched + DingTalk reminder
- C) Just sediment `docs/runbook/audit_cadence_calendar.md` + manual ticker

**Recommend**: C now (low cost) + A/B Phase J candidate.

---

## §3 Strategic Alternatives (plan v8 §3-bis style, 重 surface)

**Plan v8 Phase 3-bis 写了 5 "if redesign from scratch" alternatives Alt A-E. 现在 5-19 evening, 5d 窗口启动后, 应重审这些 alternatives 是否仍然 hold OR 已偏离 trajectory.**

### Alt A (continue monolith + harden) — **current trajectory**
- 5d paper-mode dry-run + Phase B-2 live flip + LL-189 hardening (ADR-086)
- Pro: incremental risk, single Servy stack
- Con: SPOF, single strategy continues, 不 scale 10x

### Alt B (split into 3 services: PT-engine / risk-engine / data-engine)
- Sediment in plan v8, 0 traction Session 58/58+1
- Pro: SPOF mitigation, scale-out path
- Con: 2-3 month effort, 跨多 sprint

### Alt C (move to event-sourcing for trade_log)
- Sediment in plan v8, 0 traction
- Pro: ADR-003 StreamBus extension natural fit, audit immutability
- Con: schema redesign, replayability complex

### Alt D (rewrite QMT integration as separate process pool)
- Sediment in plan v8, 0 traction
- Pro: isolation from broker outage, retry policy explicit
- Con: 2-3 week effort, 修改 broker_qmt + paper adapter

### Alt E (event-driven STAGED flow + reverse decision rights)
- ADR-027 covers partial (STAGED), AUTO ADR-028 covers full
- Sediment in plan v8, sustained progress 50% (STAGED design 10/10 ✅, implement 0%)
- Pro: V3 §20.1 设计层 10/10 ✅, Sprint M ready
- Con: Sprint M effort 4-6 sprints out

**Strategic recommendation post-Session 58+1**:
- **5d window now → Phase B-2 5-27 Wed 实施 path B sustained = Alt A 体例**
- **Phase B-2 后 (5-27+)**: 启动 Phase J 7 items + 选 1 alt B/C/D pilot
- **Sprint M+ (Q3 2026)**: ADR-028 AUTO + RAG ramp

---

## §4 Reactive vs Proactive 真 audit (heuristic #17)

### §4.1 Session 58 / 58+1 真值 work distribution

| 类型 | Commits | Pattern |
|---|---|---|
| **Reactive fix** (issue raised → fix → commit) | 11 (LL-188 + S3 + L1/L2/L3 + A3 + C2 + F-S7 + Servy + cron block defuse) | majority |
| **Discovery-driven sediment** (audit issue 自发 surface) | 5 (LL-188 + LL-189 + Frontend v3 W1-W6 + ADR-084 + Memory cleanup) | partial |
| **Proactive plan v8 follow-through** | 3 (Path B brief + ADR-085 + 5d observation template) | minor |
| **Plan v8 §VIII 5-30 suggestion implement** | **0** | gap |
| **Phase 3-bis Strategic Alt Sherpa pass** | **0** | gap |

### §4.2 LL-187 vs Session 58+1 pattern correlation

LL-187 (Frontend v3 W1-W6 ✅) said: "W1-W6 closed, W7-W15 还在 audit doc. 后续 Session 接力 W7-W15 systematic audit."

Session 58 + 58+1 实际: W7-W15 **0 touched** since 5-19 12:00 SH cold-start (~7h sustained focus on reactive fix). **同 pattern 跨 domain recurrence.**

### §4.3 我 self-audit conclusion

**Session 58+1 work was tactically successful but missed plan v8's strategic framework**:
1. heuristic #18 alternative path 应在每 P0/P1 finding apply, 实际 mostly single-fix
2. §VIII 30 suggestions 5/30 (#26-#30) 全 0 traction (Decision Log / Living Doc / Auto Diagram / Audit Cadence / Reverse Trace)
3. §3-bis Strategic Alternatives 5/5 Alt A-E 都 0 follow-up
4. Phase 4-bis-C user touchpoint (frontend mockup A/B/C 选择) 0 triggered
5. Section IX/X/XI cross-cutting findings 都 sediment 后 dormant

**Root cause**: 我把 plan v8 看作"already done, sediment complete"而非"audit framework, sustained enforce". 反 §VII heuristic #17 "Audit Self-Audit + Cadence" 自己 first failure.

---

## §5 Action recommendation — 现在 (Session 58+1 末) → 5-26 Tue gate

### §5.1 Critical (今晚 / 明早 5-20 Wed 早 SH 必做)

| Priority | Action | Why now |
|---|---|---|
| **P0** | Disable gp-weekly Beat entry for 5d window (Gap #3) | 5-24 Sun 22:00 fire risk = leak 重演 in 5d gate |
| **P0** | Wire meta_monitor memory rule (C3, ADR-086 immediate subset) | 5d 内 leak recur 元告警 must active |
| **P0** | Replace CronCreate Day 1 wake with Windows Task Scheduler-driven sediment script (Gap #2) | 防 CC session 关闭导致 cadence 断 |
| **P1** | Sediment `PHASE_B_2_PREFLIGHT_CHECKLIST.md` (Gap #4) | 5-26 Tue gate evaluation 真 source |
| **P1** | 5d "PASS" 阈值 + 早 rollback criteria 显式 sediment (C4 + C5) | 5d 内任一 anomaly 决策 ambiguous |

### §5.2 High (5d window 期 5-20 → 5-26, daily incremental)

- LL-189 promote to LL (H5, 30 min effort)
- 5d observation 自动化 script (H7, ~2h effort, 节约后续 daily 沉淀时间)
- ADR-086 promote (H6, 30min ADR + ~2h schtask + Servy memory limit verify)
- PT_START_DATE .env audit (H1, 15min verify)

### §5.3 Strategic (5-27 Phase B-2 后启动)

- Phase J 7 items (S1-S7) — single Alpha SPOF 真 alpha confidence 必先
- Plan v8 §VIII #26-#30 5 sediment SOP implement (Decision Log / Living Doc / Auto Diagram / Audit Cadence / Reverse Trace)
- Strategic Alt B/C/D pilot 决议 (post Phase J finding)

### §5.4 Long-term (Q3 2026+)

- Plan v8 §9.3 14 Open Questions (Frontend stack / mobile / auth / etc)
- ADR-028 AUTO + RAG + backtest replay (Sprint M+1~N)
- Quarterly audit cycle (heuristic #17 + #29)

---

## §6 Honest meta-finding (LL-190 候选)

**LL-190 候选 sediment** (5-19 ~19:40 SH):

> "Plan v8 audit sediment alone ≠ sustained audit enforcement. Heuristic #17 Audit Self-Audit + #18 Alternative Path Thinking + §VIII 30 suggestions, 若 sediment 后 0 schtask / 0 cron / 0 explicit enforcement mechanism, 全 drift 入 dormant state. Session 58 / 58+1 是 first-instance LL-187 cross-domain recurrence (Phase H Frontend v3 W1-W6 ✅ 后 W7-W15 sediment-then-forget). Root cause: 'sediment 完成' fault tolerance 误认 = 'audit framework active'. **真 fix**: each plan v8 sediment + corresponding **enforcement schtask + Beat rule + DingTalk reminder + audit cadence calendar tick**."

**LL-187 + LL-190 sister sub-classes of LL-183 silent NOT-GATING parent class** — plan v8 sediment 层 silent 失败 (cf. LL-188 sediment 层 vs LL-183 代码层 sub-class).

---

## §7 关联

- Plan v8 quizzical-snacking-fox.md (heuristic #17/#18/#20 + §VIII #26-#30 + §3-bis Strategic Alt A-E + §9.3 14 open Q)
- LL-184/185/186 (plan v8 sediment 3 LL candidate)
- LL-187 (Frontend v3 W1-W6 sediment-then-forget pattern parent)
- LL-188 (sediment drift forensic)
- LL-189 (worker leak + orphan queue)
- LL-190 候选 (本 doc) — plan v8 sediment-then-forget cross-domain
- ADR-085 (Path B Phase B-1 launched 5-19 evening)
- ADR-086 候选 (worker周期 restart + monitor wire)
- STATUS_REPORT 2026-05-19 memory_cleanup
- STATUS_REPORT 2026-05-19 pt_paper_dryrun_day0
- CC_ACTIONS_FOR_USER_2026_05_19 §1-§5 (15 user touchpoint items)
- ISSUES_PENDING_REGISTRY 41 items

---

**End of Comprehensive Unresolved Audit. 30+ items surfaced, 6 critical 必在 5-20 Wed 早 SH 前 closed (gp-weekly disable + memory rule wire + cron persistence fix + PHASE_B_2 preflight + 5d PASS threshold + rollback criteria). Awaiting user 决议 prioritization OR autonomous 接力 in this session (~1-2h focused work).**
