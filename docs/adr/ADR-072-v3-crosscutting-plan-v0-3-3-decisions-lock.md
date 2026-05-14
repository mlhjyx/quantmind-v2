# ADR-072: V3 横切层 Plan v0.3 3 Decisions Lock + Sprint Chain Sediment

**Status**: Accepted
**Date**: 2026-05-14
**Context**: Session 53+25, post V3 Tier B 6-sprint chain FULLY CLOSED (Session 53+24, TB-5c PR #349 ADR-071, Gate B 5/5 + Gate C 6/6 + V3 §15.4 4/4 + §13.1 5/5)
**Related**: ADR-022 / ADR-037 + 铁律 45 / ADR-049 §3 / ADR-063 (本 ADR D2 LiteLLM-3month defer 沿用 paper-mode deferral pattern) / ADR-064 (Plan v0.2 5 决议 lock + D4=否 每 Tier 独立 plan 体例, 本 ADR 直接 follow-up) / ADR-070 (TB-5b replay acceptance — 本 ADR D3 5y replay 沿用 `_TimingAdapter` 体例) / ADR-071 (Tier B FULLY CLOSED + 2 Gate C sub-item DEFERRED to Plan v0.3) / LL-098 X10 / LL-100 / LL-115 / LL-116 / LL-164

---

## §1 Context

V3 Tier B (6-sprint chain T1.5→TB-1→TB-2→TB-3→TB-4→TB-5) FULLY CLOSED 2026-05-14 (TB-5c PR #349 ADR-071). Plan v0.3 = V3 实施期第 3 个 Tier-level plan (沿用 ADR-064 D4=否 每 Tier 独立 plan 体例: v0.1=Tier A / v0.2=Tier B / **v0.3=横切层** / v0.4=cutover).

横切层 = Constitution §L10.4 Gate D. Gate D checklist 5 项: (1) V3 §13 元监控 risk_metrics_daily + alert-on-alert production-active / (2) V3 §14 失败模式 enforce + 灾备演练 ≥1 round / (3) V3 §17.1 CI lint 生效 + pre-push hook 集成 / (4) prompts/risk eval iteration ≥1 round / (5) LiteLLM 月成本 ≥3 month ≤80% baseline.

CC fresh re-read Constitution §L10.4 + V3 §13/§14/§16.2/§17.1 实测 → Gate D 5-item state assessment: item 1 risk_metrics_daily 表 + daily_aggregator + Beat 已 production-active (Tier A S10 ADR-062, alert-on-alert 净新) / item 3 CI lint check_llm_imports.sh + pre-push + governance test 已 exist (Tier A ADR-020/032, verify-only) / item 5 inherently wall-clock (paper-mode 0 live LLM traffic). + 5 carried-forward DEFERRALS from Tier B (Plan v0.2 §C 横切层 起手 prereq sediment + ADR-071 D4): 5y full replay / north_flow_cny+iv_50etf wire / RISK_FRAMEWORK_LONG_TERM_ROADMAP.md sediment / LiteLLM 3-month cost / RAG 命中率 baseline + lesson 后置抽查.

User 触发 Plan v0.3 横切层 sprint chain plan-then-execute 体例 (sustained Plan v0.2 sub-PR sediment 体例 + LL-098 X10 反 silent self-trigger). 红线 5/5 sustained throughout 横切层: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102.

User approved 3 决议 via AskUserQuestion 1 round ack — CC presented Gate D 5-item state assessment + 3 fork → user picked CC 推荐 all (3/3).

---

## §2 Decision

3 决议 lock:

### D1 = 4-sprint HC-1~4

横切层 sprint chain = HC-1 + HC-2 + HC-3 + HC-4 (HC = 横切). Rationale:

- ✅ Gate D 5 项 自然 cluster 成 4 sprint: item 1 → HC-1 (元监控 alert-on-alert 独立 layer) / item 2 → HC-2 (失败模式 enforce + 灾备演练, 最大 net new) / item 3+4 → HC-3 (CI lint verify-only + prompts eval, 体量轻 合并) / item 5 + carried deferral + closure → HC-4
- ✅ 每 sprint chunked 2-3 sub-PR (HC-1/HC-2/HC-4 各 3 + HC-3 2), 沿用 LL-100 chunked SOP + Tier B sub-PR 体例 (TB-1~5 全 chunked 2-4 sub-PR 实证)
- ⚠️ Trade-off: HC-3 体量轻 (~1 周) 可并入 HC-4 — accept (保持独立 sprint 让 Gate D item 3+4 closure 干净, sub-task creep 风险 lower; §F (v) 允许 user 修订)

### D2 = both DEFER (LiteLLM 3-month cost + §13.4 dashboard)

- ✅ Gate D item 5 LiteLLM 月成本 ≥3 month ≤80% baseline = inherently wall-clock (paper-mode 0 live LLM traffic, 3-month 自然累积不可压缩) → ⏭ DEFERRED to Gate E 自然累积, sustained ADR-063 paper-mode deferral pattern. Honest scope handling, NOT silent skip — Constitution §L10.4 item 5 amend 留 HC-4c batch closure 标注.
- ✅ V3 §13.4 监控 dashboard (frontend `risk-monitoring` 页面) NOT in Gate D checklist (checklist item 1 仅要求 risk_metrics_daily + alert-on-alert production-active, dashboard 是 §13.4 独立 frontend 设计) → 留独立 frontend track, NOT 横切层 scope, 反 scope creep 误入.
- ⚠️ Trade-off: dashboard 不在 横切层 → 横切层 closure 后风控仍无可视化面板 — accept (dashboard 是 frontend track 独立交付, 不阻 Gate D closure)

### D3 = both into HC-4 (5y replay + north_flow/iv wire)

- ✅ 5y full minute_bars replay (~191M rows, 实际覆盖 2021-2025 minute_bars 范围) — TB-1 RiskBacktestAdapter.evaluate_at + ADR-070 `_TimingAdapter` side-channel infra 已就绪, 纯 replay run (0 新 evaluator code, 0 changes to closed TB-1 code sustained ADR-022), long-tail acceptance vs Tier B 2 关键窗口 → 纳入 HC-4a
- ✅ ADR-067 D5 `north_flow_cny` + `iv_50etf` MarketIndicators real-data-source wire (TB-2 left DEFERRED) — HC-4a wire 真数据源 (沿用 铁律 1 先读官方文档确认接口), 清掉 carried deferral backlog
- ⚠️ Trade-off: 5y replay ~191M rows wall-clock run time (TB-1c 2 关键窗口 ~3.32M+0.96M bars; 5y ~191M ≈ 40x) — accept, HC-4a cycle 含此 run time buffer (~0.5 周)
- carried deferral 路由结果: 5y replay→HC-4a / north_flow-iv→HC-4a / ROADMAP→HC-4b / LiteLLM-3month→Gate E (D2) / RAG 命中率+lesson 抽查→Gate E (need live query traffic, paper-mode 物理不可做)

---

## §3 Consequences

### §3.1 Plan v0.3 横切层 sprint chain baseline cycle

- HC-1: 1-1.5 周 baseline (chunked 3 sub-PR: HC-1a + HC-1b + HC-1c)
- HC-2: 1.5-2 周 baseline (chunked 3 sub-PR: HC-2a + HC-2b + HC-2c)
- HC-3: 1 周 baseline (chunked 2 sub-PR: HC-3a + HC-3b)
- HC-4: 1-1.5 周 baseline (chunked 3 sub-PR: HC-4a + HC-4b + HC-4c)
- **横切层 total**: ~4.5-6 周 baseline (含 buffer), replan 1.5x = ~7-9 周

### §3.2 V3 实施期总 cycle 真值再修订 (post Plan v0.3 sediment)

- Tier A 真 net new ~3-5 周 ✅ closed Session 53 cumulative 19 PR (#296-#323)
- Tier B Plan v0.2 = ~8.5-12 周 baseline ✅ closed Session 53+24 cumulative ~23 chunked sub-PR (#325-#349)
- 横切层 Plan v0.3 = ~4.5-6 周 baseline (本 plan 真值修订, vs Plan v0.1/v0.2 §E cite "≥12 周" — >2x 下修)
- cutover Plan v0.4 = 1 周
- **真值 estimate**: Tier A ~3-5 + Tier B ~8.5-12 + 横切层 ~4.5-6 + cutover 1 = **~17-24 周** (~4-6 月), vs ADR-064 §3.2 cite "~25-30 周" — 下修 ~8 周
- replan trigger 1.5x = ~25-36 周 (~6-9 月)

### §3.3 横切层 baseline 真值漂移 (正向, pre-built 减负)

Plan v0.1 §E + Plan v0.2 §E + ADR-064 §3.2 cite "横切层 ≥12 周" — 本 plan 自底向上 ~4.5-6 周. 原因: Gate D item 1 (risk_metrics_daily + daily_aggregator + Beat, Tier A S10 ADR-062) + item 3 (CI lint check_llm_imports.sh + pre-push + governance test, Tier A ADR-020/032) 已实建 — HC-1 仅 wire alert-on-alert layer / HC-3 项 3 = verify-only. 沿用 Tier A "真 net new << 名义, V2 prior cumulative substantially pre-built" 体例 (ADR-064 §3.2). Drift type = scope 真值漂移 (Constitution §L5.2 #2) + 正向 (NOT 治理债). Sediment 于 Plan v0.3 §E + §H Finding #2 + LL-165.

### §3.4 Constitution §L10.4 amend pending HC-4c batch closure

- §L10.4 item 2 "失败模式 12 项" → "15 模式" amend per Plan v0.3 §H Finding #1 (V3 §14 表真值 enumerate 15 模式: mode 1-12 + mode 13 BGE-M3 OOM + mode 14 RiskReflector V4-Pro 失败 + mode 15 LIVE_TRADING_DISABLED 双锁失效; checklist "12 项" 是 stale cite)
- §L10.4 item 5 "LiteLLM 月成本 ≥3 month ≤80% baseline" → "⏭ DEFERRED-to-Gate-E" amend per D2
- §0.1 footer "失败模式 12 项" cite + ROADMAP closure 标注
- 全 amend 留 HC-4c sediment 周期 batch closure pattern (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例)

### §3.5 决议 lock 累积扩 cumulative pattern

- Plan v0.1 6 项决议 (Finding #1/#2/#3 + Push back #1/#2/#3) + Plan v0.2 5 项决议 (D1-D5) + Plan v0.3 3 项决议 (D1-D3) = **14 项决议 cumulative sediment**

### §3.6 横切层 期 ADR sediment cumulative (待 promote)

- ADR-072 (本 ADR) Plan v0.3 3 决议 lock ✅ 本 sub-PR sediment
- ADR-073 (HC-1) 元监控 alert-on-alert closure
- ADR-074 (HC-2) 失败模式 15 项 enforce + 灾备演练 synthetic closure
- ADR-075 (HC-3) prompts/risk eval iteration closure (CI lint verify-only 不另 ADR, 沿用 ADR-020/032)
- ADR-076 (HC-4) 横切层 closure cumulative + Gate D formal close

---

## §4 Cite

- [Plan v0.3 §A](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (HC-1~4 sprint table)
- [Plan v0.3 §G I](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (3 决议 lock sediment 反思)
- [Plan v0.3 §H Finding #1/#2/#3](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (Phase 0 active discovery)
- [Plan v0.2 sub-PR sediment 体例](../V3_TIER_B_SPRINT_PLAN_v0.1.md) (sustained ADR-064 D5=inline + ADR-049 §3 chunked precedent)
- [ADR-064](ADR-064-v3-tier-b-plan-v0-1-5-decisions-lock.md) (Plan v0.2 5 决议 lock + D4=否 每 Tier 独立 plan 体例 — 本 ADR 直接 follow-up)
- [ADR-071](ADR-071-v3-tier-b-closure-gate-bc-formal-close.md) (Tier B FULLY CLOSED + 2 Gate C sub-item DEFERRED to Plan v0.3)
- [ADR-063](ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md) (paper-mode deferral pattern — D2 LiteLLM-3month defer 沿用)
- [ADR-070](ADR-070-v3-tb-5b-replay-acceptance.md) (replay acceptance `_TimingAdapter` 体例 — D3 5y replay 沿用)
- [LL-098 X10](../../LESSONS_LEARNED.md) (反 silent self-trigger forward-progress default)
- [LL-100](../../LESSONS_LEARNED.md) (chunked SOP target)
- [LL-164](../../LESSONS_LEARNED.md) (Tier B closure 体例 + verification-methodology-must-match-rule-semantics + Gate verifier-as-charter pattern)

### Related ADR

- [ADR-022](ADR-022-anti-anti-pattern-集中修订机制.md) (反 silent overwrite + 反 retroactive content edit)
- [ADR-037](ADR-037-internal-source-fresh-read-sop.md) + 铁律 45 (4 doc fresh read SOP + cite source 锁定)
- [ADR-049 §3](ADR-049-v3-s2-5-architecture-sediment-and-rsshub-route-reuse.md) (chunked sub-PR 体例 greenfield scope)
