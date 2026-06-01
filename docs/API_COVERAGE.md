# API Coverage Matrix — QuantMind V2

**Generated**: 2026-05-20
**Fresh verify addendum**: 2026-05-25 §9 is the current count baseline. The original
matrix body is retained as historical audit evidence.
**Current backend surface**: 170 endpoints across 25 router files (§22.5)
**Current frontend API modules**: 18 files (§22.5)
**Current frontend-only orphan**: 0 after the 2026-05-28 O7 HTTP backfill closure
(§10)
**Methodology**: `@router.(get|post|put|delete|patch)` grep on `backend/app/api/**/*.py` + `apiClient.(get|post|put|delete|patch)` grep on `frontend/src/api/*.ts`

---

## §1 Executive Summary

| Metric | Count | % |
|--------|-------|---|
| Total backend endpoints | 170 | 100% |
| Frontend-only orphans (no matching backend) | 0 | — |
| Original 2026-05-20 backend endpoints | 148 | historical |
| Original 2026-05-20 frontend-only orphans | 10 | historical |

**Key findings**:
- The 2026-05-20 50% backend-only ratio is historical. Use §22.5 for the current
  endpoint count and orphan status.
- Original 10 frontend-only orphans were reconciled to 0. O7
  `GET /api/pipeline/{run_id}/logs` now has a Redis-backed HTTP endpoint; PN-005
  writer instrumentation and WebSocket tailing remain tracked as enhancement work,
  not frontend-only orphan work.
- Notification panel mock seeding is closed in §11: list, per-row read, and
  read-all flows now consume `frontend/src/api/notifications.ts`.
- Dashboard secondary panels are closed in §12: alerts, monthly returns,
  industry distribution, factor rows, and pipeline steps now go through
  `frontend/src/api/dashboard.ts` wrappers instead of page-level `apiClient`
  calls.
- Portfolio endpoints are closed in §13: holdings, sector distribution, and
  daily PnL now go through `frontend/src/api/portfolio.ts`; sector `value` is
  normalized to percentage for chart consumers.
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
| 20 | POST | `/api/backtest/run` | Start backtest run | backtest.py:169 | public |
| 20a | POST | `/api/backtest/{run_id}/cancel` | Cancel backtest run | backtest.py:243 | public |
| 21 | GET | `/api/backtest/history` | Backtest run history | backtest.py:292 | public |
| 22 | GET | `/api/backtest/{run_id}` | Backtest run status | backtest.py:364 | public |
| 23 | GET | `/api/backtest/{run_id}/result` | Backtest result | backtest.py:388 | public |
| 24 | GET | `/api/backtest/{run_id}/nav` | NAV series | backtest.py:457 | public |
| 25 | GET | `/api/backtest/{run_id}/trades` | Trade list | backtest.py:509 | public |
| 26 | GET | `/api/backtest/{run_id}/holdings` | Holdings | backtest.py:596 | public |
| 27 | GET | `/api/backtest/{run_id}/annual` | Annual returns | backtest.py:658 | public |
| 28 | GET | `/api/backtest/{run_id}/monthly` | Monthly returns | backtest.py:727 | public |
| 29 | GET | `/api/backtest/{run_id}/attribution` | Factor attribution | backtest.py:783 | public |
| 30 | GET | `/api/backtest/{run_id}/market-state` | Market state | backtest.py:838 | public |
| 31 | GET | `/api/backtest/{run_id}/cost-sensitivity` | Cost sensitivity | backtest.py:920 | public |
| 32 | GET | `/api/backtest/{run_id}/report` | Backtest report | backtest.py:1035 | public |
| 33 | POST | `/api/backtest/compare` | Compare runs | backtest.py:1137 | public |
| 34 | POST | `/api/backtest/{run_id}/sensitivity` | Sensitivity analysis | backtest.py:1198 | public |
| 35 | GET | `/api/backtest/{run_id}/live-compare` | Live vs backtest | backtest.py:1296 | public |

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
| 87 | GET | `/api/notifications` | List notifications | notifications.py:74 | public |
| 88 | GET | `/api/notifications/unread-count` | Unread count | notifications.py:107 | public |
| 89 | GET | `/api/notifications/{notification_id}` | Notification detail | notifications.py:186 | public |
| 90 | PUT | `/api/notifications/{notification_id}/read` | Mark as read | notifications.py:208 | public |
| 91 | POST | `/api/notifications/test` | Test notification | notifications.py:230 | public |

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

### 2.17 pms — RETIRED iter 50 2026-05-24 (ADR-094)

**Status**: 🗑️ PHYSICALLY RETIRED. `backend/app/api/pms.py` + `backend/app/services/pms_engine.py` + `pms_daily_check_task` deleted. Router unregistered from `app/main.py`. V3 风控 SSOT 走 `qm_platform/risk/rules/pms.py` (V3 §4 L1 PMSRule) + `qm_platform/risk/rules/realtime/trailing_stop.py` (V3 §7.3 dynamic). Frontend `/pms` page + Sidebar entry + router entry 同 PR 物理移除. Endpoints 107-110 全部 404 — historical rows below kept for audit trail only.

| # | Method | Path | Handler | File:Line | Auth |
|---|--------|------|---------|-----------|------|
| 107 | GET | `/api/pms/positions` | RETIRED iter 50 | — | 404 |
| 108 | GET | `/api/pms/history` | RETIRED iter 50 | — | 404 |
| 109 | GET | `/api/pms/config` | RETIRED iter 50 | — | 404 |
| 110 | POST | `/api/pms/check` | RETIRED iter 50 | — | 404 |

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
| backtest.ts:234 | POST | `/backtest/run` |
| backtest.ts:239 | GET | `/backtest/{runId}` |
| backtest.ts:255 | GET | `/backtest/{runId}/result` |
| backtest.ts:289 | POST | `/backtest/{runId}/cancel` |
| backtest.ts:293 | GET | `/backtest/history` |
| backtest.ts:348 | POST | `/backtest/compare` |
| backtest.ts:515 | GET | `/backtest/{runId}/nav` |
| backtest.ts:523 | GET | `/backtest/{runId}/trades` |
| backtest.ts:541 | GET | `/backtest/{runId}/monthly` |
| backtest.ts:553/567 | GET | `/backtest/{runId}/holdings` |
| backtest.ts:636 | GET | `/backtest/{runId}/annual` |
| backtest.ts:660 | GET | `/backtest/{runId}/attribution` |
| backtest.ts:682 | GET | `/backtest/{runId}/cost-sensitivity` |
| backtest.ts:707 | GET | `/backtest/{runId}/market-state` |
| backtest.ts:742 | GET | `/backtest/{runId}/live-compare` |
| backtest.ts:759 | URL helper | `/backtest/{runId}/report` |

