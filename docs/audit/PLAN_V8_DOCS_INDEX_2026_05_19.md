# Plan v8 Comprehensive Docs Index (2026-05-19)

> **目的**: 一处导航全部 Plan v8 + Phase G/H/I 实施 docs (21 audit/status_report + 1 LL entry + 1 memory handoff + 3 HTML mockups + 2 backend scripts). 章节级 breakdown 让任何 future session 30s 内 locate 所需内容.
> **HEAD**: a317292 (post 11-commit cumulative)
> **总 lines**: 6069 (audit docs) + 103 (LL-187) + ~2827 chars (memory handoff Session 57)

---

## §1 顶层导航 (按主题分组)

| 主题 | 主 doc | 子 docs | 总 lines |
|---|---|---|---|
| 战略/总览 | V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER | S6 Strategic + Phase J/K Decision + Docs Index (本文件) | ~1100 |
| Inventory | V3_AUDIT_S2_INVENTORY | DOC_STATUS_MATRIX + DESIGN_VS_REALITY_GAP | ~520 |
| Flow/Closure | V3_AUDIT_S3_FLOW_AND_CLOSURE | S4 HEALTH_AND_DEAD_CODE | ~590 |
| Domain | V3_AUDIT_S1_DOMAIN | — | ~100 |
| ML/Cost/HW | V3_AUDIT_S7_ML_COST_HARDWARE | S7_SUPPLEMENT (DB-verified) | ~630 |
| Frontend (v1→v3) | V3_AUDIT_FRONTEND_DESIGN_v3 | S5 PROPOSAL + REVISED_v2 + SPEC + 3 HTML mockups | ~1990 |
| UX Control Plane | V3_AUDIT_S9_UX_CONTROL_PLANE | — | ~175 |
| Phase H+I 实施 sediment | STATUS_REPORT_2026_05_19_frontend_v3_phase_h_w1_w6 | — | ~225 |
| 历史 STATUS_REPORTs (5-17/5-18) | 3 reports | — | ~795 |
| LL sediment | LESSONS_LEARNED §LL-187 | + LL-184/185/186 (earlier) | ~103 |

---

## §2 战略/总览类

### §2.1 `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md` (685 lines)

**主 audit 总文件 — Top 50 findings + Strategic Alternatives chapter**.

