# V3 HC-1b Meta-Monitor Beat Wire — Post-Merge Ops Runbook

**触发条件**: PR (HC-1b) merged 后 user 一句话 (e.g. "应用 HC-1b Beat wire") 触发本 runbook.

**关联**: Plan v0.3 §A HC-1b (meta_monitor_service + Beat wire) + 铁律 44 X9 (post-merge ops checklist) + LL-141 4-step sediment + v3_tb_4b_reflector_beat_wire.md 体例 sustained.

## 前置检查 (CC 自动执行)

```powershell
# 1. main branch sync
cd D:\quantmind-v2
git checkout main
git pull --ff-only

# 2. verify celery_app.imports 含 meta_monitor_tasks
Select-String "meta_monitor_tasks" backend\app\tasks\celery_app.py

# 3. verify beat_schedule.py 含 meta-monitor-tick entry
Select-String "meta-monitor-tick" backend\app\tasks\beat_schedule.py
```

**Expected**:
- `git pull` shows current main HEAD = post-HC-1b merge commit
- celery_app.py imports list includes `"app.tasks.meta_monitor_tasks"`
- beat_schedule.py has 1 entry: `meta-monitor-tick` (crontab `*/5 * * * *` — every 5min all hours)

## 资金 0 风险确认 (5/5 红线 sustained)

| 红线 | Pre-ops state | Post-ops expected | 验证 |
|------|---------------|-------------------|------|
| cash | ¥993,520.66 | ¥993,520.66 | xtquant query_asset(81001102) |
| 持仓 | 0 | 0 | xtquant query_position(81001102) |
| LIVE_TRADING_DISABLED | true | true | `Select-String "LIVE_TRADING_DISABLED" backend\.env` |
| EXECUTION_MODE | paper | paper | `Select-String "EXECUTION_MODE" backend\.env` |
| QMT_ACCOUNT_ID | 81001102 | 81001102 | `Select-String "QMT_ACCOUNT_ID" backend\.env` |

**0 broker mutation / 0 .env change** in this runbook — Beat wire is pure schedule registration. HC-1b task body does 2 read-only DB queries (`llm_call_log` + `execution_plans`) + (optional, DINGTALK_ALERTS_ENABLED-gated) DingTalk push only — **0 domain DB write**, 0 broker call. Note: `send_with_dedup` DingTalk helper writes `alert_dedup` dedup metadata (helper-internal, not domain data — sustained TB-4b reflector alert path 体例).

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

### Step 2: Verify Beat picked up the new entry

```powershell
Get-Content D:\quantmind-v2\logs\celery-beat-stdout.log -Tail 50 |
  Select-String "meta-monitor"
```

**Expected**: `meta-monitor-tick` entry logged with crontab `*/5 * * * *`.

### Step 3: 1:1 simulation (manual task fire, 反 wait for natural cadence)

```powershell
cd D:\quantmind-v2
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -c @'
from app.tasks.meta_monitor_tasks import meta_monitor_tick
result = meta_monitor_tick.apply(args=[], kwargs={}).get()
print('Result:', result)
'@
```

**Expected** (HC-1b — 2 real collectors + 3 no-signal):
- `result.ok = True`
- `result.evaluated = 5` (5 元告警 rules always evaluated)
- `result.triggered` = 0 在健康系统 (paper-mode) — LiteLLM 5min window 通常 0 失败 + 0 PENDING_CONFIRM plans; L1/DingTalk/News 是 no-signal collectors (HC-1b2 wires real source) → not triggered
- `result.pushed` = 0 (0 triggered) OR = triggered count
- `result.triggered_rules` = `[]` 在健康系统
- `result.at` = ISO timestamp

**Note**: HC-1b wires 2 real collectors (`llm_call_log` LiteLLM 失败率 + `execution_plans` STAGED overdue). L1 心跳 / DingTalk push status / News 全源 timeout are HC-1b **no-signal** collectors (无 clean queryable 源 — precondition 核 真值) — HC-1b2 instruments the real sources. The smoke here validates the *5min cadence + 2 real collector queries + push wire*, not full 5-rule coverage.

### Step 4: Verify alert_dedup row (only if triggered > 0)

```powershell
# Only relevant if Step 3 result.triggered > 0.
.\.venv\Scripts\python.exe -c @'
from app.services.db import get_sync_conn
conn = get_sync_conn()
cur = conn.cursor()
cur.execute("SELECT dedup_key, severity, source, fire_count FROM alert_dedup WHERE dedup_key LIKE 'meta_alert:%'")
for row in cur.fetchall():
    print(row)
conn.close()
'@
```

**Expected**: 0 rows in healthy paper-mode (0 triggered). If triggered, rows with `dedup_key='meta_alert:<rule_id>'`, `source='meta_monitor'`.

## 失败回滚

### Rollback A: Beat schedule disable (反 wire backup)

If the `meta-monitor-tick` entry causes unexpected behavior, comment out the entry in `beat_schedule.py` + Servy restart:

```python
# beat_schedule.py
# "meta-monitor-tick": { ... },  # HC-1b, restored 2026-XX-XX
```

### Rollback B: celery_app.py import revert (only if import error)

If `meta_monitor_tasks` import breaks Celery worker startup, comment out the import line in `celery_app.py` + Servy restart. (No DDL involved in HC-1b — 2 read-only queries only, no schema to roll back.)

## STATUS_REPORT 归档

After successful Step 1-3, sediment a status entry to `memory/project_sprint_state.md` handoff:
- 1 Beat entry registered: `meta-monitor-tick` (crontab `*/5 * * * *` — every 5min all hours)
- 1st manual smoke result (evaluated=5 / triggered=N / at=timestamp)
- Servy services restart timestamp
- 0 broker mutation / 0 .env change / 0 domain DB write / 0 production code change to live trading path (5/5 红线 sustained)

## 关联

- **V3 spec**: §13.3 元告警 (alert on alert) — 5 风控系统失效场景 (L1 心跳 / LiteLLM 失败率 / DingTalk push / News 全源 timeout / STAGED PENDING_CONFIRM >35min)
- **ADR**: ADR-072 (Plan v0.3 3 决议 lock) / ADR-073 候选 (HC-1 元监控 alert-on-alert closure)
- **LL**: LL-097 (Beat schedule restart 必显式) / LL-141 (4-step post-merge ops SOP) / LL-159 (4-step preflight)
- **铁律**: 22 / 41 / 44 X9 (post-merge ops explicit checklist)
- **Existing pattern reference**: docs/runbook/cc_automation/v3_tb_4b_reflector_beat_wire.md (TB-4b post-merge ops 体例 sustained)
