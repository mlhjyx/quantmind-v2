# Governance Batch 4 — Service Reload Gate and Ops Control Fix

Date: 2026-06-01 Asia/Shanghai
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 4 attempted to close the Batch 3 runtime deployment loop for the QMT cache guard and audited the service-control path used to reload Celery/Beat.

## Runtime Evidence

- `scripts/service_manager.ps1 status` reported FastAPI, Celery, Celery Slow, and Celery Beat running; `QuantMind-QMTData` remained stopped/manual.
- Scoped Servy restarts for `worker`, `slow-worker`, and `beat` failed; PIDs stayed unchanged (`QuantMind-Celery` 9900, `QuantMind-CelerySlow` 21548, `QuantMind-CeleryBeat` 9088).
- Direct Servy CLI also failed: `servy-cli restart --name="QuantMind-Celery"` returned `Failed to restart service.`
- Direct Windows service control is not available to this Codex process: `Stop-Service QuantMind-CeleryBeat` failed with `Cannot open 'QuantMind-CeleryBeat' service on computer '.'`.
- Read-only DB probe after the failed reload showed `realtime_risk_tick` still running old in-memory code: latest rows at `2026-06-01 12:14-12:16 +08` remained `status='success'`, `positions=0`, `portfolio_nav=0.0`, and no `reason='qmt_cache_unavailable'`.

## Fixes

- Hardened `scripts/service_manager.ps1`:
  - documented aliases now work: `celery`, `celery-beat`, `celerybeat`, `qmt`, `qmt-data`, `qmtdata`;
  - `all` now manages only core backend services (`fastapi`, `worker`, `slow-worker`, `beat`) and no longer starts or restarts QMTData implicitly;
  - Servy CLI failure output is printed instead of being discarded;
  - service-action failures now set process exit code `1`, so runbooks checking `$LASTEXITCODE` cannot false-pass failed restarts.
- Added `backend/tests/test_service_manager_script.py` as a static regression guard for the service-manager behavior above.
- Fixed duplicate YAML frontmatter delimiter at the top of `memory/project_sprint_state.md`.
- Updated `AGENTS.md` quick-reference wording so `restart all` is documented as core-services-only and QMTData is explicit.

## Verification

- `pytest backend/tests/test_service_manager_script.py -q` -> 4 passed.
- `pytest -m "smoke and not live_tushare" -q` -> 90 passed, 2 skipped, 7003 deselected.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\service_manager.ps1 status` -> exit 0; core services running; QMTData stopped/manual.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\service_manager.ps1 restart celery` -> exit 1 with surfaced Servy output `Failed to restart service.`
- Read-only scheduler query confirmed the runtime reload did not occur; this is an ops-permission blocker, not evidence against the Batch 3 code fix.

## Open Backlog

- **GB4-B1 [P0 ops]** Reload Celery Worker, Celery Slow Worker, and Celery Beat from an elevated/admin shell, then verify a fresh `realtime_risk_tick` row reports `status='skipped'` and `result_json.reason='qmt_cache_unavailable'` while QMTData remains stopped/manual.
- **GB4-B2 [P1 ops]** Decide whether Servy CLI restart should be available to the Codex runtime or remain operator-only; if operator-only, keep this permission boundary explicit in runbooks.
- **GB4-B3 [P2 docs]** Historical runbooks and old audit reports still contain `restart all` examples from earlier PT restart phases. The active script is now guarded, but stale historical text should not be used as an ops command source.

## Redline

No broker order API, QMTData start, `.env` edit, production YAML edit, destructive DB change, Task Scheduler mutation, or Servy configuration mutation was performed. DB access in this batch was read-only; ongoing scheduler writes were produced by the already-running application services.
