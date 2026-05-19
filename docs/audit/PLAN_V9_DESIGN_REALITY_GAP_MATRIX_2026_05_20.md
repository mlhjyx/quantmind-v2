# Plan v9 — Design-Reality Gap Matrix (2026-05-20)

> **Trigger**: User `/goal` 5-20 — "代码 vs 设计文档对照,识别 gap,更新文档,修复问题,实施闭环"
> **Method**: 8 parallel read-only audit agents (DEV_BACKEND/BACKTEST/FACTOR/FRONTEND/SCHEDULER/PARAM/AI_EVOLUTION/NOTIFICATIONS+GP+RISK)
> **Phase**: Continuation of Plan v8 closure (97% baseline) — Plan v9 is deeper design-reality reconciliation
> **Phase B-1 frozen**: 0 broker / 0 .env / 0 schtask register / 0 DB row mutation. 5/5 红线 sustained.

---

## §1 Executive Summary

| Doc | Design Quality | Code Match % | Critical Gap |
|---|---|---|---|
| **DEV_BACKEND.md** | 良 | 70% | 端点 96→148 (+54%) + 铁律 32 9 violations (5 documented, 2 真) |
| **DEV_BACKTEST_ENGINE.md** | 部分过时 | 65% | §1-§十 Rust engine (never impl) + §4.11 印花税分段 (only fixed) + §4.9 can_trade 缺 |
| **DEV_FACTOR_MINING.md** | 数字漂移 | 55% | Alpha158 158→实际~40 + Phase C 数字 |
| **DEV_FRONTEND_UI.md** | 严重过时 | 65% | 后端 123 vs 前端 11 module 消费 gap + Phase H W1-W6 5 NEW未文档化 |
| **DEV_SCHEDULER.md** | 部分过时 | 30% (doc 自标) | IcRolling 18:15 design 有 code 0 + 2 task stub 未实现 |
| **DEV_PARAM_CONFIG.md** | DESIGN_OVERSIZED | 25% | 220 → 50 真; doc 自标过时 |
| **DEV_AI_EVOLUTION.md** | 数字严重漂移 | 45-55% | CLAUDE.md "0% 实现" 漂移; V3 §S5-S8 全 merged main |
| **DEV_NOTIFICATIONS.md** | 路径漂移 | 60% | 设计路径 `qm_platform/risk/realtime/` vs 实际 `app/services/risk/` |
| **GP_CLOSED_LOOP_DESIGN.md** | 数字未验证 | 45% | "7 new operators / 243 tests" Session 16d claim 无 git 证据 |
| **RISK_CONTROL_SERVICE_DESIGN.md** | L4 已弃用 | 35% | doc 自标 deprecated; L4 真 SSOT = V3_DESIGN.md + ADR-027 |

**Overall**: ~50% 文档真实反映代码; ~30% 文档严重漂移 (数字 + 路径); ~20% 文档自标过时但未实质更新.

---

## §2 P0 Issues (immediately fixable — autonomous)

### §2.1 文档 vs 代码 数字漂移 (10 项)

| # | Item | Doc 标 | 真值 | Fix |
|---|---|---|---|---|
| 2.1.1 | DEV_BACKEND endpoint count | "~96" | 148 (54% gap) | DEV_BACKEND.md update |
| 2.1.2 | CLAUDE.md AI EVOLUTION 完成度 | "0% 实现 (agents/ 已删)" | 45-55% (Layer 1=95% / Layer 2=60%) | CLAUDE.md L722 update |
| 2.1.3 | DEV_FACTOR_MINING Alpha158 | "158 因子" | ~40 (16 def in alpha158_factors.py + 5 composite) | DEV_FACTOR_MINING.md update |
| 2.1.4 | DEV_FACTOR_MINING Phase C | "2049 → 416 行" | 实际 ~1800+ (package total) | DEV_FACTOR_MINING.md update |
| 2.1.5 | DEV_PARAM_CONFIG | "220+ params" | ~50 (doc 自标 DESIGN_OVERSIZED) | DEV_PARAM_CONFIG.md 顶部 warning + SSOT redirect |
| 2.1.6 | DEV_SCHEDULER 完成度 | "30%" (doc 自标) + missing 项 | Beat 20 entries + 27 schtask + 2 stub | DEV_SCHEDULER.md update |
| 2.1.7 | DEV_BACKTEST_ENGINE §1-§十 Rust | "Rust 引擎" | NEVER IMPLEMENTED | Annotate HISTORICAL/NEVER_IMPLEMENTED 显式 |
| 2.1.8 | DEV_BACKTEST_ENGINE §4.11 印花税分段 | "2023-08-28 前后分段" | 仅 fixed 0.0005 | Doc update OR code impl (P0 选 doc update + P1 code impl) |
| 2.1.9 | RISK_CONTROL_SERVICE_DESIGN L4 | "L4 state machine" | L4 deprecated, V3 ADR-027 SSOT | Doc add redirect header |
| 2.1.10 | DEV_NOTIFICATIONS 路径 | `qm_platform/risk/realtime/alert.py` | `app/services/risk/dingtalk_webhook_service.py` | Path correction |

