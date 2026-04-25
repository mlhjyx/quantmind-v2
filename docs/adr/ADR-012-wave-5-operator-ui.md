---
adr_id: ADR-012
title: Wave 5 Operator UI Decision (Internal-only, Vue + FastAPI)
status: accepted
related_ironlaws: [22, 23, 24, 33, 36, 38, 42]
recorded_at: 2026-04-26
supersedes: (none)
related: ADR-011-qmt-api-utilization-roadmap, QPB v1.8 → v1.9 Part 4
---

## Context

### 历史背景: UI 一直被推迟

QM 当前 (Wave 3 1/5 完结, MVP 3.1 Risk Framework Monday 4-27 09:00 首生产触发倒计时 ~31h) 的 **UI 状态 = 0%**. 所有"操作面"都靠:

- PT 状态查询: SSH 进 Redis (`portfolio:current` Hash) + DB (`performance_series`) + QMT (`query_asset()`) **三源人工对账**
- 因子 IC 监控: SQL `SELECT * FROM factor_ic_history WHERE ...` 手工查
- 回测对比: `cache/baseline/*.parquet` + JSON 文件人工 diff
- 风控事件: 钉钉 webhook 文本告警, 无可视化链路追踪
- 调度任务: schtasks `/Query` + Servy CLI + Celery Beat log 三处看

**痛点**: Session 10 P0-α 熔断 live 失效 + Session 5 "-10.2%" 误读 + Session 20 phantom 5 码 等多次踩坑都因为 "状态不可见", 全靠记忆 + 命令行 grep 拼凑 (违反铁律 22 文档跟随代码 + 铁律 33 fail-loud).

### 历史决策: "UI 是反面教材, 不开源就不做"

CLAUDE 在 2026-04-26 早期对标分析中标 "UI / 指标 IDE / Web 面板" 为 **反面教材** (理由: QM 是研究系统不是产品; 公开开源时再补).

### 用户纠正 (2026-04-26)

> "UI / 指标 IDE / Web 面板 ⭐ 反面教材 — QM 是研究系统不是产品 不做; 公开开源时再补 — **你说的这个不对, 不开源, 但是也需要 UI 的, 现在没做是因为后端没有做好, 后端做好了在做 UI 和前端等等**"

明确两点:
1. **UI 不依赖开源** — 内部使用也需要
2. **UI 不是 nice-to-have** — 现在没做是因为后端 alpha + governance 还在收尾, 后端稳定后**必做**

### 24 项目对标证据

[QUANTMIND_LANDSCAPE_ANALYSIS_2026.md](../research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md) Part 4 D8 维度:

| 项目 | UI 等级 |
|---|---|
| OpenBB (66K⭐) | ⭐⭐⭐⭐⭐ Electron desktop |
| QuantDinger (2K⭐) | ⭐⭐⭐⭐ Vue Indicator IDE |
| jesse (8K⭐) | ⭐⭐⭐ Modern Vue UI |
| vnpy (40K⭐) | ⭐⭐⭐ chart + dashboard |
| 金策 (469⭐) | ⭐⭐ Web dashboard |
| **QM** | ❌ 0% |

24 项目里 **QM 是唯一 0 UI 的**. 即使最小的 lumibot (1K⭐) 都有基础面板. 这是工程债, 不是定位选择.

## Decision

### D1 — 在 QPB v1.9 加 Wave 5 Operator UI (4-6 周)

QPB v1.8 原 4-Wave 路径扩展为 5-Wave:

```
Wave 1 (完结) → Platform Skeleton + Config + DAL + Registry + Knowledge
Wave 2 (完结) → Data Framework + Lineage U3
Wave 3 (1/5)   → Strategy + Risk + Signal-Exec + Event Sourcing + Eval Gate
Wave 4 (待)    → Observability + Performance Attribution + CI/CD + Backup & DR
Wave 5 (新)    → Operator UI ⭐ (本 ADR)
Wave 6+ (远期) → 日内 / Forex / AI 闭环 / RL 重评估
```

### D2 — 5 子 MVP 划分

| MVP | 内容 | 优先级 |
|---|---|---|
| **5.0** | UI 总纲 + 框架选型 + 后端 API surface 设计 | P0 (前置) |
| **5.1** | PT 状态实时面板 (Redis + DB + QMT 三源对账可视化) | P0 (操作刚需) |
| **5.2** | 因子 IC 监控 + 衰减可视化 (含 ic_ma20/60 rolling chart) | P1 |
| **5.3** | 回测结果对比页 (regression + WF + Phase 实验对比) | P1 |
| **5.4** | 风控事件链路追踪 (PMS / CB / Intraday 跨系统) | P1 |
| **5.5** | 调度任务 dashboard (schtasks + Beat 健康 + ServicesHealthCheck) | P2 |

### D3 — 技术栈: Vue + ECharts + FastAPI (不引 Electron)

**Vue + ECharts** (跟 QM 现有 `frontend/` 53 组件 + 4 Zustand store 一致), **不引 Electron** 避免桌面打包维护成本.

**后端 API**: 复用 FastAPI (`backend/app/api/`), 不新加进程. 实时推送走 WebSocket / SSE (跟 StreamBus Redis 集成).

