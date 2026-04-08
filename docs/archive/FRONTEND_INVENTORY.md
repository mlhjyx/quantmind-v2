# QuantMind V2 Frontend Exploration Report

**Date:** 2026-03-29  
**Scope:** D:/quantmind-v2/frontend/src/  
**Analysis Status:** Complete (Read-only exploration)

---

## 1. PAGE COMPONENTS INVENTORY (17 total)

| Page | Lines | Status | Purpose |
|------|-------|--------|---------|
| BacktestResults | 745 | FULL | NAV curves, metrics, monthly returns, holdings |
| MiningTaskCenter | 723 | FULL | Task list, real-time progress, WebSocket integration |
| SystemSettings | 648 | FULL | Agent config, model health, token costs |
| DashboardAstock | 599 | FULL | A-stock holdings, industry breakdown |
| StrategyLibrary | 574 | FULL | Strategy browse, backtest history |
| PipelineConsole | 437 | FULL | L0-L3 automation flow, approval queue |
| DashboardOverview | 388 | FULL | Main dashboard with KPIs, NAV, positions |
| FactorLab | 371 | FULL | Mining workspace (GP/LLM/Brute) |
| PTGraduation | 348 | FULL | Paper trading graduation workflow |
| BacktestRunner | 327 | FULL | Live backtest with progress tracking |
| BacktestConfig | 325 | FULL | Backtest parameter configuration |
| AgentConfig | 289 | FULL | LLM agent setup |
| Dashboard | 268 | FULL | Legacy/alternate dashboard |
| StrategyWorkspace | 254 | FULL | Strategy builder with preview |
| FactorEvaluation | 192 | FULL | Single/compare factor reports |
| FactorLibrary | 187 | FULL | Factor inventory with health checks |
| DashboardForex | 39 | STUB | Phase 2 placeholder |

**Totals:** 6,473 LOC | 16 Functional + 1 Stub | API Coverage: 90%+

---

## 2. SHARED UI COMPONENTS (44 total, 6,326 LOC)

### UI Primitives (components/ui/)
- GlassCard (52 LOC) - Glassmorphism variants
- Button (79 LOC) - Primary/secondary/danger, sm/md/lg
- MetricCard (64 LOC) - KPI display
- Breadcrumb (72 LOC) - Navigation path
- Toast (76 LOC) - Auto-dismiss notifications
- NotificationPanel (171 LOC) - Bell + dropdown
- EmptyState (33 LOC) - Placeholder
- ErrorBanner (69 LOC) - Error display
- PageSkeleton (67 LOC) - Loader skeletons

### Layout (components/layout/)
- Layout (40 LOC) - App shell
- Sidebar (153 LOC) - Navigation menu

### Agent Components
- AgentTab (252 LOC)
- CostDashboard (118 LOC)
- ModelHealth (77 LOC)

### Backtest Components (6 tabs)
- TabTimeRange (158 LOC)
- TabMarket (147 LOC)
- TabExecution (130 LOC)
- TabRiskAdvanced (206 LOC)
- TabCostModel (153 LOC)
- TabDynamicPosition (149 LOC)

### Factor Components
- FactorTable (212 LOC)
- HealthPanel (144 LOC)
- CorrelationHeatmap (128 LOC)
- TabICAnalysis (189 LOC)
- TabRegimeStats (166 LOC)
- TabGroupReturns (158 LOC)
- TabCorrelation (138 LOC)
- TabAnnual (138 LOC)
- TabICDecay (127 LOC)

### Mining Components
- GPPanel (318 LOC)
- LLMPanel (200 LOC)
- BruteForcePanel (250 LOC)
- CandidateTable (143 LOC)

### Pipeline Components
- ApprovalPanel (172 LOC)
- FlowChart (85 LOC)
- PipelineHistory (120 LOC)

### Strategy Components
- StrategyEditor (314 LOC)
- FactorPanel (180 LOC)
- StrategyPreview (106 LOC)

### Dashboard Components
- NAVChart (157 LOC)
- KPICards (91 LOC)
- PositionTable (126 LOC)
- CircuitBreaker (117 LOC)
- NotificationSystem (281 LOC)

---

## 3. ROUTER STRUCTURE (src/router.tsx)

Routes organized under Layout wrapper:

/dashboard
  - / (DashboardOverview)
  - /astock (DashboardAstock)
  - /forex (DashboardForex - STUB)

/strategy
  - / (StrategyWorkspace - browse)
  - /new (StrategyWorkspace - create)
  - /:id (StrategyWorkspace - edit)

/backtest
  - /config (BacktestConfig)
  - /history (StrategyLibrary)
  - /:runId (BacktestRunner)
  - /:runId/result (BacktestResults)

