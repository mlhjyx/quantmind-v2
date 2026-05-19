# ADR-086: Celery Worker Periodic Restart + Memory Monitor + Servy Memory Limit (Solo Pool Hardening)

> **Status**: Proposed (5-19 Session 58+1 promote from candidate; merge = Accept)
> **Date**: 2026-05-19 evening SH
> **Authors**: CC Session 58+1 (沉淀 driver: LL-189 worker memory leak surface + user "彻底清理 + 立即" 5-19 ~18:21 SH)
> **Related**:
> - [LL-189](../../LESSONS_LEARNED.md#ll-189) (solo pool memory leak + orphan queue routing, 3 sub-pattern)
> - [LL-009](../../LESSONS_LEARNED.md#ll-009) (4-03 PG OOM, 铁律 9 出处)
> - [LL-181](../../LESSONS_LEARNED.md#ll-181) (Beat schedule paused 7 天)
> - [STATUS_REPORT_2026_05_19_memory_cleanup](../audit/STATUS_REPORT_2026_05_19_memory_cleanup.md) (14 min cleanup, +15.3 GB recovered)
> - [ADR-085](ADR-085-pt-restart-staged-paper-dryrun-5d-then-live.md) (Path B Phase B-1 active)
> - [ADR-DRAFT](ADR-DRAFT.md) row N+ (sediment candidate promote)

## §1 Context

### 1.1 触发背景 — LL-189 worker memory leak

**Session 58+1 5-19 ~18:21 SH user surface**: "占用了 29gb 的内存". Cold verify:
- PID 9696 QuantMind-Celery worker, 5-18 17:27 → 5-19 16:23 = **24h+ runtime**
- WS 43.9 GB / Private 1.4 GB
- System Available 1,704 MB (5.9% free, 32 GB DDR5)
- Committed 32,810 MB > Physical 31,859 MB (pagefile 占用真启动)
- Leak rate 实测 +3.5 MB / 5s ≈ **42 MB/min ≈ 2.5 GB/hr** (24h heavy load)

**24h cleanup window 14 min**: Stop-Service + service_manager.ps1 restart all + flush 288 orphan + task_default_queue config → **+15.3 GB recovered** (Available 1,704 → 16,995 MB, 5.9% → 53.3% free).

### 1.2 Why solo pool 无 native hardening

Celery 5.x source verified:
- `worker_max_memory_per_child` config 仅 prefork pool 有效 (`celery.concurrency.asynpool.AsynPool._post_init_callback`)
- Solo pool (`celery.concurrency.solo.TaskPool`) 不实现 max_memory_per_child
- 单一 hardening 路径 = **外部周期 restart + memory monitor + Servy memory limit**

### 1.3 5d Window 期内 LL-189 recurrence risk

Phase B-1 paper-mode 5-day window (5-20 Wed → 5-26 Tue):
- 5-22 Fri 19:00 factor-lifecycle Beat (heavy pandas factor compute)
- 5-24 Sun 22:00 gp-weekly-mining (2h budget, population=100, generations=50, factor_calc heavy)
- 加上日常 Beat 22 entries (~5,000 task/day) feed solo worker

**Pre-mortem**: 5d window 内 worker 可能再撑爆 to 20+ GB before 5-26 Tue gate evaluation → 5-26 PASS/FAIL gate 决策时 worker memory 累积 24-30h 已含 gp-weekly fire → could derail PASS threshold.

## §2 Decision

### 2.1 三层 hardening sequence (immediate + short-term + medium-term)

#### Tier 1 — Periodic restart schtask (RECOMMENDED, immediate)

**Windows Task Scheduler entry**: `QuantMind_CeleryNightlyRestart`
- Trigger: 每日 03:30 SH (避开 trading hours + 避开 17:00-20:00 Beat 高峰)
- Action: `PowerShell -Command "Restart-Service QuantMind-Celery"`
- Graceful shutdown 30s sustained (CLAUDE.md §Servy规则)
- Servy AutoRestart=true 沿用 (auto-recover)
- 反 24h+ 累积

#### Tier 2 — Meta-monitor memory rule (short-term)

**Beat `meta-monitor-tick` 5min 加 rule**: `available_mb_threshold_rule`
- Trigger: `Available MBytes < 2000` (~6.3% free, 接近 OOM 风险)
- Action: P1 DingTalk alert + 自动 trigger Tier 1 restart (if confirmed sustained > 2 fire cycles)
- 沿用 V3 §13.3 元告警 (alert-on-alert) 体例
- Add row: `qm_platform/risk/metrics/meta_alert_rules.py:MemoryPressureRule`

#### Tier 3 — Servy memory limit (medium-term)

**Servy CLI** (v7.6 verify support):
- `D:\tools\Servy\servy-cli.exe install --name=QuantMind-Celery ... --memory-limit=4096`
- 触发 auto-restart if 超 4 GB sustained
- Defense-in-depth (即使 Tier 1 + Tier 2 全部 fail, Servy 强制 reclaim)

### 2.2 Backend hardening (long-term, Phase J)

**pandas / numpy explicit release SOP** in factor_calc task body:
```python
import gc
result = compute_factor(...)
# ... use result ...
del result
gc.collect()  # force release
```

沿用 铁律 33 fail-loud + explicit release. Apply to:
- `backend/qm_platform/factor/compute/*`
- `backend/app/tasks/mining_tasks.py`
- `backend/app/tasks/backtest_tasks.py`

### 2.3 task_default_queue config (already done Session 58+1)

`backend/app/tasks/celery_app.py` 已 added `task_default_queue="default"` (commit `f39ce64`). 反 future orphan queue accumulation. **不重复 sediment**, 仅 reference.

## §3 Consequences

### 3.1 Pros

- 24h+ memory accumulation 彻底防止
- 元告警 layer 主动 surface 在 OOM-边缘 之前
- Defense-in-depth 3 层 (schtask + Beat rule + Servy limit)
- 反 LL-009 4-03 PG OOM cross-domain recurrence

### 3.2 Cons

- Daily 03:30 SH 30s 中断 (但 trading hours 之外, 0 broker impact)
- Beat memory monitor rule 加 5min 计算 overhead (~10ms per fire)
- Servy memory limit 若 false-positive trigger 可能 disrupt long-running task (mitigated via Tier 1+2 catch earlier)

### 3.3 5d Window 期 deployment cadence

**Sequence**:
1. **Tier 1 immediate** (5-20 Wed early, Day 1) — schtask register (~10min)
2. **Tier 2 short-term** (5-22 Fri or Day 3) — MemoryPressureRule code add + meta_monitor wire + Beat restart (~2h)
3. **Tier 3 medium-term** (5-26 Tue or Day 5) — Servy memory limit verify (depends on Servy v7.6 spec)
4. **Tier 4 backend hardening** (Phase J post 5-27 Phase B-2) — pandas gc.collect SOP rollout

### 3.4 真账户保护 verify

- 0 broker call impact (schtask 03:30 SH 远离 trading hours)
- 0 .env mutation
- Worker restart 期间 Redis broker 保持 task queue 持久 (沿用 ack_late=True config)
- Beat 自身 sustained running (Beat 与 Worker 独立 Servy service)

## §4 Anti-pattern verify (沿用 ADR-022)

- ✅ **不 fabricate**: LL-189 实测 leak rate 真值 (+3.5 MB / 5s) + Celery 5.x source verified (solo pool 不支持 max_memory_per_child)
- ✅ **不削减 user 决议**: Tier 1 schtask register 不 trigger broker / .env / DB mutation, autonomous-doable in 5d window
- ✅ **Defense-in-depth 3 层** (schtask + Beat rule + Servy limit) 反 single-fix bias (heuristic #18)
- ✅ **真账户保护**: schtask 03:30 SH 远离 trading hours, paper-mode sustained 0 broker impact

## §5 实施 source

- LL-189 sediment (本 session)
- LL-009 4-03 PG OOM (跨域 RAM hygiene 父 class)
- LL-181 Beat schedule paused (Beat consume side fail mode 父 class)
- STATUS_REPORT_2026_05_19_memory_cleanup §5 hardening roadmap
- Celery 5.x source `celery.concurrency.solo.TaskPool` vs `celery.concurrency.asynpool.AsynPool`
- Servy CLI v7.6 docs (D:\tools\Servy\)
- CLAUDE.md §部署规则 (Servy管理服务启动顺序 + graceful shutdown 30s)

## §6 next step (user trigger 后)

**Tier 1 implementation autonomous** (CC 5-20 Wed early autonomous):
```powershell
# Register schtask (no .env / broker mutation)
$action = New-ScheduledTaskAction -Execute 'PowerShell' -Argument '-NoProfile -Command "Restart-Service QuantMind-Celery"'
$trigger = New-ScheduledTaskTrigger -Daily -At 03:30
Register-ScheduledTask -TaskName "QuantMind_CeleryNightlyRestart" -Action $action -Trigger $trigger -Description "ADR-086 Tier 1 solo pool周期 restart (LL-189 hardening, sustained CLAUDE.md §Servy规则)"
```

**Tier 2 implementation** (5-22 Fri 起手): MemoryPressureRule code + meta_monitor wire + Beat restart.

**Tier 3 + Tier 4** (Phase J post 5-27): Servy memory limit + pandas gc.collect SOP rollout.

## §7 关联

- LL-009 + LL-181 + LL-189 (3 LL chain, sediment cumulative)
- LL-190 (plan v8 sediment-then-forget pattern, ADR-086 是 first audit-driven enforcement)
- ADR-085 (Path B Phase B-1 active, 5d window context)
- 铁律 9 (重数据并发限制基础) + 铁律 33 (fail-loud silent failure禁) + 铁律 38 (Blueprint sustained — solo pool 选型 sustained, 沿用 V3 §部署规则)
- Plan v8 §VIII #29 Audit Cadence Calendar (本 ADR 是 audit cadence event-driven trigger 第一例)
