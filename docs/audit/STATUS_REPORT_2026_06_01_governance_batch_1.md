# STATUS REPORT - 2026-06-01 Governance Batch 1

> Scope: first autonomous remediation slice under the full-project closure/governance goal. This batch touched CI/governance hooks and frontend risk API wiring only. No broker action, `.env` edit, production YAML edit, DB write, Servy restart, Task Scheduler mutation, or QMT start was performed.

## 1. Grounding

- Fresh-read set used for this batch: `AGENTS.md`, `IRONLAWS.md`, `SYSTEM_STATUS.md`, `memory/project_sprint_state.md`, `docs/V3_IMPLEMENTATION_CONSTITUTION.md`, `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md`, `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`, `docs/adr/REGISTRY.md`, and `docs/V3_LAUNCH_PROMPT.md`.
- Read-only redline check attempted `python scripts/_verify_account_oneshot.py`; miniQMT connect returned `-1`, so account cash/positions were not verified in this shell. This batch avoided account/broker mutation surfaces.
- Resource check showed enough CPU/RAM for lightweight CI/frontend checks; GPU was busy, so no heavy research/GPU workload was started.

## 2. Closed

| ID | Severity | Finding | Closure |
|---|---:|---|---|
| GB1-001 | P1 | Root `pyproject.toml` pointed pytest discovery at non-existent `tests/`, producing `PytestConfigWarning` on bare smoke runs. | `testpaths` now points to `backend/tests`; `backend/tests/test_pytest_config.py` guards the value. |
| GB1-002 | P1 | Pre-commit `pytest_collect` omitted active governance inventory/hook behavior tests. | `backend/qm_platform/ci/precommit.py` now collects active Codex governance and hook test files. |
| GB1-003 | P1 | Hook behavior tests targeted stale `.claude` paths instead of active `.codex` hooks. | `test_iron_law_enforce_hook.py` and `test_protect_critical_files_hook.py` now execute `.codex/hooks/*`. |
| GB1-004 | P1 | `cite_drift_stop_pretool.py` scoped V3 drift checks to legacy `.claude` paths, missing `.codex/agents` and repo `.agents/skills`. | Active Codex agent and project skill paths are now in scope with regression tests. |
| GB1-005 | P1 | Active `iron_law_enforce.py` crashed on Windows redirected stdout when emitting non-ASCII JSON warnings. | Hook output is ASCII-safe JSON; tests parse `additionalContext`; manual PT-protection warning returns rc=0. |
| GB1-006 | P1 | Frontend circuit-breaker state/reset used `/risk/state/default` and `/risk/force-reset/default`, but backend requires UUID strategy paths. | `frontend/src/api/risk.ts` owns UUID-based wrappers; `SafetyControlPanel` and `RiskManagement` use configured `PAPER_STRATEGY_ID`; dashboard default wrapper was removed. |

## 3. Still Open

| ID | Severity | Evidence | Blocker / next batch | Acceptance |
|---|---:|---|---|---|
| GB1-B1 | P0 | Runtime probe found active `meta_alert:litellm_failure_rate` with p0 severity and repeated fire count. | Needs LLM/router/runtime log diagnosis, not solved by static code patch. | Latest meta-monitor alert cleared or downgraded with root-cause evidence and regression test/log proof. |
| GB1-B2 | P0 | Risk runtime probe found QMT Data Service stopped by design, no Redis `risk:l1_heartbeat`, no `portfolio:current`, no `portfolio:nav`, and realtime risk path exercising zero positions. | Starting QMT/Servy is an ops touchpoint; current batch intentionally avoided it. | Controlled runtime verification showing L1 risk heartbeat, portfolio input, tick/5min rule execution, and explicit no-order safety state. |
| GB1-B3 | P1 | Frontend audit found websocket routes `/ws/pipeline/{run_id}` and `/ws/factor-mine/{id}` referenced by UI without matching backend Socket.IO routes. | Requires API contract decision: implement backend routes or remove/replace frontend live assumptions. | Matching backend route tests plus frontend live-flow test, or UI fallback explicitly marked polling-only. |
| GB1-B4 | P1 | Notification UI remains mock-seeded while backend notification endpoints exist. | Needs page-to-API contract mapping and user-visible empty/error states. | Notification page reads backend endpoints through `src/api/` and tests cover loading/empty/error/data. |
| GB1-B5 | P1 | Mining task center maps selected factor IDs into `{expr: id}` placeholders for gate submission. | Needs factor expression lookup or backend contract change. | Gate submission sends valid expressions or backend accepts IDs through a typed endpoint; regression test prevents placeholder re-growth. |
| GB1-B6 | P1 | GitHub Actions workflow still does not enforce the same review/governance surface as local pre-commit; local pre-commit now improved first. | Needs workflow inspection/update and CI run evidence. | CI workflow runs the same non-advisory governance checks or documents advisory gaps with issue IDs. |

## 4. Verification

- `python scripts/ci_run_phase.py --phase pre_commit` - PASS.
- `pytest backend/tests/test_pytest_config.py backend/tests/test_qm_platform_ci_precommit.py backend/tests/test_codex_governance_inventory.py backend/tests/test_cite_drift_stop_pretool_hook.py backend/tests/test_iron_law_enforce_hook.py backend/tests/test_protect_critical_files_hook.py -q` - 120 passed.
- `pytest -m "smoke and not live_tushare" -q` - 91 passed, 2 skipped, 6950 deselected.
- `npx vitest run src/__tests__/SafetyControlPanel.test.tsx src/__tests__/pages.test.tsx src/__tests__/api.test.ts` - 21 passed.
- `npm run build` - PASS (`tsc -b && vite build`; chunk-size warning only).
- Manual active-hook probe: piping a PT-core edit payload to `.codex/hooks/iron_law_enforce.py` returns rc=0 and JSON `additionalContext`.

## 5. Sediment

- LL candidate: hook stdout must be encoding-safe under Windows redirected execution; tests should parse hook JSON instead of asserting raw terminal text.
- ADR candidate: frontend risk safety endpoints should be strategy-UUID keyed at `src/api/risk.ts`; dashboard-level convenience wrappers must not hide backend UUID contract failures.
- Handoff updated in `memory/project_sprint_state.md` with this batch and next safe steps.
