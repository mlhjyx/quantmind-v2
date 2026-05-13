# ADR-062: V3 §S10 Setup — risk_metrics_daily + verify_report infrastructure

**Status**: committed
**Date**: 2026-05-13 (PR #315 squash merged as `acc77f6`)
**Type**: V3 Tier A S10 setup sediment (operational kickoff pending separate user-driven cycle)
**Parents**: ADR-027 (V3 design SSOT) + ADR-054-061 (S5-S9 cumulative — source tables that feed risk_metrics_daily)
**Children**: future S11 ADR sediment closure + operational follow-ups (Celery Beat wire / L0/L2/L5 source-table population / SAVEPOINT pattern refactor)

## §1 背景

V3 §S10 acceptance per Plan §A: "5d paper-mode 跑通 + 触发率 / 误报率 / 漏报 / STAGED cancel 率 / LLM cost / 元监控 KPI 实测; V3 §15.4 验收 4 项 (P0 误报率<30% / L1 P99<5s / L4 STAGED 0 失败 / 元监控 0 P0)". The sprint splits naturally into (a) code infrastructure (DDL + aggregator + verify report + CLI scripts) + (b) operational kickoff (5d wall-clock dry-run + Celery Beat schedule + daily extraction + post-window verify).

This PR delivers (a). (b) is operational and pending separate user-driven cycle.

No new 5/5 红线 触发 — purely observability infrastructure (DDL + PURE Python modules + thin CLI wrappers + 25 unit tests).

## §2 Decision 1: Spec-driven SQL dispatch with per-query rollback safety

**真值**: `daily_aggregator._DEFAULT_SPECS` dict maps column name → DailyMetricsSpec (SQL + default_on_missing). `aggregate_daily_metrics` iterates the dict, runs each spec's SQL, and on per-query exception logs + calls `conn.rollback()` + returns default.

**论据**:
1. **Partial result > no result**: first day of paper-mode run, some source tables (llm_cost_daily / future L0/L2/L5 tables) may not have rows yet. Failing the entire aggregation would block the rollup. Per-query default lets the row land with whatever metrics ARE available.
2. **PG transaction abort cascade**: psycopg2 sets the connection to InFailedSqlTransaction after any error. Without rollback, all subsequent queries fail. The rollback inside `_run_query_safe` is NOT a transaction boundary write — it's per-query error recovery.
3. **Reviewer follow-up**: SAVEPOINT pattern would better preserve outer transaction state, but the single-conn-per-invocation flow (Celery task body) means there's no outer transaction to preserve. Documented as known limitation (SAVEPOINT refactor candidate if cross-task batching is added).

## §2.5 Decision 1.5: 11/20 columns intentionally deferred to source-table availability

**真值**: 9 columns have specs (alerts P0/P1/P2 + staged 5 + llm_cost); 11 columns left at dataclass defaults (news_*, fundamental_*, detection_latency_*, sentiment_*, rag_*, reflector_*). Comment block in `_DEFAULT_SPECS` documents which source sprint each deferred metric awaits.

**论据**:
1. **Reviewer cross-finding catch**: DDL has 20 columns; spec dict had 9 — gap was implicit. Comment block makes the deferral explicit, so a future maintainer doesn't assume the column is populated.
2. **Forward-compat seam**: each deferred column can be wired via spec override (passed to `aggregate_daily_metrics(specs=...)`) once source table lands, no module refactor needed.

## §3 Decision 2: UPSERT idempotency for daily re-runs

**真值**: `upsert_daily_metrics` uses `INSERT INTO risk_metrics_daily (...) VALUES (...) ON CONFLICT (date) DO UPDATE SET ...`. All 19 mutable columns in the SET clause. `created_at` excluded from SET (preserves original insert timestamp). `updated_at = NOW()` in both VALUES and SET.

**论据**:
1. **Daily re-run safety**: Celery Beat may fire the extract task multiple times per day (operator backfills, manual triggers, etc.). UPSERT means each invocation overwrites the day's row with fresh metrics — last write wins.
2. **created_at preservation by omission**: not listing it in SET clause means the original NOW() from the first insert is preserved. Reviewer P1 (db): this is correct-by-accident — explicit `created_at = risk_metrics_daily.created_at` (or removing from VALUES) would make intent unambiguous. Deferred to follow-up (current behavior correct; refactor cosmetic).

## §4 Decision 3: V3 §15.4 acceptance encoded as 4-item structured check

**真值**: `verify_report.generate_verify_report(conn, window_end, ...)` produces `AcceptanceReport` with 4 `AcceptanceItem` instances. `AcceptanceReport.all_pass` is False on any item.pass_=False OR any missing day OR no items.

**论据**:
1. **V3 §15.4 4 items map directly**: P0 误报率<30% / L1 P99<5s / STAGED FAILED=0 / 元告警 P0=0. Each item exposes pass_/threshold/actual/details for operator dashboard + RAG correlation.
2. **Markdown contract**: `to_markdown()` produces a sediment-ready report for `docs/audit/v3_tier_a_paper_mode_5d_<date>.md`. Stable format means a future doc-bot can compare across cycles.
3. **Missing-day surface**: 5d window with N<5 populated days → AcceptanceReport.missing_days list. all_pass=False. Caller (CLI script exits with code 1) makes the gate fail-loud.
4. **Reviewer HIGH fix**: `_load_window_rows` originally fetched 6 columns; now fetches all 20 (反 latent data-availability trap when future code reads staged_* directly from rows).

## §5 Decision 4: DDL hygiene — COMMENT inside transaction, no redundant index

**真值**: Reviewer P1 (db): all `COMMENT ON` statements moved INSIDE BEGIN/COMMIT (was outside, risk of partial migration). Reviewer P2 (db): dropped `idx_risk_metrics_date_desc` — PK on `date` already serves both ASC and DESC scans.

**论据**:
1. **Sustained migration convention**: project uses BEGIN/COMMIT pairing per existing migrations (`backend/migrations/*.sql`); COMMENTS outside would be inconsistent.
2. **Index discipline**: 5-day window verify queries scan ≤5 rows; PK index handles direction reversal natively. Extra index = write overhead with 0 read gain.
3. **JSONB column comment added**: `news_source_failures` column now has `COMMENT ON COLUMN` documenting `{source: failure_count}` shape — visible via `\d+ risk_metrics_daily`.

## §6 Decision 5: Thin CLI wrappers as scripted seams (not service-layer entry points)

**真值**: `scripts/v3_paper_mode_5d_extract_metrics.py` + `scripts/v3_paper_mode_5d_verify_report.py` are minimal argparse + DB conn + call-PURE-module + commit/exit wrappers. ~80 lines each. No business logic.

**论据**:
1. **PURE module testability**: business logic lives in `daily_aggregator.py` + `verify_report.py` (25 unit tests via mock conn). CLI scripts are integration-level seams, not test surface.
2. **Operator ergonomics**: standalone scripts can be wired via Celery Beat (extract daily) or run manually (verify post-window). Caller transaction boundary is the script body.
3. **Symmetry**: both scripts handle exceptions identically (rollback + close + exit 1). Reviewer LOW caught the asymmetry (verify CLI was missing rollback) — fixed.

## §7 测试覆盖

| File | Count | Scope |
|---|---|---|
| `test_daily_aggregator.py` | 7 | happy path / missing table / partial failure / None result / upsert rowcount + no-commit / custom spec override |
| `test_verify_report.py` | 18 | all-4-pass / window math (5d default / custom / missing day) / each of 4 items pass+fail boundaries / markdown shape / all_pass aggregate (4 combos) |

**Total**: 25 new tests. Pre-push smoke 55 PASS (3x). Ruff clean.

## §8 关联

- ADR-027 (V3 design SSOT)
- ADR-054-061 (S5-S9 source tables: risk_event_log + execution_plans + llm_cost_daily)
- LL-156 NEW (S10 setup-vs-operational split pattern + 6th consecutive sediment-in-same-session enforcement + reviewer 2nd-set-of-eyes 6th 实证)
- 铁律 22 (doc 跟随代码) / 32 (PURE module 0 commit, CLI owns boundary) / 33 (missing tables → default + log, NOT raise)
- V3 §13.1 SLA (L1 P99 < 5s) / §13.2 元监控 schema / §15.4 acceptance 4 items
- PR #315 (`e3d04c7` initial + `6c5ab00` reviewer-fix → squash `acc77f6` merged 2026-05-13)

## §9 已知限制 (留 operational follow-up)

1. **5d wall-clock dry-run**: actual operational cycle pending separate user-driven kickoff (apply DDL migration + register Celery Beat extract task + run for 5 days + verify report).
2. **SAVEPOINT pattern**: `_run_query_safe` uses `conn.rollback()` which would break outer transactions if caller is mid-transaction. Current flow (single conn per Celery task) doesn't have this issue. SAVEPOINT refactor candidate if cross-task batching is added.
3. **11 deferred metric columns**: wait on source-sprint table availability (Tier B mostly).
4. **L1 detection latency instrumentation**: detection_latency_p50_ms / p99_ms require risk_event_log latency_ms column or histogram cache. Out of S10 setup scope.
