# MVP 4.6 — daily_reconciliation 复活 + risk_event_log Wire (Phase J §1.3)

> **Created**: iter 164 (2026-05-26) via §v9.69 heuristic (design doc < 200 LOC → main CC, no agent fan-out needed; data gathered via direct Read/Grep/PowerShell)
> **Sediment trigger**: §v9.56 pivot ladder — Tier A§1 Phase J §1.1+§1.2 closed iter 163 (MVP 4.5 COMPLETE), §1.3 next in chain
> **Spec target**: ≤ 2 页 design doc per 铁律 24 + iter-friendly chunk decomposition per §v9.65 + sibling MVP_4_5 structure
> **Provenance**: docs/audit/PHASE_J_DEFER_MANIFEST_2026_05_20.md §1.3 (~30min schtask + ~2h code wire estimate)

---

## §1 Problem Statement (Phase J §1.3 reality re-grounded iter 164 per §v9.49)

**Phase J Defer Manifest §1.3 claim (2026-05-20)**:
> "`scripts/daily_reconciliation.py` schtask 已 Disabled 自 4-29 PT 清仓后. 真后果: mismatch 后只 DingTalk 单点告警, 无 risk_event_log audit row, trade_log repair 路径 0"

**Reality re-grounded iter 164 (2026-05-26 ~15:50 SH)** via `schtasks /Query /TN QuantMind_DailyReconciliation /V`:
- Scheduled Task State: **Enabled** (NOT Disabled — manifest claim 6-day stale)
- Last Run Time: **2026/5/26 15:40:01**, Last Result: **1** (exit code 1, NOT exit 0)
- Next Run Time: 2026/5/27 15:40:00

