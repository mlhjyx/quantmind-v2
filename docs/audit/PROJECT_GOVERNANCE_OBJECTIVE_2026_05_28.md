# QuantMind V2 Project Governance Objective — 2026-05-28

## Objective

QuantMind V2 needs continuous, full-project, evidence-driven closure and governance.
The scope is not a single bugfix or one audit report. The target state is a repository
where code, runtime behavior, documentation, hooks, skills, CI, and GitHub PR state
can be inspected together and tell the same story.

## Coverage

The governance loop covers:

- Backend APIs, services, engines, repositories, Celery Beat tasks, StreamBus, DB
  migrations, Redis/Postgres/QMT integration, backup and CI platform modules.
- Frontend routes, pages, React Query/API adapters, Operator UI pages, state stores,
  and page-to-backend closure.
- Factor registry, factor lifecycle, IC persistence, factor gates, strategies,
  SignalComposer/PortfolioBuilder/backtest paths, and PT/operator handoff.
- Trading and risk controls, including PT state, V3 risk rules, L4 staged execution,
  realtime risk, approval/pause/clear guardrails, and read-only runtime evidence.
- Documentation, including AGENTS, SYSTEM_STATUS, Blueprint, DEV docs, ADRs,
  audit reports, runbooks, API coverage, and handoff memory.
- Governance assets, including Codex hooks, Git hooks, skills, agents, CI/CD,
  GitHub PR checks, branch hygiene, and runtime noise exclusions.

## Working Loop

1. Read current state before changing it: code, docs, tests, runtime probes, and PR state.
2. Build an evidence map for each domain: claim, implementation, test, runtime signal,
   and remaining gap.
3. Fix high-confidence defects directly when they are inside the allowed boundary.
4. Verify every fix with the narrowest meaningful command plus any affected integration
   or runtime probe.
5. Record what changed, what was verified, and what remains unresolved.
6. Push the branch and keep the PR auditable.

## Redline Boundary

Do not perform broker mutations, clear positions, destructive DB changes, `.env`
sensitive edits, or production YAML changes without a specific redline plan and
explicit current authorization for that exact action. Read-only probes, code fixes,
documentation governance, hook/skill cleanup, tests, builds, commits, pushes, and PR
updates are in scope for autonomous progress.

## Completion Definition

This goal is complete only when current evidence proves all of the following:

- Major project domains have an up-to-date inventory and closure verdict.
- Claims in primary docs match current code or are explicitly marked historical.
- Frontend-visible workflows have backend/API/test/runtime evidence or a tracked
  backlog item with owner, blocker, and acceptance criteria.
- Hooks, skills, agents, and CI gates are versioned, low-noise, and verified.
- Remaining risks are not vague: each has severity, evidence, next action, and gate.
- GitHub PR state and CI checks are green or any failures are explained and tracked.

Until that evidence exists, the goal remains active and iteration continues.
