# V3 Audit Section XI — User Experience & Frontend Control Plane (NEW v6, 2026-05-18 evening)

> ⚠️ **PARTIAL DIRECTION CORRECTION 2026-05-19** — user feedback: 32 ops 矩阵 (§41) 仍然 valid (业务 ops), 但**不要新建 "Control Center" 单页**. Instead: 把 ops 分散嵌入到现有 `Execution/index.tsx` (trading ops) + `SystemSettings.tsx` (system ops) + `RiskManagement.tsx` (L4 STAGED approve/reject) + `PipelineConsole.tsx` (AI assist + LLM ops).
> **Canonical direction**: `V3_AUDIT_FRONTEND_DESIGN_REVISED_v2.md` §3 Phase H REVISED.
> §41 matrix + 4 safety tiers (LOW/MED/HIGH/CRIT 三锁) 仍然 valid 应用.
>
> **Source**: Subagent H §41-45
> **Plan v6 trigger**: User "**所有后端操作都需要能在前端进行操作, 交互式**". 主仆 inversion — frontend = primary control plane, CC = automation backend.
> **Sister doc**: `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` (UI design)
> **Master**: `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`

---

## §41 Backend Operation → Frontend Action Coverage Matrix ⭐⭐⭐

> Core user concern. Enumerate ALL CC-only backend ops + frontend equivalent status.

| # | Operation | Current trigger | API? | UI? | Risk | Recommendation |
|---|---|---|---|---|---|---|
| 1 | PT `signal_phase` trigger | Beat 16:30 / `scripts/run_paper_trading.py` | ❌ | ❌ | LOW | Add `POST /api/paper-trading/signal-trigger` + Control Center button + dry-run toggle |
| 2 | PT `execute_phase` trigger | schtask 09:31 / manual schtask enable | ❌ | ❌ | **CRIT (LL-183)** | Add `POST /api/paper-trading/execute-trigger` + **三锁**: env match + manual confirm + typed phrase. NEVER silent NOT-GATING. Log to `risk_event_log`. (P0-13) |
| 3 | `--dry-run` flag | CLI flag | ❌ | ❌ | MED | Add UI toggle "Dry Run" before any trigger button |
| 4 | `cancel_stale_orders` | `scripts/cancel_stale_orders.py` | ❌ | ❌ | LOW | Add `POST /api/execution/cancel-stale` + Execution page button |
| 5 | `env_flip paper↔live` | manual `.env` edit + Servy restart | ❌ | ❌ | **CRIT** | Add `POST /api/system/execution-mode` + **三锁** + 30s cooldown + DingTalk push + audit immutable. Default LIVE_TRADING_DISABLED=true. (P0-14) |
| 6 | Servy restart | `scripts/service_manager.ps1 restart {svc}` | ❌ | ❌ | MED | Add `POST /api/system/services/{name}/restart` + per-service button on System Health page |
| 7 | schtask enable/disable | `powershell Disable-ScheduledTask` | ❌ | ❌ | MED | Add `PUT /api/system/schtasks/{name}` toggle + audit |
| 8 | `pull_tushare` force | `scripts/pull_tushare.py` | ❌ | ❌ | LOW | Add `POST /api/data/pull/tushare` + date picker UI |
| 9 | `pull_baostock` force | `scripts/pull_baostock_minute.py` | ❌ | ❌ | LOW | Same pattern as #8 |
| 10 | `factor_lifecycle` force | Friday 19:00 Beat / manual python | ❌ | ❌ | LOW | Add `POST /api/factors/lifecycle/run` + button |
| 11 | `emergency_close_all` | `scripts/emergency_close_all_positions.py` | ✅ (`/api/execution/emergency-liquidate`) | ✅ (`execution.ts:246`) | **CRIT** | Already wired — verify 三锁 present; add typed "CONFIRM-LIQUIDATE-{date}" phrase |
| 12 | `cancelAllOrders` | already API+UI | ✅ | ✅ | MED | OK |
| 13 | `pauseTrading`/`resumeTrading` | already API+UI | ✅ | ✅ | MED | OK; add reason field (audit) |
| 14 | `fixDriftPreview`/`Execute` | already API+UI | ✅ | ✅ | MED | OK |
| 15 | `triggerRebalance` | already API+UI | ✅ | ✅ | MED | OK |
| 16 | Risk threshold yaml edit | manual yaml edit + Servy restart | partial (`PUT /api/execution/alert-config`) | ❌ | MED | Wire UI form to existing endpoint + diff preview |
| 17 | L4 STAGED confirm | DingTalk reply / manual SQL | ✅ (`/api/risk/l4-approve/{id}`) | ❌ | HIGH | Add Risk Monitor approve/reject buttons (P1-49) |
| 18 | L4 force-reset | `/api/risk/force-reset/{id}` | ✅ | ❌ | HIGH | Add UI with 双锁 |
| 19 | L4 recovery | `/api/risk/l4-recovery/{id}` | ✅ | ❌ | HIGH | Add UI |
| 20 | Beat schedule view | `celery inspect` CLI | ❌ | ❌ | LOW | Add `GET /api/system/celery/schedule` + table |
| 21 | LL sediment | manual append `LESSONS_LEARNED.md` | ❌ | ❌ | LOW | Add `POST /api/audit/lessons` + form (auto-PR optional) |
| 22 | ADR creation | manual write | ❌ | ❌ | LOW | Add `POST /api/audit/adrs` + form |
| 23 | DB backup trigger | `scripts/pg_backup.py` | ❌ | ❌ | LOW | Add `POST /api/system/backup/run` |
| 24 | Approve L4 (queue) | `/api/approval/queue/{id}/approve` | ✅ | partial (`pipeline.ts:122` for pipeline, not risk-approval) | HIGH | Verify Risk Monitor uses approval queue |
| 25 | Reject L4 | `/api/approval/queue/{id}/reject` | ✅ | partial | HIGH | Same as #24 |
| 26 | Hold L4 | `/api/approval/queue/{id}/hold` | ✅ | partial | MED | Same |
| 27 | Mining task cancel | `/api/mining/tasks/{id}/cancel` | ✅ | ✅ | LOW | OK |
| 28 | Backtest cancel | `/api/backtest/{id}/cancel` | ✅ | ✅ | LOW | OK |
| 29 | Pipeline trigger | `/api/pipeline/trigger` | ✅ | ✅ | LOW | OK |
| 30 | Factor archive | `/api/factors/{name}/archive` | ✅ | ✅ | LOW | OK |
| 31 | Reports generate | `/api/reports/generate` | ✅ | ✅ | LOW | OK |
| 32 | News ingest force | `/api/news/ingest*` | ✅ | ❌ | LOW | Add News page with manual pull button |

