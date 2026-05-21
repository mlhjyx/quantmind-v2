# P0-21 Live Trade Reproducibility Design

> **Plan v8 P0-21 closure prep** — design only, multi-week implementation deferred.
> **Source**: Plan v8 §10 Closed-Loop verification — 4 sources stale for live trade reproducibility
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 P0-21)**:
- Live trade reproducibility requires reproducing past trade decisions
- 4 sources required: signal / position / market_data / config
- Current state: 4/4 partially stale OR fragmented
- Risk: post-incident root cause analysis impossible → black box
- Industry SOP: every live trade decision must be reproducible from cold storage (regulatory + debug)

**Why P0**:
- Phase B-2 live trading 启动后 incidents 必然 — without reproducibility, debugging impossible
- Iron Law 15: Backtest 可复现 (regression max_diff=0 hard gate)
- Same standard should apply to live trade decisions

---

## §2 4 Source Inventory

### §2.1 Source 1: Signal generation context

**What**: 信号 generation 时所用 inputs
- Factor values at signal compute time (factor_values table)
- factor weights (config snapshot at signal_phase fire time)
- universe filter (PT_TOP_N, PT_INDUSTRY_CAP, etc)
- Composition logic version (SignalComposer git commit hash)

**Stale gap**: Factor values updated daily, but config snapshot **not persistently captured** per signal event.

**Fix**: New table `signal_context_snapshot` capturing config hash + signal output.

### §2.2 Source 2: Position state at decision

**What**: Position snapshot at execute_phase fire time
- holdings (code → quantity)
- cash
- pending orders
- broker connection state (xtquant status)

**Stale gap**: position_snapshot 是 EOD batch, 不是 per-decision granular.

**Fix**: Inline snapshot in execute_phase, append to trade_log row.

### §2.3 Source 3: Market data context

**What**: Market state at decision moment
- klines_daily (T-1)
- minute_bars (T intraday)
- Regime label (V3 §16)
- A 股 trading calendar state

**Stale gap**: market_data SSOT 一致, 但 minute-level snapshot **not captured per decision**.

**Fix**: Inline last 60min minute_bars hash in trade_log row.

### §2.4 Source 4: Config snapshot

**What**: Full system config at decision moment
- backend/.env (sensitive fields redacted)
- pt_live.yaml
- 5/5 红线 fields
- L4 STAGED state
- Factor active list (factor_registry status)

**Stale gap**: Config 是 mutable file, **not versioned per change**.

**Fix**: Hash + sediment to `config_snapshot` table per significant change.

---

## §3 Architecture

### §3.1 New tables

```sql
-- Per signal event context
CREATE TABLE signal_context_snapshot (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID REFERENCES signals(id),
  trade_date DATE NOT NULL,
  config_hash TEXT NOT NULL,
  factor_weights_json JSONB NOT NULL,
  universe_filter_json JSONB NOT NULL,
  composer_git_commit TEXT NOT NULL,
  factor_count INT NOT NULL,
  active_factors_json JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per execution decision context
CREATE TABLE execution_decision_snapshot (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trade_log_id INT REFERENCES trade_log(id),
  pre_execution_cash NUMERIC NOT NULL,
  pre_execution_holdings_json JSONB NOT NULL,
  pending_orders_count INT NOT NULL,
  xtquant_status TEXT NOT NULL,
  market_minute_bars_hash TEXT NOT NULL,
  regime_label TEXT,
  l4_staged_state TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per config change snapshot
CREATE TABLE config_snapshot (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_at TIMESTAMPTZ DEFAULT NOW(),
  env_hash TEXT NOT NULL,
  pt_live_yaml_hash TEXT NOT NULL,
  redline_5_fields_json JSONB NOT NULL,
  triggered_by TEXT,  -- 'manual' / 'script' / 'auto'
  notes TEXT
);
```

### §3.2 Capture points

```
[signal_phase] → write signal_context_snapshot
[execute_phase] → write execution_decision_snapshot + reference trade_log
[.env mutation] → write config_snapshot (LL-188 sediment drift precursor)
[pt_live.yaml mutation] → write config_snapshot
[red line field change] → write config_snapshot + DingTalk P0 alert
```

