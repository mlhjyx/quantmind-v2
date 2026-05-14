# V3 TB-4b RiskReflector Beat Wire — Post-Merge Ops Runbook

**触发条件**: PR (TB-4b) merged 后 user 一句话 (e.g. "应用 TB-4b Beat wire") 触发本 runbook.

**关联**: Plan v0.2 §A TB-4b (Beat schedule wire) + 铁律 44 X9 (post-merge ops checklist) + LL-141 4-step sediment + TB-2c v3_tb_2c_market_regime_beat_wire.md 体例 sustained.

## 前置检查 (CC 自动执行)

```powershell
# 1. main branch sync
cd D:\quantmind-v2
git checkout main
git pull --ff-only

# 2. verify celery_app.imports 含 risk_reflector_tasks
Select-String "risk_reflector_tasks" backend\app\tasks\celery_app.py

# 3. verify beat_schedule.py 含 2 entries
Select-String "risk-reflector-" backend\app\tasks\beat_schedule.py
```

**Expected**:
- `git pull` shows current main HEAD = post-TB-4b merge commit
- celery_app.py imports list includes `"app.tasks.risk_reflector_tasks"`
- beat_schedule.py has 2 entries: `risk-reflector-weekly` / `risk-reflector-monthly`
  (event_reflection has NO Beat entry — L1 event dispatch, data-driven not time-driven)

## 资金 0 风险确认 (5/5 红线 sustained)

| 红线 | Pre-ops state | Post-ops expected | 验证 |
|------|---------------|-------------------|------|
| cash | ¥993,520.66 | ¥993,520.66 | xtquant query_asset(81001102) |
| 持仓 | 0 | 0 | xtquant query_position(81001102) |
| LIVE_TRADING_DISABLED | true | true | `Select-String "LIVE_TRADING_DISABLED" backend\.env` |
| EXECUTION_MODE | paper | paper | `Select-String "EXECUTION_MODE" backend\.env` |
| QMT_ACCOUNT_ID | 81001102 | 81001102 | `Select-String "QMT_ACCOUNT_ID" backend\.env` |

**0 broker mutation / 0 .env change** in this runbook — Beat wire is pure schedule registration. TB-4b task body writes markdown file + (optional, DINGTALK_ALERTS_ENABLED-gated) DingTalk push only — **0 domain DB write**, 0 broker call. Note: `send_with_dedup` DingTalk helper writes `alert_dedup` dedup metadata (helper-internal, not domain data — sustained TB-2c market_regime alert path 体例).

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

### Step 2: Verify Beat picked up 2 new entries

```powershell
# Check beat log for schedule registration messages.
Get-Content D:\quantmind-v2\logs\celery-beat-stdout.log -Tail 50 |
  Select-String "risk-reflector"
```

**Expected**: 2 entries logged with crontab `0 19 * * 0` (Sunday weekly) and `0 9 1 * *` (月 1 日 monthly).

### Step 3: 1:1 simulation (manual task fire, 反 wait for natural cadence)

```powershell
cd D:\quantmind-v2
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -c @'
from app.tasks.risk_reflector_tasks import weekly_reflection
result = weekly_reflection.apply(args=[], kwargs={'decision_id': 'tb4b-manual-smoke'}).get()
print('Result:', result)
print('REPORT_PATH=' + result['report_path'])
'@
```

**Expected** (TB-4b stub input gatherer sustained):
- `result.ok = True`
- `result.period_label` = `YYYY_WXX` (ISO week format)
- `result.report_path` = `docs/risk_reflections/YYYY_WXX.md` — **capture for Step 5 cleanup**
- `result.total_candidates` ≥ 0 (V4-Pro 5 维反思 over stub input — empty-data path per reflector_v1.yaml, candidates may be 0)
- `result.dingtalk_sent` = False (DINGTALK_ALERTS_ENABLED default-off) OR True if enabled
- `result.dingtalk_reason` ∈ {"alerts_disabled", "no_webhook", "sent", "dedup_suppressed"}
- V4-Pro cost ≈ $0 (DeepSeek free-provider per ADR-063 sustained)

**Note**: TB-4b uses stub input (placeholder summaries). TB-4c wires real risk_event_log / execution_plans / trade_log / RiskMemoryRAG gathering — the smoke here validates the *cadence + sediment + push wire*, not the reflection content quality.

### Step 4: Verify markdown report written

```powershell
# Replace YYYY_WXX with the period_label from Step 3 output.
Get-Content D:\quantmind-v2\docs\risk_reflections\YYYY_WXX.md
```

**Expected**: markdown report with:
- `# RiskReflector 反思报告 — YYYY_WXX` header
- `## 综合摘要` section (V4-Pro overall_summary)
- 5 维 sections: `## Detection` / `## Threshold` / `## Action` / `## Context` / `## Strategy`
- footer 注 "参数候选需 user 显式 approve"

### Step 5: Cleanup manual smoke report (optional)

```powershell
# Replace YYYY_WXX with the period_label from Step 3 output.
Remove-Item D:\quantmind-v2\docs\risk_reflections\YYYY_WXX.md
```

**Note**: Skip Step 5 if user wants to keep the smoke report as 1st sediment baseline. The markdown report is NOT committed by the task — it is a plain file write; commit/PR flow for parameter candidates is TB-4d scope.

## 失败回滚

### Rollback A: Beat schedule disable (反 wire backup)

If 2 Beat entries cause unexpected behavior, comment out the 2 entries in `beat_schedule.py` + Servy restart:

```python
# beat_schedule.py
# "risk-reflector-weekly": { ... },  # TB-4b, restored 2026-XX-XX
# "risk-reflector-monthly": { ... },
```

### Rollback B: celery_app.py import revert (only if import error)

If `risk_reflector_tasks` import breaks Celery worker startup, comment out the import line in `celery_app.py` + Servy restart. (No DDL involved in TB-4b — markdown file write only, no schema to roll back.)

## STATUS_REPORT 归档

After successful Step 1-4, sediment a status entry to `memory/project_sprint_state.md` handoff:
- 2 Beat entries registered: `risk-reflector-weekly` (Sunday 19:00) / `risk-reflector-monthly` (月 1 日 09:00)
- 1st manual smoke report_path = `docs/risk_reflections/YYYY_WXX.md`
- Servy services restart timestamp
- 0 broker mutation / 0 .env change / 0 DB write / 0 production code change to live trading path (5/5 红线 sustained)

## 关联

- **V3 spec**: §8.1 line 918-921 cadence "每周日 19:00 + 每月 1 日 09:00 + 重大事件后 24h" / §8.2 line 939-957 (markdown 沉淀 + DingTalk 摘要)
- **ADR**: ADR-064 (Plan v0.2 D2) / ADR-069 候选 (TB-4 closure cumulative)
- **LL**: LL-097 (Beat schedule restart 必显式) / LL-141 (4-step post-merge ops SOP) / LL-159 (4-step preflight)
- **铁律**: 22 / 41 / 44 X9 (post-merge ops explicit checklist)
- **Existing pattern reference**: docs/runbook/cc_automation/v3_tb_2c_market_regime_beat_wire.md (TB-2c post-merge ops 体例 sustained)
