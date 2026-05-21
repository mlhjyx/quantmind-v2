# P0-17 Disaster Drill Simulation Design

> **Plan v8 P0-17 closure prep** — design + simulation script ready, production drill defer.
> **Source**: Plan v8 audit §16 HC-2c disaster drill pytest-only finding
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 P0-17)**:
- HC-2c disaster drill tests exist (pytest) but only validate code paths in mocks
- 0 production drill ever executed
- Risk: production incident response untested → fumbled recovery
- Industry SOP: monthly/quarterly chaos drills (Chubb GameDay, Netflix Simian Army)

**Why design now**:
- Phase B-2 (5-27 Wed) live restart = increased blast radius
- Quarterly cadence aligns with §VIII #29 Audit Cadence Calendar
- Phase J post live = first drill window

---

## §2 Disaster Scenarios (drill catalog)

### §2.1 Tier 1 — High frequency, low blast radius

| Scenario | Trigger | Expected Recovery |
|---|---|---|
| Servy service crash | `Stop-Service QuantMind-FastAPI` | AutoRestart=true picks up < 60s |
| Tushare API timeout | Mock 503 in `pull_tushare_daily.py` | 5 retry exhausted → DingTalk P1, fallback (P1-33) |
| Beat schedule paused | `celerybeat-schedule.dat` stale > 5min | `audit_beat_heartbeat.py` P0 alert |
| Schtask LastResult=1 | Inject script bug → schtask fail | `audit_schtask_freshness.py` P0 alert |

### §2.2 Tier 2 — Medium frequency, medium blast

| Scenario | Trigger | Expected Recovery |
|---|---|---|
| PG connection pool exhausted | LL-009 4-03 PG OOM pattern | Servy restart FastAPI → connections clear |
| Redis OOM | redis-cli flushdb (drill) | StreamBus reconnect, paper-mode unaffected |
| Celery worker leak (LL-189) | Sustained 24h worker (no restart) | ADR-086 schtask nightly restart |
| QMT disconnect (LL-180/182) | mock xtquant.disconnect | LL-182 5-axis fix sustained |

### §2.3 Tier 3 — Low frequency, high blast

| Scenario | Trigger | Expected Recovery |
|---|---|---|
| Disk full (D:\) | df check fails | DingTalk P0, pg_dump pause |
| .env corruption | LL-188 sediment drift scenario | pre-commit hook + manual revert |
| Broker API breach | xtquant returns invalid data | T+1 reconciliation flags |
| LIVE_TRADING_DISABLED accidentally false | LL-188 forensic pattern | Pre-commit guard (?新增) |

---

## §3 Drill Methodology

### §3.1 Read-only simulation script (Phase B-1 compatible)

```python
# scripts/disaster_drill_simulator.py
"""
Pure simulation — NO actual mutation, just validation:
- Walk Tier 1/2/3 scenario catalog
- For each: verify recovery path code EXISTS + reachable
- Report mock fire + expected response
"""
def simulate(scenario_id: str):
    # 1. Look up scenario config
    # 2. Verify recovery code path exists (grep -rn)
    # 3. Verify DingTalk alert path exists
    # 4. Verify rollback procedure documented
    # 5. Report PASS / GAP / DRIFT
```

### §3.2 Active production drill (Phase J post 5-27)

