---
description: Codex remediation handoff restored and updated after first repair batch.
date: 2026-05-28 00:25 +08:00
status: remediation_batch_1_closed
source_report: docs/audit/FULL_PROJECT_CLOSURE_AND_GOVERNANCE_AUDIT_2026_05_27.md
---

# Project Sprint State

## Current Handoff — 2026-05-28

Mode: remediation batch after full project closure and governance audit.

Current scope:
- Preserve the staged Codex governance package as the working baseline.
- Do not commit, unstage, or revert unrelated staged changes.
- First repair batch completed for pipeline settings, runtime route refresh, system health, import-root setup, and attribution evidence.
- User authorized related remediation operations on 2026-05-28.
- Still avoid broker calls, `.env` edits, Servy config edits, Task Scheduler changes, and production YAML changes unless the action is specifically required.

Fresh-read / grounding status:
- `AGENTS.md`, `IRONLAWS.md`, `LESSONS_LEARNED.md`, `SYSTEM_STATUS.md`, `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`, `docs/V3_IMPLEMENTATION_CONSTITUTION.md`, `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md`, `docs/adr/REGISTRY.md`, and `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` were read on 2026-05-27.
- The previous handoff path was missing: `memory/project_sprint_state.md` and the parent `memory/` directory did not exist in the repo checkout.
- Redline read-only account verification was attempted with `python scripts/_verify_account_oneshot.py`; it stopped at miniQMT connect return code `-1`, so full account-state verification is not complete in this shell.

Closed in this batch:
- Applied `backend/migrations/pipeline_settings.sql`; `/api/pipeline/status` now returns 200.
- Restarted FastAPI, Celery Worker, and Celery Beat; `/api/system/beat-schedule` now returns 27 entries.
- Fixed `/api/system/health`: bounded checks, sequential datasource reads, and Windows Celery solo-worker process fallback; runtime returns `overall_status=ok`.
- Fixed attribution task import roots and strategy id source; manual task apply wrote `daily_attribution.id=2`; `/api/attribution/latest` returns that row.
- Removed the manual-test attribution noise row for the old placeholder strategy.

Still open:
- Scheduler failures: `QM-ICMonitor` and `QM-SmokeTest` need disposition.
- Active `.agents/skills` files need a track/local-only policy.
- QMT Data Service remains stopped by design; do not start it without an explicit PT/QMT ops reason.

Next safe step:
- Finish verification, stage a coherent branch, and open a PR because GitHub auth is now available.
- Keep `.agents/skills/...` and `nul` untracked unless the PR scope explicitly includes skill governance.