/factors
  - / (FactorLibrary)
  - /:id (FactorEvaluation)
  - /compare/:id1/:id2 (FactorEvaluation)

/mining
  - / (FactorLab)
  - /tasks (MiningTaskCenter)
  - /tasks/:taskId (MiningTaskCenter)

/pipeline
  - / (PipelineConsole)
  - /agents (AgentConfig)

/pt-graduation (PTGraduation)

/settings
  - / (SystemSettings)
  - /:tab (SystemSettings)

Features: Lazy loading, Suspense fallback spinner, parameter support

---

## 4. ZUSTAND STORES (src/store/ - 4 stores)

authStore.ts (30 LOC)
- token: string | null
- isAuthenticated: boolean
- setToken(token), clearToken()
- Persistence: localStorage key "quantmind-auth"

backtestStore.ts (44 LOC)
- activeRunId: string | null
- runs: Record<string, BacktestRun>
- setActiveRun(), upsertRun(), updateProgress(), setStatus()

miningStore.ts (39 LOC)
- activeTaskId: string | null
- tasks: Record<string, MiningTask>
- setActiveTask(), upsertTask(), updateTask()
- MiningStatus: idle|running|paused|completed|failed|cancelled
- MiningEngine: gp|llm|brute

notificationStore.ts (43 LOC)
- notifications: Notification[]
- add(notification), remove(id), clear()
- Auto-dismiss by duration
- NotificationType: info|success|warning|error

---

## 5. API LAYER (src/api/ - 8 modules + QueryProvider)

Base URL: import.meta.env.VITE_API_BASE_URL ?? "/api"
Timeout: 30s
Retry: 2 attempts exponential backoff

Query Stale Times:
- STALE.price = 30s (dashboard, positions, NAV)
- STALE.factor = 5min (reports, IC, backtest)
- STALE.config = 30min (strategy, settings, agent)

Modules:
- dashboard.ts - Summary, NAV, positions, circuit breaker
- backtest.ts - Config, progress, result, submit, cancel
- factors.ts - Library, report, correlation, IC trends, health
- mining.ts - Tasks, detail, start, pause, cancel, approve
- pipeline.ts - Status, history, approval queue, control
- strategies.ts - CRUD, backtest
- agent.ts - Configs, health, cost, logs
- system.ts - Data sources, scheduler, health

Fallback: mock.ts (summary, NAV, positions) + mockFactors.ts (factors, correlation, IC)

---

## 6. STYLING (Tailwind CSS v4.1)

Framework: @tailwindcss/vite plugin
Theme: Dark mode (baked in, #0f172a primary dark)

Glassmorphism Pattern:
bg-rgba(15,20,45,0.65) + backdrop-blur-xl + border-white/10 + shadow-inset

Component Variants:
- GlassCard: default, glow, clickable, selected
- Button: primary, secondary, danger + sm, md, lg
- Status Badges: P0 red, P1 amber, P2 blue, P3 gray

Scrollbar: 6px width, white/10 thumb, white/20 hover

---

## 7. HOOKS & CONTEXTS

Hooks (src/hooks/):
- useBacktestProgress.ts (92 LOC) - WebSocket + polling fallback
- useWebSocket.ts (68 LOC) - Socket.io reconnection wrapper

Contexts (src/contexts/):
- NotificationContext.tsx (120 LOC) - Notifications, toasts, read state
- Mock data: P0/P1/P2/P3 seeded notifications

---

## 8. DEPENDENCIES

Core: react 18.3.1, react-dom 18.3.1, react-router-dom 7.13.2
State: zustand 5.0.12, @tanstack/react-query 5.95.2
HTTP: axios 1.7.9
Charts: echarts 5.6.0, echarts-for-react 3.0.2, recharts 3.8.1
WebSocket: socket.io-client 4.8.3
Styling: tailwindcss 4.1.3, @tailwindcss/vite 4.1.3
Dev: typescript 5.7.2, vite 6.3.1, vitest 4.1.2

---

## 9. KEY GAPS

Critical Gaps:
1. No Error Boundary - Will crash on component errors
2. Types scattered - Should consolidate in src/types/
3. No test files - Test dir exists but empty
4. Chart lib duplication - ECharts + Recharts both used
5. No centralized error handling - HTTP errors not globally caught

Feature Gaps:
1. DashboardForex Phase 2 - Not implemented
2. No offline support - No service worker
3. No user profile page - Account settings missing

---

## 10. SUMMARY STATISTICS

Total Pages: 17
Total Components: 44
Total API Modules: 8
Total Stores: 4
Total Hooks: 2
Total Contexts: 1
Total Routes: 20+
Total LOC: ~13,000
Test Files: 0
Stub Pages: 1 (DashboardForex)
Fully Functional Pages: 16
API Endpoint Coverage: 90%+

---

End of Report
