> ⚠️ **DIRECTION DEPRECATED 2026-05-19** — user feedback: "**A/B/C 偏离我的设计**, 并不是将 ADR/LL 都体现在 web, 而是业务相关. 你可以在之前的 web 基础上进行改造, 但是 **C 的 AI 辅助这个很有用**, 可以弄到之前的 web 上".
> **Canonical**: `V3_AUDIT_FRONTEND_DESIGN_REVISED_v2.md` — incremental refactor of existing 35 pages + AI 辅助 panel 集成 (extracted from C variant).
> 3 HTML mockups in `frontend_mockups/{A,B,C}.html` 保留为 exploratory artifact, NOT canonical direction. C 的 AI chat panel pattern → 沉淀到 v2 doc §2.4 `AssistPanel.tsx` design.
>
> ---
>
> # V3 Frontend Design Proposal — A/B/C Variant Rationale
## Phase 4-bis Step B · oh-my-claudecode:designer agent output · 2026-05-18 evening

> **Sister docs**: `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` (IA + roadmap) · `V3_AUDIT_S9_UX_CONTROL_PLANE.md` (32 ops matrix) · `V3_AUDIT_FRONTEND_DESIGN_SPEC.md` (full design spec)
> **Mockup files**: `frontend_mockups/A_safety_first.html` · `frontend_mockups/B_trader_velocity.html` · `frontend_mockups/C_ai_assisted.html`
> **Context**: QuantMind-V2 post-LL-183. Cash ¥993,520.66 / 0 持仓. LIVE_TRADING_DISABLED=false (RED LINE state). User mandate: "所有后端操作都需要能在前端进行操作, 交互式"

---

## Part 1 — A/B/C Tradeoff Matrix

### 1.1 Variant Summary Table

| Dimension | A: Safety-First | B: Trader-Velocity | C: AI-Assisted |
|---|---|---|---|
| **Core philosophy** | Maximum guardrail — no accidental CRIT ops | Speed + liveness — minimize friction for daily flow | Natural language — reduce cognitive load via LLM |
| **Primary user mode** | Auditor + Operator (cautious) | Operator (daily trading day) | Researcher + Operator (explainability) |
| **Op confirmation UX** | Full 三锁 for CRIT, always-visible detail | 1-click for LOW, toast undo, CRIT 三锁 minimal | Natural language → AI composes → user manually confirms CRIT |
| **Env state visibility** | Large persistent red banner, always high-contrast | Compact persistent strip, restrained | Banner + AI proactive warning in chat on session start |
| **Audit log** | Always-visible right panel (40% viewport) | Right streaming log panel (live SSE feed) | Embedded in chat context (AI summarizes recent audit) |
| **CRIT gate strength** | Maximum (env lock + typed phrase + 5s cooldown + disabled if L4 active) | Standard 三锁 (env + phrase + cooldown), faster UX | AI boundary enforced (AI never executes CRIT) + standard 三锁 modal |
| **LL-183 prevention** | Explicit lockout banner disables CRIT ops during anomalous env | Warning banner; CRIT buttons disabled by lockout | AI proactively warns on session start + refuses CRIT |
| **1-click ops (LOW)** | Yes, with toast undo 10s | Yes, prominent quick grid | Via natural language OR op button |
| **Live data** | HTTP polling (safer, simpler) | SSE streaming log + ticker strip | AI can query on demand; SSE for system feed |
| **Command palette** | Secondary (button exists, not primary) | Primary (⌘K prominent, all 32 ops listed) | Secondary (chat is primary) |
| **AI integration** | None | None (except ⌘K palette search) | Full (Claude Sonnet streaming, tool calls) |
| **LLM cost** | $0 | $0 | ~¥3-10/month (V3 §16.2 cap ¥50) |
| **Complexity to build** | Medium | Medium | High (requires `/api/agent/chat` + tool schema + cost cap server-side) |
| **Framework migration** | Incremental (can retrofit current pages) | Incremental | Requires new AI backend endpoint (Phase 5+) |
| **Accessibility** | High (large targets, high contrast, keyboard nav) | High (large quick buttons) | Medium (chat UX less accessible) |
| **Mobile emergency** | Works (large banner + buttons visible) | Works | Limited (chat UX requires keyboard) |

### 1.2 Per-Variant Strength/Weakness Deep Analysis

#### Variant A — Safety-First

