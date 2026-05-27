# ADR-096: Strategy Signal Production Boundary

## Status

Committed — 2026-05-28.

## Context

The full-project closure audit flagged DCM-005: the Strategy framework exists
(`DBStrategyRegistry`, `S1MonthlyRanking`, `S2PEADEvent`, and bootstrap tests),
but the production signal task does not run a registry-driven multi-strategy
loop.

Fresh code review found a narrower truth:

- `daily_pipeline.signal` still delegates to `scripts/run_paper_trading.py::run_signal_phase`.
- `run_signal_phase` calls `SignalService.generate_signals`.
- `SignalService.generate_signals` already constructs `StrategyContext` and calls
  `PlatformSignalPipeline(config).generate(S1MonthlyRanking(config), ctx)`.
- `get_live_strategies_for_risk_check()` is wired for risk checks, not for the
  production signal phase.

So S1 production signal generation is already SDK-backed, but registry-driven
multi-strategy signal dispatch is not production-wired.

## Decision

Keep the production signal phase as the single-live-S1 PT path for now:

`daily_pipeline.signal -> run_signal_phase -> SignalService -> PlatformSignalPipeline.generate(S1MonthlyRanking)`

Do not wire `DBStrategyRegistry.get_live()` into production signal generation in
this governance batch.

## Rationale

Registry-driven signal dispatch is not a safe mechanical swap:

- S1 needs `factor_df`, `industry_map`, optional `ln_mcap`, previous holdings,
  and PT config parity.
- S2 needs `pead_candidates` and per-strategy `current_positions`.
- `SignalService` persists to the shared `signals` table using the current
  PT/execution-mode contract.
- `run_execute_phase` still reads signals for `settings.PAPER_STRATEGY_ID`.
- Order routing and per-strategy execution merge semantics are separate
  production contracts.

Moving only the loop would create a partial multi-strategy signal surface without
matching persistence and execution semantics.

## Consequences

- DCM-005 is no longer classified as "old signal engine bypasses Strategy".
  The accurate residual gap is "no registry-driven multi-strategy production
  signal loop".
- Risk checks may continue using registry bootstrap independently.
- Any future migration must be a dedicated implementation batch with parity
  tests against the current S1 path and explicit S2 persistence/execution
  acceptance criteria.

## Acceptance For Future Migration

- S1 parity test proves current PT output is unchanged for the same
  `factor_df`, `universe`, `industry`, config, and previous holdings.
- S2 metadata loaders are implemented and tested.
- `signals` persistence can store and retrieve per-strategy outputs without
  breaking existing Operator UI and execution reads.
- `run_execute_phase` or its successor consumes selected strategy outputs by
  explicit policy, not by accidental `settings.PAPER_STRATEGY_ID` fallback.
- Smoke tests cover the chosen production boundary.

## Verification

- `backend/tests/test_strategy_signal_boundary.py` locks the current boundary:
  `SignalService` uses `PlatformSignalPipeline.generate(S1MonthlyRanking)` and
  `_async_signal` does not import the registry loop.
