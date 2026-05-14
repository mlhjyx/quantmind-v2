# ADR-076: V3 横切层 HC-4 Closure — 横切层 sprint chain FULLY CLOSED + Gate D formal close

**Status**: Accepted
**Date**: 2026-05-15
**Context**: Session 53+33/+34, V3 横切层 Plan v0.3 §A HC-4 sprint closure — the FINAL sprint of the 横切层 chain (HC-1~4). Gate D (Constitution §L10.4) formal close.
**Related**: ADR-064 D3=b (5y replay 2-window → full deferred) / ADR-067 D5 (north_flow/iv wire) / ADR-070 (TB-5b replay acceptance methodology + `_TimingAdapter`) / ADR-071 (Tier B FULLY CLOSED — 横切层 起手 prereq) / ADR-072 (Plan v0.3 3 决议 lock D1-D3) / ADR-073 (HC-1 closure) / ADR-074 (HC-2 closure) / ADR-075 (HC-3 closure) / ADR-022 (反 retroactive content edit — amend = checkbox + closure blockquote append) / ADR-063 (paper-mode deferral pattern) / LL-098 X10 (反 forward-progress — STOP gate before Plan v0.4) / LL-100 (chunked SOP) / LL-164 (Gate verifier-as-charter — pre-sediment verify) / LL-166/167/168 (HC-1/2/3 closure 体例) / LL-169 (本 — HC-4 + 横切层 chain closure 体例)

---

## §1 Context

V3 横切层 Plan v0.3 §A HC-4 = the final sprint of the cross-cutting chain (HC-1 元监控 alert-on-alert / HC-2 失败模式 enforce + 灾备演练 / HC-3 CI lint + prompts eval / **HC-4 carried deferral 路由 + 5y replay + north_flow/iv wire + ROADMAP sediment + Gate D formal close**). HC-4 chunked **3 sub-PR** (HC-4a + HC-4b + HC-4c) — **planned 3, actual 3: 0 balloon** (沿用 HC-3 estimate-held 体例 — LL-168 lesson 1: verify/audit/closure-sediment sub-PRs estimate accurately; 反 HC-1/HC-2 双 net-new-wiring 3→5 balloon).

红线 5/5 sustained throughout: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102.

---

## §2 Decision

### D1 — HC-4a: 5y full minute_bars replay long-tail acceptance ✅ PASS 4/4 V3 §15.4

`scripts/v3_hc_4a_5y_replay_acceptance.py` (NEW) runs the full 5y minute_bars replay **chunked per-quarter** (20 windows 2021Q1–2025Q4) — the full ~191M-row table cannot be materialized at once (OOM on a 32GB box), so each quarter is run + classified + raw events discarded; only count aggregates carried. Reuses TB-5b module-level helpers + `qm_platform.risk.replay` PURE evaluators (DRY — 0 changes to closed TB-1/TB-5b code, sustained ADR-022).

**Result**: ✅ PASS on all 4 V3 §15.4 criteria — FP rate **4.12%** (8,193/199,074) < 30% / latency P99 **0.024ms** (max-quarter conservative aggregate) < 5000ms / STAGED **0 failed** / 元监控 **0 P0**. 139.3M minute_bars replayed across 20 quarters in 1413.8s wall-clock. Methodology sustained ADR-070 (daily-dedup + prev_close baseline counterfactual FP classification; caveat family — synthetic universe-wide Position = 误报率 upper-bound proxy; latency = lower-bound proxy). Sediment: `docs/audit/v3_hc_4_5y_replay_acceptance_report_2026_05_14.md`. HC-4a PR #360 `3d508ca` — code-reviewer APPROVE + python-reviewer (1 P1 + 2 P2 + 2 P3 all fixed).

### D2 — HC-4a: north_flow/iv wire = VERIFY, not implement (TB-2e #338 already delivered)

