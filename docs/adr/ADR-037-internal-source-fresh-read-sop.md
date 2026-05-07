---
adr_id: ADR-037
title: Internal source fresh read SOP — 4 root doc + sub-PR/sub-step 起手前必走 enforcement (governance)
status: accepted
related_ironlaws: [22, 25, 36, 38, 45]
recorded_at: 2026-05-06
---

## Context

**P0 触发 (2026-05-06 user finding)**: "CLAUDE.md / IRONLAWS.md / LESSONS_LEARNED.md / SYSTEM_STATUS.md 4 doc 整 session 反 fresh read, CC 显然没有触发这些, 这是为什么?"

**根因**: SOP gap — Sprint 2 sub-PR 1-6 累计沉淀 仅 外 source fresh verify (智谱/Tavily/Anspire/GDELT/Marketaux/RSSHub docs, 沿用 LL-104 cross-verify 体例), 反 sediment 内 source (4 root doc) fresh read SOP. 致 5-02→5-06 累计 ~3-4x 真值漂移:

| 漂移类型 | prompt 假设 (5-02 memory cite) | fresh verify 真值 (5-06) | 漂移倍率 |
|---|---|---|---|
| IRONLAWS rule count | "32 rules T1=8 + T2=18 + T3=6" | **45 rules T1=31 + T2=14 + T3=0** | ~3-4x |
| LL last # | "ll_unique_ids 97→98 / LL-120" | **last LL-105, next free=LL-106** | drift |
| SESSION_PROTOCOL.md | "CLAUDE.md 拆分 sediment 沿用" | **0 存在** (Glob 0 results) | fictitious |
| 4 doc mtime | "5-06" | **0/4 5-06** (CLAUDE/IRONLAWS=5-01, LESSONS/SYSTEM_STATUS=5-03) | 因 |

**drift catch自身实证 #4** (PR-A #237): SOP 文件首版本身含 LL-119 / LL-115 phantom references — 正是本 SOP 设计要防止的 existence drift anti-pattern. Reviewer agent 抓 fix → 完整闭环 (沿用 LL-067 reviewer 第二把尺子 + LL-104 cross-verify).

**5-07 sediment 加深 (sub-PR 8a-followup-B 全 4 PR cycle)**: **第 6 + 第 7 漂移类型** candidate sediment (audit-week-2-B chunk B):

| # | 漂移类型 candidate | 真生产 evidence | sediment LL | 关联 candidate |
|---|---|---|---|---|
| 6 | production runtime state vs source code state | 5-07 sub-PR 8a verify **首次 SOP enforcement** catch P0-1 (Risk Beat 4-29 PAUSE 7d wiring code 在 production Beat 0 active) + P0-2 (Sprint 2 ingestion 0 caller wire) | LL-109 hook governance 4 days production 0 catch | sub-PR 8a-followup-pre meta-verify 体例 |
| 7 | 3rd-party API 默认参数误归因 silent semantic drift | 5-07 sub-PR 8a-followup-B Q9 web_fetch DeepSeek 官方 API docs 真测真值, vanilla LiteLLM call 漏 thinking 参数 → 默认 enabled → reasoning_content 出现 → CC 3 次 push back 误归因 "silent routing reasoner", user 第 7 次 push back catch correctly | LL-110 + LL-112 drift catch #14 **关键 governance** | DeepSeek API 3 层暗藏机制 (alias-pass-through + backend silent routing + LiteLLM cost registry gap) |

**drift catch自身实证 #5+#6+#7+#8 sediment** (audit-week-2-B chunk B):
- #5 候选: **SOP enforcement** 4 days 后 sub-PR 8a **首次 SOP**生效 catch P0 finding (沿用 #4 first SOP enforcement 体例)
- #6 候选: hook governance 4 days production 0 catch sediment (LL-109)
- #7 候选: alias-layer vs underlying-layer 双层混淆 — DeepSeek API 3 层暗藏机制 sediment (LL-110)
- #8 候选: vanilla 3rd-party SDK call 漏默认参数误归因 silent semantic drift (LL-112) — CC 3 次 push back 误归因, user 第 7 次 push back catch correctly. **反 anti-pattern v6.0 candidate** sediment 沿用 LL-098 X10 forward-progress reverse case 体例.

## Decision

**Governance 双层防御** sediment (PR-B):

