---
task_id: 007
priority: MID
domain: docs
tier: C
estimated_iter: 1
branch: docs/iter-XX-task007-dev-ai-v3-drift
created_by: main
created_at: 2026-05-25T17:26:00+08:00
assigned_to: sub2
depends_on: []
---

## Description

Drift scan: `docs/DEV_AI_EVOLUTION.md` (V2.1 cite per CLAUDE.md, 650 lines, Layer 1 ~95% / Layer 2 ~60% / Layer 3-4 0%) vs `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` §S5-§S8 (RAG memory + Bull-Bear + sentiment + RiskReflector已实施).

V3 §S5-§S8 PR #343-346 merged 沿用 CLAUDE.md cite — V2.1 design doc 应同步引用 OR 标记 SUPERSEDED.

## Acceptance

- grep DEV_AI_EVOLUTION.md §V3 reference (currently 0 expected)
- list V3 §S5-§S8 实施 sections + verify aligned with V2.1 Layer 2 (~60%) claim
- 输出: `docs/audit/DEV_AI_V21_V3_DRIFT_2026_05_25.md` (新文件) 含:
  - V2.1 file sections inventory
  - V3 §S5-§S8 实施 mapping
  - Drift table (V2.1 says X, V3 says Y, 真值 Z)
  - 推荐: DEV_AI_EVOLUTION.md 加 §0 redirect to V3 §S5-§S8 OR 直 retire
- TIER C direct push
- cite 4-element

## Cite source (4-element)

- CLAUDE.md §文档查阅索引 "AI闭环/因子发现" cite "V3 §S5/S6/S7/S8 ✅ merged main (PR #343-346)" (verify YYYY-MM-DD HH:MM SH)
- docs/DEV_AI_EVOLUTION.md §1 Layer 1-4 overview (verify YYYY-MM-DD HH:MM SH)
- docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md §S5 / §S6 / §S7 / §S8 (verify YYYY-MM-DD HH:MM SH)
- PR #343-346 verify (gh pr view N --json mergeCommit)

## Constraints

- 红线 5/5 sustained
- TIER C direct push
- ≤100 lines new audit doc