### §2.2 配置真实漂移

| # | Item | 现状 | Fix |
|---|---|---|---|
| 2.2.1 | backtest_12yr.yaml 因子 | CORE5 (旧) | 同步 pt_live.yaml CORE3+dv_ttm |
| 2.2.2 | backtest_5yr.yaml 因子 | CORE5 (旧, 含 reversal_20/amihud_20) | 同步或显式保留 baseline 用 (添加注释) |
| 2.2.3 | .env Session 57 keys | 30 keys | AI_ASSIST_ENABLED / PT_START_DATE / PT_TOTAL_DAYS 同步 .env.example |

---

## §3 P1 Issues (code 真问题 — autonomous-fixable)

### §3.1 铁律 32 (Service no-commit) — 2 真违规未注释

| File:Line | 状态 | Fix |
|---|---|---|
| `backend/app/services/data_orchestrator.py:256` | 🔥 Active violation, 无 inline rationale | 加 `# F16-classC` 注释 OR refactor 至 caller |
| `backend/app/services/t0_19_audit.py:506` | 🔥 Active violation, 无 rationale | 加注释 OR refactor |
| `backend/app/services/dingtalk_alert.py:182` | 🔥 Active, 无注释 | 加 leaf utility 例外注释 |

### §3.2 回测引擎 真值缺失

| Item | File:Line | Severity | Fix |
|---|---|---|---|
| 三因素滑点 overnight_gap_bps deduction | `backend/engines/backtest/broker.py` | P1 | broker.py execution path 加 gap 成本扣除 |
| can_trade 涨跌停/停牌检查 | `backend/engines/backtest/validators.py` (105 行不足) | P0 (信号能成交幻觉) | 实现 can_trade OR 明确委派 broker.py |
| 印花税 historical 分段 (2023-08-28) | `backend/engines/backtest/broker.py` 或 `cost_model.py` | P1 | 实现分段 OR 文档明确 "仅 fixed 0.05%" |

### §3.3 调度真值 gap

| Item | 现状 | Fix |
|---|---|---|
| IcRolling 18:15 Beat entry | DEV_SCHEDULER design 有, code 0 实现 | 移除 design table OR 实现 (注: schtask QuantMind_IcRolling 18:15 已存在, 但 Beat entry 缺) — 真值 verify 后 doc 修正 |
| `app/tasks/beat_schedule.py:382` llm-cost-monthly-audit | task = NotImplementedError | 实现 OR 删除 Beat entry |
| `app/tasks/beat_schedule.py:404` slippage-calibration-quarterly | task = NotImplementedError | 实现 OR 删除 Beat entry |

### §3.4 GP / 知识库 数字未验证

| Item | Claim | Fix |
|---|---|---|
| GP Session 16d "7 new operators + 243 tests" | 无 git evidence | 实测 backend/engines/mining/ + pytest count + 沉淀 |
| FACTOR_TEST_REGISTRY.md "M=213" | 文件无累计 M 字段 | 添加 M 累计统计 OR 移除引用 |

---

## §4 Phase J (Multi-week defer — sustained per Plan v8 manifest)

| Item | Why defer | Plan v8 ref |
|---|---|---|
| 流 4 风控 chain wire (AlertDispatcher → Beat) | 3-7d, multi-week | PHASE_J_DEFER_MANIFEST_2026_05_20.md |
| 流 5 daily_reconciliation schtask 复活 | ~2h code + schtask | 同上 |
| 流 6 RAG consumer wire (V3 §5.4) | 1-2w | 同上 |
| 流 3→4 trade event publish | 1w | 同上 |
| Layer 3-4 (DEV_AI_EVOLUTION) Feature Map + Capital alloc | Q3-Q4 trigger per ADR-028 | 0 active maintenance |
| Frontend Phase I 样式 dual-track 迁移 | 50h | LL-187 |
| 端点覆盖审计 (123 backend vs 11 frontend modules) | 3h, defer to Phase J | docs/API_COVERAGE.md 新增 |
| Survivorship bias 审计 (回测) | ~2w research | DEV_BACKTEST_ENGINE.md §0 addendum |
| OOS 异质性 (5yr=0.61 / 12yr=0.36 / WF=0.87) 调查 | ~2w research | Phase J.4 |

