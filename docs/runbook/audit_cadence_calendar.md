# Audit Cadence Calendar — Plan v8 §VIII #29 Sediment (sustained LL-190 fix)

> **目的**: Plan v8 §VII heuristic #17 "Audit Self-Audit + Cadence" + §VIII #29 "Audit Cadence Calendar" 真 sediment. 反 LL-190 (plan v8 sediment-then-forget pattern) — sediment alone ≠ sustained enforcement, 需 explicit cadence trigger schedule.
>
> **Date**: 2026-05-19 Session 58+1 evening SH
> **Authors**: CC autonomous (LL-190 first audit-driven enforcement, sustained ADR-086 cadence drive)
> **Related**:
> - [LL-190](../../LESSONS_LEARNED.md#ll-190) (plan v8 sediment-then-forget pattern)
> - [LL-187](../../LESSONS_LEARNED.md#ll-187) (Frontend v3 W1-W6 sediment-then-forget parent)
> - [Plan v8 §VIII #29](`C:\Users\hd\.claude\plans\quizzical-snacking-fox.md`) — Audit Cadence Calendar (NEW v8)
> - [PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19](../audit/PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md) §0.4 + §7.3

## §1 4 Audit Trigger Conditions (per Plan v8 §VIII #29)

| # | Trigger | Frequency | Mechanism |
|---|---|---|---|
| A | **Post-LL incident P0** | Within 7d after P0 LL sediment | Reactive — auto fires after each new LL with severity=P0 |
| B | **Quarterly full audit** | Q1 / Q2 / Q3 / Q4 first Mon 03:00 SH | Scheduled — schtask `QuantMind_AuditCadenceQuarterly` |
| C | **Pre-cutover gate** | Tier A→B / paper→live / 重大架构变 | Manual — checklist 触发 |
| D | **Tech debt threshold** | LL > 200 OR ADR > 100 OR test fail > baseline+10 | Scheduled — Beat `audit-tech-debt-check-weekly` Mon 02:00 SH |

## §2 Last & Next Audit Dates (sustained cite)

| Audit type | Last execution | Next trigger |
|---|---|---|
| Quarterly full | 2026-05-18 evening (Plan v8 11 doc + 3 HTML mockup, ~5000 lines) | **2026-08-01 Mon 03:00 SH** (Q3 2026, scheduled) |
| Pre-cutover Path B Phase B-1 | 2026-05-19 Session 58+1 (ADR-085 launch) | **2026-05-27 Wed** (Phase B-2 live flip, sustained PHASE_B_2_PREFLIGHT_CHECKLIST) |
| Pre-cutover Wave 4 → Wave 5 | (未 triggered yet) | Triggered when Wave 4 4.1 batch 3.x closure (in-flight per QPB v1.16) |
| Pre-cutover capital scale ¥1M→¥10M | (未 triggered yet) | Triggered when AUM > ¥5M sustained 30d |
| Post-LL P0 mini-audit | 2026-05-19 (LL-188 + LL-189 + LL-190 三连击, this Session 58+1 sediment) | Next within 7d if new P0 LL |
| Tech debt threshold | ll_unique_ids=173 (hook reading) / actual ~192 (sustained LL-190 sediment) — **approaching 200 threshold** | Trigger when ll > 200 (likely Session 60+ 视进度) |

## §3 Quarterly Audit SOP (calendar-based trigger B)

### 3.1 Q3 2026-08-01 Mon 03:00 SH — Scheduled

**Pre-audit prep** (1 week prior, 2026-07-25 onwards):
- Fresh read CLAUDE.md / IRONLAWS.md / SYSTEM_STATUS.md / LESSONS_LEARNED.md
- Cumulative cite chain: Q1 audit 2026-04-01 (if exists) + Q2 audit 2026-05-18 (plan v8)
- Decide audit scope: full / focused (e.g. Wave 4 / Wave 5)
- Plan v8 sediment-then-forget pattern verify (沿用 LL-190 — sustained #VIII #26-#30 5 sugg status check)

**Audit execution** (1 day, 03:00 SH start):
- 沿用 Plan v8 framework — 11 Sections / 45 Dim / 20 Heuristic / 30 Suggestion
- Spawn 9 subagent across 3 batches + CC cross-validate gates
- Phase 3+3-bis Strategic Alternatives synthesis pass
- Output: ~11 audit doc + STATUS_REPORT cumulative

**Post-audit closure** (1 week after):
- LL/ADR sediment from findings
- 5d window observation (sustained PASS gate criteria)
- Sediment cadence update — schedule next quarterly audit

### 3.2 Q4 2026-11-01 Mon 03:00 SH — Scheduled

### 3.3 Q1 2027-02-01 Mon 03:00 SH — Scheduled

### 3.4 Q2 2027-05-01 Mon 03:00 SH — Scheduled

## §4 Tech Debt Threshold Audit (trigger D)

### 4.1 Thresholds (hard fence)

| Metric | Current (5-19) | Threshold | Distance |
|---|---|---|---|
| LL count (unique sections) | 173 (pre-commit hook) / ~192 (sustained LL-189+190 5-19) | > 200 | 8-27 LL to threshold |
| ADR count | 67 + ADR-085/086 = 67-68 (5-19) | > 100 | 32 ADR to threshold |
| Test fail count | 24 (Session 9 baseline) — actual unknown (last verify > 1 month) | baseline+10 = 34 | unknown sustained |
| Sprint state size | ~320 KB post archive (5-19) | > 800 KB | sustained 480 KB headroom |

### 4.2 Beat entry SOP — `audit-tech-debt-check-weekly`

每周一 02:00 SH 触发 (避开 trading hours + 避开 Sun 22:00 gp-weekly + Sun 19:00 reflector-weekly):

Query:
```sql
-- LL count via header pattern
SELECT count(*) FROM (
  SELECT regexp_matches(content, '^(### |## )LL-[0-9]+', 'g') FROM scheduler_log
  WHERE source='lessons_learned'
) lls;

-- ADR count via filesystem ls
SELECT count(*) FROM filesystem WHERE path LIKE 'docs/adr/ADR-%.md';

-- Test fail count via latest pytest run
SELECT fail_count FROM pytest_run_log ORDER BY run_at DESC LIMIT 1;
```

Action if any threshold exceeded:
- Push DingTalk alert P1 with cumulative status
- Open issue in next handoff: "tech debt threshold triggered, schedule mini-audit"
- Sediment STATUS_REPORT with threshold values

### 4.3 (Future) audit-tech-debt-check task

待 implement (沿用 ADR-086 Tier 2 体例 — meta_monitor rule extension OR dedicated Beat task).

## §5 Post-LL P0 Mini-Audit (trigger A)

### 5.1 Auto-trigger logic

每 P0 LL sediment 后, 7d 内自动 trigger mini-audit:

| LL severity | Mini-audit scope |
|---|---|
| P0 + 红线 | Cross-validate gates + 5-pillar deep dive (memory / process / DB / Beat / xtquant) |
| P0 silent NOT-GATING | LL-183 体例 — pytest verify + production path verify + sediment layer reverse-check |
| P0 sediment-related | LL-190 体例 — plan v8 framework re-check + enforcement mechanism audit |

### 5.2 Last 3 P0 mini-audits 触发

- LL-180 (2026-05-18 14:02 SH, V3 L4 STAGED asyncio bootstrap) → mini-audit completed via M1/M3 双管 fix
- LL-183 (2026-05-18 evening, dry-run silent NOT-GATING) → plan v8 audit (full quarterly equivalent)
- LL-188+189+190 (2026-05-19 Session 58+1) → THIS session (cumulative)

### 5.3 Next P0 trigger watch

- Phase B-2 5-27 Wed first live execute → potential P0 if anomaly (LL-191+ 候选)
- LL-182 long-run verify post Phase B-2 → potential P0 if 5-axis fix recurrence

## §6 Pre-Cutover Gate Audit (trigger C)

### 6.1 Active gates

| Cutover | Status | Audit timing |
|---|---|---|
| **Path B Phase B-1 → B-2 (paper → live)** | 5d window 5-20 → 5-26 active | 5-26 Tue evening gate (sustained PHASE_B_2_PREFLIGHT_CHECKLIST) |
| Wave 4 → Wave 5 (Operator UI start) | 待 batch 3.x closure | Triggered post batch 3.x ✅ |
| Capital ¥1M → ¥10M scaling | 待 sustained NAV > ¥5M for 30d | 沿用 S6 §25 + S7 §36 |
| LLM V4 → V5 (DeepSeek model upgrade) | 待 V5 public release | 沿用 S7 §35 + ADR-034 |

### 6.2 Pre-cutover audit SOP

沿用 ADR-027 §7 双 trigger 体例:
- Trigger 1: user "同意" decision
- Trigger 2: user "你执行" — CC autonomous 接力
- Audit: redline-guardian fresh spawn + 10-dim gate criteria + sediment STATUS_REPORT
- Post-cutover: 5d observation + LL/ADR sediment as warranted

## §7 Cadence Calendar Mechanism (sustained enforcement)

### 7.1 Tier 1 immediate (this Session sediment, 0 schtask)

Doc-only — this file. User manual aware + CC autonomous follow-through.

### 7.2 Tier 2 short-term (P2 future)

**Windows schtask** `QuantMind_AuditCadenceQuarterly`:
- Trigger: Q1/Q2/Q3/Q4 first Mon 03:00 SH
- Action: PowerShell script that:
  - reads this file §3.1-§3.4 next-trigger row
  - sends DingTalk reminder to user
  - sediment STATUS_REPORT skeleton

### 7.3 Tier 3 medium-term (Phase J)

**Celery Beat** `audit-cadence-tick`:
- crontab `0 3 1 1,4,7,10 *` (Q quarter starts)
- Action: 同 Tier 2 via Beat task

### 7.4 Tier 4 long-term (Phase J+)

**Audit findings DB tracker**: `audit_findings_tracker` table with status enum (open/partial/closed) — sustained S6 §VIII #10 sugg "Audit Findings Tracker" (currently PARTIAL — F-D78-* numbering exists, 0 DB table).

## §8 5d Window Observation Pattern (sustained LL-190 fix)

**Pattern**: 每次 pre-cutover gate (trigger C) → 5d observation window → gate evaluation. Sustained ADR-085 / Path B Phase B-1 体例.

**Why 5d**:
- 5 trading days (avoid weekend trading-hours-only Beat cadence gap)
- Sufficient for 重 task Beat fire (factor-lifecycle Fri 19:00 / gp-weekly Sun 22:00 / 月度 reflector 1日 09:00)
- 短 enough that user 不 fatigue, 长 enough that 5d cumulative pattern emerges
- 沿用 ADR-027 §2.1 #4 prerequisite (paper-mode 5d validated)

**Pattern modifications** (依 cutover type):
- Path B Phase B-1 → B-2 (paper→live): 5d (sustained)
- Wave 4 → 5 (Operator UI): may need 7d (more UI interaction observation)
- Capital scale ¥1M → ¥10M: 30d sustained NAV trend
- LLM V4 → V5: 14d cost-quality A/B verify

## §9 关联

- [Plan v8 §VIII #29](`C:\Users\hd\.claude\plans\quizzical-snacking-fox.md`) — original suggestion
- [LL-190](../../LESSONS_LEARNED.md#ll-190) — plan v8 sediment-then-forget pattern (本 doc 是 first audit-driven enforcement)
- [LL-187](../../LESSONS_LEARNED.md#ll-187) — Frontend v3 sediment-then-forget parent
- [PHASE_B_2_PREFLIGHT_CHECKLIST_2026_05_27](../audit/PHASE_B_2_PREFLIGHT_CHECKLIST_2026_05_27.md) — pre-cutover gate audit example (trigger C)
- [PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19](../audit/PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md) §0.4 + §7.3
- [ADR-086](../adr/ADR-086-celery-worker-periodic-restart-and-memory-monitor.md) — first audit-driven enforcement decision

---

**End Audit Cadence Calendar. Sustained enforcement requires Tier 2/3/4 schtask/Beat (future). Tier 1 doc sediment + CC autonomous follow-through is current state.**
