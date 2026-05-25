# DEV_AI_EVOLUTION.md V2.1 vs V3 §S5-§S8 Drift Audit

**Date**: 2026-05-25 17:23 SH | **Task**: 007 (TIER C) | **Author**: sub2 agent

## § 1 V2.1 file sections inventory

`docs/DEV_AI_EVOLUTION.md` (745 lines, v2.1 dated 2026-04-16 + Session 57/58+1 2026-05-19 addenda):

| Layer | Section (line#) | Claimed status | Real impl |
|---|---|---|---|
| Layer 1 Trajectory (ic_monitor / rolling_wf / pt_daily_summary) | §三 (L264-304) | ~95% | ✅ scripts/monitor_factor_ic.py + run_rolling_wf.py |
| Layer 2 轨迹进化 (Idea/Factor/Strategy/Eval Agent) | §四 (L306-447) | ~60% | partial — 4 files exist, strategy_agent MISSING |
| Layer 3 Feature Map (RANKING/FAST/EVENT/MODIFIER × 风险/市值) | §五 (L449-487) | 0% | grep 0 hits (heuristic #14 sustained) |
| Layer 4 资本分配 (riskfolio-lib 季度) | §六 (L489-512) | 0% | grep `riskfolio` 0 backend hits |
| Orchestrator 8 节点状态机 | §二-A (L78-263) | designed | 0 中枢实现, engine_selector 仅工具 |

V3 reference scan (`V3|§S5-§S8`): **5 hits**, all in Session 58+1 2026-05-19 addendum frontmatter (L16-19). 主体 §一-§十四 (L40-731) **0 V3 §S5-§S8 cross-ref**.

## § 2 V3 §S5-§S8 实施 mapping

`docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` (1840 lines):

| V3 § | Title | Line# | PR | Merge commit | Backend path |
|---|---|---|---|---|---|
| §5 L2 智能风控层 | sentiment / fundamental / Bull-Bear / RAG | L604-738 | #343 RealtimeRiskEngine 10 rules 104 tests | 9aa13ea (verified) | backend/qm_platform/risk/realtime/engine.py ✅ |
| §6 L3 动态阈值层 | 实时市场状态 / 个股 / Concept-Industry | L739-814 | #345 DynamicThresholdEngine 48 tests | 6cd2f16 (verified) | backend/qm_platform/risk/dynamic_threshold/ ✅ |
| §7 L4 执行优化层 | STAGED / Batched / Trailing / Re-entry | L815-914 | #344 AlertDispatcher 28 tests | 460f18a (verified) | backend/qm_platform/risk/realtime/alert.py ✅ |
| §8 L5 反思闭环层 | RiskReflector周/月/事件 + RAG lesson | L915-1011 | #346 RiskReflector TB-4a-d 154 tests | e5c54f8 (verified) | backend/qm_platform/risk/reflector/agent.py ✅ |

Total: **334 new tests** (104+28+48+154), 4 PRs all MERGED state.

## § 3 Drift table

| # | V2.1 says | V3 says (真值) | Drift type |
|---|---|---|---|
| 1 | Layer 2 ~60% (Idea/Factor/Eval agents partial, strategy MISSING) — L7-8 addendum | V3 §5 RAG memory + §8 RiskReflector ✅ merged (PR #343-346, 334 tests) — V3 L604/L915 | V2.1 Layer 2 范围**不含 V3 风控反思路径** — orthogonal not contradictory |
| 2 | Layer 3+4 0% impl, Q3-Q4 trigger per ADR-028 — L9-10 | V3 §6 DynamicThreshold ✅ (PR #345) — V3 L739 | V2.1 Layer 3 (Feature Map 策略种群) ≠ V3 §6 (风控动态阈值) — **同名 "Layer 3" 不同语义**, drift 风险 |
| 3 | LLM 模型选择 §十 L607-619: GLM5 / DeepSeek V3 for Factor Agent | V3 §5.5 V4-Flash/V4-Pro routing (L719) + §8.4 V4-Pro RiskReflector (L980) | V2.1 LLM 选型表 **不含 V3 reflector path** |
| 4 | "agents/ → app/services/ai/ relocation" L24 (Session 58+1 addendum) | backend/qm_platform/risk/ 实际是 V3 风控 agent 路径 | V2.1 仅在 frontmatter 提及 ≠ 主体 §四 Agent 章节同步 |
| 5 | 文档元数据"前版 V1.0 (1064 行) → 本版精简" L27 | V3 设计是**新 framework**, 不是 V2.1 升级 | V2.1 是 AI 闭环 4-Layer (因子/策略发现), V3 是风控 6-Layer (L0-L5 实时风控) — **两个独立 framework** |

**核心 finding**: V2.1 ≠ V3 superseded. V2.1 = AI 因子/策略发现闭环 (Layer 1-4). V3 = 实时风控 framework (L0-L5). 两者**正交独立**, 但 V2.1 Session 58+1 addendum 已 partial sediment V3 §S5-§S8 状态, **主体章节未对齐**.

## § 4 推荐

**保留 V2.1, 加 §0 cross-ref header** (非 retire). 理由:
1. V2.1 Layer 1+2 实际仍 ~30-45% partial active (sustained Session 57 finding L11)
2. V2.1 ≠ V3 范围, retire 会丢 AI 闭环原始设计意图
3. V3 §5-§8 风控 agent 走独立路径, 不替代 Layer 2 factor agent

**建议 §0 redirect 内容** (5 行 frontmatter):
```
> **V3 风控 framework 交叉引用** (2026-05-25 audit): 本 doc Layer 2 Agent (Idea/Factor/Strategy/Eval) ≠ V3 §S5-§S8 风控 Agent (sentiment/Bull-Bear/RAG/RiskReflector).
> - V3 §S5 智能风控 → docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md L604 (PR #343 merged 9aa13ea)
> - V3 §S6 动态阈值 → V3 L739 (PR #345 merged 6cd2f16). **NB**: V3 "L3" ≠ V2.1 "Layer 3 Feature Map", 同名异义.
> - V3 §S7 执行优化 → V3 L815 (PR #344 merged 460f18a)
> - V3 §S8 反思闭环 → V3 L915 (PR #346 merged e5c54f8). 风控 reflector ≠ V2.1 Eval Agent.
```

**不建议 retire**: V2.1 是唯一 AI 因子/策略闭环 design doc, V3 不覆盖此范围.

## § 5 Cite source (4-element verified)

1. **CLAUDE.md §文档查阅索引** "AI闭环/因子发现" cite: `D:\quantmind-v2\CLAUDE.md` L504 "docs/DEV_AI_EVOLUTION.md (V2.1, 650行)... V3 §S5/S6/S7/S8 ✅ merged main (PR #343-346, ~330 tests)" — verify 2026-05-25 17:23 SH ✅ (NB: cite 说 650 行, fresh wc=745 lines, +95 lines = 5-19 Session 57/58+1 addenda sediment)
2. **docs/DEV_AI_EVOLUTION.md** §1-§14 Layer 1-4 overview: L40-731 — verify 2026-05-25 17:23 SH ✅ (745 lines total)
3. **docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md** §5/§6/§7/§8 anchors: L604 / L739 / L815 / L915 — verify 2026-05-25 17:23 SH ✅ (1840 lines total)
4. **PR #343-346 merge verify**: `gh pr view N --json mergeCommit,state` 2026-05-25 17:23 SH ✅ all 4 state=MERGED, commits 9aa13ea / 460f18a / 6cd2f16 / e5c54f8

---

**Total drift**: 5 items, 0 contradictions (orthogonal frameworks). **Recommendation**: §0 cross-ref header (not retire). **Audit doc lines**: ≤100 ✅.