### §41.1 Coverage Summary
- **14/32 (44%)** have both API + UI
- **5/32** have API but no UI (L4 ops, news, version rollback)
- **13/32 (41%) have NO API at all** (most critical ops)
- **Section XI = need ~13 new endpoints + 18 new UI buttons**

### §41.2 Heuristic #18 Alternative Recommendation
- Instead of full UI for 13 missing ops, build **single Control Center page** (operator-only) with command palette (Cmd+K) running ~30 commands as prompts with confirmations
- Faster to ship than 12 dedicated pages
- See `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` Phase H roadmap

---

## §42 Trader Daily Journey Map

| Time (SH) | Action | UI Today | Coverage % | Gap |
|---|---|---|---|---|
| 08:50 | QMT preflight, schtask check | ❌ | 0% | Need preflight panel: QMT status / schtask enabled / Beat alive / DB fresh |
| 09:15 | Pre-market signal review | partial (Dashboard NAV) | 30% | Show today's pending signal preview |
| 09:30 | Market open | Dashboard polling | 50% | Need live tick view (SSE) (P0-15) |
| 09:31 | Execute phase | schtask only | 0% | Confirm modal w/ signal recap + 三锁 (P0-13) |
| 09:30-15:00 | Monitor | Dashboard | 70% | Add live order fill feed, P&L tick |
| 15:00 | Close, daily summary | partial | 40% | One-page summary auto-generated |
| 15:40 | Reconciliation | ❌ | 0% | Recon diff view (QMT vs DB) |
| 17:35 | PT audit | ❌ | 0% | PT audit report viewer |
| Evening | LL sediment / decisions | manual file edit | 0% | LL form + ADR form |

