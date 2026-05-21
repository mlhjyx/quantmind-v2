# API Coverage Matrix — QuantMind V2

**Generated**: 2026-05-20  
**Backend**: 148 endpoints across 25 router files  
**Frontend API modules**: 11 files (`frontend/src/api/*.ts`)  
**Methodology**: `@router.(get|post|put|delete|patch)` grep on `backend/app/api/**/*.py` + `apiClient.(get|post|put|delete|patch)` grep on `frontend/src/api/*.ts`

---

## §1 Executive Summary

| Metric | Count | % |
|--------|-------|---|
| Total backend endpoints | 148 | 100% |
| Consumed (frontend caller found) | 74 | 50% |
| Backend-only (no frontend consumer) | 74 | 50% |
| Frontend-only orphans (no matching backend) | 10 | — |

**Key findings**:
- 50% of backend endpoints have no frontend consumer — primarily admin/ops endpoints (execution_ops admin actions), PMS (deprecated), news ingest, remote_status, report generation, paper_trading, SSE stream, approval workflow.
- 10 frontend calls target paths with no matching backend endpoint — these are bug candidates (`/backtest/{id}/cancel`, `/pipeline/trigger`, `/pipeline/pause`, `/pipeline/approve`, `/pipeline/reject`, `/pipeline/hold`, `/pipeline/{id}/logs`, `/pipeline/automation-level`, `/factors/health` as POST, `/factors/correlation-prune`). **(2026-05-22 Phase K reconciliation: O2/O4/O5/O6 resolved — 6 orphans remain. See §6.1.)**
- Auth gate (verify_admin_token): 22 endpoints gated, remainder public.

---

## §2 Per-Router Endpoint Inventory

Router prefixes from `backend/app/api/<file>.py` → `APIRouter(prefix=...)`.

### 2.1 agent — `/api/agent` (`backend/app/api/agent.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 1 | POST | `/api/agent/chat` | chat endpoint | agent.py:185 | admin |
| 2 | GET | `/api/agent/chat/status` | AI Assist status | agent.py:286 | admin |
| 3 | GET | `/api/agent/{name}/config` | Agent config query | agent.py:641 | public |
| 4 | PUT | `/api/agent/{name}/config` | Agent config update | agent.py:669 | admin |
| 5 | POST | `/api/agent/{name}/config/reset` | Agent config reset | agent.py:695 | admin |
| 6 | GET | `/api/agent/{name}/history` | Agent prompt history | agent.py:712 | admin |
| 7 | POST | `/api/agent/{name}/config/rollback` | Agent config rollback | agent.py:741 | admin |
| 8 | GET | `/api/agent/model-health` | LLM model health | agent.py:785 | admin |
| 9 | GET | `/api/agent/cost-summary` | LLM cost summary | agent.py:815 | admin |
| 10 | GET | `/api/agent/{name}/logs` | Agent call logs | agent.py:857 | admin |

### 2.2 approval — `/api/approval` (`backend/app/api/approval.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 11 | GET | `/api/approval/queue` | List approval queue | approval.py:205 | public |
| 12 | GET | `/api/approval/queue/{item_id}` | Get approval item | approval.py:234 | public |
| 13 | POST | `/api/approval/queue/{item_id}/approve` | Approve item | approval.py:259 | admin |
| 14 | POST | `/api/approval/queue/{item_id}/reject` | Reject item | approval.py:290 | admin |
| 15 | POST | `/api/approval/queue/{item_id}/hold` | Hold item | approval.py:321 | admin |
| 16 | GET | `/api/approval/history` | Approval history | approval.py:352 | public |

### 2.3 auth — `/api/auth` (`backend/app/api/auth.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 17 | POST | `/api/auth/admin-token` | Set admin token cookie | auth.py:55 | public |
| 18 | POST | `/api/auth/admin-token/clear` | Clear admin token cookie | auth.py:101 | admin |
| 19 | GET | `/api/auth/admin-token/status` | Check admin token status | auth.py:126 | public |

### 2.4 backtest — `/api/backtest` (`backend/app/api/backtest.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 20 | POST | `/api/backtest/run` | Start backtest run | backtest.py:145 | public |
| 21 | GET | `/api/backtest/history` | Backtest run history | backtest.py:212 | public |
| 22 | GET | `/api/backtest/{run_id}` | Backtest run status | backtest.py:284 | public |
| 23 | GET | `/api/backtest/{run_id}/result` | Backtest result | backtest.py:308 | public |
| 24 | GET | `/api/backtest/{run_id}/nav` | NAV series | backtest.py:377 | public |
| 25 | GET | `/api/backtest/{run_id}/trades` | Trade list | backtest.py:420 | public |
| 26 | GET | `/api/backtest/{run_id}/holdings` | Holdings | backtest.py:511 | public |
| 27 | GET | `/api/backtest/{run_id}/annual` | Annual returns | backtest.py:570 | public |
| 28 | GET | `/api/backtest/{run_id}/monthly` | Monthly returns | backtest.py:637 | public |
| 29 | GET | `/api/backtest/{run_id}/attribution` | Factor attribution | backtest.py:693 | public |
| 30 | GET | `/api/backtest/{run_id}/market-state` | Market state | backtest.py:743 | public |
| 31 | GET | `/api/backtest/{run_id}/cost-sensitivity` | Cost sensitivity | backtest.py:827 | public |
| 32 | GET | `/api/backtest/{run_id}/report` | Backtest report | backtest.py:936 | public |
| 33 | POST | `/api/backtest/compare` | Compare runs | backtest.py:1031 | public |
| 34 | POST | `/api/backtest/{run_id}/sensitivity` | Sensitivity analysis | backtest.py:1082 | public |
| 35 | GET | `/api/backtest/{run_id}/live-compare` | Live vs backtest | backtest.py:1112 | public |

### 2.5 dashboard — `/api/dashboard` (`backend/app/api/dashboard.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 36 | GET | `/api/dashboard/summary` | Dashboard summary | dashboard.py:23 | public |
| 37 | GET | `/api/dashboard/nav-series` | NAV series | dashboard.py:39 | public |
| 38 | GET | `/api/dashboard/pending-actions` | Pending actions | dashboard.py:55 | public |
| 39 | GET | `/api/dashboard/market-ticker` | Market ticker | dashboard.py:69 | public |
| 40 | GET | `/api/dashboard/alerts` | Alerts | dashboard.py:81 | public |
| 41 | GET | `/api/dashboard/strategies` | Strategies overview | dashboard.py:95 | public |
| 42 | GET | `/api/dashboard/monthly-returns` | Monthly returns | dashboard.py:106 | public |
| 43 | GET | `/api/dashboard/industry-distribution` | Industry distribution | dashboard.py:124 | public |

