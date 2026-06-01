# Governance Batch 37 Status - Mutating API admin-gate inventory

Date: 2026-06-01 +08:00
Branch: `codex/runtime-governance-followup`
Scope: docs-only audit of mutating FastAPI routes after Batch 36 params
admin-gate blocker.

## Summary

Batch 37 expands the Batch 36 params finding into a route-level inventory of
mutating backend API surfaces. This batch does not change production code
because the Batch 36 redline pre-edit check is still blocked by miniQMT
read-only account connection failure.

Fresh AST scan result:

- `total_mutating=58`
- `admin_gated=20`
- `no_admin_dependency=38`

This is not a single-endpoint issue. It is a governance backlog: several
resource-cost, strategy, pipeline, factor, and runtime-configuration mutation
routes currently have no `Depends(verify_admin_token)` dependency.

## Evidence

- Command run on 2026-06-01 +08: inline Python AST scan over
  `backend/app/api/*.py`, filtering `POST`, `PUT`, `DELETE`, and `PATCH`
  decorators and function-level `Depends(verify_admin_token)` usage.
- `backend/app/core/auth.py:28` defines the shared `verify_admin_token`
  dependency. It accepts the HttpOnly `admin_token` cookie or
  `X-Admin-Token` header, and raises 500 when `ADMIN_TOKEN` is absent.
- `backend/app/api/auth.py:55` intentionally exposes `POST /api/auth/admin-token`
  as the login/bootstrap route, but validates `X-Admin-Token` before setting
  the cookie.
- `backend/app/api/auth.py:101` protects logout with `verify_admin_token`.
- `frontend/src/api/execution.ts:205` already performs the admin-token cookie
  setup call with `withCredentials: true`.

## No-admin Mutating Route Inventory

| Module | Count | Routes |
|---|---:|---|
| `auth.py` | 1 | `POST /admin-token` |
| `backtest.py` | 4 | `POST /run`, `POST /{run_id}/cancel`, `POST /compare`, `POST /{run_id}/sensitivity` |
| `factors.py` | 3 | `POST /{name}/archive`, `POST /health-check`, `POST /correlation-prune` |
| `mining.py` | 3 | `POST /run`, `POST /tasks/{task_id}/cancel`, `POST /evaluate` |
| `news.py` | 3 | `POST /ingest`, `POST /ingest_rsshub`, `POST /ingest_announcement` |
| `notifications.py` | 5 | `PUT /read-all`, `DELETE /clear-old`, `PUT /preferences`, `PUT /{notification_id}/read`, `POST /test` |
| `params.py` | 3 | `PUT /{key:path}`, `POST /init-defaults`, `POST /rollback` |
| `pipeline.py` | 7 | `POST /trigger`, `POST /runs/{run_id}/cancel`, `PUT /automation-level`, `POST /pause`, `POST /resume`, `POST /runs/{run_id}/approve/{factor_id}`, `POST /runs/{run_id}/reject/{factor_id}` |
| `report.py` | 1 | `POST /generate` |
| `risk.py` | 1 | `POST /dingtalk-webhook` |
| `strategies.py` | 6 | `POST /{strategy_id}/versions`, `POST /{strategy_id}/rollback`, `POST /`, `PUT /{strategy_id}`, `DELETE /{strategy_id}`, `POST /{strategy_id}/backtest` |
| `system.py` | 1 | `POST /test-notification` |

## Triage

### P0 - Gate before production-code cleanup can proceed

These endpoints mutate runtime configuration, operator workflow state, factor
promotion state, strategy definitions, or trigger expensive jobs. They should
receive admin-token tests and route dependencies once the redline precondition
is cleared or explicitly waived for security-only route hardening.

- Params: `PUT /api/params/{key}`, `POST /api/params/init-defaults`,
  `POST /api/params/rollback`.
- Pipeline: trigger, cancel, automation level, pause, resume, approve factor,
  reject factor.
- Strategies: create, update, delete, version create, rollback, direct
  backtest trigger.
- Factors: archive, manual health check, correlation prune.
- Mining: run, cancel, evaluate.
- News ingest: manual ingest, RSSHub ingest, announcement ingest.
- Backtest: run, cancel, compare, sensitivity.

### P1 - Needs explicit product/security decision

These are operator or resource-cost surfaces, but the correct control may be
admin-token, rate limit, inbound secret, or UI-level ownership rather than the
same dependency everywhere.

- Notifications: read state, clear old, preferences, and test send.
- System: test notification.
- Report: generate report.
- Risk DingTalk webhook: inbound callback should use an inbound webhook secret
  or signature model rather than the operator admin-token cookie.

### Expected Public Exception

- `POST /api/auth/admin-token` is expected to remain public because it is the
  route that validates the supplied admin token and sets the HttpOnly cookie.

## Proposed Fix Batches

1. Batch A: params route gate from Batch 36.
2. Batch B: strategy and pipeline mutation gates, with route tests for
   missing token, wrong token, missing `ADMIN_TOKEN`, and valid token.
3. Batch C: factor, mining, news, backtest, report, and notification
   resource-cost gates or explicit documented exceptions.
4. Batch D: DingTalk inbound webhook secret/signature decision and tests.
5. Batch E: add a reusable route-auth inventory test or script so the matrix
   does not drift silently.

## Acceptance Criteria

- Every mutating route is classified as one of:
  `admin-gated`, `public bootstrap`, `inbound webhook with secret/signature`,
  `low-risk local state`, or `documented exception`.
- P0 routes either require `verify_admin_token` or have a documented stronger
  control.
- Each newly gated route has tests for missing token, invalid token, missing
  `ADMIN_TOKEN`, and valid token behavior.
- The API coverage document records auth class, caller class, and exception
  reason.
- A repeatable inventory command or test fails when a new mutating route is
  added without classification.

## Active Discovery

Finding B37-1 - prompt did not ask for this exact inventory, but the Batch 36
params blocker exposed a broader class.

- Prompt context: full-project governance and risk closure.
- Fresh verify result: 2026-06-01 +08 AST scan found 38 mutating routes without
  a function-level admin-token dependency.
- Scope correction: treat params as the first fix batch, not the whole auth
  backlog.
- Handling: documented a prioritized backlog while production-code edits remain
  blocked by the redline precondition.

## Verification

- `git status --short` before edits showed only the unrelated untracked
  `reports/28fc37e5-2d32-4ada-92e0-41c11a5103d0_2026-06-01_paper.json`.
- Inline AST scan over `backend/app/api/*.py` completed successfully and
  produced the counts above.
- No broker/order calls, DB row mutations, `.env` edits, production YAML edits,
  Servy/Task Scheduler changes, QMT service startup, or backend production-code
  edits were performed in this batch.