### §3.3 Replay API

```
POST /api/audit/replay-decision
  Body: {trade_log_id} OR {signal_id}
  Response: {
    signal_context: {full config + factors + weights},
    execution_decision: {full state at execution},
    market_state: {minute bars at decision time},
    full_replay_command: "python scripts/replay_decision.py --trade-log-id=X"
  }

POST /api/audit/replay-decision/execute
  Body: {trade_log_id, dry_run: true}
  Side effect: re-run signal + execution in dry-run mode with sediment context
  Returns: original_output vs replay_output diff
  Auth: admin token
```

---

## §4 Implementation Phases

### §4.1 Phase 1 (Week 1): Schema migrations
- `signal_context_snapshot` table + index
- `execution_decision_snapshot` table + index
- `config_snapshot` table + index
- Test: empty inserts + index performance

### §4.2 Phase 2 (Week 2): Capture wire — signal phase
- Wire `signal_engine.py` to write `signal_context_snapshot`
- Hash computation utility (`scripts/lib/config_hash.py`)
- Test: signal_phase e2e + verify snapshot row

### §4.3 Phase 3 (Week 3): Capture wire — execution phase
- Wire `execution_service.py` to write `execution_decision_snapshot`
- Inline minute_bars hash + L4 state
- Test: execute_phase e2e + verify

### §4.4 Phase 4 (Week 4): Capture wire — config snapshot
- Hook into `.env` mutation script (write `config_snapshot` row)
- Hook into pt_live.yaml mutation
- Test: each red-line field change triggers snapshot

### §4.5 Phase 5 (Week 5): Replay API
- New `/api/audit/replay-decision` endpoint
- New `scripts/replay_decision.py` CLI tool
- Test: replay a past trade, verify outputs match

### §4.6 Phase 6 (Week 6): Frontend integration
- New page `frontend/src/pages/AuditReplay.tsx`
- Browse historical trade decisions + replay button

---

## §5 Phase B-1 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (frozen state)
- Phase B-2 (5-27 Wed): NOT prerequisite, but **highly recommended** for live debugging
- Phase J Week 1-3: Phase 1-3 priority — capture wire MUST be in place before incidents
- Phase J Week 4-6: Phase 4-6
- Critical: Phase 2-3 (capture wire) before any incident — retro-capture is impossible

---

## §6 Alternatives

### Alt 1: Log file replay (current)
- Tail logs + manually reconstruct context
- Slow, error-prone, missing config snapshots
- Currently de-facto post-incident method

### Alt 2: Cold storage all factor_values + config
- Sediment everything, search later
- Storage cost + queries hard
- Inferior to structured snapshot tables

### Alt 3: Event sourcing (Plan v8 Strategic Alt C)
- All decisions emit events to event store
- Replay via event playback
- Major refactor (~3 months)
- Defer until Phase L+

---

## §7 Effort Estimate

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Schema migrations | 2-3 days | None |
| 2 Signal capture wire | 3-5 days | Phase 1 |
| 3 Execution capture wire | 3-5 days | Phase 2 |
| 4 Config snapshot wire | 2-3 days | Phase 3 |
| 5 Replay API + CLI | 5-7 days | Phase 4 |
| 6 Frontend integration | 3-5 days | Phase 5 + Phase H |

**Total**: ~3-5 weeks for full reproducibility

---

## §8 Iron Law Compliance

- Iron Law 15: Reproducibility (extend backtest standard to live trade)
- Iron Law 17: All DB writes via DataPipeline
- Iron Law 33: Snapshot failures must fail-loud (no silent miss)
- Iron Law 38: Reproducibility is long-term Blueprint memory (sustained cross-version)

---

**Maintained by**: CC autonomous (Plan v8 P0-21 design sediment, 2026-05-20 Day 1)
**Cross-ref**:
- Plan v8 §10 Closed-Loop verification
- Iron Law 15 (Backtest reproducibility precedent)
- ADR-027 (L4 STAGED state machine, similar capture pattern)
- LL-188 sediment drift forensic (config_snapshot motivation)