### 2.6 execution — `/api/execution` (`backend/app/api/execution.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 44 | GET | `/api/execution/pending-orders` | Pending orders | execution.py:28 | public |
| 45 | GET | `/api/execution/log` | Execution log | execution.py:93 | public |
| 46 | GET | `/api/execution/algo-config` | Algo config | execution.py:183 | public |

### 2.7 execution_ops — `/api/execution` (`backend/app/api/execution_ops.py`)

*Note: shares `/api/execution` prefix with execution.py*

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 47 | GET | `/api/execution/qmt-status` | QMT status | execution_ops.py:155 | public |
| 48 | GET | `/api/execution/positions` | Positions | execution_ops.py:161 | public |
| 49 | GET | `/api/execution/asset` | Asset / NAV | execution_ops.py:213 | public |
| 50 | GET | `/api/execution/orders` | Orders | execution_ops.py:254 | public |
| 51 | GET | `/api/execution/trades` | Trades | execution_ops.py:281 | public |
| 52 | GET | `/api/execution/drift` | Portfolio drift | execution_ops.py:305 | public |
| 53 | POST | `/api/execution/cancel-all` | Cancel all orders | execution_ops.py:515 | admin |
| 54 | POST | `/api/execution/cancel/{order_id}` | Cancel order | execution_ops.py:552 | admin |
| 55 | POST | `/api/execution/fix-drift/preview` | Fix drift preview | execution_ops.py:579 | admin |
| 56 | POST | `/api/execution/fix-drift/execute` | Fix drift execute | execution_ops.py:628 | admin |
| 57 | POST | `/api/execution/trigger-rebalance` | Trigger rebalance | execution_ops.py:691 | admin |
| 58 | POST | `/api/execution/emergency-liquidate` | Emergency liquidate | execution_ops.py:719 | admin |
| 59 | POST | `/api/execution/pause-trading` | Pause trading | execution_ops.py:763 | admin |
| 60 | POST | `/api/execution/resume-trading` | Resume trading | execution_ops.py:776 | admin |
| 61 | GET | `/api/execution/trading-paused` | Trading paused state | execution_ops.py:789 | public |
| 62 | PUT | `/api/execution/alert-config` | Alert config | execution_ops.py:795 | admin |
| 63 | GET | `/api/execution/audit-log` | Audit log | execution_ops.py:813 | admin |

### 2.8 factors — `/api/factors` (`backend/app/api/factors.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 64 | GET | `/api/factors/health` | Factor health | factors.py:57 | public |
| 65 | GET | `/api/factors/correlation` | Correlation matrix | factors.py:148 | public |
| 66 | GET | `/api/factors/summary` | Factor summary | factors.py:249 | public |
| 67 | GET | `/api/factors/stats` | Factor stats | factors.py:309 | public |
| 68 | GET | `/api/factors` | Factor list | factors.py:395 | public |
| 69 | GET | `/api/factors/{name}` | Factor detail | factors.py:477 | public |
| 70 | GET | `/api/factors/{name}/report` | Factor report | factors.py:566 | public |
| 71 | POST | `/api/factors/{name}/archive` | Archive factor | factors.py:1019 | public |

### 2.9 health — `/api/health` (`backend/app/api/health.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 72 | GET | `/api/health` | Health check | health.py:21 | public |
| 73 | GET | `/api/health/checks` | Detailed health checks | health.py:51 | public |
| 74 | GET | `/api/health/qmt` | QMT health | health.py:70 | public |

### 2.10 market — `/api/market` (`backend/app/api/market.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 75 | GET | `/api/market/indices` | Market indices | market.py:32 | public |
| 76 | GET | `/api/market/sectors` | Sector data | market.py:106 | public |
| 77 | GET | `/api/market/top-movers` | Top movers | market.py:151 | public |

### 2.11 mining — `/api/mining` (`backend/app/api/mining.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 78 | POST | `/api/mining/run` | Start mining run | mining.py:126 | public |
| 79 | GET | `/api/mining/tasks` | List tasks | mining.py:177 | public |
| 80 | GET | `/api/mining/tasks/{task_id}` | Task detail | mining.py:208 | public |
| 81 | POST | `/api/mining/tasks/{task_id}/cancel` | Cancel task | mining.py:244 | public |
| 82 | POST | `/api/mining/evaluate` | Evaluate factor expr | mining.py:278 | public |

### 2.12 news — `/api/news` (`backend/app/api/news.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 83 | POST | `/api/news/ingest` | Ingest news | news.py:250 | public |
| 84 | POST | `/api/news/ingest_rsshub` | Ingest RSSHub | news.py:321 | public |
| 85 | POST | `/api/news/ingest_announcement` | Ingest announcement | news.py:436 | public |
| 86 | GET | `/api/news/stats` | News stats | news.py:513 | public |

### 2.13 notifications — `/api/notifications` (`backend/app/api/notifications.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 87 | GET | `/api/notifications` | List notifications | notifications.py:51 | public |
| 88 | GET | `/api/notifications/unread-count` | Unread count | notifications.py:82 | public |
| 89 | GET | `/api/notifications/{notification_id}` | Notification detail | notifications.py:93 | public |
| 90 | PUT | `/api/notifications/{notification_id}/read` | Mark as read | notifications.py:111 | public |
| 91 | POST | `/api/notifications/test` | Test notification | notifications.py:129 | public |

### 2.14 paper_trading — `/api/paper-trading` (`backend/app/api/paper_trading.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 92 | GET | `/api/paper-trading/status` | PT status | paper_trading.py:57 | public |
| 93 | GET | `/api/paper-trading/graduation` | Graduation criteria | paper_trading.py:76 | public |
| 94 | GET | `/api/paper-trading/graduation-status` | Graduation status | paper_trading.py:101 | public |
| 95 | GET | `/api/paper-trading/positions` | PT positions | paper_trading.py:224 | public |
| 96 | GET | `/api/paper-trading/trades` | PT trades | paper_trading.py:243 | public |