**Strengths**:
- Directly addresses LL-183 root cause: env anomaly is unmissable
- Immutable audit log always visible eliminates "what happened?" guesswork
- Explicit lockout (ops disabled during bad env state) prevents re-injury
- Schtask table inline on Control Center = single pane for system state
- Most conservative = lowest risk of accidental CRIT execution
- 三锁 modal demo (env-flip) is the most complete guardrail implementation

**Weaknesses**:
- Highest friction for daily operator flow (every CRIT = 3 steps)
- Audit log panel consumes 30% of viewport — heavy for research workflows
- No liveness (polling only) — PT live tick not well supported
- Conservative = slow; frustrating for experienced daily operator
- Duplicate confirmation UX may breed "confirm fatigue" over time

**Best fit**: Post-incident recovery phases, PT restart gate validation, auditor role, new user onboarding

---

#### Variant B — Trader-Velocity

**Strengths**:
- Best daily operator DX — minimal friction for LOW/MED ops (1-click + toast undo)
- 3-column layout is information-dense without feeling overwhelming
- SSE streaming log (right panel) gives real-time beat/schtask/signal feedback
- ⌘K command palette = power-user shortcut for all 32 ops
- Sparkline NAV chart + KPI strip immediately shows account state
- Left sidebar service status (FastAPI/Celery/QMTData dots) = sub-second health check
- Best for market-hours flow (09:00-15:00 intraday monitoring)

**Weaknesses**:
- CRIT ops (execute_phase, env_flip) still require 三锁 — but less prominent guardrail than A
- Without always-visible immutable audit log, audit trail requires separate page
- Command palette UX assumes keyboard shortcut proficiency
- Streaming SSE requires backend `/api/streams/*` endpoints (not yet built — §7.1)
- Faster UX = higher risk of hasty CRIT op if user is tired/stressed

**Best fit**: Normal trading day operation, signal-to-execution flow, daily monitoring loop

---

#### Variant C — AI-Assisted

**Strengths**:
- Natural language eliminates "what's the API?" cognitive load
- Context-aware AI suggestions surface relevant ops based on current state (dv_ttm warning → auto-suggest analysis)
- Auto-explain panels (factor contribution bars, regime detection) = researcher insight without extra clicks
- AI boundary enforcement is architecturally sound: AI cannot execute CRIT even if prompted
- LL draft generation via AI = significant time saving for incident documentation
- Best for researcher + auditor role (exploratory, not transactional)
- Cost-tracked (LLM cost always visible per session)

**Weaknesses**:
- Requires new backend: `/api/agent/chat` with Claude API + tool schema + cost cap
- AI latency (1-2s per response) unacceptable for market-hours ops (09:31 execute_phase window)
- Single-user with deep system knowledge: may find natural language slower than direct buttons
- LLM hallucination risk for system state (AI may confidently report stale data)
- AI cannot help with CRIT ops → forces modal switch anyway, removing AI benefit at critical moments
- Highest implementation effort (Phase 5+ per §24 roadmap)
- LLM cost + API dependency (external service reliability)

**Best fit**: Evening research sessions, incident post-mortem, LL/ADR drafting, factor exploration

---

## Part 2 — Recommended Path

### 2.1 Primary Recommendation: Hybrid A+B (Phased)

**Phase 1 (2 weeks) — Variant A retrofit**: Build Control Center page with full guardrails. Priority because:
1. LL-183 direct prevention (P0-23 env banner + P0-13 execute 三锁)
2. Satisfies user mandate "所有后端操作能在前端" for the CRIT ops first
3. Minimal new infrastructure (no SSE, no AI backend)
4. Can be built as new page in existing `frontend/src/pages/ControlCenter.tsx` without touching current pages

**Phase 2 (3 weeks) — Layer B velocity patterns**: After guardrails are proven, add:
- ⌘K command palette overlay
- Streaming log panel via native `EventSource` (drop `socket.io-client`)
- KPI strip with React Query polling (upgrade to SSE in Phase 3)
- Quick-grid buttons replacing the A grid (same safety tiers, faster UX)

**Phase 3 (3 weeks) — SSE real-time**: Build `/api/streams/*` FastAPI SSE endpoints bridging Redis Streams. Add live tick to PT Dashboard. Remove polling for critical paths.

**Phase 4 (Phase 5+) — Variant C AI layer**: After core op plane is stable + PT restart validated + API contracts frozen. Only if user finds natural language genuinely useful in practice.

### 2.2 Alternative Paths (Heuristic #18 — 3 options per variant)

