# Wave 2 Synthesis — 5 Wave 1 Audit Agents 综合 (2026-05-20)

**Trigger**: `/goal` 5-20 — coordinator-role 综合审计 + 闭环验证
**Branch**: feature/plan-v8-batch-cumulative-5-19-20  HEAD=4ad9c3f
**Phase**: Phase B-1 paper-mode dry-run (5-20→5-26), 5/5 红线 sustained
**Time**: 2026-05-20 SH (Day 1 morning)

---

## §1 Wave 1 Agent Outputs Summary (5/5 完成)

| Agent | Type | Scope | Output |
|---|---|---|---|
| A | Code Health | 铁律 31/32/33 + dead code + magic | 5 P1 + 11 P2 silent annotations + 2 magic timeouts. 真严重 0 P0. |
| B | Security | secrets / inj / API auth / broker bypass | 2 HIGH (eval sandbox + EXECUTION_MODE override) + 2 MEDIUM (eval inner / SQL fstring). 5/5 红线 sustained ✅. |
| C | Doc Drift | CLAUDE.md numeric vs reality | 5 P0 漂移 (PT_TOP_N / factor_values / minute_bars / 测试 baseline / cash 精度) + 3 archive 候选 |
| D | Business Closed-Loop | 6 流 trace | 1/6 ✅ + 4/6 🟡 + 1/6 ❌ (流 4 风控 P0 chain wire). 5 silent break surfaced. |
| E | Test Coverage | pytest + smoke + critical path | baseline 6251/0 vs CLAUDE.md 2864 stale + 22d regression stale + 3 NEW script 0 test |

---

## §2 P0/P1 Triage (cross-agent dedup)

### §2.1 P0 — Immediate Action (Wave 3 Dispatch)

| # | Source | Finding | Action | Status |
|---|---|---|---|---|
| P0-W3-1 | Agent B H-1 | `eval_agent.py:138` exec() `__builtins__` 不限 → RCE 风险 | Wave 3 fix1 (a2c21d05469a297b8) | 🟡 running |
| P0-W3-2 | Agent B H-2 | `daily_reconciliation.py:76` + `intraday_monitor.py:141` `os.environ["EXECUTION_MODE"]="live"` 静默 SSOT 旁路 (违反 铁律 34, 定时炸弹) | Wave 3 fix1 (a2c21d05469a297b8) | 🟡 running |
| P0-W3-3 | Agent C drift | CLAUDE.md 测试 baseline "2864 / 24 fail" → 真值 6251 collected | Wave 3 fix3 (af92321f29e53d6a7) | 🟡 running |
| P0-W3-4 | Agent C drift | CLAUDE.md PT_TOP_N=20 vs 真值 5 (5-18 灰度 sustained .env + pt_live.yaml) — **生产 SSOT 错位** | Wave 3 fix5 (待 fix3 完成后 dispatch) | ⏸ queued |
| P0-W3-5 | Agent C drift | CLAUDE.md factor_values 840M vs SYSTEM_STATUS 501M (4-07 snapshot) — 1.67x 跨 doc 漂移 | Wave 3 fix5 (待 fix3 完成后) — note 需 fresh DB verify | ⏸ queued |
| P0-W3-6 | Agent C drift | CLAUDE.md minute_bars 190M vs SYSTEM_STATUS 139M (4-17 snapshot) — 1.37x | Wave 3 fix5 (待 fix3 完成后) | ⏸ queued |
| P0-W3-7 | Agent C drift | CLAUDE.md cash ¥993,520 (取整) vs ¥993,520.66 (memory + DB) — 精度丢 | Wave 3 fix5 (待 fix3 完成后) | ⏸ queued |

### §2.2 P0 — Phase J / B-2 Defer (multi-week, sediment 设计)

