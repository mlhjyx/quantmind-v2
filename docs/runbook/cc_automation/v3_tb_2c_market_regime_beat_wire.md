# V3 TB-2c Market Regime Beat Wire — Post-Merge Ops Runbook

**触发条件**: PR #335 (TB-2c) merged 后 user 一句话 (e.g. "应用 TB-2c Beat wire") 触发本 runbook.

**关联**: Plan v0.2 §A TB-2c (Beat schedule wire) + 铁律 44 X9 (post-merge ops checklist) + LL-141 4-step sediment.

## 前置检查 (CC 自动执行)

```powershell
# 1. main branch sync
cd D:\quantmind-v2
git checkout main
git pull --ff-only

# 2. verify celery_app.imports 含 market_regime_tasks
Select-String "market_regime_tasks" backend\app\tasks\celery_app.py

# 3. verify beat_schedule.py 含 3 entries
Select-String "risk-market-regime" backend\app\tasks\beat_schedule.py
```

**Expected**:
- `git pull` shows current main HEAD = post-TB-2c merge commit
- celery_app.py imports list includes `"app.tasks.market_regime_tasks"`
- beat_schedule.py has 3 entries: `risk-market-regime-0900` / `-1430` / `-1600`

## 资金 0 风险确认 (5/5 红线 sustained)

| 红线 | Pre-ops state | Post-ops expected | 验证 |
|------|---------------|-------------------|------|
| cash | ¥993,520.66 | ¥993,520.66 | xtquant query_asset(81001102) |
| 持仓 | 0 | 0 | xtquant query_position(81001102) |
| LIVE_TRADING_DISABLED | true | true | `Select-String "LIVE_TRADING_DISABLED" backend\.env` |
| EXECUTION_MODE | paper | paper | `Select-String "EXECUTION_MODE" backend\.env` |
| QMT_ACCOUNT_ID | 81001102 | 81001102 | `Select-String "QMT_ACCOUNT_ID" backend\.env` |

**0 broker mutation / 0 .env change** in this runbook — Beat wire is pure schedule registration.

## 执行步骤

### Step 1: Servy restart QuantMind-CeleryBeat AND QuantMind-Celery

```powershell
# Order matters: stop Beat first to prevent stale schedule, then restart both.
& "D:\tools\Servy\servy-cli.exe" stop --name="QuantMind-CeleryBeat"
& "D:\tools\Servy\servy-cli.exe" stop --name="QuantMind-Celery"

# Wait 30s for graceful Celery shutdown (沿用 CLAUDE.md 部署规则 Celery solo pool).
Start-Sleep -Seconds 30

# Restart Celery worker first so Beat dispatches to ready queue.
& "D:\tools\Servy\servy-cli.exe" start --name="QuantMind-Celery"
Start-Sleep -Seconds 10

# Restart Beat scheduler.
& "D:\tools\Servy\servy-cli.exe" start --name="QuantMind-CeleryBeat"

# Verify both running.
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-Celery"
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-CeleryBeat"
```

**Expected**: Both services show `Status: Running`.

### Step 2: Verify Beat picked up 3 new entries

```powershell
# Check beat log for schedule registration messages.
Get-Content D:\quantmind-v2\logs\celery-beat-stdout.log -Tail 50 |
  Select-String "risk-market-regime"
```

**Expected**: 3 entries logged with crontab `0 9 * * 1-5`, `30 14 * * 1-5`, `0 16 * * 1-5`.

### Step 3: 1:1 simulation (manual Beat fire, 反 wait for natural cadence)

```powershell
cd D:\quantmind-v2
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -c @"
from app.tasks.market_regime_tasks import classify_market_regime
result = classify_market_regime.apply(args=[], kwargs={'decision_id': 'tb2c-manual-smoke'}).get()
print('Result:', result)
"@
```

**Expected** (TB-2c stub provider sustained):
- `result.ok = True`
- `result.regime_id > 0` (BIGSERIAL生成)
- `result.regime ∈ {Bull, Bear, Neutral, Transitioning}` (Judge 输出, stub all-None 输入倾向 Neutral / Transitioning)
- `result.confidence ∈ [0, 1]`
- `result.cost_usd ≈ $0.001-0.01` (3 V4-Pro calls, ADR-036 cost estimate)
- Log: `[market-regime] STUB IndicatorsProvider active` (one-time warning per worker process)

### Step 4: Verify row inserted to market_regime_log

```powershell
$env:PGPASSWORD='quantmind'
& "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -c @"
SELECT regime_id, regime, confidence, cost_usd,
       to_char(timestamp, 'YYYY-MM-DD HH24:MI:SS TZ') AS ts,
       jsonb_array_length(bull_arguments) AS bull_n,
       jsonb_array_length(bear_arguments) AS bear_n,
       LEFT(judge_reasoning, 100) AS reasoning_preview
  FROM market_regime_log
 ORDER BY regime_id DESC LIMIT 5;
"@
```

**Expected**: Latest row from the manual smoke test, with:
- `regime` ∈ 4 valid labels (CHECK constraint enforced)
- `confidence` ∈ [0, 1]
- `bull_n = 3` + `bear_n = 3` (V3 §5.3 sustained)
- `judge_reasoning` non-empty Chinese text

### Step 5: Cleanup manual smoke row (optional)

```powershell
$env:PGPASSWORD='quantmind'
& "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -c @"
DELETE FROM market_regime_log
 WHERE judge_reasoning LIKE 'tb2c-manual-smoke%'
    OR regime_id IN (
       SELECT regime_id FROM market_regime_log
        ORDER BY regime_id DESC LIMIT 1
    );
"@
```

**Note**: Skip Step 5 if user wants to keep the smoke row as 1st audit baseline.

## 失败回滚

### Rollback A: Beat schedule disable (反 wire backup)

If 3 Beat entries cause unexpected behavior, comment out the 3 entries in `beat_schedule.py` + Servy restart:

```python
# beat_schedule.py
# "risk-market-regime-0900": { ... },  # TB-2c, restored 2026-XX-XX
# "risk-market-regime-1430": { ... },
# "risk-market-regime-1600": { ... },
```

### Rollback B: market_regime_log DDL rollback (only if schema corruption)

```powershell
$env:PGPASSWORD='quantmind'
& "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -f D:\quantmind-v2\backend\migrations\2026_05_14_market_regime_log_rollback.sql
```

**Risk**: All historical market_regime_log rows DELETED. Only use on schema corruption (反 rollback for behavioral concerns).

## STATUS_REPORT 归档

After successful Step 1-4, sediment a status entry to `memory/project_sprint_state.md` Session 53+15 handoff:
- 3 Beat entries registered: `risk-market-regime-0900` / `-1430` / `-1600`
- 1st manual smoke regime_id = X (verify with Step 4 output)
- Servy services restart timestamp
- 0 broker mutation / 0 .env change / 0 production code change to live trading path (5/5 红线 sustained)

## 关联

- **V3 spec**: §5.3 line 664 cadence "每日 9:00 + 14:30 + 16:00 3 次更新"
- **ADR**: ADR-036 (V4-Pro mapping) / ADR-064 (Plan v0.2 D2) / ADR-066 (Tier B context cumulative)
- **LL**: LL-097 (Beat schedule restart 必显式) / LL-141 (4-step post-merge ops SOP) / LL-159 (4-step preflight)
- **铁律**: 22 / 41 / 44 X9 (post-merge ops explicit checklist)
- **Existing pattern reference**: docs/runbook/cc_automation/v3_s10_c1_synthetic_cleanup.md (post-merge ops 体例)
