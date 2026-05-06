# Architecture Decision Records (ADR)

> Supplements `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (Blueprint = 长期架构真相源, 铁律 38).
> ADR = 细粒度的独立决策记录, 每条决策一份 markdown.
> **双源**: markdown 是权威 (版本控制 + 人类可读); `adr_records` DB 表是查询索引 (`list_by_ironlaw`).

## 索引

| ADR | 标题 | 状态 | 关联铁律 |
|---|---|---|---|
| [ADR-001](ADR-001-platform-package-name.md) | Platform 包名 `backend.qm_platform` | accepted | 38 |
| [ADR-002](ADR-002-pead-as-second-strategy.md) | 第 2 策略 PEAD Event-driven (非 Minute Intraday) | accepted | 38 |
| [ADR-003](ADR-003-event-sourcing-streambus.md) | Event Sourcing StreamBus + PG (非 EventStoreDB) | accepted | 22, 38 |
| [ADR-004](ADR-004-ci-3-layer-local.md) | CI 3 层本地 (pre-commit + pre-push + daily full) | accepted | 22, 40 |
| [ADR-005](ADR-005-critical-not-db-event.md) | MVP 1.3c CRITICAL 不落 DB 走 critical_alert 事件 | accepted | 33 |
| [ADR-006](ADR-006-data-framework-3-fetcher-strategy.md) | Data Framework 3 fetcher 策略 | accepted | — |
| [ADR-007](ADR-007-mvp-2-3-backtest-run-alter-strategy.md) | MVP 2.3 Sub1 沿用老 backtest_run schema | accepted | 15, 17, 22, 25, 36, 38 |
| [ADR-008](ADR-008-execution-mode-namespace-contract.md) | execution_mode 命名空间契约 (live/paper 物理隔离) | accepted | 25, 33, 34, 36, 39 |
| [ADR-0009](ADR-0009-datacontract-tablecontract-convergence.md) | DataContract/TableContract convergence | accepted | — |
| [ADR-010](ADR-010-pms-deprecation-risk-framework.md) | PMS Deprecation + Risk Framework Migration (Wave 3 MVP 3.1) | accepted | 23, 24, 31, 33, 34, 36, 38 |
| [ADR-010-addendum](ADR-010-addendum-cb-feasibility.md) | Circuit Breaker 状态机映射 RiskRule 可行性 Spike (MVP 3.1 批 0) | accepted | 24, 31, 36 |
| [ADR-011](ADR-011-qmt-api-utilization-roadmap.md) | QMT/xtquant API 利用规划 + F19 根因定案 | accepted | — |
| [ADR-012](ADR-012-wave-5-operator-ui.md) | Wave 5 Operator UI Decision (Internal-only, Vue + FastAPI) | accepted | 22, 23, 24, 33, 36, 38, 42 |
| [ADR-013](ADR-013-rd-agent-revisit-plan.md) | RD-Agent Re-evaluation Plan (Wave 4+ Decision Gate) | accepted | 21, 23, 25, 38 |
| [ADR-014](ADR-014-evaluation-gate-contract.md) | Evaluation Gate Contract (G1-G10 + Strategy G1'-G3') | accepted | 4, 5, 12, 13, 15, 18, 19, 20 |
| [ADR-021](ADR-021-ironlaws-v3-refactor.md) | 铁律 v3.0 重构 + IRONLAWS.md 拆分 + X10 加入 | accepted | 全 |
| [ADR-022](ADR-022-sprint-treadmill-revocation.md) | Sprint Period Treadmill 反 anti-pattern + 集中修订机制 | accepted | 22, 25, 27 |
| [ADR-023](ADR-023-yaml-ssot-vs-db-strategy-configs-deprecation.md) | yaml SSOT vs DB strategy_configs deprecation (PT 生产配置唯一 SSOT) | proposed | 22, 25, 34, 38 |
| [ADR-024](ADR-024-factor-lifecycle-vs-registry-semantic-separation.md) | factor_lifecycle 与 factor_registry 语义分工显式声明 (生产生命周期 vs 设计审批) | proposed | 22, 25, 38 |
| [ADR-027](ADR-027-l4-staged-default-reverse-decision-with-limit-down-fallback.md) | L4 STAGED default + 反向决策权论据 + 跌停 fallback (V3 §20.1 #1 + #7 sediment) | proposed | 22, 25, 27, 33, 35 |
| [ADR-028](ADR-028-auto-mode-v4-pro-rag-and-backtest-replay.md) | AUTO 模式 + V4-Pro X 阈值动态调整 + Risk Memory RAG + backtest replay (V3 §20.1 #5 + #9 sediment) | proposed | 22, 25, 27, 33, 35 |
| [ADR-032](ADR-032-s4-caller-bootstrap-factory-and-naked-router-export-restriction.md) | S4 caller bootstrap factory + naked LiteLLMRouter export 限制 | accepted | 22, 25, 27, 33, 34 |
| [ADR-033](ADR-033-news-source-replacement-decision.md) | News 源替换决议 (5-02 sprint period sediment, V3 §3.1 + §20.1 #10 patch) | accepted | 22, 25, 27, 34, 38 |

> **注**: ADR-019/020/025/026 sustained reserve (V3 §18.1 row 1/2/5/6 真预约, 0 file 等 user 决议时创建). ADR-024 真主题 = factor lifecycle (5-02 sprint factor task), V3 §18.1 row 4 真预约 "L4 STAGED" 已 # 下移到 ADR-027 (user a-iii 决议 5-02). 详 [ADR-027 §1.1](ADR-027-l4-staged-default-reverse-decision-with-limit-down-fallback.md). ADR-031 (S8 audit) 真 S2 LiteLLMRouter implementation path, ADR-032 真 S4 caller bootstrap factory + naked router export 限制 (V3 Sprint 1 S2-S4 sub-task sediment).

## 模板

新 ADR 走 `ADR-NNN-slug.md` 命名. YAML frontmatter + 6 section:

```markdown
---
adr_id: ADR-NNN
title: 决策简短标题 (≤ 60 字)
status: accepted      # proposed / accepted / deprecated / superseded_by:ADR-NNN
related_ironlaws: [38] # 关联铁律 id 列表
recorded_at: YYYY-MM-DD
---

## Context
背景: 问题是什么, 为何此时决策.

## Decision
决策内容: 选择哪个方案, 采纳哪个实现.

## Alternatives Considered
备选 + 为什么没选 (2-3 个).

## Consequences
后果: 正面 (收益) + 负面 (成本/约束).

## References
相关文档 / commit / issue.
```

## 工作流

1. 新决策 → 写 `docs/adr/ADR-NNN-slug.md` (人工编辑).
2. `python scripts/knowledge/register_adrs.py --apply` 扫 markdown 写 DB.
3. 过时决策 → `DBADRRegistry.supersede(old, new)` 标记 `status=superseded_by:NEW-ID` + 新 ADR 引用 old.
4. 查询 "铁律 38 关联哪些 ADR" → `DBADRRegistry.list_by_ironlaw(38)`.

## 为什么不只用 Blueprint

- **Blueprint**: 长期架构宏图, 改动少, 反映"现在应当长什么样".
- **ADR**: 每次具体决策的"当时决定 + 当时理由", 不可改 (只可 supersede). 历史记录.

Blueprint 是结果, ADR 是过程. 两者互补, 不冲突.