ADR-067 D5 routed `north_flow_cny` + `iv_50etf` MarketIndicators real-data-source wire to HC-4. **HC-4a Phase 0 fresh-verify finding [type a]**: the wire was **already delivered by TB-2e (PR #338 `c537d13`)** — `backend/qm_platform/risk/regime/default_indicators_provider.py` wires both (`_fetch_north_flow_cny` via Tushare moneyflow_hsgt + `_fetch_iv_50etf_proxy` via 上证 20-day realized vol proxy), production-active via `market_regime_tasks._get_provider()` lazy singleton. HC-4a's deliverable for this item is therefore **verification, not implementation** (re-shaped per user 决议 A, AskUserQuestion 1 round) — verified facts sediment in HC-4a report §4. **0 new code** (sustained ADR-022 反 silent 改 closed TB-2e code). Stale cites amended in HC-4c batch (see D4 below).

### D3 — HC-4b: RISK_FRAMEWORK_LONG_TERM_ROADMAP.md created + carried deferral 6 项路由

`docs/RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` (NEW, 171 lines) — V3_DESIGN §19 Roadmap (12月) 标准化为独立 file + re-anchor 到 2026-05-15 真值 (V3 §18.3 reserved scope). sediment 触发 = Tier B closure REACHED (ADR-071) + Constitution §0.1 长期 Roadmap 行. **Phase 0 finding [type a]**: V3 §19.1 时序表 (design-time projection v1.0 2026-05-01) stale — 项目超前约 1 quarter; re-anchored in the standalone file (V3_DESIGN §19 itself NOT retroactively edited — sustained ADR-022).

**carried deferral 6 项路由** (Plan v0.3 §C table, sediment 反 silent drop — Plan §B 风险 #5): 3 done — 5y replay (HC-4a) / north_flow-iv (HC-4a verify) / ROADMAP (HC-4b); 3 → Gate E — LiteLLM 月成本 ≥3 month / RAG retrieval 命中率 baseline / lesson→risk_memory 后置抽查, all physically require live traffic (paper-mode cannot equivalently simulate wall-clock-bound + traffic-bound measurement, sustained ADR-063 paper-mode deferral pattern). HC-4b docs-only 直 push `2c621bb` — document-specialist reviewer (1 P1 + 2 P2 + 1 P3 all fixed).

### D4 — HC-4c: Gate D formal close — verifier PASS 5/5 + batch closure sediment

`quantmind-v3-sprint-closure-gate-evaluator` subagent ran Gate D verify (Constitution §L10.4) — **PASS 5/5**:

| Gate D item | verdict | evidence |
|---|---|---|
| 1. V3 §13 元监控 risk_metrics_daily + alert-on-alert production-active | PASS | HC-1 (ADR-073) — meta_alert_interface/rules PURE + meta_monitor_service + Beat `meta-monitor-tick` `*/5` live; risk_metrics_daily Tier A S10 (ADR-062) |
| 2. V3 §14 失败模式 **15 模式** enforce + 灾备演练 ≥1 round | PASS | HC-2 (ADR-074) — 15-mode enforcement matrix doc + `test_v3_hc_2c_disaster_drill.py` 29 tests + `docs/risk_reflections/disaster_drill/2026-05-14.md` |
| 3. V3 §17.1 CI lint `check_llm_imports.sh` 生效 + pre-push 集成 | PASS | HC-3 (ADR-075) — `check_llm_imports.sh --full` exit 0; pre-push + pre-commit integrate; `core.hooksPath=config/hooks` active; governance test 10/10 GREEN |
| 4. prompts/risk/*.yaml prompt eval iteration ≥1 round | PASS | HC-3 (ADR-075) — 5 YAML structural baseline eval, 5/5 sound 0 defect; routing 决议 locked vs ADR-036 |
| 5. LiteLLM 月成本 ≥3 month ≤80% baseline | ⏭ DEFERRED to Gate E | ADR-072 D2 — paper-mode 0 live LLM traffic, 3-month wall-clock 不可压缩; methodologically sound deferral, NOT a checklist gap |

**Gate D formally CLOSED** — items 1-4 ✅ verified production-active with concrete file+test+live-run evidence; item 5 Gate-E deferral methodologically sound. Verifier note (LL-164): HC-4c's own closure paperwork (this ADR-076, the §L10.4 checkbox amend) did not exist at verify time — that is expected and not counted against the verdict (the verify gates the UNDERLYING deliverables, not the closure paperwork).

**HC-4c batch closure sediment** (sustained ADR-022 反 retroactive content edit — amend = checkbox `[x]` + closure blockquote append + sanctioned stale-cite 真值修正 only):
- Constitution §L10.4: items 1-4 `[x]` with evidence cite + item 2 "失败模式 12 项"→"15 模式" 真值修正 (per Plan v0.3 §H Finding #1, sanctioned by Constitution v0.11 footnote) + item 3 path `check_anthropic_imports.py`→`check_llm_imports.sh` 真值修正 (per ADR-031 §6) + item 5 ⏭ DEFERRED-to-Gate-E (per ADR-072 D2) + §0.1 5-gate footer "失败模式 12 项"→"15 模式" + §L10 footer same; header v0.11→v0.12 + version history v0.12 entry append
- Constitution §0.1 长期 Roadmap 行: closure 标注 (ROADMAP file created HC-4b)
- skeleton V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md §2.2.2: 横切层 chain closure 标注 + header v0.9→v0.10 + version history v0.10 entry
- Plan v0.3 §A HC-4 row: closure blockquote append; lines 46+261 north_flow/iv stale-cite 标注 (TB-2e #338 已 wire)
- ADR-067 D5 + ADR-072 D3: north_flow/iv stale-cite 标注 (TB-2e #338 已 wire, HC-4a verify confirmed)
- REGISTRY: ADR-076 reserved→committed

### D5 — HC-4 estimate held (0 balloon) — 沿用 HC-3, 反 HC-1/HC-2

HC-1 ballooned 3→5 (ADR-073), HC-2 ballooned 3→5 (ADR-074), HC-3 held at 2 (ADR-075). **HC-4 held at planned 3.** Sustains LL-168 lesson 1 refinement: net-new-wiring sub-PRs balloon; verify/audit/closure-sediment sub-PRs estimate accurately. HC-4a = 5y replay run (infra 已就绪 TB-1+ADR-070, 0 new evaluator code) + north_flow/iv VERIFY (TB-2e 已 wire) — verify-heavy. HC-4b = ROADMAP doc sediment. HC-4c = Gate D verify + batch closure sediment. 0 net-new wiring across all 3 → estimate held. 横切层 4-sprint chain final balloon tally: 2 ballooned (HC-1/HC-2 net-new-wiring) + 2 held (HC-3/HC-4 verify/audit/sediment) — the LL-168 classification predicted this exactly.

### D6 — Plan v0.4 cutover (Gate E) prereq sediment — NOT auto-triggered

横切层 closure does NOT auto-trigger Plan v0.4 (Gate E PT cutover). Per LL-098 X10 + Plan v0.3 §C STOP gate: cutover is a 真账户 unlock action — Plan v0.4 起手 requires **user 显式 trigger** (Constitution §L8.1 (c) sprint 收口决议 user 介入). HC-4c sediments the prereq inventory so Plan v0.4 can start cleanly:

**Plan v0.4 (Gate E) prerequisites** (Constitution §L10.5 + V3 §20.1 #1+#5):
- paper-mode 5d dry-run 验收 (元监控 0 P0 + 5 SLA 满足)
- 5 SLA verify (V3 §13.1 — detection latency / News 6 源 / LiteLLM / DingTalk / STAGED 30min)
- 10 user 决议状态 verify (V3 §20.1 10 决议 closed PR #216)
- Tier A ADR 全 sediment (Gate A 部分)
- 3 carried-to-Gate-E deferrals measured: LiteLLM 月成本 ≥3 month ≤80% baseline / RAG retrieval 命中率 ≥ baseline / lesson→risk_memory 后置抽查 ≥1 live round
- DB 4-28 stale snapshot 清理 (运维层)
- **user 显式 .env paper→live 授权** + LIVE_TRADING_DISABLED true→false 解锁 (红线解锁硬门)

---

## §3 Consequences

### §3.1 HC-4 3 sub-PR cumulative

| sub-PR | PR / commit | scope |
|---|---|---|
| HC-4a | #360 `3d508ca` | 5y full minute_bars replay acceptance (chunked per-quarter, ✅ PASS 4/4 §15.4) + north_flow/iv wire VERIFY (TB-2e #338 已 delivered) + report doc §4 |
| HC-4b | `2c621bb` (docs-only 直 push 铁律 42) | `RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` NEW (171 lines) + carried deferral 6 项路由 sediment |
| HC-4c | 本 (docs-only 直 push 铁律 42) | Gate D `sprint-closure-gate-evaluator` verify PASS 5/5 + ADR-076 + Constitution §L10.4 5-checkbox amend + §0.1 closure 标注 + skeleton patch + Plan v0.3 closure markers + stale-cite amends + LL-169 + memory handoff + Plan v0.4 prereq sediment |

Reviewer 2nd-set-of-eyes: HC-4a `code-reviewer` APPROVE + `python-reviewer` (parallel multi-reviewer per feedback_code_pr_workflow); HC-4b `document-specialist`; HC-4c `document-specialist` (closure sediment).

### §3.2 横切层 sprint chain FULLY CLOSED — 4/4

HC-1 ✅ (ADR-073) + HC-2 ✅ (ADR-074) + HC-3 ✅ (ADR-075) + **HC-4 ✅ (本 ADR-076)** — 横切层 4-sprint chain FULLY CLOSED. **Gate D formally CLOSED** (Constitution §L10.4 — items 1-4 ✅ + item 5 ⏭ DEFERRED-to-Gate-E).

### §3.3 V3 实施 5 Gate status post-横切层

Gate A (Tier A) ✅ ADR-065 / Gate B (T1.5) ✅ ADR-071 / Gate C (Tier B) ✅ ADR-071 / **Gate D (横切层) ✅ 本 ADR-076** / Gate E (PT cutover) ⏳ Plan v0.4 (user 显式 trigger required — D6).

### §3.4 横切层 期 ADR cumulative

ADR-072 (Plan v0.3 3 决议 lock) + ADR-073 (HC-1 closure) + ADR-074 (HC-2 closure) + ADR-075 (HC-3 closure) + **ADR-076 (本 — HC-4 + Gate D formal close)** — 横切层 5 ADR cumulative, all committed.

### §3.5 next

横切层 FULLY CLOSED → V3 实施 entered Gate E pre-stage. Plan v0.4 (PT cutover) 起手 **awaits user 显式 trigger** (sustained LL-098 X10 + Plan v0.3 §C STOP gate). 0 forward-progress auto-offer.

---

## §4 Cite

- [Plan v0.3 §A HC-4 row + §C](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (HC-4 sprint plan + carried-deferral 路由 + Gate D criteria + STOP gate)
- [Constitution §L10.4](../V3_IMPLEMENTATION_CONSTITUTION.md) (Gate D checklist — HC-4c amend)
- [HC-4a 5y replay acceptance report](../audit/v3_hc_4_5y_replay_acceptance_report_2026_05_14.md)
- [RISK_FRAMEWORK_LONG_TERM_ROADMAP.md](../RISK_FRAMEWORK_LONG_TERM_ROADMAP.md) (HC-4b NEW)
- [ADR-070](ADR-070-v3-tb-5b-replay-acceptance.md) (replay acceptance methodology — 5y run 沿用)
- [ADR-071](ADR-071-v3-tier-b-closure-gate-bc-formal-close.md) (Tier B FULLY CLOSED — 横切层 起手 prereq)
- [ADR-072](ADR-072-v3-crosscutting-plan-v0-3-3-decisions-lock.md) (Plan v0.3 3 决议 lock — D3 5y-replay+north_flow/iv into HC-4)
- [ADR-073](ADR-073-v3-hc-1-meta-alert-closure.md) / [ADR-074](ADR-074-v3-hc-2-failure-mode-closure.md) / [ADR-075](ADR-075-v3-hc-3-ci-lint-prompts-eval-closure.md) (HC-1/2/3 closure)
- [LL-169](../../LESSONS_LEARNED.md) (HC-4 + 横切层 chain closure 体例 — plan-then-execute 第 5 case 全链 closure 真值落地)
- HC-4 PR #360 (HC-4a); HC-4b + HC-4c docs-only 直 push

### Related ADR

- [ADR-022](ADR-022-sprint-treadmill-revocation.md) (反 retroactive content edit — Constitution/Plan amend = checkbox + closure blockquote append + sanctioned 真值修正 only)
- [ADR-063](ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md) (paper-mode deferral pattern — 3 Gate-E deferrals 沿用)
- [ADR-067](ADR-067-v3-tb-2-market-regime-closure.md) (D5 north_flow/iv wire — stale-cite amended HC-4c: TB-2e #338 已 deliver)
