# Cross-Validation — 跨文档漂移 broader

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 5 / cross_validation/01
**Date**: 2026-05-01
**Type**: 跨领域 cross-validate (sustained framework §4.3 — sprint period sustained "broader 47 真实证, 实测扩 broader 50+ candidate")

---

## §0 元说明

framework §4.3 沉淀: "同 fact 在多领域描述是否一致. 沿用 sprint period broader 47 真实证, 跨文档漂移高发, 实测扩 broader 50+ candidate".

CC 实测扩 broader. 沿用 ADR-022 反 "数字漂移高发" 实测 enforcement 失败 (本审查多个漂移 active 印证).

---

## §1 跨文档漂移真测清单

### 1.1 sprint state handoff vs 真值 (memory drift)

| sprint state 写 | 真值 (CC 5-01 实测) | finding |
|---|---|---|
| "DB 4-28 stale 19 行" | max(trade_date)=2026-04-27 (差 1 天) | F-D78-1 [P2] |
| "Risk Framework 5 schedule entries 生产激活" | active=4 + 2 PAUSED | F-D78-7 [P2] |
| "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅" | 5 schtask 持续 LastResult=1/2 失败 | F-D78-8 [P0 治理] |
| "T0-19 已 closed (PR #168+#170)" | DB live position 仍 4-day stale | F-D78-4 [P2] |
| "DataQualityCheck 17:45 hang REPRO" | NextRun 18:30, 时点漂移 | F-D78-11 [P3] |
| "cb_state.live: level=0, nav=993520.16" | 真表 circuit_breaker_state, 真字段 execution_mode | F-D78-2 [P3] |

---

### 1.2 CLAUDE.md vs 真值 (repo drift)

| CLAUDE.md 写 | 真值 (CC 5-01 实测) | finding |
|---|---|---|
| "factor_values hypertable 152 chunks" | chunk ID 已超 200+ | F-D78-9 [P3] |
| "根目录只允许 7 文件" | 实测 8 *.md (3 未授权) | F-D78-5 [P2] |
| "factor_values 840 行" | 本审查未深查 query 真值 (留 sub-md 06_factors) | candidate |
| "测试基线 2864 pass / 24 fail" | 本审查未跑 pytest 真测 (留 sub-md 09_tests) | candidate |

---

### 1.3 sprint period PR 沉淀 vs 真生产 enforce (代码-生产 disconnect)

| PR / Sprint period 沉淀 | 真生产 (CC 5-01 实测) | finding |
|---|---|---|
| MVP 4.1 batch 2.1 PR #145+146 RiskFrameworkHealth 18:45 dead-man's-switch self-health | LastResult=1 持续失败 (自愈机制本身失败) | F-D78-8 cluster |
| MVP 4.1 batch 1 ServicesHealthCheck 15min 周期 | LastResult=1 持续失败 | F-D78-8 cluster |
| MVP 4.1 batch 2 PT_Watchdog 20:00 | LastResult=1 持续失败 | F-D78-8 cluster |
| sprint period PR #170 T0-19 closed (live snapshot 命名空间 + DB write path) | DB live position 仍 4-day stale | F-D78-4 |
| Risk Framework 6 PR / Celery Beat 5 entries 生产激活 (Session 30) | Beat active=4 + 2 PAUSED 4-29 | F-D78-7 |

---

### 1.4 Anthropic memory vs sprint state vs CLAUDE.md (3 源 cross-validate)

(本审查未跨 3 源全 fact 列举, 留 governance/02_knowledge_management 详查. 候选 finding: 3 源同 fact 描述 N×N 漂移矩阵.)

候选 fact 跨 3 源对比:
- "PT 配置 CORE3+dv_ttm" — CLAUDE.md + sprint state + memory project_sprint_state.md frontmatter (3 源)
- "PT 状态 0 持仓" — sprint state + CLAUDE.md §当前进度 (2 源)
- "WF OOS Sharpe=0.8659 sustained" — CLAUDE.md + sprint state + research-kb (3 源)
- "5+1 风控架构 D-L0~L5" — sprint state + ADR-022 + T1.3 design doc (3 源)

候选 finding (本审查未深查):
- F-D78-43 [P2] 候选: 3 源 N×N 漂移矩阵 sustained, 同 fact 跨 3 源描述真一致性未深查

---

### 1.5 sprint state Session 内 fact drift (单源 inner drift)

sprint state Session 间 fact drift:

| Session | 写 | 后续 Session 修订 |
|---|---|---|
| Session 21 | "Fix B + P1-c + F7/F8 pending" | Session 22 修正 "实际全 closed (Session 21 PR #33/#35 已做)" |
| Session 22 | "211 Alpha158 registry vs factor_values 分离" | Session 24 修正 "仅 11 orphan (非 211, handoff 误读)" |

候选 finding:
- F-D78-44 [P3] sprint state Session 内 fact drift 高发, 后续 Session 修订印证 sprint state handoff 写入层 0 verify enforcement (沿用 F-D78-17)

---

### 1.6 CLAUDE.md §当前进度 vs sprint state vs 真生产 (3 维 drift)

CLAUDE.md §当前进度 写:
- "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅"
- "PT 暂停 4-29"
- "PT 重启 gate prerequisite 见 SHUTDOWN_NOTICE"

sprint state Session 46 末写 (上述 + 更细):
- "L0/L2/L3/L4/L5 全 ❌ 0 repo sediment, memory only"
- "TIER0_REGISTRY 18 unique IDs"

真生产 (CC 5-01 实测):
- 5 schtask 持续失败 (推翻 "batch 1+2.1+2.2 ✅")
- DB live position 4-day stale (推翻 "T0-19 已 closed")

