# CC Actions Remaining For User — Comprehensive Sediment (2026-05-19 Session 58 round-3)

> **Purpose**: ISSUES_PENDING_REGISTRY 41 items + Session 57+1/58 surfaced items 中**剩余 strict user touchpoint** (X10 enforce, CC 不能 auto-push). 本 doc 是 user-action-required SSOT, 替代多处散落 mentions.
>
> **Generated**: Session 58 round-3 autonomous batch closure end, after exhausting CC-autonomous backlog (10 commits since +15,433 surface).
>
> **Status as of write**: Session 58 round-2 commit `be00471` (P4+P7). Subsequent: A.5 ADR-084 + this doc.

---

## 1. Critical Path (immediate decision needed)

### 1.1 PT 重启 timeline 决议

**Status**: .env state has been `EXECUTION_MODE=live` + `LIVE_TRADING_DISABLED=false` for 3+ weeks (since 5-15~5-17 cutover). All 4 Servy services running with broker-enabled config. BUT **0 broker calls since 4-29** (trade_log真值 verified).

**Question**: When do you want signal Beat tasks to actually fire and generate trades?

**Pre-requisites visible from Session 58 round-1 forensic**:
- ✅ env=live + broker enabled (already done)
- ✅ DingTalk alerts wired (manual_verify 5-18 18:55)
- ✅ Calendar gate wired (Session 57+1 round-6 A5/C4/H4)
- ⏳ paper-mode 5d dry-run NOT executed (留 SHUTDOWN_NOTICE §9 prerequisite)
- ⏳ COOKIE_SECURE_FLAG migration (optional, separate decision)

**Action needed from you**:
- Confirm 5d dry-run plan OR skip with explicit ADR
- Trigger signal Beat after green light (e.g. enable QuantMind_DailySignal schtask)

---

### 1.2 COOKIE_SECURE_FLAG migration (HTTPS reverse proxy)

**Status**: Round-2 startup guard refined to advisory log.warning for localhost OR log.error HIGH for external bind (current API_HOST=0.0.0.0 = external bind → HIGH severity). admin_token cookie travels cleartext.

**Question**: HTTPS migration roadmap?

**Options**:
- A) Set up nginx reverse proxy with self-signed cert + COOKIE_SECURE_FLAG=true
- B) Bind API_HOST=127.0.0.1 (localhost-only) + accept advisory warning
- C) Defer until production hosting decision

**Action needed**: pick option + .env edit.

---

### 1.3 S2 PG password .env edit

**Status**: backend/.env has `DATABASE_URL=postgresql+asyncpg://xin:<password>@localhost:5432/quantmind_v2`. Audit Subagent G flagged password=`quantmind` plaintext.

**Question**: Rotate to stronger password + verify DB user permission scope?

**Action needed**:
1. Generate strong password (e.g. `pwgen 32`)
2. PG: `ALTER USER xin WITH PASSWORD '<new>';`
3. Edit `backend/.env` DATABASE_URL
4. Restart all 4 Servy services
5. Smoke verify health check 200

**Risk**: 0 if executed correctly (rollback = restore .env backup), HIGH if forgot to restart services or rolled back partial.

---

## 2. Strategy Research (Phase J — multi-week)

### 2.1 B1: WF Sharpe Heterogeneity Audit (Phase J.4)

**Issue**: Sharpe 异质性 2.4× across periods:
- WF (Walk-Forward OOS): **0.8659** (2026-04-12 PASS)
- 5yr backtest: **0.6095**
- 12yr backtest: **0.3594**

**Question**: Is WF Sharpe overfitting OR truly best representation of forward expected return?

**Action needed**:
- Run paired bootstrap p-value across the 3 periods
- Identify regime shifts explaining the gap
- ~2 weeks research effort

---

### 2.2 B2 / C1: Phase 3B/3D/3E NO-GO → backup strategy (Phase J.3)

**Issue**: Single Alpha strategy (CORE3+dv_ttm equal-weight + SN b=0.50) = 100% portfolio. SPOF risk.

**Phase J.3 候选**:
- 因子 diversification (cross-region: forex / commodities)
- ML synthesis re-attempt with different methodology
- Event-driven supplement (PEAD, earnings drift) per ADR-002

**Action needed**: 4-8 weeks research + capacity allocation decision.

---

### 2.3 B3: Survivorship bias audit

**Issue**: 5yr / 12yr backtest universe 是否含历史退市 / ST / 暂停 stocks?

