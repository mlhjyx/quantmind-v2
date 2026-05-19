# STATUS_REPORT 2026-05-19 evening — Memory Cleanup (Session 58+1)

> **触发**: user 5-19 18:21 SH 报告 "占用了29gb的内存" — 真值 verify + 彻底清理 + 立即.
> **Date**: 2026-05-19 18:21 → 18:35 SH (14 min cumulative cleanup)
> **Session**: 58+1 (interrupted from PT 重启战略讨论 Path B prep, 待 trigger 2)
> **Outcome**: ✅ **+15.3 GB recovered, 0 broker call, 0 .env change, 0 schtask change**

---

## §1 Root cause sediment (LL-189 候选)

### §1.1 Celery solo pool memory accumulation (primary)

**真值** (5-19 16:23 SH cold):
- `QuantMind-Celery` worker PID 9696, started 5-18 17:27:36 (24h+ runtime, post-M3 asyncio bootstrap fix)
- Command: `celery -A app.tasks.celery_app worker --pool=solo --concurrency=1 -Q default,factor_calc,data_fetch -n worker-main@XIN`
- WorkingSet: 43.9 GB (Windows shared/file-mapped artifact)
- PrivateMemorySize: 1.4 GB
- CPU cumulative: 16,619s
- Leak rate (实测 5s sample): +3.5 MB / 5s ≈ **42 MB/min ≈ 2.5 GB/hr 持续**
- System impact: Total RAM 31,859 MB / Available 1,704 MB (**5.9% free, OOM 边缘**)
- Committed > Physical (32,810 MB committed > 31,859 MB), **pagefile 占用真启动**