1. **铁律 45 (T1)** — 4 doc fresh read SOP enforcement, 加入 IRONLAWS.md §18 X 系列治理类 (沿用 X10 governance pattern). 触发条件: 任一 sub-PR / sub-step / step / cross-session resume 起手前必走 SESSION_PROTOCOL.md §1.3 4 步真生产体例.
2. **LL-106** — 5-06 P0 finding sediment + memory cite 5-02 沉淀真值漂移 ~3-4x cite source 锁定真值 + PR-A drift catch sediment 实证 #4 cite source 锁定真值. ll_unique_ids canonical 97 → 98.
3. **SESSION_PROTOCOL.md** (PR-A #237 已 sediment) — 4 doc fresh read SOP detailed 体例 + sub-PR 起手前必走清单 + cite source 锁定真值 SOP, 5 类漂移类型 cite 体例.

## Alternatives Considered

**(1) LL-only sediment 反铁律 (governance 弱)** — 仅 LESSONS_LEARNED.md +LL-106 sediment, 不加铁律. **未选**: LL backref governance 弱 (CC 自主自律), pre-commit hook 仅 warning, 反 block. 历史已证 LL-103 分离 architecture finding 类 sediment 30 min 后即被违反 (沿用 LL-103 SOP-4 drift catch case第 1 次). 反复实证 governance 单层 (LL-only) 不足.

**(2) 沿用 LL-119 SOP only (现状, 反 sediment 内 source)** — 不引 SESSION_PROTOCOL.md / 铁律 45 / LL-106, 沿用 sub-PR 1-6 体例. **未选**: 5-06 P0 finding 因即 SOP gap, 反 sediment 内 source 直延续致后续 sub-PR 起手时累计漂移更深 (next 7-N).

**(3) 仅 SESSION_PROTOCOL.md create (PR-A only) 反铁律 + ADR + LL** — sediment 实操 SOP 但反 governance enforcement. **未选**: SOP 文件 0 enforcement 触发机制 (CC 自主读 vs 强制), 沿用 LL-098 X10 governance pattern 类比, X10 当时即沉淀为铁律 (反仅 LL-098), 本 SOP 沿用同体例.

## Consequences

**正面**:
- Governance 双层防御 (铁律 45 enforcement + SOP file detailed 体例 + LL-106 cite source 锁定真值)
- 4 doc fresh read SOP 真生产 enforcement, 反"凭印象 sediment" anti-pattern (沿用 LL-101 真测 verify 体例)
- 沿用 LL-098 X10 governance pattern (governance rule 加铁律 + LL + ADR 三层 sediment)
- drift catch自身实证 #4 真生产 captured (PR-A SOP 首版含 phantom LL → reviewer fix → 完整闭环, sediment cite source 锁定真值)
- 跨 session resume 时强制 fresh verify 4 doc, 反 5-02→5-06 类似漂移累计

**负面**:
- sub-PR / sub-step 起手前 4 步 fresh read 时间成本 (~1-2 min/sub-PR, 沿用 PR-A fresh verify 实测)
- IRONLAWS rule count 增 1 (45 → 46 rules), 文档引用漂移候选 (各 audit / handoff cite "45 rules" / "T1=31" 真值漂移 audit Week 2 batch sediment 候选)
- LESSONS_LEARNED.md ll_unique_ids canonical update 触 pre-commit 5 metric canonical 同步 update (反 silent overwrite, 沿用 SOP-3 数字 cite SOP)

## Implementation

**PR-A** (#237 merged 5-06 13:39 UTC, 沿用):
- create [docs/SESSION_PROTOCOL.md](../SESSION_PROTOCOL.md) (160 行 / reviewer findings 全采纳)

**PR-B** (本 PR, 5-06 sediment):
- patch [IRONLAWS.md](../../IRONLAWS.md) +铁律 45 next 编号 (1-44 + X9 + X10 + 45 sequence) + §1 索引 T1 共 31 → 32 + 全文 cross-ref 同步
- create [LESSONS_LEARNED.md](../../LESSONS_LEARNED.md) +LL-106 新建 (next free, ll_unique_ids canonical 97 → 98)
- create [docs/adr/ADR-037](ADR-037-internal-source-fresh-read-sop.md) (本 ADR, governance decision)
- patch [docs/adr/REGISTRY.md](REGISTRY.md) +ADR-037 row (committed) + total 28 / 6 reserved / 4 gap
- patch [docs/adr/README.md](README.md) +ADR-037 cite 行 (沿用 ADR-035/036 cite 体例)

**留 audit Week 2 batch sediment 候选** (push back 沿用 LL-098 X10 反 forward-progress default):
- SYSTEM_STATUS.md update — sub-PR 6 RSSHub Servy register service count drift (4 → 5)
- 4 doc fresh read SOP scope 拓展 (V3 / sprint_state v7 / ADR cumulative)

## References

- [SESSION_PROTOCOL.md](../SESSION_PROTOCOL.md) — 4 doc fresh read SOP detailed 体例 (PR-A #237 sediment)
- [IRONLAWS.md §18 #45](../../IRONLAWS.md) — 4 doc fresh read SOP enforcement (本 PR-B sediment)
- [LESSONS_LEARNED.md LL-106](../../LESSONS_LEARNED.md) — 5-06 P0 finding sediment (本 PR-B sediment)
- [ADR-021](ADR-021-ironlaws-v3-refactor.md) — 铁律 v3.0 重构 + IRONLAWS.md 拆分 + X10 加入 (本 ADR 沿用同体例)
- [ADR-022](ADR-022-sprint-treadmill-revocation.md) — Sprint Period Treadmill 反 anti-pattern + 集中修订机制 (governance backbone, 本 ADR 沿用)
- LL-067 — Reviewer agent 是 AI 自循环 PR 流程的正第二把尺子 (PR-A drift catch case sediment 生效 cite source)
- LL-098 (X10) — AI 自动驾驶 cutover-bias governance pattern (本 ADR 沿用同体例)
- LL-101 — audit cite 数字必 SQL/git/log 真测 verify before 复用 (反信任 sediment cite SOP)
- LL-103 — Claude.ai vs CC 分离 architecture (governance 双层防御实证)
- LL-104 — Claude.ai 写 prompt 时表格 cite 仅看 1 row 不够, 必 grep 全表 cross-verify
- LL-105 — ADR # reservation 待办 4 source cross-verify SOP-6 sediment
- PR #237 — PR-A SESSION_PROTOCOL.md create (本 ADR drift catch case #4 source)
