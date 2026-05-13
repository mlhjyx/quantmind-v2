# ADR-019: V3 Vision — 5+1 Layer Risk Architecture + Tier A/B Phasing + Borrowing List

**Status**: Committed (reserved 2026-04-29 + formal promote 2026-05-13 via T1.5b-2 Plan v0.2 §A T1.5 Acceptance item (4) closure)
**Date**: 2026-04-29 (decision) / 2026-05-13 (formal promote)
**Decider**: User 4-29 决议
**Related**: ADR-020 (Claude 边界 + LiteLLM 路由) / ADR-021 (铁律 v3.0 + IRONLAWS) / ADR-022 (反 silent overwrite) / ADR-027 (L4 STAGED + 反向决策权) / ADR-028 (AUTO + V4-Pro X 阈值 + RAG + backtest replay) / ADR-029 (L1 实时化 + xtquant subscribe_quote) / ADR-064 (Plan v0.2 5 决议 lock) / V3_DESIGN doc itself (SSOT)

---

## §1 Context

**2026-04-29 PT 暂停清仓事件** (V3 §0.1 设计起点):

- PT 真账户 17 股 emergency_close (CC 4-29 10:43:54) + 1 股 (688121.SH 跌停 cancel → 4-30 user GUI sell) → 真账户 0 持仓 / cash=¥993,520.66 / market_value=0
- 根因: PMSRule v1 静态阈值 + 0 实时 detection + 0 News/regime context aware + STAGED 决策权缺失 + 0 反思闭环
- 痛点 surface 多维:
  - **detection latency**: PMSRule v1 14:30 daily Beat fire only, 不实时 (跌停后 ~6h 才 detect, far exceeds V3 §13.1 SLA P99 <5s baseline)
  - **context-blind**: 0 sentiment / 0 fundamental / 0 regime → 风控误报率 high (e.g. earnings reaction false positive)
  - **decision binary**: 反向决策权缺失, AUTO sell vs STAGED 30min hold 选择缺
  - **0 lesson loop**: 每事件 outcome 不沉淀 risk_memory, 类似事件重复犯错
- 经验决议: 现 PMSRule v1 不足以 cover 4-29 类 event 风控需求 → V3 重新设计

**Why V3 (vs incremental patch on PMSRule v1)**:

- 4-29 事件 surface 5 维 architectural gap (detection / context / decision / sentiment / lesson) — incremental patch 不够, 需要 full layered redesign
- 借鉴现有 4 项目最佳实践 (RD-Agent / Qlib / TradingAgents / QuantDinger) 而非自建
- 平台化路径 sustained (sustained Wave 1-4 +5 platform decision 体例)

---

## §2 Decision

### §2.1 5+1 Layer Risk Architecture

V3 风控走 **5+1 layer 架构** (sustained V3 §2.1 5+1 层数据流图 SSOT):

| layer | 职责 | 模块 (V3 §11.1) |
|---|---|---|
| **L0** 多源数据接入 | News / fundamental / 公告流 / regime indicators ingest | NewsIngestionService + NewsClassifierService + FundamentalContextService + AnnouncementProcessor |
| **L1** 基础规则层 (实时化) | 9 RealtimeRiskRule + tick-level event-driven detection | RealtimeRiskEngine (XtQuantTickSubscriber + 9 rules: LimitDown / NearLimitDown / RapidDrop5min / RapidDrop15min / GapDown / VolumeSpike / LiquidityCollapse / IndustryConcentrationDrop / TrailingStop) |
| **L2** 智能风控层 | sentiment modifier + fundamental_context + Bull/Bear regime + Risk Memory RAG | MarketRegimeService (Tier B) + RiskMemoryRAG (Tier B) |
| **L3** 动态阈值层 | 实时市场状态 + 个股动态阈值 + Concept/Industry 联动 | DynamicThresholdEngine (3 级 Calm/Stress/Crisis + ATR/beta/liquidity multiplier + S7→S5 wire back) |
| **L4** 执行优化层 | STAGED 决策权 (3 档) + Batched 平仓 + Trailing Stop + Re-entry | L4ExecutionPlanner + DingTalkWebhookReceiver + BatchedPlanner + TrailingStop + ReentryTracker |
| **L5** 反思闭环层 (+1) | 周/月/事件 5 维反思 + lesson→risk_memory 闭环 + 候选规则新增 | RiskReflectorAgent (Tier B) |

### §2.2 Tier A / Tier B 时序

**Tier A (Plan v0.1, ~6-8 weeks baseline)**: L0 + L1 + L3 + L4 完整 production-ready + RiskBacktestAdapter stub (T1.5 prereq)

