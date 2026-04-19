# Architecture Decision Records (ADR)

> Supplements `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (Blueprint = 长期架构真相源, 铁律 38).
> ADR = 细粒度的独立决策记录, 每条决策一份 markdown.
> **双源**: markdown 是权威 (版本控制 + 人类可读); `adr_records` DB 表是查询索引 (`list_by_ironlaw`).

## 索引

| ADR | 标题 | 状态 | 关联铁律 |
|---|---|---|---|
| [ADR-001](ADR-001-platform-package-name.md) | Platform 包名 `backend.platform` | accepted | 38 |
| [ADR-002](ADR-002-pead-as-second-strategy.md) | 第 2 策略 PEAD Event-driven (非 Minute Intraday) | accepted | 38 |
| [ADR-003](ADR-003-event-sourcing-streambus.md) | Event Sourcing StreamBus + PG (非 EventStoreDB) | accepted | 22, 38 |
| [ADR-004](ADR-004-ci-3-layer-local.md) | CI 3 层本地 (pre-commit + pre-push + daily full) | accepted | 22, 40 |
| [ADR-005](ADR-005-critical-not-db-event.md) | MVP 1.3c CRITICAL 不落 DB 走 critical_alert 事件 | accepted | 33 |
| [ADR-006](ADR-006-data-framework-3-fetcher-strategy.md) | Data Framework 3 fetcher 策略 | accepted | — |
| [ADR-007](ADR-007-mvp-2-3-backtest-run-alter-strategy.md) | MVP 2.3 Sub1 沿用老 backtest_run schema | accepted | 15, 17, 22, 25, 36, 38 |
| [ADR-008](ADR-008-execution-mode-namespace-contract.md) | execution_mode 命名空间契约 (live/paper 物理隔离) | accepted | 25, 33, 34, 36, 39 |
| [ADR-0009](ADR-0009-datacontract-tablecontract-convergence.md) | DataContract/TableContract convergence | accepted | — |

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
