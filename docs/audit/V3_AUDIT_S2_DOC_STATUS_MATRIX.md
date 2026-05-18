# V3 Audit Section II Sub-doc — Doc Status Matrix (2026-05-18 evening)

> **Source**: Subagent B Part 1 (165 docs status enumeration)
> **Parent**: `V3_AUDIT_S2_INVENTORY.md` §6 Doc Inventory
> **Method**: Bash `ls D:/quantmind-v2/docs/` + categorized read + status tagging

---

## §1 Category Breakdown (Verified 2026-05-18 19:00 SH)

| Category | Total | ✅ | 🟡 | ⏸ | ⚪ | ❌ | 🕰 | Notes |
|---|---|---|---|---|---|---|---|---|
| `docs/DEV_*.md` (9) | 9 | 1 | 6 | 1 | 1 | 0 | 0 | Self-tagged status in headers (LL-049 enforcement) |
| `docs/mvp/MVP_*.md` (Wave 1-4) | 23 | 19 | 3 | 0 | 0 | 1 | 0 | Wave 1 ✅ + Wave 2 ✅ + Wave 3 5/5 ✅ + Wave 4 4.1 🟡 |
| `docs/adr/` (verified ls) | 67 | 63 | 4 | 0 | 0 | 2 | 0 | ADR-021 ironlaws / ADR-027/028/029 V3 决议 / ADR-076 横切层 closure |
| `docs/audit/` (verified ls) | 122 | n/a | n/a | n/a | n/a | n/a | n/a | 一次性诊断 + STATUS_REPORT chain, 状态语义不适用 |
| `docs/research-kb/` (verified) | 41 | n/a | n/a | n/a | n/a | n/a | n/a | 8 failed + 25 findings + 1 experiments + 5 decisions + 2 risk_findings (memory claim 38 略低,实测 41) |
| `docs/research/` | 14 | n/a | n/a | n/a | n/a | n/a | n/a | R1-R7 + G1/G2/G25 + Landscape 调研报告 |
| `docs/runbook/cc_automation/` | 15 | 15 | 0 | 0 | 0 | 0 | 0 | 全 active (00_INDEX 在用) |
| `docs/archive/` | 31+ | n/a | n/a | n/a | n/a | 31+ | n/a | DESIGN_V5 / ROADMAP_V3 等已归档 (CLAUDE.md §文档层级声明) |
| `docs/risk_reflections/` | 4+ | 4 | 0 | 0 | 0 | 0 | 0 | L5 Reflector output, W20 active |
| V3 docs (V3_*.md, RISK_FRAMEWORK_*) | 8 | 6 | 2 | 0 | 0 | 0 | 0 | V3 IC-3 closed 5-16 + V3 §20.1 10/10 ✅ |
| 根目录 SSOT (5) | 5 | 5 | 0 | 0 | 0 | 0 | 0 | CLAUDE.md / IRONLAWS.md / SYSTEM_STATUS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md |

**总计可分类 doc**: ~165 (含 archive 不计入 active 决策)

---

## §2 Notable Per-Category Findings

