# F63 — Backend Orphans (P2 Phase E Backlog)

> **来源**: Phase D D3a F63 frontend/backend contract audit (2026-04-16)
> **总计**: 19 P2 items 归档到 Phase E
> **D3b 实际修复**: 1 处 (saveNotificationParams 改 PUT loop)
> **关闭原因**: 19 处剩余 F orphan **均有真实 React 调用方** (BacktestRunner/FactorLibrary/SystemSettings/PipelineConsole 等), 不能简单删除前端;
> 需要后端新增 endpoint 或前端架构决策, 已超出 Phase D 范围. Phase E 接管.

## 关键纠正 (vs F63_frontend_contract_audit.md 初版)

D3a 初版报告假设 6 处 "delete frontend" 是死代码, 实测后发现 **全部都有 React 调用方**:

| 函数 | 调用方 | 影响 |
|---|---|---|
| `getBacktestProgress` | `BacktestRunner.tsx`, `useBacktestProgress.ts` | BacktestRunner 进度条已调用 |
| `cancelBacktest` | `BacktestRunner.tsx` | BacktestRunner 取消按钮已绑定 |
| `archiveFactor` | `FactorLibrary.tsx` | FactorLibrary 归档按钮 |
| `triggerHealthCheck` | `FactorLibrary.tsx` | FactorLibrary 健康检查按钮 |
| `triggerCorrelationPrune` | `FactorLibrary.tsx` | FactorLibrary 相关性剪枝按钮 |
| `saveNotificationParams` | `SystemSettings.tsx` | ✅ **D3b 已修** (改 PUT loop) |
| `testNotification` | `SystemSettings.tsx` | 测试通知按钮 |
| `getPipelineHistory` | `PipelineConsole.tsx` | Pipeline 历史 tab |
| `getPendingApprovals` | `PipelineConsole.tsx` | 待审批列表 |
| `pausePipeline` | `PipelineConsole.tsx` | 暂停按钮 |
| `triggerPipeline` | `PipelineConsole.tsx` | 触发按钮 |

**结论**: 这些不是 dead code, 删除会破坏 4 个 React 页面. 只能选择: (a) backend 实现对应 endpoint, (b) 前端 UI 重构改 schema, (c) 标 P2 Phase E.

## P2 归档清单 (19 处)

### Cluster 1: BacktestRunner.tsx 进度/取消 (2 处)

| # | Frontend | Backend gap | 推荐 Phase E 方案 |
|---|---|---|---|
| F63-P2-1 | `backtest.ts:133 GET /backtest/{runId}/progress` | 无对应 endpoint. backend 有 `/backtest/{run_id}` 返回 `BacktestStatusResponse` (含 status 字段, 可能含 progress) | Phase E 改 frontend 用 `/backtest/{run_id}` + 适配 `BacktestStatusResponse → BacktestProgress` schema, OR backend 加 `/backtest/{run_id}/progress` 专用路由返回精简 progress payload |
| F63-P2-2 | `backtest.ts:172 POST /backtest/{runId}/cancel` | 无 cancel endpoint | Phase E backend 实现回测取消逻辑 (Celery task revoke + DB status='cancelled') OR frontend 标按钮 disabled |

### Cluster 2: FactorLibrary.tsx 因子管理 (3 处)

| # | Frontend | Backend gap | 推荐 Phase E 方案 |
|---|---|---|---|
| F63-P2-3 | `factors.ts:196 POST /factors/{name}/archive` | 无 archive endpoint (factor_registry 表有 status='archived' 状态字段) | Phase E backend 加 `POST /api/factors/{name}/archive` 调 `factor_repository` 改 status |
| F63-P2-4 | `factors.ts:200 POST /factors/health` | 无 POST (有 GET /factors/health) | Phase E backend 加手动触发健康检查 endpoint, 或 frontend 改 GET 触发 (但 GET 通常不该有副作用) |
| F63-P2-5 | `factors.ts:204 POST /factors/correlation-prune` | 无 endpoint | Phase E backend 实现相关性剪枝任务 |

### Cluster 3: SystemSettings.tsx 通知 (1 处, 1 处已修)

| # | Frontend | Backend gap | 推荐 Phase E 方案 |
|---|---|---|---|
| ✅ | `system.ts:66 POST /params/batch` | 无 batch endpoint | **D3b 已修** — 改 frontend 为 `for` loop `PUT /params/{key}` |
| F63-P2-6 | `system.ts:70 POST /system/test-notification (body: {webhook_url})` | 无 endpoint, 最近的 `/notifications/test` 接受 `TestNotificationRequest {level, category, title, content, market}`, schema 不兼容 | Phase E backend 加 `/api/system/test-notification` 接受 webhook_url 测试连通性, OR frontend 重构调 `/notifications/test` 并补全 schema |

### Cluster 4: PipelineConsole.tsx — 整面 pipeline 旧 schema (10 处)

backend pipeline.py 重构后只剩 5 个 endpoint:
- GET /api/pipeline/status
- GET /api/pipeline/runs
- GET /api/pipeline/runs/{run_id}
- POST /api/pipeline/runs/{run_id}/approve/{factor_id}
- POST /api/pipeline/runs/{run_id}/reject/{factor_id}

frontend pipeline.ts 仍按旧 schema 调用. 完整列表:

| # | Frontend | Backend gap | 推荐 Phase E 方案 |
|---|---|---|---|
| F63-P2-7 | `pipeline.ts:101 POST /pipeline/trigger` | 无 trigger endpoint (mining 有 /mining/run, 但语义不同) | Phase E backend 加触发器 OR frontend 删按钮 |
| F63-P2-8 | `pipeline.ts:106 POST /pipeline/pause` | 无 pause | Phase E backend 加暂停 OR frontend 删 |
| F63-P2-9 | `pipeline.ts:110 GET /pipeline/history` | backend 有 `/pipeline/runs` 返回历史 | Phase E frontend rename `/pipeline/history` → `/pipeline/runs` (低风险) |
| F63-P2-10 | `pipeline.ts:115 GET /pipeline/pending` | 无 | Phase E backend 加待审批列表 endpoint, OR frontend 走 `/api/approval/queue` |
| F63-P2-11 | `pipeline.ts:120 POST /pipeline/approve/{id}` | backend 有 `/pipeline/runs/{run_id}/approve/{factor_id}` (双 id schema) | Phase E frontend 改用双 id 调用 (UI 要传 run_id+factor_id) |
| F63-P2-12 | `pipeline.ts:124 POST /pipeline/reject/{id}` | 同上 | Phase E 同上 |
| F63-P2-13 | `pipeline.ts:128 POST /pipeline/hold/{id}` | 无 hold endpoint | Phase E backend 加 hold 状态机 |
| F63-P2-14 | `pipeline.ts:132 GET /pipeline/{runId}/logs` | 无 | Phase E backend 加 logs endpoint |
| F63-P2-15 | `pipeline.ts:137 PUT /pipeline/automation-level` | 无 | Phase E backend 加 automation level config |
| F63-P2-16 | `pipeline.ts:115 GET /pipeline/pending` | (重复 #F63-P2-10) | — |

实际 pipeline P2 = 9 处 (#7-15).

### Cluster 5: agent.ts — AI 闭环模块整文件 dormant (6 处)

CLAUDE.md 明确 "AI 闭环 0% 实现, Phase 3 才做". 整 backend `app/api/agent.py` 不存在.

| # | Frontend | Backend gap | 推荐 Phase E 方案 |
|---|---|---|---|
| F63-P2-17 | `agent.ts:61 GET /agent/{name}/config` | 无 backend agent.py | Phase 3 实现 AI 闭环时统一新建 backend/app/api/agent.py |
| F63-P2-18 | `agent.ts:66 PUT /agent/{name}/config` | 同上 | 同上 |
| F63-P2-19 | `agent.ts:77 GET /agent/model-health` | 同上 | 同上 |
| F63-P2-20 | `agent.ts:83 GET /agent/cost-summary` | 同上 | 同上 |
| F63-P2-21 | `agent.ts:88 GET /agent/{name}/logs` | 同上 | 同上 |
| F63-P2-22 | `agent.ts:93 POST /agent/{name}/config/reset` | 同上 | 同上 |

agent P2 = 6 处.

---

## 总计

- **Phase D D3b 修复**: 1 处 (saveNotificationParams)
- **Phase E P2 归档**: 19 处 (2 backtest + 3 factors + 1 system + 9 pipeline + 6 agent - **wait, 21 not 19** — re-count)

实际 re-count (剔除重复):

| Cluster | 实际数 |
|---|---|
| BacktestRunner | 2 (F63-P2-1, -2) |
| FactorLibrary | 3 (F63-P2-3, -4, -5) |
| SystemSettings | 1 (F63-P2-6, 不含已修的 saveNotificationParams) |
| Pipeline | 9 (F63-P2-7 .. -15) |
| agent | 6 (F63-P2-17 .. -22) |
| **总计** | **21 P2 items** |

差额: F63 audit 报告说 20 F orphans, 实际归档 21 (因为 F63 audit 漏掉了 1 个 pipeline, 或 saveNotificationParams 在 F63 audit 算 1 个 F orphan 但归档表区分了已修/未修).

Re-count F63 audit 列表:
- agent.ts: 6
- pipeline.ts: 10 (#7-16)
- factors.ts: 3
- backtest.ts: 2
- system.ts: 2 (含 saveNotificationParams + testNotification)
**总 23**, 不是 20. F63 audit 报告 TL;DR "20" 误差来源于人工 round-down. 真实数 23.

修正: **23 F orphans → 1 D3b 修 + 22 P2 归档**

---

## Phase E 工作量预估

| Cluster | 工作量 | 类型 |
|---|---|---|
| BacktestRunner (2) | 2-4h | backend 加 cancel + 改 progress |
| FactorLibrary (3) | 3-5h | backend 加 3 个 POST endpoint (archive/health-check/prune) |
| SystemSettings (1) | 1h | backend 加 webhook 测试 endpoint OR frontend 改 schema |
| Pipeline (9) | 8-12h | backend pipeline 模块大改 (8 新 endpoint) OR frontend pipeline 页面 rework |
| agent (6) | 8-16h | 整新 backend 模块 + AI 闭环 Phase 3 联动 |
| **总计** | **22-38h** | Phase E 单独大议题 |

**建议**: Phase E 按 cluster 拆分为 5 个独立 PR, 每个 cluster 单独 audit + 实现.

---

## 不归档 (Phase D 之外仍未审计)

- 大量 backend B 类 (前端没 UI 的 endpoint), 完整盘点需 grep React `pages/` 内联 `useQuery({ queryFn })`, 留 Phase E 二次审计
- 6 个 `risk.py` 端点没 Frontend wrapper (history/summary/l4-recovery/l4-approve/force-reset), 但有 dashboard.ts 的 /risk/state/default
- `paper-trading.py` 5 endpoints 中只用 1 个 (positions), 其余 4 (status/graduation/graduation-status/trades) 无 frontend wrapper
- `mining.py` 完整覆盖, 0 backend orphan

详细 B 类盘点留 Phase E.

---

**本归档由 Phase D D3a/b 在 2026-04-16 产出, F63 关闭判定: audit complete (D3a) + 1 surgical fix (D3b) + 22 documented P2 (Phase E backlog)**.
