# Frontend Design v3 — W7-W15 Sediment Plan (2026-05-25)

> **Status**: Sediment-only reference doc. NOT for immediate execution.
> **Trigger gate**: X1-X5 boundary (multi-week research / Q3-Q4-by-design / user-touchpoint / 50h frontend remain) per session_61_design_doc_loop_handoff.
> **Source**: V3_AUDIT_FRONTEND_DESIGN_v3.md + STATUS_REPORT_2026_05_19_frontend_v3_phase_h_w1_w6.md + LL-187 sediment.

---

## §1 W1-W6 实施 inventory (DONE, ✅ baseline)

5 NEW components shipped (verified `frontend/src/components/`):

| Component | Path | LOC | Closure |
|---|---|---|---|
| EnvStateBanner | `safety/EnvStateBanner.tsx` | ~80 | Finding #1 P0 ✅ |
| ShutdownBanner | `safety/ShutdownBanner.tsx` | ~60 | Finding #15 P1 ✅ |
| SafetyControlPanel | `safety/SafetyControlPanel.tsx` | ~250 | Finding #2 P0 ✅ |
| ConfirmModal (4-tier) | `ui/ConfirmModal.tsx` | ~150 | Finding #8 P2 (2/3) ✅ |
| AssistPanel | `ai/AssistPanel.tsx` | ~300 | Finding #4 P1 ✅ |

Cumulative: 11 commits / 27 files / +1925/-756 / **10/15 v3 findings closed** / axios SSOT 14→0 / dead code -370 LOC.

---

## §2 W7-W15 待实施 list

W7-W15 = 9 residual work-blocks reframed from v3 W3+W5 defer + Phase I + post-Plan-v8.

### W7 — AgentConfig prompt 版本 / diff / rollback UI (~10h)
- **Scope**: `pages/AgentConfig.tsx` (289 → ~380 lines). 添加 prompt 历史版本 list + diff viewer + rollback HIGH-tier ConfirmModal.
- **Files**: `pages/AgentConfig.tsx` (edit) + `api/agent.ts` (add `listPromptVersions / getPromptDiff / rollbackPrompt`).
- **Backend dep**: NEW endpoints — `GET /api/agent/prompts/{role}/versions`, `GET /api/agent/prompts/{role}/diff?from=&to=`, `POST /api/agent/prompts/{role}/rollback` (HIGH-tier).

### W8 — SystemSettings Servy + schtask UI (~14h)
- **Scope**: `pages/SystemSettings.tsx` (648 → ~750 lines). Servy 4 服务 restart 按钮 (CRIT-tier) + 5+ schtask enable/disable (HIGH-tier) + prompt-eval skill trigger.
- **Files**: `pages/SystemSettings.tsx` (edit).
- **Backend dep**: `POST /api/system/services/{name}/restart` (CRIT) / `PUT /api/system/schtasks/{name}` (HIGH).

### W9 — PMS history wire + 归并评估 (~6h)
- **Scope**: `pages/PMS.tsx` (227 lines). 评估归并到 RiskManagement 紧急控制 tab OR 保留独立页. Wire 历史触发 list.
- **Files**: `pages/PMS.tsx` (edit OR delete + RiskManagement extend).
- **Backend dep**: `GET /api/pms/history` (exists check).

### W10 — 双轨样式 P2 pages 批量 migrate (~30h)
- **Scope**: 414 inline `style={{...}}` + 116 `text-slate-*` → 全 Tailwind + GlassCard. 影响 ~15 P2 pages.
- **Files**: 全 `pages/*.tsx` 扫一遍 + `components/shared/*` 复用提升.
- **Backend dep**: 无.

### W11 — 三套 real-time tiered consolidation (~16h)
- **Scope**: 7 处 raw `setInterval` → react-query refetchInterval / SSE. socket.io-client → EventSource SSE.
- **Files**: `pages/Dashboard/`, `pages/Portfolio.tsx`, `pages/Execution/`, `pages/PipelineConsole.tsx`, `hooks/use*`.
- **Backend dep**: NEW SSE endpoints — `/api/streams/portfolio` / `/api/streams/risk` / `/api/streams/market`.

### W12 — admin token localStorage → httpOnly cookie (~6h)
- **Scope**: 安全加固 per audit P0-22. 当前 admin token 在 localStorage (XSS 暴露).
- **Files**: `lib/apiClient.ts` (改 cookie 模式) + `pages/Execution/AdminTokenModal.tsx` (改 set-cookie 路径).
- **Backend dep**: `POST /api/auth/admin-token` (Set-Cookie HttpOnly Secure SameSite=Strict).

### W13 — 4 entry-points AI Assist 真后端 wire (~12h)
- **Scope**: 当前 `/api/agent/chat` 是 stub. wire 真 LiteLLM (F-S7-001 fix 已 done, AI_ASSIST_ENABLED unblock). Per-domain context injection + tool whitelist enforce.
- **Files**: `components/ai/AssistPanel.tsx` (edit) + `api/agent.ts` (real streaming).
- **Backend dep**: `/api/agent/chat` streaming 真值化 (现 stub) + `/api/agent/chat/tools` whitelist endpoint.

