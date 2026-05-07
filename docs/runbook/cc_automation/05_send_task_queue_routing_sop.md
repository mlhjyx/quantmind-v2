# 05 — Celery send_task Queue Routing SOP

> **Why**: sub-PR 8b-cadence-B post-merge ops Option (C) verify (5-07 22:00) **第 1 次 send_task dispatch silent fail** — `celery_app.send_task('app.tasks.news_ingest_tasks.news_ingest_5_sources')` default routing key `"celery"` 反 Worker subscribed queues `default/data_fetch/factor_calc` (per stdout banner) → Redis LLEN celery=288 backlog stuck. **Frame drift #14 catch sediment**.
> **触发**: 任 manual `celery_app.send_task(...)` Synthetic dispatch (反 Beat 自动触发) — **queue routing prerequisite verify**.

## **正确 send_task 体例**

### ❌ Anti-pattern (silent drop reverse case)
```python
celery_app.send_task('app.tasks.news_ingest_tasks.news_ingest_5_sources')
# default routing → Redis list "celery" → Worker NOT subscribed → silent drop
```

### ✅ 正确 体例 (queue= explicit)
```python
celery_app.send_task(
    'app.tasks.news_ingest_tasks.news_ingest_5_sources',
    queue='default',  # MUST match Beat entry config 沿用 beat_schedule.py
)
```

## **queue routing matrix** (Worker config 沿用 Servy export QuantMind-Celery)

> **Source**: Servy export config `Parameters` field **`-Q default,factor_calc,data_fetch`** (5-07 22:00 实测 `D:\tools\Servy\servy-cli.exe export --name="QuantMind-Celery" --config json --path <tmp>`) + Worker stdout banner `[queues] .> default ... .> data_fetch ... .> factor_calc` 沿用 sub-PR 8b-cadence-B post-merge ops Phase 0 verify (`logs/celery-stdout.log` line "Worker startup banner 5-07 21:38:26").

| queue name | source | task pattern | Worker subscribe? |
|---|---|---|---|
| `default` | Beat entry `"queue": "default"` | News ingestion / outbox / factor lifecycle / daily quality / gp-weekly | ✅ subscribed (Worker `--Q default,factor_calc,data_fetch`) |
| `data_fetch` | dual-write tasks (deprecated) | data fetcher legacy | ✅ subscribed |
| `factor_calc` | factor onboarding tasks | factor mining heavy compute | ✅ subscribed |
| `celery` (default Celery routing key) | manual `send_task` 反 `queue=` | — | ❌ NOT subscribed → **silent drop** |

## **verify SOP** post-dispatch

### Step 1: Redis queue depth check
```powershell
redis-cli LLEN default       # Expected: dispatched task ⊆ here
redis-cli LLEN celery         # Expected: 0 (反 backlog accumulation)
redis-cli LLEN data_fetch
redis-cli LLEN factor_calc
```

### Step 2: AsyncResult poll
```python
from celery.result import AsyncResult
r = AsyncResult(task_id, app=celery_app)
print(r.state)  # PENDING → STARTED → SUCCESS / FAILURE
```

### Step 3: Worker stdout log tail
```bash
tail -50 D:/quantmind-v2/logs/celery-stdout.log | grep -E "Received|Task succeeded|raised"
```

### Step 4: scheduler_task_log proof-of-life (M1 reviewer adopt PR #257 sediment)
```sql
SELECT task_name, status, start_time, end_time, result_json
FROM scheduler_task_log
WHERE task_name LIKE 'news_ingest_%' AND start_time > now() - interval '5 minutes'
ORDER BY start_time DESC;
```

## **反 anti-pattern** sediment

- ❌ `send_task(name)` 反 `queue=` 假设 default routing 生效 — Celery default routing key `celery` 反 align Worker queue subscription
- ❌ Beat entry config `"queue": "default"` cite 反 manual send_task 同步 — manual + Beat 必同 queue 体例
- ❌ silent drop 沿用 unregistered task warning 假设 Worker pick up — **queue 反 match** **0 warning** Celery Worker **反 见 task** at all

## 真生产真值 evidence (5-07 22:00)

- 第 1 次 send_task `5-source` + `rsshub` 反 queue= → Redis `celery` LLEN += 2 → Worker 0 pickup → AsyncResult PENDING 30+ min → DB 0 row 反 evidence
- 第 2 次 send_task with `queue='default'` → Redis `default` LLEN += 2 → Worker pickup 22:02:27 / 22:02:58 → AsyncResult SUCCESS → 8 news_classified rows verified

## 关联

- ADR-043 §Decision #2 cron + Beat entry config queue 体例
- LL-067 reviewer 第二把尺子 (Worker registry verify M1 adopt PR #257)
- drift catch #14 frame drift catch (本 SOP **实证 fix path**)
- backend/app/tasks/celery_app.py:33-62 (Worker concurrency + queue config)
- backend/app/tasks/beat_schedule.py (Beat entry queue mapping)