**15 HTTP calls + 1 report URL helper → 16 consumed (#20, #20a, #21-33, #35)**.
Historical O1 cancel orphan is resolved by `backend/app/api/backtest.py:243`;
backtest deep-dive rows 26-32 and 35 are closed in §23.

### 3.3 client.ts (`frontend/src/api/client.ts`)

Axios instance definition only. No direct API calls. **0 calls**.

### 3.4 dashboard.ts (`frontend/src/api/dashboard.ts`)

Historical 2026-05-20 snapshot. Superseded by §12 Fresh verify.

Current wrapper coverage includes Dashboard summary, NAV, pending actions,
alerts, monthly returns, industry distribution, paper trades, positions,
strategy overview, factor rows, and pipeline steps.

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
| factors.ts:35 | GET | `/factors/ic-monitoring` |
| factors.ts:61 | GET | `/factors/{name}` |
| factors.ts:78 | GET | `/factors/stats` |
| factors.ts:96 | GET | `/factors/health` |
| factors.ts:197 | GET | `/factors/summary` |
| factors.ts:202 | GET | `/factors` |
| factors.ts:207 | GET | `/factors/stats` |
| factors.ts:212 | GET | `/factors/correlation` |
| factors.ts:217 | GET | `/factors/health` |
| factors.ts:223 | GET | `/factors/{name}/report` |
| factors.ts:293 | POST | `/factors/{name}/archive` |
| factors.ts:300 | POST | `/factors/health-check` |
| factors.ts:304 | POST | `/factors/correlation-prune` |

**13 calls → all 13 consumed** (IcMonitoring + factor library/evaluation + O9/O10 repaired)

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
| system.ts:110 | GET | `/system/datasources` |
| system.ts:149 | GET | `/system/scheduler` |
| system.ts:185 | GET | `/system/beat-schedule` |
| system.ts:190 | GET | `/system/health` |
| system.ts:195 | GET | `/system/streams` |
| system.ts:200 | GET | `/health/qmt` |
| system.ts:205 | GET | `/params` |
| system.ts:218 | PUT | `/params/{key}` |
| system.ts:226 | POST | `/system/test-notification` |
| system.ts:236 | GET | `/system/env-state` |
| system.ts:263 | GET | `/system/calendar-info` |
| system.ts:285 | GET | `/system/settings/paper-strategy-id` |
| system.ts:325 | GET | `/system/scheduler-task-log` |

**13 calls → all 13 consumed** (#142, #145, beat dashboard, #143, #144, #74, #97, #100, #146, #148, #147, D5, scheduler dashboard)

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
| 12 | `/api/approval/queue/{item_id}` | GET | approval.ts:92 | ✅ |
| 13 | `/api/approval/queue/{item_id}/approve` | POST | approval.ts:98 | ✅ |
| 14 | `/api/approval/queue/{item_id}/reject` | POST | approval.ts:110 | ✅ |
| 15 | `/api/approval/queue/{item_id}/hold` | POST | approval.ts:122 | ✅ |
| 16 | `/api/approval/history` | GET | approval.ts:134 | ✅ |
| 17 | `/api/auth/admin-token` | POST | execution.ts:164 | ✅ |
| 18 | `/api/auth/admin-token/clear` | POST | execution.ts:186 | ✅ |
| 19 | `/api/auth/admin-token/status` | GET | execution.ts:204 | ✅ |
| 20 | `/api/backtest/run` | POST | backtest.ts:234 | ✅ |
| 21 | `/api/backtest/history` | GET | backtest.ts:293 | ✅ |
| 22 | `/api/backtest/{run_id}` | GET | backtest.ts:239 | ✅ |
| 23 | `/api/backtest/{run_id}/result` | GET | backtest.ts:255 | ✅ |
| 24 | `/api/backtest/{run_id}/nav` | GET | backtest.ts:515 | ✅ |
| 25 | `/api/backtest/{run_id}/trades` | GET | backtest.ts:523 | ✅ |
| 26 | `/api/backtest/{run_id}/holdings` | GET | backtest.ts:553/567/591 | ✅ |
| 27 | `/api/backtest/{run_id}/annual` | GET | backtest.ts:636/650 | ✅ |
| 28 | `/api/backtest/{run_id}/monthly` | GET | backtest.ts:541 | ✅ |
| 29 | `/api/backtest/{run_id}/attribution` | GET | backtest.ts:660 | ✅ |
| 30 | `/api/backtest/{run_id}/market-state` | GET | backtest.ts:707 | ✅ |
| 31 | `/api/backtest/{run_id}/cost-sensitivity` | GET | backtest.ts:682 | ✅ |
| 32 | `/api/backtest/{run_id}/report` | GET | backtest.ts:759 | ✅ |
| 33 | `/api/backtest/compare` | POST | backtest.ts:348 | ✅ |
| 34 | `/api/backtest/{run_id}/sensitivity` | POST | — | ❌ |
| 35 | `/api/backtest/{run_id}/live-compare` | GET | backtest.ts:742 | ✅ |
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
| 64 | `/api/factors/health` | GET | factors.ts:96/217 | ✅ |
| 65 | `/api/factors/correlation` | GET | factors.ts:212 | ✅ |
| 66 | `/api/factors/summary` | GET | factors.ts:197 | ✅ |
| 67 | `/api/factors/stats` | GET | factors.ts:78/207 | ✅ |
| 68 | `/api/factors` | GET | factors.ts:202 | ✅ |
| 69 | `/api/factors/{name}` | GET | factors.ts:61 | ✅ |
| 70 | `/api/factors/{name}/report` | GET | factors.ts:223 | ✅ |
| 71 | `/api/factors/{name}/archive` | POST | factors.ts:293 | ✅ |
| 72 | `/api/health` | GET | — | ❌ |
| 73 | `/api/health/checks` | GET | — | ❌ |
| 74 | `/api/health/qmt` | GET | system.ts:200 | ✅ |
| 75 | `/api/market/indices` | GET | market.ts:34 | ✅ |
| 76 | `/api/market/sectors` | GET | market.ts:39 | ✅ |
| 77 | `/api/market/top-movers` | GET | market.ts:47 | ✅ |
| 78 | `/api/mining/run` | POST | mining.ts:142 | ✅ |
| 79 | `/api/mining/tasks` | GET | mining.ts:166 | ✅ |
| 80 | `/api/mining/tasks/{task_id}` | GET | mining.ts:184 | ✅ |
| 81 | `/api/mining/tasks/{task_id}/cancel` | POST | mining.ts:190 | ✅ |
| 82 | `/api/mining/evaluate` | POST | mining.ts:211 | ✅ |
| 83 | `/api/news/ingest` | POST | — | ❌ |
| 84 | `/api/news/ingest_rsshub` | POST | — | ❌ |
| 85 | `/api/news/ingest_announcement` | POST | — | ❌ |
| 86 | `/api/news/stats` | GET | — | ❌ |
| 87 | `/api/notifications` | GET | notifications.ts:113 | ✅ |
| 88 | `/api/notifications/unread-count` | GET | list response `unread_count` | ⚠️ redundant |
| 89 | `/api/notifications/{notification_id}` | GET | notifications.ts:129 | ✅ |
| 90 | `/api/notifications/{notification_id}/read` | PUT | notifications.ts:138 | ✅ |
| 91 | `/api/notifications/test` | POST | — | ❌ |
| 92 | `/api/paper-trading/status` | GET | — | ❌ |
| 93 | `/api/paper-trading/graduation` | GET | — | ❌ |
| 94 | `/api/paper-trading/graduation-status` | GET | dashboard.ts:99 | ✅ |
| 95 | `/api/paper-trading/positions` | GET | dashboard.ts:109 | ✅ |
| 96 | `/api/paper-trading/trades` | GET | dashboard.ts:67 | ✅ |
| 97 | `/api/params` | GET | system.ts:205 | ✅ |
| 98 | `/api/params/changelog` | GET | — | ❌ |
| 99 | `/api/params/{key}` | GET | — | ❌ |
| 100 | `/api/params/{key}` | PUT | system.ts:218 | ✅ |
| 101 | `/api/params/init-defaults` | POST | — | ❌ |
| 102 | `/api/pipeline/status` | GET | pipeline.ts:96 | ✅ |
| 103 | `/api/pipeline/runs` | GET | pipeline.ts:111 | ✅ |
| 104 | `/api/pipeline/runs/{run_id}` | GET | pipeline.ts:150 | ✅ |
| 105 | `/api/pipeline/runs/{run_id}/approve/{factor_id}` | POST | pipeline.ts:160 | ✅ |
| 106 | `/api/pipeline/runs/{run_id}/reject/{factor_id}` | POST | pipeline.ts:171 | ✅ |
| 107 | `/api/pms/positions` | GET | — | 🗑️ RETIRED iter 50 (ADR-094) |
| 108 | `/api/pms/history` | GET | — | 🗑️ RETIRED iter 50 (ADR-094) |
| 109 | `/api/pms/config` | GET | — | 🗑️ RETIRED iter 50 (ADR-094) |
| 110 | `/api/pms/check` | POST | — | 🗑️ RETIRED iter 50 (ADR-094) |
| 111 | `/api/portfolio/holdings` | GET | portfolio.ts:93 | ✅ |
| 112 | `/api/portfolio/sector-distribution` | GET | portfolio.ts:63 | ✅ |
| 113 | `/api/portfolio/daily-pnl` | GET | portfolio.ts:83 | ✅ |
| 114 | `/api/realtime/portfolio` | GET | realtime.ts:84 | ✅ |
| 115 | `/api/realtime/market` | GET | realtime.ts:89 | ✅ |
| 116 | `/api/v1/ping` | GET | — | ❌ |
| 117 | `/api/v1/status` | GET | — | ❌ |
| 118 | `/api/reports/list` | GET | reports.ts:143 | ✅ |
| 119 | `/api/reports/quick-stats` | GET | reports.ts:150 | ✅ |
| 120 | `/api/reports/generate` | POST | reports.ts:168 | ✅ |
| 121 | `/api/risk/state/{strategy_id}` | GET | risk.ts:176 | ✅ |
| 122 | `/api/risk/history/{strategy_id}` | GET | risk.ts:225 | ✅ |
| 123 | `/api/risk/summary/{strategy_id}` | GET | risk.ts:241 | ✅ |
| 124 | `/api/risk/l4-recovery/{strategy_id}` | POST | risk.ts:200 | ✅ |
| 125 | `/api/risk/l4-approve/{approval_id}` | POST | risk.ts:213 | ✅ |
| 126 | `/api/risk/force-reset/{strategy_id}` | POST | risk.ts:187 | ✅ |
| 127 | `/api/risk/overview` | GET | risk.ts:252 | ✅ |
| 128 | `/api/risk/limits` | GET | risk.ts:268 | ✅ |
| 129 | `/api/risk/stress-tests` | GET | risk.ts:277 | ✅ |
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
| 142 | `/api/system/datasources` | GET | system.ts:110 | ✅ |
| 143 | `/api/system/health` | GET | system.ts:190 | ✅ |
| 144 | `/api/system/streams` | GET | system.ts:195 | ✅ |
| 145 | `/api/system/scheduler` | GET | system.ts:149 | ✅ |
| 146 | `/api/system/test-notification` | POST | system.ts:226 | ✅ |
| 147 | `/api/system/calendar-info` | GET | system.ts:263 | ✅ |
| 148 | `/api/system/env-state` | GET | system.ts:236 | ✅ |

---

## §5 Unused Endpoint Candidates (historical backend-only snapshot)

> These endpoints have no frontend consumer in `frontend/src/api/*.ts`. Some are legitimate (admin scripts, DingTalk webhooks, health probes); others may be Phase J cleanup candidates.

### 5A — Likely Legitimate (ops / webhook / script-triggered)

| # | Endpoint | Rationale |
|---|----------|-----------|
| 72–73 | `/api/health`, `/api/health/checks` | Consumed by Servy / monitoring, not frontend |
| 74 | `/api/health/qmt` | Wrapped by `fetchQmtHealth()` for `QMTStatusBadge`; badge is exported but not mounted by current frontend routes |
| 116–117 | `/api/v1/ping`, `/api/v1/status` | Remote ops script (`remote_status.py`) — external monitoring |
| 130 | `/api/risk/dingtalk-webhook` | DingTalk webhook receiver — not frontend-initiated |
| 131 | `/api/sse/risk-events` | SSE stream — consumed via `EventSource` in frontend JS, not apiClient |
| 83–85 | `/api/news/ingest*` | Script-triggered ingest, not user-facing UI |
| 88 | `/api/notifications/unread-count` | Redundant for the panel because `GET /api/notifications` already returns `unread_count` |
| 91 | `/api/notifications/test` | Admin test only |

### 5B — Dashboard Module Gap (historical)

Historical 2026-05-20 snapshot. Dashboard secondary panels were closed in §12;
remaining dashboard work should be assessed from fresh code, not this stale
snapshot.

### 5C — Deprecated / Low Priority

| # | Endpoint | Rationale |
|---|----------|-----------|
| 107–110 | `/api/pms/*` | **PHYSICALLY RETIRED iter 50 2026-05-24 (ADR-094)** — pms_engine.py + api/pms.py + frontend page/route/nav 同 PR 全部删除. V3 SSOT 走 V3 §4 L1 PMSRule + V3 §7.3 trailing_stop |
| 98 | `/api/params/changelog` | No frontend UI for changelog |
| 99 | `/api/params/{key}` GET | Only PUT consumed; GET by key unused |
| 101 | `/api/params/init-defaults` | Init script only |

### 5D — Backend-Implemented But Frontend Not Yet Wired

| # | Endpoint | Priority |
|---|----------|----------|
| 34 | `/api/backtest/{run_id}/sensitivity` | Explicitly deferred/backlog; rows 26-32 and 35 are now consumed by BacktestResults (§23) |
| 44–46 | `/api/execution/pending-orders`, `/log`, `/algo-config` | `execution.py` router has 3 endpoints, none consumed |
| 62 | `/api/execution/alert-config` PUT | Alert config mutation not wired |
| 92–93 | `/api/paper-trading/status`, `/api/paper-trading/graduation` | Legacy PT status/criteria endpoints not wrapped by current frontend API layer |
| 134–136, 140–141 | `/api/strategies/{id}/versions`, `/rollback`, `/factors`, `/backtest` | Strategy management partially wired |

---

## §6 Historical Frontend-Only Orphans (2026-05-20 Snapshot)

> Historical snapshot retained for audit trail. Current truth is §1 + §6.1 + §10:
> all original 10 frontend-only orphans are reconciled to 0 as of 2026-05-28.

| # | File:Line | Method | URL Called | Notes |
|---|-----------|--------|------------|-------|
| O1 | backtest.ts:183 | POST | `/backtest/{runId}/cancel` | **RESOLVED** — backend cancel endpoint exists in `backtest.py:243`; see PR #446 note in §6.1 |
| O2 | pipeline.ts:101 | POST | `/pipeline/trigger` | No trigger endpoint in pipeline.py (only status/runs/approve/reject) |
| O3 | pipeline.ts:106 | POST | `/pipeline/pause` | **RESOLVED** — see §6.1 / PN-003 |
| O4 | pipeline.ts:122 | POST | `/pipeline/approve/{id}` | Uses old approval path — backend uses `/approval/queue/{item_id}/approve` |
| O5 | pipeline.ts:126 | POST | `/pipeline/reject/{id}` | Uses old rejection path — backend uses `/approval/queue/{item_id}/reject` |
| O6 | pipeline.ts:130 | POST | `/pipeline/hold/{id}` | Uses old hold path — backend uses `/approval/queue/{item_id}/hold` |
| O7 | pipeline.ts:134 | GET | `/pipeline/{runId}/logs` | **RESOLVED 2026-05-28** — backend HTTP backfill now exists; see §10 |
| O8 | pipeline.ts:139 | PUT | `/pipeline/automation-level` | **RESOLVED** — see §6.1 / PN-001 |
| O9 | factors.ts:300 | POST | `/factors/health-check` | **RESOLVED** — current wrapper targets backend `POST /api/factors/health-check`; see §25 |
| O10 | factors.ts:304 | POST | `/factors/correlation-prune` | **RESOLVED** — see §6.1 / PN-002 |

**Historical 2026-05-20 finding**: `pipeline.ts` was the highest-risk file, with
7 of 13 calls targeting non-existent or stale backend paths. This is no longer the
current state; §6.1 and §10 record the reconciled endpoint contracts and remaining
enhancement backlog.

### §6.1 Update — 2026-05-22 Phase K reconciliation (L4+R loop iteration 1)

Re-verified against current code (`main` HEAD `f70b04a`). The §6 snapshot above (2026-05-20) is stale for the pipeline.ts orphans — 4 of the 7 are already resolved:

| Orphan | Current state (2026-05-22) |
|---|---|
| O2 `/pipeline/trigger` | **RESOLVED.** Backend `POST /api/pipeline/trigger` exists and is fully implemented (`pipeline.py::trigger_pipeline`, requires `TriggerPipelineRequest {engine, config}`). Frontend `triggerPipeline()` was stale (sent no body → 422); fixed this iteration to send `{engine, config}` + a correct `TriggerPipelineResult` return type. |
| O4 `/pipeline/approve/{id}` | **RESOLVED** (prior work). `approveItem()` now calls `POST /api/approval/queue/{id}/approve`. |
| O5 `/pipeline/reject/{id}` | **RESOLVED** (prior work). `rejectItem()` now calls `POST /api/approval/queue/{id}/reject`. |
| O6 `/pipeline/hold/{id}` | **RESOLVED** (prior work). `holdItem()` now calls `POST /api/approval/queue/{id}/hold`. |
| O3 `/pipeline/pause` | **RESOLVED** (2026-05-23/24, iter 12 PN-003). Backend `POST /api/pipeline/pause` + `/resume` wired — gate-at-entry semantics (pipeline_settings.paused_at column; idempotent no-overwrite when already paused; mid-run cooperative abort explicitly out of scope per PN-003 §6). `GET /status` extended with `paused_at` + `paused_reason`. Frontend `pausePipeline(reason?)` + new `resumePipeline()` consumers. |
| O7 `/pipeline/{runId}/logs` | **RESOLVED 2026-05-28 at HTTP contract level.** Backend `GET /api/pipeline/{run_id}/logs` now reads Redis list `pipeline:logs:{run_id}` and returns `PipelineLogEntry[]`; manual trigger / approve / reject write first decision events. Remaining PN-005 scope is narrower: broader mining-task instrumentation, optional `/ws/pipeline/{run_id}` live tailing, and durable-retention decision. |
| O8 `/pipeline/automation-level` | **RESOLVED** (2026-05-23, iter 10 PN-001). Backend `GET /api/pipeline/automation-level` + `PUT /api/pipeline/automation-level` wired against a singleton `pipeline_settings` table (level L0–L3 enum + audit columns). Frontend `setAutomationLevel()` + `getAutomationLevel()` consumers. PR #450 squash `d26ac2a` / ADR-087. |

**Remaining orphans: 10 → 0** (O1 closed iter 5 PR #446 backtest cancel; O3 closed iter 12 PR #452 PN-003; O8 closed iter 10 PR #450 PN-001; O9 closed iters 3-4 PR #445 factor health POST; O10 closed iter 11 PR #451 PN-002 correlation-prune; O7 closed 2026-05-28 HTTP backfill).

**NEW finding (separate from orphan classification) — RESOLVED 2026-05-24 iter 15 PR #453 squash `7218496` / ADR-090:** `GET /api/pipeline/status` *is* consumed (#102), but the backend response shape (`active_run_id` / `node_statuses` dict / `progress` / `config_summary` …) did **not** match the frontend `PipelineStatus` interface (`run_id` / `nodes[]` / `automation_level` / `is_running` / `is_paused` / `schedule_cron` / `next_run_at` / `last_run_at`). Refactored response now exposes 8 frontend-aligned keys (`is_running` = status=='running' / `is_paused` = paused_at IS NOT NULL / `nodes[]` array mapped from `node_statuses` dict / `automation_level` read from `pipeline_settings` / `schedule_cron` + `next_run_at` from stdlib-only weekly-cron helper / `last_run_at` / `run_id`); legacy keys (`active_run_id` / `node_statuses` / `progress` / `config_summary`) retained as 1-sprint backward-compat aliases. See `docs/design/PN_004_pipeline_status_contract_refactor.md`.

**Deferred enhancements:** PN-005 writer coverage beyond trigger/approve/reject, optional WebSocket live tailing, and durable retention if Redis recent logs are not enough. No frontend-only API orphan remains.

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

---

## §9 Fresh verify — 2026-05-25 (iter 96 sub2, taskboard task_003)

**Methodology** (sustained §8): `@router.(get|post|put|delete|patch)` grep on `backend/app/api/**/*.py` + axios/apiClient consumer grep on `frontend/src/api/*.ts`. PowerShell `Select-String` count cross-checked against ripgrep.

### §9.1 Backend route inventory (FRESH)

**Total: 161 endpoints across 24 router files** (vs 148 / 25 files on 2026-05-20 — net **+13 endpoints / −1 file**, the −1 file = `pms.py` physically retired iter 50 2026-05-24 per [ADR-094](adr/ADR-094-pms-v1-physical-retirement.md)).

| Router | 2026-05-20 | 2026-05-25 (fresh) | Δ | Net change source |
|--------|-----------:|-------------------:|--:|-------------------|
| agent | 10 | 10 | 0 | sustained |
| approval | 6 | 6 | 0 | sustained |
| auth | 3 | 3 | 0 | sustained |
| **backtest** | 16 | **17** | **+1** | new endpoint (see §9.4) |
| dashboard | 8 | 8 | 0 | sustained |
| execution | 3 | 3 | 0 | sustained |
| execution_ops | 17 | 17 | 0 | sustained |
| **factors** | 8 | **10** | **+2** | `/archive`, `/health-check`, `/correlation-prune` (3 new, but `/health-check` was POST-method-mismatch fixed iter 3-4 not a new endpoint, net +2) |
| health | 3 | 3 | 0 | sustained |
| market | 3 | 3 | 0 | sustained |
| mining | 5 | 5 | 0 | sustained |
| news | 4 | 4 | 0 | sustained |
| **notifications** | 5 | **9** | **+4** | `/read-all` PUT, `/clear-old` DELETE, `/preferences` GET, `/preferences` PUT |
| paper_trading | 5 | 5 | 0 | sustained |
| **params** | 5 | **7** | **+2** | `/{key}/impact` GET, `/rollback` POST |
| **pipeline** | 5 | **10** | **+5** | `/trigger`, `/automation-level` GET, `/automation-level` PUT, `/pause`, `/resume` (all backfill closing pre-existing frontend orphans O2/O3/O8 — see §6.1) |
| **pms** | 4 | **0** | **−4** | **RETIRED iter 50 ADR-094** (`backend/app/api/pms.py` physically deleted commit `4d8ca04`) |
| portfolio | 3 | 3 | 0 | sustained |
| realtime | 2 | 2 | 0 | sustained |
| remote_status | 2 | 2 | 0 | sustained |
| **report** | 3 | **5** | **+2** | `/{strategy_id}/latest` GET, `/{strategy_id}/list` GET |
| risk | 10 | 10 | 0 | sustained |
| sse | 1 | 1 | 0 | sustained |
| strategies | 10 | 10 | 0 | sustained |
| **system** | 7 | **8** | **+1** | `/settings/paper-strategy-id` GET |
| **TOTAL** | **148** | **161** | **+13** | net adds: +17 / retires: −4 |

### §9.2 Frontend consumer inventory (FRESH)

**Total: 12 `*.ts` files** (vs 11 on 2026-05-20 — `client.ts` axios base config was always present but not counted as a "consumer module"; `reports.ts` is new in iter window 2026-05-20 → 2026-05-25 reflecting backend `report.py` +2 endpoints). Consumer modules: `agent / backtest / dashboard / execution / factors / mining / pipeline / realtime / reports / strategies / system` = 11 modules + `client.ts` base.

**Total axios/apiClient calls (fresh grep)**: **~90 calls** (vs 83 in §8 — +7, consistent with new `pipeline.ts` automation-level / pause / resume and new `reports.ts` consumers).

### §9.3 Drift sample table (5 cells)

> 5+ cells per acceptance. Mix of matched / backend-missing / frontend-missing / mismatch param.

| # | Endpoint | Backend | Frontend | State | Note |
|---|----------|---------|----------|-------|------|
| D1 | `POST /api/pipeline/pause` | pipeline.py:323 | pipeline.ts:138 (`pausePipeline`) | ✅ matched | iter 12 PN-003 closed O3 orphan (§6.1) |
| D2 | `POST /api/pipeline/trigger` | pipeline.py:168 | pipeline.ts:125 (`triggerPipeline`) | ✅ matched | iter 1 PN-001 closed O2 orphan |
| D3 | `GET /api/pipeline/{run_id}/logs` | pipeline.py:267 | pipeline.ts:180 (`getPipelineLogs`) | ✅ matched | O7 HTTP backfill closed 2026-05-28; PN-005 writer/WS enhancements remain |
| D4 | `DELETE /api/notifications/clear-old` | notifications.py:133 | — | ⚠️ backend has + frontend missing | new admin endpoint, no UI yet (candidate §5D) |
| D5 | `GET /api/system/settings/paper-strategy-id` | system.py:509 | system.ts:285 (`getPaperStrategyId`) | ✅ matched | iter 50+ new pair |
| D6 | `GET /api/system/streams` | system.py:334 | system.ts:195 (`fetchSystemStreams`) | ✅ matched | §24 closes the former ops viewer gap |
| D7 | `POST /api/factors/correlation-prune` | factors.py:1121 | factors.ts:207 | ✅ matched | iter 11 PN-002 closed O10 orphan |

### §9.4 Backtest +1 root-cause locator

Existing matrix §2.4 originally showed 16 numbered backtest rows, while fresh
grep returns 17 route decorators. Batch 21 re-verified the current route lines:
169, 243, 292, 364, 388, 457, 509, 596, 658, 727, 783, 838, 920, 1035,
1137, 1198, and 1296. The previously missing row is
`POST /api/backtest/{run_id}/cancel` (`backtest.py:243`), which matches
`cancelBacktest()` in `frontend/src/api/backtest.ts:281`. The historical O1
orphan text is corrected above; row 34 sensitivity remains present and deferred
by design.

### §9.5 Orphan status sustained from §6.1

- **O7** (`/pipeline/{runId}/logs`) — resolved 2026-05-28 at HTTP contract level; remaining PN-005 work is writer/WS/retention enhancement, not orphan closure.
- All other O1-O10 from 2026-05-20 snapshot closed iter 3-4 / 5 / 10 / 11 / 12 / 15.
- **No new orphans surfaced** in 2026-05-20 → 2026-05-25 window (all 13 new backend endpoints either have a frontend consumer or are admin-only by design).

### §9.6 Cite source (4-element)

- `backend/app/api/**/*.py` (verify 2026-05-25 16:50 SH) — 24 router files, 161 `@router.*` decorators (PowerShell Select-String count cross-checked).
- `frontend/src/api/*.ts` (verify 2026-05-25 16:50 SH) — 12 files (11 consumer + client.ts).
- `docs/API_COVERAGE.md` last git commit: `git log -1 docs/API_COVERAGE.md` → `4d8ca04 2026-05-24 23:36 +0800` (iter 50 PMS retire row 107-110 marking) — content body untouched since 2026-05-24, methodology §8 footer 5d stale vs fresh inventory.
- `backend/app/api/pms.py` (verify 2026-05-25 16:50 SH) — physically absent (RETIRED iter 50 ADR-094 commit 4d8ca04).

**Fresh verify 2026-05-25 16:50 SH (iter 96 sub2 — taskboard POC task_003)**: 161 backend / 12 frontend / 1 orphan sustained / 13 endpoint Δ enumerated above. 红线 5/5 sustained (LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / 0 持仓 / cash ¥993,520.66 / 0 trades since 2026-04-29). TIER C direct push, ≤ 200 lines new content (122 lines appended).

## §10 Fresh verify — 2026-05-28 (O7 HTTP backfill closure)

### §10.1 Backend route delta

`backend/app/api/pipeline.py` now implements `GET /api/pipeline/{run_id}/logs`
as a Redis-list HTTP backfill endpoint for the Operator UI "AI决策日志" tab.
The backend route surface is now **162 endpoints across 24 router files**.

### §10.2 Orphan status

The previous sustained frontend-only orphan O7 is closed at the HTTP contract
level: `frontend/src/api/pipeline.ts::getPipelineLogs()` now has a matching
backend endpoint.

Remaining PN-005 scope is explicitly narrower:
- writer instrumentation that pushes JSON `PipelineLogEntry` rows to
  `pipeline:logs:{run_id}`;
- optional `/ws/pipeline/{run_id}` live tailing;
- a retention decision if the project later needs durable DB-backed history.

These are enhancements/backlog, not current frontend-only API orphans.

## §11 Fresh verify — 2026-06-01 (notification panel API closure)

### §11.1 Frontend route consumer delta

`frontend/src/api/notifications.ts` adds the missing frontend API module for the
notification panel. The current frontend API module inventory is **13 files**:
the §9.2 list plus `notifications.ts`.

### §11.2 Notification endpoint status

| Endpoint | Backend | Frontend | State | Note |
|---|---|---|---|---|
| `GET /api/notifications` | notifications.py:74 | notifications.ts:113 + `NotificationProvider` | ✅ matched | Panel loads backend rows and uses response `unread_count` |
| `PUT /api/notifications/{notification_id}/read` | notifications.py:208 | notifications.ts:138 + row click handler | ✅ matched | Already-read rows are guarded client-side to avoid backend 404 reload |
| `PUT /api/notifications/read-all` | notifications.py:120 | notifications.ts:151 + header action | ✅ matched | Header action marks loaded rows read and updates unread badge |
| `GET /api/notifications/unread-count` | notifications.py:107 | — | ⚠️ intentionally unused | Redundant for current panel because list response includes `unread_count` |
| `GET /api/notifications/{notification_id}` | notifications.py:186 | notifications.ts:129 + `NotificationPanel` detail view | ✅ matched | No-link notification rows open the backend detail payload |
| `DELETE /api/notifications/clear-old` | notifications.py:133 | — | ⚠️ admin gap | No admin cleanup UI yet |
| `GET/PUT /api/notifications/preferences` | notifications.py:152 / 170 | — | ⚠️ settings gap | Existing system notification settings use `/api/system/test-notification` and `/api/params` |
| `POST /api/notifications/test` | notifications.py:230 | — | ⚠️ admin test gap | No direct frontend consumer |

### §11.3 Verification

- RED: `npx vitest --run src/__tests__/notifications-api-contract.test.ts src/__tests__/notifications-ui-contract.test.tsx` failed before the fix on missing `@/api/notifications`, zero backend fetch calls, seeded mock rows, and missing backend mark-all calls.
- Edge RED: `npx vitest --run src/__tests__/notifications-ui-contract.test.tsx -t "already-read"` failed before the guard because read rows still called `markNotificationRead()`.
- GREEN targeted notification contracts: 10 passed.
- Full frontend suite: `npx vitest --run` -> 100 passed.
- Frontend production build: `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning only.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7005 deselected.

### §11.4 Remaining notification backlog

- Add cleanup/preferences UI only if notification administration becomes an operator workflow. Until then, those endpoints remain backend/admin-only candidates rather than broken user-facing chains.

## §12 Fresh verify — 2026-06-01 (dashboard API-layer closure)

### §12.1 Finding

`frontend/src/pages/Dashboard/index.tsx` previously imported `apiClient`
directly for five secondary data reads:

| UI panel | Previous page-level call | Current wrapper |
|---|---|---|
| Alerts | `/dashboard/alerts` | `fetchAlerts()` |
| Monthly heatmap | `/dashboard/monthly-returns` | `fetchMonthlyReturns()` |
| Industry distribution | `/dashboard/industry-distribution` | `fetchIndustryDistribution()` |
| Factor library rows | `/factors` | `fetchDashboardFactorRows()` |
| AI pipeline steps | `/pipeline/status` | `fetchDashboardPipelineSteps()` |

Risk: the API matrix grep only counts `frontend/src/api/*.ts`, so page-level
calls hid real consumers and made the historical §3.4 “backend-only” dashboard
claim stale. The page also owned response-shape conversion that belongs in the
API layer per LL-035.

### §12.2 Closure

- Added the five wrappers in `frontend/src/api/dashboard.ts`.
- Centralized Dashboard row types in `frontend/src/types/dashboard.ts`.
- Updated `MonthlyHeatmap` to accept backend `null` months via
  `MonthlyReturns`.
- Removed the direct `apiClient` import and all `apiClient.*` calls from
  `Dashboard/index.tsx`.
- Added `frontend/src/__tests__/dashboard-api-contract.test.ts` to lock wrapper
  exports, endpoint params, factor-row normalization, pipeline-step
  normalization, and the Dashboard page boundary.

### §12.3 Verification

- RED: `npx vitest --run src/__tests__/dashboard-api-contract.test.ts` failed
  before the fix on missing wrapper exports and the direct `apiClient` import.
- GREEN targeted contract: `npx vitest --run src/__tests__/dashboard-api-contract.test.ts`
  -> 6 passed.
- Broader frontend/API suite:
  `npx vitest --run src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 20 passed.
- Full frontend suite: `npx vitest --run` -> 106 passed.
- Frontend build: `npm run build` -> exit 0 with the existing Vite vendor
  chunk-size warning only.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/dashboard`;
  heading `驾驶舱` was visible and console error list was empty.

### §12.4 Remaining API Governance Backlog

- `DashboardAstock.tsx` and `Portfolio.tsx` are closed in §13 for portfolio
  endpoint usage and sector-chart normalization.
- `PTGraduation.tsx`, `RiskManagement.tsx`,
  and a few shared widgets still import `apiClient`
  directly. They are candidates for follow-up API-layer contraction only when a
  code-backed page/API contract gap is confirmed.

## §13 Fresh verify — 2026-06-01 (portfolio API-layer closure)

### §13.1 Finding

`frontend/src/pages/Portfolio.tsx` and `frontend/src/pages/DashboardAstock.tsx`
previously imported `apiClient` directly for portfolio-side data:

| UI surface | Previous page-level call | Current wrapper |
|---|---|---|
| Portfolio sector chart | `/portfolio/sector-distribution` | `fetchPortfolioSectorDistribution()` |
| Portfolio daily PnL | `/portfolio/daily-pnl` | `fetchPortfolioDailyPnl()` |
| Portfolio holding-days map | `/portfolio/holdings` | `fetchHoldingDaysMap()` |
| A-share dashboard sector chart | `/portfolio/sector-distribution` | `fetchPortfolioSectorDistribution()` |

Risk: the backend `portfolio.py` route returns sector `pct` as percentage and
`value` as market value. Both frontend charts were using `value` as the
percentage label/data key, so the page-level contract could display market
value as a percent and also hid the `/api/portfolio/*` consumers from this
matrix.

### §13.2 Closure

- Added `frontend/src/api/portfolio.ts` with wrappers for sector distribution,
  daily PnL, holdings, and holding-days lookup.
- Normalized sector rows so chart-facing `value` equals `pct`, while
  `marketValue` preserves the backend value.
- Added deterministic colors for sector chart consumers.
- Removed direct `apiClient` imports and calls from `Portfolio.tsx` and
  `DashboardAstock.tsx`.
- Added `frontend/src/__tests__/portfolio-api-contract.test.ts` to lock wrapper
  params, sector normalization, holding-days mapping, and the two page
  boundaries.

### §13.3 Verification

- RED: `npx vitest --run src/__tests__/portfolio-api-contract.test.ts` failed
  before the fix because `@/api/portfolio` did not exist.
- GREEN targeted contract:
  `npx vitest --run src/__tests__/portfolio-api-contract.test.ts`
  -> 4 passed.
- Broader frontend/API suite:
  `npx vitest --run src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 24 passed.
- TypeScript: `npx tsc -b --pretty false` -> exit 0.
- Full frontend suite: `npx vitest --run` -> 110 passed.
- Frontend build: `npm run build` -> exit 0 with the existing Vite vendor
  chunk-size warning only.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/portfolio`
  and `http://127.0.0.1:5173/dashboard/astock`; headings `持仓管理` and
  `A股详情` were visible and console error lists were empty.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

### §13.4 Remaining API Governance Backlog

- Remaining direct page/component imports after this batch: `PTGraduation.tsx`,
  `RiskManagement.tsx`, `ReportCenter.tsx`, `SafetyControlPanel.tsx`,
  and `QMTStatusBadge.tsx`.
- The next contraction should be selected only after confirming a response
  conversion bug, coverage-matrix blind spot, or broken user workflow from
  current code.

## §14 Fresh verify — 2026-06-01 (market API-layer closure)

### §14.1 Finding

`frontend/src/pages/MarketData.tsx` previously consumed the three implemented
market routes directly from the page:

| UI surface | Previous page-level call | Current wrapper |
|---|---|---|
| Main index cards | `/market/indices` | `fetchMarketIndices()` |
| Sector heatmap | `/market/sectors` | `fetchMarketSectors()` |
| Top gainers / losers | `/market/top-movers?direction=...&limit=5` | `fetchMarketTopMovers(direction, limit)` |

Risk: this matrix marked rows 75–77 as unconsumed even though the page used
them inline. That hid real frontend usage from the `frontend/src/api/*.ts`
coverage methodology and left route params spread across UI code.

Fresh evidence:
- `frontend/src/pages/MarketData.tsx:61` / §MarketData queries — wrapper query
  functions in use after fix; fresh verify 2026-06-01 14:51 +08.
- `frontend/src/api/market.ts:33-47` / §Market wrappers — three `/market/*`
  routes covered by typed API functions; fresh verify 2026-06-01 14:51 +08.

### §14.2 Closure

- Added `frontend/src/api/market.ts` with typed wrappers for indices, sectors,
  and top movers.
- Removed direct `apiClient` import and direct `/market/*` calls from
  `MarketData.tsx`.
- Added `frontend/src/__tests__/market-api-contract.test.ts` to lock wrapper
  endpoints, top-mover params, and the page boundary.
- Updated rows 75–77 in this matrix and removed `/api/market/*` from §5D.

### §14.3 Verification

- RED: `npx vitest --run src/__tests__/market-api-contract.test.ts` failed
  before the fix because `src/api/market.ts` did not exist and `MarketData.tsx`
  imported `apiClient` directly.
- GREEN targeted contract:
  `npx vitest --run src/__tests__/market-api-contract.test.ts`
  -> 3 passed.
- Broader frontend/API suite:
  `npx vitest --run src/__tests__/market-api-contract.test.ts src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 27 passed.
- TypeScript: `npx tsc -b --pretty false` -> exit 0.
- Full frontend suite: `npx vitest --run` -> 113 passed.
- Frontend build: `npm run build` -> exit 0 with the existing Vite vendor
  chunk-size warning only.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/market`;
  heading `行情数据` and tab `行情概览` were visible, and console error list was
  empty.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

### §14.4 Remaining API Governance Backlog

- Remaining direct page/component imports after this batch: `PTGraduation.tsx`,
  `RiskManagement.tsx`, `ReportCenter.tsx`, `SafetyControlPanel.tsx`, and
  `QMTStatusBadge.tsx`.
- Continue selecting the next contraction only from current code evidence:
  response conversion bug, coverage-matrix blind spot, or broken user workflow.

## §15 Fresh verify — 2026-06-01 (report center API-layer closure)

### §15.1 Finding

`frontend/src/pages/ReportCenter.tsx` previously consumed two implemented
report routes directly from the page while `docs/API_COVERAGE.md` rows 118–120
still marked report endpoints as unwired:

| UI surface | Previous page-level call | Current wrapper |
|---|---|---|
| Report history tab | `/reports/list` | `listReportHistory()` |
| Quick stats tab | `/reports/quick-stats` | `fetchReportQuickStats()` |
| Generate report button | already wrapped | `generateReport()` |

Risk: real report-page usage was hidden from the `frontend/src/api/*.ts`
coverage methodology. `frontend/src/api/reports.ts` also carried an explicit
comment saying the legacy list endpoint was intentionally inline, preserving
the stale boundary.

Active discovery at resume:
- `memory/project_sprint_state.md` / §Current Handoff said Batch 13 still needed
  commit/push/CI, but fresh `git log` + PR #523 state showed head `0e628bc0`
  clean with all checks passing. Batch 14 handoff now corrects that drift.

Fresh evidence:
- `frontend/src/api/reports.ts:142-150` / §Report wrappers — history and quick
  stats wrappers in place; fresh verify 2026-06-01 15:08 +08.
- `frontend/src/pages/ReportCenter.tsx:64-70` / §ReportCenter queries —
  page now calls wrappers; fresh verify 2026-06-01 15:08 +08.

### §15.2 Closure

- Added `listReportHistory()` and `fetchReportQuickStats()` to
  `frontend/src/api/reports.ts`.
- Exported typed report history / quick-stats contracts from the API layer.
- Removed direct `apiClient` import and `/reports/*` calls from
  `ReportCenter.tsx`.
- Added `frontend/src/__tests__/report-center-api-contract.test.ts` to lock
  endpoint params and the page boundary.
- Updated rows 118–120 and removed `/api/reports/*` from §5D.

### §15.3 Verification

- RED: `npx vitest --run src/__tests__/report-center-api-contract.test.ts`
  failed before the fix because the wrappers were missing and `ReportCenter.tsx`
  imported `apiClient` directly.
- GREEN targeted contract:
  `npx vitest --run src/__tests__/report-center-api-contract.test.ts`
  -> 3 passed.
- Focused compatibility suite:
  `npx vitest --run src/__tests__/report-center-api-contract.test.ts src/__tests__/reports-api.test.ts src/__tests__/pages.test.tsx`
  -> 19 passed.
- Broader frontend/API pack:
  `npx vitest --run src/__tests__/report-center-api-contract.test.ts src/__tests__/reports-api.test.ts src/__tests__/market-api-contract.test.ts src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 38 passed.
- TypeScript/build:
  `npx tsc -b --pretty false` -> exit 0;
  `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- Full frontend suite: `npx vitest --run` -> 116 tests passed across 22 files.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/reports`;
  heading `报告中心` and tab text `报告列表` were visible; console errors were
  empty. Existing dev server on port 5173 was reused and not stopped.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.
- Governance guards: V3 banned-word diff scan -> no new hits;
  `git diff --check` -> exit 0 with Git line-ending warnings only.

### §15.4 Remaining API Governance Backlog

- Remaining direct page/component imports after this batch: `PTGraduation.tsx`,
  `SafetyControlPanel.tsx`, and `QMTStatusBadge.tsx`.
- Continue selecting the next contraction only from current code evidence:
  response conversion bug, coverage-matrix blind spot, or broken user workflow.

## §16 Fresh verify — 2026-06-01 (risk management API-layer closure)

### §16.1 Finding

`frontend/src/pages/RiskManagement.tsx` previously consumed implemented risk
routes directly from the page, while rows 121–129 in this matrix still marked
most `/api/risk/*` endpoints as unwired.

| UI surface | Previous page-level call | Current wrapper |
|---|---|---|
| Status history tab | `/risk/history/{strategy_id}` | `fetchRiskHistory()` |
| Status summary card | `/risk/summary/{strategy_id}` | `fetchRiskSummary()` |
| Overview metric cards | `/risk/overview` | `fetchRiskOverviewDisplay()` |
| Limit monitor tab | `/risk/limits` | `fetchRiskLimits()` |
| Stress-test tab | `/risk/stress-tests` | `fetchStressTests()` |
| Header circuit badge | already wrapped | `fetchCircuitBreakerState()` |

Risk: the backend returns raw scalar overview fields, limit statuses
`normal/warning/danger`, and stress-test fields such as `estimated_loss` and
`period`. The page expected display metrics, `ok/warn/critical`, and
`impact/probability/recovery`, so direct page calls could silently show empty
overview cards and miscount risk-limit severity.

Fresh evidence:
- `frontend/src/api/risk.ts:225` / §Risk wrappers — history wrapper in place;
  fresh verify 2026-06-01 15:30 +08.
- `frontend/src/api/risk.ts:252-277` / §Risk display wrappers — overview,
  limits, and stress-test normalization in the API layer; fresh verify
  2026-06-01 15:30 +08.
- `frontend/src/pages/RiskManagement.tsx:179` / §RiskStatusHistoryPanel —
  page now calls `fetchRiskHistory`; fresh verify 2026-06-01 15:30 +08.
- `frontend/src/pages/RiskManagement.tsx:384-400` / §Risk overview loader —
  page now calls risk API wrappers for live/paper fallback; fresh verify
  2026-06-01 15:30 +08.

### §16.2 Closure

- Added risk history, summary, overview, limit, and stress-test wrappers to
  `frontend/src/api/risk.ts`.
- Normalized backend overview scalars into the six metric cards the page
  renders.
- Normalized risk-limit status and percentage display in the API layer.
- Normalized stress-test rows for the existing stress-test cards without
  inventing missing time series or exposure data.
- Kept empty `data_days <= 0` overview responses as empty metric sets so the
  page still falls back from live to paper data.
- Removed direct `apiClient` import and all direct `/risk/*` GET calls from
  `RiskManagement.tsx`.
- Added `frontend/src/__tests__/risk-management-api-contract.test.ts` to lock
  wrapper endpoints, response normalization, and the page boundary.
- Updated rows 121–129 and narrowed the §5D risk backlog to L4 admin mutations
  before the follow-up admin-flow closure in §17.

### §16.3 Verification

- RED: `npx vitest --run src/__tests__/risk-management-api-contract.test.ts`
  failed before the fix on missing wrapper exports and the direct page
  `apiClient` import.
- GREEN targeted contract:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts`
  -> 7 passed.
- Focused frontend/API pack:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts src/__tests__/report-center-api-contract.test.ts src/__tests__/market-api-contract.test.ts src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 37 passed.
- TypeScript/build:
  `npx tsc -b --pretty false` -> exit 0;
  `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- Full frontend suite: `npx vitest --run` -> 123 tests passed across 23 files.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/risk`; heading
  `风控管理`, tab `风控总览`, and tab `限额监控` each resolved once; console error
  list was empty. Existing dev server on port 5173 was reused and not stopped.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

### §16.4 Remaining API Governance Backlog

- Superseded by §17 for `SafetyControlPanel` rows 124–125.
- Continue selecting the next contraction only from current code evidence:
  response conversion bug, coverage-matrix blind spot, or broken user workflow.

## §17 Fresh verify — 2026-06-01 (SafetyControlPanel L4 API-layer closure)

### §17.1 Finding

`frontend/src/components/safety/SafetyControlPanel.tsx` directly posted L4
recovery and approval mutations from the component while this matrix still
marked rows 124–125 as unwired. That left the most privileged risk UI path
outside the `frontend/src/api/risk.ts` wrapper boundary used by the rest of the
risk surface.

| UI surface | Previous component-level call | Current wrapper |
|---|---|---|
| L4 recovery request | `/risk/l4-recovery/{strategy_id}` | `requestL4Recovery()` |
| L4 approve/reject | `/risk/l4-approve/{approval_id}` | `approveL4Recovery()` |

Fresh evidence:
- `backend/app/api/risk.py:206` / §L4 recovery endpoint — POST
  `/l4-recovery/{strategy_id}` requires admin token and accepts
  `reviewer_note`; fresh verify 2026-06-01 15:47 +08.
- `backend/app/api/risk.py:239` / §L4 approve endpoint — POST
  `/l4-approve/{approval_id}` requires admin token and accepts `approved` plus
  `reviewer_note`; fresh verify 2026-06-01 15:47 +08.
- `frontend/src/api/risk.ts:200` and `frontend/src/api/risk.ts:213` /
  §Risk wrappers — L4 mutation wrappers now own both HTTP calls; fresh verify
  2026-06-01 15:47 +08.
- `frontend/src/components/safety/SafetyControlPanel.tsx:151` and
  `frontend/src/components/safety/SafetyControlPanel.tsx:182` /
  §Safety panel handlers — component now calls wrappers and no longer imports
  `apiClient`; fresh verify 2026-06-01 15:47 +08.

### §17.2 Closure

- Added typed `L4RecoveryResponse`, `L4RecoveryState`, and `L4ApproveResponse`
  contracts to `frontend/src/api/risk.ts`.
- Added `requestL4Recovery()` and `approveL4Recovery()` wrappers.
- Refactored `SafetyControlPanel.tsx` to consume the wrappers while preserving
  existing modal behavior and success/error handling.
- Extended `frontend/src/__tests__/risk-management-api-contract.test.ts` to
  lock the two L4 endpoint calls and the component boundary.
- Updated `frontend/src/__tests__/SafetyControlPanel.test.tsx` mocks so the
  existing L4 flow tests continue to exercise the UI flow through wrappers.
- Updated rows 124–125 to covered and removed the L4 row from §5D.

### §17.3 Verification

- RED:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts`
  failed before the fix on missing `requestL4Recovery` /
  `approveL4Recovery` exports and the direct `SafetyControlPanel` `apiClient`
  import.
- GREEN targeted contract/UI:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts src/__tests__/SafetyControlPanel.test.tsx`
  -> 17 passed.
- Focused frontend/API pack:
  `npx vitest --run src/__tests__/risk-management-api-contract.test.ts src/__tests__/SafetyControlPanel.test.tsx src/__tests__/report-center-api-contract.test.ts src/__tests__/market-api-contract.test.ts src/__tests__/portfolio-api-contract.test.ts src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 47 passed.
- TypeScript/build:
  `npx tsc -b --pretty false` -> exit 0;
  `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- Full frontend suite: `npx vitest --run` -> 126 tests passed across 23 files.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened `http://127.0.0.1:5173/risk`, clicked
  `紧急控制`, and the DOM contained `熔断状态`, `紧急操作`, and `ENV: paper`;
  console error list was empty. Existing dev server on port 5173 was reused and
  not stopped.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

### §17.4 Remaining API Governance Backlog

- Remaining direct page/component imports after this batch: `PTGraduation.tsx`
  and `QMTStatusBadge.tsx`.
- Keep `/api/risk/dingtalk-webhook` classified as webhook/ops, not a frontend
  wrapper target unless a UI workflow is added.
- Continue choosing the next closure from current code evidence rather than
  historical matrix drift alone.

## §18 Fresh verify — 2026-06-01 (QMTStatusBadge health API-layer closure)

### §18.1 Finding

`frontend/src/components/shared/QMTStatusBadge.tsx` directly called
`/health/qmt`, while row 74 in this matrix still classified the endpoint as
backend-only monitoring. Fresh grep also showed the badge is exported from the
shared component barrel but not mounted by current routes, so this is a
low-blast-radius wrapper-boundary cleanup rather than an active visible page
bug.

Fresh evidence:
- `backend/app/api/health.py:78` / §QMT health endpoint — POST-free GET
  `/qmt` returns `qmt_manager.health_check()`; fresh verify 2026-06-01
  16:00 +08.
- `backend/app/services/qmt_connection_manager.py:142` / §health_check —
  response includes `execution_mode`, `state`, `account_id`, `connected_at`,
  `last_error`, and `is_healthy`; fresh verify 2026-06-01 16:00 +08.
- `frontend/src/api/system.ts:184` / §System wrappers — `fetchQmtHealth()`
  now owns the `/health/qmt` call; fresh verify 2026-06-01 16:00 +08.
- `frontend/src/components/shared/QMTStatusBadge.tsx:16` / §Badge query —
  badge now uses `fetchQmtHealth`; fresh verify 2026-06-01 16:00 +08.

### §18.2 Closure

- Added `QmtAccountAsset` and `QmtHealth` types to
  `frontend/src/api/system.ts`.
- Added `fetchQmtHealth()` as the typed `/health/qmt` wrapper.
- Refactored `QMTStatusBadge.tsx` to consume `fetchQmtHealth` and remove direct
  `apiClient` usage.
- Added `frontend/src/__tests__/health-api-contract.test.ts` to lock the
  wrapper endpoint and component boundary.
- Updated row 74 and clarified §5A so `/health/qmt` is no longer counted as
  pure backend-only monitoring.

### §18.3 Verification

- RED:
  `npx vitest --run src/__tests__/health-api-contract.test.ts` first failed on
  the missing `fetchQmtHealth` export and direct `QMTStatusBadge` `apiClient`
  import after tightening the test to the existing `system.ts` API module.
- GREEN targeted contract:
  `npx vitest --run src/__tests__/health-api-contract.test.ts` -> 2 passed.
- Focused frontend/API pack:
  `npx vitest --run src/__tests__/health-api-contract.test.ts src/__tests__/system-api-scheduler.test.ts src/__tests__/system-api-paper-sid.test.ts src/__tests__/risk-management-api-contract.test.ts src/__tests__/SafetyControlPanel.test.tsx src/__tests__/dashboard-api-contract.test.ts src/__tests__/pages.test.tsx src/__tests__/api.test.ts`
  -> 44 passed.
- TypeScript/build:
  `npx tsc -b --pretty false` -> exit 0;
  `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- Full frontend suite: `npx vitest --run` -> 128 tests passed across 24 files.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

### §18.4 Remaining API Governance Backlog

- Superseded by §19: `PTGraduation.tsx` direct API usage is closed.
- Since `QMTStatusBadge` is not mounted by current routes, browser smoke should
  remain an app-load smoke unless a route starts rendering the badge.

## §19 Fresh verify — 2026-06-01 (PTGraduation paper-trading API-layer closure)

### §19.1 Finding

`frontend/src/pages/PTGraduation.tsx` directly called
`/paper-trading/graduation-status`, while rows 94-96 in this matrix still
classified the paper-trading page data as backend-only. Fresh code review showed
`/paper-trading/trades` and the `/paper-trading/positions` fallback were already
owned by `frontend/src/api/dashboard.ts`; the remaining page bypass was the
graduation-status request.

Fresh evidence:
- `backend/app/api/paper_trading.py:101` / §paper_trading router — GET
  `/graduation-status`; fresh verify 2026-06-01 16:14 +08.
- `backend/app/api/paper_trading.py:224` and `:243` / §paper_trading router —
  GET `/positions` and GET `/trades`; fresh verify 2026-06-01 16:14 +08.
- `frontend/src/api/dashboard.ts:67`, `:99`, and `:109` / §Dashboard API
  wrappers — paper trades, graduation status, and positions wrappers; fresh
  verify 2026-06-01 16:14 +08.
- `frontend/src/pages/PTGraduation.tsx:264` / §PTGraduation effect — page now
  calls `fetchPaperGraduationStatus("live")`; fresh verify 2026-06-01
  16:14 +08.

### §19.2 Closure

- Added `PaperGraduationCriterion`, `PaperGraduationStatus`, and
  `fetchPaperGraduationStatus()` to `frontend/src/api/dashboard.ts`.
- Removed direct `apiClient` usage from `PTGraduation.tsx`.
- Added `frontend/src/__tests__/pt-graduation-api-contract.test.ts` to lock the
  wrapper endpoint and page boundary.
- Updated rows 94-96 and narrowed §5D to the two unwrapped legacy PT endpoints:
  `/api/paper-trading/status` and `/api/paper-trading/graduation`.

### §19.3 Verification

- RED: `npx vitest --run src/__tests__/pt-graduation-api-contract.test.ts`
  first failed because `fetchPaperGraduationStatus()` was missing and
  `PTGraduation.tsx` imported `apiClient` directly.
- GREEN targeted contract + trade panel:
  `npx vitest --run src/__tests__/pt-graduation-api-contract.test.ts src/__tests__/TradeLogPanel.test.tsx`
  -> 5 passed.
- Focused frontend/API pack:
  `npx vitest --run src/__tests__/pt-graduation-api-contract.test.ts src/__tests__/TradeLogPanel.test.tsx src/__tests__/dashboard-api-contract.test.ts src/__tests__/health-api-contract.test.ts src/__tests__/risk-management-api-contract.test.ts`
  -> 23 passed.
- TypeScript/build:
  `npx tsc -b --pretty false` -> exit 0;
  `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- Full frontend suite: `npx vitest --run` -> 130 tests passed across 25 files.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS, and production page/component grep for direct `apiClient` imports
  returned no matches.
- Browser smoke: in-app browser opened
  `http://127.0.0.1:5173/pt-graduation`; `PT 毕业评估` was visible with backend
  data loaded and console errors empty.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

### §19.4 Remaining API Governance Backlog

- Direct `apiClient` imports in production pages/components: none found by the
  current audit scan.
- Rows 92-93 remain as a low-risk paper-trading API backlog until a current
  frontend workflow needs the legacy status/criteria endpoints.

## §20 Fresh verify — 2026-06-01 (ApprovalQueue API coverage drift closure)

### §20.1 Finding

Rows 12-16 still classified approval detail, approve, reject, hold, and history
as unwired, and §5D still described the approval workflow as incomplete. Fresh
code review showed this was documentation drift: `frontend/src/api/approval.ts`
already wraps all six approval endpoints, `ApprovalQueue.tsx` is mounted at
`/approval-queue`, and the sidebar exposes it as `因子审批`.

Fresh evidence:
- `backend/app/api/approval.py:205`, `:234`, `:259`, `:290`, `:321`, and
  `:353` / §approval router — queue list, detail, approve, reject, hold, and
  history endpoints; fresh verify 2026-06-01 16:21 +08.
- `frontend/src/api/approval.ts:84`, `:92`, `:98`, `:110`, `:122`, and `:134`
  / §Approval API wrappers — all six endpoint wrappers; fresh verify
  2026-06-01 16:21 +08.
- `frontend/src/pages/ApprovalQueue.tsx:279`, `:450`, `:601`, `:607`, `:619`,
  and `:631` / §ApprovalQueue page — pending, history, detail, approve, reject,
  and hold consumers; fresh verify 2026-06-01 16:21 +08.
- `frontend/src/router.tsx:82` and `frontend/src/components/layout/Sidebar.tsx:82`
  / §Route + nav — `/approval-queue` mounted and reachable; fresh verify
  2026-06-01 16:21 +08.

### §20.2 Closure

- Added `frontend/src/__tests__/approval-api-contract.test.ts` to lock the
  endpoint mapping for queue reads and admin actions.
- Updated rows 12-16 to covered.
- Removed the stale approval workflow row from §5D.
- No production behavior changed; this batch reduces audit noise and preserves
  the existing ApprovalQueue implementation.

### §20.3 Verification

- Characterization contract + page guard:
  `npx vitest --run src/__tests__/approval-api-contract.test.ts src/__tests__/ApprovalQueue.test.tsx`
  -> 9 passed.
- TypeScript/build:
  `npx tsc -b --pretty false` -> exit 0;
  `npm run build` -> exit 0 with the existing Vite vendor chunk-size warning.
- Full frontend suite: `npx vitest --run` -> 132 tests passed across 26 files.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened
  `http://127.0.0.1:5173/approval-queue`; `因子审批队列`, `待审批`, and `历史`
  were visible, the page returned the empty-state view, and console errors were
  empty. No approval actions were clicked.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

### §20.4 Remaining API Governance Backlog

- Approval queue is no longer part of §5D.
- Admin action browser smoke should not click approve/reject/hold without a
  separately scoped operator test fixture and explicit non-production target.

## §21 Fresh verify — 2026-06-01 (BacktestCompare S5 trade diff closure)

### §21.1 Finding

MVP 5.3 promised a lazy S5 trade-diff section for BacktestCompare, and the page
header still claimed lazy `/backtest/{run_id}/trades` usage, but fresh code
review showed the page only rendered S1-S4. The coverage matrix also still
classified both row 24 `/nav` and row 25 `/trades` as unwired even though NAV
was already wrapped and consumed. Runtime browser verification then found a
second API-contract gap: `/api/backtest/compare` returns Decimal fields as
strings, while `MetricRow` assumed the API layer returned numbers.

Fresh evidence:
- `docs/mvp/MVP_5_3_backtest_compare.md:36` and `:74` / §MVP 5.3 design —
  S5 trade diff was in scope; fresh verify 2026-06-01 16:31 +08.
- `backend/app/api/backtest.py:429`, `:469`, and `:1081` / §backtest router —
  NAV, trades, and compare endpoints; fresh verify 2026-06-01 16:38 +08.
- `frontend/src/api/backtest.ts:340`, `:355`, `:419`, and `:427` /
  §Backtest API wrappers — compare numeric normalization, `getNavSeries()`,
  and `getBacktestTrades()`; fresh verify 2026-06-01 16:38 +08.
- `frontend/src/pages/BacktestCompare.tsx:334`, `:339`, `:355`, and `:645` /
  §BacktestCompare S5 — lazy trade section, query, heading, and render site;
  fresh verify 2026-06-01 16:38 +08.

### §21.2 Closure

- Added `BacktestTradeRow`, `BacktestTradesResponse`, `BacktestTradesParams`,
  and `getBacktestTrades()` to `frontend/src/api/backtest.ts`.
- Added `TradeListDiff` to `BacktestCompare.tsx`. It is collapsed by default
  and fetches each run's first trade page only after the operator expands S5.
- Added a per-run trade table and first-page signed-share difference summary.
- Normalized compare metric fields in `compareBacktests()` so Decimal strings
  are converted before `BacktestCompare.tsx` renders metric cells.
- Added `frontend/src/__tests__/backtest-compare-trade-contract.test.ts`.
- Updated rows 24-25 and narrowed §5D to the remaining deep-dive backtest
  endpoints.

### §21.3 Verification

- RED:
  `npx vitest --run src/__tests__/backtest-compare-trade-contract.test.ts`
  first failed because `getBacktestTrades()` was missing and `BacktestCompare`
  did not contain `TradeListDiff`.
- GREEN targeted:
  `npx vitest --run src/__tests__/backtest-compare-trade-contract.test.ts`
  -> 3 passed after adding trade wrapper + Decimal-string normalization.
- TypeScript: `npx tsc -b --pretty false` first caught a nullable aggregate
  index in `buildTradeDiffRows`; after the fix, it exited 0.
- Full frontend suite: `npx vitest --run` -> 135 tests passed across 27 files.
- TypeScript/build: `npm run build` -> exit 0 with the existing Vite
  vendor-echarts chunk-size warning.
- API discipline guard: `python scripts/audit/check_frontend_api_discipline.py`
  -> PASS.
- Browser smoke: in-app browser opened
  `http://127.0.0.1:5173/backtest/compare?runs=2c91bd92-ee0f-4f52-9244-795365cc1037,3d7ecc84-0536-4d26-ac07-3eca4d53bdc4`,
  verified S5 collapsed, expanded it, saw per-run `无交易记录` state from the
  lazy trades endpoint, and fresh console errors were empty.
- Backend smoke: `pytest -m "smoke and not live_tushare"` -> 90 passed, 2
  skipped, 7013 deselected.

### §21.4 Remaining API Governance Backlog

- Backtest rows 26-32 and 35 are now consumed by BacktestResults (§23).
  Row 34 `/api/backtest/{run_id}/sensitivity` remains deferred/backlog.

## §22 Fresh verify — 2026-06-01 (Backtest detail endpoint schema/runtime hardening)

### §22.1 Finding

Batch 20's browser smoke exposed an adjacent backend runtime gap: several
backtest detail endpoints were marked as backend-implemented in rows 26-32 and
35, but their SQL no longer matched the actual DDL and writer contract. The
visible symptom was an empty BacktestCompare chart path plus server-side 500s
when detail endpoints queried columns that do not exist in the committed schema.

Fresh evidence:
- `docs/QUANTMIND_V2_DDL_FINAL.sql:599-640` / §backtest DDL — `backtest_daily_nav`
  has `benchmark_nav` but no `benchmark_return`; `backtest_trades` has
  `trade_id` but no `id`; `backtest_holdings` has `shares`, `cost_basis`, and
  `market_price` but no stored `market_value` or `pnl`; fresh verify
  2026-06-01 16:56 +08.
- `backend/app/tasks/backtest_tasks.py:579-605` / §backtest result writer —
  writer inserts trades without `target_price`/`transfer_fee` and NAV rows with
  `benchmark_nav`, not `benchmark_return`; fresh verify 2026-06-01 16:56 +08.
- `backend/app/api/backtest.py:122`, `:458`, `:570`, `:623`, `:921`,
  `:1036`, and `:1297` / §backtest router — patched runtime contract points;
  fresh verify 2026-06-01 16:56 +08.

### §22.2 Closure

- Narrowed `_safe_query()` so only missing relation errors return an empty list;
  undefined-column schema drift now fails loud instead of being reported as no
  data.
- Derived `benchmark_return` from `benchmark_nav` with `LAG(benchmark_nav)` for
  NAV/report paths.
- Updated trades SQL to select `trade_id AS id` and use `CAST(NULL AS NUMERIC)`
  placeholders for fields not stored by the writer.
- Derived holdings `market_value` and `pnl` from actual holdings columns.
- Normalized Decimal/date/UUID values before detail responses leave
  `backend/app/api/backtest.py`.
- Updated the frontend trade-row type to accept UUID string IDs returned by the
  backend.
- Added `backend/tests/test_backtest_detail_endpoint_contract.py` covering
  fail-loud schema errors, JSON-friendly conversion, DDL-aligned SQL guards,
  trades UUID IDs, cost-sensitivity Decimal arithmetic, and live-compare metric
  conversion.

### §22.3 Verification

- RED:
  `pytest backend/tests/test_backtest_detail_endpoint_contract.py -q` first
  failed on the new guards because trades SQL still used `NULL::numeric`, direct
  endpoint-call defaults needed explicit query args, and the cost-sensitivity
  assertion targeted the non-baseline row.
- GREEN targeted:
  `pytest backend/tests/test_backtest_detail_endpoint_contract.py -q` -> 7
  passed.
- Existing backtest/A6 compatibility:
  `pytest backend/tests/test_a4_a6.py::TestA6BacktestNavEndpoint backend/tests/test_backtest_api.py -q`
  -> 33 passed.
- Backend lint/compile:
  `ruff check backend/app/api/backtest.py backend/tests/test_backtest_detail_endpoint_contract.py`
  -> PASS; `python -m py_compile backend/app/api/backtest.py` -> PASS.
- Frontend compatibility:
  `npx vitest --run src/__tests__/backtest-compare-trade-contract.test.ts` ->
  3 passed; `npx tsc -b --pretty false` -> exit 0; frontend API discipline
  guard -> PASS.
- Real DB read-only runtime check against run
  `2c91bd92-ee0f-4f52-9244-795365cc1037`: direct calls to nav, trades,
  holdings summary, annual, monthly, attribution, market-state,
  cost-sensitivity, live-compare, and report all returned without runtime
  errors; the generated report temp file was removed after verification.

### §22.4 Remaining API Governance Backlog

- Rows 26-32 and 35 were backend-runtime-hardened here and are now
  frontend-wired in §23 through `frontend/src/api/backtest.ts` wrappers and
  `BacktestResults.tsx`.
- Row 34 `/api/backtest/{run_id}/sensitivity` remains deferred/backlog by
  design.

### §22.5 Aggregate Count Drift Surfaced

While correcting the backtest cancel row, Batch 21 re-ran the raw route/module
counts. This supersedes the older §10 headline count but does not replace the
row-level matrix audit, which remains future work for non-backtest domains.

- Backend raw grep:
  `rg -n "@router\\.(get|post|put|delete|patch)\\(" backend/app/api -g "*.py"`
  -> 170 route decorators across 25 router files.
- Per-router counts:
  agent 10, approval 6, attribution 2, auth 3, backtest 17, dashboard 8,
  execution 3, execution_ops 17, factors 11, health 3, market 3, mining 5,
  news 4, notifications 9, paper_trading 5, params 7, pipeline 12,
  portfolio 3, realtime 2, remote_status 2, report 5, risk 12, sse 1,
  strategies 10, system 10.
- Frontend API modules:
  18 `frontend/src/api/*.ts` files: agent, approval, attribution, backtest,
  client, dashboard, execution, factors, market, mining, notifications,
  pipeline, portfolio, realtime, reports, risk, strategies, system.

Backlog: run a dedicated API coverage refresh to update every non-backtest
row-level mapping and stale count paragraph rather than silently editing only
the headline numbers.

## §23 Fresh verify — 2026-06-01 (BacktestResults deep-dive wiring)

### §23.1 Finding

After §22 hardened the backtest detail endpoints, rows 26-32 and 35 still had a
frontend integration gap: `BacktestResults.tsx` read only sparse
`/backtest/{run_id}/result` data, while the dedicated detail endpoints for
holdings, annual/monthly slices, Brinson attribution, market-state,
cost-sensitivity, report download, and live-compare were left unused.

Fresh evidence:
- `frontend/src/pages/BacktestResults.tsx:860`, `:884`, and `:1010-1013` /
  §BacktestResults queries and tabs — page now calls the detail wrappers and
  renders attribution/cost/market/live tabs; fresh verify 2026-06-01 17:18 +08.
- `frontend/src/api/backtest.ts:541`, `:553`, `:567`, `:591`, `:636`, `:650`,
  `:660`, `:682`, `:707`, `:742`, and `:759` / §Backtest detail wrappers —
  monthly, holdings, annual risk, attribution, cost, market-state,
  live-compare, and report URL are normalized in the API layer; fresh verify
  2026-06-01 17:18 +08.
- `frontend/src/__tests__/backtest-results-detail-contract.test.ts` and
  `frontend/src/__tests__/backtest-results-page-render.test.tsx` /
  §frontend contracts — wrappers and rendered tabs are locked by tests; fresh
  verify 2026-06-01 17:18 +08.

### §23.2 Closure

- Added typed backtest detail wrappers in `frontend/src/api/backtest.ts`.
- Updated `BacktestResults.tsx` so `/result` remains the summary source while
  monthly returns, latest holdings, trades, annual risk metrics, attribution,
  cost sensitivity, market-state, and live-compare load from dedicated detail
  endpoints.
- Added tabs for industry attribution, cost sensitivity, market-state, and
  live-compare, and changed report export to use `/backtest/{run_id}/report`.
- Updated the coverage matrix rows 26-32 and 35 to consumed.
- Kept row 34 `/api/backtest/{run_id}/sensitivity` in backlog; the existing
  backend endpoint remains intentionally deferred from the deep-dive page.

### §23.3 Verification

- RED:
  `npx vitest --run src/__tests__/backtest-results-detail-contract.test.ts`
  first failed because the wrappers and page wiring were absent.
- GREEN targeted:
  `npx vitest --run src/__tests__/backtest-results-page-render.test.tsx src/__tests__/backtest-results-detail-contract.test.ts`
  -> 7 passed.
- Frontend regression:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 142 passed;
  `npm run build` -> exit 0 with the existing Vite vendor-echarts chunk-size
  warning.
- Backend compatibility:
  `pytest backend/tests/test_backtest_detail_endpoint_contract.py -q` -> 7
  passed.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected; `bash config/hooks/pre-push` -> X10 clean, LLM import guard
  clean, smoke 91 passed, 2 skipped, 6976 deselected.
- Runtime proof against current source:
  temporary uvicorn on `127.0.0.1:8011` served run
  `2c91bd92-ee0f-4f52-9244-795365cc1037`; monthly=4, holdings_summary=0,
  holdings_detail=0, annual=1, attribution_industries=0, market_states=0,
  cost_rows=4, live_compare_has_backtest=true. The temporary process was
  stopped after verification.

### §23.4 Runtime Ops Note

The existing Servy FastAPI listener on `127.0.0.1:8000` still emitted old SQL
errors during verification (`AVG(pnl)`, `benchmark_return`, and Decimal/float
cost arithmetic), which indicates the service process had not loaded the §22
backend changes yet. This batch did not restart Servy. Ops backlog: reload the
FastAPI service in a separate runtime step, then re-run the same detail endpoint
probe against port 8000 before declaring deployed runtime parity.

## §24 Fresh verify — 2026-06-01 (System Redis Streams viewer)

### §24.1 Finding

Row 144 `GET /api/system/streams` was backend-implemented but frontend-unwired.
The health page already exposed service and resource status, but Redis Streams
state required an external query path.

Fresh evidence:
- `backend/app/api/system.py:567` / §system streams endpoint — the route returns
  `{"streams": bus.all_streams_status()}`; fresh verify 2026-06-01 17:33 +08.
- `backend/app/core/stream_bus.py:191` / §StreamBus status summary — each row
  contains `stream`, `length`, and `last_published_at`; fresh verify
  2026-06-01 17:33 +08.
- `frontend/src/api/system.ts:194` / §System wrappers — `fetchSystemStreams()`
  now wraps `/system/streams`; fresh verify 2026-06-01 17:33 +08.
- `frontend/src/pages/SystemSettings.tsx:63` and `:644` /
  §SystemSettings health tab — the Redis Streams panel loads through the API
  wrapper and is mounted under health; fresh verify 2026-06-01 17:33 +08.

### §24.2 Closure

- Added typed Redis Streams API wrapper in `frontend/src/api/system.ts`.
- Added a read-only Redis Streams panel to `SystemSettings` health tab with
  30-second refresh, stream counts, total messages, per-stream length, and last
  publish time.
- Added wrapper and rendered-page contract tests.
- Updated row 144 to consumed and removed it from §5D.

### §24.3 Verification

- RED:
  `npx vitest --run src/__tests__/system-api-streams.test.ts src/__tests__/system-settings-streams.test.tsx`
  first failed because the wrapper and panel were absent.
- GREEN targeted:
  `npx vitest --run src/__tests__/system-api-streams.test.ts src/__tests__/system-settings-streams.test.tsx`
  -> 2 passed.
- Frontend regression:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 144 passed;
  `npm run build` -> exit 0 with the existing Vite vendor-echarts chunk-size
  warning.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected; `bash config/hooks/pre-push` -> X10 clean, LLM import guard
  clean, smoke 91 passed, 2 skipped, 6976 deselected.

### §24.4 Remaining Work

Commit/push and GitHub checks remain pending for Batch 23.

## §25 Fresh verify — 2026-06-01 (Factor `{name}` coverage drift)

### §25.1 Finding

Row 69 `GET /api/factors/{name}` was marked backend-only in §4/§5D, but current
frontend code already consumes it through `fetchFactorIcSeries()` for the
IcMonitoring S1 chart. This was coverage documentation drift, not an
implementation gap.

Fresh evidence:
- `backend/app/api/factors.py:477` / §single factor detail endpoint — route
  returns factor metadata, stats, and `ic_series`; fresh verify 2026-06-01
  17:45 +08.
- `frontend/src/api/factors.ts:56` and `:61` / §factor API wrappers —
  `fetchFactorIcSeries()` calls `/factors/{factorName}` with date params; fresh
  verify 2026-06-01 17:45 +08.
- `frontend/src/pages/IcMonitoring.tsx:25`, `:76`, and `:82` /
  §IcMonitoring S1 — page query uses `fetchFactorIcSeries()` for the selected
  factor; fresh verify 2026-06-01 17:45 +08.
- `frontend/src/__tests__/factors-api.test.ts:29` and `:56` /
  §factor API contracts — test now locks wrapper endpoint mapping and page
  consumption; fresh verify 2026-06-01 17:45 +08.

### §25.2 Closure

- Added contract coverage for `fetchFactorIcSeries()`.
- Updated the factor API inventory to current call sites, including
  `health-check` and `correlation-prune`.
- Marked row 69 consumed and removed it from §5D.
- Updated historical O9 to reflect the already-repaired `POST
  /factors/health-check` wrapper.

### §25.3 Verification

- Contract:
  `npx vitest --run src/__tests__/factors-api.test.ts` -> 4 passed.
- Frontend regression:
  `npx tsc -b --pretty false` -> exit 0;
  `python scripts/audit/check_frontend_api_discipline.py` -> PASS;
  `npx vitest --run` -> 146 passed;
  `npm run build` -> exit 0 with the existing Vite vendor-echarts chunk-size
  warning.
- Backend smoke/pre-push:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected; `bash config/hooks/pre-push` -> X10 clean, LLM import guard
  clean, smoke 91 passed, 2 skipped, 6976 deselected.

### §25.4 Remaining Work

Batch 24 commit, push, and GitHub checks completed before Batch 25. No factor
row 69 work remains.

## §26 Fresh verify — 2026-06-01 (Notification detail view + unread-count reclass)

### §26.1 Finding

Rows 88-89 in §5D bundled two different cases. Fresh code review showed
`GET /api/notifications/unread-count` is intentionally redundant because
`GET /api/notifications` already returns `unread_count`, while
`GET /api/notifications/{notification_id}` still lacked a frontend consumer.

Fresh evidence:
- `backend/app/api/notifications.py:74` and `:99-104` / §list route — list
  response includes `unread_count`; fresh verify 2026-06-01 18:05 +08.
- `backend/app/api/notifications.py:107` / §unread-count route — standalone
  count endpoint remains backend-only by design; fresh verify 2026-06-01
  18:05 +08.
- `backend/app/api/notifications.py:186` / §notification detail route — detail
  endpoint returns `repo.get_by_id()` or 404; fresh verify 2026-06-01
  18:05 +08.
- `frontend/src/api/notifications.ts:129` and `:134` / §notification API
  wrappers — `fetchNotificationDetail()` calls `/notifications/{id}` and
  normalizes the backend row; fresh verify 2026-06-01 18:05 +08.
- `frontend/src/components/ui/NotificationPanel.tsx:128` and `:133` /
  §notification panel — no-link rows fetch and render backend detail content;
  fresh verify 2026-06-01 18:05 +08.

### §26.2 Closure

- Added `fetchNotificationDetail()` to the unified notification API layer.
- Added a no-link notification detail state to `NotificationPanel`, including
  load/error/detail/list states.
- Added a dropdown-close regression so a reopened panel returns to the list
  instead of stale detail content.
- Reclassified row 88 as redundant and removed the notification row from §5D.

### §26.3 Verification

- RED detail contract:
  `npx vitest --run src/__tests__/notifications-api-contract.test.ts src/__tests__/notifications-ui-contract.test.tsx`
  failed before the wrapper/panel change because `fetchNotificationDetail` was
  missing and the panel never called the backend detail endpoint.
- RED close-state regression:
  `npx vitest --run src/__tests__/notifications-ui-contract.test.tsx -t "returns to the list"`
  failed before the close-path fix because reopened dropdowns still showed the
  prior detail body.
- GREEN targeted notification contracts:
  `npx vitest --run src/__tests__/notifications-api-contract.test.ts src/__tests__/notifications-ui-contract.test.tsx`
  -> 13 passed.

Full regression/build/smoke results are recorded in the Batch 25 status report.

### §26.4 Remaining Work

Notification cleanup, preferences, and admin test endpoints remain backend/admin
workflow candidates. They are not part of the current operator panel chain.