#### Variant A alternatives
| Path | Description | Effort | When to choose |
|---|---|---|---|
| **A1 (recommended)** | Build `ControlCenter.tsx` as new page in existing React app. Incremental retrofit. No framework change. | 2 weeks | Default choice — lowest risk |
| **A2** | Full React rewrite of Sidebar + all pages with new IA (§23.2). Control Center first, then 11 more pages. | 11 weeks | Only if budget allows full Phase P1-P5 per §24 roadmap |
| **A3** | Build Control Center as **standalone mini-app** (`/admin` route, separate bundle) with heightened auth. Current app untouched. | 1 week | If concerned about regressions in current pages |

#### Variant B alternatives
| Path | Description | Effort | When to choose |
|---|---|---|---|
| **B1 (after A)** | Layer velocity UX (⌘K + streaming log + quick grid) on top of A guardrails. Same `ControlCenter.tsx`. | 3 weeks | Recommended Phase 2 path |
| **B2** | Build as PWA with Service Worker for offline emergency button (emergency_close only). | 4 weeks | If mobile emergency access is needed |
| **B3** | Build ⌘K palette only (no page changes). Palette covers all 32 ops. Minimal footprint. | 1 week | Fastest way to satisfy "所有后端操作前端化" without page redesign |

#### Variant C alternatives
| Path | Description | Effort | When to choose |
|---|---|---|---|
| **C1** | Full chat panel as described. Requires `/api/agent/chat` + Claude API + tool schema. | 4-5 weeks | Phase 5+ |
| **C2** | AI for **read-only queries only** (no tool calls, no mutations). Chat can explain system state, not execute ops. Zero safety risk. | 2 weeks | Can build earlier as research tool |
| **C3** | Skip AI entirely. Use smart context panel (auto-explain from API data, no LLM). Same visual result, no LLM cost/risk. | 1.5 weeks | Preferred if user values explainability but not natural language input |

---

## Part 3 — Implementation Effort Estimates

### 3.1 Per-Variant Effort

| Variant | New endpoints needed | New components | Estimated dev time | Infrastructure new |
|---|---|---|---|---|
| A (Safety-First) | 13 new (§41 matrix LOW-CRIT) + 5 existing wired | ControlCenter page, ConfirmModal 三锁, AlertBanner, AuditLogPanel, SchtaskTable | 2-3 weeks | None (polling only) |
| B (Trader-Velocity) | Same 13 + 6 SSE endpoints (§7.1) | Everything in A + CommandPalette + StreamingLogPanel + Sparkline | 4-5 weeks | SSE bridge for Redis Streams |
| C (AI-Assisted) | Same 13 + 6 SSE + 1 AI chat endpoint | Everything in A+B + ChatPanel + ToolCallDisplay + CostTracker + AutoExplainPanels | 7-9 weeks | Claude API integration + cost cap server-side |

### 3.2 API Contract Gap (per §41 coverage: 14/32 have both API+UI)

Priority order for new endpoints (Phase 1):

| Priority | Endpoint | Safety | Effort |
|---|---|---|---|
| P0 | `POST /api/paper-trading/execute-trigger` | CRIT | 0.5d (schtask wrapper) |
| P0 | `POST /api/system/execution-mode` (env_flip) | CRIT | 1d (env write + Servy restart + audit) |
| P1 | `POST /api/paper-trading/signal-trigger` | LOW | 0.5d |
| P1 | `POST /api/execution/cancel-stale` | LOW | 0.5d |
| P1 | `POST /api/system/services/{name}/restart` | MED | 1d (Servy wrapper) |
| P1 | `PUT /api/system/schtasks/{name}` | MED | 0.5d |
| P2 | `POST /api/data/pull/tushare` | LOW | 0.5d |
| P2 | `POST /api/factors/lifecycle/run` | LOW | 0.5d |
| P2 | `POST /api/system/backup/run` | LOW | 0.5d |
| P2 | `POST /api/audit/lessons` | LOW | 1d (file write + git) |
| P2 | `POST /api/audit/adrs` | LOW | 0.5d |
| P3 | `GET /api/system/celery/schedule` | LOW | 0.5d |
| P3 | SSE endpoints (6) | LOW | 2d total |

**Total P0+P1 backend**: ~4.5 days
**Total P0+P1+P2 backend**: ~8 days
**SSE bridge**: ~2 days (after P0+P1+P2 stable)

---

## Part 4 — Integration Plan with Existing `frontend/src/`

### 4.1 Incremental Migration Strategy (Minimal Disruption)

