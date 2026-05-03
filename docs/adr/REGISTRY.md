# ADR # Registry SSOT

> **真意义**: ADR # 真预约 / 真创建状态 single source of truth (SSOT). 沿用 SOP-6 (ADR # reservation 4 source cross-verify, LL-105 sediment 5-02 sprint close).
> **触发**: 5-02 sprint period 累计 2 次真 N×N 同步漂移 textbook 案例 (ADR-024 conflict V3 §18.1 row 4 / ADR-027 conflict 4 audit docs Layer 4 SOP candidate). 真根因 = ADR # 真预约 source 分散 (V3 §18.1 + audit docs candidate + sprint_state cite + LL backlog), 0 single source of truth.
> **修订机制**: 新 ADR # reserve 必 grep 全 docs/ + memory/ before 决议 + 同步 update 本 [REGISTRY.md](REGISTRY.md) (1 PR cover, sustained 5-02 sprint close 体例).
> **关联文档**: [docs/adr/README.md](README.md) (ADR 索引 + 模板 + 工作流) / [docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](../QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §18.1 (V3 真预约) / [LESSONS_LEARNED.md](../../LESSONS_LEARNED.md) LL-104 + LL-105 (sediment).

## 真状态总览

| ADR # | 真 file 或主题 | 真状态 | 真 source |
|---|---|---|---|
| ADR-001 | Platform 包名 `backend.qm_platform` | committed | Wave 1 sprint 早期 |
| ADR-002 | 第 2 策略 PEAD Event-driven (非 Minute Intraday) | committed | Wave 1 sprint 早期 |
| ADR-003 | Event Sourcing StreamBus + PG (非 EventStoreDB) | committed | Wave 1 sprint 早期 |
| ADR-004 | CI 3 层本地 (pre-commit + pre-push + daily full) | committed | Wave 1 sprint 早期 |
| ADR-005 | MVP 1.3c CRITICAL 不落 DB 走 critical_alert 事件 | committed | Wave 1 MVP 1.3c |
| ADR-006 | Data Framework 3 fetcher 策略 | committed | Wave 2 Data Framework |
| ADR-007 | MVP 2.3 Sub1 沿用老 backtest_run schema | committed | Wave 2 MVP 2.3 |
| ADR-008 | execution_mode 命名空间契约 (live/paper 物理隔离) | committed | Session 17-20 cutover |
| ADR-0009 | DataContract/TableContract convergence | committed | Wave 2 Data Framework |
| ADR-010 | PMS Deprecation + Risk Framework Migration (Wave 3 MVP 3.1) | committed | Session 20 (2026-04-20) |
| ADR-010-addendum | Circuit Breaker 状态机映射 RiskRule 可行性 Spike | committed | MVP 3.1 批 0 spike |
| ADR-011 | QMT/xtquant API 利用规划 + F19 根因定案 | committed | Session 22+ schtask 硬化 |
| ADR-012 | Wave 5 Operator UI Decision (Internal-only, Vue + FastAPI) | committed | Wave 4-5 plan |
| ADR-013 | RD-Agent Re-evaluation Plan (Wave 4+ Decision Gate) | committed | Wave 4 起手 |
| ADR-014 | Evaluation Gate Contract (G1-G10 + Strategy G1'-G3') | committed | Wave 3 Eval Framework |
| ADR-015 | (gap, 0 file, 0 reserve) | — | — |
| ADR-016 | (gap, 0 file, 0 reserve) | — | — |
| ADR-017 | (gap, 0 file, 0 reserve) | — | — |
| ADR-018 | (gap, 0 file, 0 reserve) | — | — |
| ADR-019 | V3 vision (5+1 层 + Tier A/B + 借鉴清单) | reserved | V3 §18.1 row 1 (4-29 决议 + 本设计) |
| ADR-020 | Claude 边界 + LiteLLM 路由 + CI lint | reserved | V3 §18.1 row 2 (4-29 决议) |
| ADR-021 | 铁律 v3.0 重构 + IRONLAWS.md 拆分 + X10 加入 | committed | Step 6.2 (2026-04-30) |
| ADR-022 | Sprint Period Treadmill 反 anti-pattern + 集中修订机制 | committed | Step 6.4 (2026-04-30/05-01) |
| ADR-023 | yaml SSOT vs DB strategy_configs deprecation (PT 生产配置唯一 SSOT) | committed | 5-02 sprint factor task 5 (注: V3 §18.1 row 3 原 cite "ADR-023 L1 实时化" 真 drift, 本 PR row 3 修订 + row 9 ADR-029 真 reserve L1 实时化) |
| ADR-024 | factor_lifecycle 与 factor_registry 语义分工显式声明 (生产生命周期 vs 设计审批) | committed | 5-02 sprint factor task (注: V3 §18.1 row 4 原 cite "ADR-024 L4 STAGED" 真 drift, PR #216 row 4 修订 + row 7 ADR-027 真 sediment, user a-iii # 下移决议) |
| ADR-025 | RAG vector store 选型 (pgvector + embedding model 决议) | reserved | V3 §18.1 row 5 (本设计 §5.4 + §20 #3, 等 user 决议) |
| ADR-026 | L2 Bull/Bear 2-Agent debate (Tier B) | reserved | V3 §18.1 row 6 (本设计 §5.3, Tier B 架构决议) |
| ADR-027 | L4 STAGED default + 反向决策权论据 + 跌停 fallback | committed | PR #216 (5-02), V3 §20.1 #1 + #7 sediment (注: 本 # 真 silent overwrite 4 audit docs 5-01 Phase 4.2 真预约 "Layer 4 SOP" candidate, 本 PR cite 修订 # 下移 ADR-030, sustained user a-iii 决议体例) |
| ADR-028 | AUTO 模式 + V4-Pro X 阈值动态调整 + Risk Memory RAG + backtest replay | committed | PR #216 (5-02), V3 §20.1 #5 + #9 sediment |
| ADR-029 | L1 实时化 + xtquant subscribe_quote 接入 | reserved | V3 §18.1 row 9 (本 PR sediment, 沿用 ADR-023 真 cite drift # 下移决议, V3 Tier A Sprint 3 真起手时 sediment) |
| ADR-030 | Layer 4 SOP 沉淀 (governance protocol) | reserved | 4 audit docs (5-01 Phase 4.2 sediment) sustained 下移 (本 PR sediment, 沿用 ADR-024/027 conflict # 下移体例, audit Week 2 候选讨论时 sediment) |
| ADR-031 | S2 LiteLLMRouter implementation path 决议 (新建模块 + 渐进 deprecate) | committed | V3 Sprint 1 S8 audit sediment (2026-05-03), user X2=(ii) 决议, 沿用 ADR-020 + ADR-022 + V3 §5.5 真预约 |
| ADR-032 | S4 caller bootstrap factory + naked LiteLLMRouter export 限制 | committed | V3 Sprint 1 S4 sub-task sediment (2026-05-03 PR #226), 沿用 ADR-022 反 silent overwrite + ADR-031 §6 渐进 deprecate plan 前置 enforcement |

## 真状态分布

- **committed (真 file 真在 docs/adr/)**: 23 个 (ADR-001~014 + ADR-021/022/023/024/027/028/031/032)
- **reserved (V3 §18.1 真预约, 0 file 等真起手时 sediment)**: 6 个 (ADR-019/020/025/026/029/030)
- **gap (0 file, 0 reserve)**: 4 个 (ADR-015/016/017/018, 历史跳号 sustained)

总 33 # space (含 gap), 真活跃 29 (committed 23 + reserved 6).

## 真 maintenance 规则

### 新 ADR # reserve 真 SOP-6 cross-verify (沿用 LL-105 sediment)

新 # reserve 前必 grep 4 source:

1. **V3 §18.1** (`docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` §18.1 表格): risk framework V3 真预约 (含 Tier A/B 实施 plan)
2. **audit docs candidate** (`docs/audit/**/*.md`): sprint period audit 中 sediment 的 candidate 主题 (e.g. 4 audit docs 真 ADR-027 candidate 5-01 Phase 4.2)
3. **sprint_state cite** (`memory/project_sprint_state.md` frontmatter + handoff): sprint period 中 cited 的 candidate
4. **LL backlog** (`LESSONS_LEARNED.md`): LL sediment 中 candidate 主题

任一 source 真 cite 漂移 → STOP 反问 user (沿用 SOP-1 / SOP-3 体例).

### 新 ADR file 创建时同步 update 本 [REGISTRY.md](REGISTRY.md)

- 新 # 从 reserved → committed 时, 修改本 registry 真状态 + source
- 真 file 创建 时 sustained PR 1 cover (本 registry update + new ADR file 同 PR)

### 现 reserved # 起手时同步 update

- ADR-019/020 (V3 vision / Claude 边界): V3 实施时 sediment
- ADR-025 (RAG vector store): user 决议 vector store 选型时 sediment
- ADR-026 (Bull/Bear 2-Agent): Tier B 架构决议时 sediment
- ADR-029 (L1 实时化 + xtquant subscribe_quote): V3 Tier A Sprint 3 真起手时 sediment
- ADR-030 (Layer 4 SOP): audit Week 2 候选讨论时 sediment

> **新 committed**: ADR-031 (S8 audit, 2026-05-03 PR #220) — S2 LiteLLMRouter implementation path 决议, S2 真起手时引用本 ADR 真渐进 deprecate plan.

## 历史 N×N 同步漂移 真案例

### 案例 1: ADR-024 conflict (V3 §18.1 row 4)

- **触发**: 5-02 sprint period 早期 ADR-024 真 file 真主题 = factor lifecycle (5-02 sprint factor task), 真未交叉 verify V3 §18.1 row 4 真预约 "L4 STAGED"
- **CC 主动发现**: 5-02 sprint close session V3 §20.1 sediment 时 grep 全 ADR # 发现 ADR-024 真主题真冲突
- **user 决议**: (a-iii) # 下移 sustained ADR-024 0 改动, 新创建 ADR-027 (PR #216)
- **修复**: V3 §18.1 row 4 cite 修订 (PR #216) + ADR-027 真 file 创建 (PR #216)

### 案例 2: ADR-027 conflict (4 audit docs Layer 4 SOP candidate)

- **触发**: PR #216 ADR-027 真 file 真主题 = L4 STAGED, 真 silent overwrite 5-01 Phase 4.2 audit 4 docs sustained 真预约 ADR-027 = Layer 4 SOP (governance protocol)
- **CC 主动发现**: PR #217 sync session 真 grep 全 docs/audit/ 发现 4 audit docs cite "ADR-027 candidate (Layer 4 SOP 沉淀)" 真预约
- **user 决议**: 1 PR cover 真根本性处置 (本 PR), 沿用 (a-iii) # 下移 ADR-030 (Layer 4 SOP 真 reserve sediment)
- **修复**: 4 audit docs cite 修订 (本 PR Part B) + V3 §18.1 row 10 ADR-030 真预约 (本 PR Part C) + 本 [REGISTRY.md](REGISTRY.md) 真 SSOT 创建 (本 PR Part A) + LL-105 SOP-6 sediment (本 PR Part F)

### 案例 3 (附 V3 §18.1 row 3): ADR-023 conflict (V3 §18.1 row 3)

- **触发**: 5-02 sprint factor task 5 真 file 真主题 = yaml-ssot-vs-db-strategy-configs-deprecation, 真 silent overwrite V3 §18.1 row 3 真预约 "L1 实时化"
- **CC 主动发现**: 5-02 sprint close PR #217 sync session 真 P3 bonus drift report
- **user 决议**: 1 PR cover 真根本性处置 (本 PR), 沿用 (a-iii) # 下移 ADR-029 (L1 实时化 真 reserve sediment)
- **修复**: V3 §18.1 row 3 cite 修订 + row 9 ADR-029 真预约 (本 PR Part C) + 本 [REGISTRY.md](REGISTRY.md) 真 SSOT 创建 (本 PR Part A)

## footer

- **维护频率**: 每次新 ADR # reserve / 创建时同步 update (1 PR cover)
- **真 SSOT**: 本 [REGISTRY.md](REGISTRY.md) 是 ADR # 真预约 / 真创建状态唯一权威源 (沿用 LL-105 SOP-6 sediment 5-02 sprint close)
- **现 last update**: 5-02 sprint period (3 N×N 同步漂移 textbook 案例 sustained 真根本性处置)
