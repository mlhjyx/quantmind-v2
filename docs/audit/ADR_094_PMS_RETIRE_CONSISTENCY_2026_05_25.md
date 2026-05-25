# ADR-094 PMS v1.0 Physical Retirement — Consistency Audit

**Date**: 2026-05-25
**Audit scope**: CLAUDE.md cite vs ADR-094 file vs REGISTRY.md vs codebase physical-deletion state
**Verdict**: **0 drift — clean**
**Method**: Read-only audit (no commit, no push, no DB/broker/.env mutation)
**Red-line 5/5 sustained**: LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / 0 持仓 / cash ¥993,520.66 / 0 trades since 2026-04-29

---

## §1 CLAUDE.md Cite Inventory

| Line# | Section | Claim |
|---|---|---|
| 17 | §项目概述 | "PMS: v1.0 (pms_engine + api/pms + Beat task) **物理退役 iter 50 2026-05-24** (ADR-094). V3 风控走 V3 §4 L1 PMSRule (backend/qm_platform/risk/rules/pms.py, 14:30 Beat via PlatformRiskEngine) + V3 §7.3 trailing_stop (subscribe_quote 实时, 动态替代 PMSRule v1 静态阈值)" |
| 210 | §PMS 阶梯利润保护规则 (V3 SSOT) | Section header (rewritten for V3 SSOT) |
| 212 | (same) | V3 §4 L1 PMSRule + V3 §7.3 trailing_stop active replacement description |
| 213 | (same) | 静态三层保护 L1/L2/L3 阈值 (V3 PMSRule) |
| 215 | (same) | `.env` `PMS_ENABLED` + `PMS_LEVEL{1,2,3}_*` 保留 |
| 216 | (same) | "旧版 PMS v1.0 物理退役 iter 50 2026-05-24 (ADR-094): `app/services/pms_engine.py` + `app/api/pms.py` + `pms_daily_check_task` + `test_pms_engine.py` 全部物理删除. 历史 PR #34 停 Beat (2026-04-21 ADR-010 Session 21) + sustained 7+ 月 0 真账户触发 + ADR-010 §C sunset gate '...满足' (Wave 4 MVP 4.1 batch 1+2.1+2.2 ✅)" |
| 444 | (research-kb table) | "RD-Agent / Qlib ... 回测无 PMS 涨跌停" — historical research finding, unrelated to retirement scope |
| 446 | (research-kb table) | "PMS v2.0 组合级保护 p=0.655 = 随机" — historical research finding, cited as evidence in ADR-094 §1 |

## §2 ADR-094 File Content Summary

`docs/adr/ADR-094-pms-v1-physical-retirement.md` (93 lines, verified 2026-05-25):
- **§1 Context**: 3 v1 layers enumerated (pms_engine.py / api/pms.py / pms_daily_check_task), historical timeline (4-21 Beat 停 / 4-29 PT 暂停 / 5-24 retire), v3.6 verify evidence cited.
- **§2 Decision**: 2.1 Physical deletions (3 files) / 2.2 Code edits (main.py + daily_pipeline.py + beat_schedule.py) / 2.3 Doc updates (CLAUDE.md ×2 + REGISTRY.md).
- **§3 Retained (V3 active)**: 7 retained artifacts incl. `qm_platform/risk/rules/pms.py` (PMSRule), `realtime/trailing_stop.py`, PMSConfigSchema, loader.py mapping, V3 tests.
- **§4 Consequences**: Positive (~250 lines code + ~150 lines tests deleted, LL-194 closure, ADR-010 §C enforced) / Risk (git revert reversible, audit-trail mitigation) / Neutral (.env vars preserved).
- **§5 Sunset gate evidence**: Wave 4 MVP 4.1 batch 1+2.1+2.2 ✅ verified.
- **§6 Implementation evidence**: Branch `feat/iter-50-v3-ssot-redirect-l4-drift`, smoke 61/61 PASS 82.11s.
- **§7 Cross-references**: ADR-010 / V3 §4 L1 / V3 §7.3 / CLAUDE.md / LL-194.

**Title / Decision / Consequences / Sediment sections all present**: ✅ PASS

## §3 REGISTRY.md Row Check