| # | Source | Finding | Defer Reason | Owner |
|---|---|---|---|---|
| P0-DEFER-1 | Agent D 流 4 | **AlertDispatcher 0 production caller** — alert.py:22-23 自述 "tests-only usage". tick→engine→dispatcher→DingTalk 整链未 wire 到 Beat. P0 alert 真无人发. | 多周 wire 工作, V3 §5/6 实施. Path B-2 (5-27 Wed live flip) prerequisite. | Phase J 多周 |
| P0-DEFER-2 | Agent D 流 4 | **L4 STAGED plan 创建源未 wire** — `l4_sweep_tasks.py` broker.sell wire 完整, 但 plan 创建 (RealtimeRiskEngine + L4ExecutionPlanner) 0 caller. l4_sweep 实际空跑. | 同上 chain 上游断, 多周修. | Phase J 多周 |
| P0-DEFER-3 | Agent A 铁律 31 | `backend/engines/datafeed.py:94` psycopg2.connect inside engines/ — pre-existing 违反, 单文件 narrow blast | Phase B-2 post 5-27 重构 (multi-file refactor) | Phase J |
| P0-DEFER-4 | Agent E | regression baseline 4-28 22 天 stale — `max_diff=0` 契约 22d 间无 fresh verify | Phase B-2 refresh post 5-27 (re-run scripts/run_backtest.py) | User trigger required |

### §2.3 P1 — Wave 3 Batch (autonomous safe)

| # | Source | Finding | Action |
|---|---|---|---|
| P1-W3-1 | Agent A | 2 P1 silent except (`pg_backup.py:115` + `disaster_recovery_verify.py:75`) 收紧 except + logger.warning | Wave 3 fix2 (afc1422f51ff1000c) |
| P1-W3-2 | Agent A | 11 P2 silent annotations 加 `# silent_ok:` | Wave 3 fix2 |
| P1-W3-3 | Agent A | `data_orchestrator.py:256` 铁律 32 violation (service commit) — 改用 F16-classC 标记 OR 移除 | Defer Phase B-2 (multi-file analysis) |
| P1-W3-4 | Agent A | `strategy_bootstrap.py:99` 铁律 32 — 移到 startup hook | Defer Phase B-2 |
| P1-W3-5 | Agent A | 2 magic number timeouts in `llm_cost_audit_tasks.py:67` + `slippage_calibration_tasks.py:70` — yaml-driven | Defer (low impact, sustained) |
| P1-W3-6 | Agent E | 3 NEW scripts 0 smoke test (generate_system_diagram / build_traceability_index / audit_design_doc_smoke) | Wave 3 fix4 (a64f208528b938962) |
| P1-W3-7 | Agent E | `backend/engines/broker_qmt.py` 0 dedicated test | Defer Phase B-2 (broker_qmt.py mock test 需 LL-182 fix verification scope, 多日 effort) |
| P1-W3-8 | Agent C | 3 docs archive 候选 (ML_WALKFORWARD / GP_CLOSED_LOOP / DATA_SYSTEM_V1) — 30+ 天 stale + 已 superseded | Wave 3 fix6 (optional, conservative defer to user decision) |

### §2.4 P1 — Phase J defer (multi-week)

| # | Source | Finding | Defer Reason |
|---|---|---|---|
| P1-D1 | Agent D 流 5 | `daily_reconciliation` schtask Disabled 自 4-29 PT 清仓后, 复活留 PT 重启 prerequisite | PT 重启 user 决议依赖 |
| P1-D2 | Agent D 流 6 | RAG consumer 单点 (RiskMemoryRAG 仅 reflector 自反馈, NewsClassifier / Bull / Bear 0 wire) — TB-4d/TB-5 wire scope | V3 TB-5 多周 |
| P1-D3 | Agent D 流 3→4 | trade_log INSERT 后 trade event publish 缺失 → 风控 5min polling gap | V3 §3.2 event bus 多周 |
| P1-D4 | Agent B H-2 (extended) | `intraday_monitor.py` dormant 但 same EXECUTION_MODE override pattern (修后即 closed) | Wave 3 fix1 含 |

