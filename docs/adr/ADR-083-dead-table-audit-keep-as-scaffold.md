# ADR-083: F-S7-007 12 Dead Tables Audit Decision — KEEP all 12 as scaffold, defer drop

**Date**: 2026-05-19
**Status**: Accepted
**Author**: CC (Session 57+1 autonomous)
**Related**:
- Audit F-S7-007 (P1, V3_AUDIT_S7_ML_COST_HARDWARE_SUPPLEMENT.md §X)
- ISSUES_PENDING_REGISTRY §7 P8
- DEV_FOREX.md (NOT_STARTED, Phase 2+ DEFERRED)
- DEV_AI_EVOLUTION.md (V2.1 AI Agent design)

## Context

Audit Subagent C identified 12 tables with 0 rows totalling 216 KB:

| Table | rows | refs (code) | category |
|---|---|---|---|
| agent_decision_log | 0 | 1 (test_phase_b_infra.py only) | scaffold for AI Agent (DEV_AI_EVOLUTION V2.1) |
| chip_distribution | 0 | 1 (test only) | A 股 chip data 未启用 (planned future feature) |
| factor_mining_task | 0 | 1 (test only) | legacy GP/mining tracking (replaced by Wave 3 MVP 3.5 Strategy Gates) |
| forex_bars | 0 | 1 (test only) | DEV_FOREX DEFERRED (Phase 2+) |
| forex_events | 0 | 1 (test only) | DEV_FOREX DEFERRED |
| forex_swap_rates | 0 | 1 (test only) | DEV_FOREX DEFERRED |
| approval_queue | 0 | 144 refs | ACTIVE code path, empty data only |
| experiments | 0 | 88 refs | ACTIVE code path |
| platform_metrics | 0 | 40 refs | Wave 4 MVP 4.1 batch 2.2 expected populate |
| gp_approval_queue | 0 | 22 refs | legacy GP path, active references |
| backtest_holdings | 0 | 9 refs | backtest engine scaffold |
| backtest_wf_windows | 0 | 4 refs | walk-forward scaffold |

## Decision

**KEEP all 12 tables. NO drop.**

Rationale per table category:

### Category A — Heavy code refs (≥4) (6 tables): KEEP

- approval_queue (144), experiments (88), platform_metrics (40), gp_approval_queue (22), backtest_holdings (9), backtest_wf_windows (4)
- Code actively reads/writes these tables. 0 rows = empty data, NOT dead code.
- Dropping would require concurrent refactor of 100+ refs (high risk).
- **Action**: Sustained, no work.

### Category B — Scaffold for DEFERRED features (3 forex tables): KEEP

- forex_bars, forex_events, forex_swap_rates
- DEV_FOREX.md status: **NOT_STARTED** (Phase 2+, A股 mature 后启动)
- Scaffold left from initial design. Tables exist + 1 test ref ensures they're not silently lost.
- Dropping now means re-creating during Phase 2+ (extra work).
- **Action**: KEEP. Future Phase 2 Forex 启动时 verify schema matches actual needs (re-create if drift large).

### Category C — Scaffold for future AI / chip / mining features (3 tables): KEEP

- agent_decision_log: Will likely populate when DEV_AI_EVOLUTION V2.1 4-agent闭环 真上线 (Sprint 1.18+)
- chip_distribution: A 股 chip data 未启用, Wave 5+ candidate
- factor_mining_task: Legacy from GP era, BUT MVP 3.5 Strategy Gates `factor_evaluation` 是 replacement. Could be dropped in future if no resurrection plan.
- **Action**: KEEP as scaffold. Re-evaluate during quarterly audit (Heuristic #29 Audit Cadence).

## Consequences

### Positive
- **0 risk** of breaking refs (heavy refs preserved)
- **Future-proof**: DEFERRED features (Forex Phase 2+, AI Agent Sprint 1.18+) have scaffold ready
- **Test smoke remains green**: test_phase_b_infra.py expects all 12 tables exist

### Negative
- **Cognitive load**: onboarding readers see 12 empty tables, may wonder if dead
- **216 KB disk** (negligible) but multiplies if pattern repeated
- **Pollutes schema introspection**: `\dt` output longer

### Mitigation
- This ADR serves as discoverable reference for "why empty tables exist"
- Quarterly audit (Heuristic #29) reviews if any can be safely dropped post-feature decision
- If Wave 5+ decides chip_distribution path is closed, that table becomes drop candidate

## Alternatives Considered

### Alt 1: Drop 6 light-ref tables (chip / forex / agent / factor_mining)
**Rejected**: Forex DEFERRED不应 silent drop without DEV_FOREX update (sustained ADR pattern). chip/agent/factor_mining 同理 — drop 需要明确 feature 决议 closed.

### Alt 2: Rename to `_deprecated_<name>` prefix (Alternative 2 from audit)
**Rejected**: Renaming is also a schema change requiring re-test of test_phase_b_infra.py + audit/migration cite drift. Cost > benefit for 216 KB.

### Alt 3: Selective drop per category (Alternative 3 from audit)
**Rejected**: Even "obvious" drops (forex_*) tie to DEV_FOREX DEFERRED status — sustained policy is keep scaffold until feature decision.

## Verification

```bash
# Verify all 12 tables still exist + test passes
cd D:/quantmind-v2
python -m pytest backend/tests/test_phase_b_infra.py -v
```

## Re-evaluation Trigger (per Heuristic #29 Audit Cadence Calendar)

This ADR re-opens for review when ANY of:
- Phase J Strategy Diversification decision closes "Forex" path → drop 3 forex tables
- DEV_AI_EVOLUTION Sprint 1.18+ wires agent_decision_log → table goes from "scaffold" to "active"
- Wave 5+ decides chip_distribution not pursued → drop chip_distribution
- Quarterly audit (next: Q3 2026) — Heuristic #29 re-eval

## Closure Status

**F-S7-007 P1 finding → CLOSED with documented decision (KEEP)**.

Empty table presence is intentional scaffold, not theatrical dead code. Audit alert can be silenced for this finding pending re-trigger above.

---

**End ADR-077.** Sustained decision for 12 empty tables: KEEP, defer drop, quarterly re-eval.
