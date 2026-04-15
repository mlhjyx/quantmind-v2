# F63 — 前端 / 后端 API 契约审计报告

> **F63 P0 看板 ⬜**: 前端调用 vs 后端路由覆盖缺口 (S2 audit 原始计数 12 vs 21, 实测 11 ts vs 22 py)
> **审计时间**: 2026-04-16 (Phase D D3a)
> **当前 git HEAD**: `audit(d-2-close)` 之后
> **扫盘命令**:
> - `rtk grep -rn "apiClient\.\(get|post|put|delete|patch\)" frontend/src/api/`
> - `rtk grep -rn "api\.\(get|post|put|delete|patch\)" frontend/src/api/` (dashboard.ts 用的独立 axios instance)
> - `rtk grep -rn "@router\.\(get|post|put|delete|patch\)" backend/app/api/`
> - `rtk grep "APIRouter(...prefix" backend/app/api/`

---

## TL;DR

- **前端 ts 文件**: **11** (`agent / system / mining / strategies / pipeline / factors / backtest / execution / realtime / dashboard / client`), client.ts 是 axios wrapper 不含路由
- **后端 py 文件**: **22** (`params / __init__ / notifications / dashboard / health / market / portfolio / remote_status / report / risk / realtime / paper_trading / system / approval / pipeline / mining / backtest / execution / strategies / execution_ops / pms / factors`), `__init__.py` 空, 21 个有 router
- **前端总调用数**: ~70 个 endpoint
- **✅ Match (前后端对齐)**: ~**50** 个
- **❌ F (Frontend orphan, 前端调后端无)**: **20** 个 (5 个文件)
- **❌ M (Mismatch, 路径/method 不一致)**: 0 (所有 mismatch 实际是 F 类)
- **⚠️ B (Backend orphan, 后端有前端没用)**: 大量 (前端没界面的高级 API), 留 Phase E

---

## F orphan 分布 (20 处, 5 文件)