Quarterly cadence (per §VIII #29):

```
Q1 (Jan 1 evening): Tier 1 drills (low-risk)
Q2 (Apr 1 evening): Tier 1 + 1 Tier 2 drill
Q3 (Jul 1 evening): Tier 2 + 1 Tier 3 drill
Q4 (Oct 1 evening): Full Tier 1+2+3 (most stress)
```

**Pre-flight (all drills)**:
- LIVE_TRADING_DISABLED=true (paper-mode)
- 0 持仓 (Sun evening / no trading windows)
- Servy backup state captured
- DingTalk PRE-NOTIFICATION (`[DRILL] Disaster simulation starting...`)

**Execution**:
1. Trigger scenario (mock / actual)
2. Observe recovery (timer + logs + alerts)
3. Verify SLA: detection < 5min, recovery < 30min, alert reaches DingTalk
4. Rollback to pre-drill state

**Post-drill**:
- STATUS_REPORT sediment
- Recovery time vs SLA delta
- LL candidate for gaps surfaced
- LESSONS update

---

## §4 Simulation Script Scope (Phase 1)

scripts/disaster_drill_simulator.py outline:

```python
SCENARIOS = [
    {"id": "tier1_servy_crash", "tier": 1, "recovery_code": "scripts/service_manager.ps1"},
    {"id": "tier1_tushare_timeout", "tier": 1, "recovery_code": "scripts/pull_tushare_daily.py"},
    {"id": "tier1_beat_paused", "tier": 1, "recovery_code": "scripts/audit_beat_heartbeat.py"},
    {"id": "tier1_schtask_fail", "tier": 1, "recovery_code": "scripts/audit_schtask_freshness.py"},
    {"id": "tier2_pg_oom", "tier": 2, "recovery_code": "scripts/service_manager.ps1"},
    {"id": "tier2_redis_oom", "tier": 2, "recovery_code": "backend/app/core/stream_bus.py"},
    {"id": "tier2_celery_leak", "tier": 2, "recovery_code": "ADR-086"},
    {"id": "tier2_qmt_disconnect", "tier": 2, "recovery_code": "backend/engines/broker_qmt.py"},
    {"id": "tier3_disk_full", "tier": 3, "recovery_code": "MISSING"},  # gap
    {"id": "tier3_env_corruption", "tier": 3, "recovery_code": "scripts/pre-commit-validate.py"},
    {"id": "tier3_broker_breach", "tier": 3, "recovery_code": "scripts/daily_reconciliation.py"},
    {"id": "tier3_live_disabled_false", "tier": 3, "recovery_code": "MISSING"},  # gap
]

def simulate(scenario):
    # Verify recovery code path exists
    if scenario["recovery_code"] == "MISSING":
        return {"status": "GAP", "reason": "No recovery code documented"}
    # ... continue
```

---

## §5 Implementation Phases

### §5.1 Phase 1 (Week 1): Simulation script
- `scripts/disaster_drill_simulator.py` (~150 lines)
- Walk 12 scenarios, report PASS/GAP/DRIFT
- Phase B-1 compatible (0 mutation)

### §5.2 Phase 2 (Week 2): Frontend integration
- New page `frontend/src/pages/DisasterDrill.tsx`
- Browse scenarios + last-simulation results
- Trigger production drill (admin token)

### §5.3 Phase 3 (Quarterly post 5-27): Production drills
- Q3 2026 first production Tier 1 drill (Sun evening)
- STATUS_REPORT sediment per drill
- Annual cumulative review

---

## §6 Gap Analysis (surface today)

From scenario catalog:
- **Tier 3 disk full** — 0 recovery code (no `df`-style monitor)
- **Tier 3 LIVE_TRADING_DISABLED accidentally false** — only pre-commit hook, no runtime guard

**Action items** (Phase J):
- Write `scripts/audit_disk_space.py` (~50 lines, similar pattern to audit_beat_heartbeat.py)
- Write `scripts/audit_redline_runtime.py` (~50 lines, polls .env field hash periodically)

---

## §7 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (design only)
- Phase B-2 (5-27 Wed): NOT prerequisite
- Phase J (post 5-27): Phase 1 simulation script priority
- Phase J+1 (Q3 2026): First Tier 1 drill (Sun evening)
- Phase J+2 (Q4 2026): Cumulative Tier 1+2+3

---

## §8 Iron Law Compliance

- Iron Law 33: All drill outputs fail-loud (no silent pass)
- Iron Law 38: Disaster drill catalog 是 long-term Blueprint memory (sustained cross-session)
- Iron Law 41: Drill execution time UTC + Asia/Shanghai

---

**Maintained by**: CC autonomous (Plan v8 P0-17 design sediment, 2026-05-20 Day 1)
**Cross-ref**:
- Plan v8 §16 HC-2c finding
- §VIII #29 Audit Cadence Calendar (quarterly cadence integration)
- ADR-085 / ADR-086 (recovery context for Path B-1/B-2)
- Recovery code: scripts/audit_*.py (P0-5/6/15) + service_manager.ps1