### §2.5 P2 — Cleanup batch (Phase B-2 / opportunistic)

- M-3 28+ files hardcoded `password="quantmind"` (known localhost issue)
- M-4 f-string SQL table name (internal var, low risk)
- L1 No FastAPI rate limit (localhost personal)
- Long functions (4 个 >80 lines) — defer
- xfail strict=True 2 个 BATCH 2 BUG (待 BATCH 2 fix flip green)
- pytest markers `slow / integration` 未 register in pyproject.toml

---

## §3 Wave 3 Dispatch Status (4 running, 1 queued)

| Agent ID | Scope | Files | Status |
|---|---|---|---|
| a2c21d05469a297b8 | Security H-1 + H-2 | eval_agent.py / daily_reconciliation.py / intraday_monitor.py | 🟡 running |
| afc1422f51ff1000c | Silent annotations | 12 files (2 P1 收紧 + 10 P2 注释) | 🟡 running |
| af92321f29e53d6a7 | CLAUDE.md test baseline drift | CLAUDE.md (单 file) | 🟡 running |
| a64f208528b938962 | Smoke tests 3 NEW scripts | backend/tests/ 加 3 files | 🟡 running |
| **fix5 (待 dispatch)** | CLAUDE.md remaining drift (PT_TOP_N + factor counts + cash) | CLAUDE.md (after fix3) | ⏸ blocked on fix3 |

---

## §4 Wave 4 Verify Plan (待 Wave 3 完成后)

### §4.1 Test Suite Verify
- [ ] `python -m pytest backend/tests/ --co -q 2>&1 | tail -5` → 应 ≥ 6251 collected, 0 errors
- [ ] `python -m pytest backend/tests/test_realtime_alert.py backend/tests/test_l4_execution_planner.py backend/tests/test_dry_run_no_broker_call.py -x -q` (critical path)
- [ ] 3 NEW smoke tests `python -m pytest backend/tests/test_generate_system_diagram_smoke.py backend/tests/test_build_traceability_index_smoke.py backend/tests/test_audit_design_doc_smoke_smoke.py -v`
- [ ] `python -m pytest -m smoke --co -q | tail -5` → ≥ 70 + 6 NEW = ~76 smoke collected (PASS rate)

### §4.2 5/5 红线 Verify Cite
- [ ] grep `LIVE_TRADING_DISABLED` backend/.env → `true`
- [ ] grep `EXECUTION_MODE` backend/.env → `paper`
- [ ] grep `QMT_ACCOUNT_ID` backend/.env → `81001102`
- [ ] grep `DINGTALK_ALERTS_ENABLED` backend/.env → `true`
- [ ] config.py default `LIVE_TRADING_DISABLED: bool = True` (Agent B verify L94)

### §4.3 Git Status Verify
- [ ] `git status --short` → 仅 Wave 3 changes (12 silent annotations + 3 security + CLAUDE.md + 3 smoke tests + this synthesis doc)
- [ ] `git diff --stat` → no surprising file additions

### §4.4 Sediment + Commit
- [ ] STATUS_REPORT_2026_05_20_wave_2_synthesis.md ← 本 doc 升级版 (post-Wave 3 验证后)
- [ ] git add 各 Wave 3 changes + 本 doc
- [ ] git commit (single batch OR分组: security + code-health + doc-drift + tests)
- [ ] **不 push** (PR 创建留 user 触发 OR autonomous if classifier allows)

### §4.5 Sediment to Memory Handoff
- [ ] Prepend `memory/project_sprint_state.md` with Day 1 morning Wave 1-4 cumulative + 5/5 红线 sustained + Phase J defer list

---

## §5 Phase J / Phase B-2 Defer Manifest

