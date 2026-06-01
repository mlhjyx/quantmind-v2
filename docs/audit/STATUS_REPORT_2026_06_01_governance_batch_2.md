# STATUS REPORT - 2026-06-01 Governance Batch 2

> Scope: second autonomous remediation slice under the full-project closure/governance goal. This batch diagnosed `meta_alert:litellm_failure_rate`, patched a meta-monitor false-positive path, and left the provider credential issue as an explicit redline backlog. No broker action, `.env` edit, production YAML edit, DB write, Servy restart, Task Scheduler mutation, or QMT start was performed.

## 1. Grounding

- Fresh-read continuity: used the batch-1 handoff in `memory/project_sprint_state.md` plus the required V3 anchors already read at batch start (`AGENTS.md`, `IRONLAWS.md`, `SYSTEM_STATUS.md`, V3 Constitution, skill/hook map, risk framework design, ADR registry).
- Runtime evidence timestamp: 2026-06-01 11:37-11:40 Asia/Shanghai, via read-only PostgreSQL queries and local Celery logs.
- Active discovery #1: batch-1 classified the LiteLLM meta alert as active. Fresh runtime evidence changed that status: the alert fired at 11:05, 11:10, and 11:15, then cleared from 11:20 through 11:40. The root provider problem remains.
- Active discovery #2: while diagnosing the incident, code review found a latent false-positive path: intentional `budget_capped` local fallback was counted as a LiteLLM API failure.

## 2. Runtime Diagnosis

| Evidence | Result |
|---|---|
| `alert_dedup` row | `meta_alert:litellm_failure_rate`, `severity=p0`, `fire_count=44`, last fired 2026-06-01 11:15:00+08, suppress until 11:20:00+08. This row is dedup state, not proof that the alert is still active. |
| `scheduler_task_log` | `meta_monitor` success rows at 11:20, 11:25, 11:30, 11:35, and 11:40 all had `triggered=0`. |
| `llm_call_log` 5-minute window at 11:40 | `calls_5m=0`, `failed_5m=0`; latest LLM audit row was 11:10:03+08. |
| `llm_call_log` 1-hour window at 11:39 | 13 API-attempt rows, 13 failures, 0 `budget_capped` rows. All recent rows were `primary_fail_fallback_engaged` with actual model `ollama_chat/qwen3.5:9b`. |
| `logs/celery-slow-stderr.log` | Primary DeepSeek calls failed with masked-key authentication error, then LiteLLM fell back to local Qwen. |

Conclusion: GB1-B1 is no longer an active 5-minute alert condition as of 11:20+08, but it is still an operational P0 blocker because primary DeepSeek credentials are rejected. Fixing that requires sensitive `.env` / secret rotation, which is intentionally outside this autonomous batch.

## 3. Closed

| ID | Severity | Finding | Closure |
|---|---:|---|---|
| GB2-001 | P1 | Meta-monitor LiteLLM collector counted every non-null `error_class` as an API failure. That misclassified `budget_capped` as a provider outage, even though budget-cap fallback is an intentional cost-control route before primary API attempt. | `_collect_litellm` now excludes `budget_capped` from both API-attempt denominator and failure numerator. Regression coverage pins the SQL filter and parameter order. |

## 4. Still Open

| ID | Severity | Evidence | Blocker / next batch | Acceptance |
|---|---:|---|---|---|
| GB2-B1 | P0 | Slow-worker log shows DeepSeek authentication rejection with masked key suffix; DB shows recent fallback rows and no successful primary rows after the incident. | Requires secret/key rotation or provider-side account fix. `.env` mutation is a redline and was not performed. | After rotation, a controlled LiteLLM primary call succeeds, recent `llm_call_log` primary rows have `error_class IS NULL`, and `meta_monitor` stays `triggered=0` across at least two 5-minute ticks with LLM traffic. |
| GB2-B2 | P1 | `llm_call_log.error_class='primary_fail_fallback_engaged'` does not persist the sanitized provider error category; the exact cause currently depends on worker logs. | Needs schema/design decision: add sanitized provider error metadata or a separate LLM provider health table. | Provider failure reason is queryable after log rotation without storing secrets or raw provider payloads. |
| GB1-B2 | P0 | Realtime risk/QMT runtime input path remains unresolved from batch 1. | Starting QMT/Servy is an ops touchpoint; not touched in this batch. | Controlled runtime verification showing L1 heartbeat, portfolio input, tick/5min rule execution, and explicit no-order state. |

## 5. Verification

- `pytest backend/tests/test_meta_monitor_service.py::test_collect_litellm_window_param_and_counts backend/tests/test_meta_monitor_service.py::test_collect_litellm_excludes_budget_cap_from_api_failure_rate_query backend/tests/test_meta_monitor_service.py::test_collect_and_evaluate_litellm_failure_triggers_rule -q` - 3 passed.
- `ruff format backend/app/services/risk/meta_monitor_service.py backend/qm_platform/risk/metrics/meta_alert_interface.py backend/tests/test_meta_monitor_service.py` - formatted 3 files.
- `ruff check backend/app/services/risk/meta_monitor_service.py backend/qm_platform/risk/metrics/meta_alert_interface.py backend/tests/test_meta_monitor_service.py` - PASS.
- `pytest backend/tests/test_meta_monitor_service.py backend/tests/test_meta_alert_rules.py -q` - 106 passed.
- Read-only live SQL after the patch logic: last 1 hour had 13 API-attempt rows, 13 provider/fallback failures, 0 `budget_capped`; latest 5-minute window at 11:40 had 0 calls and 0 failures.

## 6. Sediment

- LL candidate: alert state must distinguish current rule evaluation from `alert_dedup` history; dedup rows are not active-alert truth by themselves.
- ADR candidate: LiteLLM observability should persist a sanitized provider failure category for fallback-success rows, because `primary_fail_fallback_engaged` alone loses root-cause granularity after logs rotate.
- Handoff updated in `memory/project_sprint_state.md` with current evidence, redline blocker, and next safe steps.
