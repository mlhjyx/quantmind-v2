# ADR-064: V3 Tier B Plan v0.1 5 Decisions Lock + Sprint Chain Sediment

**Status**: Accepted
**Date**: 2026-05-13
**Context**: Session 53+1, post Tier A code-side 12/12 closure cumulative (Session 53, PR #319-#323) + ADR-063 sediment 5-13 (Tier A 5d paper-mode skip empty-system anti-pattern + Tier B replay 真测路径)
**Related**: ADR-022 / ADR-037 + 铁律 45 / ADR-049 §3 / ADR-063 (本 ADR 直接 follow-up) / LL-098 X10 / LL-100 / LL-115 / LL-116 / LL-157

---

## §1 Context

Tier A code-side 12/12 sprint closure cumulative (Session 53 cumulative 19 PR累积, sub-PR 9~19 sediment 体例 cumulative: PR #296~#323). Latest 5 PR post-compact (Session 53 +9 5d operational kickoff): PR #319 Celery Beat wire + PR #320 2 silent-zero bug fix + 3 schema-aware smoke + PR #321 C1 synthetic 5d toolkit + PR #322 ADR-063 + LL-157 + Constitution Gate A item 2 ⏭️ DEFERRED amend + Plan v0.1 §A S10 DEFERRED + PR #323 Plan v0.1 §D + §C + §A 5d-related anchors sync.

ADR-063 sediment 5-13: Tier A wall-clock 5d paper-mode acceptance ⏭️ DEFERRED → Tier B `RiskBacktestAdapter` 历史 minute_bars replay 真测路径 (empty-system 5d 自然 fire 信息熵 ≈ 0, trivially-pass 不 distinguishable from silent-zero bug class). 真测路径转 Tier B `RiskBacktestAdapter` 历史 minute_bars 回放 → 9 RealtimeRiskRule 真触发.

User 触发 Plan v0.2 Tier B sprint chain plan-then-execute 体例 (sustained Plan v0.1 sub-PR 8 体例 + LL-098 X10 反 silent self-trigger). 红线 5/5 sustained throughout Tier B: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102.

User approved 5 决议 via 2 round 反问 ack:

- **Round 1**: 3 sub-recommendation (I/II/III) → user picked (I) Plan v0.2 Tier B sprint chain
- **Round 2**: 5 decision matrix (D1-D5) → user picked CC 推荐 all

---

## §2 Decision

5 决议 lock:

### D1 = (a) T1.5 与 TB-1 串行

T1.5 形式 close 先 → 干净 phase transition → TB-1 起手. Rationale:

- ✅ Gate A 7/8 PASS 是 ADR-063 sustained 的前提 (Tier A 形式 close 完整 + Tier B 不带 Tier A debt 进场)
- ✅ 干净 phase transition + sub-PR 8 plan-then-execute 体例 sustainability sustained
- ⚠️ Trade-off: 多 ~3-5 day vs 并行 — accept (干净 phase 更稳, sub-task creep 风险 lower, sustained Plan v0.1 §B item 11 sub-task creep mitigation 体例)

### D2 = A BGE-M3 本地 embedding

TB-3 RiskMemoryRAG embedding 模型 = BGE-M3 本地 (vs LiteLLM API B 选项 reject). Rationale:

- ✅ 32GB RAM budget verify (V3 §16.1: 风控总常驻 ~5GB + buffer 7GB 留, BGE-M3 2GB 内可容)
- ✅ 0 cost advantage + 中文优化 + 1024 维 retrieval 命中率 baseline (V3 §5.4 line 712-714 option A sustained)
- ⚠️ Trade-off: 部署复杂度 (docker container OR conda env, CC 实测决议 + ADR-068 sediment 锁) vs LiteLLM API 0 部署 — accept (V3 §16.2 上限 ≤$50/月 sustained, BGE-M3 0 cost 内含足)
- ⚠️ V3 §14 #13 sustained: BGE-M3 OOM → retrieval skip alert path verify (TB-3c acceptance, integration smoke fail-mode injection alert 仍发)

### D3 = (b) TB-1 历史窗口 = 2 关键窗口

2024Q1 量化踩踏 + 2025-04-07 关税冲击 -13.15% (vs 5y full ~191M minute_bars rows). Rationale:

- ✅ TB-1 cycle 2 周 baseline reasonable (5y full ~191M rows × 2537 stocks × 9 rules wall-clock 估 ~1-2 周 仅 replay run + 不含 evaluator + counterfactual framework)
- ✅ 2 关键窗口 cover regime 极端 case 充分 (2024Q1 量化踩踏 + 2025-04-07 关税冲击 -13.15%)
- ✅ 5y full replay 留 Tier B closure post 横切层 (Plan v0.3 scope) — 横切层 V3 §13 元监控 + V3 §14 12 失败模式 + V3 §17.1 CI lint + LiteLLM cost ≥3 month 完整, 5y full replay 提供 long-tail acceptance
- ⚠️ Trade-off: 2 关键窗口 (~2-4M rows) vs 5y full (~191M rows) — accept (TB-1 acceptance baseline 不需 full)
- ⚠️ Constitution §L10.2 Gate B item 2 "12 年 counterfactual" amend per D3=b 留 TB-5c sediment 周期 (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例)

### D4 = (否) Plan v0.2 仅 Tier B scope

Plan v0.2 仅 Tier B (T1.5 + TB-1~5), 横切层 留 Plan v0.3 (Gate D scope), cutover 留 Plan v0.4 (Gate E scope). Rationale:

- ✅ Sustained Plan v0.1 体例每 Tier 独立 plan (v0.1 = Tier A, v0.2 = Tier B, v0.3 = 横切层, v0.4 = cutover)
- ✅ 每 plan 可独立 user approve + sediment + replan
- ⚠️ Trade-off: Plan v0.3 / v0.4 起手前需 user 显式 trigger — sustained LL-098 X10 反 silent self-trigger sustainability sustained

### D5 = inline 完整

Plan v0.2 ~40-50KB single Write call, single PR sediment (sustained Plan v0.1 54KB 体例 inline 完整, sub-PR 8 sediment 体例 sustainability):

- ✅ Sustained Plan v0.1 54KB 体例 inline 完整 (sub-PR 8 sediment 体例 sustainability)
- ✅ 单 plan doc 单 file 易 cite + REGISTRY row + memory handoff 同步 (反 N×N 漂移 LL-101/103/116)
- ⚠️ Trade-off: Plan v0.2 ~40-50KB single Write call — accept (chunked SOP per LL-100 applies to PR-level, NOT file-write-level; Plan v0.2 sub-PR sediment 1 PR single commit 沿用 Plan v0.1 sub-PR 8 体例 sustained)
- ✅ Plan v0.2 sub-PR sediment 7 file delta atomic 1 PR: Plan v0.2 doc NEW + Constitution amend (header v0.8 → v0.9) + skeleton amend (header v0.7 → v0.8 + §2.2 Tier B sprint chain row) + REGISTRY row + memory handoff + ADR-064 NEW + LL-158 append

---

## §3 Consequences

### §3.1 Plan v0.2 Tier B sprint chain baseline cycle

- T1.5: 3-5 day baseline (chunked 2 sub-PR: T1.5a + T1.5b)
- TB-1: 2 周 baseline (chunked 3 sub-PR: TB-1a + TB-1b + TB-1c)
- TB-2: 2 周 baseline (chunked 3 sub-PR: TB-2a + TB-2b + TB-2c)
- TB-3: 1-2 周 baseline (chunked 3 sub-PR: TB-3a + TB-3b + TB-3c)
- TB-4: 2 周 baseline (chunked 4 sub-PR: TB-4a + TB-4b + TB-4c + TB-4d)
- TB-5: 1 周 baseline (chunked 3 sub-PR: TB-5a + TB-5b + TB-5c)
- **Tier B total**: ~8.5-12 周 baseline (含 buffer), replan 1.5x = ~13-18 周

### §3.2 V3 实施期总 cycle 真值再修订 (post Plan v0.2 sediment)

- Tier A 真 net new ~3-5 周 (V2 prior cumulative S1/S4/S6/S8 substantially pre-built per sub-PR 9 sediment 体例) ✅ 已 closed Session 53 cumulative 19 PR
- T1.5 Plan v0.2 = 3-5 day
- Tier B Plan v0.2 = 8.5-12 周
- 横切层 Plan v0.3 = ≥12 周 (Plan v0.1 §E cite sustained)
- cutover Plan v0.4 = 1 周
- **真值 estimate**: Tier A ~3-5 + T1.5 3-5 day + Tier B 8.5-12 + 横切层 ≥12 + cutover 1 = **~25-30 周** (~6-7 月)
- replan trigger 1.5x = ~37-45 周 (~9-11 月)

### §3.3 Constitution §L10.2 amend pending TB-5c batch closure

- Constitution §L10.2 line 411 item 2 "12 年 counterfactual replay" 真值 amend per D3=b → 2 关键窗口 (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例)
- Constitution §L10.2 line 412 item 3 "WF 5-fold" 真值 scope mis-attribution amend (factor research scope NOT Tier B 风控) 留 TB-5c sediment 周期

### §3.4 决议 lock 累积扩 cumulative pattern

- Plan v0.1 6 项决议 (Finding #1/#2/#3 + Push back #1/#2/#3) + Plan v0.2 5 项决议 (D1-D5) = **11 项决议 cumulative sediment**

### §3.5 Tier B 期 ADR sediment cumulative (待 promote)

- ADR-064 (本 ADR) Plan v0.2 5 决议 lock ✅ 本 sub-PR sediment
- ADR-065 (T1.5) Gate A formal close
- ADR-066 (TB-1) RiskBacktestAdapter full impl + 历史回放 infra
- ADR-067 (TB-2) MarketRegimeService prompt + DDL + 集成 (alias 沿用 ADR-026 reserved 体例 sustained REGISTRY)
- ADR-068 (TB-3) BGE-M3 + risk_memory + 4-tier retention (alias 沿用 ADR-025 reserved 体例 sustained REGISTRY)
- ADR-069 (TB-4) RiskReflectorAgent + lesson 闭环
- ADR-070 (TB-5) Tier B replay 真测结果 sediment per ADR-063 referenced ADR-XXX
- ADR-071 (TB-5) Tier B closure cumulative + Gate B + Gate C formal close

---

## §4 Cite

- [Plan v0.2 §A](../V3_TIER_B_SPRINT_PLAN_v0.1.md) (T1.5 + TB-1~5 sprint table)
- [Plan v0.2 §G I](../V3_TIER_B_SPRINT_PLAN_v0.1.md) (5 决议 lock sediment 反思)
- [Plan v0.2 §H Finding #1/#2/#3](../V3_TIER_B_SPRINT_PLAN_v0.1.md) (Phase 0 active discovery)
- [Plan v0.1 sub-PR 8 sediment 体例](../V3_TIER_A_SPRINT_PLAN_v0.1.md) (sustained ADR-049 §3 chunked precedent)
- [ADR-063](ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md) (Tier A 5d paper-mode skip + Tier B replay 真测路径 — 本 ADR 直接 follow-up)
- [LL-098 X10](../../LESSONS_LEARNED.md) (反 silent self-trigger forward-progress default)
- [LL-100](../../LESSONS_LEARNED.md) (chunked SOP target)
- [LL-115](../../LESSONS_LEARNED.md) (capacity expansion 真值 silent overwrite anti-pattern)
- [LL-116](../../LESSONS_LEARNED.md) (fresh re-read enforce)
- [LL-157](../../LESSONS_LEARNED.md) (Mock-conn schema-drift LL-115 family 8/9 实证, Session 53 cumulative)

### Related ADR

- [ADR-022](ADR-022-anti-anti-pattern-集中修订机制.md) (反 silent overwrite + 反 retroactive content edit)
- [ADR-037](ADR-037-internal-source-fresh-read-sop.md) + 铁律 45 (4 doc fresh read SOP + cite source 锁定)
- [ADR-049 §3](ADR-049-v3-s2-5-architecture-sediment-and-rsshub-route-reuse.md) (chunked sub-PR 体例 greenfield scope)
- [ADR-063](ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md) (本 ADR 直接 follow-up)
