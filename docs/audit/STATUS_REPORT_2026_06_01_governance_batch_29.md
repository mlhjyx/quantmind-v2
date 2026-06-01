# Governance Batch 29 Status — Backtest sensitivity defer reclass

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: API coverage row 34, final §5D backlog cleanup.

## Summary

Batch 29 reclassified the last §5D item. `POST
/api/backtest/{run_id}/sensitivity` is not a missed frontend integration; the
backend endpoint is intentionally preserved as a deferred contract with ADR-DRAFT
row 18 tracking. A frontend hook today would only expose a non-working
placeholder.

The useful current UI surface is already row 31
`/api/backtest/{run_id}/cost-sensitivity`, consumed by `BacktestResults.tsx`.

## Changes

- Updated `docs/API_COVERAGE.md` §5D to show no remaining generic
  backend-implemented/frontend-unwired rows.
- Moved row 34 to §5E as backend-semantics-before-UI.
- Added `docs/API_COVERAGE.md` §30 with evidence, verification, and the
  design prerequisites for future implementation.

## Active Discovery

1. Row 34 already returns `status="deferred"` with tracking metadata; it is not
   a runnable sensitivity analysis endpoint.
2. Existing tests lock the deferred behavior, so frontend wiring would create a
   misleading UX rather than closing a product feature.
3. Future implementation needs an architecture decision covering parameter
   whitelist, override path, child-run lineage/storage, aggregation, result
   delivery, and shared-data-load strategy.

## Verification

- Backend defer contract:
  `pytest backend/tests/test_backtest_sensitivity_defer.py -q` -> 3 passed.
- Existing backtest API compatibility:
  `pytest backend/tests/test_backtest_api.py::test_sensitivity_analysis -q` ->
  1 passed.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected.
- Pre-push:
  `bash config/hooks/pre-push` -> X10 scan clean, LLM import guard clean,
  smoke 91 passed, 2 skipped, 6976 deselected.

## Remaining Work

- Row 34 remains in §5E until a Phase B sensitivity architecture design exists.
- Rows 135-136 remain in §5E for strategy version create/rollback semantics.
- Row 62 remains in §5E for execution alert-config persistence/reload
  semantics.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