### 2.15 params — `/api/params` (`backend/app/api/params.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 97 | GET | `/api/params` | List all params | params.py:41 | public |
| 98 | GET | `/api/params/changelog` | Param changelog | params.py:63 | public |
| 99 | GET | `/api/params/{key}` | Get param by key | params.py:78 | public |
| 100 | PUT | `/api/params/{key}` | Update param | params.py:97 | public |
| 101 | POST | `/api/params/init-defaults` | Init default params | params.py:124 | public |

### 2.16 pipeline — `/api/pipeline` (`backend/app/api/pipeline.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 102 | GET | `/api/pipeline/status` | Pipeline status | pipeline.py:89 | public |
| 103 | GET | `/api/pipeline/runs` | Pipeline run history | pipeline.py:148 | public |
| 104 | GET | `/api/pipeline/runs/{run_id}` | Pipeline run detail | pipeline.py:218 | public |
| 105 | POST | `/api/pipeline/runs/{run_id}/approve/{factor_id}` | Approve factor | pipeline.py:310 | public |
| 106 | POST | `/api/pipeline/runs/{run_id}/reject/{factor_id}` | Reject factor | pipeline.py:413 | public |

### 2.17 pms — `/api/pms` (`backend/app/api/pms.py`)

*Note: PMS deprecated per ADR-010; Beat stopped PR #34*

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 107 | GET | `/api/pms/positions` | PMS positions | pms.py:19 | public |
| 108 | GET | `/api/pms/history` | PMS history | pms.py:60 | public |
| 109 | GET | `/api/pms/config` | PMS config | pms.py:106 | public |
| 110 | POST | `/api/pms/check` | PMS check | pms.py:131 | public |

### 2.18 portfolio — `/api/portfolio` (`backend/app/api/portfolio.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 111 | GET | `/api/portfolio/holdings` | Portfolio holdings | portfolio.py:34 | public |
| 112 | GET | `/api/portfolio/sector-distribution` | Sector distribution | portfolio.py:105 | public |
| 113 | GET | `/api/portfolio/daily-pnl` | Daily PnL | portfolio.py:169 | public |

### 2.19 realtime — `/api/realtime` (`backend/app/api/realtime.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 114 | GET | `/api/realtime/portfolio` | Realtime portfolio snapshot | realtime.py:47 | public |
| 115 | GET | `/api/realtime/market` | Realtime market overview | realtime.py:54 | public |

### 2.20 remote_status — `/api/v1` (`backend/app/api/remote_status.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 116 | GET | `/api/v1/ping` | Ping | remote_status.py:284 | public |
| 117 | GET | `/api/v1/status` | Remote system status | remote_status.py:303 | public |

### 2.21 report — `/api/reports` (`backend/app/api/report.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 118 | GET | `/api/reports/list` | List reports | report.py:28 | public |
| 119 | GET | `/api/reports/quick-stats` | Quick stats | report.py:98 | public |
| 120 | POST | `/api/reports/generate` | Generate report | report.py:176 | public |

### 2.22 risk — `/api/risk` (`backend/app/api/risk.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 121 | GET | `/api/risk/state/{strategy_id}` | Risk state | risk.py:93 | public |
| 122 | GET | `/api/risk/history/{strategy_id}` | Risk history | risk.py:146 | public |
| 123 | GET | `/api/risk/summary/{strategy_id}` | Risk summary | risk.py:187 | public |
| 124 | POST | `/api/risk/l4-recovery/{strategy_id}` | L4 recovery | risk.py:206 | admin |
| 125 | POST | `/api/risk/l4-approve/{approval_id}` | L4 approve | risk.py:239 | admin |
| 126 | POST | `/api/risk/force-reset/{strategy_id}` | Force reset | risk.py:273 | admin |
| 127 | GET | `/api/risk/overview` | Risk overview | risk.py:307 | public |
| 128 | GET | `/api/risk/limits` | Risk limits | risk.py:387 | public |
| 129 | GET | `/api/risk/stress-tests` | Stress tests | risk.py:486 | public |
| 130 | POST | `/api/risk/dingtalk-webhook` | DingTalk webhook | risk.py:618 | public |

### 2.23 sse — `/api/sse` (`backend/app/api/sse.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 131 | GET | `/api/sse/risk-events` | SSE risk-event stream | sse.py:162 | admin |

### 2.24 strategies — `/api/strategies` (`backend/app/api/strategies.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 132 | GET | `/api/strategies` | List strategies | strategies.py:72 | public |
| 133 | GET | `/api/strategies/{strategy_id}` | Strategy detail | strategies.py:92 | public |
| 134 | GET | `/api/strategies/{strategy_id}/versions` | Strategy versions | strategies.py:114 | public |
| 135 | POST | `/api/strategies/{strategy_id}/versions` | Create version | strategies.py:147 | public |
| 136 | POST | `/api/strategies/{strategy_id}/rollback` | Rollback strategy | strategies.py:173 | public |
| 137 | POST | `/api/strategies` | Create strategy | strategies.py:199 | public |
| 138 | PUT | `/api/strategies/{strategy_id}` | Update strategy | strategies.py:220 | public |
| 139 | DELETE | `/api/strategies/{strategy_id}` | Delete strategy | strategies.py:245 | public |
| 140 | GET | `/api/strategies/{strategy_id}/factors` | Strategy factors | strategies.py:267 | public |
| 141 | POST | `/api/strategies/{strategy_id}/backtest` | Trigger backtest | strategies.py:289 | public |

### 2.25 system — `/api/system` (`backend/app/api/system.py`)

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 142 | GET | `/api/system/datasources` | Data sources | system.py:258 | public |
| 143 | GET | `/api/system/health` | System health | system.py:298 | public |
| 144 | GET | `/api/system/streams` | Redis streams | system.py:334 | public |
| 145 | GET | `/api/system/scheduler` | Scheduler tasks | system.py:346 | public |
| 146 | POST | `/api/system/test-notification` | Test notification | system.py:370 | public |
| 147 | GET | `/api/system/calendar-info` | Trading calendar | system.py:407 | public |
| 148 | GET | `/api/system/env-state` | Env state (LL-183) | system.py:458 | public |