| Doc | Status | One-line finding |
|---|---|---|
| `DEV_BACKEND.md:1` (header) | 🟡 | self-tag `PARTIALLY_IMPLEMENTED ~60%`, header date 2026-04-10, drift未刷新但内容 valid |
| `DEV_FOREX.md:1-2` | ⏸ | self-tag `NOT_STARTED 0%`, A股未成熟前 deferred; Grep `forex_bars\|MT5\|ECMarkets` → 0 backend hits — heuristic #2 design Orphan |
| `DEV_AI_EVOLUTION.md:1-7` | 🟡 | V2.1 705 lines, AILoopOrchestrator partial: 5 agent files exist but 无 orchestrator state machine 主控 |
| `DEV_FRONTEND_UI.md:1-7` | 🟡 | self-tag `DESIGN_VALID_CODE_PARTIAL ~45%`; 设计 57 endpoints / 实际 96 endpoints (反向漂移 #1) |
| `DEV_PARAM_CONFIG.md:1-3` | ⚪ | self-tag `DESIGN_OVERSIZED ~25%`, D5 决议裁剪到 50 核心 — 设计 220 参数已废 |
| `DEV_SCHEDULER.md:1-5` | 🟡 | self-tag `~25%`, T1-T17 + FX1-FX11 设计大部分 deferred (FX 全 deferred) |
| `DEV_FACTOR_MINING.md:1-4` | 🟡 | self-tag `~55%`, Phase C 已重构 factor_engine.py→`engines/factor_engine/`, 但单文档未刷新 |
| `DEV_NOTIFICATIONS.md:1-5` | 🟡 | self-tag `~35%`, dispatcher partial: dingtalk_alert ✅ + email_alert ✅; 微信 ⏸ + WS `/ws/notifications` ⏸ |
| `DEV_BACKTEST_ENGINE.md:1-5` | ✅ | self-tag `MOSTLY_IMPLEMENTED ~70%`, Step 4-A 8 模块拆分 + Phase 1.1 性能 (841s→14.6s) ✅ |
| `GP_CLOSED_LOOP_DESIGN.md:1-5` | 🟡 | self-tag `PARTIAL ~40%`, 4 组件 (DSL / GP / Gate / SimBroker) 都有代码; 端到端自动闭环 ⏸ |
| `RISK_CONTROL_SERVICE_DESIGN.md` | 🟡 | 4 级熔断 partial; **L4 STAGED 在 V3 ADR-027 重定义 — heuristic #1 Drift P0** |
| `ML_WALKFORWARD_DESIGN.md` | ✅ | self-tag `~50%`, walk_forward.py 已修复. LightGBM 17 因子 WF=Sharpe 0.09 FAIL — ML 作为独立策略 NO-GO (research-kb sediment) |
| `QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md:6-9` | 🟡 | v1.0.1 cumulative annotation 2026-05-17; §20.1 10/10 ✅, Tier A/B/横切层 closed, Gate E partial |
| `V3_IMPLEMENTATION_CONSTITUTION.md` | ✅ | v0.13 2026-05-17, 6 件套 100% closure cumulative |
| `V3_PT_CUTOVER_PLAN_v0.1.md` | 🟡 | Plan v0.4 5-sprint chain IC-1~3 + CT-1 ✅; CT-2c-pre operational remediation 5-17; "LIVE-FIRE armed for Mon 2026-05-18 09:31 SH" — invalidated by LL-183 |
| `QUANTMIND_PLATFORM_BLUEPRINT.md:1-6` | ✅ | QPB v1.16, Wave 1+2 ✅ + Wave 3 ✅ 5/5 + Wave 4 4.1 🟡; 12 Framework + 6 升维 mapping |
| `QUANTMIND_V2_SYSTEM_BLUEPRINT.md` | ✅ | 791 行, 唯一设计真相源 |
| `V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md` | ✅ | v0.11 2026-05-17, 6 件套 invocation 索引 |
| `SETUP_DEV.md` | ✅ | 铁律 10b + MVP 1.1b 沉淀,环境 bootstrap |

---

## §3 Summary Recommendations (Per-Doc Disposition)

### §3.1 Implement Now (a) — 5 docs
- V3 Plan v0.4 CT-2 + Gate E formal close (LL-183 incident handling priority)
- Wave 4 4.1 batch 3.x 17 scripts SDK migration (in-flight)
- `RISK_CONTROL_SERVICE_DESIGN.md` ↔ ADR-027 reconciliation
- `DEV_FRONTEND_UI.md` Wave 5 Operator UI (ADR-012)
- `SETUP_DEV.md` / V3_INVOCATION_MAP / V3_CONSTITUTION — maintain only

### §3.2 Revisit Q3-Q4 (b) — 4 高价值未实施
- `DEV_AI_EVOLUTION.md` Layer 3-4 + Orchestrator (AI 闭环价值高)
- `GP_CLOSED_LOOP_DESIGN.md` end-to-end 自动闭环 + AlphaAgent prompt 改造
- `DEV_FACTOR_MINING.md` Engine 1+2+3+4 全栈
- `DEV_NOTIFICATIONS.md` 邮件/微信/WS 实施

### §3.3 Archive (c) — 4
- `DEV_FOREX.md` (Phase 2+ deferred, 0 backend code) — P1-37
- `DEV_BACKTEST_ENGINE.md` §一-§十 历史章节
- `DEV_PARAM_CONFIG.md` 220 参数原始章节
- `docs/audit/STATUS_REPORT_*` 时序 chunk archive

### §3.4 Merge / Deprecate (d/e) — 3
- `DEV_BACKEND.md` → merge into `SYSTEM_BLUEPRINT.md` (per CLAUDE.md SSOT 声明)
- `DEV_SCHEDULER.md` → merge with `SCHEDULING_LAYOUT.md`
- `ML_WALKFORWARD_DESIGN.md` ML-as-independent-strategy 章节 deprecate

### §3.5 Audit Chain Follow-up (P1)
- `docs/audit/` 122 files 缺统一索引 (除 AUDIT_MASTER_INDEX.md), 时序整理需要

---

## §4 Doc Count Drifts (Heuristic #1 / #14)

| Drift | Truth | CLAUDE.md says | Action |
|---|---|---|---|
| ADR count | 67 | "ADR-001~ADR-022" | Update CLAUDE.md or auto-generate ADR index |
| LL count | ~160 sections | "ll_unique_ids=94" | Standardize header pattern + count script |
| research-kb count | 41 entries | "38 entries" | Update CLAUDE.md to 41 |
| qm_platform frameworks | 15 actual dirs | "12 Framework + 6 升维" | Reconcile framework count |
| scripts count | 80 top-level | "80+" | OK matches |

---

**End Doc Status Matrix sub-doc.**