**Overall operator UI coverage: ~22%**. Section XI inversion target: 90%+.

---

## §43 Researcher / Auditor Journey Map

### §43.1 Factor Onboarding (Proposal → IC → Profile → Gate → Backtest → Onboard)
- Proposal: ❌ no UI (memo only)
- IC: ✅ Factor Explorer
- Profile: ✅ Factor Evaluation page
- Gate G1-G8 check: ❌ no UI display of which gates passed
- Backtest paired bootstrap: partial (`BacktestResults.tsx`)
- Onboard to PT config: ❌ no UI (manual yaml edit)

### §43.2 Incident Response (LL-183 类)
- View `risk_event_log`: ❌
- Cancel orders mid-flight: ✅ (`cancelAllOrders`)
- Pause trading: ✅
- Audit trail: ❌
- Post-mortem LL write: ❌

**Researcher UI coverage: ~45%**.
**Auditor UI coverage: ~10%**.

---

## §44 Control Plane Safety UX

### §44.1 LL-183 Lesson — Frontend Ops Must NEVER Silent-NOT-GATE

### §44.2 Recommendations

#### Confirmation Tiers:
- **LOW** (cancel order): 1-click + toast undo (10s)
- **MED** (force pull, factor archive): modal + click confirm
- **HIGH** (L4 approve, drift fix): modal + typed reason + admin token re-enter
- **CRIT** (live execute, env_flip, emergency_close): **三锁** = (a) env var match check (b) typed exact phrase like `EXECUTE-PAPER-20260518` (c) 5s cooldown timer

#### Immutable Audit Log
- Every UI action → `audit_log` table + DingTalk push
- No DELETE on log

#### Undo Path
- Most non-CRIT ops support undo within 30s (queue, don't fire immediately)

#### Banner State
- Always-visible banner: `[PAPER] LIVE_TRADING_DISABLED=true` red/green per env (anti LL-183)
- P0-23 master

#### Lockout on Alert
- If any L4+ active → critical buttons auto-disabled with explanation

### §44.3 Heuristic #18 Alternative
- Full RBAC overkill for single user
- Use **2 admin tokens** (`researcher_token`, `operator_token`)
- operator_token required for CRIT ops, stored separately
- OR Windows Hello / TOTP / hardware key for CRIT

---

## §45 AI-Assisted Frontend Operations

### §45.1 Feasible LLM Ops
- ✅ "Cancel all orders for 601398" → tool call `cancelOrder` with filter — feasible, safe (already gated by admin token)
- ✅ "Why is signal weak today?" → call signal explainer → return text
- ✅ "Show factor IC trend for bp_ratio last 60d" → call factor API
- ✅ "Summarize today's PT" → aggregate dashboard data

### §45.2 Boundary
- ❌ **NEVER LLM for CRIT ops** (env_flip, emergency_close, execute trigger). Even if user says "yes" — risk of prompt injection / hallucinated number / OOD action.
- ⚠️ HIGH ops: LLM may compose, user must manually click confirm in 三锁 modal
- ✅ MED/LOW: LLM may execute directly with toast notification

### §45.3 Implementation (Phase 5+)
- `POST /api/agent/chat` streams Claude API
- Tool schema = subset of API endpoints filtered by risk tier
- Tool calls logged to `agent_action_log` immutable
- Cost cap (V3 §16.2) enforced server-side

### §45.4 Heuristic #18 Alternative
- Skip AI ops entirely (single user can type)
- Defer to Phase 6+ post-PT-restart

---

## §46 Cross-Reference

- Frontend UI design: `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md`
- Frontend Design Spec (claude.ai/design feedable): `V3_AUDIT_FRONTEND_DESIGN_SPEC.md`
- Designer agent mockup: `V3_AUDIT_FRONTEND_DESIGN_PROPOSAL.md` + `frontend_mockups/{A,B,C}.html`

---

**End Section XI.**