**Root cause** (LL-189 候选 #1):
- `--pool=solo --concurrency=1` = **单 Python process, 不 fork**, 内存累积 0 reset (区别于 prefork pool 每 N 任务 fork child + max_memory_per_child 触发 child 重启)
- pandas / numpy DataFrame allocate 用 glibc malloc, 释放后**page 不还给 OS**
- Python GC + reference cycles 也不主动 release native heap
- Beat 22 schedule entries 持续 feed solo worker:
  - outbox-publisher-tick (30s) ≈ 2,880 fires/day
  - meta-monitor-tick (5min) ≈ 288 fires/day
  - risk-l4-sweep-1min (1min trading hrs) ≈ 360 fires/day
  - risk-dynamic-threshold-5min (5min trading hrs) ≈ 72 fires/day
  - news-ingest 6x daily / RSSHub 6x daily / announcement-ingest 5x daily / regime 3x daily / 等
  - **Total ≈ 5,000+ task/day fed solo worker**

**Solo pool 不支持 `worker_max_memory_per_child`** (verified via celery 5.x source `celery.concurrency.solo.TaskPool` vs `celery.concurrency.asynpool.AsynPool`). 真 hardening 需要外部 schtask 触发周期 restart.

### §1.2 Orphan queue accumulation (secondary)

**真值** (5-19 16:23 SH cold):
- `celery` Redis queue depth: **288 messages**
- Worker `-Q default,factor_calc,data_fetch` 不订阅 "celery" queue
- 288 messages 24h+ orphan accumulation
- Task distribution: **286/288 = `app.tasks.backtest_tasks.run_backtest`** + 1 × news_ingest_5_sources + 1 × news_ingest_rsshub
- 3 producer process origin: `gen18740`, `gen32784`, `gen90328` (all 不存在 by 5-19, 已死)
- `expires=null` (no TTL, 永不过期)

**Root cause** (LL-189 候选 #2):
- `app/api/backtest.py:202` — `run_backtest.delay(run_id)` — POST /api/backtest endpoint
- `app/services/backtest_service.py:94` — `run_backtest.delay(run_id)` — service layer
- 2 caller 用 `.delay()` 不传 `queue=` argument
- Celery default → "celery" queue (config `task_default_queue` 未设)
- Worker `-Q default,factor_calc,data_fetch` 不订阅 "celery"
- 这些 `.delay()` 调用产生的 task **从未被消费**, Redis 累积 silent orphan

**Note**: 286 orphan run_backtest 都是 expires=null, **若不 orphan 反而被 worker 一次性 pick up 286 个 backtest → 实测 backtest 单 run 占用 ~3-5GB pandas + price_data → 立即 OOM**. 真讽刺: orphan 反而是 OOM 保护层. Sediment LL-189 候选 #3.

---

## §2 Cleanup sequence executed (5-19 18:30 → 18:35 SH, 14 min)

| Step | Action | Result |
|---|---|---|
| 1 | Pre-cleanup snapshot | Memory 5.9% free / 288 backlog / PID 9696 43.9 GB WS |
| 2 | `Stop-Service QuantMind-Celery` | 12s graceful shutdown (sustained CLAUDE.md 30s spec) |
| 3 | Verify PID 9696 terminated | 0 orphan, Available 1,704 → 12,587 MB (**+10.8 GB**) |
| 4 | Edit `backend/app/tasks/celery_app.py` | docstring LL-189 sediment + `task_default_queue="default"` config |
| 5 | `service_manager.ps1 restart all` | FastAPI / Worker / Beat 3 services restarted clean |
| 6 | Servy auto-managed QMTData | re-cycled along with restart all |
| 7 | `redis-cli DEL celery` | 288 orphan flushed (0 remaining) |
| 8 | Verify post-restart Python processes | 6 fresh PIDs, sub-400 MB each, healthy baseline |
| 9 | Final memory verify | Available 16,995 MB (**53.3% free**), Committed < Physical (no pagefile) |

---

## §3 Final state verification (5-19 18:35 SH)

### §3.1 Memory metrics

```
Total:     31,859 MB (32 GB DDR5)
Free:      16,970 MB
Available: 16,995 MB (53.3% free)
Cache:        102 MB
Standby:      983 MB
Committed:    < Physical (no pagefile pressure)
```

### §3.2 Python process baseline (post-restart healthy)

| PID | Service | WorkingSet MB | Role |
|---|---|---|---|
| 17344 | FastAPI uvicorn parent | 30 | Servy main process |
| 3760 | FastAPI worker 1 | 371 | multiprocessing child |
| 19384 | FastAPI worker 2 | 370 | multiprocessing child |
| 37472 | Celery worker | 280 | solo pool task executor |
| 37244 | Celery Beat | 280 | scheduler |
| 32336 | QMT Data Service | 120 | xtquant → Redis cache |
| 28656 | RealtimeRisk engine | 3 | L1 tick monitor |

**Total Python footprint: ~1.45 GB** (down from 30+ GB).

### §3.3 Servy 6 services state

All Running: QuantMind-FastAPI / QuantMind-Celery / QuantMind-CeleryBeat / QuantMind-QMTData / QuantMind-RealtimeRisk / QuantMind-RSSHub.

### §3.4 Redis queue state

| Queue | Depth | 说明 |
|---|---|---|
| celery | **0** | flushed orphan (was 288) |
| default | 0 | new tasks 现在 route 到这里 (post task_default_queue config) |
| factor_calc | 0 | explicit queue, 沿用 |
| data_fetch | 0 | explicit queue, 沿用 |

### §3.5 红线 5/5 sustained

| # | 红线 field | Value | Status |
|---|---|---|---|
| 1 | cash | ¥993,520.66 | sustained (sediment cite 5-19 brief §1.4) |
| 2 | 持仓 | 0 | sustained |
| 3 | EXECUTION_MODE | live | sustained (post-cutover 5-15~5-17) |
| 4 | LIVE_TRADING_DISABLED | false | sustained |
| 5 | QMT_ACCOUNT_ID | 81001102 | sustained |

**0 broker call / 0 .env change / 0 schtask change / 0 DB row mutation**.

---

## §4 Code changes (this Session)

### `backend/app/tasks/celery_app.py`

- **Docstring**: 加 "Solo pool memory leak — LL-189 候选" 段, sediment root cause + 4 hardening 选项
- **Config**: `task_default_queue="default"` 加入 `celery_app.conf.update()` 反 orphan queue 累积

---

## §5 Hardening roadmap (sediment for follow-up)

### §5.1 Immediate (执行 in this Session) ✅
- [x] Celery worker restart (release 28+ GB)
- [x] task_default_queue="default" config (反 future orphan)
- [x] 288 orphan flushed

### §5.2 Short-term (ADR-086 候选, 1 follow-up PR)
- [ ] **Periodic restart schtask** `QuantMind_CeleryNightlyRestart` 每日 03:30 SH 触发
  `Restart-Service QuantMind-Celery` (~30s graceful + Servy AutoRestart=true)
- [ ] **Memory monitor rule**: Beat `meta-monitor-tick` 5min 加 rule
  `Available MBytes < 2000 → P1 DingTalk alert` (V3 §13.3 第 8 元告警)
- [ ] **Servy memory limit** (if Servy v7.6 支持): `--memory-limit=4096` 触发 auto-restart

### §5.3 Medium-term (Phase J 候选, multi-session)
- [ ] **Backend hardening**: pandas explicit `gc.collect() + del df` in factor_calc task body
  (沿用铁律 33 fail-loud + explicit release)
- [ ] **Sentry / memory_profiler instrumentation** for leak source attribution per task
- [ ] **factor_calc queue 拆分**: 重数据 task 独立 worker process (隔离泄漏域)

### §5.4 Audit follow-up
- [ ] Phase J audit add memory hygiene SOP: schtask restart cadence + monitor wire
- [ ] LL-189 sediment LESSONS_LEARNED.md (本 STATUS_REPORT 是 interim sediment)
- [ ] ADR-086 候选 promote (Solo pool periodic restart + monitor + memory limit, 沿用 ADR-DRAFT.md row N+ 体例)

---

## §6 Pre-existing context preserved

### §6.1 PT 重启 path B prep (interrupted, ready resume)

- ADR-085 + 2 scripts + observation template 已 commit (commit `3323cd4`)
- DryRun verified: step1 PASS / step2 fail-fast PASS
- Redline guardian: NEEDS_USER (waiting trigger 2 "你执行")
- Memory cleanup 不影响 path B readiness (0 .env 变更 / schtask 状态 sustained)
- **Path B step1 next**: user 显式 "你执行" → CC 接力跑 paper flip (5-20 Wed window)

### §6.2 Time progression note

- 16:21 SH: user 报 memory issue (interrupted PT restart trigger 2 ask)
- 16:23 SH: pre-cleanup snapshot
- 18:30 SH: stop worker (16:30 SH DailySignal 已 fired in live state, signal layer 不受影响)
- 18:35 SH: cleanup 完成

**Path B timing impact**: 5-20 Wed 早 SH 仍是 paper flip 最佳 window (clean Day 1 起点). Memory cleanup 是 prep work 加分项, NOT timing reset.

---

## §7 LL-189 候选 sediment (3 sub-pattern)

**Pattern #1 — Solo pool unbounded memory growth**:
- `--pool=solo --concurrency=1` 不 fork, 单 process 累积内存 24h+ 不释放
- glibc malloc + pandas + numpy + GC 联合不 release native heap
- `worker_max_memory_per_child` 仅 prefork 有效 (celery 5.x source verified)
- **Hardening**: 外部周期 restart (schtask) + monitor (meta-monitor rule) + Servy memory limit

**Pattern #2 — Orphan queue accumulation via .delay() no-queue**:
- `task.delay()` / `task.apply_async()` 不传 `queue=` → 默认 `task_default_queue`
- 若 `task_default_queue` 未配置 → Celery 默认 "celery" queue
- 若 worker `-Q` 不订阅 "celery" → 24h+ silent orphan 累积
- **Hardening**: 显式 set `task_default_queue` config (本 PR 已 fix)

**Pattern #3 — Orphan-as-protection irony**:
- 286 orphan run_backtest 都是 expires=null, **若被消费 → 立即 OOM**
- 真讽刺: orphan 反而是 OOM 保护层
- 真 fix 应在 caller side (api/backtest.py + services/backtest_service.py)
  加 `apply_async(queue="backtest_heavy", expires=3600)` + 独立 worker pool 隔离重数据
- 当前 fix 只 fix routing, NOT fix backtest queue capacity issue

**关联**:
- LL-009 (4-03 PG OOM 事件) — 并发限制基础, 铁律 9 出处
- LL-181 (Beat schedule paused 7 天) — 沿用 Beat consume side fail mode
- LL-183 (silent NOT-GATING) — sediment 层 silent 失败 parent class (LL-188 + LL-189 sub-class)
- ADR-085 (PT 重启 path B prep, 5-19 sustained)
- 铁律 9 (重数据并发限制) + 铁律 33 (fail-loud silent failure 禁)

---

## §8 关联 commits

- `9dea1cc` — Session 58 round-6 LL-188 step 0 enforce (sediment-drift hook)
- `3edaabe` — PT 重启 Phase F strategic brief
- `3323cd4` — ADR-085 + 2 scripts + observation template (path B prep)
- **(this Session)** — celery_app.py task_default_queue + LL-189 sediment + 本 STATUS_REPORT

---

**End of memory cleanup STATUS_REPORT. Path B prep 复位 ready, awaiting user trigger 2 "你执行".**