**Endpoint count verification**: 10+6+3+16+8+3+17+8+3+3+5+4+5+5+5+5+4+3+2+2+3+10+1+10+7 = **148** ✓

---

## §3 Per-Frontend-Module API Call Inventory

Frontend base URL: `apiClient` configured in `frontend/src/api/client.ts:28` (axios instance, baseURL = `/api`).

> Note: frontend URLs omit the `/api` prefix (added by axios baseURL). All paths below are as written in source.

### 3.1 agent.ts (`frontend/src/api/agent.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| agent.ts:69 | GET | `/agent/{name}/config` |
| agent.ts:74 | PUT | `/agent/{name}/config` |
| agent.ts:85 | GET | `/agent/model-health` |
| agent.ts:91 | GET | `/agent/cost-summary` |
| agent.ts:96 | GET | `/agent/{name}/logs` |
| agent.ts:101 | POST | `/agent/{name}/config/reset` |
| agent.ts:119 | GET | `/agent/{name}/history` |
| agent.ts:130–131 | POST | `/agent/{name}/config/rollback` |
| agent.ts:184 | POST | `/agent/chat` |
| agent.ts:189 | GET | `/agent/chat/status` |

**10 calls → maps to endpoints #1–10** (all consumed)

### 3.2 backtest.ts (`frontend/src/api/backtest.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| backtest.ts:128 | POST | `/backtest/run` |
| backtest.ts:135 | GET | `/backtest/{runId}` |
| backtest.ts:150 | GET | `/backtest/{runId}/result` |
| backtest.ts:183 | POST | `/backtest/{runId}/cancel` |
| backtest.ts:189 | GET | `/backtest/history` |
| backtest.ts:207 | POST | `/backtest/compare` |

