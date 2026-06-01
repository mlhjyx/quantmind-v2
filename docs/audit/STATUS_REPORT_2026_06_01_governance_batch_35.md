# Governance Batch 35 Status — Final API matrix hard-gap cleanup

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: API coverage rows 34, 135-136, and 141.

## Summary

Batch 35 removes the last hard `❌` markers from the API coverage matrix by
reclassifying deferred/sensitive/superseded endpoints into explicit taxonomy
rows. It also adds backend route coverage for the direct strategy backtest
endpoint while keeping the frontend on the safer reviewed backtest flow.

## Changes

- Added strategy direct-backtest route tests in `backend/tests/test_api_routes.py`.
- Updated `docs/API_COVERAGE.md` rows 34, 135-136, and 141 from hard gaps to
  deferred-contract / needs-UX-design / superseded taxonomy labels.
- Added `docs/API_COVERAGE.md` §36.

## Active Discovery

1. Row 34 is intentionally deferred and already has sensitivity-defer coverage.
2. Rows 135-136 are real version mutations; exposing them needs diff preview,
   required changelog, rollback confirmation, audit display, and reload
   semantics.
3. Row 141 is not the active operator path. Strategy pages navigate to
   `/backtest/config?strategy_id=...`, then the reviewed config is submitted via
   `/api/backtest/run`.

## Verification

- Strategy routes:
  `pytest backend/tests/test_api_routes.py::TestStrategiesAPI -q` -> 13 passed.
- Ruff:
  `ruff check backend/tests/test_api_routes.py` -> all checks passed.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7028
  deselected.
- Pre-push:
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6984 deselected.

## Remaining Work

- No hard `❌` API matrix rows remain.
- Deferred design work remains explicit for row 34 and rows 135-136.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