---

## §5 User Touchpoint (cannot autonomous)

| Item | Cite |
|---|---|
| PG password rotation execute | docs/runbook/pg_password_rotate_playbook.md (S2) |
| DingTalk HMAC secret 配置 | P1-43 Plan v8 |
| 4 schtask register (RotateServyLogs / SchtaskFreshnessProbe / BeatHeartbeatProbe / MarketOpenWatcher) | scripts/register_phase_b_1_schtasks.ps1 ready |
| 5-27 Wed live flip 第 3 trigger '你执行' | ADR-027 §7 |
| 11 stale local branches cleanup | STALE_BRANCHES_AND_PRS_AUDIT_2026_05_20.md |
| 3 stale OPEN PRs (#303/304/305) 关闭 + 沉淀 | 同上 |

---

## §6 超越设计 (Code > Docs — 必须沉淀文档)

| Item | 真值位置 | 当前 doc 状态 |
|---|---|---|
| 6.1 API 端点 96→148 (+54%) | backend/app/api/* + main.py:104-128 | DEV_BACKEND.md 严重 undercount |
| 6.2 Service 层 25→57 files | backend/app/services/ recursive | DEV_BACKEND.md 缺 services/news/ + services/risk/ subdirs |
| 6.3 Phase H W1-W6 frontend 5 NEW components | EnvStateBanner / ShutdownBanner / SafetyControlPanel / ConfirmModal / AssistPanel | DEV_FRONTEND_UI.md 缺 |
| 6.4 RAG memory backfill | 20 历史 events real DB | DEV_AI_EVOLUTION.md 缺 |
| 6.5 DeepSeek pricing fallback (LiteLLM cost) | F-S7-001 Session 57 commit 23ebea5 | DEV_AI_EVOLUTION.md 缺 |
| 6.6 V3 §S5 RealtimeRiskEngine + 9 rules + 104 tests | backend/qm_platform/risk/realtime/engine.py | DEV_AI_EVOLUTION.md 0% claim 完全漂移 |
| 6.7 V3 §S6 AlertDispatcher + 28 tests | backend/qm_platform/risk/realtime/alert.py | 同上 |
| 6.8 V3 §S7 DynamicThresholdEngine + 48 tests | backend/qm_platform/risk/dynamic_threshold/ | 同上 |
| 6.9 V3 §S8 RiskReflector TB-4a-d + 154 tests | backend/qm_platform/risk/reflector/agent.py | 同上 |
| 6.10 6 news fetchers (anspire/gdelt/tavily/zhipu/marketaux/rsshub) | backend/qm_platform/news/*.py | DEV_AI_EVOLUTION.md 缺 |
| 6.11 Market Regime 3 daily cadence (9:00/14:30/16:00) | backend/qm_platform/risk/regime/agents.py | DEV_AI_EVOLUTION.md 缺 |
| 6.12 Calendar gate is_trading_day_today_or_skip | beat_schedule.py:22-38 (post LL-181) | DEV_SCHEDULER.md 缺 |
| 6.13 Meta-monitor 5min HC-1b 元告警 | beat_schedule.py:360 | DEV_SCHEDULER.md 缺 |
| 6.14 EnvStateBanner /api/system/env-state 5s 轮询 | frontend/src/components/safety/EnvStateBanner.tsx | DEV_FRONTEND_UI.md + DEV_BACKEND.md 缺 |
| 6.15 Axios SSOT 14→0 raw axios | frontend/src/api/client.ts L2 fix | DEV_FRONTEND_UI.md 缺 |

---

## §7 Plan v9 Closure Roadmap

### §7.1 Phase A (DONE) — Audit
- ✅ 8 parallel agents read-only audit
- ✅ This matrix doc sediment

### §7.2 Phase B (DONE — this doc) — Synthesis
- ✅ Unified gap matrix
- ✅ P0/P1 triage
- ✅ Phase J defer manifest cross-ref

### §7.3 Phase C — Autonomous Fix (immediate)
- **C-1**: Doc number drift (10 P0 items in §2.1) — parallel doc-update agents
- **C-2**: Code violation annotations (3 铁律 32 sites in §3.1)
- **C-3**: backtest config alignment (backtest_12yr/5yr factor sync — §2.2.1/2)
- **C-4**: 2 task stub decision (delete OR implement, §3.3)
- **C-5**: validators.py can_trade 实现 (§3.2 信号能成交幻觉 P0)
- **C-6**: broker.py overnight_gap_bps deduction (§3.2 P1)

### §7.4 Phase D — Doc Update (post-fix)
- DEV_BACKEND.md endpoint count + service expansion + 铁律 32 exception list
- DEV_BACKTEST_ENGINE.md §1-§十 HISTORICAL annotation + 印花税 + can_trade
- DEV_FACTOR_MINING.md Alpha158 真值 + Phase C 数字 + IC Beat wire status
- DEV_FRONTEND_UI.md Phase H W1-W6 沉淀 + ConfirmModal 4-tier
- DEV_SCHEDULER.md 20 Beat + 27 schtask + IcRolling status + 2 stub
- DEV_PARAM_CONFIG.md header warning + SSOT redirect
- DEV_AI_EVOLUTION.md V3 §S5-S8 fully merged + Layer 1-2 60% + Q3-Q4 trigger
- DEV_NOTIFICATIONS.md path correction
- GP_CLOSED_LOOP_DESIGN.md operator count verify
- RISK_CONTROL_SERVICE_DESIGN.md L4 deprecate header

### §7.5 Phase E — Verify + Commit
- AI reviewer agents (code-reviewer + security-reviewer)
- pytest critical path
- ruff check
- Commit batch to feature/plan-v8-batch-cumulative-5-19-20 OR new branch
- PR #383 update OR new PR

### §7.6 Phase F — User Touchpoint Deferred
- 11 stale branches cleanup (require user approval)
- 3 OPEN PRs close (#303/304/305)
- PG rotation + 4 schtask register + 5-27 Wed live flip

---

## §8 Acceptance Criteria (Plan v9)

### §8.1 Doc-level (Phase C+D)
- [ ] §2.1 10 doc drift items closed (cite verify after update)
- [ ] §6 15 "超越设计" items sediment 到对应 DEV_*.md OR appendix
- [ ] §3.1 3 铁律 32 violations annotated OR refactored
- [ ] §3.2 P0 can_trade 实现 (信号能成交幻觉 closed)

### §8.2 Code-level
- [ ] backtest_12yr.yaml + backtest_5yr.yaml factor 与 pt_live.yaml 一致或显式 baseline 注释
- [ ] beat_schedule.py 2 stub decision (delete OR implement)
- [ ] data_orchestrator:256 + t0_19_audit:506 + dingtalk_alert:182 注释合规

### §8.3 System-level (Phase B-1 frozen — sustained)
- [ ] 5/5 红线 sustained (EXECUTION_MODE=paper / LIVE_TRADING_DISABLED=true / etc)
- [ ] 0 broker call / 0 .env mutation / 0 schtask register / 0 DB row mutation
- [ ] pytest --co stable 6251+ collected (post-fix sustained)
- [ ] ruff check 所有改动 PASS
- [ ] AI reviewer (code + security) verdict APPROVED

### §8.4 Closure %
- **Plan v8 baseline**: 97% (per PLAN_V8_FINAL_CLOSURE_STATUS_2026_05_20.md)
- **Plan v9 target**: 设计文档真实反映代码 ≥ 90% (从 50%) + 0 number drift in DEV_*.md
- **Cumulative**: Plan v8 + v9 ≥ 99% (剩 1% = Phase J multi-week + user touchpoint)

---

## §9 Risk Mitigation

1. **铁律 25**: 改文档前必读当前代码验证 — agent reports 已 cite file:line, 但 Phase C 修复每个 doc 改动必再 re-verify
2. **铁律 38 (Blueprint SSOT)**: DEV_*.md 更新必同步检查 QPB v1.16 / SYSTEM_BLUEPRINT.md cross-ref
3. **铁律 22**: 文档跟随代码 — 每改动 sediment LL candidate
4. **Phase B-1 frozen breach**: 0 .env mutation / 0 schtask register sustained
5. **PR flow**: 走 PR #383 (single PR cumulative) OR 新 PR (Phase C+D 分离)

---

**Maintained by**: CC autonomous (Plan v9 Phase B synthesis, 2026-05-20)
**Verified at**: 2026-05-20 ~03:30 SH (post 8 parallel audit agents)
**Cross-ref**:
- Plan v8 baseline: `docs/audit/PLAN_V8_FINAL_CLOSURE_STATUS_2026_05_20.md`
- Phase J defer: `docs/audit/PHASE_J_DEFER_MANIFEST_2026_05_20.md`
- Stale branches: `docs/audit/STALE_BRANCHES_AND_PRS_AUDIT_2026_05_20.md`
- 8 agent reports: 本会话 dispatch records