| # | 前端文件:行号 | Method | 前端 path | 后端是否存在 | 优先级 | 修复策略 |
|---|---|---|---|---|---|---|
| **agent.ts (6 F, 整文件无后端 - P2 dormant feature)** ||||||
| 1 | agent.ts:61 | GET | /agent/{name}/config | ❌ 无 backend/app/api/agent.py | P2 | **defer** — AI 闭环 0% 实现 (CLAUDE.md), 整模块预留 Phase 3 |
| 2 | agent.ts:66 | PUT | /agent/{name}/config | ❌ | P2 | defer |
| 3 | agent.ts:77 | GET | /agent/model-health | ❌ | P2 | defer |
| 4 | agent.ts:83 | GET | /agent/cost-summary | ❌ | P2 | defer |
| 5 | agent.ts:88 | GET | /agent/{name}/logs | ❌ | P2 | defer |
| 6 | agent.ts:93 | POST | /agent/{name}/config/reset | ❌ | P2 | defer |
| **pipeline.ts (10 F, backend 重构未同步前端)** ||||||
| 7 | pipeline.ts:101 | POST | /pipeline/trigger | ❌ | P1 | **defer** — backend 没有 trigger 入口, 前端调用 dead 或需改 mining |
| 8 | pipeline.ts:106 | POST | /pipeline/pause | ❌ | P1 | defer |
| 9 | pipeline.ts:110 | GET | /pipeline/history | ❌ (有 /pipeline/runs) | P1 | **fix** — rename to /pipeline/runs |
| 10 | pipeline.ts:115 | GET | /pipeline/pending | ❌ | P1 | defer |
| 11 | pipeline.ts:120 | POST | /pipeline/approve/{id} | ❌ (有 /pipeline/runs/{run_id}/approve/{factor_id}) | P1 | **defer** — schema 不同 (单 id vs run+factor 双 id), 需要 UI 改造 |
| 12 | pipeline.ts:124 | POST | /pipeline/reject/{id} | ❌ | P1 | defer (同 #11) |
| 13 | pipeline.ts:128 | POST | /pipeline/hold/{id} | ❌ | P1 | defer |
| 14 | pipeline.ts:132 | GET | /pipeline/{runId}/logs | ❌ | P1 | defer |
| 15 | pipeline.ts:137 | PUT | /pipeline/automation-level | ❌ | P1 | defer |
| 16 | pipeline.ts:158/169 | POST | /pipeline/runs/{runId}/{approve\|reject}/{factorId} | ✅ | — | (重复行号, 是 ✅, 不计 F) |
| **factors.ts (3 POST F, factor 管理 dead code 或 backend 未实现)** ||||||
| 17 | factors.ts:196 | POST | /factors/{name}/archive | ❌ (factors.py 全是 GET) | P1 | **delete frontend** — backend 无, 前端 archive 功能从未实现端到端 |
| 18 | factors.ts:200 | POST | /factors/health | ❌ (有 GET /factors/health) | P1 | **delete frontend** — POST 是手动触发健康检查, backend 无 |
| 19 | factors.ts:204 | POST | /factors/correlation-prune | ❌ | P1 | **delete frontend** — backend 无 |
| **backtest.ts (2 F, 路径重命名遗漏)** ||||||
| 20 | backtest.ts:133 | GET | /backtest/{runId}/progress | ❌ (有 /backtest/{run_id} 返回 status) | P0 | **fix frontend** — change to /backtest/{runId} (status field) |
| 21 | backtest.ts:172 | POST | /backtest/{runId}/cancel | ❌ (no cancel endpoint) | P0 | **defer** — backend 没有 cancel 实现, 标 dead button or 删 frontend |
| **system.ts (2 F, 通知 + 批量参数 dead code)** ||||||
| 22 | system.ts:66 | POST | /params/batch | ❌ (有 /params/{key:path} PUT, 无 batch) | P2 | **delete frontend** or implement /params/batch backend |
| 23 | system.ts:70 | POST | /system/test-notification | ❌ (有 /notifications/test) | P1 | **fix frontend** — change to /notifications/test |

---

## ✅ Match 清单 (~50, 主要文件)

### dashboard.ts (7 calls, all ✅)
- /dashboard/{summary, nav-series, pending-actions, strategies} → dashboard.py:25/46/67/118 ✅
- /realtime/portfolio → realtime.py:52 ✅
- /paper-trading/positions → paper_trading.py:224 ✅
- /risk/state/default → risk.py:76 (`/state/{strategy_id}` 接受字符串) ✅

### execution.ts (16 calls, all ✅)
全部 16 个 endpoint 与 execution.py + execution_ops.py 对齐 (两个文件共享 `/api/execution` prefix)

### strategies.ts (5 calls, all ✅)
全部 CRUD endpoints 对齐 strategies.py

### realtime.ts (2 calls, all ✅)
- /realtime/portfolio + /realtime/market → realtime.py:52/59 ✅

### mining.ts (8 calls, all ✅)
- /mining/{run, tasks, tasks/{id}, tasks/{id}/cancel, evaluate} → mining.py 全对齐 ✅

### system.ts (3/5 ✅)
- /system/{datasources, scheduler, health} ✅
- /params (GET) ✅
- /params/batch ❌ F #22
- /system/test-notification ❌ F #23

### factors.ts (6/9 ✅)
- /factors/{summary, "", stats, correlation, health, {name}/report} GET ✅
- 3 POST 全 F (#17/18/19)

### backtest.ts (4/6 ✅)
- POST /backtest/run, GET /backtest/history, GET /backtest/{run_id}/result, POST /backtest/compare ✅
- /backtest/{runId}/progress ❌ F #20
- /backtest/{runId}/cancel ❌ F #21

### pipeline.ts (3/13 ✅)
- /pipeline/status ✅
- /pipeline/runs/{run_id} ✅
- /pipeline/runs/{run_id}/{approve|reject}/{factor_id} ✅ (×2)
- 其余 10 个 F (#7-15)

### agent.ts (0/6 ✅)
- 整文件 F (#1-6)

---

## ⚠️ Backend orphan (B 类, 后端有前端没用)

后端 21 个 router 文件含 ~110 个 endpoint, 前端只用 ~50. 大量 backend 端点没有前端 UI:

### 高频 B (likely 真 dead 或仅服务端调用)
- `/api/health/{checks, qmt}` — 前端只调 /system/health, 不调 /health
- `/api/approval/queue/*` — approval UI 可能未接入前端
- `/api/backtest/{run_id}/{nav, trades, holdings, annual, monthly, attribution, market-state, cost-sensitivity, report}` — 详细回测分析页面可能部分未接
- `/api/backtest/{run_id}/sensitivity`, `/live-compare` — 高级分析未接
- `/api/factors/{name}` (single factor detail) — 前端可能只用 list, 不用 detail
- `/api/mining` — 大部分 mining endpoint ✅, 但子页面可能缺
- `/api/notifications/*` — 前端 notification 走 client 拦截器, 不调 REST
- `/api/paper-trading/{status, graduation, graduation-status, trades}` — graduation 监控页面可能未接
- `/api/pms/*` — PMS UI 在 /pms 路由, 但 dashboard.ts 不调
- `/api/portfolio/*` — portfolio 子页面
- `/api/reports/*` — report 生成 UI
- `/api/risk/{history, summary, l4-recovery, l4-approve, force-reset, overview, limits, stress-tests}` — risk 详情页 (dashboard.ts 只调 /state)
- `/api/market/{indices, sectors, top-movers}` — 市场监控页
- `/api/v1/{ping, status}` — remote status 服务端通信, 非前端

**结论**: B 类大量但**不是真违规** — 前端可能只覆盖了部分 UI (auditor 只 grep `frontend/src/api/*.ts`, 没 grep React component 内的 `useQuery` 直接调用). **完整 B 类盘点需要 grep React `pages/` 目录**, 留 Phase E.

---

## D3b 修复决策

按"F 类 P0/P1 全部修完, P2 归档" 原则:

### 立即修复 (D3b, ~30-60 min)
| # | 修复 | 文件 | 类型 | 风险 |
|---|---|---|---|---|
| F-FIX-1 | backtest.ts:133 — 改 /backtest/{runId}/progress → 用 /backtest/{runId} 取 status | frontend/src/api/backtest.ts | rename | 🟢 低 |
| F-FIX-2 | backtest.ts:172 — 删除 cancelBacktest() 函数 (backend 无对应 endpoint) | frontend/src/api/backtest.ts | delete | 🟢 低 |
| F-FIX-3 | factors.ts:196/200/204 — 删除 archiveFactor() / triggerHealthCheck() / pruneCorrelation() 三个函数 | frontend/src/api/factors.ts | delete | 🟢 低 |
| F-FIX-4 | system.ts:70 — 改 /system/test-notification → /notifications/test | frontend/src/api/system.ts | rename | 🟢 低 |
| F-FIX-5 | system.ts:66 — 删除 batchUpdateParams() (frontend dead code, backend 无) | frontend/src/api/system.ts | delete | 🟢 低 |
| F-FIX-6 | pipeline.ts:110 — 改 /pipeline/history → /pipeline/runs | frontend/src/api/pipeline.ts | rename | 🟢 低 |

**预估**: 6 fix, 4 文件, ~30 min, 单 commit

### 归档 P2 留 Phase E (~14 处)
| # | 文件 | 处理 |
|---|---|---|
| pipeline.ts (#7-9, 11-15) | 9 处 pipeline 旧 schema endpoints | docs/audit/F63_backend_orphans.md 归档 |
| agent.ts (#1-6) | 整 6 个 agent endpoint | docs/audit/F63_backend_orphans.md 归档 (AI 闭环 Phase 3 实现时统一处理) |

**理由**:
- pipeline.ts 旧 endpoints 需要 backend 改造 (把 /pipeline/runs/{run_id}/* 重新映射或加新路由), 这是中等规模 backend 重构, 不在 Phase D 范围
- agent.ts 是 AI 闭环模块预留, CLAUDE.md 明确 "AI 闭环 0% 实现, Phase 3 才做". Phase D 不动死代码.

---

## 修复后 F63 状态预期

- F orphan: 20 → 14 (修 6, 归档 14)
- ⚠️ 修复后 P0 看板 F63 ⬜→✅ 的 **判定标准**: 6 个 F-FIX 完成 + 14 个 P2 归档到 F63_backend_orphans.md (有正式归档路径, 不是消失的)
- Phase E 接管: agent.ts (AI 闭环时实现) + pipeline.ts 9 处 (pipeline UI rework 时实现)

---

## 工件清单 (Phase D D3a 产出)

- 本报告: `docs/audit/F63_frontend_contract_audit.md`
- 待 D3b 产出: `docs/audit/F63_backend_orphans.md` (归档 14 P2)
- 0 代码改动 (扫盘 only)
- D3b 阶段开始执行 6 处修复

---

**铁律 28 范围外发现** (Phase D D3a 期间发现):

1. **dashboard.ts 用独立 axios instance** (`api = axios.create({ baseURL: "/api" })` line 11), 没走 `apiClient` 全局错误处理 — 这意味着 dashboard 页面的 API 错误不会触发全局 toast. **Phase E 应统一**, 让 dashboard.ts 也用 `apiClient`.

2. **execution.py + execution_ops.py 共享 `/api/execution` prefix** — 两个 router file 注册同一前缀, FastAPI 是允许的, 但路由审计时容易混淆. 不是 bug, 但是文档化值得.

3. **B 类未深度盘点** — 本审计只 grep `frontend/src/api/*.ts`, React component 内的 `useQuery({ queryFn: ... })` 直接调用未审. 完整 backend orphan 清单需要 Phase E 二次审计.

4. **agent.ts 是 dead code 风险源** — 6 个函数全部调用不存在的 backend endpoint. 如果有 React 页面真调用了, 会运行时 404. 应该 grep 调用方, 或者 Phase E AI 闭环统一删除/实现.
