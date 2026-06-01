# QuantMind V2 Governance Batch 3 Status Report

Date: 2026-06-01 11:57 +08
Branch: `codex/runtime-governance-followup`
PR: `#523`

## Scope

Batch 3 audited the L1 realtime risk and QMT cache input chain using code, Redis, DB audit rows, and service status evidence. No broker order API, `.env` mutation, production YAML mutation, DB row mutation, Redis mutation, Servy mutation, or Task Scheduler mutation was performed.

## Runtime Evidence

- `scripts/service_manager.ps1 status` showed FastAPI, Celery, Celery Slow, and Celery Beat running; `QuantMind-QMTData` was stopped/manual.
- Redis read-only probe: `EXISTS portfolio:nav portfolio:current risk:l1_heartbeat qmt:connection_status` returned `0`.
- DB read-only probe: last 2 hours had 120 `realtime_risk_tick` rows, latest `2026-06-01 11:56:00+08`, all with `positions_sum=0`, `evaluated_tick_sum=0`, `evaluated_5min_sum=0`, `triggered_sum=0`.
- Latest `trade_event_risk_consumer` rows were current and successful, but consumed/processed 0 events.
- Redline read-only account probe `python scripts/_verify_account_oneshot.py` could not connect to miniQMT (`broker.connect() failed`, return code `-1`). `.env` guard values were verified read-only: `LIVE_TRADING_DISABLED=true`, `EXECUTION_MODE=paper`, `QMT_ACCOUNT_ID=81001102`.

## Findings Closed

### P0: QMT fallback guard existed but was not wired

Evidence: `QMTFallbackTriggeredRule` existed in `backend/qm_platform/risk/rules/qmt_fallback.py`, but `build_intraday_risk_engine()` did not register it. Current Redis evidence showed no `portfolio:*` cache keys, so the intended P0 guard would not run through the 5-minute intraday path.

Fix:
- Added `RedisPortfolioCacheHealthReader` in `backend/app/services/risk_wiring.py` to count live `portfolio:*` keys.
- Registered `QMTFallbackTriggeredRule` in `build_intraday_risk_engine()`.
- Kept the clean-empty-account case safe: the reader counts `portfolio:*`, so a healthy empty account with a fresh `portfolio:nav` key does not trigger the fallback guard.

Fresh code anchors verified at 2026-06-01T11:57:08+08:
- `backend/app/services/risk_wiring.py:333` reader implementation.
- `backend/app/services/risk_wiring.py:402` rule registration.
- `backend/tests/test_risk_wiring.py:39` expected rule list includes `ll081_qmt_fallback_triggered`.

### P1: Realtime tick accepted missing QMT cache as a clean empty context

Evidence: `RealtimeRiskContextBuilder.build_context()` returned an empty `RiskContext` when `positions_raw == {}` even if `portfolio:nav` was absent. Current scheduler rows matched this failure shape: `ok=True`, `positions=0`, `portfolio_nav=0.0`, and no evaluations.

Fix:
- `PositionSourceError` now carries a `reason` field.
- Empty positions without `portfolio:nav` now raises `PositionSourceError(reason="qmt_cache_unavailable")`.
- `realtime_risk_tick` preserves that reason in `scheduler_task_log.result_json` and returns a skipped audit result instead of clean success.

Fresh code anchors verified at 2026-06-01T11:57:08+08:
- `backend/app/services/risk/realtime_context_builder.py:29` reason-bearing exception.
- `backend/app/services/risk/realtime_context_builder.py:100` `qmt_cache_unavailable` guard.
- `backend/app/tasks/realtime_risk_tasks.py:285` scheduler result reason preservation.

## Verification

- `ruff format` on all touched Python files: pass.
- `ruff check` on all touched Python files: pass.
- `pytest backend/tests/test_realtime_context_builder.py backend/tests/test_realtime_risk_tasks.py backend/tests/test_risk_wiring.py backend/tests/test_qmt_fallback_rule.py -q`: 56 passed.
- `pytest backend/tests/test_daily_pipeline_multi_strategy.py backend/tests/test_risk_rules_intraday.py -q`: 41 passed.
- `pytest -m "smoke and not live_tushare" -q`: 90 passed, 2 skipped, 6999 deselected.

## Remaining Backlog

- Ops deployment: the patched Celery task and risk wiring require the normal FastAPI/Celery/Celery Beat reload path before runtime rows will reflect `qmt_cache_unavailable`; no service restart was performed in this batch.
- QMT account probe: direct miniQMT read-only verification is blocked by `broker.connect() failed` return code `-1`; account cash/positions could not be freshly confirmed through miniQMT in this batch.
- QMTData runtime: `QuantMind-QMTData` remains stopped/manual. Restarting it is an ops/redline action and was intentionally not performed in this code batch.
