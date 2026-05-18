# V3 Audit Section V — Frontend Redesign Proposal (2026-05-18 evening)

> **Source**: Subagent H §21-24 (Frontend Redesign)
> **Sister doc**: `V3_AUDIT_S9_UX_CONTROL_PLANE.md` (Section XI Backend Op → Frontend Action Matrix)
> **Master**: `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`

---

## §21 Current Frontend Diagnosis

### §21.1 Repository State
- **Last commit on `frontend/`**: 2026-04-17 15:19:08 `6f57180 chore(gitignore): untrack runtime state`
- **31 days stale** (verify: `git log -1 -- frontend/`)
- Real code change is ≥ Wave 1 timeframe (gitignore-only commit on 4-17)

### §21.2 Stack
- React 18.3.1 + TypeScript 5.7.2 + Vite 6.3.1
- Tailwind 4.1.3 (`@tailwindcss/vite` plugin)
- State: Zustand 5.0.12 (4 stores: auth/notification/backtest/mining)
- Data fetching: `@tanstack/react-query 5.95.2` + `axios 1.7.9`
- Charts: **ECharts 5.6.0 + Recharts 3.8.1 (dual library — anti-pattern, ~500KB redundant bundle)**
- Realtime: `socket.io-client 4.8.3` (**no socket.io backend server**)
- Router: react-router-dom 7.13.2
- Test: Vitest 4.1.2 + RTL

### §21.3 Pages Inventory (35 .tsx)
- **Trading**: DashboardAstock.tsx, Portfolio.tsx, RiskManagement.tsx, Execution/index.tsx, PMS.tsx
- **Strategy**: StrategyWorkspace.tsx, BacktestConfig.tsx, BacktestRunner.tsx, BacktestResults.tsx, StrategyLibrary.tsx
- **Factor**: FactorLibrary.tsx, FactorLab.tsx, FactorEvaluation.tsx, MiningTaskCenter.tsx
- **Pipeline/AI**: PipelineConsole.tsx, AgentConfig.tsx
- **System**: SystemSettings.tsx, MarketData.tsx, ReportCenter.tsx, PTGraduation.tsx
- **Dummy**: ComingSoon.tsx (placeholder), DashboardForex.tsx (deferred), TradeExecution.tsx (likely superseded)

### §21.4 Components
- 54 .tsx in `frontend/src/components/`
- Well-organized subdirs: `ui/`, `shared/`, `factor/`, `backtest/`, `mining/`, `pipeline/`, `strategy/`, `agent/`, `layout/`

### §21.5 Sidebar IA Issues (Sidebar.tsx:35-75)
- 6 groups, 13 routes
- **Missing**: News (4 sources backend exists), Audit Trail, LL/ADR browser, Reflector Reports, System Health page (only Settings exists)
- IA mixes "频率组织" with module grouping → confusing operator vs researcher mental model

### §21.6 之前 Frontend 问题 (per User: "之前的前端有问题")

1. **socket.io-client installed but no server** — `useWebSocket.ts` hook exists but no backend `socket.io` endpoint. Realtime via HTTP polling. **70KB dead weight + dev confusion**.
2. **Dual chart libs**: ECharts + Recharts both installed — components mix. Bundle bloat + style inconsistency.
3. **35 pages vs ~21 services with API** (Subagent F connectivity finding) — frontend has pages for unimplemented backend.
4. **131-day project gap since commit** (4-17 → 5-18) under heavy backend churn — schema drift risk.
5. **Admin token via `localStorage`** (api/execution.ts:137-145) — XSS-vulnerable, no rotation, no audit on token use. (P0-22)
6. **Sidebar IA confusing** — operator vs researcher unclear.

---

## §22 Backend Feature Surface for Frontend

### §22.1 132 Endpoints Coverage

| Backend has | Frontend uses | Gap |
|---|---|---|
| /api/risk/l4-approve/{id} (risk.py:239) | ⚠️ unverified | Likely 0 UI for L4 STAGED approval — Section XI critical, P1-49 |
| /api/risk/l4-recovery/{id} | ⚠️ unverified | No UI button |
| /api/risk/force-reset/{id} | ⚠️ unverified | Sensitive op, no UI gate |
| /api/news/ingest, /ingest_rsshub, /ingest_announcement | 0 frontend hits | No News page |
| /api/factors/{name}/archive | ✅ used | OK |
| /api/strategies/{id}/rollback | ⚠️ unverified | Version rollback UI gap |
| /api/params/init-defaults | 0 frontend hits | Admin reset gap |
| /api/execution/alert-config PUT | 0 frontend hits | No UI editor |

