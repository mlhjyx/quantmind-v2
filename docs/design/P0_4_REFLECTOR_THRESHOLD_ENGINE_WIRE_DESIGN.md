# P0-4 Reflector → ThresholdEngine Wire Design

> **Plan v8 P0-4 closure prep** — design only, multi-week implementation deferred.
> **Source**: V3 §8.3 lesson loop + V3 §S7 dynamic threshold engine
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 P0-4)**:
- RiskReflector V4-Pro 5-dim reflection runs Sunday 19:00 + monthly 1st 09:00 (TB-4b Beat)
- Reflection sediment → `docs/risk_reflections/YYYY_WW.md` + RAG (risk_memory pgvector)
- **0 closed-loop**: reflections do NOT auto-adjust DynamicThresholdEngine thresholds
- Threshold adjustments require manual review + ADR sediment

**Why wire P0-4**:
- V3 §S7 design intent: thresholds adapt to market regime + lesson learnings
- Manual review bottleneck = 1 person (bus factor 1)
- Auto-wire enables continuous improvement loop (V3 §16 Bull/Bear LLM debate parallel)

**Risk**:
- Auto-adjusting thresholds can drift unsafe directions (LL-013/014 mf_divergence pattern)
- Need guardrails: bounded adjustments + human-in-loop weekly review

---

## §2 Architecture Sketch

### §2.1 Current state (5-20)

```
RiskReflector Beat (Sun 19:00) → ReflectionInput (4 sources) → V4-Pro inference
    → ReflectionOutput (5 dims: detection / threshold / action / data / methodology)
    → docs/risk_reflections/YYYY_WW.md sediment
    → risk_memory RAG INSERT (BGE-M3 embedding)
    ↘
    [DEAD END — no consumer of threshold dim]
```

### §2.2 Target state (post P0-4 wire)

```
RiskReflector Beat → ReflectionOutput.threshold (per-rule_id suggested adjustments)
    ↓
ThresholdProposalQueue (new table) — persists proposals with status
    ↓
[Path A: AUTO-WIRE]
    ThresholdEngine.apply_proposal() (bounded ±20% per cycle, max 1/week per rule)
    → DynamicThresholdEngine emit new rule.threshold
    → AlertRouter re-evaluates next tick
    ↓
[Path B: HUMAN-IN-LOOP WEEKLY] (preferred initial)
    Email/DingTalk weekly digest of proposed adjustments
    → User approves via /api/risk/threshold-proposals/approve
    → Same downstream as Path A
```

### §2.3 Decision: Path B initial (human-in-loop) → Path A after 3 months observation

**Rationale**:
- Auto-adjust threshold = directly modifies risk policy = need confidence
- Path B = AI suggests, human approves (low risk, slower learn rate)
- After 3 months of human-approved data, evaluate auto-wire safety

---

## §3 Schema

### §3.1 New table: risk_threshold_proposals

```sql
CREATE TABLE risk_threshold_proposals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source_reflection_id UUID,
  rule_id TEXT NOT NULL,
  current_threshold NUMERIC NOT NULL,
  proposed_threshold NUMERIC NOT NULL,
  pct_change NUMERIC GENERATED ALWAYS AS (
    100.0 * (proposed_threshold - current_threshold) / NULLIF(current_threshold, 0)
  ) STORED,
  rationale TEXT,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending / approved / rejected / superseded
  approved_at TIMESTAMPTZ,
  approved_by TEXT,
  applied_at TIMESTAMPTZ,
  CHECK (status IN ('pending', 'approved', 'rejected', 'superseded'))
);

CREATE INDEX idx_threshold_proposals_status ON risk_threshold_proposals(status, proposed_at DESC);
CREATE INDEX idx_threshold_proposals_rule ON risk_threshold_proposals(rule_id);
```

### §3.2 Guardrails table: risk_threshold_history (sustained existing OR new)

Per-rule_id timeline of all applied thresholds (audit trail).

---

## §4 Implementation Phases

