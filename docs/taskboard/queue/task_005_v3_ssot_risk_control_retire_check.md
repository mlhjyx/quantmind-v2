---
task_id: 005
priority: HIGH
domain: docs
tier: C
estimated_iter: 1
branch: docs/iter-XX-task005-v3-ssot-risk-control
created_by: main
created_at: 2026-05-25T17:25:00+08:00
assigned_to: sub2
depends_on: []
---

## Description

Audit `docs/RISK_CONTROL_SERVICE_DESIGN.md` (per CLAUDE.md cite "PARTIALLY DEPRECATED, 勿作当前设计") vs `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` (current SSOT).

Deliverable: write fresh audit row + retire recommendation.

## Acceptance

- grep `docs/RISK_CONTROL_SERVICE_DESIGN.md` 当前 status header
- compare V3 SSOT 覆盖范围 (V3 §4 L1 PMSRule / §7.3 trailing_stop / §6 DynamicThreshold etc) vs 老 RISK_CONTROL_SERVICE_DESIGN sections
- 输出: `docs/audit/V3_SSOT_RISK_CONTROL_RETIRE_2026_05_25.md` (新文件) 含:
  - 老 file 章节 inventory (sections × line counts)
  - V3 SSOT 已覆盖列 + 未覆盖列
  - 推荐: full retire OR add `> ARCHIVED — see V3 SSOT` redirect header
- TIER C direct push (sub2 沿用 PR auto-merge 体例)
- cite 4-element

## Cite source (4-element)

- CLAUDE.md (current) §文档查阅索引 "PARTIALLY DEPRECATED" cite (verify YYYY-MM-DD HH:MM SH)
- docs/RISK_CONTROL_SERVICE_DESIGN.md (verify YYYY-MM-DD HH:MM SH) — old design grep
- docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md §4 / §6 / §7.3 / §8 (verify YYYY-MM-DD HH:MM SH) — new SSOT

## Constraints

- 红线 5/5 sustained
- TIER C direct push (沿用 §v9.1)
- ≤100 lines new audit doc