**Real root cause of exit=1** (`scripts/daily_reconciliation.py:84-97`):
```python
expected_mode = (os.environ.get("EXECUTION_MODE") or "").strip().lower()
if expected_mode == "paper": sys.exit(0)  # graceful skip
if expected_mode != "live": sys.exit(f"[FATAL] ... got {expected_mode!r}. Refusing ...")
```
Schtask launches `python.exe` without sourcing backend/.env → `os.environ["EXECUTION_MODE"]` is empty → falls through paper-mode guard → hits FATAL sys.exit with string message → exit code 1. The script never reaches QMT query / reconciliation / scheduler_task_log INSERT logic. **Net production impact: identical to Disabled — 0 reconciliation runs since schtask was edited (~PR #384 / Wave 3 fix1 era).**

**True work needed iter 164**:
1. Fix env-loading so schtask runs reach paper-mode graceful skip (exit 0) — restores schtask LastResult clean
2. Wire `risk_event_log` INSERT for mismatch events when EXECUTION_MODE=live (audit trail beyond single-point DingTalk)
3. Update PHASE_J Manifest §1.3 to reflect reality + LL append (§v9.49 reality re-grounding catch)

---

## §2 Design Sketch

Wire path (sibling pattern from MVP 4.5 Chunk 5 `execution_plan_persistence.py:102-127` canonical 12-column INSERT):
```
schtask QuantMind_DailyReconciliation (15:40 daily)
  → python daily_reconciliation.py
  → [Chunk 1] load_dotenv(backend/.env) at module top
  → expected_mode resolved correctly
  → IF paper → exit 0 (graceful skip, LastResult=0)
  → IF live  → run_reconciliation()
       → QMT query / DB query / mismatch detect
       → [Chunk 2] per-mismatch: INSERT risk_event_log row
         (strategy_id, execution_mode='live', rule_id='daily_reconciliation',
          severity='p1', code=mismatch.code, shares=qmt_shares - db_shares,
          reason=f'QMT={qmt} DB={db}', context_snapshot=mismatches_dict,
          action_taken='ALERT_FIRED' | 'AUDIT_ONLY',
          action_result={'fill_rate':..., 'total_diff':...},
          cadence='daily_recon', priority='P1')
       → existing DingTalk path + scheduler_task_log INSERT (unchanged)
```

**Pattern reuse**:
- `backend/app/services/risk/execution_plan_persistence.py:102` 12-column risk_event_log INSERT canonical
- 铁律 32: caller owns transaction (script `conn.commit()` at end already correct)
- 铁律 33: existing `# silent_ok:` annotation at L592-594 (failed-row write) preserved
- 铁律 35: `from app.services.db import get_sync_conn` already canonical (L36)
- 铁律 43: fail-loud schtask hardening already in place (L572-595 try/except + failed-row INSERT)
- 铁律 44 X9: schtask schedule unchanged — no post-merge ops needed

---

## §3 Chunk Decomposition (4 chunks, iter 165→168)

### Chunk 1 — Env Loading Fix + schtask Exit Cleanup (~60 LOC) — iter 165
- **Goal**: Schtask launch correctly loads backend/.env so EXECUTION_MODE resolves. Verify Last Result goes from 1 → 0 on next 15:40 fire.
- **Files**: MODIFY `scripts/daily_reconciliation.py` (add `from dotenv import load_dotenv; load_dotenv(PROJECT_ROOT / 'backend' / '.env')` after sys.path setup, before `from app.config import settings`)
- **New Beat**: No / **New DB**: No
- **Risk**: dotenv might already be loaded implicitly via pydantic-settings `from app.config import settings` — IF so, the bug is elsewhere (e.g. settings.EXECUTION_MODE vs os.environ). Mitigation: Chunk 1 test verifies via subprocess invocation matching schtask exact command.
- **Test**: pytest subprocess invocation `python.exe scripts/daily_reconciliation.py` with empty env → verify exit 0 + log "EXECUTION_MODE=paper detected"
- **§v9.49 verify post-merge**: next 15:40 fire LastResult should be 0 (sustained)

### Chunk 2 — risk_event_log INSERT for Mismatches (~150 LOC) — iter 166
- **Goal**: When EXECUTION_MODE=live AND mismatches detected, INSERT one risk_event_log row per significant mismatch (diff_pct > STOCK_DIFF_THRESHOLD=1%). Separate row for total_mv breach (P0). Audit row independent of DingTalk send (audit trail even when DingTalk suppressed/failed).
- **Files**: MODIFY `scripts/daily_reconciliation.py` (insert `_persist_mismatch_audit` helper after `send_alert` call sites at L527/L535)
- **New Beat/DB**: No (risk_event_log table already exists, sibling INSERT pattern proven iter 162 MVP 4.5 Chunk 5)
- **Risk**: `paper-mode` graceful skip at L91 never reaches mismatch path → Chunk 2 path is dormant until EXECUTION_MODE=live. Validated via unit test (mock environment as live). Mitigation: Chunk 3 smoke test mocks live mode for full path coverage.
- **Dependency**: Chunk 1 (Chunk 2 dormant until env loads correctly)
- **Test**: pytest mock QMT positions vs DB positions producing 2 mismatches → verify 2 risk_event_log rows inserted with correct severity (P1) + context_snapshot JSON + action_taken value

### Chunk 3 — Integration Smoke + scheduler_task_log Verify (~80 LOC) — iter 167
- **Goal**: pytest -m smoke test exercising full daily_reconciliation flow in mocked-live mode. Verify: scheduler_task_log row inserted with status='success' + risk_event_log rows present + correct fill_rate calc.
- **Files**: NEW `backend/tests/test_daily_reconciliation_smoke.py`
- **Risk**: Smoke flaky on non-trading-day → mitigation: monkeypatch `is_trading_day` to True. Mitigation 2: clean test fixtures DELETE old test rows before run.
- **Dependency**: Chunks 1+2 merged
- **Test**: Self-tested via the new smoke test

### Chunk 4 — PHASE_J Manifest Correction + LL Append + STATUS_REPORT (~50 LOC) — iter 168
- **Goal**: Update PHASE_J_DEFER_MANIFEST §1.3 to reflect reality (Enabled + exit=1 root cause) + LL append "manifest stale claim caught via §v9.49 reality re-grounding" + STATUS_REPORT closure note. Update `.omc/state/l4r_loop_state.md` MVP 4.6 closed marker.
- **Files**: MODIFY `docs/audit/PHASE_J_DEFER_MANIFEST_2026_05_20.md` §1.3 + APPEND `LESSONS_LEARNED.md` LL-2XX + NEW `docs/audit/STATUS_REPORT_2026_05_26_mvp46_recon_revival.md` + MODIFY `.omc/state/l4r_loop_state.md`
- **Dependency**: Chunks 1-3 merged + scheduled_task_log row from 5-27 15:40 fire showing LastResult=0
- **No tests** (doc-only governance closure per §v9.66 sediment SOP)

---

## §4 Cross-cutting

### ADR-DRAFT
- "Manifest stale-claim catch via reality re-grounding (§v9.49)" — document that PHASE_J §1.3 "Disabled since 4-29" claim drifted ~6 days from reality (Enabled + exit=1) because manifest was authored 2026-05-20 BEFORE the schtask Edit path that broke env loading. Pattern: any manifest claim about service state MUST be reality-re-grounded at sediment time, not just at creation.

### Frontend parity (§v9.43)
- Tier B Wave 5 MVP 5.4 (Risk Chain Dashboard) would visualize `risk_event_log` rows including daily_reconciliation P1 entries — gives operator a unified mismatch timeline beyond DingTalk single-shot. **No frontend chunk in this MVP** — data layer only. MVP 5.4 deferred to Wave 5.

### Reality verification (§v9.49 post-deploy)
- SQL: `SELECT * FROM scheduler_task_log WHERE task_name='reconciliation' AND start_time > NOW() - INTERVAL '2 days' ORDER BY start_time DESC` should show `status='success'` post-Chunk 1 next-day fire (currently 0 rows because FATAL exits before INSERT)
- SQL: `SELECT count(*) FROM risk_event_log WHERE rule_id='daily_reconciliation' AND ts > NOW() - INTERVAL '7 days'` — expect 0 during paper-mode (Chunk 2 dormant); flip to >0 only when EXECUTION_MODE=live + actual mismatches occur
- Schtask: `schtasks /Query /TN QuantMind_DailyReconciliation` Last Result = 0 sustained ≥ 3 daily fires post-Chunk 1

### Recommended order
**Chunk 1 → 2 → 3 → 4**

Rationale: 1 first because schtask is currently failing daily — env fix immediately restores observable health (LastResult=0). 2 second because it's the actual feature work but dormant in paper-mode. 3 third as integration gate covering both. 4 last as governance closure per §v9.66 sediment SOP.

---

## §5 Risk + STOP triggers

- **§6 carve-out NEGATIVE for this MVP**: 0 .env mutation / 0 broker write / 0 真账户 row / 0 红线 drift / 0 governance SSOT retroactive / 0 new Framework / 0 Architecture·Strategy level. All chunks are wire/audit/test work within existing infrastructure.
- **User authorization gates**:
  - (a) None for Chunk 1+2+3 (script/test/doc work)
  - (b) Schtask is already Enabled — no user re-enable needed (contradicts manifest claim)
  - (c) EXECUTION_MODE=live cutover is OUT OF SCOPE for this MVP — Chunk 2 path activates IF/WHEN user flips paper→live via separate authorization (ADR-027 / V3 §0.3 cutover gate)
- **红线 5/5 sustained**: cash ¥993,520.66 / 0 持仓 / paper / true / 81001102 — wire dormant in paper-mode, audit-only when live

---

## §6 Effort estimate

Per Phase J Defer Manifest §1.3 original estimate: **~30min schtask + ~2h code wire**. iter 164 reality re-grounding revealed env-loading bug → +1 chunk vs original (Chunk 1 wasn't anticipated). At ~30-60min per iter, expect **iter 165-168 = 4 iter cumulative** ≈ 2-4 hours work + 1 daily-fire verification window.

Post Chunk 4 closure: `daily_reconciliation.py` schtask LastResult=0 sustained + risk_event_log INSERT path ready for live-mode activation + Phase J §1.3 manifest reality-aligned. Phase J §1.4 (RAG consumer) + §1.5 (StreamBus trade event) remain as Tier A§1 backlog post this MVP.

---

**Provenance**: iter 164 direct main-CC investigation (Read scripts/daily_reconciliation.py:1-613 + execution_plan_persistence.py:1-162 + qmt_reconciliation_service.py:1-120 + PowerShell `schtasks /Query /TN QuantMind_DailyReconciliation /V`). Sibling pattern: MVP 4.5 Chunk 5 risk_event_log 12-column INSERT canonical (`execution_plan_persistence.py:102-127`). All cites verified at 2026-05-26 ~16:00 SH via fresh Read.
