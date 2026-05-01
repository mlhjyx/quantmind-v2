# 现状快照 — CC 扩 类 15+17+20 (broker对账历史 + PT 重启历史 + 误操作历史)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 3 / snapshot/15+17+20
**Date**: 2026-05-01
**Type**: 描述性 + CC 扩 类合并 sub-md

---

## §1 类 15 — 真账户对账历史 (sustained operations/01)

(详 [`operations/01_real_account_reconciliation.md`](../operations/01_real_account_reconciliation.md))

实测 sprint period sustained sustained:
- xtquant ↔ cb_state 一致 (差 ¥0.50 微小, F-D78-12)
- xtquant ↔ position_snapshot 4 trade days stale + 19 vs 0 持仓 (F-D78-4 P2)
- 跨源 reconciliation SOP 0 sustained (F-D78-50 P1)
- broker 月报 / 季报 vs cb_state 真深查 0 sustained (F-D78-35 P2 unknown unknown)

**finding** (sustained):
- F-D78-50 (复) P1 + F-D78-4 (复) P2 + F-D78-35 (复) P2

---

## §2 类 17 — 历史 PT 重启次数 + 失败原因

实测 sprint period sustained sustained sustained:
- PT 启动: 2026-03-25 (sprint state Session 1-46+ 累计)
- PT 暂停: 2026-04-29 (sprint state Session 44 沉淀)
- 重启次数: **0 真重启 since 4-29** (sprint period sustained sustained sustained "PT 重启 prerequisite gate" candidate sustained)
- 失败原因: (无重启, N/A)

候选深查:
- 历史 sprint period sustained PT 启动停止真 enumerate (sprint state Session 1-46+ 真累计)
- 历史 PT 期间真 NAV 演进 (3-25 → 4-29 60 day)

候选 finding:
- F-D78-180 [P3] 历史 PT 启动停止真 enumerate 0 sustained sustained sustained 度量 (sprint state Session 1-46+ 累计 但真 enumerate sub-md 0 sustained sustained sustained 沉淀)
- F-D78-181 [P3] PT 期间真 NAV 演进 (3-25 → 4-29 60 day) 0 sustained sustained sustained 度量, sprint period sustained sustained "Sharpe 0.8659 WF" sustained sustained sustained vs 真期间 NAV ~-0.65% sustained sim-to-real gap (sustained F-D78-85 P1 sustained)

---

## §3 类 20 — 历史误操作 (git revert + 数据误删)

实测 (CC 5-01 实测 governance/04 §3):
- git 60 day reverts (grep "revert|Revert") = **0 真 git revert** ✅
- 候选数据误删 0 sustained sustained sustained 度量

**finding**:
- F-D78-150 (复) [P3] git 60 day 0 真 git revert ✅, 协作 maturity 候选 高
- F-D78-182 [P3] 候选数据误删历史 0 sustained sustained sustained 度量 (sprint period sustained sustained 沉淀 多次"DELETE position_snapshot 4-28 stale (19)" 类 sustained, 候选 audit sub-md 详查)

---

## §4 类 21 — 用户输入历史 (D 决议链)

(详 [`governance/03_d_decision_chain.md`](../governance/03_d_decision_chain.md) sustained F-D78-130/131/132 sustained + governance/06 §5 F-D78-177 sustained)

---

## §5 类 22 — 跨 session memory drift

(详 [`governance/02_knowledge_management.md`](../governance/02_knowledge_management.md) sustained F-D78-26/51/52 sustained)

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-180 | P3 | 历史 PT 启动停止真 enumerate 0 sustained 度量 |
| F-D78-181 | P3 | PT 期间真 NAV 演进 0 sustained 度量, WF Sharpe 0.8659 vs 真期间 NAV ~-0.65% sim-to-real gap |
| F-D78-182 | P3 | 数据误删历史 0 sustained 度量 (sprint period sustained "DELETE position_snapshot 4-28 stale" 类 sustained) |

---

**文档结束**.
