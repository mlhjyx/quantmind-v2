# Phase J / Phase B-2 Defer Manifest (2026-05-20)

> **Trigger**: `/goal` Wave 1 综合审计 surface 多 P0/P1 真问题, autonomous-doable 已 Wave 3 修复, 剩余 multi-week / user-touchpoint items 沉淀此处供 user 决议.
>
> **Status**: Read-only manifest (本 doc 不 trigger 任何 action, 仅 list).
>
> **Branch**: feature/plan-v8-batch-cumulative-5-19-20  HEAD=4ad9c3f  (Wave 3 修后)
>
> **Cross-ref**:
> - Source: `WAVE_2_SYNTHESIS_2026_05_20.md` §5 + Wave 1 Agent A/B/C/D/E reports
> - Catalog: `ISSUES_PENDING_REGISTRY_2026_05_19.md` (老 P0/P1, 部分 overlap)
> - Path B status: `STATUS_REPORT_2026_05_20_pt_paper_dryrun_day1.md`

---

## §1 P0 Multi-Week (Phase J Research / Phase B-2 Implementation)

### §1.1 流 4 风控 Chain Wire ⭐⭐⭐ (PT 重启 5-27 前 prerequisite)

**Source**: Wave 1 Agent D 流 4 闭环 audit, alert.py:22-23 自述 "**AlertDispatcher 0 production caller 当前 — tests-only usage**"

**Real issue**:
- `RealtimeRiskEngine` (`backend/qm_platform/risk/realtime/engine.py`) 单元完整, register_rule + on_tick + on_5min_beat 全实现
- `AlertDispatcher` (`backend/qm_platform/risk/realtime/alert.py`) 单元完整, P0/P1/P2 routing + buffer + send_fn 全实现
- **但**: 没有任何 Beat task / Celery worker / scheduler 实例化 engine + dispatcher + 喂 tick / 5min beat
- `meta-monitor-tick` (5min, `beat_schedule.py:360`) 只 collect metrics + meta_alert_rules, **不替代 L1 push**

**真后果**:
- Paper-mode 期间真发生 limit_down / rapid_drop / volume_spike, **L1 风控完全静默**
- DingTalk P0 alert 真无人发
- L4 STAGED `l4_sweep_tasks` 已 wire broker.sell, 但**上游 plan 创建 0 caller** → l4_sweep 长期空跑

**Phase J 修法 candidate**:
- **Option A (Beat-driven)**: 加 `realtime-risk-tick` Beat entry (cadence 30s OR 60s), 实例化 RealtimeRiskEngine + AlertDispatcher, 喂 latest tick from market_latest Redis hash. Effort: ~3-5 day.
- **Option B (Celery worker process)**: 独立 worker process 长期持有 engine state, Redis pub/sub 接 qmt_data_service tick stream. Effort: ~1 week (process model decision).
- **Option C (Servy 服务化)**: 新 Servy service `QuantMind-RealtimeRisk` 独立常驻进程. Effort: ~1 week + Servy bootstrap.

**推荐**: Option A (Beat-driven) — 最快 wire, 跟现有 Beat infra 一致, 性能 OK (Top-20 持仓 + 10 rules ≪ 30s budget).

**Path B-2 prerequisite**: ❌ **必须 wire 后才能 5-27 Wed live flip**. 当前 paper-mode + 0 持仓 可 sustain, 真账户开仓后 silent 风控 = 资金风险.

**Owner**: Backend dev, V3 §5/6 实施 scope
**Effort**: 3-7 day
**User decision needed**: 选 Option A/B/C + 5-27 Wed live flip 时机

---

### §1.2 L4 STAGED Plan 创建源 Wire (跟 §1.1 同 chain 上游)

**Source**: Wave 1 Agent D 流 4

**Real issue**:
- `L4ExecutionPlanner.generate_plan` (`backend/qm_platform/risk/execution/planner.py:65`) 单元完整, PENDING_CONFIRM ExecutionPlan 创建路径 OK
- `l4_sweep_tasks.py:74` PENDING_CONFIRM → TIMEOUT_EXECUTED → broker.sell wire 完整 (8c-followup, broker_qmt asyncio bootstrap fix LL-182 sustained)
- **但**: planner.generate_plan 0 production caller — STAGED plan 实际 0 创建 → l4_sweep 空跑

