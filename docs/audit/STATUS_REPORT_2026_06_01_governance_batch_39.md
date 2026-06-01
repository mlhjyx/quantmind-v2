# Governance Batch 39 Status - Hosted pre_commit format fix

Date: 2026-06-01 +08:00
Branch: `codex/runtime-governance-followup`
Scope: CI repair for Batch 38 hosted `pre_commit` failure.

## Summary

PR #523 head `81b12847` failed only the hosted
`pre_commit (ruff + collect + llm_imports)` check. The other hosted checks
passed: `pre_push`, `regression`, and `ci_matrix`.

Root cause: `ruff format --check .` in the hosted pre-commit phase would
reformat the two new Batch 38 Python files:

- `backend/tests/test_mutating_api_auth_audit.py`
- `scripts/audit/check_mutating_api_auth.py`

The fix in this batch formats only those two new files.

## Important Non-Fix

Local Windows `ruff format --check backend scripts` also reports two older
mixed-line-ending worktree files:

- `backend/app/api/backtest.py`
- `backend/tests/test_param_system.py`

Those were not edited in this batch. Evidence from `git ls-files --eol` shows
their index entries are LF while the current Windows worktree copies are mixed.
Hosted CI checks the Linux checkout from the index. The production API file
also remains behind the project redline precondition: the read-only account
check still cannot connect to miniQMT.

## Verification

- `ruff format scripts/audit/check_mutating_api_auth.py backend/tests/test_mutating_api_auth_audit.py`
  -> 2 files reformatted.
- `ruff format --check scripts/audit/check_mutating_api_auth.py backend/tests/test_mutating_api_auth_audit.py`
  -> 2 files already formatted.
- `pytest backend/tests/test_mutating_api_auth_audit.py -q` -> 4 passed.
- `python scripts/audit/check_mutating_api_auth.py` ->
  `PASS: 58 mutating routes, 20 admin-gated, 38 classified no-admin routes`.
- `python scripts/_verify_account_oneshot.py` -> exit 1,
  `broker.connect()` returned `-1`.

## Risk Impact

This is a CI hygiene fix only. It does not change route behavior, auth policy,
DB state, broker state, `.env`, production YAML, Servy, Task Scheduler, or QMT
service state.
