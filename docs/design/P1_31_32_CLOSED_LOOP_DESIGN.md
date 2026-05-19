# P1-31 / P1-32 Signal-NAV-Regime Closed-Loop Design

> **Plan v8 P1-31 + P1-32 closure prep** — design only, multi-month implementation deferred.
> **Source**: Plan v8 §10 Closed-Loop verification — Loop 1 + Loop 4 disconnect surface
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 §10)**:

### Loop 1 — Signal → NAV feedback (P1-31)
- Signal generator produces Top-N stocks
- Backtest replay computes hypothetical NAV
- **0 closed loop**: signal generator doesn't see realized NAV vs predicted
- Disconnect: no auto-adapt to alpha decay

### Loop 4 — Regime → Signal (P1-32)
- Market regime detector (V3 §16 Bull/Bear LLM) outputs regime label
- Signal generator uses fixed factor weights regardless of regime
- **0 wire**: regime label not consumed by signal generation
- Disconnect: regime-blind strategy

---

## §2 Loop 1 (Signal-NAV) Design

### §2.1 Current state
```
factor_engine → factor_ic_history → signal_engine → Top-N signals
    ↓
execute_phase → trade_log → position_snapshot → performance_series.nav
    [DEAD END — NAV evolution not fed back to signal generation]
```

### §2.2 Target state
```
factor_engine → IC → signal_engine
    ↑                ↓
[feedback]      Top-N signals
    ↑                ↓
NAV-vs-prediction delta ← performance_series ← trade_log ← execute_phase
```

### §2.3 Feedback signal
- Realized alpha vs predicted alpha (per signal cycle)
- Sharpe rolling 1y window vs backtest baseline
- Drawdown deviation from expected MDD distribution
- Factor IC realized vs predicted

### §2.4 Adaptation modes
- **Read-only**: Display delta in dashboard, no auto-adapt
- **Soft adapt**: Adjust factor weights ±15% based on delta
- **Hard adapt**: Switch factor set on sustained breach

**Decision**: Read-only Phase 1, Soft adapt Phase 2 (Phase J+1+)

Note (code review MEDIUM fix 5-20): Soft adapt bound revised 5% → 15% to align with
§4 compound bound calculation. Previous draft conflict resolved.

### §2.5 Implementation phases

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Delta computation engine | 2 weeks | factor_engine + performance_series |
| 2 Dashboard surface | 2 weeks | Phase 1 + frontend integration |
| 3 Soft adapt proposal | 3 weeks | Phase 2 + P0-4 approval flow |
| 4 Production rollout | 6 months observation | Phase 3 |

**Total Phase 1-2**: ~1 month
**Total Phase 1-3**: ~2 months
**Total mature**: ~8 months

---

## §3 Loop 4 (Regime → Signal) Design

### §3.1 Current state
```
news/pipeline → Bull/Bear LLM debate → regime label (BULL/BEAR/NEUTRAL)
    [DEAD END — not consumed by signal_engine]
signal_engine reads factors → Top-N (regime-blind)
```

### §3.2 Target state
```
regime label → factor_weight_modifier
    ↓
signal_engine.compute_signals(regime=BULL/BEAR/NEUTRAL, weights=W)
    ↓
Top-N signals with regime-adapted weights
```

### §3.3 Regime adaptation strategies

**Option A: Discrete factor swap**
- BULL: emphasize momentum + bp_ratio
- BEAR: emphasize defensive (low volatility)
- NEUTRAL: equal weight (current behavior)

**Option B: Continuous weight modulation**
- regime_score ∈ [-1, +1] continuous
- weights = base_weights * (1 + regime_score * sensitivity_vector)
- Bounded by ±20% adjustment per factor

**Option C: Sub-strategy ensembling**
- Maintain 3 strategies (bull / bear / neutral)
- Capital allocation by regime probability
- Higher complexity, Phase L candidate

**Decision**: Option B + bounded (safer than A, simpler than C)

### §3.4 Implementation phases

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Regime label consumer | 2 weeks | V3 §16 regime detector stable |
| 2 Weight modulation engine | 2 weeks | Phase 1 |
| 3 Backtest replay validation | 3 weeks | Phase 2 + backtest infra |
| 4 Production rollout (paper) | 1 month observation | Phase 3 |
| 5 Live trading rollout | 3 months gradual | Phase 4 + Phase B-2 stable |

**Total Phase 1-3**: ~2 months
**Total mature**: ~6 months

---

## §4 Cross-loop Interactions

Both loops affect signal_engine — coordination needed:

1. **Loop 1** adjusts factor weights based on realized delta
2. **Loop 4** adjusts factor weights based on regime

If both active: apply Loop 4 regime modulation, then Loop 1 delta adjustment.

Bounded compound: total ±25% max adjustment per factor weight
- Loop 1 soft adapt: ±15% (§2.4)
- Loop 4 regime modulation: ±20% bounded (§3.3 Option B)
- Compound overlap dampening: applied (e.g. when both sign agree, dampen by ~30%)
- Hard cap: 25% prevents pathological compounding (code review MEDIUM fix 5-20).

---

## §5 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (design only)
- Phase B-2 (5-27 Wed): NOT prerequisite
- Phase J (post 5-27): Loop 1 Phase 1-2 candidate (read-only dashboard)
- Phase K (~3 months post live): Loop 4 Phase 1-3 (regime weight modulation)
- Phase L (~6-12 months): Both loops mature + Layer 3 from P1-38 design

---

## §6 Iron Law Compliance

- Iron Law 4: Factor validation w/ neutralized IC sustained
- Iron Law 7: OOS validation required pre-rollout (walk-forward / paired bootstrap)
- Iron Law 16: Signal path 唯一性 + 契约化 (Loop 1 + Loop 4 don't bypass SignalComposer)
- Iron Law 39: 设计/实施 mode 切换 explicit

---

**Maintained by**: CC autonomous (Plan v8 P1-31 + P1-32 design sediment, 2026-05-20 Day 1)
**Cross-ref**:
- Plan v8 §10 Closed-Loop verification (parent finding)
- V3 §16 Bull/Bear LLM debate (regime detector)
- P0-4 design (precursor approval pattern)
- P1-38 design (Layer 3 self-improvement parallel)