**Phase J 修法**:
- §1.1 Option A Beat-driven path 内: RealtimeRiskEngine 产 P0 alert 后, 调 `planner.generate_plan(symbol, severity, ...)` 写 execution_plans 表
- `risk_event_log` INSERT 同步 (audit row immutability)
- DingTalk P0 alert 同时 send (L4 STAGED 决策权延迟 + audit trail)

**Effort**: 包含在 §1.1 effort (合并 wire)

---

### §1.3 流 5 daily_reconciliation schtask + risk_event_log wire ✅ CLOSED iter 164-168 (MVP 4.6)

**Source**: Wave 1 Agent D 流 5 (original 2026-05-20)
**Status iter 168 (2026-05-26)**: ✅ design + 3 code chunks merged + doc closure shipped

**Original claim (2026-05-20, ~6d stale)**:
- `scripts/daily_reconciliation.py` schtask 已 Disabled 自 4-29 PT 清仓后
- 真后果: mismatch 后只 DingTalk 单点告警, 无 risk_event_log audit row

**Reality re-grounded iter 164** (per §v9.49, fresh `schtasks /Query /TN QuantMind_DailyReconciliation /V`):
- Scheduled Task State: **Enabled** (NOT Disabled — manifest claim ~6d stale)
- Last Run Time: 2026-05-26 15:40:01, Last Result: **1** (FATAL exit, not graceful skip)
- Root cause: `os.environ.get("EXECUTION_MODE")` returned `""` (schtask launches `python.exe` without sourcing `.env`) → fell through paper-mode guard → hit FATAL `sys.exit`
- Net production impact identical to Disabled (0 reconciliation runs since refactor), but mechanism orthogonal

**Closure cumulative iter 164-168** (MVP 4.6 4 chunks per `docs/mvp/MVP_4_6_daily_reconciliation_revival.md`):
- iter 164: MVP 4.6 design doc shipped (`bccd749`, design-only direct push)
- iter 165 Chunk 1 PR #500 (`ba2cc3e`): `settings.EXECUTION_MODE` replaces `os.environ.get` (SSOT per 铁律 34); removed unused `import os`; 3 TDD tests
- iter 166 Chunk 2 PR #501 (`6f12f32`): `_persist_mismatch_audit()` helper + wire; sibling pattern `execution_plan_persistence.py:102-127`; 8 TDD tests
- iter 167 Chunk 3 PR #502 (`360a702`): 5 integration smoke tests covering full `run_reconciliation()` flow
- iter 168 Chunk 4 (this): manifest §1.3 correction + LL-209 + STATUS_REPORT + CLAUDE.md L18 minor edit (direct push per 铁律 42)

**Owner**: Closed iter 164-168 CC autonomous (0 user touchpoint required)
**Effort actual**: ~30min design + ~1h per code chunk × 3 + ~30min doc closure = ~3.5h cumulative
**Path B-2 prerequisite**: ✅ Code-level wire complete. Live cutover gates remain at `.env` paper→live (separate user authorization per ADR-027 / V3 §0.3).
**Sibling §v9.49 finding (LL-209)**: Manifest reality drift caught pre-implementation via fresh `schtasks /Query` — 5-iter chain demonstrates reality re-grounding SOP value.

---

### §1.4 流 6 RAG Consumer Wire (TB-4d / TB-5)

**Source**: Wave 1 Agent D 流 6

**Real issue**:
- `risk_reflector_agent.py` Sun 19:00 + 月 1 日 09:00 reflection sediment 进 risk_memory ✅
- BGE-M3 embedding cron **NOT 实施** (F2 in ISSUES_PENDING_REGISTRY, 21 rows embedding NULL)
- **更关键**: NewsClassifier / Bull / Bear / RegimeJudge **0 RAG consume** (V3 §5.4 line 710 设计的 "L1 push augmentation" 真值 wire 0)
- 当前 RAG 只 reflector 自反馈 (循环, 增量极小)

**Phase J 修法**:
1. BGE-M3 embedding cron (F2, ~4h GPU script)
2. NewsClassifier / Bull / Bear / RegimeJudge 加 `RiskMemoryRAG.retrieve(query, top_k=5)` consume — V3 TB-4d/TB-5 scope
3. 真集成测试 (cross-component, ~1 week)

