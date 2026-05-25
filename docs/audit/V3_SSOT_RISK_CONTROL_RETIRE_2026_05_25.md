# V3 SSOT Risk Control Retire Audit (task_005)

**Date**: 2026-05-25 17:22 SH
**Scope**: `docs/RISK_CONTROL_SERVICE_DESIGN.md` (legacy, PARTIALLY DEPRECATED) vs `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` (V3 SSOT)
**Trigger**: CLAUDE.md §文档查阅索引 line 503 cite "已 PARTIALLY DEPRECATED, 勿作当前设计"

---

## §1 老 RISK_CONTROL_SERVICE_DESIGN.md sections inventory

| # | Section | Lines | Notes |
|---|---------|-------|-------|
| Header | DEPRECATION header (lines 1-26) | 26 | 2026-05-19 + 2026-05-20 audit sediment |
| §1 | 背景与动机 | 34-43 | sustained 真问题描述 |
| §2 | 4级熔断状态机 (L0-L4) | 46-99 | §2.1 状态定义 / §2.2 转换规则 / §2.3 行为矩阵 |
| §3 | 数据模型 (circuit_breaker_state + log) | 101-145 | 2 表 schema |
| §4 | 接口定义 (RiskControlService Python class) | 149-591 | enum + dataclass + method 签名 |
| §5 | 调用方集成 (调度链路 + 前端 API) | 595-650 | run_paper_trading.py + 5 REST endpoints |
| §6 | L3 降仓与回补流程 | 654-677 | streak counting 文字描述 |
| §7 | 与现有系统的关系 | 681-691 | 6 组件交互表 |
| §8 | 测试策略 (unit + integration) | 695-711 | 7 unit + 4 integration case |

**Total**: 711 lines, 8 顶层 § + DEPRECATION header.

---

## §2 V3 SSOT 已覆盖列

| 老 § | V3 SSOT 对应位置 | 覆盖度 |
|---|---|---|
| §1 背景与动机 | V3 §0.1-§0.4 (4-29 PT 暂停清仓事件 + 现状诊断 + hypothesis + 目标) | ✅ 100% + 升级 (真账户 ground truth) |
| §2 L0-L3 状态机 (NORMAL/L1_PAUSED/L2_HALTED/L3_REDUCED) | V3 §4 L1 PMSRule 3 档 (PMSRule L1/L2/L3) + V3 §6 L3 DynamicThresholdEngine (Calm/Stress/Crisis) | ✅ semantic 重命名 (L0-L3 → PMS L1-L3 + DT 3 级) |
| §2 L4_STOPPED (累计-25% 人工审批) | V3 §7 L4 STAGED default + 反向决策权 + 跌停 fallback (ADR-027) | ✅ 重定义 (旧逻辑 deprecated) |
| §3 数据模型 (circuit_breaker_state/log) | V3 §10 schema (risk_event_log 扩展 + execution_plans + market_regime_log + dynamic_threshold_adjustments + risk_memory) | ✅ schema 现代化 (TimescaleDB hypertable + JSONB) |
| §4 RiskControlService 接口 | V3 §11 接口契约 + 模块边界 (RealtimeRiskEngine / L4ExecutionPlanner / DynamicThresholdEngine / RiskReflector 多 service 拆分) | ✅ 单一 service → 5+1 层 service |
| §5 调用方集成 | V3 §2.3 闭环路径 + V3 §9 端到端 24h cycle | ✅ |
| §6 L3 降仓回补 | V3 §7.3 Trailing Stop (ATR 动态) + V3 §7.2 Batched 平仓 | ✅ 静态 → 动态升级 |
| §7 现有系统关系 | V3 §11 模块边界 + V3 §10 schema 关系 | ✅ |
| §8 测试策略 | V3 §15 测试策略 | ✅ |

---

## §3 V3 SSOT 未覆盖列

经逐节核对, **V3 SSOT 已 100% 覆盖** 老 file 全部 valid 章节. 老 file §2 L4_STOPPED 自动审批逻辑被 ADR-027 SEMANTIC REDEFINED (非未覆盖, 是 deprecated). 0 gap.

唯一名义差异: 老 file 的 `circuit_breaker_state` / `circuit_breaker_log` 表名 → V3 重组为 `risk_event_log` 扩展 + `execution_plans` + `dynamic_threshold_adjustments` 3 表分离. 这是 schema 进化, 非功能 gap.

---

## §4 推荐 verdict

**Recommendation**: **FULL RETIRE (physical archive)** — move file to `docs/archive/RISK_CONTROL_SERVICE_DESIGN_2026_05_25_archived.md` + add forward-only redirect stub at original path.

**Rationale**:
1. 现 DEPRECATION header (26 lines) 已 cite V3 + ADR-027 真值 source priority
2. V3 SSOT 100% 覆盖 + L4 portion semantic conflict (ADR-027 重定义)
3. sustained PR/audit 已 7+ 周 (5-19 → 5-25) 反复修订 header, 维护成本 > 历史价值
4. archive 后任 grep `RISK_CONTROL_SERVICE_DESIGN.md` cite 走 redirect stub → V3 + ADR-027

**Fallback** (if user 反对 physical archive): keep file + add `> **ARCHIVED — see [V3 SSOT](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md)**` redirect header (line 1, before current DEPRECATION header). 0 文件移动, 仅 header 升级.

**推荐路径**: 走 FULL RETIRE (archive + stub), 减 6 doc → 5 doc 维护负担, sustained Wave 4 closeout 减债.

---

## §5 Cite source (4-element)

1. **CLAUDE.md** | line 503 | §文档查阅索引 "PARTIALLY DEPRECATED" cite | verified 2026-05-25 17:22 SH (Grep result line 503)
2. **docs/RISK_CONTROL_SERVICE_DESIGN.md** | line 1-26 | DEPRECATION header + line 711 total | verified 2026-05-25 17:22 SH (Read + wc -l)
3. **docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md** | §4 line 476 / §6 line 739 / §7.3 line 853 / §8 line 915 + 1840 total | L1 PMSRule + DynamicThreshold + trailing_stop + RiskReflector | verified 2026-05-25 17:22 SH (Read + Grep + wc -l)
4. **task spec** | docs/taskboard/queue/task_005_v3_ssot_risk_control_retire_check.md | line 24 acceptance | verified 2026-05-25 17:22 SH

**红线 5/5 sustained**: 任 .env / broker / DB row mutation / yaml / production code 改动 — 本 task 0 触发, 纯 doc audit.
