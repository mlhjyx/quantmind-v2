# V3 Tier A§5 Servy Elevated Restart — Phase J 4-MVP Runtime-Verified Ship Unblock

**触发条件**: user 一句话 (e.g. "应用 Servy elevated restart" / "解锁 Phase J runtime-verified") 触发本 runbook. 前置: Phase J 4 MVPs (4.5/4.6/4.7/4.8) 均已 backend-only ✅ shipped (post iter 185 confirmed). 此 runbook 一次操作 flip 全部 4 个 runtime-verified gate.

**关联**: LL-210 ship 三态 (backend-only → runtime-verified flip via Servy elevated restart) + Tier A§5 sustained 28+ iter blocker + 4 MVP 设计文档 (MVP_4_5/4_6/4_7/4_8) + sibling pattern `v3_hc_1b_meta_monitor_beat_wire.md` + 铁律 44 X9 (post-merge ops checklist) + LL-097 (Beat schedule restart 必显式) + LL-141 4-step sediment.

---

## 前置检查 (CC 自动执行 — 非 elevated)

```powershell
cd D:\quantmind-v2
git checkout main
git pull --ff-only

# Verify Phase J 4 MVPs merged
git log --oneline -20 | Select-String "iter (162|163|167|168|178|184|185)"
```

**Expected** (sustained as of 2026-05-26 iter 185):
- iter 184 PR #510 (MVP 4.8 trade event consumer) merged: `b80f27f`
- iter 178 PR #507 (MVP 4.7 RAG consumer) merged
- iter 167-168 (MVP 4.6 daily_reconciliation) merged
- iter 162-163 PR #498-#499 (MVP 4.5 L4 ExecutionPlanner) merged
- Latest main HEAD `8313172` (iter 185 closure) or later

```powershell
# Verify beat_schedule.py contains all 4 MVP entries
Select-String -Path backend\app\tasks\beat_schedule.py -Pattern "trade-event-risk-consumer-tick|daily-reconciliation|rag-embedding-backfill|risk-l1-realtime-tick|risk-l4-sweep" |
  Select-Object Line
```

**Expected**: 5 distinct Beat entries (L1 + L4 sweep + daily reconciliation + RAG backfill + trade event consumer).

```powershell
# Verify celery_app.py imports all 4 MVP task modules
Select-String -Path backend\app\tasks\celery_app.py -Pattern "realtime_risk_tasks|l4_sweep_tasks|daily_reconciliation|embedding_backfill_tasks|trade_event_risk_tasks"
```

**Expected**: 5 import lines present.

## 资金 0 风险确认 (5/5 红线 sustained 28+ days)

| 红线 | Pre-restart state | Post-restart expected | 验证方法 |
|------|-------------------|----------------------|---------|
| cash | ¥993,520.66 | ¥993,520.66 | xtquant query_asset(81001102) (post-restart QMTData 60s resync) |
| 持仓 | 0 | 0 | xtquant query_position(81001102) |
| LIVE_TRADING_DISABLED | true | true | `Select-String "LIVE_TRADING_DISABLED" backend\.env` |
| EXECUTION_MODE | paper | paper | `Select-String "EXECUTION_MODE" backend\.env` |
| QMT_ACCOUNT_ID | 81001102 | 81001102 | `Select-String "QMT_ACCOUNT_ID" backend\.env` |

**0 broker mutation / 0 .env change / 0 DB row mutation** in this runbook — pure service capacity ops (Servy CLI restart). All 4 MVPs are wired to fail-safe paths (paper-mode trading disabled, all task bodies fail-soft per 铁律 33).

## 执行步骤 (user touchpoint = elevated PowerShell required)

> **CRITICAL**: Steps 1-3 require **elevated PowerShell** (Servy CLI needs Administrator for service control). User must open `powershell.exe` as Administrator. Step 4-7 verification can run from non-elevated session.

### Step 1: Servy stop sequence (elevated)

```powershell
# Stop Beat first to prevent stale schedule fire during worker restart
& "D:\tools\Servy\servy-cli.exe" stop --name="QuantMind-CeleryBeat"
Start-Sleep -Seconds 5

# Stop worker (graceful Celery solo pool shutdown ~30s per CLAUDE.md 部署规则)
& "D:\tools\Servy\servy-cli.exe" stop --name="QuantMind-Celery"
Start-Sleep -Seconds 30

# Verify both stopped
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-Celery"
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-CeleryBeat"
```

**Expected**: Both `Status: Stopped`. If Celery times out at 30s, can extend to 60s — DO NOT force-kill (will lose in-flight task state).

