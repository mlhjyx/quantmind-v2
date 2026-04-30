# SYSTEM_AUDIT_2026_05 — 总入口

**Audit ID**: SYSTEM_AUDIT_2026_05
**Date**: 2026-05-01
**Type**: 一次性全方位系统审查 (read-only / 0 修改 / 0 Phase 拆分 / 0 时长限制)
**触发**: User D72-D78 反 sprint period treadmill + Claude 4 次错读 + 反 sprint period 6 块基石 sustained 假设
**Status**: 进行中

---

## 阅读顺序 (推荐)

### 第一档 — 战略 (1h 可读)
1. [`EXECUTIVE_SUMMARY.md`](EXECUTIVE_SUMMARY.md) — 顶层概览 (项目真健康度 / Top P0 / 推翻假设清单 / 战略候选)
2. [`PRIORITY_MATRIX.md`](PRIORITY_MATRIX.md) — 全 finding 严重度矩阵 (P0/P1/P2/P3)
3. [`GLOSSARY.md`](GLOSSARY.md) — 术语词典 (新 Claude session onboarding 关键)

### 第二档 — Framework + Adversarial (1-2h)
4. [`blind_spots/05_framework_self_audit.md`](blind_spots/05_framework_self_audit.md) — Framework 自身审 (CC 主动质疑 + 扩 scope 决议)
5. [`blind_spots/01_claude_assumptions.md`](blind_spots/01_claude_assumptions.md) — 推翻 Claude 假设
6. [`blind_spots/02_user_assumptions.md`](blind_spots/02_user_assumptions.md) — 推翻 user 假设
7. [`blind_spots/03_shared_assumptions.md`](blind_spots/03_shared_assumptions.md) — 推翻共同假设
8. [`blind_spots/04_unknown_unknowns.md`](blind_spots/04_unknown_unknowns.md) — Unknown unknowns

### 第三档 — 现状快照 (3-5h, 22 类)
9. [`snapshot/`](snapshot/) — Repo / DB / 服务 / 配置 / API / 依赖 / 因子 / 数据流 / 测试 / 文档 / 业务状态 / ADR-LL / 协作 / LLM-cost + CC 8 类扩 (真账户对账 / alert 真触发 / PT 重启 / GPU / OOM / 误操作 / user 输入 / memory drift)

### 第四档 — Review 13 + 3 = 16 领域 (5-10h)
10. [`architecture/`](architecture/) — ATAM + SAAM + V3 gap
11. [`code/`](code/) — SAST + SCA
12. [`data/`](data/) — 数据 6 维度
13. [`factors/`](factors/) — 谱系 + 拥挤 + 归因 + 治理 + Model Risk + multiple testing
14. [`backtest/`](backtest/) — 正确性 + 复现性 + 性能 + 一致性
15. [`risk/`](risk/) — V2 现状 + 4-29 5 Why + V3 gap
16. [`testing/`](testing/) — coverage + 金字塔 + flakiness + regression
17. [`operations/`](operations/) — Servy + 调度 + DR + Observability + alert 真触发 + **真账户对账 (CC 扩)**
18. [`security/`](security/) — STRIDE + secrets + supply chain + secret rotation
19. [`performance/`](performance/) — Memory + Latency + Throughput
20. [`business/`](business/) — 工作流 + 经济性 + 决策权 + 5 Why + 可持续性
21. [`external/`](external/) — 行业对标 + 学术 + 投资人 + **Vendor Lock-in (CC 扩)**
22. [`governance/`](governance/) — 6 块基石 + ADR-022 + D 决议链 + Code archaeology + Information arch + **Knowledge Management (CC 扩)**

### 第五档 — 端到端 + 跨领域 (2-3h)
23. [`end_to_end/`](end_to_end/) — 8 业务路径
24. [`independence/`](independence/) — 模块解耦 + 跨调用
25. [`cross_validation/`](cross_validation/) — 跨文档漂移
26. [`temporal/`](temporal/) — 历史 / 当前 / 未来

### 第六档 — STATUS_REPORT
27. [`STATUS_REPORT_2026_05_01.md`](STATUS_REPORT_2026_05_01.md) — 本审查执行报告 (实测时间 / token / context / 严重度分级清单)

---

## 实施 framework (沿用 `blind_spots/05_framework_self_audit.md` §3.1)

```
Claude framework: 5 维度 + 8 方法论 + 13 领域 + 14 类清单 + 4 端到端 + 4 adversarial + 双视角
+ CC 主动扩: 3 维度 + 6 方法论 + 3 领域 + 8 类清单 + 4 端到端 + 1 adversarial + 4 横向视角 + 严重度分级
= 实施: 8 维度 / 14 方法论 / 16 领域 / 22 类 / 8 端到端 / 5 adversarial / 6 视角 / P0真金/P0治理/P1/P2/P3 5 级
```

详见 [`blind_spots/05_framework_self_audit.md`](blind_spots/05_framework_self_audit.md) §3.

---

## CC onboarding 路径 (新 Claude session)

新 Claude session 走本 audit folder onboard:
1. 读 `GLOSSARY.md` — 术语先 onboard (Servy / QMT / Tier 0 / D 决议 / 6 块基石 / etc)
2. 读 `EXECUTIVE_SUMMARY.md` — 顶层概览
3. 读 `PRIORITY_MATRIX.md` — 找 P0/P1 关注点
4. 按需读领域 sub-md (sub-md 自包含, 不依赖 conversation 上下文)
5. 读 `STATUS_REPORT_2026_05_01.md` — 本审查 meta-info (执行时间 / scope / context %)

---

## Claude.ai 战略对话 onboarding 路径

Claude.ai (vs CC) 用 audit folder 做 user 战略对话:
1. 读 `EXECUTIVE_SUMMARY.md` 顶层 1h 可读
2. 战略候选 (修复 vs 推翻重做 vs 维持) — 仅候选, **不决议** (沿用 D78 0 修改 + 0 Phase)
3. 战略对话后产出 user 显式触发 prompt — 走下一 sprint period

---

## 不变项 + 硬边界 (沿用 FRAMEWORK.md §8)

✅ 允许: read-only audit, 创建 audit md, commit + push + PR + AI self-merge
❌ 禁止: 改业务代码 / .env / 已有 md / INSERT/UPDATE/DELETE SQL / 重启 Servy / 实施任何修复 / forward-progress offer

例外: framework_self_audit §3.4 严重度 P0 真金触发 → STOP 反问 user (D78 反驳条款, 沿用 framework §5.5).

---

## 关联

- [`FRAMEWORK.md`](FRAMEWORK.md) — 本审查 framework 设计 (Claude.ai 沉淀)
- ADR-021 (IRONLAWS v3) sustained
- ADR-022 (sprint period 反 anti-pattern) sustained
- PR #172-#181 (sprint period 6 块基石) sustained 但 framework_self_audit §1.6 部分 stale 候选

**文档结束**.
