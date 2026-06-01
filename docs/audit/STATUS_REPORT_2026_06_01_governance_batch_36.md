# Governance Batch 36 Status — Params admin-gate production-code blocker

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: params admin-gate security follow-up after API matrix cleanup.

## Summary

Batch 36 investigated the next risk after API matrix cleanup: params mutation
endpoints are still public in `backend/app/api/params.py`. Existing audit
history already flags `PUT /api/params/{key}` and
`POST /api/params/init-defaults` as runtime-configuration mutation surfaces.

The intended code fix is to add `Depends(verify_admin_token)` to params
mutation endpoints and update tests/frontend behavior accordingly. That fix was
not applied in this batch because the project redline read-only account check
could not complete.

## Evidence

- `docs/audit/api_auth_gate_2026_04_29.md` records `params.py` as missing an
  admin gate for runtime parameter mutation.
- `docs/audit/d3_11_security_2026_04_30.md` escalates params mutation endpoints
  as high-risk configuration mutation surfaces.
- Current `backend/app/api/params.py` has no `verify_admin_token` dependency on
  `PUT /{key:path}`, `POST /init-defaults`, or `POST /rollback`.
- `app.core.auth.verify_admin_token` is the existing shared admin-token
  dependency used by approval, risk, agent, and SSE routes.

## Blocker

Required pre-edit redline check did not pass:

- `python scripts/_verify_account_oneshot.py` -> exit 1.
- Output reason: `broker.connect() failed: miniQMT连接失败，返回码: -1`.

Because this would be a `backend/app/**` production-code edit, the code change
is deferred until the read-only account check can complete or the user explicitly
waives that precondition for this security-only route mutation.

## Proposed Fix Batch

1. Add `from app.core.auth import verify_admin_token` to `backend/app/api/params.py`.
2. Add `_: None = Depends(verify_admin_token)` to:
   - `PUT /api/params/{key}`
   - `POST /api/params/init-defaults`
   - `POST /api/params/rollback`
3. Update params route tests to cover 401/500 auth behavior plus happy path with
   `X-Admin-Token`.
4. Update frontend save behavior if the current admin-token cookie path is not
   already set by the operator session.

## Acceptance Criteria

- Missing/wrong token returns 401 for params mutation endpoints.
- Missing `ADMIN_TOKEN` returns 500 for params mutation endpoints.
- Valid token preserves existing success behavior.
- Existing `GET /api/params`, `GET /api/params/{key}`, and
  `GET /api/params/changelog` remain public read endpoints.
- `pytest backend/tests/test_param_system.py -q` passes.
- `pytest -m "smoke and not live_tushare"` passes.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