### Step 2: Servy start sequence (elevated)

```powershell
# Start worker first so Beat can dispatch to ready queue
& "D:\tools\Servy\servy-cli.exe" start --name="QuantMind-Celery"
Start-Sleep -Seconds 15

# Verify worker registered all 5 task modules
Get-Content D:\quantmind-v2\logs\celery-stdout.log -Tail 100 |
  Select-String "Tasks include|risk\.realtime|risk\.l4|reconciliation|embedding_backfill|risk\.trade_event"

# Start Beat scheduler
& "D:\tools\Servy\servy-cli.exe" start --name="QuantMind-CeleryBeat"
Start-Sleep -Seconds 10

# Verify both running
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-Celery"
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-CeleryBeat"
```

**Expected**: Both `Status: Running`. Worker log shows 5 task registrations (or "Tasks include" line listing all `app.tasks.*` modules).

### Step 3: Verify Beat picked up all 5 entries (elevated or non-elevated)

```powershell
Get-Content D:\quantmind-v2\logs\celery-beat-stdout.log -Tail 100 |
  Select-String "trade-event-risk-consumer-tick|daily-reconciliation|rag-embedding-backfill|risk-l1-realtime|risk-l4-sweep"
```

**Expected**: 5 entries logged with their respective schedules:
- `trade-event-risk-consumer-tick` — 10s
- `daily-reconciliation-job` — crontab Mon-Fri 16:50
- `rag-embedding-backfill-job` — crontab daily 06:00 (or per MVP 4.7 schedule)
- `risk-l1-realtime-tick` — 1min
- `risk-l4-sweep-1min` — 1min

## 验证清单 (post-restart 5 min wait + non-elevated)

After ~5 minutes post-restart (allowing 10s × 30 ticks for trade event consumer + 1min × 5 ticks for L1/L4 + first 5min cycle complete):

### MVP 4.5 — L1 RealtimeRiskEngine + L4 STAGED planner (✅ runtime-verify)

```powershell
cd D:\quantmind-v2
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -c @'
from app.services.db import get_sync_conn
conn = get_sync_conn()
cur = conn.cursor()
cur.execute("""
    SELECT task_name, count(*), max(start_time)
    FROM scheduler_task_log
    WHERE task_name IN ('realtime_risk_engine_tick','l4_sweep_tick')
      AND start_time > NOW() - INTERVAL '10 minutes'
    GROUP BY task_name
    ORDER BY task_name
""")
for row in cur.fetchall():
    print(row)
conn.close()
'@
```

**Expected**:
- `realtime_risk_engine_tick`: ~5 rows / max(start_time) within last 1min
- `l4_sweep_tick`: ~5 rows / max(start_time) within last 1min

### MVP 4.6 — daily_reconciliation (runtime-verify deferred to next 16:50 weekday)

```powershell
.\.venv\Scripts\python.exe -c @'
from app.services.db import get_sync_conn
conn = get_sync_conn()
cur = conn.cursor()
cur.execute("""
    SELECT task_name, status, start_time
    FROM scheduler_task_log
    WHERE task_name='daily_reconciliation'
    ORDER BY start_time DESC LIMIT 5
""")
for row in cur.fetchall():
    print(row)
conn.close()
'@
```

**Expected**: Last 5 daily_reconciliation rows. Today's row appears at first 16:50 (Mon-Fri). Status='success' on healthy run (0 持仓 paper-mode → empty reconcile, 不 trigger risk_event_log).

### MVP 4.7 — RAG consumer + BGE-M3 embedding cron (runtime-verify deferred to next 06:00)

```powershell
.\.venv\Scripts\python.exe -c @'
from app.services.db import get_sync_conn
conn = get_sync_conn()
cur = conn.cursor()
cur.execute("""
    SELECT task_name, status, start_time, result_json
    FROM scheduler_task_log
    WHERE task_name='embedding_backfill_job'
    ORDER BY start_time DESC LIMIT 3
""")
for row in cur.fetchall():
    print(row)
# Also check risk_memory_event embedding coverage
cur.execute("""
    SELECT count(*) FILTER (WHERE embedding IS NOT NULL) AS with_emb,
           count(*) AS total
    FROM risk_memory_event
""")
print('embedding coverage:', cur.fetchone())
conn.close()
'@
```

**Expected**: First 06:00 backfill row appears next day. embedding coverage rises toward 100% over time.

### MVP 4.8 — Trade event StreamBus consumer (✅ runtime-verify, 10s cadence)

