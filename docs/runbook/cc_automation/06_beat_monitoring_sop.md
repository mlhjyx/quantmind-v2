# 06 — CeleryBeat Schedule Monitoring SOP

> **Why**: sub-PR 8b-cadence-B post-merge ops verify 5-07 22:35 catch CeleryBeat **Stopped** 沿用 prior session 21:50 末 Beat Running 体例 — 真**Beat 自 crash silent drift** sustained 反 alert. X9 (铁律 44) "Beat schedule / config 注释 ≠ 真停服, 必显式 restart" 真**reverse case** sediment.
> **触发**: post-merge ops checklist + daily Beat health check + 任 cron-driven task 真**预期触发未触发** debug.

## 真**Beat health 4-layer verify**

### Layer 1 — Servy CLI status
```powershell
D:\tools\Servy\servy-cli.exe status --name QuantMind-CeleryBeat
# Expected: "Service status: Running"
```

### Layer 2 — Process timestamp 真值
```powershell
Get-CimInstance -Query "select ProcessId,CreationDate,CommandLine from Win32_Process where Name='python.exe'" `
  | Where-Object { $_.CommandLine -match "celery.*beat" } `
  | Select-Object ProcessId, CreationDate
# Expected: CreationDate 真**post 最近 deploy / restart** sustained
```

### Layer 3 — celerybeat-schedule.dat shelve introspect (gold standard)
```python
import shelve
db = shelve.open('D:/quantmind-v2/celerybeat-schedule', flag='r')
entries = db.get('entries', {})
print(f'Total entries: {len(entries)}')
for name, entry in sorted(entries.items()):
    print(f'  {name}: {entry.schedule}')
db.close()
```
真**6 entries (4 现存 + 2 News)** sustained ADR-043 §Decision #2 cron `0 3,7,11,15,19,23 * * *`.

### Layer 4 — celery-beat-stderr.log 真**Sending due task** ticking
```bash
tail -50 D:/quantmind-v2/logs/celery-beat-stderr.log | grep -E "beat: Starting|Sending due task|ERROR"
# Expected: regular ticks (e.g., outbox-publisher-tick every 30s) + last "beat: Starting..." 真值
```

## 真**alert / monitoring 体例** (chunk C-SOP-B 真预约 implementation)

**Layer 1 candidate** (manual SOP, 本 SOP 体例):
- Daily Servy CLI status check (cron / schtask)
- 真**Stopped detect** → restart + DingTalk alert

**Layer 2 candidate** (sub-PR 9 真预约 implementation):
- DingTalk push 触发 Beat schedule miss / scheduler_task_log 真**预期 task name 反 fire** alert
- `LL_AUDIT_INSERT_FAILED` + `BEAT_DEAD_DETECT` 双类 alert

## 真**反 anti-pattern** sediment

- ❌ Beat schedule comment-out 假设 真**真停服** sustained — 沿用 LL-097 X9 reverse case (代码 commented 沿用 真生产 active sustained 真值漂移)
- ❌ Servy CLI "Running" sustained ack Beat 真**ticking** sustained — 真**process exists 反 ack scheduler tick** 沿用 dead loop / startup hang reverse case
- ❌ "schedule.dat exists" 假设 Beat 沿用 read 真**latest schedule code** sustained — 真**post-deploy restart 必触发 schedule reload**

## 真生产真值 evidence (5-07 cumulative)

| timestamp | Beat status | source | trigger |
|---|---|---|---|
| 21:20:26 | Started (banner) | Servy restart W0 | sub-PR 8b-cadence-B post-merge ops Step 1 |
| 21:20:39 | Schedule.dat ticked (6 entries) | shelve introspect | gold-standard verify |
| 22:35 | Stopped (Get-Service / Servy CLI) | Phase 0 fresh verify | reverse case catch |
| 22:50 | Running (X9 restoration) | Servy `start` | post-Option (C) closure |
| 23:00+ | Ticking sustained | celery-beat-stderr.log + outbox 30s ticks | post-restoration verify |

## 真关联

- ADR-043 §Decision #1+#2 (Celery Beat mechanism + cron)
- LL-097 X9 Beat schedule restart 体例
- LL-098 X10 forward-progress reverse case
- backend/app/tasks/beat_schedule.py (CELERY_BEAT_SCHEDULE 6 entries)
- 真讽刺 X9 CeleryBeat post-restoration finding (本 SOP 真**实证 verify chain**)
- chunk C-SOP-B 真预约 sub-PR 9 alert wiring (DingTalk push BEAT_DEAD_DETECT)
