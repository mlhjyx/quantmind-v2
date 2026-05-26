# STATUS_REPORT — iter 191 Calendar Singleton Conn Bug ARCHIVE (cross-domain MID backlog stale)

> **Trigger**: iter 191 backlog burn-down — Calendar singleton conn bug (cross-domain MID backlog item, sustained from pre-digest #14)
> **Verdict**: **ARCHIVE — STALE BACKLOG ITEM**. Investigation finds underlying issues already fixed via Plan 1 + Plan 1.5 + Plan D (2026-05-20). 14/14 calendar tests PASS. No remaining bug surface.
> **Pattern**: §v9.49 reality re-grounding (6th cumulative application post-iter-188)

---

## §1 Investigation Findings

### Backlog history reconstruction

The "Calendar singleton conn bug" appears as backlog text in:
- `L4R_DIGEST_LOG.md` line 656 (digest #15 cluster summary)
- `L4R_DIGEST_LOG.md` line 690 (digest #15 iter 191+ recommendation)
- `STATUS_REPORT_2026_05_26_iter_188_reality_cycle.md` line 105 (iter 188 §8 candidate list)

Source: appears to predate digest #14 (iter 180), but no specific PR / finding doc creates it. Searched docs/audit/ + scripts grep — found 0 doc with "Calendar singleton conn bug" as primary subject. **The backlog item is a reference without a defining artifact**.

### Plan 1 (stdlib logger crash) — CLOSED earlier

Per `backend/tests/test_calendar_gate.py:60-74` regression test `test_stdlib_logger_skip_does_not_crash`:
> Regression (Plan 1 precondition find): every Beat caller passes a stdlib `logging.Logger`. The skip-log must NOT pass structlog-style kwargs — those raise TypeError on a stdlib Logger.info. This test guards that crash.

Implementation guard at `backend/qm_platform/calendar/__init__.py:171-173` — uses a single pre-formatted string compatible with both stdlib + structlog.

### Plan 1.5 (Layer 3 DB fallback) — CLOSED earlier

Per `calendar/__init__.py:144-151` docstring + `_resolve_trading_day` implementation (lines 196-246):
> Layer 3 (Plan 1.5): the helper runs a conn-backed TradingDayChecker so the local `trading_calendar` DB table (Layer 3) answers when the Tushare API is unreachable. ... A short-lived conn is opened from `app.services.db.get_sync_conn` (lazy) and closed after the single check.

Conn properly closed via `finally: conn.close()` (line 242-246).

### Plan D (2026-05-20) — CLOSED at iter ~136 timeframe

Per `calendar/__init__.py:54-76` docstring:
> Plan D (2026-05-20): 移除旧 `conn_factory` 形参 — 它是死且误导的 API:
> (1) 0 调用方传入 (system.py / daily_pipeline.py / 本模块内部全部无参调用);
> (2) singleton 语义下首次 init 后传入的 `conn_factory` 被静默忽略 (反铁律 33 — 静默忽略 = 隐性失败 footgun: API 签名暗示 per-call 可控, 实则无效)。
>
> 本 singleton 故意 conn-less (`CalendarProvider()` → TradingDayChecker Layer 4 heuristic): 进程级 singleton 不宜长持 DB 连接。

The singleton is conn-less by design — long-lived DB connection in a process-level singleton is anti-pattern. Caller-supplied short-lived conn pattern via `is_trading_day_today_or_skip(conn_factory=...)` is correct.

### TradingDayChecker._upsert_local commit safety

Per grep `backend/engines/trading_day_checker.py`:
```
153:            self._upsert_local(d, is_open)
196:    def _upsert_local(self, d: date, is_open: bool) -> None:
209:            self._conn.commit()
213:                self._conn.rollback()
```

`_upsert_local` explicitly commits at line 209 + rolls back at line 213 (exception path). No silent data loss.

## §2 Test Verification (Live)

```
.venv/Scripts/python.exe -m pytest backend/tests/test_calendar_gate.py -q --tb=line
..............                                                           [100%]
14 passed in 0.11s
```

14/14 PASS. Test coverage includes:
- bool return contract (trading day / non-trading day)
- stdlib logger crash regression (Plan 1)
- conn_factory build (Layer 3 DB-backed checker)
- Layer 3 reads local `trading_calendar` table
- conn_factory failure degrades gracefully (fail-safe per 铁律 33)

## §3 ARCHIVE Verdict + Sediment

**Verdict**: ARCHIVE — STALE BACKLOG ITEM.

**Reasoning**:
1. **0 defining artifact** — backlog reference without a specific PR / finding doc
2. **Underlying issues all closed** — Plan 1 (stdlib crash) + Plan 1.5 (Layer 3 DB) + Plan D (singleton conn-less design)
3. **14/14 tests PASS** — no remaining test gap
4. **Code review confirms correctness** — `finally: conn.close()` proper resource management, commit/rollback explicit in `_upsert_local`

**Closure mechanism**:
- L4R_DIGEST_LOG.md "Remaining: F9 DEFER + Plan 2.5 SimBroker + Calendar singleton conn bug" → next digest #16 will reflect "Calendar singleton conn bug = ARCHIVED iter 191 via this STATUS_REPORT"
- STATUS_REPORT_iter_188 line 105 → superseded by this doc

## §4 Cumulative §v9.49 Reality Re-Grounding (6th application)

| iter | reality catch | verdict |
|---|---|---|
| 164 | PHASE_J §1.3 manifest "Disabled since 4-29" stale | re-verified — schtask was actually fine |
| 175 | factor T+1 NATURAL_LAG ARCHIVE iter 171 | DISCONFIRMED — Layer 4 silent failure revealed |
| 179 | compute_daily_ic.py Layer 4 silent failure | ROOT CAUSE — DataPipeline.ingest fail-soft |
| 183 | PHASE_J §1.5 manifest "no event publish" stale | REFUTED — outbox publisher already wires |
| 188 | Servy services "running" status | CONFIRMED expected blocker (stale code uptime ~21h) |
| **191** | **Calendar singleton conn bug** | **ARCHIVED — Plan 1+1.5+D all closed** |

**Pattern reinforcement**: Backlog items dating from before Plan-name refactor cycles systematically need §v9.49 reality re-grounding before scheduling investigation work. 6th cumulative validation of LL-209 SOP.

## §5 Cross-domain MID Backlog Status Update

Post iter 191:
| Item | Status | iter closed |
|---|---|---|
| iter 179 compute_daily_ic.py Layer 4 silent failure | ✅ FIXED | iter 181 PR #508 |
| iter 177 reviewer P2-1 regime null-guard | ✅ FIXED | iter 182 PR #509 |
| W4-A LL-188 hook test_baseline drift | ✅ FIXED | iter 187 `ba477e6` |
| iter 167 pre-push smoke scope gap | ✅ FIXED | iter 189 `d54966d` |
| **Calendar singleton conn bug** | **✅ ARCHIVED (stale)** | **iter 191 this doc** |
| F9 DEFER | ⏳ pending | — |
| Plan 2.5 SimBroker | ⏳ pending (design effort) | — |

**5/7 closed (71% closure)** post iter 191. Remaining 2 items are either deferred-by-design (F9) or larger-scope design effort (SimBroker).

## §6 iter 192+ Hand-off

**Recommended**:
- (a) F9 DEFER triage — investigate what F9 references + verify if it's also a stale backlog item (mirror §v9.49 pattern)
- (b) Tier B Wave 5 MVP 5.1 PT 状态 page design start (parallel-eligible, frontend scope)
- (c) Servy elevated restart walkthrough (user touchpoint coming, runbook ready)
- (d) §v9.49 reality cycle (5-iter post-190 — due iter 195)

**iter 191 ship 三态** per LL-210: backend-only ✅ doc-sediment.

**红线 5/5 sustained iter 191 fresh**. **Cumulative iter 185-191 post-compaction**: ~2.5h / 1 PR / 2 hook fixes / 9 doc artifacts.

---

**Coordinator**: Claude Opus 4.7 (1M context), autonomous L4+R loop, §v9.49 reality re-grounding 6th application
**Backlog burn-down ratio**: 5/7 cross-domain MID closed = 71%