### §22.2 Critical Backend Ops with ZERO Frontend (Section XI gap, see S9 doc)

- signal_phase trigger (Celery Beat 16:30 only)
- execute_phase (schtask only)
- emergency_close_all_positions (script only)
- cancel_stale_orders (script only)
- env_flip paper↔live (manual .env edit)
- Servy service restart (script)
- schtask enable/disable (powershell)
- pull_tushare force-pull (script)
- factor_lifecycle force (Beat only)
- LL/ADR sediment (file-write only)

### §22.3 Real-Time Updates Gap

- Backend: Redis Streams `qm:{domain}:{event_type}`
- Frontend: `useWebSocket.ts` hook exists, **0 socket.io server**
- Current: HTTP polling 30s refetch via React Query
- For PT live tick, polling is wasteful + laggy

---

## §23 New Frontend Design Proposal (12 Pages, Role-Tabbed IA)

### §23.1 User Persona (Per Memory)
- Single user, full-time quant developer
- Dual-role (operator + researcher + auditor)
- Chinese UI primary
- Expects "Team Lead 主动推进" → UI must surface decisions/risks proactively

### §23.2 Recommended IA

```
A. OPERATOR (生产, 每日)
   1. Control Center (NEW)        — 单页命令中枢 (Section XI fulfillment)
   2. PT Dashboard                 — NAV/PnL/持仓/今日交易 + live tick
   3. Risk Monitor                 — V3 L0-L5 state + alert timeline + 元告警
   4. Trade Audit                  — trade_log + recon diff + fill detail

B. RESEARCHER (研究)
   5. Factor Explorer              — 库/IC 趋势/画像/生命周期
   6. Strategy Lab                 — multi-factor combine + WF simulate
   7. Backtest Viewer              — regression/WF/比较
   8. Signal Explorer              — 今天 signal + 历史 + drift

C. AUDITOR (审计)
   9. Audit Trail                  — LL/ADR/sediment 文档浏览 + diff
   10. L5 Reflector Reports        — weekly/monthly/event
   11. System Health               — Servy + Beat + Schtask + DB freshness

D. ALL
   12. News Stream                 — 6 sources + classified + sentiment
```

### §23.3 Tech Stack Decisions

| Stack | Current | Recommended | Rationale |
|---|---|---|---|
| Framework | React 18.3.1 | **Keep React 18** | Mature, low migration cost. SvelteKit/Solid force re-write of 89 components for marginal perf gain |
| Charts | ECharts + Recharts | **Drop Recharts → ECharts only** | Richer fin charts, candlestick built-in, ~250KB savings (P1-47) |
| Realtime | socket.io-client (no server) | **Drop socket.io + use native EventSource (SSE)** | Replace with native SSE for Redis Streams bridge OR native WebSocket. Single user → SSE simpler than socket.io (P1-48) |
| State | Zustand | **Keep Zustand** | Fine for single-user; React Query handles server state |
| Real-time strategy | HTTP polling 30s | **FastAPI SSE endpoint per stream** (e.g. `GET /api/streams/risk` returns SSE) bridging Redis pub/sub | Polling kept for low-freq (factor health 60s) |
| Charting | mixed | **ECharts only** | K-line + IC heatmap + risk timeline = ECharts strengths |
| Mobile | none | **Minimal** | Single-user desktop. Skip PWA. Mobile fallback only for alerts viewing |
| Performance budget | unverified | **TTI < 1.5s, page-switch < 200ms, tick lag < 500ms** | Plan baselines |
| Auth | `localStorage` admin_token | **httpOnly cookie + CSRF token + TOTP step-up for CRIT ops** | Anti-XSS (P0-22) |
| Theme | glass+dark per `frontend/src/theme/` | **Codify into `tokens.ts`** | Type-safe design tokens |
| i18n | none | **Skip** | Single Chinese user |

### §23.4 Component Library Foundation

- Button (primary/secondary/danger/ghost)
- Modal w/ ConfirmModal 三锁 variant (env match + typed phrase + cooldown)
- Form (validation + zod schema)
- Table (sortable / filterable / pagination)
- Chart wrapper (ECharts) — line / bar / candlestick / heatmap / sankey
- AlertBanner (env state always visible)
- AuditLogPanel (immutable log component)
- StreamingTickView (SSE consumer for live tick)

### §23.5 New Page Highlights

#### Control Center (NEW v6 critical)
- Single-page command palette
- 30 backend ops listed with safety tiers
- Quick actions: dry-run + execute + cancel + env_flip + emergency_close
- Cmd+K shortcut

