# V3 HC-2b2 G7 Broker Plan Stuck Sweep — Post-Merge Ops Runbook

**触发条件**: PR (HC-2b2) merged 后 user 一句话 (e.g. "应用 HC-2b2 Beat wire") 触发本 runbook.

**关联**: Plan v0.3 §A HC-2b2 (G7 broker plan stuck sweep) + V3 §14 mode 12 + 铁律 44 X9 (post-merge ops checklist) + LL-141 4-step sediment + v3_hc_1b_meta_monitor_beat_wire.md 体例 sustained.

## 前置检查 (CC 自动执行)

```powershell
cd D:\quantmind-v2
git checkout main
git pull --ff-only

# verify celery_app.imports 含 l4_sweep_tasks (已有, HC-2b2 0 改 celery_app)
Select-String "l4_sweep_tasks" backend\app\tasks\celery_app.py

# verify beat_schedule.py 含 risk-l4-broker-stuck-sweep entry
Select-String "risk-l4-broker-stuck-sweep" backend\app\tasks\beat_schedule.py
```

**Expected**:
- `git pull` shows current main HEAD = post-HC-2b2 merge commit
- celery_app.py imports list already includes `"app.tasks.l4_sweep_tasks"` (HC-2b2 adds the `sweep_stuck_broker_plans` task to the *existing* module — 0 celery_app change)
- beat_schedule.py has 1 NEW entry: `risk-l4-broker-stuck-sweep` (crontab `*/5 * * * *` — every 5min all hours)

## 资金 0 风险确认 (5/5 红线 sustained)

| 红线 | Pre-ops state | Post-ops expected | 验证 |
|------|---------------|-------------------|------|
| cash | ¥993,520.66 | ¥993,520.66 | xtquant query_asset(81001102) |
| 持仓 | 0 | 0 | xtquant query_position(81001102) |
| LIVE_TRADING_DISABLED | true | true | `Select-String "LIVE_TRADING_DISABLED" backend\.env` |
| EXECUTION_MODE | paper | paper | `Select-String "EXECUTION_MODE" backend\.env` |
| QMT_ACCOUNT_ID | 81001102 | 81001102 | `Select-String "QMT_ACCOUNT_ID" backend\.env` |

**0 broker mutation / 0 .env change** in this runbook — Beat wire 是 pure schedule registration. `sweep_stuck_broker_plans` task body: SELECT stuck plans (`execution_plans` read) + per-plan retry `StagedExecutionService.execute_plan`. In paper-mode the broker_call = `RiskBacktestAdapter` (0 真 broker call — `is_paper_mode_or_disabled()` gate). The per-plan retry does `execution_plans` UPDATE (status writeback) — that is the *intended* reconciliation behavior, NOT a 红线 mutation (paper-stub broker, 0 真账户 touch). 元告警 push (BROKER_PLAN_STUCK) writes `alert_dedup` dedup metadata (helper-internal).

## 执行步骤

### Step 1: Servy restart QuantMind-CeleryBeat AND QuantMind-Celery

```powershell
# Order matters: stop Beat first to prevent stale schedule, then restart both.
& "D:\tools\Servy\servy-cli.exe" stop --name="QuantMind-CeleryBeat"
& "D:\tools\Servy\servy-cli.exe" stop --name="QuantMind-Celery"

# Wait 30s for graceful Celery shutdown (沿用 CLAUDE.md 部署规则 Celery solo pool).
Start-Sleep -Seconds 30

# Restart Celery worker first so Beat dispatches to a ready queue.
& "D:\tools\Servy\servy-cli.exe" start --name="QuantMind-Celery"
Start-Sleep -Seconds 10

# Restart Beat scheduler.
& "D:\tools\Servy\servy-cli.exe" start --name="QuantMind-CeleryBeat"

# Verify both running.
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-Celery"
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-CeleryBeat"
```

**Expected**: Both services show `Status: Running`.

### Step 2: Verify Beat picked up the new entry (natural cadence)

`*/5` 自然触发 — 等下一个 5min 边界 (e.g. HH:05 / HH:10), 然后:

```powershell
Get-Content D:\quantmind-v2\logs\celery-beat-stderr.log -Tail 50 |
  Select-String "risk-l4-broker-stuck-sweep"
```

**Expected**: `Scheduler: Sending due task risk-l4-broker-stuck-sweep` logged at the `*/5` boundary.

### Step 3: 1:1 simulation (manual task fire, 反 wait for natural cadence)

```powershell
cd D:\quantmind-v2
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -c @'
from app.tasks.l4_sweep_tasks import sweep_stuck_broker_plans
result = sweep_stuck_broker_plans.apply(args=[], kwargs={}).get()
print('Result:', result)
'@
```

**Expected** (healthy paper-mode — 0 stuck plans typical):
- `result.ok = True`
- `result.scanned = 0` (健康系统 0 plan 卡在 CONFIRMED/TIMEOUT_EXECUTED > 5min — l4_sweep 每分钟推进 PENDING_CONFIRM, webhook CONFIRM inline 执行)
- `result.resolved = 0` / `result.still_stuck = 0` / `result.still_stuck_plan_ids = []`
- `result.batch_limited = False`

**Note**: 若 `scanned > 0` 表示真有 plan 卡住 — task 会 retry `execute_plan`; retry 成功 → `resolved`; retry 仍失败 → `still_stuck` + BROKER_PLAN_STUCK 元告警 (P0). 这是设计行为 (reconciliation safety net).

## 失败回滚

### Rollback: Beat schedule disable (反 wire backup)

If the `risk-l4-broker-stuck-sweep` entry causes unexpected behavior, comment out the entry in `beat_schedule.py` + Servy restart:

```python
# beat_schedule.py
# "risk-l4-broker-stuck-sweep": { ... },  # HC-2b2 G7, restored 2026-XX-XX
```

No DDL involved in HC-2b2 — `sweep_stuck_broker_plans` does read + status-writeback UPDATE only, no schema to roll back.

## STATUS_REPORT 归档

After successful Step 1-3, sediment a status entry to `memory/project_sprint_state.md` handoff:
- 1 Beat entry registered: `risk-l4-broker-stuck-sweep` (crontab `*/5 * * * *` — every 5min all hours)
- 1st manual smoke result (scanned=N / resolved=N / still_stuck=N)
- Servy services restart timestamp
- 0 broker mutation / 0 .env change / 5/5 红线 sustained

## 关联

- **V3 spec**: §14 mode 12 (broker_qmt 接口故障 — sell 单提交但 status 未推进)
- **ADR**: ADR-074 候选 (HC-2 失败模式 enforce + 灾备演练 closure)
- **LL**: LL-097 (Beat schedule restart 必显式) / LL-141 (4-step post-merge ops SOP)
- **铁律**: 22 / 41 / 44 X9 (post-merge ops explicit checklist)
- **Existing pattern reference**: docs/runbook/cc_automation/v3_hc_1b_meta_monitor_beat_wire.md (HC-1b post-merge ops 体例 sustained)
