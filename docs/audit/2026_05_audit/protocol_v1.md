# QuantMind V2 Layer 4 协作 SOP (Protocol v1)

**Document ID**: protocol_v1
**Date**: 2026-05-01
**Status**: Phase 4.1 minimal design (Claude design 沉淀, 待 CC Phase 4.2 implementation)
**Source**: D78 Layer 4 协作改善决议 + Topic 1-4 ~30min 战略对话 closed sustained

---

## §1 真核背景

sprint period 真证据驱动:
- broader 47 → 53+ sustained 1 week (sprint period 真核 source candidate trend)
- 5 anti-pattern 累计 (memory #19/20/21/22/23) sustained
- audit Phase 1-10 cluster 4/6/7 sustained 真根因 (framework 自身缺 + security 真核 0 sustained + GUI 单点 dependency)
- F-D78-26 (4 源协作 N×N 漂移 broader 84+) + F-D78-260 (D 决议链 0 SSOT registry) sustained 真证据加深

真核 sustained: Layer 4 协作 SOP align prerequisite Layer 2 sprint sustained, 真核 ex-ante prevention 真核 sustained sprint period broader trend reverse.

---

## §2 4 Topic 决议 closed 真核

### Topic 1: ex-ante prevention 真 SOP

**A** pre-commit hook 验 .md 数字 vs DB 真值 (minimal scope: factor count / Tier 0 数 / LL 数 / D 决议 数 / 测试 baseline)
**B** handoff SQL verify 强制 template (handoff 数字必 cite SQL query + result + timestamp)
**C** sprint state 数字必 cite source + timestamp SOP
**D-G** memory #20-#23 sustained verify (Claude prompt 仅给方向 + 目标 + 验收标准 / CC 真测 verify / 反 user GUI cite = 真状态 / 反静态分析 = 真测)

### Topic 2: D 决议链 SSOT registry

**A** `docs/DECISION_LOG.md` 单文件 SSOT
**C** 后续 D 决议必 SSOT registry update (~30s/decision ongoing)
**D** D 决议 schema (D-N / 时点 / 来源 / 内容 / 关联 PR/ADR / 真核 verdict)
**B** D1-D71 历史 backfill 留 Layer 2 sprint Week 2-3 candidate
**E** D 决议矛盾 detect 留 Layer 2 sprint candidate

### Topic 3: 4 源 SSOT cross-verify

**A** weekly cadence
**B** 1% drift threshold
**C** 5 metric (factor count / Tier 0 数 / LL 数 / D 决议 数 / 测试 baseline)
**D** process: 我 prepare 4 源 cite → 你 review → drift verdict → 真根因 → STOP / continue
**E** sediment `docs/audit/cross_verify_log.md`

### Topic 4: alpha continuous verify

**A** weekly backtest 12yr regression_test (max_diff=0 + Sharpe=0.5309 sustained)
**B** weekly factor_ic verify (CORE3+dv_ttm IC trend)
**C** monthly walk-forward OOS rolling
**D** quantitative threshold (max_diff=0 / Sharpe drift > 10% / IC drift > 20%)
**E** sediment `docs/audit/alpha_continuous_log.md`
**F** quarterly factor methodology audit 留 Layer 2 sprint Week 4+ candidate

---

## §3 Monday 09:00-11:00 cadence sustained

**起手 Week 2** (sustained Week 1 sustained 真核 sustained Week 2 起手 first):

```
Monday 09:00-09:30 — Layer 0 真账户 ground truth
  - User GUI manual verify: xtquant cash + 持仓 + cb_state nav
  - sustained sprint period sustained 真账户保护 sustained
  - sediment account_truth_log.md weekly entry

Monday 09:30-10:00 — Layer 5 alpha continuous verify
  - CC weekly regression_test 12yr (max_diff=0 + Sharpe=0.5309 sustained)
  - CC weekly factor_ic verify (CORE3+dv_ttm IC trend)
  - drift > threshold → STOP + 真根因
  - sediment alpha_continuous_log.md weekly entry

Monday 10:00-10:30 — Layer 4 4 源 SSOT cross-verify
  - Claude.ai prepare 4 源 cite (Anthropic memory + repo + Claude.ai context + CC handoff)
  - User review 5 metric
  - drift > 1% → STOP + 真根因
  - sediment cross_verify_log.md weekly entry

Monday 10:30-11:00 — Sprint review + next week planning
  - Week N closed verdict
  - Week N+1 sprint scope finalize
```

**真核 cadence**: 起手 weekly. Week 4+ adapt biweekly candidate sustained (sustained sprint period sustained Week 2-3 broader trend reverse 真证据 sustained adapt).

---

## §4 STOP triggers sustained

任一 STOP trigger sustained:

- Layer 0: 真账户 drift > 0.01% (sprint state cite vs xtquant 真值)
- Layer 5: max_diff > 0 / Sharpe drift > 10% / IC drift > 20%
- Layer 4: 4 源 cross-verify drift > 1% (5 metric 任一)

STOP SOP sustained:
- 真根因诊断
- STATUS_REPORT 中段写入 (含 STOP 原因 + 已完成 + 未完成)
- 等 user reply (0 forward-progress offer, sustained LL-098)
- 0 自动 resume

---

## §5 5 anti-pattern 守门 sustained verify

memory #19-#23 sustained sprint period sustained verify:

1. memory #19 — 凭空假设具体数字 (broader 47/53+)
2. memory #20 — 凭空假设 path/file/function/class
3. memory #21 — 信 user GUI cite = 真状态
4. memory #22 — 看文档/grep/静态分析 = 真测 verify
5. memory #23 — Claude prompt 仅给方向 + 目标 + 验收标准

**真核 sustained**: 5 守门 memory sustained, 真核 enforce sustained sprint period sustained Monday cadence cross-verify 真证据 sustained reverse trend.

---

## §6 关联 ADR + LL + Tier 0 sustained

- ADR-021 (IRONLAWS v3) sustained
- ADR-022 (sprint period treadmill 反 anti-pattern) sustained
- 待写 ADR-027 candidate (Layer 4 SOP 沉淀, sustained Layer 2 sprint Week 4+ 决议)
- LL "假设必实测" broader 47/53+ sustained
- LL-098 stress test 第 19+ 次 sustained

---

## §7 next sequencing

Phase 4.2 CC implementation sustained:
- A pre-commit hook (Topic 1 A, minimal scope)
- DECISION_LOG.md file create + initial schema + D72-D78 sediment (~10min/decision x 7 = ~70min CC)
- handoff SQL verify template (Topic 1 B)
- sprint state cite SOP (Topic 1 C, update CLAUDE.md SOP section)
- protocol_v1.md sustained 沉淀 (本文件)
- alpha_continuous_log.md + cross_verify_log.md skeleton create

输出 PR sustained §4.3 PR review SOP + AI self-merge prerequisite verify sustained.

---

**Document end**.