### W14 — PipelineConsole `window.prompt` 残修 + EMPTY_STATUS 删除 (~4h)
- **Scope**: `PipelineConsole.tsx:252` `window.prompt` → ConfirmModal HIGH tier (Finding #8 残 1/3). 删 `EMPTY_STATUS` mock (line 49-59) — fail-loud instead.
- **Files**: `pages/PipelineConsole.tsx` (edit).
- **Backend dep**: 无 (前端纯化).

### W15 — Hardcoded UI 真值 wire (cron / Sprint badge / MetricCard 阈值) (~8h)
- **Scope**: Finding #7 P2 (cron + Sprint badge hardcoded) + Finding #12 PMS 三层硬编码 + FactorEvaluation MetricCard 阈值 (line 117-119).
- **Files**: `pages/SystemSettings.tsx`, `pages/FactorEvaluation.tsx`, `pages/Dashboard/index.tsx`.
- **Backend dep**: `GET /api/system/calendar-state` + `GET /api/system/sprint-state` + `GET /api/config/thresholds`.

---

## §3 Backend dependency summary

| W | NEW endpoint(s) | Tier |
|---|---|---|
| W7 | 3 agent prompt version endpoints | HIGH |
| W8 | Servy restart / schtask toggle | CRIT/HIGH |
| W9 | `/api/pms/history` (verify) | LOW |
| W10 | 无 | — |
| W11 | 3 SSE streams | LOW |
| W12 | admin-token cookie endpoint | HIGH |
| W13 | real LLM streaming + tools whitelist | MED |
| W14 | 无 | — |
| W15 | 3 config-state read endpoints | LOW |

**Total NEW backend endpoints**: ~11 (vs v3 §7 originally listed 15 — 4 covered by `/api/agent/chat` generic).

---

## §4 50h estimate breakdown (per W)

| W | Effort | Solo-low-risk? | Backend coord? |
|---|---|---|---|
| W7 | 10h | partial | YES (3 endpoints) |
| W8 | 14h | NO | YES (CRIT/HIGH) |
| W9 | 6h | YES | NO (verify only) |
| W10 | 30h | YES | NO |
| W11 | 16h | partial | YES (3 SSE) |
| W12 | 6h | NO | YES (security) |
| W13 | 12h | partial | YES (LLM gate) |
| W14 | 4h | YES | NO |
| W15 | 8h | YES | YES (3 read endpoints, low risk) |

**Sum**: 106h total. Per session_61 handoff "50h frontend remain" = **W9 + W10 + W14 + W15 subset = ~48h solo-front-only** (closest match). Full W7-W15 (106h) requires backend coord.

---

## §5 Recommendation

### Solo low-risk (do first when triggered, ~48h, 1 dev × ~2 wk):
- **W14** (~4h) — pure frontend `window.prompt` removal + EMPTY_STATUS fail-loud. **Start here**.
- **W9** (~6h) — wire existing `/pms/history` OR evaluate-and-delete. Low backend risk.
- **W15** (~8h) — 3 hardcoded UI fields → backend reads. Read-only endpoints = low risk.
- **W10** (~30h) — 双轨样式 batch migrate. 0 backend, mostly mechanical Tailwind + GlassCard sweep.

### Need backend coord (defer until backend sprint pairs, ~58h):
- **W7** (~10h) — prompt versioning needs new agent prompt schema + diff infra.
- **W8** (~14h) — Servy restart / schtask toggle = CRIT-tier security-sensitive backend.
- **W11** (~16h) — 3 SSE endpoints + EventSource client migration coordinated.
- **W12** (~6h) — auth security refactor (cookie semantics + CORS + CSRF). Single backend slot.
- **W13** (~12h) — real LLM wire requires F-S7-001 deployed + AI_ASSIST_ENABLED user 决议 + cost budget.

### Trigger gate (per session_61 X1-X5 boundary):
- 不主动启动 W7-W15. Wait for explicit user 决议:
  - (a) "do W10 双轨 sweep" (50h batch) — solo-safe
  - (b) "do W14+W9+W15" (~18h quick wins) — solo + low backend
  - (c) "do W7-W13" — need backend sprint pairing
- 反 X10 (AI 自动驾驶 forward-progress offer). 任 W 启动须显式 user trigger.

---

## §6 Cite source (4-element)

| Cite | Path | Line# | Section | Verify timestamp |
|---|---|---|---|---|
| LL-187 sediment + Phase H scope | `CLAUDE.md` | 504, 520, 529 | §当前进度 / §重要里程碑 | 2026-05-25 (this session grep) |
| v3 W3+W5 defer + 5 findings residual | `docs/audit/V3_AUDIT_FRONTEND_DESIGN_v3.md` | 321-353 | §5 + §6 | 2026-05-25 fresh read |
| W1-W6 closure 10/15 + axios + dead code | `docs/audit/STATUS_REPORT_2026_05_19_frontend_v3_phase_h_w1_w6.md` | 1-227 | §1-§9 | 2026-05-25 fresh read |
| 50h frontend remain + X1-X5 boundary | `memory/MEMORY.md` "session_61_design_doc_loop_handoff" entry | — | (per system context) | 2026-05-25 (this session read) |

5 NEW components verified existence: `frontend/src/components/{safety/EnvStateBanner.tsx, safety/ShutdownBanner.tsx, safety/SafetyControlPanel.tsx, ui/ConfirmModal.tsx, ai/AssistPanel.tsx}` (2026-05-25 Glob).

---

**End W7-W15 plan.** Sediment-only. NOT for immediate execution. Awaits user trigger per X1-X5 boundary.
