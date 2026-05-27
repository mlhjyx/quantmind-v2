# STATUS REPORT — iter 239 — DEV Doc Rot Audit (G1 backlog closure attempt)

**Date:** 2026-05-27
**Iter:** 239 (post-compaction continuous L4+R loop, 56-iter cumulative)
**Trigger:** ISSUES_PENDING_REGISTRY G1 — "DEV_FRONTEND_UI.md 已 65% sync (Phase H), 其他 8 DEV docs 漂移程度未审计 (铁律 22)". User "继续" directive after iter 238 sediment.
**Status:** 8/8 DEV docs audited (DEV_FRONTEND_UI excluded per ISSUES_PENDING_REGISTRY note). 15 broken path refs surfaced. 10 fixed autonomously in this iter; 5 deferred (expected Layer 3-4 NOT-IMPL per ADR-028).
**Scope:** read-only audit + doc-truth fixes. **0 code mutation. 0 broker / .env / yaml / DDL change.**

---

## 1. Audit method

**Tooling:** Python script extracting all `(backend|scripts|frontend|configs)[\w/.-]*\.(py|sql|yaml|yml|ts|tsx)` regex matches from each DEV doc, then `Path(p).exists()` check.

**Scope:** 8 DEV docs (DEV_BACKEND / DEV_FACTOR_MINING / DEV_PAPER_BROKER / DEV_BACKTEST_ENGINE / DEV_PARAM_CONFIG / DEV_AI_EVOLUTION / DEV_SCHEDULER / DEV_NOTIFICATIONS). DEV_FRONTEND_UI excluded (already 65% sync per Phase H audit).

**Verdict tiers:**
- **CLEAN** — 0 broken refs, no action.
- **PATH-SHIFT** — actual file exists at canonical relocated path (e.g. namespace migration). Fix in-place.
- **ASPIRATIONAL** — never implemented (plan-only content). Annotate as such.
- **DEPRECATED-PLAN** — phase NO-GO'd per research findings. Annotate with banner.
- **EXPECTED-UNIMPL** — Layer 3-4 Q3-Q4 trigger gate, expected absent per ADR-028. No action (would create false noise).

---

## 2. Findings by doc

| Doc | Last mod | Total refs | Broken | Verdict | Iter 239 action |
|---|---|---|---|---|---|
| DEV_FACTOR_MINING.md | 2026-05-20 | 2 | 0 | CLEAN | none |
| DEV_PAPER_BROKER.md | 2026-05-20 | 9 | 0 | CLEAN | none |
| DEV_SCHEDULER.md | 2026-05-25 | 5 | 0 | CLEAN | none |
| DEV_NOTIFICATIONS.md | 2026-05-26 | 4 | 0 | CLEAN | none |
| **DEV_BACKEND.md** | 2026-05-20 | 12 | 7 | PATH-SHIFT + DEPRECATED-PLAN | 5 path fixes + 2 deprecation banners |
| **DEV_BACKTEST_ENGINE.md** | 2026-05-24 | 19 | 2 | PATH-SHIFT + ASPIRATIONAL | 1 path fix + 1 banner |
| **DEV_PARAM_CONFIG.md** | 2026-05-25 | 4 | 1 | PATH-SHIFT | 1 namespace fix |
| DEV_AI_EVOLUTION.md | 2026-05-25 | 18 | 5 | EXPECTED-UNIMPL | none (per ADR-028) |

**Aggregate:** 73 path refs total / 15 broken (20.5%) / **10 autonomously fixed (66.7% of broken)** / 5 deferred (expected unimpl).

---

## 3. Detail: DEV_BACKEND.md fixes (largest scope)

### 3.1 Path-shift fixes (5 mechanical)

| Line | Old path | New path | Reason |
|---|---|---|---|
| L412 | `backend/main.py` | `backend/app/main.py` | namespace migration |
| L463 | `backend/config.py` | `backend/app/config.py` | namespace migration |
| L510 | `backend/database.py` | `backend/app/db.py` | rename + namespace |
| L1040 | `backend/main.py 中间件` | `backend/app/main.py 中间件` | namespace |
| L1079 | `backend/websocket/manager.py` | `backend/app/websocket/manager.py` | namespace |

### 3.2 DEPRECATED-PLAN banner: Section 12.3 ML 模型架构

**Drift:** doc claims `backend/engines/ml_models.py` + `backend/services/ml_service.py` are the canonical ML封装. **Reality:** Phase 3D ML Synthesis verified NO-GO (4 实验全 FAIL, CORE3+dv_ttm = 等权 alpha 上限 per 5 次独立验证). Files **从未实现**.

**Fix:** prepended deprecation banner pointing readers to current ML/AI route = DEV_AI_EVOLUTION.md V2.1 (Layer 1=95% / Layer 2=60% / Layer 3-4=0% Q3-Q4 trigger per ADR-028). Inline annotations mark code block paths as `(NOT IMPLEMENTED)`.

### 3.3 DEPRECATED-PLAN banner: Section 八 日志框架