**6 calls → 5 consumed (#20, #22, #23, #21, #33); 1 orphan** (`/backtest/{runId}/cancel` — no backend endpoint)

### 3.3 client.ts (`frontend/src/api/client.ts`)

Axios instance definition only. No direct API calls. **0 calls**.

### 3.4 dashboard.ts (`frontend/src/api/dashboard.ts`)

No `apiClient.*` calls — comment only at line 2.  
**0 direct calls** — dashboard data likely fetched via react-query hooks elsewhere or SSE/WebSocket.  
All 8 dashboard endpoints (#36–43) are **backend-only** (no frontend API module consumer).

### 3.5 execution.ts (`frontend/src/api/execution.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| execution.ts:164–165 | POST | `/auth/admin-token` |
| execution.ts:186 | POST | `/auth/admin-token/clear` |
| execution.ts:204–205 | GET | `/auth/admin-token/status` |
| execution.ts:227 | GET | `/execution/qmt-status` |
| execution.ts:232 | GET | `/execution/positions` |
| execution.ts:237 | GET | `/execution/asset` |
| execution.ts:242 | GET | `/execution/orders` |
| execution.ts:247 | GET | `/execution/trades` |
| execution.ts:252 | GET | `/execution/drift` |
| execution.ts:257 | GET | `/execution/trading-paused` |
| execution.ts:262 | GET | `/execution/audit-log` |
| execution.ts:273 | POST | `/execution/cancel-all` |
| execution.ts:280 | POST | `/execution/cancel/{orderId}` |
| execution.ts:287 | POST | `/execution/fix-drift/preview` |
| execution.ts:297 | POST | `/execution/fix-drift/execute` |
| execution.ts:306 | POST | `/execution/trigger-rebalance` |
| execution.ts:316 | POST | `/execution/emergency-liquidate` |
| execution.ts:325 | POST | `/execution/pause-trading` |
| execution.ts:332 | POST | `/execution/resume-trading` |

**19 calls → all 19 consumed** (auth #17–19, execution_ops #47–63 partially)

### 3.6 factors.ts (`frontend/src/api/factors.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| factors.ts:100 | GET | `/factors/summary` |
| factors.ts:105 | GET | `/factors` |
| factors.ts:110 | GET | `/factors/stats` |
| factors.ts:115 | GET | `/factors/correlation` |
| factors.ts:120 | GET | `/factors/health` |
| factors.ts:126 | GET | `/factors/{name}/report` |
| factors.ts:196 | POST | `/factors/{name}/archive` |
| factors.ts:200 | POST | `/factors/health` |
| factors.ts:204 | POST | `/factors/correlation-prune` |

**9 calls → 7 consumed; 2 orphans** (`POST /factors/health` — backend has only GET; `POST /factors/correlation-prune` — no backend endpoint)

### 3.7 mining.ts (`frontend/src/api/mining.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| mining.ts:142, 151, 160, 199 | POST | `/mining/run` |
| mining.ts:166 | GET | `/mining/tasks` |
| mining.ts:184 | GET | `/mining/tasks/{taskId}` |
| mining.ts:190, 194, 205 | POST | `/mining/tasks/{taskId}/cancel` |
| mining.ts:211, 218 | POST | `/mining/evaluate` |

**9 distinct calls (deduped) → all 5 endpoints consumed** (#78–82)

### 3.8 pipeline.ts (`frontend/src/api/pipeline.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| pipeline.ts:96 | GET | `/pipeline/status` |
| pipeline.ts:101 | POST | `/pipeline/trigger` |
| pipeline.ts:106 | POST | `/pipeline/pause` |
| pipeline.ts:111 | GET | `/pipeline/runs` |
| pipeline.ts:117 | GET | `/approval/queue` |
| pipeline.ts:122 | POST | `/pipeline/approve/{id}` |
| pipeline.ts:126 | POST | `/pipeline/reject/{id}` |
| pipeline.ts:130 | POST | `/pipeline/hold/{id}` |
| pipeline.ts:134 | GET | `/pipeline/{runId}/logs` |
| pipeline.ts:139 | PUT | `/pipeline/automation-level` |
| pipeline.ts:150 | GET | `/pipeline/runs/{runId}` |
| pipeline.ts:160 | POST | `/pipeline/runs/{runId}/approve/{factorId}` |
| pipeline.ts:171 | POST | `/pipeline/runs/{runId}/reject/{factorId}` |

**13 calls → 3 consumed (#102, #103, #104–106); 7 orphans** (see §6)

### 3.9 realtime.ts (`frontend/src/api/realtime.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| realtime.ts:84 | GET | `/realtime/portfolio` |
| realtime.ts:89 | GET | `/realtime/market` |

**2 calls → both consumed** (#114, #115)

### 3.10 strategies.ts (`frontend/src/api/strategies.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| strategies.ts:47 | GET | `/strategies` |
| strategies.ts:67 | GET | `/strategies/{id}` |
| strategies.ts:72 | POST | `/strategies` |
| strategies.ts:77 | PUT | `/strategies/{id}` |
| strategies.ts:82 | DELETE | `/strategies/{id}` |

**5 calls → all 5 consumed** (#132, #133, #137, #138, #139)

### 3.11 system.ts (`frontend/src/api/system.ts`)

| File:Line | Method | URL |
|-----------|--------|-----|
| system.ts:57 | GET | `/system/datasources` |
| system.ts:62 | GET | `/system/scheduler` |
| system.ts:67 | GET | `/system/health` |
| system.ts:72 | GET | `/params` |
| system.ts:85 | PUT | `/params/{key}` |
| system.ts:93 | POST | `/system/test-notification` |
| system.ts:103 | GET | `/system/env-state` |
| system.ts:130 | GET | `/system/calendar-info` |

**8 calls → all 8 consumed** (#142, #145, #143, #97, #100, #146, #148, #147)

---

## §4 Coverage Matrix

Legend: ✅ Consumed | ❌ Backend-only | 🚧 Frontend-only orphan

| # | Endpoint | Method | Frontend Consumer | Status |
|---|----------|--------|-------------------|--------|
| 1 | `/api/agent/chat` | POST | agent.ts:184 | ✅ |
| 2 | `/api/agent/chat/status` | GET | agent.ts:189 | ✅ |
| 3 | `/api/agent/{name}/config` | GET | agent.ts:69 | ✅ |
| 4 | `/api/agent/{name}/config` | PUT | agent.ts:74 | ✅ |
| 5 | `/api/agent/{name}/config/reset` | POST | agent.ts:101 | ✅ |
| 6 | `/api/agent/{name}/history` | GET | agent.ts:119 | ✅ |
| 7 | `/api/agent/{name}/config/rollback` | POST | agent.ts:130 | ✅ |
| 8 | `/api/agent/model-health` | GET | agent.ts:85 | ✅ |
| 9 | `/api/agent/cost-summary` | GET | agent.ts:91 | ✅ |
| 10 | `/api/agent/{name}/logs` | GET | agent.ts:96 | ✅ |
| 11 | `/api/approval/queue` | GET | pipeline.ts:117 | ✅ |
| 12 | `/api/approval/queue/{item_id}` | GET | — | ❌ |
| 13 | `/api/approval/queue/{item_id}/approve` | POST | — | ❌ |
| 14 | `/api/approval/queue/{item_id}/reject` | POST | — | ❌ |
| 15 | `/api/approval/queue/{item_id}/hold` | POST | — | ❌ |
| 16 | `/api/approval/history` | GET | — | ❌ |
| 17 | `/api/auth/admin-token` | POST | execution.ts:164 | ✅ |
| 18 | `/api/auth/admin-token/clear` | POST | execution.ts:186 | ✅ |
| 19 | `/api/auth/admin-token/status` | GET | execution.ts:204 | ✅ |
| 20 | `/api/backtest/run` | POST | backtest.ts:128 | ✅ |
| 21 | `/api/backtest/history` | GET | backtest.ts:189 | ✅ |
| 22 | `/api/backtest/{run_id}` | GET | backtest.ts:135 | ✅ |
| 23 | `/api/backtest/{run_id}/result` | GET | backtest.ts:150 | ✅ |
| 24 | `/api/backtest/{run_id}/nav` | GET | — | ❌ |
| 25 | `/api/backtest/{run_id}/trades` | GET | — | ❌ |
| 26 | `/api/backtest/{run_id}/holdings` | GET | — | ❌ |
| 27 | `/api/backtest/{run_id}/annual` | GET | — | ❌ |
| 28 | `/api/backtest/{run_id}/monthly` | GET | — | ❌ |
| 29 | `/api/backtest/{run_id}/attribution` | GET | — | ❌ |
| 30 | `/api/backtest/{run_id}/market-state` | GET | — | ❌ |
| 31 | `/api/backtest/{run_id}/cost-sensitivity` | GET | — | ❌ |
| 32 | `/api/backtest/{run_id}/report` | GET | — | ❌ |
| 33 | `/api/backtest/compare` | POST | backtest.ts:207 | ✅ |
| 34 | `/api/backtest/{run_id}/sensitivity` | POST | — | ❌ |
| 35 | `/api/backtest/{run_id}/live-compare` | GET | — | ❌ |
| 36 | `/api/dashboard/summary` | GET | — | ❌ |
| 37 | `/api/dashboard/nav-series` | GET | — | ❌ |
| 38 | `/api/dashboard/pending-actions` | GET | — | ❌ |
| 39 | `/api/dashboard/market-ticker` | GET | — | ❌ |
| 40 | `/api/dashboard/alerts` | GET | — | ❌ |
| 41 | `/api/dashboard/strategies` | GET | — | ❌ |
| 42 | `/api/dashboard/monthly-returns` | GET | — | ❌ |
| 43 | `/api/dashboard/industry-distribution` | GET | — | ❌ |
| 44 | `/api/execution/pending-orders` | GET | — | ❌ |
| 45 | `/api/execution/log` | GET | — | ❌ |
| 46 | `/api/execution/algo-config` | GET | — | ❌ |
| 47 | `/api/execution/qmt-status` | GET | execution.ts:227 | ✅ |
| 48 | `/api/execution/positions` | GET | execution.ts:232 | ✅ |
| 49 | `/api/execution/asset` | GET | execution.ts:237 | ✅ |
| 50 | `/api/execution/orders` | GET | execution.ts:242 | ✅ |
| 51 | `/api/execution/trades` | GET | execution.ts:247 | ✅ |
| 52 | `/api/execution/drift` | GET | execution.ts:252 | ✅ |
| 53 | `/api/execution/cancel-all` | POST | execution.ts:273 | ✅ |
| 54 | `/api/execution/cancel/{order_id}` | POST | execution.ts:280 | ✅ |
| 55 | `/api/execution/fix-drift/preview` | POST | execution.ts:287 | ✅ |
| 56 | `/api/execution/fix-drift/execute` | POST | execution.ts:297 | ✅ |
| 57 | `/api/execution/trigger-rebalance` | POST | execution.ts:306 | ✅ |
| 58 | `/api/execution/emergency-liquidate` | POST | execution.ts:316 | ✅ |
| 59 | `/api/execution/pause-trading` | POST | execution.ts:325 | ✅ |
| 60 | `/api/execution/resume-trading` | POST | execution.ts:332 | ✅ |
| 61 | `/api/execution/trading-paused` | GET | execution.ts:257 | ✅ |
| 62 | `/api/execution/alert-config` | PUT | — | ❌ |
| 63 | `/api/execution/audit-log` | GET | execution.ts:262 | ✅ |
| 64 | `/api/factors/health` | GET | factors.ts:120 | ✅ |
| 65 | `/api/factors/correlation` | GET | factors.ts:115 | ✅ |
| 66 | `/api/factors/summary` | GET | factors.ts:100 | ✅ |
| 67 | `/api/factors/stats` | GET | factors.ts:110 | ✅ |
| 68 | `/api/factors` | GET | factors.ts:105 | ✅ |
| 69 | `/api/factors/{name}` | GET | — | ❌ |
| 70 | `/api/factors/{name}/report` | GET | factors.ts:126 | ✅ |
| 71 | `/api/factors/{name}/archive` | POST | factors.ts:196 | ✅ |
| 72 | `/api/health` | GET | — | ❌ |
| 73 | `/api/health/checks` | GET | — | ❌ |
| 74 | `/api/health/qmt` | GET | — | ❌ |
| 75 | `/api/market/indices` | GET | — | ❌ |
| 76 | `/api/market/sectors` | GET | — | ❌ |
| 77 | `/api/market/top-movers` | GET | — | ❌ |
| 78 | `/api/mining/run` | POST | mining.ts:142 | ✅ |
| 79 | `/api/mining/tasks` | GET | mining.ts:166 | ✅ |
| 80 | `/api/mining/tasks/{task_id}` | GET | mining.ts:184 | ✅ |
| 81 | `/api/mining/tasks/{task_id}/cancel` | POST | mining.ts:190 | ✅ |
| 82 | `/api/mining/evaluate` | POST | mining.ts:211 | ✅ |
| 83 | `/api/news/ingest` | POST | — | ❌ |
| 84 | `/api/news/ingest_rsshub` | POST | — | ❌ |
| 85 | `/api/news/ingest_announcement` | POST | — | ❌ |
| 86 | `/api/news/stats` | GET | — | ❌ |
| 87 | `/api/notifications` | GET | — | ❌ |
| 88 | `/api/notifications/unread-count` | GET | — | ❌ |
| 89 | `/api/notifications/{notification_id}` | GET | — | ❌ |
| 90 | `/api/notifications/{notification_id}/read` | PUT | — | ❌ |
| 91 | `/api/notifications/test` | POST | — | ❌ |
| 92 | `/api/paper-trading/status` | GET | — | ❌ |
| 93 | `/api/paper-trading/graduation` | GET | — | ❌ |
| 94 | `/api/paper-trading/graduation-status` | GET | — | ❌ |
| 95 | `/api/paper-trading/positions` | GET | — | ❌ |
| 96 | `/api/paper-trading/trades` | GET | — | ❌ |
| 97 | `/api/params` | GET | system.ts:72 | ✅ |
| 98 | `/api/params/changelog` | GET | — | ❌ |
| 99 | `/api/params/{key}` | GET | — | ❌ |
| 100 | `/api/params/{key}` | PUT | system.ts:85 | ✅ |
| 101 | `/api/params/init-defaults` | POST | — | ❌ |
| 102 | `/api/pipeline/status` | GET | pipeline.ts:96 | ✅ |
| 103 | `/api/pipeline/runs` | GET | pipeline.ts:111 | ✅ |
| 104 | `/api/pipeline/runs/{run_id}` | GET | pipeline.ts:150 | ✅ |
| 105 | `/api/pipeline/runs/{run_id}/approve/{factor_id}` | POST | pipeline.ts:160 | ✅ |
| 106 | `/api/pipeline/runs/{run_id}/reject/{factor_id}` | POST | pipeline.ts:171 | ✅ |
| 107 | `/api/pms/positions` | GET | — | ❌ |
| 108 | `/api/pms/history` | GET | — | ❌ |
| 109 | `/api/pms/config` | GET | — | ❌ |
| 110 | `/api/pms/check` | POST | — | ❌ |
| 111 | `/api/portfolio/holdings` | GET | — | ❌ |
| 112 | `/api/portfolio/sector-distribution` | GET | — | ❌ |
| 113 | `/api/portfolio/daily-pnl` | GET | — | ❌ |
| 114 | `/api/realtime/portfolio` | GET | realtime.ts:84 | ✅ |
| 115 | `/api/realtime/market` | GET | realtime.ts:89 | ✅ |
| 116 | `/api/v1/ping` | GET | — | ❌ |
| 117 | `/api/v1/status` | GET | — | ❌ |
| 118 | `/api/reports/list` | GET | — | ❌ |
| 119 | `/api/reports/quick-stats` | GET | — | ❌ |
| 120 | `/api/reports/generate` | POST | — | ❌ |
| 121 | `/api/risk/state/{strategy_id}` | GET | — | ❌ |
| 122 | `/api/risk/history/{strategy_id}` | GET | — | ❌ |
| 123 | `/api/risk/summary/{strategy_id}` | GET | — | ❌ |
| 124 | `/api/risk/l4-recovery/{strategy_id}` | POST | — | ❌ |
| 125 | `/api/risk/l4-approve/{approval_id}` | POST | — | ❌ |
| 126 | `/api/risk/force-reset/{strategy_id}` | POST | — | ❌ |
| 127 | `/api/risk/overview` | GET | — | ❌ |
| 128 | `/api/risk/limits` | GET | — | ❌ |
| 129 | `/api/risk/stress-tests` | GET | — | ❌ |
| 130 | `/api/risk/dingtalk-webhook` | POST | — | ❌ |
| 131 | `/api/sse/risk-events` | GET | — | ❌ |
| 132 | `/api/strategies` | GET | strategies.ts:47 | ✅ |
| 133 | `/api/strategies/{strategy_id}` | GET | strategies.ts:67 | ✅ |
| 134 | `/api/strategies/{strategy_id}/versions` | GET | — | ❌ |
| 135 | `/api/strategies/{strategy_id}/versions` | POST | — | ❌ |
| 136 | `/api/strategies/{strategy_id}/rollback` | POST | — | ❌ |
| 137 | `/api/strategies` | POST | strategies.ts:72 | ✅ |
| 138 | `/api/strategies/{strategy_id}` | PUT | strategies.ts:77 | ✅ |
| 139 | `/api/strategies/{strategy_id}` | DELETE | strategies.ts:82 | ✅ |
| 140 | `/api/strategies/{strategy_id}/factors` | GET | — | ❌ |
| 141 | `/api/strategies/{strategy_id}/backtest` | POST | — | ❌ |
| 142 | `/api/system/datasources` | GET | system.ts:57 | ✅ |
| 143 | `/api/system/health` | GET | system.ts:67 | ✅ |
| 144 | `/api/system/streams` | GET | — | ❌ |
| 145 | `/api/system/scheduler` | GET | system.ts:62 | ✅ |
| 146 | `/api/system/test-notification` | POST | system.ts:93 | ✅ |
| 147 | `/api/system/calendar-info` | GET | system.ts:130 | ✅ |
| 148 | `/api/system/env-state` | GET | system.ts:103 | ✅ |

---

## §5 Unused Endpoint Candidates (Backend-Only, 74 endpoints)

> These endpoints have no frontend consumer in `frontend/src/api/*.ts`. Some are legitimate (admin scripts, DingTalk webhooks, health probes); others may be Phase J cleanup candidates.

### 5A — Likely Legitimate (ops / webhook / script-triggered)

| # | Endpoint | Rationale |
|---|----------|-----------|
| 72–74 | `/api/health`, `/api/health/checks`, `/api/health/qmt` | Consumed by Servy / monitoring, not frontend |
| 116–117 | `/api/v1/ping`, `/api/v1/status` | Remote ops script (`remote_status.py`) — external monitoring |
| 130 | `/api/risk/dingtalk-webhook` | DingTalk webhook receiver — not frontend-initiated |
| 131 | `/api/sse/risk-events` | SSE stream — consumed via `EventSource` in frontend JS, not apiClient |
| 83–85 | `/api/news/ingest*` | Script-triggered ingest, not user-facing UI |
| 91 | `/api/notifications/test` | Admin test only |

### 5B — Dashboard Module Gap (8 endpoints)

All 8 `/api/dashboard/*` endpoints (#36–43) have no frontend API module consumer. `dashboard.ts` exists but contains only a comment. Dashboard data is likely fetched via react-query hooks in page components directly, bypassing the api layer — **check `frontend/src/pages/` for direct axios/fetch usage**.

### 5C — Deprecated / Low Priority

| # | Endpoint | Rationale |
|---|----------|-----------|
| 107–110 | `/api/pms/*` | PMS deprecated (ADR-010, PR #34 stopped Beat) |
| 98 | `/api/params/changelog` | No frontend UI for changelog |
| 99 | `/api/params/{key}` GET | Only PUT consumed; GET by key unused |
| 101 | `/api/params/init-defaults` | Init script only |

### 5D — Backend-Implemented But Frontend Not Yet Wired

| # | Endpoint | Priority |
|---|----------|----------|
| 12–16 | `/api/approval/queue/{item_id}` detail + approve/reject/hold + history | Approval workflow incomplete in frontend |
| 24–32, 34–35 | `/api/backtest/{run_id}/nav`, `/trades`, `/holdings`, `/annual`, `/monthly`, `/attribution`, `/market-state`, `/cost-sensitivity`, `/report`, `/sensitivity`, `/live-compare` | Backtest detail views not yet connected |
| 44–46 | `/api/execution/pending-orders`, `/log`, `/algo-config` | `execution.py` router has 3 endpoints, none consumed |
| 62 | `/api/execution/alert-config` PUT | Alert config mutation not wired |
| 69 | `/api/factors/{name}` GET | Factor detail page not using factor detail endpoint |
| 75–77 | `/api/market/*` | Market data not consumed by any frontend module |
| 87–90 | `/api/notifications/*` | Notifications panel not using API module |
| 92–96 | `/api/paper-trading/*` | Paper trading status not wired to frontend |
| 111–113 | `/api/portfolio/*` | Portfolio panel bypasses API module |
| 118–120 | `/api/reports/*` | Report generation not wired |
| 121–129 | `/api/risk/*` (10 endpoints) | Risk framework dashboard not wired |
| 134–136, 140–141 | `/api/strategies/{id}/versions`, `/rollback`, `/factors`, `/backtest` | Strategy management partially wired |
| 144 | `/api/system/streams` | Streams viewer not wired |

---

## §6 Frontend-Only Orphans (No Matching Backend Endpoint)

> These frontend calls have no matching `@router.*` definition in `backend/app/api/`. They are potential bugs or endpoints that were removed/renamed.

| # | File:Line | Method | URL Called | Notes |
|---|-----------|--------|------------|-------|
| O1 | backtest.ts:183 | POST | `/backtest/{runId}/cancel` | No cancel endpoint in backtest.py — cancel may be Celery task revoke only |
| O2 | pipeline.ts:101 | POST | `/pipeline/trigger` | No trigger endpoint in pipeline.py (only status/runs/approve/reject) |
| O3 | pipeline.ts:106 | POST | `/pipeline/pause` | No pause endpoint in pipeline.py |
| O4 | pipeline.ts:122 | POST | `/pipeline/approve/{id}` | Uses old approval path — backend uses `/approval/queue/{item_id}/approve` |
| O5 | pipeline.ts:126 | POST | `/pipeline/reject/{id}` | Uses old rejection path — backend uses `/approval/queue/{item_id}/reject` |
| O6 | pipeline.ts:130 | POST | `/pipeline/hold/{id}` | Uses old hold path — backend uses `/approval/queue/{item_id}/hold` |
| O7 | pipeline.ts:134 | GET | `/pipeline/{runId}/logs` | No logs endpoint in pipeline.py |
| O8 | pipeline.ts:139 | PUT | `/pipeline/automation-level` | No automation-level endpoint in pipeline.py |
| O9 | factors.ts:200 | POST | `/factors/health` | Backend has GET `/api/factors/health` (factors.py:57) — method mismatch |
| O10 | factors.ts:204 | POST | `/factors/correlation-prune` | No correlation-prune endpoint in factors.py |

**Pipeline.ts is the highest-risk file**: 7 of 13 calls target non-existent backend paths. The approval workflow routes (`/pipeline/approve|reject|hold`) use the wrong prefix — should be `/approval/queue/{item_id}/approve|reject|hold` per approval.py router.

### §6.1 Update — 2026-05-22 Phase K reconciliation (L4+R loop iteration 1)

Re-verified against current code (`main` HEAD `f70b04a`). The §6 snapshot above (2026-05-20) is stale for the pipeline.ts orphans — 4 of the 7 are already resolved:

| Orphan | Current state (2026-05-22) |
|---|---|
| O2 `/pipeline/trigger` | **RESOLVED.** Backend `POST /api/pipeline/trigger` exists and is fully implemented (`pipeline.py::trigger_pipeline`, requires `TriggerPipelineRequest {engine, config}`). Frontend `triggerPipeline()` was stale (sent no body → 422); fixed this iteration to send `{engine, config}` + a correct `TriggerPipelineResult` return type. |
| O4 `/pipeline/approve/{id}` | **RESOLVED** (prior work). `approveItem()` now calls `POST /api/approval/queue/{id}/approve`. |
| O5 `/pipeline/reject/{id}` | **RESOLVED** (prior work). `rejectItem()` now calls `POST /api/approval/queue/{id}/reject`. |
| O6 `/pipeline/hold/{id}` | **RESOLVED** (prior work). `holdItem()` now calls `POST /api/approval/queue/{id}/hold`. |
| O3 `/pipeline/pause` | **STILL ORPHAN.** No backend endpoint. Needs a build decision (pausing a running Celery GP task is non-trivial). |
| O7 `/pipeline/{runId}/logs` | **STILL ORPHAN.** No backend endpoint. `getPipelineLogs` 404 is caught silently → "AI决策日志" tab shows empty. |
| O8 `/pipeline/automation-level` | **STILL ORPHAN.** No backend endpoint. The L0–L3 automation selector in PipelineConsole 404s. Needs a persistence-model decision. |

**Remaining orphans: 10 → 6** (O1, O3, O7, O8, O9, O10).

**NEW finding (separate from orphan classification):** `GET /api/pipeline/status` *is* consumed (#102), but the backend response shape (`active_run_id` / `node_statuses` dict / `progress` / `config_summary` …) does **not** match the frontend `PipelineStatus` interface (`run_id` / `nodes[]` / `automation_level` / `is_running` / `is_paused` / `schedule_cron` / `next_run_at` / `last_run_at`). PipelineConsole's status display, FlowChart, automation-level and schedule cards are fed `undefined` for most fields. This is contract-shape drift, not an orphan — and `automation_level` / `schedule_cron` / `next_run_at` / `last_run_at` have no backend source at all.

**Deferred:** O3 / O7 / O8 + the `/pipeline/status` contract reconciliation form a single PipelineConsole↔backend integration task with product-scope decisions (pipeline pausability, pipeline-log source, `automation_level` persistence) — not closed by this iteration; tracked as a backlog item.

---

## §7 Auth Coverage

Auth implementation: `app.core.auth.verify_admin_token` — reads HttpOnly cookie set by `POST /api/auth/admin-token`.

### Admin-Gated Endpoints (22 total)

| Router | Endpoints Gated | File:Line (auth dep) |
|--------|-----------------|----------------------|
| agent | POST /chat, GET /chat/status, PUT /{name}/config, POST /{name}/config/reset, GET /{name}/history, POST /{name}/config/rollback, GET /model-health, GET /cost-summary, GET /{name}/logs (9) | agent.py:188, 288, 675, 700, 718, 748, 789, 820, 863 |
| approval | POST /approve, POST /reject, POST /hold (3) | approval.py:264, 295, 326 |
| auth | POST /admin-token/clear (1) | auth.py:104 |
| execution_ops | POST /cancel-all, POST /cancel/{id}, POST /fix-drift/preview, POST /fix-drift/execute, POST /trigger-rebalance, POST /emergency-liquidate, POST /pause-trading, POST /resume-trading, PUT /alert-config (9 — shares `_verify_admin_token` alias) | execution_ops.py:536, 575, 601, 655, 717, 748, 791, 804, 824 |
| risk | POST /l4-recovery, POST /l4-approve, POST /force-reset (3) | risk.py:212, 244, 279 |
| sse | GET /risk-events (1) | sse.py:168 |

### Public Endpoints (126 total)

All remaining endpoints — no `Depends(verify_admin_token)`. Includes read-only data endpoints and non-destructive operations.

### Auth Notes

- `execution_ops.py` uses `_verify_admin_token` alias (imported as `from app.core.auth import verify_admin_token as _verify_admin_token`, execution_ops.py:26) — same implementation.
- `POST /api/auth/admin-token` (set cookie) is intentionally public — it validates the token value server-side before setting the cookie.
- Rate limiting (`Depends(rate_limit_chat)`) applied additionally at agent.py:189 (10 req/min per IP).

---

## §8 Verification

```
grep -c "@router\." backend/app/api/*.py | awk -F: '{sum += $2} END {print sum}'
# Expected: 148
```

Endpoint count by router file:
- agent: 10, approval: 6, auth: 3, backtest: 16, dashboard: 8
- execution: 3, execution_ops: 17, factors: 8, health: 3, market: 3
- mining: 5, news: 4, notifications: 5, paper_trading: 5, params: 5
- pipeline: 5, pms: 4, portfolio: 3, realtime: 2, remote_status: 2
- report: 3, risk: 10, sse: 1, strategies: 10, system: 7
- **Total: 148** ✓

Frontend modules: 11 files (agent / backtest / client / dashboard / execution / factors / mining / pipeline / realtime / strategies / system)  
Total frontend apiClient calls: 83 (deduplicated by URL: ~60 unique paths)