- Sprint S1-S11 + S2.5 (12 sprint chain, sustained Plan v0.1 sub-PR 8 + cumulative 29 PR #296-#324 cumulative 2026-05-13 Tier A code-side closure)
- Tier A scope: 9 模块 production-ready (LiteLLMRouter + NewsIngestionService + NewsClassifierService + FundamentalContextService + AnnouncementProcessor + RealtimeRiskEngine + DynamicThresholdEngine + L4ExecutionPlanner + DingTalkWebhookReceiver) + RiskBacktestAdapter stub (S5 sub-PR 5c `a656176` 140 行 stub base)

**T1.5 transition (Plan v0.2, ~3-5 day baseline)**: Tier A formal closure + Gate A 7/8 verify + Tier A ADR cumulative promote

- T1.5a (PR #325 `3087ced`): Gate A 7/8 verify run + STATUS_REPORT sediment + interim verdict 4 PASS / 3 INCOMPLETE / 1 DEFERRED
- T1.5b chain (4 chunked sub-PR per LL-100): T1.5b-1 (item 3 retroactive ETL closure, PR #326 `71374b0` merged) + T1.5b-2 (item 4 ADR-019/020/029 promote, 本 PR sediment) + T1.5b-3 (item 8 V3 §3.5 fail-open smoke) + T1.5b-4 (ADR-065 full close + Constitution amend + STATUS_REPORT amend + LL-159)

**Tier B (Plan v0.2, ~8.5-12 weeks baseline)**: L2 (MarketRegimeService + RiskMemoryRAG) + L5 (RiskReflectorAgent) + RiskBacktestAdapter 完整实现 + replay 验收

- Sprint TB-1 (RiskBacktestAdapter full impl + 2 关键窗口 replay) → TB-2 (L2 Bull/Bear V4-Pro debate) → TB-3 (L2 RAG BGE-M3) → TB-4 (L5 RiskReflector + lesson 闭环) → TB-5 (Tier B closure + Gate B/C close)

### §2.3 借鉴清单 (4 项目 best practices)

| 项目 | 借鉴 |
|---|---|
| **RD-Agent (微软)** | 自主因子发现 pipeline + 假设驱动迭代 (Tier B Phase 3 候选, V3 NOT 借鉴 — 因子研究独立轨道, 沿用 4 因子 CORE3+dv_ttm equal-weight ceiling per Phase 2/3 NO-GO sediment) |
| **Qlib (微软)** | 数据层 + factor pipeline (V3 NOT 借鉴, 沿用自建 backend/qm_platform/factor/ + factor_values 840M rows hypertable) |
| **TradingAgents** | 5 维反思框架 (Detection / Threshold / Action / Context / Strategy) — sustained V3 §8 L5 RiskReflector 直接借鉴 + V3 §8.1 cadence (Sunday 19:00 周 / 月 1 日 09:00 / 重大事件 24h) |
| **QuantDinger** | Bull vs Bear 2-Agent debate + Memory-Augmented decision — sustained V3 §5.3 + §5.4 直接借鉴 + V4-Pro × 3 (Bull/Bear/Judge) + RiskMemoryRAG (pgvector + BGE-M3) |

### §2.4 4-29 PT 暂停清仓决议落地 (sustained 红线 5/5)

- **现状 (Session 53 cumulative)**: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 — 自 2026-04-30 user GUI sell 后 sustained
- **PT 重启 prereq**: Gate E PT cutover gate (Constitution §L10.5 + Plan v0.4 scope) — Tier A ADR + Tier B closure + 横切层 + 5 SLA + 10 user 决议 + user 显式 .env paper→live 授权 (4 锁)
- **本 ADR**: Tier A formal close 时机 sediment (T1.5b-2 cycle 2026-05-13 promote committed)

---

## §3 Consequences

### §3.1 V3 实施期总 cycle 真值

- Tier A (Plan v0.1): ~3-5 周 net new (V2 prior cumulative S1/S4/S6/S8 substantially pre-built per sub-PR 9 sediment 体例) — ✅ closed Session 53 cumulative 29 PR #296-#324
- T1.5 (Plan v0.2): ~3-5 day (Gate A 7/8 verify + Tier A ADR cumulative promote + 3 INCOMPLETE items closure)
- Tier B (Plan v0.2): ~8.5-12 weeks (TB-1~5)
- 横切层 (Plan v0.3): ≥12 weeks
- cutover (Plan v0.4): ~1 week
- **V3 总 cycle**: **~25-30 周 (~6-7 月)** baseline, replan 1.5x = ~37-45 weeks (~9-11 月)

### §3.2 ADR cumulative

post-V3 vision (本 ADR-019) sediment, Tier A 期内 cumulative ADR 共 17 (ADR-047~063):
- S1 closure: ADR-047
- S2 closure: ADR-048
- S2.5 closure: ADR-049 + ADR-050
- S3 closure: ADR-051
- S2.5 reverse decision: ADR-052
- S4 closure: ADR-053
- S5 closure: ADR-054
- S7 closure: ADR-055
- S8 (8a/8b/8c-partial/8c-followup) closure: ADR-056/057/058/059
- S9 (9a + 9b) closure: ADR-060 + ADR-061
- S10 setup closure: ADR-062
- S10 5d skip decision: ADR-063
- Plan v0.2 sediment: ADR-064

Tier B 期内候选 ADR (post-Plan v0.2 sediment): ADR-065 (T1.5 Gate A formal close) + ADR-066 (TB-1 RiskBacktestAdapter full impl) + ADR-067 (TB-2 MarketRegimeService) + ADR-068 (TB-3 RiskMemoryRAG) + ADR-069 (TB-4 RiskReflector) + ADR-070 (TB-5 replay 真测结果) + ADR-071 (TB-5 Tier B closure cumulative) = 8 items

### §3.3 5 维 architectural gap closure (Tier A 实施期内)

| gap | closure path |
|---|---|
| Detection latency (PMSRule v1 14:30 daily → V3 L1 tick-level) | S5 sub-PR 5a (PR 14) + 5b (PR 15) RealtimeRiskEngine + 9 RealtimeRiskRule production-ready (ADR-054) |
| Context-blind (0 sentiment/fundamental/regime) | S1-S4 + S2.5 L0 multi-source data ingest (LiteLLM + NewsIngestion + NewsClassifier + FundamentalContext + Announcement) production-ready |
| Decision binary (0 STAGED + 反向决策权) | S8 chunked 4 sub-PR (8a STAGED state machine + 8b webhook receiver + 8c-partial Celery sweep + 8c-followup broker_qmt wire) production-ready (ADR-056/057/058/059) |
| Sentiment modifier (Tier A 简化 / Tier B 完整) | Tier A: minimal context aware (sustained Plan v0.1 §A S4 minimal scope + ADR-053). Tier B: Bull/Bear V4-Pro debate + RAG (sustained Plan v0.2 §A TB-2 + TB-3 scope) |
| Lesson loop (Tier B scope) | Tier B TB-4 L5 RiskReflector + lesson→risk_memory 闭环 (sustained Plan v0.2 §A TB-4 scope) |

---

## §4 Cite

- V3_DESIGN §0.1 (4-29 PT 暂停清仓事件 设计起点) / §0.2 (现状诊断) / §0.3 (设计 hypothesis) / §0.4 (设计目标)
- V3_DESIGN §2.1 (5+1 层数据流图) / §2.2 (Tier A/B 时序)
- V3_DESIGN §11.1 (12 模块清单)
- V3_DESIGN §12.1 + §12.2 (Tier A + Tier B sprint 拆分)
- V3_DESIGN §13.1 (5 SLA)
- V3_DESIGN §17.1 (Claude 边界, sustained ADR-020 follow-up)
- V3_DESIGN §18.1 row 1 (本 ADR-019 reserve)
- Plan v0.1 (Tier A sprint chain SSOT)
- Plan v0.2 (Tier B sprint chain SSOT)
- Constitution §L0/L10 (V3 governance scope)
- 4 借鉴项目: RD-Agent / Qlib / TradingAgents / QuantDinger (docs/research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md cumulative)

### Related Decisions

- ADR-020 (Claude 边界 + LiteLLM 路由 + CI lint) — V3 §17.1 实施
- ADR-021 (铁律 v3.0 + IRONLAWS.md 拆分 + X10) — V3 governance pattern sustained
- ADR-022 (反 silent overwrite + 反 retroactive content edit) — V3 文档治理 pattern sustained
- ADR-027 (L4 STAGED + 反向决策权 + 跌停 fallback) — V3 §7 L4 实施
- ADR-028 (AUTO + V4-Pro X 阈值 + RAG + backtest replay) — V3 §5 L2 + §15.5 sustained
- ADR-029 (L1 实时化 + xtquant subscribe_quote) — V3 §4 L1 实施
- ADR-064 (Plan v0.2 5 决议 lock) — Tier B sprint chain sediment