**Drift:** doc shows `loguru`-based `setup_logging()` at `backend/utils/logging.py`. **Reality:** actual logging uses **structlog JSON** at `backend/app/logging_config.py` (Sprint 1.15 Task 4, R6 §7 处理器链, RotatingFileHandler 10MB×7 轮转). `backend/utils/logging.py` **从未存在**.

**Fix:** prepended deprecation banner with pointer to real implementation. Code block path annotated `(PLAN ONLY — 实际不存在; 真实路径 backend/app/logging_config.py)`.

---

## 4. Detail: DEV_BACKTEST_ENGINE.md fixes

### 4.1 Path-shift (L1430)

`scripts/walk_forward.py` → `backend/engines/walk_forward.py`. Early plan put it under `scripts/`, actual implementation landed in `backend/engines/`. Inline note added.

### 4.2 ASPIRATIONAL banner: Section 4.12.3 Celery 异步回测

**Drift:** doc shows `@celery_app.task` template at `backend/tasks/astock_tasks.py`. **Reality:** path doesn't exist. Current回测走同步 CLI (`scripts/run_backtest.py --config configs/pt_live.yaml`). Celery 异步回测属 Wave 5+ 范畴 per QPB v1.17.

**Fix:** prepended aspirational banner + inline annotation. Also flagged that example code imports use stale `backend.services.*` / `backend.websocket.*` namespace (real = `backend.app.services.*` / `backend.app.websocket.*`).

---

## 5. Detail: DEV_PARAM_CONFIG.md fix

### 5.1 Namespace migration (L27)

`backend/platform/config/auditor.py:PlatformConfigAuditor._TRIPLE_SOURCE_FIELDS` → `backend/qm_platform/config/auditor.py:PlatformConfigAuditor._TRIPLE_SOURCE_FIELDS`.

Verified actual file exists: `backend/qm_platform/config/auditor.py:56` defines `_TRIPLE_SOURCE_FIELDS` (line number ~L56 vs doc claim L57-64, 1-line drift acceptable). Inline iter 239 path-fix note added.

---

## 6. Detail: DEV_AI_EVOLUTION.md — EXPECTED-UNIMPL (no action)

5 missing paths:
- `backend/app/services/ai_loop_orchestrator.py`
- `backend/app/tasks/ai_loop_tasks.py`
- `backend/qm_platform/llm/_internal/litellm_router.py`
- `configs/ai_loop.yaml`
- `scripts/run_rolling_wf.py`

**Rationale:** per CLAUDE.md "DEV_AI Layer 3-4=0% Q3-Q4 trigger per ADR-028" — these correspond to Layer 3-4 components that are explicitly **planned for Q3-Q4 implementation** but documented now as forward-looking design. Annotating them as DEPRECATED would create false noise (they're not drift; they're roadmap). Defer to natural implementation cadence.

---

## 7. Verification (iter 239 close, LL-210 三态)

- **backend-only ✅**: N/A (doc-only changes)
- **runtime-verified ✅**: re-ran path-ref scan, DEV_BACKEND.md broken refs **7 → 3** (3 residual are intentionally retained inside DEPRECATED-PLAN banner blocks as historical NO-GO Phase 3D plan markers). DEV_BACKTEST_ENGINE.md **2 → 1** (1 inside ASPIRATIONAL banner). DEV_PARAM_CONFIG.md **1 → 0**.
- **sediment ✅**: this STATUS_REPORT + 8 inline edits + git commit

**Red lines:** 5/5 sustained 28+ days. Verified via canonical `audit_redline_runtime.py --no-alert` at iter 238 close. No mutation in iter 239 (doc-only).

---

## 8. Backlog deferrals (for future iters)

- **DEV_FRONTEND_UI.md residual 35%** — last audited at Phase H (65% sync per ISSUES_PENDING_REGISTRY G1). Wave 5 5 sub-MVPs (iter 196-216) may have introduced fresh drift; full audit deferred.
- **DEV_AI_EVOLUTION.md Layer 3-4 path realism** — when Q3-Q4 Layer 3-4 launches, audit the 5 EXPECTED-UNIMPL refs for actual placement vs current claims.
- **Cross-doc consistency** — semantic claims (e.g. test counts, factor counts) not audited in iter 239 — path-level only. Future iter could expand to numeric drift scan.

---

## 9. Iter 240+ next

User "继续" directive sustained. Next autonomous-eligible candidates from iter 238 STATUS_REPORT close queue:
- (a) test_factor_determinism flaky-in-sweep Option A fix (loosen atol via np.isclose) — ~10min, low risk
- (b) Tier C/D research lane start (DEV_AI L3-4 / Sharpe 0.87→1.0+ design doc)
- (c) Memory handoff archive (G3 — 779 KB approaching Read upper bound)
- (d) DEV_FRONTEND_UI.md residual 35% audit

Tier A§5 Servy elevated restart still gates 9 MVPs runtime-verified; user touchpoint required.
