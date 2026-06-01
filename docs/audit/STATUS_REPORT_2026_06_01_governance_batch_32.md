# Governance Batch 32 Status — External/admin endpoint taxonomy

Date: 2026-06-01 +08:00  
Branch: `codex/runtime-governance-followup`  
Scope: API coverage rows 72-73, 91, 116-117, and 130.

## Summary

Batch 32 reduces API matrix noise by reclassifying endpoints that are not
missing operator UI. The affected rows are health probes, remote monitoring
probes, an admin notification test endpoint, and an inbound DingTalk webhook.
They remain backend surfaces, but they should not be counted as unresolved
frontend wiring gaps.

## Changes

- Updated `docs/API_COVERAGE.md` rows 72-73, 91, 116-117, and 130 from stale
  backend-only markers to explicit taxonomy labels.
- Added `docs/API_COVERAGE.md` §33 with code and test evidence.

## Active Discovery

1. The matrix was mixing "backend-only by design" with "frontend gap".
2. Rows 72-73 and 116-117 are probe/monitoring surfaces.
3. Row 91 is an admin test-send endpoint distinct from the current system
   notification test UI.
4. Row 130 is an inbound DingTalk receiver and should not be frontend-initiated.

## Verification

- Health API:
  `pytest backend/tests/test_api_routes.py::TestHealthAPI -q` -> 4 passed.
- Remote status API:
  `pytest backend/tests/test_remote_status.py -q` -> 7 passed.
- Notification test endpoint:
  `pytest backend/tests/test_notification_system.py::TestNotificationAPI::test_send_test_notification -q`
  -> 1 passed.
- DingTalk inbound webhook endpoint:
  `pytest backend/tests/test_dingtalk_webhook_endpoint.py::TestEndpointHappyPath::test_transitioned_returns_200 -q`
  -> 1 passed.
- Backend smoke:
  `pytest -m "smoke and not live_tushare"` -> 90 passed, 2 skipped, 7020
  deselected.
- Pre-push:
  `bash config/hooks/pre-push` -> X10 scan clean, LLM import guard clean,
  smoke 91 passed, 2 skipped, 6976 deselected.

## Remaining Work

- Remaining `❌` rows after this taxonomy cleanup: 34, 83-86, 98-99, 101,
  135-136, and 141.

## Redline Scope

No broker/order calls, no DB row mutation, no `.env` edits, no production YAML
edits, no Servy/Task Scheduler changes, and no QMT service startup were
performed in this batch.