```
frontend/src/
├── pages/
│   ├── ControlCenter.tsx          ← NEW (Phase 1 — builds on design spec Part 4 §Page 1)
│   ├── DashboardAstock.tsx        ← RETROFIT (add EnvBanner import, SSE in Phase 2)
│   ├── RiskManagement.tsx         ← RETROFIT (add L4 approve/reject buttons per §41 #17-19)
│   ├── SystemSettings.tsx         ← RETROFIT (add Servy + schtask management from §Page 11)
│   └── [existing pages untouched] ← No breakage
├── components/
│   ├── ui/
│   │   ├── EnvBanner.tsx          ← NEW (P0-23 anti-LL-183, mount in App.tsx Layout)
│   │   ├── ConfirmModal.tsx       ← NEW (三锁 variant per spec §3.2)
│   │   ├── AuditLogPanel.tsx      ← NEW (immutable log per spec §3.7)
│   │   ├── CommandPalette.tsx     ← NEW (Phase 2, ⌘K)
│   │   └── StreamingTickView.tsx  ← NEW (Phase 2-3, EventSource)
│   └── [existing components untouched]
├── api/
│   ├── control-center.ts          ← NEW (13 new endpoints)
│   └── [existing api files untouched]
└── App.tsx                        ← MODIFY: add /control-center route + EnvBanner in Layout
```

### 4.2 Step-by-Step Migration

**Step 1 (Week 1)**: EnvBanner + ConfirmModal 三锁 components
- Drop `socket.io-client` (P0-3, 70KB saved)
- Add `EnvBanner` to `Layout.tsx` — always visible, reads from `GET /api/system/env-state`
- Add `ConfirmModal` with 4 safety tiers (LOW/MED/HIGH/CRIT)
- Zero breakage to existing pages

**Step 2 (Week 2)**: Control Center page
- New route `/control-center` in `react-router-dom`
- Add to Sidebar under OPERATOR group
- Wire to 13 new backend endpoints (P0 first: execute-trigger, env_flip)
- `AuditLogPanel` component (reads `GET /api/audit/timeline` polling 5s)