#### PT Dashboard refresh
- Real-time NAV via SSE
- Today's signal preview pre-09:31
- Live order fill feed
- Intraday P&L tick chart

#### Risk Monitor
- V3 L0-L5 live state visualization
- Alert timeline (filterable by severity + rule)
- 元告警 panel
- Approve/Reject buttons for L4 STAGED

---

## §24 Roadmap (5 Phases, ~11 Weeks)

| Phase | Scope | Effort | Dependency |
|---|---|---|---|
| **P1 API Contract Finalize** | Add ~15 missing endpoints (signal/execute/emergency/env_flip/schtask/Servy/L4-approve/pull-force/LL-sediment); generate OpenAPI; freeze schemas | 2 weeks | Backend Section XI buy-in |
| **P2 Design System + Base** | Color tokens + button/modal/form primitives + confirm-modal w/ 双锁 + audit-log component + theme provider; ECharts wrapper | 1 week | P1 contracts |
| **P3 Operator Pages** | Control Center (§41 matrix) + PT Dashboard refresh + Risk Monitor L0-L5 + Trade Audit. SSE bridge for live | 3 weeks | P1+P2 |
| **P4 Researcher Pages** | Factor Explorer rewrite + Strategy Lab + Backtest Viewer + Signal Explorer | 3 weeks | P3 patterns established |
| **P5 Auditor + Observability** | Audit Trail + L5 Reports + System Health + News Stream + AI ops (§45) | 2 weeks | All API + design system frozen |

**Total**: ~11 weeks (2-3 months) for full rewrite.

**Cheaper alternative (heuristic #18)**: Keep current pages, incrementally retrofit Control Center only (~2 weeks) to address Section XI critical need first, defer full rewrite.

---

## §25 Top 10 P0/P1 Findings (with Heuristic #18 Alternatives)

(Per Subagent H; aligned with Master Top 50)

| # | Finding | Heuristic | Alt 1 | Alt 2 | Alt 3 |
|---|---|---|---|---|---|
| **P0-1** | execute_phase has 0 API + 0 UI — LL-183 attack surface | #19 | API + 三锁 modal | API only, no UI (CC-mediated) | Keep schtask-only, add monitoring page |
| **P0-2** | env_flip is manual `.env` edit + Servy restart — LL-183 silent-mode-mismatch root | #19 | API + 三锁 + DingTalk + cooldown | API + separate operator_token | Refuse to API-ify; keep manual; add UI banner only |
| **P0-3** | socket.io-client installed but no socket.io backend — dead 70KB + misleading | #18 | Remove pkg, build SSE bridge | Build socket.io server (needed for multi-tab) | Keep + delete `useWebSocket.ts` (cleanup only) |
| **P0-4** | Admin token in `localStorage` (api/execution.ts:137) XSS-vulnerable | #18 | httpOnly cookie + CSRF | TOTP step-up for CRIT | WebAuthn passkey |
| **P0-5** | No always-visible env banner — LL-183 prevention | #19 | Banner top + per-route gate | Banner only on operator pages | Status indicator in sidebar (current Sidebar.tsx:227 only shows `v2.0·在线`) |
| P1-6 | Dual chart libs (ECharts + Recharts) ~500KB redundant | #18 | Drop Recharts | Drop ECharts (loss of K-line) | Keep both, codify per-use rule |
| P1-7 | 35 pages, ~21 services, drift since 2026-04-17 | #19 | Audit each page, archive broken | Full rewrite per §24 roadmap | Page-by-page incremental refresh |
| P1-8 | L4 STAGED approve has API but no UI (risk.py:239) | #19 | Add Risk Monitor approve/reject buttons | DingTalk-only (no UI) | Email approval link |
| P1-9 | No Control Center / Command Palette for ~13 CC-only ops | #19 | Build Control Center page | Cmd+K palette only | Per-section pages w/ ops |
| P1-10 | Sidebar IA based on "频率组织" mixes operator/researcher | #19 | Role-tab IA (operator/researcher/auditor) | Workflow-based IA (今日/分析/审计) | Keep current + add role selector |

---

## §26 Cross-Reference

- Section XI deeper analysis: `V3_AUDIT_S9_UX_CONTROL_PLANE.md`
- Frontend Design Spec (claude.ai/design feedable): `V3_AUDIT_FRONTEND_DESIGN_SPEC.md`
- Designer agent mockup: `V3_AUDIT_FRONTEND_DESIGN_PROPOSAL.md` + `frontend_mockups/{A,B,C}.html`

---

**End Section V.**
