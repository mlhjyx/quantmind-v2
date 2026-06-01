# Governance Batch 33 Status — News ops endpoint taxonomy

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: API coverage rows 83-86.

## Summary

Batch 33 reduces API matrix noise by reclassifying news ingestion and news
diagnostics endpoints as ops surfaces rather than missing frontend wiring. It
also adds mocked route-level tests for the non-RSSHub manual news endpoints so
the taxonomy has executable coverage.

## Changes

- Added `backend/tests/test_news_api_manual_endpoints.py` with mocked route
  coverage for `/api/news/ingest`, `/api/news/ingest_announcement`, and
  `/api/news/stats`.
- Updated `docs/API_COVERAGE.md` rows 83-86 from stale backend-only markers to
  explicit ops-ingest / ops-diagnostics taxonomy labels.
- Added `docs/API_COVERAGE.md` §34 with code and test evidence.

## Active Discovery

1. Rows 83-85 are trigger endpoints that can call external news providers,
   classifiers, and persistence paths; they should not be frontend-initiated.
2. Row 86 is a diagnostics endpoint for recent news counts and samples.
3. RSSHub route coverage already existed, but the 5-source ingest,
   announcement ingest, and stats routes lacked matching route-level tests.

## Verification

- News manual endpoints:
  `pytest backend/tests/test_news_api_manual_endpoints.py -q` -> 4 passed.
- News ops route suite:
  `pytest backend/tests/test_news_api_manual_endpoints.py backend/tests/test_news_api_rsshub_endpoint.py -q`
  -> 16 passed.
- Ruff:
  `ruff check backend/tests/test_news_api_manual_endpoints.py` -> all checks
  passed.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7024
  deselected.
- Pre-push:
  `bash config/hooks/pre-push` -> X10 clean, LLM import guard clean, smoke 91
  passed, 2 skipped, 6980 deselected.

## Remaining Work

- Remaining `❌` rows after this taxonomy cleanup: 34, 98-99, 101, 135-136,
  and 141.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