**P0 multi-week / user-decision** (sediment to Phase J planning doc):
1. **流 4 风控 chain wire** — V3 §5/6 实施, AlertDispatcher 接 Beat scheduler + L4 plan 创建源接 RealtimeRiskEngine. 多周 effort.
2. **流 5 daily_reconciliation schtask 复活** — PT 重启 prerequisite, 需 user 决议 5-27 Wed live flip 时机.
3. **流 6 RAG consumer wire** — TB-4d/TB-5 NewsClassifier + Bull/Bear consumer RAG retrieval. V3 §5.4 设计 vs 真实现 gap.
4. **regression baseline refresh** — `scripts/run_backtest.py --config configs/pt_live.yaml` re-run, refresh `cache/baseline/` parquet + json. 留 user trigger (compute-heavy, possible CB call surface).
5. **铁律 31/32 重构** — datafeed.py / data_orchestrator.py / strategy_bootstrap.py engine/service layer cleanup. Phase B-2 post 5-27.

**P1 multi-week / lower priority**:
- broker_qmt.py dedicated mock test (LL-182 fix verification scope)
- 2 magic timeout → yaml-driven (LLM cost + slippage tasks)
- M=213 vs M=240 FACTOR_TEST_REGISTRY internal contradiction (B3 ssor + Step 6.4 G1 reconcile)

---

## §6 Coordinator Decision Log

| Decision | Reason |
|---|---|
| **不 dispatch fix5 此时** | af92321f29e53d6a7 (fix3) 正改 CLAUDE.md, fix5 同 file 写冲突. 待 fix3 完成后 sequentially dispatch. |
| **不 dispatch fix6 (docs archive)** | 保守: archive 设计 doc 涉及 grep refs 跨 doc links 风险, 留 user decision OR Wave 4 verify 后 separate batch. |
| **流 4 风控 wire 不 fix** | 多周 effort, V3 §5/6 实施 scope, Phase B-2 post 5-27 cutover 前修. 本 audit sediment 设计 prereq 即可. |
| **regression baseline 不 refresh** | 跑 scripts/run_backtest.py 可能触 CB call / DB 重读, Phase B-1 frozen 期内 read-only 优先. Phase B-2 user trigger. |
| **N×N drift fix 不批量** | fact_values 840M vs 501M 跨 SSOT doc 矛盾 — 真值需 DB query (Phase B-1 0 DB row mutation OK, query 不变 row count). 留 fix5 + 复测. |

---

## §7 Next Steps (Coordinator)

1. **等 4 个 Wave 3 fix agents 完成** (notifications auto)
2. **fix3 (af92321f29e53d6a7) 完成后**: 立即 dispatch fix5 (CLAUDE.md remaining drift items)
3. **所有 Wave 3 完成后**: 派 Wave 4 verifier agent (pytest critical path + 5/5 红线 cite + git status)
4. **Wave 4 PASS 后**: 派 git executor agent (commit batch + sediment STATUS_REPORT 升级版 + memory handoff prepend)
5. **Phase J defer manifest** (§5) → sediment 到 `PHASE_J_DEFER_2026_05_20.md` 给 user 阅读

---

## §8 Verification Evidence (cite source, 铁律 2)

每 finding cite source 全在 Wave 1 agent 报告:
- Agent A: file:line per 铁律 33/31/32 violation
- Agent B: file:line per OWASP type, cite verify cite admin_token / LIVE_TRADING_DISABLED config.py:94 default
- Agent C: file:line + grep cite cross-doc
- Agent D: file:line per 流 + 自述 (alert.py:22-23 0 production caller)
- Agent E: pytest --co 实跑 output 6251 collected

5/5 红线 source: `backend/.env` (LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper) + config.py:94 default + redline_pretool_block.py hook + StagedExecutionService factory check

---

**Coordinator**: Claude Opus 4.7 (1M context)
**Wave 1-3 elapsed**: ~30 min audit + ~待 fix completion
**Wave 4 estimate**: ~15 min verify + commit
**Total /goal session**: ~50-90 min target