**章节**:
- §1 Executive Summary — 24 P0 + 26 P1 ranked findings 概要
- §2 Top 50 Findings ranked
  - P0 (24 findings): EnvBanner / L4 UI / 双轨样式 / hardcoded LOW / ...
  - P1 (26 findings): AssistPanel / axios bypass / dead code / hardcoded badge / ...
  - 每个 finding: severity / heuristic tag (#1-#20) / effort / 2-3 alternative remediation
- §3 Cross-Layer Dependency Map (12 examples)
- §4 Strategic Alternatives Chapter (Phase 3-bis output) — 5 "if we redesign from scratch" architectures (A monolith+harden / B 3-service split / C event-sourcing / D rewrite QMT pool / E LLM-driven control plane)
- §5 Audit Self-Audit + Cadence (Heuristic #17)
- §6 LL-184/185/186 sediment candidates
- §7 Memory handoff prep

### §2.2 `V3_AUDIT_S6_STRATEGIC_AND_CONTINUITY.md` (150 lines)

**Section VI — 战略 + 知识传承**.

**章节**:
- §25 Strategic Risks (single point of failure)
- §26 Roadmap Alignment (Wave 4 batch 3.x / Wave 5/6 / V3 §19)
- §27 Future-Proofing (10x scale / strategy diversify / asset class expand)
- §28 知识传承 (CC restart onboard / memory file index)
- §29 Reproducibility (backtest / factor / IC / live trade replay)
- §30 Process Maturity Assessment (CMMI-like)

### §2.3 `PHASE_J_K_REMAINING_DECISION_DOC_2026_05_19.md` ⭐ NEW (209 lines)

**Plan v8 doc-level 100% closure — Phase J + K + 5 deferred findings 决议**.

**章节**:
- §1 Phase J Strategy Diversification (0% → DOC-CLOSED)
  - §1.1 Background (audit §2 + §16)
  - §1.2 Decision Tree (PT-restart prerequisite)
  - §1.3 5 research directions (J.1 Sharpe Confidence / J.2 失败方向 re-eval / J.3 Backup strategy / J.4 OOS hetero / J.5 Multi-strategy portfolio)
  - §1.4 Recommended sequencing
- §2 Phase K Live-Fire Resume (0% → DOC-CLOSED)
  - §2.1 Background (SHUTDOWN_NOTICE §9)
  - §2.2 10-item prerequisite checklist (K.1-K.10)
  - §2.3 Conditional path decision tree
  - §2.4 Status (4/10 closed)
- §3 Phase H/I 5 remaining findings 决议:
  - §3.1 #3 双轨样式 — DEFERRED (Phase I-future, 50h)
  - §3.2 #7 cron hardcoded — DEFERRED (Section X §39 dep, 9h)
  - §3.3 #12 PMS归并 — CLOSED (保持独立)
  - §3.4 #14 三套 real-time — Phase I option A/B/C
  - §3.5 admin_token httpOnly cookie — needs backend (6h)
  - §3.6 socket.io evaluation — verified backend HAS, retain
- §4 Cumulative Status + 14 user 决议触发点

---

## §3 Inventory 类 (S2 trio)

### §3.1 `V3_AUDIT_S2_INVENTORY.md` (304 lines)

**章节**:
- §3 代码 Inventory (backend/app 295 files / engines 45 / qm_platform 15 / scripts 80+ / frontend 14500 LOC)
- §4 API/Interface Inventory (121 FastAPI endpoints + 11 Celery + 15+ Beat + 5 Schtask + Redis streams + PG locks + 外部契约)
- §5 Data Inventory (PG 74+ tables / TimescaleDB hypertable / Parquet cache / Redis cardinality)
- §7 配置 + 红线 Inventory (.env 37+ fields / config.py / 5/5 红线 + V3 阈值 SSOT / Hardcoded values audit)

### §3.2 `V3_AUDIT_S2_DOC_STATUS_MATRIX.md` (98 lines)

**150+ docs status matrix**.

**章节**:
- DEV_*.md ×9 (DEV_BACKEND / DEV_AI_EVOLUTION / DEV_FOREX 等)
- Blueprint (QPB v1.16 / SYSTEM_BLUEPRINT 791行)
- docs/mvp/*.md (MVP 1.1 ~ MVP 4.1)
- docs/adr/*.md (130+ ADR)
- 每个 doc 标 disposition: ✅IMPLEMENTED / 🟡IN-PROGRESS / ⏸NOT-STARTED / ⚪NOT-APPLICABLE / ❌DEPRECATED / 🕰STALE

### §3.3 `V3_AUDIT_S2_DESIGN_VS_REALITY_GAP.md` (120 lines)

**Design vs Implementation Gap Analysis — heuristic #20 reverse mapping**.

**章节**:
- 20 重点 design 文档 (DEV_AI_EVOLUTION 705 / DEV_FOREX 682 / GP_CLOSED_LOOP / RISK_CONTROL_SERVICE / ML_WALKFORWARD 1096 / V3_DESIGN / QPB v1.16 / SYSTEM_BLUEPRINT 791 / MVP docs / ADR 130+)
- 每个 doc: IMPLEMENTED % + valuable-but-未实施 list + recommendation (implement now / revisit Q3-Q4 / archive / merge / deprecate)
- Bidirectional traceability sample (5-10 code module ↔ design doc)

---

## §4 Flow / Closure / Health 类

### §4.1 `V3_AUDIT_S3_FLOW_AND_CLOSURE.md` (303 lines)

**章节**:
- §8 6 Business Flow text-diagram each:
  - 数据流: Tushare → DataPipeline → PG/Parquet → Factor engine
  - 信号流: signal_phase 16:30 → factor → IC weight → SignalComposer → signals table
  - 交易流: execute_phase 09:31 → CB → adapter → broker → trade_log
  - 风控流: tick → RealtimeRiskEngine → 10 rules → AlertDispatcher → L4 STAGED
  - 因子研究流: proposal → IC → profile → Gate → backtest → onboard
  - 对账+报表流: 15:40 reconciliation → 17:35 audit + summary → DingTalk push
- §9 Service Interaction Graph (Redis ↔ PG ↔ Celery ↔ Servy ↔ xtquant)
- §10 闭环 (Closed-Loop) Verification
- §11 Failure Cascade Map (single point of failure inventory)
- §12 工作流完整性 (新因子 onboarding / 新 strategy / Bug fix / Daily/Weekly ops)

### §4.2 `V3_AUDIT_S4_HEALTH_AND_DEAD_CODE.md` (286 lines)

**章节**:
- §13 代码健康 (ruff/mypy/pytest baseline 真值 + 铁律合规)
- §14 死代码 / 未用 inventory (NotificationSystem 281 / DashboardForex 39 / TradeExecution / 等)
- §15 连接性 audit (backend → API → frontend gap)
- §16 运维 + Observability (5 Servy services / Log / Metrics / SLI/SLO)
- §17 Security / Compliance (.env secrets / DB perm / API auth / 双锁)
- §18 数据健康 (freshness / Integrity / Backup)
- §19 性能 + 资源 (RAM/GPU/disk/network)
- §20 治理 / Audit (LL count / ADR registry / Memory hooks / Sprint state)

---

## §5 Domain 类

### §5.1 `V3_AUDIT_S1_DOMAIN.md` (100 lines)

**章节**:
- §1 业务领域深度理解 (A股 T+1 / 涨跌停 / 集合竞价 / 中国市场 quirks)
- §2 Strategy Edge / 投研哲学审视 (alpha 来源真分析 / single-bet risk / failed direction re-eval / OOS robustness / capacity)

---

## §6 ML/Cost/Hardware 类

### §6.1 `V3_AUDIT_S7_ML_COST_HARDWARE.md` (279 lines)

**Section IX + Section X — ML/AI Closed Loop + Hardware/Cost/Capacity**.

**章节**:
- §31 LiteLLM Router Cost Per Decision Granularity
- §32 V4-Flash vs V4-Pro Routing Strategy 真值
- §33 LLM Prompt Versioning + Iteration History
- §34 RAG Memory Population Strategy
- §35 V4 → V5 Migration Readiness
- §36 Strategy Capacity Analysis (¥1M → ¥10M → ¥100M)
- §37 Survivorship Bias Audit
- §38 Slippage Model 季度复核
- §39 Beat/Schtask Calendar SSOT
- §40 Daily Critical Path Analysis

### §6.2 `V3_AUDIT_S7_ML_COST_HARDWARE_SUPPLEMENT.md` (350 lines)

**Subagent I resume DB-verified — 3 P0 NEW escalations**.

**章节**:
- F-S7-001 P0: LLM cost_usd=0 across 570 calls / 12d / 877K tokens (BudgetGuard silently defanged)
  - Root cause: LiteLLM model_cost.json 不含 DeepSeek
  - Fix path: 3 alternatives (LiteLLM yaml / inline fallback / post-call UPDATE) — chosen #2
  - **State: CLOSED 23ebea5** (this session)
- F-S7-005 P0: RAG memory 1 row total (ADR-068 closure theatrical)
  - **State: backfill script ready a317292** (this session, 留 user execute)
- F-S7-008 P1: VACUUM ANALYZE never ran (pg_stat unreliable)
  - **State: script ready b560a0c** (留 user schtask 注册)
- + 12 dead tables inventory
- Recovery sequencing (5 items priority)
- #18 alternatives 5 项 finding

---

## §7 Frontend 设计类 (v1 → v3 演进)

### §7.1 `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` v1 (219 lines)

**初代设计 — 后被 v2/v3 替代**.

**章节**:
- §21 当前前端诊断 (last commit date / stack / 35 pages / broken/stale)
- §22 Backend Feature Surface for Frontend
- §23 新前端设计 Proposal (Personas / IA / Page-by-page / Tech stack / Real-time / Auth)
- §24 Frontend 重写 Roadmap (Phase 1-5)

### §7.2 `V3_AUDIT_FRONTEND_DESIGN_PROPOSAL.md` (344 lines, designer agent)

**3 mockup variant rationale**:
- Variant A safety-first (max guardrail, conservative)
- Variant B trader-velocity (real-time + fast ops + minimal confirm friction)
- Variant C AI-assisted (LLM-driven natural language ops)
- 3 HTML mockups (frontend_mockups/{A,B,C}.html)

### §7.3 `V3_AUDIT_FRONTEND_DESIGN_SPEC.md` (815 lines) ⭐ 完整 design spec

**章节** (8 part design system):
1. Design Tokens (color / typography / spacing)
2. Component library (Button / Modal / Form / Chart / Table 全 spec)
3. Page-by-page layout (~11 pages, wireframe in text)
4. User flow (trader/researcher/auditor 3 journey)
5. Interactive Spec (CC ops → frontend button + confirmation + RBAC + audit trail)
6. Real-time strategy (WebSocket / SSE / polling per data type)
7. API endpoint binding (existing /api/* vs 新需要)
8. Accessibility / responsive / mobile

### §7.4 `V3_AUDIT_FRONTEND_DESIGN_REVISED_v2.md` (205 lines) — user feedback canonical direction

**User 5-19 feedback**: 业务向 (NOT audit/ADR/LL 元数据) + 渐进 refactor of existing 35 pages + AI 助手 panel 集成 from C variant.

**章节**:
- §1 existing 35 pages 业务功能 inventory + P0-P3 改造优先级
- §2 AI 辅助 panel integration plan (9 business scenarios)
- §3 Phase H REVISED 4-6 weeks roadmap

### §7.5 `V3_AUDIT_FRONTEND_DESIGN_v3.md` (409 lines) ⭐ canonical implementation guide

**取代 v1/v2, 真实施 plan**.

**章节**:
- §1 Deep Audit Summary (14500 LOC / Top 3 P0 / Top 3 tech debt / 黄金模板 Execution/index.tsx)
- §2 5 NEW Components Spec:
  - EnvStateBanner (~80 lines, Layout 顶部固定)
  - SafetyControlPanel (~250 lines, L4 ladder + force-reset HIGH)
  - AssistPanel (~300 lines, 3 modes + 4 entry points)
  - ConfirmModal (~150 lines, 4 safety tiers LOW/MED/HIGH/CRIT)
  - ShutdownBanner (~60 lines, 3 条件 conditional)
- §3 Page-by-page refactor plan (10 高频页 P0 W1 / P1 W2-3 / P2 W4-5 / P3 W6)
- §4 Migration strategy (双轨/4通知/2axios/real-time tiered)
- §5 Phase H Roadmap 6-week × 30h/week = ~154h breakdown
- §6 Top 15 findings → action mapping
- §7 15 NEW backend endpoints required

---

## §8 UX Control Plane 类

### §8.1 `V3_AUDIT_S9_UX_CONTROL_PLANE.md` (173 lines)

**Section XI Backend Op → Frontend Action Coverage Matrix**.

**章节**:
- §41 Backend Operation Inventory → Frontend Action Coverage Matrix (32 ops enumerate, 14/32 have UI)
- §42 Trader Daily Journey Map (开盘前 / 盘中 / 收盘后)
- §43 Researcher / Auditor Journey Map (因子 onboarding / Incident response)
- §44 Control Plane Safety UX (HIGH/CRIT ops confirmation flow)
- §45 AI-Assisted Frontend Operations (LLM-driven natural language ops + smart suggestion)

---

## §9 STATUS_REPORTs (4 历史)

### §9.1 `STATUS_REPORT_2026_05_17_phase1_system_fix.md` (379 lines, earlier)

**章节**: Phase 1 system fixes / Servy restart / 红线 verify cycle.

### §9.2 `STATUS_REPORT_2026_05_18_evening_cumulative.md` (249 lines, 7b57018)

**章节**: Mon 5-18 evening cumulative 4 commits (4f337cc + 481ebcd + 355b813 + 7b57018) — LL-182 QMT 5-axis + LL-183 dry-run fix + Phase B regression gate.

### §9.3 `STATUS_REPORT_2026_05_18_evening_audit_closure.md` (166 lines)

**章节**: V3 Full Project Deep Audit Plan v8 closure + Phase G+ roadmap.

### §9.4 `STATUS_REPORT_2026_05_19_frontend_v3_phase_h_w1_w6.md` ⭐ NEW (226 lines this session)

**章节**:
- §1 Commits chain (5 commits initially, 后 §9 扩展 8 commits)
- §2 v3 Top 15 findings 闭环 mapping (10/15 closed + 5/15 deferred reason)
- §3 Week 3 folded + Week 5 deferred + Phase I roadmap
- §4 设计原则 sustained throughout commits
- §5 Build/test sanity 4 commits 全过
- §6 红线 5/5 sustained
- §7 LL-187 candidate prep
- §8 W5 outstanding user decision points
- **§9 Session Continuation (commits 7+8 sediment, F-S7-001 + axios SSOT)**
  - §9.1 F-S7-001 P0 真闭环
  - §9.2 axios SSOT 全 migration
  - §9.3 Cumulative session totals
  - §9.4 Plan v8 completion matrix (final)

---

## §10 LL Sediment + Memory Handoff

### §10.1 `LESSONS_LEARNED.md §LL-187` ⭐ NEW (~103 lines, 9046faf)

**章节**:
- Trigger ("依次进行" + "需思考全面")
- Session scope (9-commit autonomous closure)
- Phase H Frontend Redesign (5 NEW components + 10/15 v3 findings closed)
- Phase G F-S7-001 P0 闭环 (3-path strategy + 6 regression tests + 31/31 router PASS)
- Phase G F-S7-008 P0 (VACUUM script + schtask 留 user)
- Phase I Tech Debt (axios SSOT + dead code, ~50% closed)
- Cumulative session totals
- Plan v8 final completion
- Sustained design principles (9 commits)
- 红线 5/5 sustained
- 留 user 决议触发 8 items
- 铁律 backref / Heuristic backref

### §10.2 `memory/project_sprint_state.md` 顶部 Session 57 handoff (~2827 chars)

**章节**:
- 6 commits table this session
- Cumulative diff
- Findings closed cumulative
- Design principles sustained
- Build/Test sanity
- Deferred 留 user 触发
- 红线 5/5 sustained
- Next session entry points (5 items)

---

## §11 Phase H+G+I Backend Scripts ⭐ NEW (this session)

### §11.1 `scripts/db_vacuum_analyze.py` (b560a0c, 190 lines)

**章节** (docstring):
- 背景 (F-S7-008 P0 — pg_stat NULL)
- 设计目标 (VACUUM ANALYZE 10 重型表 + 不锁表 + 单表串行)
- 调度 (推荐 schtask 周日 03:00 SH)
- 手动执行 + 单表执行
- 关联 (audit + LL-186)

**函数**:
- `get_table_size(conn, table)` — 表 + 索引总大小
- `get_table_stats(conn, table)` — pg_stat_user_tables 关键指标
- `vacuum_analyze_table(conn, table, log)` — 单表 VACUUM ANALYZE + size before/after
- `main()` — CLI entry (--tables / --dsn)

**HEAVY_TABLES**: factor_values 840M / minute_bars 190M / klines_daily 11.8M / daily_basic 11.7M / factor_ic_history / position_snapshot / trade_log / stock_valuation / moneyflow / stream_outbox

### §11.2 `scripts/rag_memory_backfill.py` (a317292, 240 lines) ⭐ NEW

**章节** (docstring):
- 背景 (F-S7-005 P0 — 1 row theatrical)
- 设计目标 (从 risk_event_log + trade_log 历史 backfill + embedding=NULL 留 BGE-M3)
- 数据源 (3 sources)
- 调度 (一次性 backfill, 之后 V3 L1 实时 INSERT)
- 后续步骤 (embedding cron, 留 user GPU 决议)

**函数**:
- `fetch_risk_events(conn, limit, log)` — 历史 risk_event_log 读取
- `fetch_trade_emergency(conn, limit, log)` — 4-29 清仓 events
- `check_existing(conn, event_type, event_timestamp)` — 幂等检查
- `insert_risk_memory(...)` — INSERT (embedding=NULL)
- `map_risk_event_to_memory(event)` — risk_event → memory payload
- `map_trade_emergency_to_memory(event)` — trade emergency → memory payload
- `main()` — CLI (--dry-run / --limit 500 / --dsn)

---

## §12 总览矩阵 (按 read-order 顺序)

**新进 user / future session 30min 内全 grasp 推荐 read order**:

1. **本文件** (PLAN_V8_DOCS_INDEX_2026_05_19.md) — 全 doc 导航 (5 min)
2. `STATUS_REPORT_2026_05_19_frontend_v3_phase_h_w1_w6.md` ⭐ — 11-commit session sediment (10 min)
3. `PHASE_J_K_REMAINING_DECISION_DOC_2026_05_19.md` ⭐ — 14 user 决议触发 + Phase J/K 入口 (5 min)
4. `LESSONS_LEARNED.md §LL-187` — LL closure (5 min)
5. `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md` — Top 50 findings full context (深读, 30 min)
6. `V3_AUDIT_FRONTEND_DESIGN_v3.md` ⭐ — Frontend implementation guide (10 min)
7. `V3_AUDIT_S7_ML_COST_HARDWARE_SUPPLEMENT.md` — P0 escalation context (10 min)
8. 其它 audit S1/S2/S3/S4/S6/S9 — 按需查阅

---

## §13 Quick Reference — 关键链接

| 问题 | 看哪 doc + § |
|---|---|
| Plan v8 11-commit 全总览 | STATUS_REPORT_2026_05_19 §1 + §9 |
| 14 user 决议触发点 | PHASE_J_K_DECISION_DOC §4.2 |
| Frontend Design v3 5 NEW components | DESIGN_v3 §2 + §3 |
| Frontend 10/15 findings closed | DESIGN_v3 §6 + STATUS_REPORT v2 §3 |
| AI Boundary CRIT ops list | components/ai/AssistPanel.tsx docstring OR agent.py /chat/status |
| LL-183 silent NOT-GATING 教训 | LESSONS_LEARNED §LL-183 |
| F-S7-001 fix 3-path strategy | SUPPLEMENT F-S7-001 entry OR LL-187 §Phase G |
| VACUUM ANALYZE 10 重型表 | scripts/db_vacuum_analyze.py HEAVY_TABLES |
| Phase K live-fire 10-item checklist | PHASE_J_K_DECISION_DOC §2.2 |
| Phase J 5 research directions ranked | PHASE_J_K_DECISION_DOC §1.3 |
| 双轨样式 migration 决议 | PHASE_J_K_DECISION_DOC §3.1 |
| socket.io retain rationale | PHASE_J_K_DECISION_DOC §3.6 |
| admin_token httpOnly fix path | PHASE_J_K_DECISION_DOC §3.5 |

---

**End docs index.** 6000+ lines audit + status_report docs + 343 lines this-session NEW (decision doc + scripts + index). All structured for 30-second 章节 lookup.
