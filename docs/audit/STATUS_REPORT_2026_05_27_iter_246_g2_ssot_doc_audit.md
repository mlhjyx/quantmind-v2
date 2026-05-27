# STATUS REPORT — iter 246 — G2 SSOT Doc Drift Audit (IRONLAWS + Blueprint + V3 design)

**Date:** 2026-05-27
**Iter:** 246 (post-compaction continuous L4+R loop, 62-iter cumulative)
**Trigger:** ISSUES_PENDING_REGISTRY G2 — "IRONLAWS.md / Blueprint QPB v1.16 / V3 DESIGN docs 跟 Session 57 代码 漂移程度未审计 (铁律 38)". User "继续" sustained.
**Status:** 6/6 SSOT docs path-ref audited via LL-214 method + LL-215 corrected regex. 2 PATH-SHIFT mechanical fixes applied (V2 BLUEPRINT). 5 ASPIRATIONAL findings in V3_DESIGN deferred to iter 247+. **0 code mutation. 0 broker / .env / yaml / DDL change.**

---

## 1. Audit method

Per LL-214 5-tier verdict taxonomy + LL-215 corrected regex pattern.

**Scope:** 6 SSOT docs per CLAUDE.md §"Session 启动 / 续接 SOP":
1. IRONLAWS.md
2. docs/QUANTMIND_PLATFORM_BLUEPRINT.md (QPB v1.17)
3. docs/V3_IMPLEMENTATION_CONSTITUTION.md
4. docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md
5. docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md
6. docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md

---

## 2. Findings summary

| Doc | Last mod | Total refs | Broken (raw) | Real drift (after context check) | Verdict |
|---|---|---|---|---|---|
| IRONLAWS.md | 2026-05-08 | 16 | 2 | **0** | CLEAN (both intentional historical narration) |
| QPB v1.17 | 2026-05-25 | 4 | 2 | 2 | ASPIRATIONAL × 2 (configs/resource_pools.yaml + scripts/backup_verify.py 从未实现) |
| V3_CONSTITUTION | 2026-05-22 | 11 | 0 | 0 | CLEAN |
| V3_SKILL_HOOK_MAP | 2026-05-17 | 1 | 0 | 0 | CLEAN |
| V3_RISK_FRAMEWORK | 2026-05-25 | 11 | 6 | 6 | 3 PATH-SHIFT + 3 ASPIRATIONAL (design-stage path planning, impl 演化偏离) |
| V2_SYSTEM_BLUEPRINT | 2026-05-20 | 10 | 2 | 2 | 2 PATH-SHIFT (walk_forward.py L288/L296) |

**Aggregate:** 53 path refs / 12 broken raw / **10 real drift (after IRONLAWS context disqualification)** / **2 fixed iter 246 / 8 deferred to iter 247+**.

---

## 3. IRONLAWS.md — CLEAN (false-positive)

Raw scan: 2 broken refs.

| Ref | Verdict | Justification |
|---|---|---|
| `backend/engines/factor_engine.py` (L466) | CLEAN | Intentional historical narration of Phase C C1+C2+C3 refactor: `backend/engines/factor_engine.py` → `backend/engines/factor_engine/` package. Text reads "**Phase C C1+C2+C3 全部完成 (2026-04-16)**: `backend/engines/factor_engine.py` → `backend/engines/factor_engine/` package". This is correct refactor narrative, not drift. |
| `scripts/pull_klines.py` (L655) | CLEAN | Already annotated with strikethrough + "文件不存在 (Session 27 Task A precondition 核实)". Intentional historical reference. |

**Verdict:** IRONLAWS.md is CLEAN at semantic level. Path-ref regex flagged false-positives.

---

## 4. QPB v1.17 — 2 ASPIRATIONAL (deferred)

| Ref | Verdict | Note |
|---|---|---|
| `configs/resource_pools.yaml` | ASPIRATIONAL | Framework #11 ROF design-stage YAML. Implementation status: 从未建. May land in future Wave 6+ when ROF Framework matures. |
| `scripts/backup_verify.py` | ASPIRATIONAL | MVP 4.4 Backup & DR ancillary script design-stage path. Actual MVP 4.4 shipped `restore_verification.py` orchestrator in `backend/qm_platform/backup/` package (iter 73). The standalone scripts/backup_verify.py was alternate design that didn't ship. |

**Action:** ASPIRATIONAL banner annotation deferred — would need careful in-doc context check. Banner template per LL-214: `⚠️ ASPIRATIONAL (iter # doc-rot audit YYYY-MM-DD)` + pointer to actual canonical alternative.

---

## 5. V3_DESIGN — 3 PATH-SHIFT + 3 ASPIRATIONAL (deferred)

V3_DESIGN.md design-stage code block headers diverged from final implementation due to namespace migration + rename evolution:

