# Governance Batch 10 - Blocking CI Regression Parity

Date: 2026-06-01 Asia/Shanghai
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 10 closes the CI/GitHub parity backlog tracked from Batch 1:

- Make the GitHub `regression` and `ci_matrix` jobs blocking instead of advisory.
- Make the regression phase use committed artifacts that are available on a fresh GitHub runner.
- Add workflow-contract coverage so advisory masking cannot quietly return.
- Keep the change limited to CI orchestration, tests, and design sediment.

No broker, QMT, `.env`, production YAML, scheduler, Servy, database mutation, or service-control action was performed.

## Finding

The GitHub workflow still ran `regression` and `ci_matrix` through `scripts/ci_run_phase.py --advisory`, so failures could be converted into a passing job with `ADVISORY_FAIL` output.

Code inspection found a second issue behind that advisory wrapper: `RegressionOrchestrator.default_pairs()` pointed at `cache/baseline/backtest_5yr_{baseline,actual}.json` and `cache/baseline/backtest_12yr_{baseline,actual}.json`, but those files are not committed. The committed artifacts are `cache/baseline/regression_result_5yr.json` and `cache/baseline/regression_result_12yr.json`, both carrying recorded `run1.max_diff: 0.0` evidence.

Active discovery:

- Before the fix, `python scripts/ci_run_phase.py --phase regression` failed immediately with `FILE_MISSING` for the nonexistent `backtest_*` JSON files.
- `python scripts/ci_run_phase.py --phase ci_matrix` already passed locally, so the advisory wrapper on that job was unnecessary noise.
- Local pre-commit collect did not include a GitHub workflow contract test, so advisory masking could regress without tripping the bounded governance collect set.
- After the first push, GitHub confirmed the new blocking behavior: `regression`, `pre_commit`, and `pre_push` passed, while `ci_matrix` failed instead of being masked. The matrix runner used a bare `pytest -m ... -q` command, unlike the hosted pre-push collect-only command, and its failure detail exposed only `stdout_len`.
- After the command-tail follow-up, GitHub showed the remaining hosted-runner gap explicitly: `ci_matrix` selected tests but ended with `3 errors`, because GitHub-hosted runners do not provide the local runtime services required by smoke execution.

## Fixes

- Updated the default regression pairs to point at committed `regression_result_5yr.json` and `regression_result_12yr.json` artifacts.
- Added `recorded_max_diff()` so same-file regression artifacts are valid only when recorded `max_diff` fields are exactly zero; paired baseline-vs-actual comparison remains supported for custom callers.
- Removed `--advisory` from GitHub `regression` and `ci_matrix` jobs.
- Added `backend/tests/test_github_ci_workflow.py` to lock the workflow contract.
- Added the workflow contract test to the bounded `pre_commit` collect target list.
- Aligned `CIMatrixOrchestrator` smoke execution with the passing pre-push smoke scope: `pytest backend/tests/ -m "smoke and not live_tushare" --tb=line -q --timeout=60`.
- Added bounded stdout-tail output for failed matrix cells so future GitHub failures include the last meaningful pytest line rather than only output length.
- Added `QM_CI_SMOKE_COLLECT_ONLY=1` support to `CIMatrixOrchestrator`, sharing the pre-push collect target list for hosted CI.
- Set the GitHub `ci_matrix` job to the blocking collect-only contract. Local matrix runs without that env still execute the full smoke command.
- Updated `docs/mvp/MVP_4_3_cicd.md` to describe the blocking GitHub behavior.

## Verification

Red phase:

- `pytest backend/tests/test_qm_platform_ci_regression.py::test_default_pairs_use_committed_regression_result_artifacts backend/tests/test_qm_platform_ci_regression.py::test_single_artifact_nonzero_max_diff_fails backend/tests/test_qm_platform_ci_regression.py::test_default_regression_artifacts_pass_in_current_worktree backend/tests/test_github_ci_workflow.py::test_regression_and_matrix_jobs_are_blocking_not_advisory -q` failed before the fix on:
  - default pairs pointing at nonexistent `backtest_*` files;
  - same-file artifacts with nonzero recorded `max_diff` passing incorrectly;
  - the default regression phase failing due missing files;
  - GitHub workflow commands still carrying `--advisory`.

Green phase:

- Focused red-to-green contract tests -> 4 passed.
- CI regression/test pack -> 54 passed.
- `python scripts/ci_run_phase.py --phase regression` -> PASS, both default artifacts reported `max_diff=0.0`.
- `python scripts/ci_run_phase.py --phase ci_matrix` -> PASS.
- `python scripts/ci_run_phase.py --phase pre_commit` -> PASS.
- Post-push RED: first GitHub blocking `ci_matrix` run failed while `regression`, `pre_commit`, and `pre_push` passed, exposing matrix command drift and opaque failure details.
- Matrix RED: `pytest backend/tests/test_qm_platform_ci_matrix.py::test_default_cmd_builder_matches_prepush_smoke_scope backend/tests/test_qm_platform_ci_matrix.py::test_cell_failure_includes_stdout_tail_for_debugging -q` failed before the follow-up fix.
- Matrix GREEN: `pytest backend/tests/test_qm_platform_ci_matrix.py::test_default_cmd_builder_matches_prepush_smoke_scope backend/tests/test_qm_platform_ci_matrix.py::test_cell_failure_includes_stdout_tail_for_debugging backend/tests/test_qm_platform_ci_matrix.py -q` -> 18 passed.
- `ruff check backend/qm_platform/ci/ci_matrix.py backend/tests/test_qm_platform_ci_matrix.py` -> PASS.
- Follow-up `python scripts/ci_run_phase.py --phase ci_matrix` -> PASS.
- Hosted collect-only RED: `pytest backend/tests/test_qm_platform_ci_matrix.py::test_collect_only_env_uses_prepush_smoke_collect_targets -q` failed before env support.
- Hosted collect-only GREEN: `pytest backend/tests/test_qm_platform_ci_matrix.py -q` -> 19 passed.
- Local full matrix mode: `python scripts/ci_run_phase.py --phase ci_matrix` -> PASS.
- Hosted collect-only mode: `$env:QM_CI_SMOKE_COLLECT_ONLY='1'; python scripts/ci_run_phase.py --phase ci_matrix` -> PASS.

## Open Backlog

- **GB4-B1 [P0 ops]** Elevated/admin service reload is still required before Batch 3 runtime rows can reflect the `qmt_cache_unavailable` risk-tick path.
- **GB2-B1 [P0 ops/secret]** DeepSeek primary provider authentication still requires operator secret/provider remediation; no secret mutation was performed.
- **GB9-B1 [P2]** Notification detail, cleanup, and preferences endpoints remain backend/admin-only unless they become explicit operator workflows.

## Sediment Decision

- No new LL candidate: this closes a known Batch 1 backlog item with tests and CI configuration, without adding a new reusable governance principle.
- No new ADR candidate: this is an implementation correction inside the existing MVP 4.3 CI/CD design.

## Redline

No broker order API, QMTData start, `.env` edit, production YAML edit, destructive DB change, Task Scheduler mutation, Servy configuration mutation, or database write was performed.
