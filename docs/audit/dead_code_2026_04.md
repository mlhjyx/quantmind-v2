# Dead Code Monthly Audit — 2026-04

> **Date**: 2026-04-21 (Session 21 下午 inaugural, LL-063 月度规则首次兑现)
> **Scope**: DB 空表扫描 (79 public tables 全扫) — 代码层 dead code 下次审 (需 pyflakes/vulture)
> **Method**: PL/pgSQL DO block 对每表 `SELECT COUNT(FROM LIMIT 1)`, 排除 TimescaleDB hypertables (factor_values/klines_daily)
> **下次审**: 2026-05-21 ± 7 日

---

## Summary

| 维度 | 数 |
|---|---|
| 扫描表数 | 79 (public schema) |
| 空表数 | **25** (CLAUDE.md L452 记 24, drift +1 待纠) |
| 空表总大小 | ~450 KB (dust-level, 无磁盘压力) |
| 确认死码 (ADR-010/正式废弃) | 2: `position_monitor` / `circuit_breaker_log` |
| Future feature 锚点 (保留) | 19 |
| 需调查 (schema 用途不明) | 4 |

## Classification

### Category A — 确认死码, DROP 候选 (2)

| 表 | 大小 | 废弃路径 |
|---|---|---|
| `position_monitor` | 8 KB | ADR-010 PMS deprecation. Risk Framework MVP 3.1 批 1 `risk_event_log` 上线+稳定 2 周后 DROP |
| `circuit_breaker_log` | 64 KB | 现 circuit_breaker_state 表用, log 设计未启. ADR-010 Risk Framework MVP 3.1 批 3 迁入 `risk_event_log`, 同期 DROP |

### Category B — Future anchor (19, 保留)

**AI 闭环** (Wave 3+ 未实现):
- `agent_decision_log` (16 KB)
- `ai_parameters` (24 KB)

**Forex module** (DEFERRED, docs/DEV_FOREX.md):
- `forex_bars` (8 KB) / `forex_events` (16 KB) / `forex_swap_rates` (8 KB)

**GP / 因子研究基础设施** (部分启用):
- `experiments` (16 KB) / `factor_evaluation` (24 KB) / `factor_mining_task` (16 KB)
- `mining_knowledge` (48 KB, 基于 Spearman>0.7 判重, GP 去重锚点)
- `model_registry` (16 KB) — ML 模型注册 (G1 CLOSED 但 Wave 3+ 可能复用)

**审批流 / 审计基础设施** (未启):
- `approval_queue` (16 KB) / `gp_approval_queue` (40 KB)
- `operation_audit_log` (24 KB) / `param_change_log` (16 KB)
- `pipeline_run` (16 KB) — pipeline orchestrator 部分实现

**通知系统** (未启):
- `notification_preferences` (16 KB)

**BaoStock 扩展数据** (未拉):
- `bs_balance_data` (8 KB) / `bs_cash_flow_data` (8 KB) / `bs_dupont_data` (8 KB)
- 比率指标 (非原始资产负债表), 目前不需

**回测持久化** (MVP 2.3 Sub1 后可能填):
- `backtest_holdings` (8 KB) / `backtest_wf_windows` (16 KB)

**风险提示**:
- `chip_distribution` (8 KB) — comment 明言"数据质量存疑, Phase 0 不依赖筹码类因子". Phase 1 复活或 DROP 待决

### Category C — 需调查 (4)

- `universe_daily` (8 KB) — 推测被 `stock_status_daily` 替代, 但无 DDL/service 明示. **action**: grep service + migration 确认后决定保/删
- `mining_knowledge` (48 KB) — comment 描述 GP 去重, 但 GP 实际是否写入? **action**: grep `INSERT INTO mining_knowledge`
- `notification_preferences` (16 KB) — DEV_NOTIFICATIONS.md 设计存在, 实际 service 未启. **action**: 决定 Wave 4 MVP 4.1 Observability 启用或 DROP
- `chip_distribution` (8 KB) — comment "Phase 0 不依赖, 数据质量存疑". **action**: Phase X+ 评估再决定

---

## LL-063 三问法应用验证

`position_monitor` 用 LL-063 三问法检测, **全部红灯**, 证明模型有效:

- **a. 核心输出表有行?** 0 行 → 🔴
- **b. 告警链路有消费者?** `grep XREAD qm:pms` = 0 → 🔴
- **c. 触发条件下代码路径能走完?** `entry_price=0` 静默 skip → 🔴

---

## Follow-up Actions

### 立即 (Session 22 可做)
- [ ] `universe_daily` grep service + migration 调查 (~15 min)
- [ ] `mining_knowledge` grep GP insert 路径调查 (~10 min)

### 下次月审 (2026-05-21)
- [ ] 重跑本 DO block 扫
- [ ] 比对 2026-04 → 2026-05 的 Category 迁移 (新增 empty / 从 empty 变有行)
- [ ] 代码层 dead code audit (pyflakes / vulture / ts-prune 扫)

### ADR-010 推进依赖
- [ ] MVP 3.1 批 1 (PMS→`risk_event_log`) 完成 + 稳定 2 周 → DROP `position_monitor`
- [ ] MVP 3.1 批 3 (CB→`risk_event_log`) 完成 + 稳定 2 周 → DROP `circuit_breaker_log`

### CLAUDE.md 数字同步
CLAUDE.md L452 "空表 24 张" → **25 张**, Session 22 CLAUDE.md PR 中顺带改 (PR 必走 per 铁律 42).

---

## References

- LL-063 "假装健康的死码比真坏的更危险" (本 audit 的方法论源)
- ADR-010 PMS Deprecation + Risk Framework (position_monitor / circuit_breaker_log DROP 路径)
- SYSTEM_STATUS.md §空表列表 (需对齐)
- CLAUDE.md L452 空表 count (25 vs 24 drift, 待 Session 22 修)