**Owner**: Backend dev (RAG wire) + User (GPU resource for BGE-M3)
**Effort**: ~1-2 week
**Path B-2 priority**: P1 (不阻塞 5-27 live flip, 但 V3 §5/6 完整闭环依赖)

---

### §1.5 流 3 → 流 4 Trade Event Publish ✅ CLOSED iter 183-185 (MVP 4.8 backend-only)

**Status iter 185 (2026-05-26)**: ✅ backend-only ✅ closed. Runtime-verified pending Servy unblock.

**Original claim (2026-05-20, STALE per iter 183 §v9.49 catch)**:
The original "no event publish" framing was REFUTED by architect agent fresh code read iter 183. Outbox publisher (MVP 3.4 batch 5 PR #130 2026-04-28) already wires `qm:fill:executed` Redis Stream since 4-28 via `execution_service.py:266-282` (paper) + `:472-488` (live) OutboxWriter.enqueue calls.

**True gap (discovered iter 183 via Layer 3 code verify)**:
0 consumer subscribed to `qm:fill:executed` for risk evaluation. `realtime_risk_tasks.py:244-397` 1min Beat builds context from Redis positions but does NOT XREAD from any stream.

**MVP 4.8 closure (iter 183-185)**:
- iter 183 design doc `docs/mvp/MVP_4_8_streambus_trade_event_consumer.md` (multi-agent fan-out)
- iter 184 PR #510 (`b80f27f`) — Chunks 1-4 batched: `trade_event_consumer.py` (XREADGROUP helper) + `trade_event_risk_tasks.py` (10s Beat task + audit envelope) + beat_schedule.py + celery_app.py registration. 9 TDD tests + reviewer cycle 1 P1+P2 fixed same-iter (canonical `_write_scheduler_log_safe` adoption + multi-worker consumer_name + caller-supplied redis client).
- iter 185 closure: this manifest update + CLAUDE.md L18 + STATUS_REPORT

**Latency budget**: outbox 30s + consumer 10s = ~40s worst-case (vs current ~60s `l4_sweep_tasks` polling). ~33% improvement.

**Owner**: ✅ closed iter 183-185 (CC autonomous, batched-iter pattern per user efficiency directive)
**Effort actual**: ~1h cumulative wallclock vs ~1 week manifest estimate (batched + reality re-grounded scope reduction)
**Path B-2 prerequisite**: ✅ Code-level wire complete. Live cutover gates remain at `.env` paper→live (separate user authorization).

---

### §1.5 (legacy, sustained for cross-ref) 流 3 → 流 4 Trade Event Publish (5min Polling Gap)

**Source**: Wave 1 Agent D 流 3 cross-flow

**Real issue**:
- `trade_log` INSERT 后 → 风控流 trigger **隐式** (无显式 publish event)
- 当前依赖 5min Beat `risk-l4-sweep-1min` polling
- 真后果: 真发单 → tick 级风控介入 **~60s gap**, live-mode 不可接受

**Phase J 修法**:
- StreamBus publish `qm:trade:executed` event after trade_log INSERT
- RealtimeRiskEngine subscribe `qm:trade:executed` Redis stream, tick-level 风控介入
- Event sourcing pattern (Plan v8 §3-bis Alt C "Event-sourcing trade_log" 候选)

**Owner**: Backend dev, V3 §3.2 event bus scope
**Effort**: ~1 week
**Path B-2 prerequisite**: 🟡 paper-mode tolerable (1 持仓), 真账户 5-27 后 multi-position 必修

---

## §2 P0 Engineering Refactor (Phase B-2 post 5-27)

### §2.1 铁律 31 violation — `datafeed.py:94` (Agent A finding)

**Real issue**:
- `backend/engines/datafeed.py:94`: `psycopg2.connect(db_url)` inside `backend/engines/`
- 违反 铁律 31: Engine 层纯计算, 0 IO

**修法**: 改 factory pattern, caller 传 conn (单文件 narrow blast). OR 移到 `backend/app/services/`.

**Effort**: ~1h refactor + caller adjust + test
**Path B-2 timing**: Post 5-27 cutover

---

### §2.2 铁律 32 violation — `data_orchestrator.py:256` + `strategy_bootstrap.py:99` (Agent A)

**Real issue**:
- `data_orchestrator.py:256`: `self._conn.commit()` inside service method `mark_success`
- `strategy_bootstrap.py:99`: `conn.commit()` inside service file
- 违反 铁律 32: Service 不 commit, 事务由调用方管

**修法**:
- `mark_success`: 加 F16-classC tag (like `risk_control_service.py:1199`) 标 idempotent bookkeeping OR 移 commit out to caller
- `strategy_bootstrap.py`: 移 commit to FastAPI startup hook (per docstring)

**Effort**: ~2h refactor + cross-caller verify
**Path B-2 timing**: Post 5-27

---

### §2.3 Regression Baseline Refresh

**Source**: Wave 1 Agent E

**Real issue**:
- `cache/baseline/regression_result_5yr.json` mtime 2026-04-28 (22 days stale)
- `cache/baseline/regression_result_12yr.json` 22 days stale
- `metrics_5yr.json` 41 days stale (4-09)
- 铁律 15 `max_diff=0` 契约 22d 无 fresh verify

**修法**: `python scripts/run_backtest.py --config configs/pt_live.yaml` re-run, refresh baseline parquet + json, git tag pin.

**Constraint**: 跑 backtest 可能触 CB factor compute call surface (factor_engine read) — Phase B-1 frozen 期内 read-only DB OK, 但脚本本身 compute-heavy. 留 user trigger.

**Effort**: ~30min - 1h (depends on cache state)
**Path B-2 prerequisite**: ✅ **5-27 Wed live flip 前应 refresh** (回测 = 实盘契约 max_diff=0 必 fresh verify)

---

## §3 P1 User Touchpoint (留 user 决议触发)

### §3.1 S2 PG Password Rotation (Plan v8 P0-2 老)

**Source**: ISSUES_PENDING_REGISTRY §1 + `docs/runbook/pg_password_rotate_playbook.md` (5-20 新增)

**Status**: Playbook ready, user trigger required (high-risk credential mutation, PG superuser)

**Path B-2 recommended**: 5-27 Wed 后 (live flip 后, 系统稳态 evening window)

---

### §3.2 4 Schtask Register (cumulative pending)

**Source**: STATUS_REPORT_2026_05_20_pt_paper_dryrun_day1.md §6

**4 commands ready, user execute** (elevated PowerShell):
1. `QuantMind_RotateServyLogs` (daily 02:00)
2. `QuantMind_SchtaskFreshnessProbe` (daily 09:00)
3. `QuantMind_BeatHeartbeatProbe` (every 5 min, `/SC MINUTE /MO 5`)
4. `QuantMind_MarketOpenWatcher` (daily 09:31)

**Commands sediment**: docs/audit/STATUS_REPORT_2026_05_19_*.md 各 STATUS_REPORT 中

**Why blocked**: CC autonomous schtask register breaks 5/5 红线 (0 schtask register), 故留 user 触发

---

### §3.3 F2 BGE-M3 RAG Embedding Cron

**Source**: ISSUES_PENDING_REGISTRY F2

**Status**: 21 rows ready in risk_memory, embedding column NULL → RAG retrieve broken

**Effort**: ~4h script + GPU resource decision (RTX 5070 12GB available, BGE-M3 1024-dim, batch 100)
**Owner**: User (GPU resource allocation) + Backend dev (script + cron schedule)

---

## §4 P0 Multi-Doc N×N Drift Resolution

### §4.1 factor_values / minute_bars 跨 SSOT 漂移 (Wave 3 fix5 处理)

CLAUDE.md L29/L31 vs SYSTEM_STATUS.md:726/732 真值差 1.37x-1.67x

**fix5 在跑** (a145040a15b4f11df): DB fresh count + CLAUDE.md update

**SYSTEM_STATUS.md 同步**: fix5 完成后, **应 sediment 一份 cross-doc sync task** 把 SYSTEM_STATUS.md:726/732 也 update to fresh DB count.

**Effort**: ~10min once fix5 completes

---

### §4.2 ML_WALKFORWARD_DESIGN.md / GP_CLOSED_LOOP_DESIGN.md / DATA_SYSTEM_V1.md 3 Archive Candidates

**Source**: Wave 1 Agent C P2 stale

**3 docs** (>30 day stale, superseded):
- `docs/ML_WALKFORWARD_DESIGN.md` (4-10, 41d) — G1 NO-GO + ML 预测层 CLOSED
- `docs/GP_CLOSED_LOOP_DESIGN.md` (4-17, 34d) — GP AlphaZero 升级后 0 sediment
- `docs/DATA_SYSTEM_V1.md` (4-17, 34d) — Wave 2 真实现 superseded

**Conservative archive**:
1. Move to `docs/archive/<name>_2026_05_20_archived.md`
2. Add DEPRECATED header pointing to current source (per `RISK_CONTROL_SERVICE_DESIGN.md` P0-18 closure pattern)
3. Update CLAUDE.md 文档查阅索引 link (`docs/<name>.md` → `docs/archive/<name>_archived.md`)

**Why defer to user**: archive 涉及 grep refs 跨 doc + CLAUDE.md link update + ADR/research-kb cross-ref. 保守留 user 决议.

**Recommended Phase B-2**: 5-27 后 cleanup batch.

---

## §5 P1/P2 Engineering Cleanup (Opportunistic)

| # | Source | Item | Effort |
|---|---|---|---|
| C-1 | Agent A | `backend/engines/broker_qmt.py` 0 dedicated test | ~4h mock test |
| C-2 | Agent A | 2 magic timeouts (llm_cost / slippage) → yaml-driven | ~1h |
| C-3 | Agent A | `_extract_cost_usd` 99 lines refactor (split fallback) | ~2h (defer if test dense) |
| C-4 | Agent E | pytest markers `slow` / `integration` register in pyproject.toml | ~10min |
| C-5 | Agent E | `db_session` fixture hardcoded `xin:quantmind@localhost` → env var | ~30min (铁律 35) |
| C-6 | Agent E | `test_execution_mode_isolation.py` 2 xfail strict=True (BATCH 2 BUG) | post BATCH 2 fix |
| C-7 | Agent B | M-3 28+ scripts hardcoded `password="quantmind"` | git history scrub (high-risk, defer) |
| C-8 | Agent C | M=213 vs M=240 FACTOR_TEST_REGISTRY internal contradiction | reconcile + Step 6.4 G1 freshen |
| C-9 | Agent C | DEV_PARAM_CONFIG.md 25% sustained (220 design vs 50 real) | already P1-40 sediment, sustain |

---

## §6 Estimate

| Tier | Items | Effort | Path B timing |
|---|---|---|---|
| **P0 Path B-2 prerequisite** (5-27 前必修) | §1.1 + §1.2 + §1.3 + §2.3 | ~5-10d | Pre 5-27 |
| **P0 Path B-2 post 5-27** | §1.4 + §1.5 + §2.1 + §2.2 | ~3-4w | Post 5-27 |
| **P1 user touchpoint** | §3.1 + §3.2 + §3.3 + §4.2 | ~2-4h user + ~1d code | User decision |
| **P2 opportunistic** | §5 全 9 项 | ~12-16h | Backlog |

**Total Phase J / B-2 backlog**: ~7-10w 真 implementation, +1w cross-doc sync + cleanup.

---

## §7 User Decision Required

1. **5-27 Wed live flip 时机**: 5d paper-mode dry-run (5-20→5-26) PASS 后, user 决议 EXECUTION_MODE=paper→live + LIVE_TRADING_DISABLED=true→false 翻牌. 当前 5-20 Day 1 中.
2. **流 4 风控 chain wire** Option A/B/C 选择 (§1.1)
3. **PT 重启 Top-N**: 灰度 5 → 10 → 20 节奏
4. **3 archive candidates** (§4.2): autonomous archive OR sustain
5. **regression baseline refresh** 跑哪天 (§2.3)
6. **4 schtask register** (§3.2) — 一次性 elevated PowerShell

---

**Coordinator**: Claude Opus 4.7 (1M context)
**Verified cite**: Wave 1 Agent A/B/C/D/E reports (5 doc) + ISSUES_PENDING_REGISTRY + STATUS_REPORT_2026_05_20_pt_paper_dryrun_day1.md
**Next**: Wave 4 verify (post fix5 completion) + commit batch
