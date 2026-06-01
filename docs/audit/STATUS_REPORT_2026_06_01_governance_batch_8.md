# Governance Batch 8 - LLM Fallback Audit Error Category Closure

Date: 2026-06-01 Asia/Shanghai
Branch: `codex/runtime-governance-followup`
PR: #523

## Scope

Batch 8 closes the LLM fallback audit durability backlog opened during the PR #523 follow-up review:

- Preserve a sanitized primary-provider failure category when LiteLLM succeeds through fallback.
- Keep the existing `llm_call_log.error_class` schema and avoid raw provider error persistence.

This was a backend LLM audit contract fix only. No broker, QMT, `.env`, production YAML, scheduler, Servy, or database mutation was performed.

## Finding

`BudgetAwareRouter._audit_log()` only wrote `primary_fail_fallback_engaged` for non-capped fallback success rows. That made fallback visibility durable, but not the provider failure category. Once logs rotate, operators could see that fallback happened but not whether the primary failure was authentication, rate limit, timeout, context, content-policy, outage, or an unknown provider error.

Code evidence:

- LiteLLM records failed primary attempts in fallback metadata under `previous_models` with `exception_type` and `exception_string`.
- `LLMResponse` did not expose any sanitized fallback error category.
- `BudgetAwareRouter._audit_log()` ignored LiteLLM metadata and persisted only the broad fallback label.

Active discovery:

- A schema migration was unnecessary: the existing `error_class VARCHAR(40)` can safely store fixed category labels such as `primary_fail_authentication`.
- Raw provider messages may include API-key fragments or provider text, so the durable value must be a fixed category string only.
- Budget-capped fallback rows should keep `budget_capped`; the provider category is only for primary-fail fallback rows.

## Fixes

- Added `LLMResponse.fallback_error_class: str | None`.
- Added router extraction for LiteLLM fallback metadata from `_hidden_params.metadata.previous_models`, `_hidden_params.litellm_metadata.previous_models`, and direct response metadata containers.
- Added fixed sanitized categories:
  - `primary_fail_authentication`
  - `primary_fail_rate_limit`
  - `primary_fail_timeout`
  - `primary_fail_context_window`
  - `primary_fail_content_policy`
  - `primary_fail_provider_unavailable`
  - `primary_fail_provider_error`
- Updated `BudgetAwareRouter._audit_log()` to persist the sanitized category for non-capped fallback rows when present, while preserving `primary_fail_fallback_engaged` as the no-metadata fallback label.
- Added router and audit regression tests proving no raw provider message/key fragment is persisted.

## Verification

Red phase:

- `pytest backend/tests/test_litellm_router_core.py::test_fallback_response_records_sanitized_provider_error_class backend/tests/test_litellm_audit.py::test_aware_router_audit_persists_sanitized_primary_error_category -q` failed before the fix:
  - `LLMResponse` had no `fallback_error_class` attribute;
  - audit rows still wrote `primary_fail_fallback_engaged`.

Green phase:

- Targeted RED tests -> 2 passed.
- `pytest backend/tests/test_litellm_router_core.py backend/tests/test_litellm_audit.py -q` -> 52 passed.
- `pytest backend/tests/test_litellm_budget.py backend/tests/test_meta_monitor_service.py -q` -> 61 passed.
- `pytest backend/tests/test_market_regime_service.py backend/tests/test_news_classifier_service.py backend/tests/test_news_classifier_rag_wire.py backend/tests/test_rag_consumer_smoke.py backend/tests/test_regime_rag_wire.py -q` -> 97 passed, 2 skipped.
- `ruff check backend/qm_platform/llm backend/tests/test_litellm_router_core.py backend/tests/test_litellm_audit.py` -> pass.
- `ruff format --check backend/qm_platform/llm backend/tests/test_litellm_router_core.py backend/tests/test_litellm_audit.py` -> pass.

## Open Backlog

- **GB4-B1 [P0 ops]** Elevated/admin service reload is still required before Batch 3 runtime rows can reflect the new `qmt_cache_unavailable` risk-tick path.
- **GB2-B1 [P0 ops/secret]** DeepSeek primary provider authentication still requires operator secret/provider remediation; no secret mutation was performed.

## Redline

No broker order API, QMTData start, `.env` edit, production YAML edit, destructive DB change, Task Scheduler mutation, Servy configuration mutation, or database write was performed.
