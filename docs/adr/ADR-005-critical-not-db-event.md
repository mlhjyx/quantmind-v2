---
adr_id: ADR-005
title: Factor Lifecycle CRITICAL 状态不落 DB, 走 critical_alert 事件
status: accepted
related_ironlaws: [33]
recorded_at: 2026-04-17
---

## Context

MVP 1.3c 设计 `backend/platform/factor/lifecycle.py::PlatformLifecycleMonitor` 时遇到 `FactorStatus` 枚举冲突:

- `engines/factor_lifecycle.py::FactorStatus` 5 值 (candidate / active / warning / **critical** / retired)
- `backend/platform/factor/interface.py::FactorStatus` 7 值 (candidate / **testing** / active / warning / **deprecated** / **invalidated** / retired)

Platform 版**没 CRITICAL** 状态. 但老 engines 版的语义 "WARNING 持续 20 天 ratio<0.5 → CRITICAL" 是合理的衰减阶段性标记, 不能丢.

此外 DB `factor_registry.status` 列当前实际存 3 值 (active/warning/deprecated), 加新 enum 值会引起 migration 风险.

## Decision

**CRITICAL 不落 DB** — `PlatformLifecycleMonitor` 触发 "持续 critical 阈值" 时:

- `to_status` 保 **WARNING** (不跨状态转换, DB status 仍是 warning)
- `metrics["critical_alert"] = True` 标记
- 发布 Redis Stream 事件 `qm:ai:monitoring:critical_alert` 给 L2 人 (人工审核)
- L2 人确认后通过 `update_status(name, RETIRED/DEPRECATED, reason)` 明确落 DB

Platform interface.FactorStatus 保持 7 值 (不加 CRITICAL), engines 版 5 值保留**但两者并存** (engines 做 MVP A 老路径, Platform 做新路径).

## Alternatives Considered

| 选项 | 破坏面 | DB migration | 为何不选 |
|---|---|---|---|
| **CRITICAL 不落 DB + 事件** ⭐ | 0 | 0 | — (选此, 最小破坏) |
| interface 加 CRITICAL 变 8 值 | 跨 MVP 1.1 合约 | 否 | interface 一旦改需 ADR, 影响面大 |
| DB `factor_registry.status` CHECK 加 'critical' | 老 SQL 查询潜在冲突 | 需 ALTER + 索引重建 | migration 风险 > 收益, CRITICAL 本来持续性标记, 人确认后直接到 DEPRECATED |
| 完全删 CRITICAL 概念 | 老 engines_monitor 语义丢失 | 否 | MVP A 落地了, 丢语义等同回滚 |

## Consequences

**正面**:
- 0 migration 风险 (DB schema 不动)
- interface 7 值合约不破
- critical_alert 事件通道用现有 StreamBus 基础设施 (ADR-003 同一套)
- L2 人工确认是设计意图 (铁律 33 禁 silent, critical_alert 是显式信号)

**负面**:
- 代码需记"CRITICAL 语义存在但不落库"这个微妙约定, MVP 1.3d 删老 `_constants.py` direction dict 时要留 CRITICAL 判定代码
- 前端 PMS 页面/IC 监控若要展示 critical_alert, 需订阅 Redis Stream (不能仅看 DB)
- 未来若第 3 种衰减阶段标记出现, 同样走"事件不落库"模式, 避免 enum 膨胀

## References

- `docs/mvp/MVP_1_3c_factor_framework_complete.md` §D1
- `backend/platform/factor/lifecycle.py` (MVP 1.3c 实施)
- `backend/tests/test_platform_lifecycle.py::test_warning_critical_alert_but_no_db_transition` 验证
- 铁律 33: 禁 silent failure (critical_alert 事件 = 显式通知, 非 silent)