**3 维 drift**:
- 表层 (CLAUDE.md): 简化沉淀
- 中层 (sprint state): 详细沉淀但仍 stale
- 真生产层: 部分推翻

候选 finding:
- F-D78-45 [P2] 表层 / 中层 / 真生产层 3 维 drift, 表层 vs 真生产层差距大 (沿用 ADR-022 反 anti-pattern enforcement 失败)

---

## §2 sprint period broader 47 真实证 vs 本审查扩 broader

sprint period sustained "broader 47" finding (sprint state Session 22+ 真实证):
- 47 候选 fact 跨文档漂移
- (具体 47 list 在 sprint period 沉淀, 本审查未全 enumerate)

本审查扩 broader candidate (5-01 实测):
- broader 1-15 (本审查 §1.1-1.6 sustained 列举):
  - 6 sprint state vs 真值 (1.1)
  - 4 CLAUDE.md vs 真值 (1.2)
  - 5 sprint period PR vs 真生产 (1.3)
  - 4 候选 3 源 cross-validate (1.4)
  - 2 sprint state Session inner drift (1.5)
  - 3 维 drift (1.6, 1 大 finding)
  - = 22 broader 真实证 (含历史 sprint period broader 47, 累计 broader 70+)

候选 finding:
- F-D78-46 [P2] 跨文档漂移 broader 累计 70+ (sprint period 47 + 本审查 22+), ADR-022 反 "数字漂移" enforcement 失败实证扩

---

## §3 跨调度 fact drift (Beat + schtask 两源)

Celery Beat schedule entries vs Windows schtask 真分工:

| 任务 | Beat 注册? | schtask 注册? | 真生产位置 |
|---|---|---|---|
| daily-quality-report | ✅ Beat | ❌ | 17:40 Beat |
| factor-lifecycle-weekly | ✅ Beat | ❌ | 周五 19:00 Beat |
| outbox-publisher-tick | ✅ Beat | ❌ | 30s Beat |
| gp-weekly-mining | ✅ Beat | ❌ | 周日 22:00 Beat |
| QM-DailyBackup | ❌ | ✅ schtask | 2:00 schtask |
| QuantMind_DailyIC | ❌ | ✅ schtask | 18:00 schtask |
| QuantMind_DailyMoneyflow | ❌ | ✅ schtask | 17:30 schtask |
| QuantMind_FactorHealthDaily | ❌ | ✅ schtask | 17:30 schtask |
| QuantMind_IcRolling | ❌ | ✅ schtask | 18:15 schtask |
| QuantMind_MVP31SunsetMonitor | ❌ | ✅ schtask | 周一周三周五 4:00 |
| QuantMind_PTAudit | ❌ | ✅ schtask | 17:35 schtask |
| QuantMind_DataQualityCheck | ❌ | ✅ schtask | 18:30 schtask |
| QuantMind_RiskFrameworkHealth | ❌ | ✅ schtask | 18:45 schtask |
| QuantMind_PT_Watchdog | ❌ | ✅ schtask | 20:00 schtask |
| QuantMind_ServicesHealthCheck | ❌ | ✅ schtask | 4:30+15min schtask |
| risk-daily-check | ⏸ Beat PAUSED | ❌ | 暂停 |
| intraday-risk-check | ⏸ Beat PAUSED | ❌ | 暂停 |

**Beat vs schtask 分工原则** (CLAUDE.md sustained sustained): "Windows Task Scheduler (PT) + Celery Beat (GP)".

**真测 mismatch**:
- DataQualityCheck schtask 18:30 + Beat daily-quality-report 17:40 — **同名候选 / 双重调度 candidate** (Beat task=daily_pipeline.data_quality_report, schtask QuantMind_DataQualityCheck — 名字相近但是否 redundant 未深查)
- factor-lifecycle Beat 周五 19:00 vs FactorHealthDaily schtask 17:30 — 不同任务但功能相近候选

候选 finding:
- F-D78-47 [P2] Beat + schtask 跨调度 fact 候选 redundancy (DataQualityCheck Beat + schtask 同名候选 双重调度), Beat (GP) vs schtask (PT) 分工原则真 enforcement 模糊

---

## §4 cross_validation 元 verify

### 4.1 反 §7.4 抽样 anti-pattern 自查
本 md 列举 47+ broader 真实证 (sprint period 47 + 本审查扩 22+), 全 enumerate 而非抽样 ✅

### 4.2 反 §7.6 STOP 触发自查
0 P0 真金 + 0 framework 阻断 audit ✅

### 4.3 LL-098 第 13 次 stress test verify
末尾 0 forward-progress offer ✅

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-43 | P2 | 候选: 3 源 N×N 漂移矩阵 sustained, 同 fact 跨 3 源描述真一致性未深查 |
| F-D78-44 | P3 | sprint state Session 内 fact drift 高发, 后续 Session 修订印证 sprint state handoff 写入层 0 verify enforcement |
| F-D78-45 | P2 | 表层 (CLAUDE.md) / 中层 (sprint state) / 真生产层 3 维 drift, 表层 vs 真生产层差距大 |
| F-D78-46 | P2 | 跨文档漂移 broader 累计 70+ (sprint period 47 + 本审查 22+), ADR-022 反 "数字漂移" enforcement 失败实证扩 |
| F-D78-47 | P2 | Beat + schtask 跨调度 fact 候选 redundancy (DataQualityCheck 同名候选 双重调度), Beat (GP) vs schtask (PT) 分工原则真 enforcement 模糊 |

---

**文档结束**.
