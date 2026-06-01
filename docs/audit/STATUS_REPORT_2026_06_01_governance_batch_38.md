# Governance Batch 38 Status - Mutating API auth guard

Date: 2026-06-01 +08:00
Branch: `codex/runtime-governance-followup`
Scope: mechanized guard for the Batch 37 mutating API auth inventory.

## Summary

Batch 38 converts the Batch 37 route inventory into a repeatable read-only
audit guard. New mutating FastAPI routes must either be detected as
admin-gated by AST scan or be explicitly classified in
`scripts/audit/mutating_api_auth_classification.json`.

The guard is intentionally non-mutating:

- No app modules are imported.
- No broker/order calls are made.
- No DB, Redis, network, `.env`, production YAML, Servy, or Task Scheduler
  state is touched.
- It only parses `backend/app/api/*.py` and the JSON classification baseline.

## Changes

- Added `scripts/audit/check_mutating_api_auth.py`.
- Added `scripts/audit/mutating_api_auth_classification.json` with the current
  38 no-admin mutating routes classified as backlog, decision-required,
  inbound-secret-required, or public-bootstrap exception.
- Added `backend/tests/test_mutating_api_auth_audit.py`.
- Marked the current-repo classification test as `smoke` so the existing
  pre-push guard catches new unclassified mutating routes.
- Added the script to `scripts/audit/README.md`.

## TDD Record

- RED: `pytest backend/tests/test_mutating_api_auth_audit.py -q` failed during
  collection because `scripts.audit.check_mutating_api_auth` did not exist.
- GREEN: after adding the scanner and baseline,
  `pytest backend/tests/test_mutating_api_auth_audit.py -q` passed
  with 4 tests.

## Verification

- `pytest backend/tests/test_mutating_api_auth_audit.py -q` -> 4 passed.
- `ruff check scripts/audit/check_mutating_api_auth.py backend/tests/test_mutating_api_auth_audit.py`
  -> all checks passed.
- `python scripts/audit/check_mutating_api_auth.py` ->
  `PASS: 58 mutating routes, 20 admin-gated, 38 classified no-admin routes`.
- `pytest -m "smoke and not live_tushare"` -> 91 passed, 2 skipped,
  7031 deselected. The new mutating-route guard test was selected by the smoke
  marker.
- `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke
  92 passed, 2 skipped, 6987 deselected.

## Risk Impact

This does not fix the P0 admin-gate backlog. It prevents the backlog from
silently growing and creates a machine-checkable acceptance criterion for
future route work.

The Batch 36 production-code blocker remains unchanged: adding admin gates to
`backend/app/**` routes is deferred until the read-only account check can
complete or the user explicitly waives that precondition for security-only
route hardening.
