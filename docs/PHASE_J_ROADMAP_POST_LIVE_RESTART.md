# Phase J Roadmap — Post Phase B-2 Live Restart Implementation Sequence

> **Created**: 2026-05-20 Day 1 morning autonomous push
> **Scope**: Post 5-27 Wed Phase B-2 live flip — implement sedimented designs in priority order
> **Source**: Plan v8 cumulative closure batch (PR #383)
> **Status**: Roadmap sediment, awaits user trigger sequence

---

## §1 Sequencing Principles

1. **Phase B-1 → B-2 verification first** (5-20 → 5-26 → 5-27): no Phase J work begins until Phase B-2 stable 1 week
2. **Risk-conservative**: lowest-risk closures first, highest-risk last
3. **Dependency-respecting**: features build on each other where possible
4. **Single-PR rule**: each Phase J item = own PR + AI review + tests + merge gate
5. **Sediment-then-implement enforced** (反 LL-187/LL-190): every closure tracks back to design doc

---

## §2 Phase J Week 1 (5-27 → 6-3, first live week)

**Theme**: Frozen-state observation + audit + verify Phase B-2 stability

| # | Work | Source | Risk | Priority |
|---|---|---|---|---|
| W1.1 | Day-by-day STATUS_REPORT sediment (5-27 → 6-3) | Path B-1 template extends | None | P0 |
| W1.2 | Schtask register batch (9 commands) | scripts/register_phase_b_1_schtasks.ps1 | LOW (read-only probes) | P0 |
| W1.3 | PG password rotate (P0-2) | docs/runbook/pg_password_rotate_playbook.md | MEDIUM | P0 (security hygiene) |
| W1.4 | DingTalk HMAC outbound enable (P1-43) | user secret + .env edit | LOW | P1 |

**Outputs**:
- 7 daily STATUS_REPORTs
- 9 schtasks registered + verified fire schedule
- New PG password rotated + 4 services healthy
- DingTalk HMAC enabled (signature verification active)

**Gate criteria**:
- Phase B-2 5-27 live flip stable across 5+ trading days
- 0 incidents requiring rollback
- All 9 schtasks fire green for 3+ consecutive days

---

## §3 Phase J Week 2-3 (6-3 → 6-17, weeks 2-3)

**Theme**: Live trade reproducibility infrastructure (P0-21 priority — critical for incident response)

| # | Work | Source | Effort | Risk |
|---|---|---|---|---|
| W2.1 | P0-21 Phase 1: Schema migrations (signal_context_snapshot + execution_decision_snapshot + config_snapshot) | docs/design/P0_21_LIVE_TRADE_REPRODUCIBILITY_DESIGN.md §4.1 | 2-3 days | LOW |
| W2.2 | P0-21 Phase 2: Signal capture wire | §4.2 | 3-5 days | MEDIUM |
| W2.3 | P0-21 Phase 3: Execution capture wire | §4.3 | 3-5 days | MEDIUM-HIGH |
| W2.4 | P0-21 Phase 4: Config snapshot wire | §4.4 | 2-3 days | LOW |

**Outputs**:
- 3 new DB tables (migrations)
- Signal phase + execution phase both write snapshots
- Config drift snapshot per mutation
- Replay capability for incident reproduction

**Gate criteria**:
- All 3 schemas applied + indexed
- 1 week of live data captured in snapshots
- Replay 1 historical trade decision produces identical output to original

---

## §4 Phase J Week 4-5 (6-17 → 7-1)

**Theme**: Service-layer transaction boundary refactor (P0-9, Iron Law 32 enforcement)

| # | Work | Source | Effort |
|---|---|---|---|
| W4.1 | P0-9 Phase 0: Inventory + tooling | docs/design/P0_9_SERVICE_LAYER_COMMIT_REFACTOR_DESIGN.md §4.1 | 1 day |
| W4.2 | P0-9 Phase 1: Tier 3 utility services (5-7 services) | §4.2 | 5-10 days |

**Outputs**:
- `scripts/audit_service_commit_violations.py` (inventory tool)
- 5-7 utility services refactored to remove `conn.commit()`

**Risk**:
- Some test failures expected (test fixtures may rely on autocommit)
- 每个 PR 必带 integration test verifying transaction boundary

---

## §5 Phase J Week 6-8 (7-1 → 7-22)

**Theme**: Cross-loop closure + Multi-source data resilience

| # | Work | Source | Effort | Priority |
|---|---|---|---|---|
| W6.1 | P0-4 Phase 1-3: Reflector → ThresholdEngine wire | docs/design/P0_4_REFLECTOR_THRESHOLD_ENGINE_WIRE_DESIGN.md §4 | 2 weeks | P0 |
| W6.2 | P1-33 Phase 1-3: Tushare fallback chain (Baostock secondary) | docs/design/P1_33_TUSHARE_FALLBACK_CHAIN_DESIGN.md §4 | 2-3 weeks | P0 (live trading data SPF) |
| W6.3 | P1-36 Phase 1: Risk subservice read-only API | docs/design/P1_36_RISK_SUBSERVICE_API_DESIGN.md §5 | 3-5 days | P1 (UX support) |

**Outputs**:
- Risk threshold proposal queue + human-in-loop approval flow
- Tushare → Baostock auto-fallback on sustained failure
- 7 read-only `/api/risk/*` endpoints

---

## §6 Phase K (7-22 → ~Q3 2026 end)

**Theme**: Closed-loop deepening + Operator UX

| # | Work | Source | Effort | Quarter |
|---|---|---|---|---|
| K1 | P1-31 Loop 1 Signal-NAV feedback (read-only + soft adapt) | docs/design/P1_31_32_CLOSED_LOOP_DESIGN.md §2 | 2 months | Q3 2026 |
| K2 | P1-32 Loop 4 Regime-Signal (Option B continuous weight modulation) | §3 | 2 months | Q3 2026 |
| K3 | P0-17 Phase 2-3: Production disaster drill | docs/design/P0_17_DISASTER_DRILL_DESIGN.md §5 | 1 quarter | Q3-Q4 2026 |
| K4 | P0-9 Phase 2-3: Cold + Hot service refactor (12+8 services) | docs/design/P0_9 §4.3 | 6-10 weeks | Q3-Q4 |
| K5 | P1-26 Phase 1-3: 8-dim FundamentalContext (Dim 6+7 → 2+4 → 3+8) | docs/design/P1_26_FUNDAMENTAL_CONTEXT_8_DIM_DESIGN.md §4 | 6-8 weeks | Q3-Q4 |
| K6 | P1-36 Phase 2-3: Risk write API + frontend integration | P1-36 §5 | 4-6 weeks | Q3-Q4 |

---

## §7 Phase L (~Q4 2026 onward)

**Theme**: Multi-strategy + Self-improvement layer

| # | Work | Source | Effort |
|---|---|---|---|
| L1 | P1-38 Layer 3 (self-improvement closed loop) | docs/design/P1_38_DEV_AI_LAYER_3_4_DESIGN.md §2 | 2-3 months |
| L2 | P1-26 Phase 4-5: Dim 5 Governance + aggregator integration | P1-26 §4.4-4.5 | 4-6 weeks |
| L3 | P0-21 Phase 5-6: Replay API + frontend integration | P0-21 §4.5-4.6 | 4-6 weeks |
| L4 | P1-47 Frontend chart lib consolidation (Recharts → ECharts, 6 files) | docs/design/P1_47_FRONTEND_CHART_LIB_MIGRATION.md | 6-8 days |

---

## §8 Phase M (Q1 2027+)

**Theme**: Cross-strategy meta-learning + Long-term sustainability

| # | Work | Source | Effort |
|---|---|---|---|
| M1 | P1-38 Layer 4 (cross-strategy meta-learning) | P1-38 §3 | 3-4 months + 12 mo observation |
| M2 | Multi-strategy infrastructure (≥2 strategies live) | Strategy diversification design (Phase 2.1 NO-GO revisit) | Sprint planning |
| M3 | Annual disaster drill (Tier 1+2+3 full) | P0-17 Phase 3 + cumulative review | 1 day Q4 evening |

---

## §9 Tracking + Audit Cadence

### §9.1 Per-PR rules
- Single concern per PR
- AI code review + security review mandatory
- Integration test included
- 5/5 红线 verification commit message
- Backward-compatible (no breaking changes without ADR)

### §9.2 Quarterly review (§VIII #29 cadence)
- Q1 (Jan 1): Disaster drill Tier 1
- Q2 (Apr 1): Disaster drill Tier 1+2
- Q3 (Jul 1): Disaster drill Tier 2+3
- Q4 (Oct 1): Full Tier 1+2+3 drill + cumulative review

### §9.3 Monthly closure progress
- Plan v8 closure delta per month
- Phase J/K/L progress vs roadmap
- LL/ADR sediment count per month
- Failed direction registry maintenance

---

## §10 Decision Triggers + Stop Conditions

### §10.1 Phase J continuation criteria
- Phase B-2 live trading stable ≥ 7 consecutive trading days
- 0 P0 incidents requiring rollback
- 5/5 红线 sustained throughout

### §10.2 Phase J halt triggers
- Any P0 incident during live trading → halt Phase J, fix incident first
- LL count growth > 5/week (excessive new lessons) → freeze + audit
- ADR proliferation > 2/week without merge → pause + decide

### §10.3 Phase K gating criteria
- Phase J Week 1-8 complete with no rollbacks
- All sedimented design docs marked APPROVED post-implementation review
- Test coverage maintained ≥ baseline (24 fail max sustained)

---

## §11 Cross-ref

- **PR #383**: cumulative closure batch (97% Plan v8 closure)
- **ADR-085**: Path B Phase B-1/B-2 (live restart)
- **ADR-086**: Celery周期 restart (Tier 1 deployment Week 1)
- **§VIII #29**: Audit Cadence Calendar (quarterly review integration)
- All design docs referenced live in `docs/design/*.md` (8 files) + `docs/runbook/*.md`

---

**Maintained by**: CC autonomous Day 1 morning push (2026-05-20)
**Status**: Roadmap sediment, sequenced by risk + dependency
**Triggers**: Phase B-2 5-27 Wed live flip + 1 week stability gate
**Next update**: 5-27 Phase B-2 trigger evening (Week 1 kickoff sediment)