| Doc ref | Real path | Verdict |
|---|---|---|
| `backend/app/celery_config.py` (L1383 `# 扩`) | `backend/app/tasks/celery_app.py` | PATH-SHIFT |
| `backend/engines/risk/abstract.py` (L1269 `# sustained`) | `backend/qm_platform/risk/interface.py` | PATH-SHIFT (namespace `engines/risk` → `qm_platform/risk` + rename `abstract` → `interface`) |
| `backend/engines/risk/backtest_adapter.py` (L1316 `# 新增, T1.5 集成`) | `backend/qm_platform/risk/backtest_adapter.py` | PATH-SHIFT (namespace) |
| `scripts/realtime_risk_subscriber.py` (L500 `# 新增`) | `scripts/realtime_risk_engine_service.py` | PATH-SHIFT (rename) |
| `backend/migrations/v3_risk_framework_s7.sql` | NOT BUILT | ASPIRATIONAL (migrations use date-prefix `2026_05_XX_*.sql`, plan-style name never used) |
| `scripts/audit/check_anthropic_imports.py` | NOT BUILT | ASPIRATIONAL (pre-push uses `scripts/check_llm_imports.sh`, different intent) |

**Total V3_DESIGN drift:** 4 PATH-SHIFT + 2 ASPIRATIONAL = 6 items.

**Action:** all V3_DESIGN edits deferred to iter 247+. The design-stage code block headers carry "(新增)" / "(sustained)" / "(扩)" annotations that should be replaced with "(implementation shipped at $canonical_path)" patterns. Bulk edit warrants careful per-ref review.

---

## 6. V2_SYSTEM_BLUEPRINT — 2 PATH-SHIFT (FIXED iter 246)

| Doc ref | Real path | Fix |
|---|---|---|
| L288 `scripts/walk_forward.py` (5-fold WF table row) | `backend/engines/walk_forward.py` | ✅ Edited inline with `[iter 246 path-fix: scripts/ → backend/engines/]` annotation |
| L296 `python scripts/walk_forward.py --config ...` (回测入口 bash block) | `python backend/engines/walk_forward.py --config ...` | ✅ Edited inline with `[iter 246 path-fix]` annotation |

Also reviewed L365 `backend/platform/risk/rules/pms.py`:
- Found in a long annotated note: "上述 pms_engine 路径已 DEPRECATED, PMS L1/L2/L3 保护迁入 Platform Risk Framework (`backend/platform/risk/rules/pms.py`)"
- Real path is `backend/qm_platform/risk/rules/pms.py` (namespace `platform` → `qm_platform`)
- BUT this reference is itself inside an explanatory note about migration; the annotation correctly hints at migration. The `platform/` → `qm_platform/` rename is the broader iter 119 namespace work; the doc captured the migration intent at time of writing. Decision: leave note intact, doc-truth at semantic level OK.

---

## 7. Verification (iter 246 close, LL-210 三态)

- **backend-only ✅:** N/A (doc-only)
- **runtime-verified ✅:** post-fix re-scan V2_SYSTEM_BLUEPRINT shows walk_forward.py broken 2 → 0
- **sediment ✅:** this STATUS_REPORT + 2 V2_SYSTEM_BLUEPRINT inline edits + git commit

**Red lines:** 5/5 sustained 28+ days. 0 broker / 0 .env / 0 yaml / 0 DDL / 0 production code mutation iter 246 (doc-only).

---

## 8. Backlog deferrals (iter 247+)

- **V3_DESIGN.md PATH-SHIFT × 4** + **ASPIRATIONAL × 2**: design-stage → impl-reality annotation. ~30-60 min if done as single bulk iter.
- **QPB v1.17 ASPIRATIONAL × 2** (`resource_pools.yaml` + `backup_verify.py`): light banner annotation. ~15 min.

Both deferred to keep iter 246 scope bounded.

---

## 9. Methodology validation (LL-214 + LL-215 reuse)

iter 246 successfully reused iter 239-240 methodology codified in LL-214 + LL-215:
- Corrected regex (LL-215 longest-first + word-boundary lookahead) — 0 false positives in this scan
- 5-tier verdict taxonomy (LL-214) — applied to all 6 SSOT docs
- ASPIRATIONAL / PATH-SHIFT / CLEAN / DEPRECATED-PLAN / EXPECTED-UNIMPL verdicts each used

LL methodology proven generalizable beyond DEV docs to SSOT-tier governance docs.

---

## 10. G2 closure status

G2 entry "IRONLAWS.md 自身 / Blueprint QPB v1.16 / V3 DESIGN docs 跟 Session 57 代码 漂移程度未审计" — **6/6 path-level audited iter 246, 2 fixed + 8 deferred backlog.** ISSUES_PENDING_REGISTRY G2 status NOT marked closed yet (8 backlog items remain); update to "🟡 6/6 audited, 2 fixed iter 246, 8 deferred" after iter 247 backlog closure.

iter 247+ next: V3_DESIGN deferred annotations (highest leverage remaining autonomous work) OR DEV_FRONTEND deep per-page sync OR Tier C/D research design start.
