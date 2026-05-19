# QuantMind-V2 ONBOARDING — 30-Min CC Restart / Human Onboard Playbook

> **目的**: P0-19 / P0-20 closure (Plan v8 Master Top 50). CC restart 后 30min 内**重建项目认知到可执行状态**, 反 bus factor=1 风险.
>
> **触发场景**:
> - CC session restart (memory 重置 / 新窗口)
> - User 突发不在线 (休假 / 伤病 / 设备故障) → 新 CC instance 接手
> - 项目第三方接手 (远期 — Q3-Q4 2026 知识传承)
>
> **使用方式**: 顺序阅读 §1 → §7 (各 ~3-5min). 完成后 onboard ready.
>
> **Date**: 2026-05-19 Session 58+1 evening SH
> **Authors**: CC autonomous (P0-19 + P0-20 closure)
> **Related**:
> - [Plan v8 §28 §VIII #1](audit/PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md) — knowledge continuity
> - [LL-190](../LESSONS_LEARNED.md#ll-190) — plan v8 sediment-then-forget pattern (本 doc 是 sustained enforcement)

---

## §1 项目本质 (1 min) — 你在做什么

**QuantMind V2** = 个人 A 股 + 外汇量化交易系统 (Python-first 全栈).

**目标**:
- 年化 15-25% / Sharpe 1.0-2.0 / MDD <15%
- 当前 PT 配置: **CORE3+dv_ttm WF OOS Sharpe=0.8659** (2026-04-12 PASS)
- 真账户 cash ¥993,520.66 sustained 4-29 清仓后 (0 持仓 19+ days as of 5-19)

**主线 phase**:
- ✅ Phase A-F (基础架构) + Phase H Frontend v3 W1-W6 (5-19 Session 57 ✅)
- 🟡 Wave 4 MVP 4.1 Observability batch 3.x (in-flight)
- 🟢 Phase F Path B Phase B-1 (5-19 evening → 5-26 Tue) — paper-mode 5d dry-run active
- 🔴 Phase B-2 5-27 Wed live restart (pending 5d gate evaluation)
- ⏸ Phase J Strategy diversification (post Phase B-2, multi-week 7 research items)

**单 user, 全职量化开发者** + AI 协助 model. **Bus factor = 1** (P0-19 sustained risk).

---

## §2 环境 Layout (3 min) — 系统在哪里

### §2.1 硬件
- Windows 11 Pro, R9-9900X3D, **RTX 5070 12GB** (PyTorch cu128, **cupy 不支持 Blackwell sm_120**)
- **32 GB DDR5** (沿用 LL-009 4-03 PG OOM 教训, **铁律 9 重数据并发限制基础**)

### §2.2 路径
- 项目: `D:\quantmind-v2\`
- PostgreSQL 16.8 + TimescaleDB 2.26.0: `D:\pgsql\bin\pg_ctl.exe`, 数据 `D:\pgdata16`, db=`quantmind_v2`, user=`xin`
- Redis 5.0.14.1: Windows native service
- Servy v7.6 (替 NSSM): `D:\tools\Servy\servy-cli.exe`
- miniQMT: `E:\国金QMT交易端模拟\` (Account=81001102)
- xtquant: `.venv\Lib\site-packages\Lib\site-packages\` (双层嵌套, `append` 不 `insert`)

### §2.3 Servy 6 services
| Name | Role |
|---|---|
| QuantMind-FastAPI | uvicorn --workers 2, port 8000 |
| QuantMind-Celery | `--pool=solo --concurrency=1` (Windows 不 fork) |
| QuantMind-CeleryBeat | Beat scheduler (32 entries) |
| QuantMind-QMTData | xtquant → Redis cache (60s sync) |
| QuantMind-RealtimeRisk | L1 tick monitor |
| QuantMind-RSSHub | News fetcher (localhost:1200) |

**Service mgr**: `powershell -File scripts\service_manager.ps1 [start|stop|restart|status] [all|fastapi|worker|beat]`

### §2.4 Windows schtask (~19 + QM-* sub)
- **QuantMind_DailySignal** Mon-Fri 16:30 SH (signal 生成)
- **QuantMind_DailyExecute** Mon-Fri 09:31 SH (execute, **真 PT gate** — Disabled = 0 broker call, 沿用 LL-188 forensic)
- QuantMind_DailyReconciliation 15:40 / QuantMind_PTAudit 17:35 / etc

---

## §3 关键 SSOT 文档优先级 (3 min) — 必读 4 doc

### §3.1 启动顺序 (沿用 铁律 38 + Constitution §L1.1 8 doc)

| # | Doc | 用途 | 大小 |
|---|---|---|---|
| 1 | `CLAUDE.md` | 项目 entry (40 铁律 + 当前进度) | ~530 lines |
| 2 | `IRONLAWS.md` | 铁律 SSOT v3.0 (44 + X9 + X10) | ~600 lines |
| 3 | `SYSTEM_STATUS.md` | §0 当前 sprint state | ~300 lines |
| 4 | `LESSONS_LEARNED.md` | LL-001 ~ LL-190+ (~192 sections 实测 5-19) | ~6500 lines, 仅 tail 200 lines + cite specific LL |
| 5 | `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` | V3 风控 spec authoritative | 巨型 |
| 6 | `docs/V3_IMPLEMENTATION_CONSTITUTION.md` | V3 实施宪法 v0.13+ | ~2000 lines |
| 7 | `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` | 平台化 QPB v1.16 | ~1600 lines |
| 8 | `docs/adr/REGISTRY.md` | ADR-001 ~ ADR-086+ SSOT | growing |

### §3.2 Memory frontmatter

最重要 1 line: `memory/project_sprint_state.md` frontmatter **顶部 Session 当前 handoff** — 跨 session 真相源 (沿用 铁律 37 + Constitution §L0.3 step 3).

### §3.3 不要读 (cognitive load 高)

- `docs/audit/` 122 files — 一次性诊断, 只 cite specific by name
- `docs/research-kb/` 41 entries — 失败方向, 沿用 §已知失败方向 cite only
- `docs/archive/` — 历史 deprecated, 0 maintain
- `docs/mvp/MVP_*` — 设计稿 only fetch by phase need

---

## §4 5 分钟 sanity check — verify system alive

```powershell
# 1. Servy 6 services Running
Get-Service | Where-Object { $_.Name -like "QuantMind*" } | Select Name, Status

# 2. FastAPI /health (verify execution_mode + connection)
Invoke-RestMethod "http://127.0.0.1:8000/health"

# 3. .env 红线 5/5 verify (沿用 LL-188 SOP step 0)
(Get-Content backend\.env) -match "^(EXECUTION_MODE|LIVE_TRADING_DISABLED|QMT_ACCOUNT_ID|DINGTALK_ALERTS_ENABLED)="

# 4. Memory baseline
Get-CimInstance Win32_OperatingSystem | Select @{N='AvailableMB';E={[math]::Round((Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue,0)}}, @{N='%Free';E={[math]::Round($_.FreePhysicalMemory/$_.TotalVisibleMemorySize*100,1)}}

# 5. Schtask state
Get-ScheduledTask | Where-Object { $_.TaskName -like "QuantMind*" } | Select TaskName, State

# 6. Git status (any uncommitted? branch sync?)
git status; git log --oneline -5

# 7. DB lastest row counts (10s sanity)
psql -U xin -d quantmind_v2 -c "SELECT MAX(filled_at) FROM trade_log;"
psql -U xin -d quantmind_v2 -c "SELECT COUNT(*) FROM factor_ic_history WHERE trade_date >= CURRENT_DATE - 7;"
```

**Expected 5-19 evening sustained Phase B-1 state**:
- 6 Servy Running
- `/health`: `{"status":"ok","execution_mode":"paper"}`
- `.env`: paper/true/81001102/true
- Available > 15 GB (sustained post memory cleanup +15.3 GB 5-19 18:35 SH)
- DailyExecute=Ready (sustained Phase B-1 Enable, NextRun next 09:31)
- Git: clean OR small ahead of remote
- trade_log MAX = 2026-04-29 (sustained 19+ days no new live trade)

---

## §5 7 顶级 铁律 + LL (5 min) — 必懂 enforcement

### §5.1 铁律 TOP 7 (生产 enforcement)

| # | 铁律 | One-line |
|---|---|---|
| 9 | 重数据并发限制 | 最多 2 个 >4GB Python process (沿用 LL-009 4-03 OOM) |
| 17 | DataPipeline 入库 (禁裸 INSERT) | LL-066 partial-UPSERT exception |
| 27 | 结论必明确 | ✅/❌/⚠️, 不接受"大概没问题" |
| 32 | Service 不 commit | 事务边界在 Router/Celery 调用方 (P0-9 sustained 30 violations) |
| 33 | 禁 silent failure | `# silent_ok:` annotation 或 fail-loud |
| 35 | Secrets via env 唯一 | 0 fallback 默认值 |
| 42 | PR + reviewer 制 | docs/** 直 push / backend/** 必走 PR |

### §5.2 LL TOP 7 (最关键 sediment)

| # | LL | Pattern |
|---|---|---|
| 009 | PG OOM 4-03 | 32GB 并发限制基础 |
| 098 | X10 (CC 不抢跑) | 末尾不 offer forward-progress |
| 105/106 | 4-source 漂移 | 4 source cross-verify (V3 §18.1 + audit docs + sprint_state + LL backlog) |
| 183 | dry-run silent NOT-GATING | --dry-run=true silent 真发 broker (5-18 P0) |
| 188 | sediment 层 drift | .env=live 3+ weeks while claim sustained paper (5-19 Session 58 forensic) |
| 189 | Solo pool memory leak + orphan queue | 24h+ 累积 / 286 orphan run_backtest (5-19 Session 58+1) |
| 190 | Plan v8 sediment-then-forget | sediment alone ≠ sustained enforcement (5-19 Session 58+1) |

### §5.3 真账户操作 (CRIT, 沿用 ADR-027 §7 双 trigger 体例)

- `.env` 红线 fields (EXECUTION_MODE / LIVE_TRADING_DISABLED / QMT_ACCOUNT_ID / DINGTALK_ALERTS_ENABLED / L4_AUTO_MODE_ENABLED) 修改 必 user **双 trigger** ("同意" + "你执行")
- broker call (xtquant order_stock/sell/buy/cancel) 必 user 显式 trigger
- Servy restart for memory hygiene = NON-CRIT (沿用 LL-189 cleanup 体例, autonomous OK)
- schtask Enable/Disable = CRIT-ADJACENT (PT main chain), sustained 双 trigger 体例

---

## §6 当前 Sprint 状态快速 cite (3 min)

### §6.1 Active context (5-19 Session 58+1 evening)

**Phase B-1 paper-mode 5d dry-run window active** (ADR-085):
- 5-19 evening flip executed
- 5-20 Wed → 5-26 Tue 5 trading days
- 5-26 Tue evening gate → 5-27 Wed Phase B-2 live flip (pending user trigger 3)

**Recent commit chain (Session 58+1)**:
```
d462a2b  Batch 1 — DEV_FOREX archive + Audit Cadence Calendar + CLAUDE.md fix
1969473  Plan v8 systematic closure (13-doc deep-read + 6 sediment)
3385bd8  UNRESOLVED comprehensive audit 30+ items
62bc585  Day 0 STATUS_REPORT Phase B-1 launch
f39ce64  Memory cleanup (LL-189 sediment)
3323cd4  ADR-085 + 2 scripts + observation template (Path B prep)
3edaabe  PT 重启 Phase F 战略 brief
```

### §6.2 User touchpoint queue (pending)

**Critical**:
- U1 PG password rotate timing
- U2 gp-weekly disable for 5d ambush prevention
- U3 Phase B-2 5-27 Wed "你执行" trigger 3
- U4 meta-monitor memory rule wire (ADR-086 Tier 2 immediate?)

**Phase J 7 research items** (post 5-27 live restart):
- U5-U11 per PLAN_V8_MASTER_FINDINGS_REGISTER §4.2

### §6.3 Active known issues (sustained)

- LL-188 sediment drift (.env=live 3+ weeks while claim paper) — REPAIRED via Path B Phase B-1 (5-19 evening flip)
- LL-189 worker leak — Hardening Tier 1-4 sediment in ADR-086 (Tier 1 schtask register pending)
- LL-190 sediment-then-forget pattern — Audit Cadence Calendar sediment Tier 1 (Tier 2-4 future)

---

## §7 触发 work 后做什么 (3 min) — Common action paths

### §7.1 User 说 "继续" / "什么状态"

1. Read SYSTEM_STATUS.md §0
2. Cite memory frontmatter Session handoff
3. Surface 当前 phase + recent 3 commits + pending user touchpoint queue

### §7.2 User 说 "排查 X 问题"

沿用 LL-188 SOP step 0 cold reality check:
1. `grep <field> backend/.env` (反 sediment 层 claim drift)
2. `Get-ScheduledTask <name>` (真 schtask state)
3. DB query `trade_log / risk_event_log / position_snapshot` 真值
4. `psql -c "SELECT MAX(...) FROM ..." vs sediment claim
5. Surface 真值 vs claim 漂移

### §7.3 User 说 "你执行 X"

沿用 ADR-027 §7 双 trigger 体例:
- Verify trigger 1 ("同意" already received)
- Verify trigger 2 ("你执行" / "执行" present)
- Spawn redline-guardian if mutation touches 5/5 红线 fields OR broker
- Backup + atomic edit + Servy restart 沿用 PR #169/170 体例

### §7.4 User 说 "提交" / "commit"

1. `git status --short` + verify staged
2. Sediment commit msg 沿用 `docs(...)` / `fix(...)` / `feat(...)` Conventional Commits
3. Co-Authored-By line at bottom
4. Pre-commit hook 通过 (LL-188 step 0 sediment drift check 0 mismatch)

### §7.5 User 说 "audit" / "全面 review"

走 Plan v8 framework (沿用 quizzical-snacking-fox.md):
1. Spawn 9 subagent across 3 batches + CC cross-validate gates
2. Phase 3+3-bis Strategic Alternatives synthesis
3. Per-finding 2-3 alternative remediation (heuristic #18 GLOBAL)
4. Sediment ~11 audit doc + LL/ADR candidate
5. Update Audit Cadence Calendar (sustained doc updates trigger A or B)

---

## §8 紧急 emergency response (1 min) — 极端场景 fallback

### §8.1 真账户 emergency close

**Trigger**: user 显式 "emergency close all" OR PT runtime detect 极端事件 (e.g. limit-down >8% 全持仓 + drawdown >15%)

**Action**: `scripts/emergency_close_all_positions.py` (API: `/api/execution/emergency-liquidate`)

**Recent example**: 2026-04-29 17 emergency_close orders (cleanup, 真账户 0 持仓)

### §8.2 Servy 全 crash

**Trigger**: 全 6 Servy Stopped (检查 `Get-Service QuantMind*`)

**Action**: `powershell -File scripts\service_manager.ps1 restart all` + Servy CLI restart QMTData + RealtimeRisk + RSSHub manually

### §8.3 PG OOM (沿用 LL-009 4-03)

**Trigger**: PG postgres.exe crash with 0xc0000409 + Windows error 1455

**Action**:
1. `D:\pgsql\bin\pg_ctl.exe stop -D D:\pgdata16 -m immediate`
2. `D:\pgsql\bin\pg_ctl.exe start -D D:\pgdata16 -l D:\pgdata16\log\startup.log`
3. Verify shared_buffers=2GB sustained
4. Reduce concurrent Python process (沿用 铁律 9 max 2)

### §8.4 LL-180 类 (xtquant asyncio bootstrap fail)

**Trigger**: `RuntimeError: no event loop in thread 'broker_qmt'`

**Action**:
1. Check `backend/engines/broker_qmt.py:253-264` — `asyncio.set_event_loop` bootstrap 沿用
2. Servy restart QuantMind-Celery + QuantMind-CeleryBeat
3. Verify Beat resumes 32 schedule entries fire

---

## §9 关联 (post onboard read 1 of these)

- [Plan v8](`C:\Users\hd\.claude\plans\quizzical-snacking-fox.md`) framework reference
- [LL-190 sediment](../LESSONS_LEARNED.md#ll-190) — plan v8 sediment-then-forget pattern (本 doc 是 sustained enforcement Tier 1)
- [SHUTDOWN_NOTICE_2026_04_30](audit/SHUTDOWN_NOTICE_2026_04_30.md) — 4-29 清仓决议
- [ADR-085](adr/ADR-085-pt-restart-staged-paper-dryrun-5d-then-live.md) — Path B Phase B-1 active
- [ADR-086](adr/ADR-086-celery-worker-periodic-restart-and-memory-monitor.md) — Celery hardening
- [PHASE_B_2_PREFLIGHT_CHECKLIST_2026_05_27](audit/PHASE_B_2_PREFLIGHT_CHECKLIST_2026_05_27.md) — 10-dim gate criteria
- [PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19](audit/PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md) — 50+ findings × closure status
- [audit_cadence_calendar](runbook/audit_cadence_calendar.md) — 4 audit trigger conditions

---

**End ONBOARDING. 30 min onboard complete. Ready to take any user request.**