```powershell
.\.venv\Scripts\python.exe -c @'
from app.services.db import get_sync_conn
conn = get_sync_conn()
cur = conn.cursor()
cur.execute("""
    SELECT count(*) AS row_count, max(start_time) AS last_fire,
           sum((result_json->>'events_consumed')::int) AS total_events_consumed
    FROM scheduler_task_log
    WHERE task_name='trade_event_risk_consumer'
      AND start_time > NOW() - INTERVAL '10 minutes'
""")
print(cur.fetchone())
conn.close()
'@
```

**Expected**: row_count ≈ 60 (10s × 60 in 10min); last_fire within last 30s; total_events_consumed = 0 in paper-mode (no fills since 4-29 清仓).

```powershell
# Verify Redis consumer group created
& "redis-cli" XINFO GROUPS qm:fill:executed
```

**Expected**:
- Consumer group `risk-engine-fill-consumer` exists
- 1+ consumers (per worker process, derived hostname+pid)
- pending = 0 (no events to consume in paper-mode)
- last-delivered-id = "0-0" or initial position

## 失败回滚

### Rollback A: Beat schedule disable (单 MVP)

If 1 of the 4 MVP Beat entries causes unexpected behavior (e.g. exception spam in logs), comment out the entry in `beat_schedule.py` + Servy restart Beat only:

```python
# beat_schedule.py
# "trade-event-risk-consumer-tick": { ... },  # MVP 4.8 — disabled 2026-XX-XX due to <reason>
```

Then elevated:
```powershell
& "D:\tools\Servy\servy-cli.exe" restart --name="QuantMind-CeleryBeat"
```

### Rollback B: Worker import revert (only on celery_app.py import error)

If 1 of the task modules raises ImportError at worker boot (look for "Unable to load celery application" in `celery-stderr.log`), comment out the import line in `celery_app.py` + Servy restart Celery:

```python
# celery_app.py
# "app.tasks.trade_event_risk_tasks",  # MVP 4.8 — disabled
```

### Rollback C: Full Phase J disable (extreme — should never need)

Comment all 5 Beat entries + revert all 5 imports + restart both services. Documented for completeness; in 28+ days of design+impl no such crash observed.

## STATUS_REPORT 归档

After successful Step 1-3 + 5+ verification queries returning expected rows, sediment status entry to `memory/project_sprint_state.md` handoff + create new `docs/audit/STATUS_REPORT_<date>_servy_restart_phase_j_unblock.md`:

- Servy services restart timestamp (`Get-Service` Get-Date stamp pre + post)
- 4 MVPs `runtime-verified ✅` flip per LL-210 ship 三态
- scheduler_task_log row counts confirmed within expected ranges
- redis XINFO GROUPS verified consumer group `risk-engine-fill-consumer` created
- 5/5 红线 sustained (cash / 持仓 / LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID 0 change)
- 0 broker mutation / 0 .env change / 0 production code change

## 关联

- **MVP 设计**: `docs/mvp/MVP_4_5_*.md` / `MVP_4_6_*.md` / `MVP_4_7_*.md` / `MVP_4_8_*.md`
- **STATUS_REPORTs (4 MVPs closure cite source)**:
  - MVP 4.5: iter 154-163 PRs #495-#499 closure
  - MVP 4.6: iter 167-168 PRs #500-#502 + `STATUS_REPORT_2026_05_26_mvp46_closure.md`
  - MVP 4.7: iter 173-178 PRs #503-#507
  - MVP 4.8: iter 183-185 PR #510 + `STATUS_REPORT_2026_05_26_mvp48_closure.md`
- **ADR**: ADR-094 (PMS v1 retire — 1 of 4 MVPs related decisions) / ADR-039 (Calendar Gate) / Phase J defer manifest cite source
- **LL**: LL-097 (Beat schedule restart 必显式) / LL-141 (4-step post-merge ops SOP) / LL-159 (4-step preflight) / **LL-210 (ship 三态)** / LL-211 (4-layer SOP)
- **铁律**: 22 / 33 / 41 / 44 X9 (post-merge ops explicit checklist)
- **Sibling runbooks**: `v3_hc_1b_meta_monitor_beat_wire.md` / `v3_tb_4b_reflector_beat_wire.md` / `04_post_deploy_restart_cadence_sop.md`
- **Phase J defer manifest**: `docs/audit/PHASE_J_DEFER_MANIFEST_2026_05_20.md` (5-chain blocker tracker — closes §1.1-§1.5 runtime-verified ship tier on successful execution)