**Action needed**: SQL audit on backtest universe vs historical universe真值 (含退市). 若 bias confirmed, redo backtest with proper survivorship handling.

---

### 2.4 B4 / P6: Slippage 季度复核 (铁律 18)

**Issue**: H0 < 5bps 季度复核, **last execution time unknown**.

**Action needed**:
- Check `docs/audit/*` or commit log for last slippage_model verification
- If > 90 days: re-run slippage estimate via three-factor model (spread + impact + overnight_gap)
- Compare to铁律 18 threshold

---

### 2.5 D2: sim-to-real gap verify

**Issue**: WF fold doesn't cover 4-29 incident (清仓 day). sim-to-real gap unverified for crisis periods.

**Action needed**: Use 4-29 as OOS fold OR build crisis-scenario synthetic替代 (per V3 §15.6).

---

### 2.6 C3: LL-182 QMT 5-axis long-run verify

**Issue**: LL-182 fix (broker_qmt.py 5-axis stability) applied 5-18, verified in Phase B regression, but **真 long-run production verify** requires PT restart.

**Action needed**: Once PT restarts (1.1 decision), monitor first 5-10 days for 5-axis stability indicators.

---

## 3. Configuration Audits

### 3.1 L6: PT_START_DATE .env audit

**Issue**: Calendar module's `parse_pt_start_date()` defaults to `2026-03-15`. Backup-chain forensic suggests actual PT start was after 4-20 cutover (Session 20).

**Action needed**:
- Verify .env has `PT_START_DATE=` set (currently uses default)
- If unset OR wrong: set explicit `PT_START_DATE=<actual>` in backend/.env
- Affects PT day counter displayed in Dashboard ("PT Day X/Y")

---

### 3.2 P1: BGE-M3 embedding cron (GPU decision)

**Issue**: RAG memory backfill (F2) inserted 21 rows with `embedding=NULL`. BGE-M3 1024-dim embedding generation requires GPU (RTX 5070 12GB).

**Action needed**:
- Decision: dedicate GPU slot for BGE-M3 cron? (e.g. nightly 02:00, 5-10 min)
- Implement `scripts/rag_embedding_generate.py --batch 100`
- Schedule schtask similar to QuantMind_VacuumAnalyze

---

## 4. Plan v8 Open Questions §9.3 (14 items)

ISSUES_PENDING_REGISTRY §10 L12 reference: 14 pending Plan v8 §9.3 user 决议.

These are ALL strict user touchpoint — examples (full list in Plan v8 `quizzical-snacking-fox.md`):
- Frontend stack decision (React 18 retain vs SvelteKit/Vue 3/Solid?)
- Frontend hosting (local dev server vs Servy persistent?)
- Mobile support level
- Auth model upgrade (ADMIN_TOKEN → OAuth/RBAC/multi-user?)
- Real-time updates choice (now superseded by ADR-084 proposed Hybrid)
- AI-assisted ops boundary
- ... (full list in Plan v8 §9.3)

**Action needed**: Item-by-item 决议 OR collective ADR.

---

## 5. Surfaced From Session 57+1 / 58 (NEW)

### 5.1 Round-2 startup guard true production fix

**Status**: Advisory mode now (log.warning localhost / log.error external). 真 production fix = COOKIE_SECURE_FLAG=true via HTTPS.

**Tied to**: 1.2 above.

### 5.2 LL-188 step 0 cold-start enforce mechanism

**Status**: SOP step 0 written in `docs/runbook/retroactive_review.md` but **no automated enforcement** — CC's discipline only.

**Possible enforcement**:
- Pre-commit hook check that PR-related commits 出现红线 claim must cite .env file mtime
- Session start ritual auto-run env reality check + diff vs handoff claim

**Action needed**: decide if automation worth the effort, OR rely on SOP discipline.

### 5.3 Multi-worker rate-limit Redis upgrade

**Status**: S3 in-memory bucket per-worker. If uvicorn 2-worker → effective limit = 2 × max_per_min.

**Action needed**: If scaling beyond 1 worker, upgrade to Redis-backed bucket.

### 5.4 Audit middleware body capture

**Status**: P7 captures method + path + query + status. Body parsing stub `{}` for binary/stream bodies.

**Action needed**: Enable body capture via `request._receive` monkey-patch if compliance要求 full body audit.

---

## 6. Defer / Low-Priority (autonomous but ROI low)

These are NOT user touchpoint, just deferred:

- **L4 LLM_IMPORT_POLICY marker** fine-grained expansion (11 unmarked but sanctioned-via-service callers, PR #226 baseline adequate)
- **A1 双轨样式** migration (414 inline / 116 Tailwind, ~50h tech debt)
- **L10/L11 Dashboard duplication** — verdict from Session 58: **AUDIT OVER-CLAIM**. 3 pages serve distinct purposes (Dashboard=overview / DashboardAstock=A股 drill / Portfolio=detail). Already share data hooks (`usePortfolio`, `fetchSummary`, `fetchNAVSeries`). UI differentiation is intentional.
- **A3 full 4→1** notification consolidation (Context + Zustand merge, ~4-6h refactor per notificationStore.ts docstring deferred)

---

## 7. Closed in Session 57+1 + 58 (FYI sediment)

For completeness — these items HAVE been resolved by CC autonomous work:

| Item | Status | Closing commit |
|---|---|---|
| S1 admin_token httpOnly cookie | ✅ DONE | `ae4b70d` + retroactive `0e26ac8` + `5a58ef0` |
| F1 LLM cost forward-only | ✅ DONE | `23ebea5` |
| F3 VACUUM schtask register | ✅ DONE | `15a7d93` + live register Session 58 (NextRun 5-24 03:00) |
| A4 AgentConfig PUT no-op | ✅ DONE | `506a2cf` + `e5edae5` + atomic rollback round-2 |
| A5/C4/H4 Calendar wire | ✅ DONE | `df79ec4` (4 Beat tasks gated) |
| D1 DB 4-28 stale | ✅ DONE | `b644ad1` |
| G1 8 DEV docs sync | ✅ DONE | `be0a6de` |
| H1 silent UI lie | ✅ DONE | `b644ad1` + round-2 |
| L7 v4-flash/pro alias | ✅ DONE | `b644ad1` |
| L8 Memory archive 754→320KB | ✅ DONE | `15a7d93` + Session 58 prepends |
| S3 LLM rate-limit | ✅ NEW | `9ecd588` |
| C2 silent failure audit | ✅ DONE | `9ecd588` (4 `# silent_ok:` annotations) |
| L1 bundle splitting | ✅ PRE-DONE | vite.config.ts manualChunks |
| L2 VITE_API_BASE_URL runtime | ✅ DONE | `9ecd588` (window.__APP_CONFIG__) |
| L3 useWebSocket lifecycle | ✅ DONE | `9ecd588` (callback refs + polling) |
| A3 notification partial 4→2 | ⚠️ PARTIAL | `9ecd588` (ToastFromStore) |
| P4 SSE endpoint scaffold | ✅ NEW | `be00471` |
| P7 audit middleware | ✅ NEW | `be00471` |
| P2 prompt_history | ✅ DONE | `506a2cf` |
| P3 httpOnly cookie | ✅ DONE | `ae4b70d` (S1 same) |
| P8 12 dead tables | ✅ DONE | ADR-083 KEEP |
| P9 LLM cache-hit fallback | ✅ DONE | `6d51a77` |
| H3 AssistPanel dark launch | ✅ INTENTIONAL | startup guard added |
| L5 alias drift | ✅ INTENTIONAL | (LEGACY) labels sustained |
| L10/L11 Dashboard duplication | ✅ INTENTIONAL | 3 pages distinct purpose, audit over-claim |
| LL-188 sediment drift | ✅ DOCUMENTED | `c01817b` + `4d37df0` + SOP step 0 |
| ADR-084 real-time architecture | ✅ PROPOSED | Session 58 round-3 (留 user approve) |

---

## 8. Summary

**ISSUES_PENDING_REGISTRY 41 items + 5 NEW Session 57+1/58 surfaced = 46 total**:
- ✅ **Closed (autonomous CC)**: ~27 items (~59%)
- ⚠️ **PARTIAL (深化 possible)**: ~4 items (~9%)
- ⏸ **User touchpoint** (THIS DOC): ~15 items (~33%)

**Critical path for user**: §1.1 PT 重启 timeline + §1.2 HTTPS migration + §1.3 PG password rotate + §4 Plan v8 §9.3 14 items.

**Strategy research backlog** (multi-week, §2): B1-B4 + C1 + C3 + D2 + P6.

**Configuration audits** (light, §3): L6 + P1.

**Surfaced NEW** (§5): 4 items mostly tied to §1 critical path decisions.

---

**End of CC_ACTIONS_FOR_USER doc. 沉淀点 — 任何 future session "之前问题都解决了吗" 直 cite 本 doc + git log 验证.**
