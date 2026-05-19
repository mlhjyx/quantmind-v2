# P1-38 DEV_AI_EVOLUTION Layer 3+4 Implementation Design

> **Plan v8 P1-38 closure prep** — design + simulation plan, multi-month implementation deferred.
> **Source**: docs/DEV_AI_EVOLUTION.md V2.1 (Layer 1+2 implemented, 3+4 0% impl)
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 P1-38)**:
- docs/DEV_AI_EVOLUTION.md V2.1 (705 lines) defines 4 layers:
  - **Layer 1** (factor discovery) ✅ 部分 implemented (LLM-driven factor proposal)
  - **Layer 2** (alpha generation) ✅ 部分 implemented (GP + LLM hybrid)
  - **Layer 3** (closed-loop self-improvement) ❌ 0% impl
  - **Layer 4** (cross-strategy meta-learning) ❌ 0% impl

**Why 0%**: Layer 3+4 require:
- Layer 1+2 stable + 6+ months production data
- LLM cost budget for self-reflection cycles
- Engineering effort 3+ months full-time

**Phase B-1 status**: Layer 1+2 reasonably stable, Layer 3+4 design intent sustained but no implementation.

---

## §2 Layer 3 Design (Self-Improvement Closed Loop)

### §2.1 Inputs
- factor_ic_history (IC time series per factor)
- factor_lifecycle log (active / warning / dead transitions)
- trade_log (执行 alpha)
- performance_series (NAV evolution)
- risk_event_log (incidents)

### §2.2 Closed loop cycle (weekly cadence)

```
Week N analysis:
    1. Gather inputs (factor IC + trade alpha + NAV evolution)
    2. LLM reflection: "Which factors degraded? Why?"
       - V4-Pro 5-dim reflection (similar to RiskReflector pattern)
    3. Surface candidate adjustments:
       - Factor weight rebalance proposal
       - Factor retire/reactivate proposal
       - New factor discovery direction proposal
    4. Backtest replay verify proposed adjustments (paired bootstrap)
    5. Human-in-loop approval (sustained P0-4 pattern)
    6. Apply approved adjustments to next-period configs
```

### §2.3 Schema

```sql
CREATE TABLE factor_lifecycle_proposals (
  id UUID PRIMARY KEY,
  proposed_at TIMESTAMPTZ,
  source_reflection_id UUID,
  factor_id UUID REFERENCES factor_registry(id),
  current_status TEXT,  -- active / warning / dead
  proposed_status TEXT,
  rationale TEXT,
  backtest_replay_id UUID,
  status TEXT DEFAULT 'pending',
  approved_at TIMESTAMPTZ
);
```

### §2.4 Implementation phases

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Schema + reflection prompt | 1 week | None |
| 2 Beat task (Sunday 20:00) wire | 1 week | Phase 1 |
| 3 Backtest replay integration | 2 weeks | Existing backtest infra |
| 4 Approval API + Frontend | 2 weeks | P1-36 risk API |
| 5 Production rollout | 6 months observation | Phase 4 |

**Total Layer 3 implementation**: ~2-3 months

---

## §3 Layer 4 Design (Cross-Strategy Meta-Learning)

### §3.1 Pre-requisite
- ≥2 production strategies simultaneously running
- ≥6 months data per strategy
- Layer 3 stable (auto-approval rate > 70%)

### §3.2 Cross-strategy 学习方向

1. **Diversification check**: Are 2+ strategies truly diversified or alpha overlap?
2. **Capital allocation**: How to split capital across strategies?
3. **Regime adaptation**: Which strategy dominates in which market regime?

### §3.3 Closed loop (monthly cadence)

```
Month N analysis:
    1. Gather cross-strategy correlations (returns + factor exposures)
    2. LLM analysis: regime + diversification + capacity scaling
    3. Surface meta-proposals:
       - Capital reallocation between strategies
       - Strategy retirement / activation
       - New strategy direction
    4. Quarterly review + slow rollout
```

### §3.4 Implementation phases

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Multi-strategy data model | 2 weeks | Current = single-strategy |
| 2 Cross-strategy correlation engine | 3 weeks | Phase 1 |
| 3 LLM meta-reflection prompt | 2 weeks | Phase 2 |
| 4 Capital reallocation API | 2 weeks | Phase 3 + P1-36 |
| 5 Production rollout | 12 months observation | Phase 4 |

**Total Layer 4**: ~3-4 months + 12 months observation

---

## §4 Decision: Defer Both Layers

### §4.1 Layer 3 status
- **Defer to Phase K** (~6 months post Phase B-2 live restart)
- Pre-requisite: 6 months stable live + cumulative data sediment
- Sustained P0-4 ThresholdEngine pattern is precursor (similar approval flow)

### §4.2 Layer 4 status
- **Defer to Phase L** (~12-18 months post Phase B-2)
- Pre-requisite: ≥2 production strategies running

### §4.3 What to do now (Phase B-1)

1. **Sediment this design doc** ✅ (本 doc)
2. **Identify Layer 3 precursor opportunities**:
   - RiskReflector V3 §8 已实现 (3 dims, not 5 full)
   - P0-4 ThresholdEngine proposal pattern (类似)
3. **Layer 4 NOT YET viable** (single-strategy CORE3+dv_ttm)
4. **Monthly review**: re-evaluate Layer 3 readiness post Phase B-2

---

## §5 Alternative Considerations

### Alt 1: Skip Layer 3+4 entirely
- Manual factor weight rebalance suffices for single-user
- Accept 0% Layer 3+4 as design intent only
- **Risk**: Bus factor 1 + manual review bottleneck

### Alt 2: Layer 3-lite (manual reflection digest only)
- Weekly digest of factor IC drift (without LLM)
- Human reads digest, decides actions
- **Pros**: Simpler, no LLM cost
- **Cons**: Loses LLM pattern recognition

### Alt 3: Outsource to existing tools
- Qlib / RD-Agent has similar reflection (per阶段 0 调研)
- Pros: Don't reinvent wheel
- Cons: Route C decision sustained — Qlib reflection 不 align with A 股 quirks

---

## §6 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (design only)
- Phase B-2 (5-27 Wed): NOT prerequisite
- Phase J (post 5-27): Layer 3 precursor (RiskReflector enhancements)
- Phase K (~6 months post live): Layer 3 Phase 1-2
- Phase L (~12-18 months): Layer 4

---

## §7 Iron Law Compliance

- Iron Law 24: Layer 3+4 design ≤5 page (本 doc) per Framework abstraction layer
- Iron Law 33: Closed-loop fail-loud (no silent auto-approval)
- Iron Law 38: Layer 3+4 是 long-term Blueprint memory sustained
- Iron Law 39: 设计 vs 实施模式切换 explicit (design = THIS DOC, 实施 = Phase K+)

---

**Maintained by**: CC autonomous (Plan v8 P1-38 design sediment, 2026-05-20 Day 1)
**Status**: Design sediment only — Layer 3 Phase K (~6 months), Layer 4 Phase L (~12 months+)
**Cross-ref**:
- docs/DEV_AI_EVOLUTION.md V2.1 (parent design, 705 lines)
- ADR-064 RiskReflector design (precursor pattern)
- P0-4 ThresholdEngine wire design (parallel pattern)
- P1-36 Risk subservice API design (Layer 3 needs API endpoints)