### §4.1 Phase 1 (Week 1): Schema + RiskReflector hook

- Add `risk_threshold_proposals` table migration
- RiskReflector POST output → INSERT into proposals (status=pending)
- Bounded validation: reject proposals where `|pct_change| > 20%`
- Test: existing reflector e2e + 1 proposal verify

### §4.2 Phase 2 (Week 2): User approval API + DingTalk digest

- `GET /api/risk/threshold-proposals/pending` — list pending proposals
- `POST /api/risk/threshold-proposals/{id}/approve` — admin token auth
- `POST /api/risk/threshold-proposals/{id}/reject` — admin token auth
- Weekly DingTalk digest (Sun 20:00, post reflector run)

### §4.3 Phase 3 (Week 3): ThresholdEngine wire + audit trail

- DynamicThresholdEngine.apply_proposal() — on approval status transition
- Audit row to risk_threshold_history (current → applied transition)
- Test: end-to-end reflector → proposal → approve → engine pick up

### §4.4 Phase 4 (Month 2+): Backtest replay validation

- Re-backtest with hypothetical applied thresholds
- Surface adverse Sharpe / MDD changes pre-apply

### §4.5 Phase 5 (Month 4+): Auto-wire evaluation

- After 3 months of human-approved data:
  - Approval rate by rule_id
  - Post-apply alpha impact
  - Decision: AUTO-WIRE eligible? Per-rule basis? Bounded auto-apply?

---

## §5 Alternatives Considered

### Alt 1: Direct auto-wire (rejected)
- Risk: reflector hallucination / LLM drift directly modifies risk policy
- Mitigation needs: bounded adjustments + rollback path
- Decision: defer until human-in-loop proven (3 months)

### Alt 2: Read-only weekly report (current state)
- Current behavior: reflections sediment to docs/risk_reflections/, manual review
- Limitation: 0 closure loop, bus factor 1 bottleneck

### Alt 3: Multi-LLM consensus (V3 §16 Bull/Bear parallel)
- Bull/Bear/Judge consensus on threshold proposals
- Adds latency + complexity, deferred Phase J

### Alt 4: Backtest gate (mandatory)
- Every approved proposal must pass backtest replay verification
- Adds Week 4 phase (above)

---

## §6 Effort Estimate

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Schema + reflector hook | 2-3 days | None |
| 2 API + DingTalk digest | 3-4 days | Phase 1 |
| 3 ThresholdEngine wire | 2-3 days | Phase 2 |
| 4 Backtest replay validation | 5-7 days | Phase 3 + backtest infra |
| 5 Auto-wire evaluation | 1 day decision + per-rule analysis | Phase 4 + 3 months observation |

**Total to Phase 3 (human-in-loop closure)**: ~2 weeks
**Total to Phase 5 (auto-wire)**: ~4-5 months

---

## §7 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (design only sediment)
- Phase B-2 (5-27 Wed live flip): NOT prerequisite
- Phase J (post 5-27): Phase 1-3 candidate
- Phase J+2 (3 months post live restart): Phase 4-5 evaluation

---

## §8 Iron Law Compliance

- Iron Law 17: All DB writes via DataPipeline → adapt INSERT pattern
- Iron Law 31: ThresholdEngine pure compute (no IO in engine)
- Iron Law 32: Service-layer transaction owner
- Iron Law 33: Fail-loud on bounded violations
- Iron Law 41: UTC internal, Asia/Shanghai display

---

**Maintained by**: CC autonomous (Plan v8 P0-4 design sediment, 2026-05-20 Day 1)
**User decision required**: Phase 1-3 wire timing (Phase J post 5-27 OR earlier)
**Cross-ref**:
- V3 §8.3 RiskReflector lesson loop
- V3 §S7 DynamicThresholdEngine
- ADR-064 RiskReflector design
- backend/app/tasks/risk_reflector_tasks.py (current state)
- backend/qm_platform/risk/dynamic_threshold/ (engine module)