**Step 3 (Week 3)**: Risk Monitor L4 buttons
- Retrofit `RiskManagement.tsx` with L4 approve/reject buttons (§41 #17-19)
- Wire `POST /api/risk/l4-approve/{id}` + `POST /api/risk/l4-recovery/{id}`

**Step 4 (Week 4)**: System Health schtask management
- Retrofit `SystemSettings.tsx` or create `SystemHealth.tsx`
- Wire schtask enable/disable + Servy restart per sidebar service list

**Step 5 (Weeks 5-6)**: Recharts removal + ECharts consolidation
- Audit all 54 components for Recharts imports
- Replace with ECharts wrappers (P1-6, ~250KB savings)
- Add candlestick chart to PT Dashboard

**Step 6 (Weeks 7-8)**: SSE bridge
- Build `/api/streams/*` FastAPI endpoints (6 per §7.1)
- Replace `socket.io-client` `useWebSocket.ts` with native `EventSource`
- Wire to `StreamingTickView` component

### 4.3 Auth Migration (P0-22, Non-Breaking)

Current: `localStorage` admin token in `api/execution.ts:137`

Migration path (zero-downtime):
1. Backend: add `httpOnly cookie` auth endpoint alongside existing bearer token
2. Frontend: update `axios` interceptor to prefer cookie auth, fallback to bearer
3. CRIT ops: add TOTP step-up modal before `ConfirmModal` 三锁
4. After 2 weeks: deprecate localStorage token
5. Final: operator_token + researcher_token split

---

## Part 5 — Cross-Reference to Phase H Roadmap

Per `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` §24:

| §24 Phase | Our recommendation | Alignment |
|---|---|---|
| **P1 API Contract** (2 weeks) | Build 13 missing endpoints first (Part 3.2 above), freeze OpenAPI schema | Full alignment |
| **P2 Design System** (1 week) | EnvBanner + ConfirmModal 三锁 + AuditLogPanel + ECharts wrapper | Full alignment — build these before pages |
| **P3 Operator Pages** (3 weeks) | Control Center (Variant A) + PT Dashboard (Variant B velocity layer) + Risk Monitor L4 | Full alignment |
| **P4 Researcher Pages** (3 weeks) | Factor Explorer rewrite (existing `FactorEvaluation.tsx` baseline), Strategy Lab, Backtest Viewer | Defer to after P3 stable |
| **P5 Auditor + AI** (2 weeks) | Audit Trail + L5 Reports + Variant C AI layer (Phase 5+ only) | Defer AI to after PT restart validated |

**Cheaper §24 alternative (heuristic #18)**:
Per §24 last paragraph — "Keep current pages, incrementally retrofit Control Center only (~2 weeks)". This is exactly our **Step 1-2** recommendation. Satisfies the critical Section XI need (§41 32 ops → UI) with minimal disruption.

---

## Part 6 — Design System Decisions

### 6.1 Aesthetic Direction

**Chosen tone**: Precision instrument — dark, data-dense, zero decorative chrome. Every element earns its place by conveying information or enabling action. Inspired by Bloomberg Terminal density + trading system control panels, not consumer SaaS.

**Differentiation** (the ONE memorable thing): The always-visible env state banner that pulses red when LIVE_TRADING_DISABLED=false. This is a direct LL-183 memorial — the system remembers its own near-miss and will not let the operator forget the current env state.

**Deliberately avoided**:
- Purple gradients on white (AI slop aesthetic)
- Large hero sections (no marketing content)
- Animated loading skeletons beyond functional indicators
- Decorative illustrations or icons beyond functional emoji shortcuts
- Card drop shadows that don't indicate elevation hierarchy

### 6.2 Typography

- **UI text**: `-apple-system, "PingFang SC", "Microsoft YaHei"` — system font stack, zero loading time, native Chinese rendering
- **Numbers/code**: `"JetBrains Mono", "Consolas"` — monospace for NAV values, factor IDs, timestamps, API paths
- **No distinctive heading font** (deliberate) — this is a control panel, not a marketing site. Font personality comes from layout density and color, not decorative type.

### 6.3 Color Philosophy

- Background layers: 3 levels (`#0a0e1a` → `#111827` → `#1f2937`) — depth without harshness
- Primary brand: Cyan-500 (`#06b6d4`) — readable on dark, not aggressive
- Chinese trading convention: Red = 涨 (`#ef4444`), Green = 跌 (`#10b981`) — **reversed from Western convention**
- CRIT actions: Red glow (`box-shadow: 0 0 20px rgba(239,68,68,0.4)`) — danger is legible at a glance
- Glass morphism: `rgba(31,41,55,0.6)` + `backdrop-filter: blur(12px)` — cards float without full opacity loss

### 6.4 Motion

- Transitions ≤ 150ms for all interactive elements (button hover, modal open)
- Env banner pulse: 2s ease-in-out — subtle but persistent (anti-LL-183)
- AI typing indicator: 3-dot bounce at 800ms cycle — communicates processing without anxiety
- Toast slide-in: 250ms translateX — confirms action without stealing focus
- No page-load animations (control plane = instant readiness, not showmanship)

---

## Part 7 — Risk Assessment per Variant

| Risk | A | B | C |
|---|---|---|---|
| CRIT op accidental execution | Very Low (multiple hard gates) | Low (三锁 present but less prominent) | Low (AI refuses CRIT, still needs 三锁) |
| LL-183 recurrence | Very Low (lockout banner + disabled) | Low (warning banner, less forceful) | Low (AI warns proactively) |
| Build risk (new infra) | Low (polling only) | Medium (SSE bridge new) | High (Claude API + tool schema + cost cap) |
| Stale data risk | Low (explicit refresh buttons) | Low (SSE keeps fresh) | Medium (AI may return cached/hallucinated data) |
| User fatigue (too much friction) | Medium (confirm-fatigue for CRIT) | Low | Low (natural language is lower friction) |
| Implementation timeline slip | Low | Medium | High |

---

## Part 8 — Final Recommendation Summary

**Recommended implementation order**:

1. **Now (2 weeks)**: Variant A Control Center — EnvBanner + ConfirmModal 三锁 + AuditLogPanel + 13 new backend endpoints. Satisfies LL-183 prevention + "所有后端操作前端化" for CRIT ops.

2. **After PT restart gate passes (3 weeks)**: Layer Variant B velocity patterns — ⌘K palette + SSE streaming log + quick grid — on top of A guardrails. Daily operator UX improves dramatically.

3. **After 2 months stable PT operation**: Evaluate Variant C AI layer. Instrument actual user behavior first: if most ops are already fast via ⌘K, AI may not add enough value to justify Phase 5 complexity. If LL/ADR drafting time is significant, AI draft assist (C2 read-only path) provides value with minimal risk.

**One-line verdict**: Build A first (safety), layer B second (velocity), evaluate C last (AI).

---

**End V3 Frontend Design Proposal.**
**Files**: `frontend_mockups/A_safety_first.html` · `frontend_mockups/B_trader_velocity.html` · `frontend_mockups/C_ai_assisted.html`