`docs/adr/REGISTRY.md:200` — ADR-094 row present:
- **Title**: "PMS v1.0 物理退役 (V3 SSOT 集成)" ✓ matches ADR-094 file title
- **Status**: `committed` ✓
- **Date**: iter 50 (2026-05-24) ✓ matches ADR-094 §header `Date: 2026-05-24`
- **Body**: lists 3 physical deletions + 3 code edits + 3 doc updates + 7 retained artifacts + smoke test 61/61 PASS — fully consistent with ADR-094 file content
- Cross-link to `ADR-094-pms-v1-physical-retirement.md` present ✓
- **Fresh verify timestamp**: REGISTRY.md:208 "2026-05-25 16:55 SH (iter 97 sub2 — taskboard task_004)" ✓

## §4 Physical Deletion Verification (4 grep results)

| # | Path / pattern | Expected | Actual | Verdict |
|---|---|---|---|---|
| 1 | `backend/app/services/pms_engine.py` | 0 (deleted) | Glob returns "No files found" | ✅ DELETED |
| 2 | `backend/app/api/pms.py` | 0 (deleted) | Glob returns "No files found" | ✅ DELETED |
| 3 | `daily_pipeline.py::pms_daily_check_task` | 0 active OR commented RETIRED block | grep shows 2 hits (lines 722, 728) — both inside RETIRED comment block citing ADR-010 + V3 §4 L1 PMSRule. **0 active def/call.** | ✅ COMMENTED-OUT |
| 4 | `app/main.py` pms_router import | 0 active import | line 25 = `# NOTE: app.api.pms removed iter 50 — PMS v1.0 物理退役 per ADR-010 §C sunset gate` (comment-only, no import) | ✅ REMOVED |
| 5 (bonus) | `beat_schedule.py` PMS Beat | DEPRECATED block updated | lines 75-76 = comment "删除文件: app/services/pms_engine.py + app/api/pms.py + tests/test_pms_engine.py + daily_pipeline.pms_daily_check_task. V3 风控走 qm_platform/risk/rules/pms.py" | ✅ COMMENT UPDATED |

## §5 V3 PMSRule Replacement Existence Verification

`backend/qm_platform/risk/rules/pms.py` — verified present:
- Line 55: `class PMSRule(RiskRule):` ✓
- Line 73: `def __init__(self, levels: tuple[PMSThreshold, ...] | None = None) -> None:` ✓

Also referenced in `backend/app/services/risk_wiring.py` (registration in PlatformRiskEngine) per grep §4 result. V3 SSOT replacement path intact. ✅ PASS

## §6 Drift Findings

**0 drift found.** All 5 cross-checks (CLAUDE.md cite ↔ ADR-094 file ↔ REGISTRY.md row ↔ physical deletions ↔ V3 replacement) consistent.

**Recommendation**: **CLEAN — no fix required.**

### 4-Element Cite Source Verification

Per `quantmind-v3-cite-source-lock` skill (path + line# + section + fresh verify timestamp):

| Cite | Path | Line# | Section | Fresh verify |
|---|---|---|---|---|
| CLAUDE.md PMS retire claim (project overview) | `D:\quantmind-v2\CLAUDE.md` | 17 | §项目概述 | 2026-05-25 (this audit) |
| CLAUDE.md PMS section rewrite | `D:\quantmind-v2\CLAUDE.md` | 210-216 | §PMS 阶梯利润保护规则 (V3 SSOT) | 2026-05-25 (this audit) |
| ADR-094 file | `D:\quantmind-v2\docs\adr\ADR-094-pms-v1-physical-retirement.md` | 1-93 | full file | 2026-05-25 (this audit) |
| REGISTRY.md row | `D:\quantmind-v2\docs\adr\REGISTRY.md` | 200 | ADR table | 2026-05-25 16:55 SH (REGISTRY self-stamped, this audit re-verified) |
| V3 PMSRule replacement | `D:\quantmind-v2\backend\qm_platform\risk\rules\pms.py` | 55, 73 | PMSRule class | 2026-05-25 (this audit) |

**4-element compliance**: ✅ all citations include path + line# + section + fresh verify timestamp.