**对标参考**:
- 借: 金策 `event_coalesce + flow_emit_stride` 实时回测 backpressure (LANDSCAPE #17)
- 借: QuantDinger `KlineCache TTL 按周期分` (LANDSCAPE #19)
- **不抄**: OpenBB Electron (维护成本高) / QuantDinger 闭源 Vue dist (license 不全)

### D4 — Internal-only, 不开源

**Auth 模型**: 单用户 (作者本人), 走 `.env` 配置 token, 不引 OAuth / JWT 多用户复杂度.

**部署**: 独立 Servy 服务 (`QuantMind-UI`), 跟 FastAPI/Celery/Beat/QMTData 5 服务并列, 端口 8080 (跟 8000 FastAPI 解耦).

**License**: 仍 private repo, 不公开. 但代码库内 `frontend/` 子模块如果未来想拆分开源, **保持 Apache-2.0 兼容设计** (避免引 GPL 依赖, ADR-011 license 隔离原则).

### D5 — 启动时机: Wave 4 Observability 完结后

不能在 Wave 3 / Wave 4 之前启动. 理由:
- Wave 3 MVP 3.2-3.5 改信号路径 + 事件总线, UI 写早了会跟着改
- Wave 4 Observability 提供 Run Record + factor_quality_check + task_run_record, 这些是 UI 5.x 的**数据源**, 没有它们 UI 是空壳

预期启动: **2026 Q3 (Week 27 起, 约 6-30)**, 持续 4-6 周到 Week 32 (约 8-10).

## Consequences

### 好处

1. **Operability 提升 1-2 个数量级**: PT 状态从 3 源人工对账 → 1 页可视化
2. **Onboarding 友好**: 即便仍是个人系统, 半年后回看也不需要重读 4 万字 CLAUDE.md
3. **真金风控可见**: Session 10 P0-α 熔断失效类问题在 5.4 风控链路面板上**一眼可见**, 不会再 2 周裸奔
4. **铁律 22 升级**: "文档跟随代码" 升级到 "状态跟随代码" — UI 是 live 状态文档
5. **未来公开开源选项保留**: 如果 v2.0 想公开, UI 是产品的脸面, 现在做就不用紧急赶工

### 风险

1. **+5K loc 代码债** (估算 5 子 MVP × 1K loc/MVP)
2. **维护成本**: Vue 依赖升级 / 浏览器兼容 / WebSocket 状态同步 bug
3. **走偏成"产品"风险**: UI 容易吸引添加用户管理 / 计费 / OAuth 等 SaaS 化功能 (QuantDinger 的坑). **D4 的 internal-only 是 hard guard**.
4. **API surface 设计错误**: 后端 API 写早了 UI 没法用, 写晚了 UI blocking. **5.0 总纲先做** 是 mitigation.

### 中性

- 跟 SYSTEM_BLUEPRINT 现有 35 页面 + 53 组件 + 4 Zustand store 集成成本中等 (复用 70%, 新增 30%)
- 不影响 Wave 1-4 任何已交付 / 进行中工作

## Alternatives Considered

### A1 — 继续不做 (现状)
**否决**: Session 10 / 20 多次"状态不可见"踩坑已证不可持续. 真金 PT live 后这是合规风险 (无法 audit trail).

### A2 — Streamlit / Gradio 快速搭建
**否决**: 写起来快但产品级不够 (无 SSE / 无 component 复用 / 无路由). 半年后必重写. 不如一步到位 Vue.

### A3 — 等 v2.0 公开开源时再做
**否决**: 用户 2026-04-26 明确否决. 公开开源是不确定的远期事件, 不能成为 UI blocker.

### A4 — Electron Desktop (OpenBB 模式)
**否决**: 单用户跨设备访问需求小 (作者只在主机操作), 桌面打包 + auto-update 维护成本高. Web Vue 浏览器访问已够.

### A5 — vnpy 4.0 chart 模块直接复用
**否决**: vnpy MIT 友好可读, 但跟 QM `frontend/` 现有栈不一致, 引入会增加维护面. 可借设计模式不抄代码.

## Migration Schedule

| 阶段 | 时间 | 内容 |
|---|---|---|
| Wave 4 完结 | ~2026 Q3 早 | 前置依赖 (Run Record / factor_quality / Observability) 就绪 |
| MVP 5.0 设计稿 | Week 27 (~6-30) | UI 总纲 + 框架选型 + API surface 设计 |
| MVP 5.1 PT 状态面板 | Week 28-29 | P0 操作刚需 |
| MVP 5.2-5.5 串行 | Week 30-32 | 因子 IC / 回测对比 / 风控链路 / 调度 dashboard |
| Wave 5 完结 | Week 32 末 (~8-10) | UI v1.0 上线 |

## Validation

UI v1.0 上线后**必须**验证:

- [ ] 5 个 MVP 全部交付, 每个有 smoke test (铁律 10b 真启动验证)
- [ ] PT 状态面板 vs Redis/DB/QMT 三源 100% 一致 (max_diff = 0 不变量)
- [ ] 风控链路面板能复现 Session 10 P0-α 熔断失效场景 (历史回放)
- [ ] 因子 IC 面板跟 `factor_ic_history` 数据一致, 衰减告警 = `factor_lifecycle_monitor` 输出一致
- [ ] 调度面板能 1-click 看到所有 schtasks + Servy + Beat 健康
- [ ] 单用户 token auth 走通, 无 OAuth / multi-user 漂移

## References

- [docs/research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md](../research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md) Part 4 D8 + Part 5 P3 (#16-#19) + Part 6.2 工程债 + Part 7.4 路线
- [memory/project_borrowable_patterns.md](../../memory/project_borrowable_patterns.md) P3 Wave 5 子表
- ADR-011 (qmt-api-utilization-roadmap) — 同 Wave 周期但独立, UI 5.4 可消费 ADR-011 产出的 QMT 实时指标
- 铁律 22 (文档跟随代码) / 铁律 33 (fail-loud) / 铁律 38 (Blueprint 长期记忆)
