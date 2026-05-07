---
adr_id: ADR-039
title: LLM audit failure path resilience — retry policy + transient/permanent classifier (S2.4 sub-task partial closure)
status: accepted
related_ironlaws: [33, 34, 41]
recorded_at: 2026-05-07
---

## Context

**5-07 sub-PR 8b-llm-audit-S2.4 sediment trigger**: ADR-DRAFT row 7 **残余 sub-task** promote — Sprint 1 PR #224 **success-only audit** deferred S2.4+ → 5-07 sub-PR 8a-followup-B-audit PR #248 已**部分 closed** (BUG #2 dynamic detect 4-case error_class + BUG #3 try/except 包络 failure path audit row + re-raise).

**残余 sub-task** (per ADR-DRAFT row 7):
1. retry policy (本 ADR scope ✅)
2. circuit breaker (defer sub-PR 8b-resilience 待办)
3. DingTalk push 触发 LL_AUDIT_INSERT_FAILED (defer sub-PR 9 待办)

**因 sediment** (5-07 sub-PR 8a-followup-B-audit PR #248 + sub-PR 8b-llm-fix PR #253 sediment 沿用):

post-PR #248 audit failure path **0 retry**: `LLMCallLogger.log_call` INSERT 失败 → `logger.warning("llm_audit_insert_failed")` → `return False`. **0 transient retry path** **connection loss / cursor state error / serialization deadlock** 漂移:

| transient case | post-PR #248 behavior | **residual** risk |
|---|---|---|
| psycopg2.OperationalError (connection lost mid-INSERT) | logger.warning + return False | audit row **silent loss** |
| psycopg2.InterfaceError (cursor state error) | logger.warning + return False | audit row **silent loss** |
| psycopg2.errors.SerializationFailure (concurrent deadlock) | logger.warning + return False | audit row **silent loss** |

post-PR #253 (sub-PR 8b-llm-fix Pydantic propagate primary path 生效) DeepSeek primary **100% success path 沿用 18:03+ batches**, audit row **全 INSERT 生效** 0 trigger above transient cases. 但**真生产 transient** (e.g. PG restart / network blip / serialization conflict) risk — 沿用 ADR-008 命名空间 partial-write 漂移历史 + LL-100 chunked SOP **production resilience** 体例.

****反**真生产真值** sub-PR 8a-followup-pre meta-verify 4 days production 0 catch (沿用 LL-109 hook governance reverse case): retry policy **production-level** verify 反 paper sediment.

## Decision

**Retry policy 双层防御** sediment (本 ADR-039 scope):

1. **Transient/permanent classifier**: `_TRANSIENT_DB_EXC_CLASSES` frozenset (`OperationalError`, `InterfaceError`, `SerializationFailure`) — 沿用 psycopg2 **connection-level / cursor-level / deadlock** 体例. 反 hard `import psycopg2` couple (沿用 audit module conn:Any **connection-agnostic** 体例 sub-PR 7c contract). Heuristic type(exc).__name__ 字符串 match.

2. **Retry rule** (LLMCallLogger._insert_with_retry):
 - transient match → retry up to `max_retries` (默认 2 3 attempts total) with exponential backoff `retry_wait_base * 2^attempt` (默认 0.1s → 0.2s, max ~0.3s total).
 - permanent (其他 Exception subclass) → immediate fail-loud (反 retry same permanent error waste budget — IntegrityError / ProgrammingError 等 retry 反**改变 outcome**).
 - exhausted retries → `logger.warning("llm_audit_insert_failed", attempts=N, transient=True/False)` + return False (反 break caller completion).
 - retry success → `logger.warning("llm_audit_insert_retry_success", attempts=N+1)` 沿用铁律 33 fail-loud sediment 反 silent recovery.

3. **反 break completion contract** (沿用 sub-PR 7c contract + 决议 7):
 - max retry overhead: `0.1 + 0.2 = 0.3s` **caller latency budget** ~5s (V3 §16.2 cost guardrails) 反**break**.
 - rollback on each failed attempt (反 cumulative DB state corruption).

## Alternatives Considered

**(1) Tenacity decorator **retry mechanism**** — 沿用 backend/qm_platform/news/*.py fetcher 体例. **未选**: tenacity **function-level decorator** 体例 反 LLMCallLogger **class method instance state** (max_retries/retry_wait_base instance config). 反 audit module **hard coupling** tenacity (反 already-imported 体例, 反 sub-task feature creep). manual `while + time.sleep` **simpler control flow** + 反 third-party retry behavior surprise.

**(2) Hard psycopg2 import + isinstance transient classifier** — `from psycopg2 import OperationalError; isinstance(exc, OperationalError)`. **未选**: 沿用 audit module conn:Any **connection-agnostic** 体例 sub-PR 7c contract — 反**hard couple** specific DB driver. Heuristic `type(exc).__name__ in frozenset(...)` **generic** 反 driver-specific (e.g. asyncpg / SQLAlchemy **类似 exc class names**, hot-swappable). **production evidence**: psycopg2 **唯一 production driver**, frozenset cover 100% transient cases.

**(3) Sediment-only ADR-039 (反 implementation patch)** — `docs/adr/ADR-039-...md` create + REGISTRY/ADR-DRAFT update, 0 audit.py change. **未选**: 沿用 ADR-037 governance pattern + drift catch #17 sediment 加深 (修复 metric ≠ 修复真生产 issue). ADR-039 **production verify** 反 paper sediment 沿用 LL-100 chunked SOP **production-level e2e re-run** 体例.

**(4) 全 sub-task 同 PR cover (retry + circuit breaker + DingTalk push)** — single mega-chunk PR. **未选**: 沿用 LL-100 chunked SOP <400 line single chunk + sub-PR 8b-resilience (circuit breaker) + sub-PR 9 (DingTalk push) 待办. circuit breaker **state machine + threshold + cooldown** **重 implementation** + DingTalk push **LL_AUDIT_INSERT_FAILED alert chain integration**, 全独立 sub-task 沿用 user 决议精神 #4 反留尾巴 + #2 sequence-based.

## Consequences

**正面**:
- audit row **transient loss recovery** — production resilience **双层防御** (retry + fail-loud)
- 沿用 ADR-037 governance pattern + ADR-031 §6 渐进 deprecate plan + ADR-032 caller bootstrap factory 体例
- **connection-agnostic** (反 hard psycopg2 couple) 沿用 audit module future driver swap path open
- **fail-loud sediment** (transient+permanent 沿用 logger.warning structured event log, 反 silent miss 铁律 33)
- max retry overhead 0.3s **caller latency budget** ~5s 反 break completion contract sub-PR 7c

**负面**:
- audit module **stateful retry config** (max_retries / retry_wait_base) 沿用 instance attr **caller config exposure** 体例 — 反 default-only API
- transient classifier **string match heuristic** 反 isinstance — **driver-specific exc class name change** **silent miss** risk (audit Week 2 batch C 待办 — sub-PR 9 DingTalk push 触发 audit alarm)
- **残余 sub-task** 2 个 (circuit breaker + DingTalk push) 沿用 sub-PR 8b-resilience + sub-PR 9 待办 — ADR-DRAFT row 7 **partial closed**, 0 全 closed
- **Conn-reuse limitation** (HIGH reviewer adopt sub-PR 8b-llm-audit-S2.4): **retry on same conn** **effective scope**:
 - `SerializationFailure` (deadlock): conn alive, rollback + retry 生效 ✅
 - `InterfaceError` (cursor state): conn alive, rollback + retry 生效 ✅
 - `OperationalError` (connection lost / TCP reset): conn dead, rollback 走 suppress 反**retry on same dead conn** **subsequent InterfaceError 链 retry budget exhausted**, **反 break completion** (return False).
 **connection-loss recovery 待办** sub-PR 8b-resilience circuit breaker + fresh `conn_factory()` reissue 体例 — **避免 silent infinite reconnect loop** 沿用 ADR-008 命名空间 circuit breaker 体例.

## Implementation

**本 PR (sub-PR 8b-llm-audit-S2.4)**:
- patch [`backend/qm_platform/llm/_internal/audit.py`](../../backend/qm_platform/llm/_internal/audit.py): 新 `_TRANSIENT_DB_EXC_CLASSES` constant + LLMCallLogger `__init__` 加 `max_retries` + `retry_wait_base` 参数 + 新 `_insert_with_retry()` method (refactor `log_call` INSERT 路径)
- create [`backend/tests/test_litellm_audit_retry.py`](../../backend/tests/test_litellm_audit_retry.py): retry policy smoke tests
- update [`docs/adr/REGISTRY.md`](REGISTRY.md): +ADR-039 row (committed)
- update [`docs/adr/ADR-DRAFT.md`](ADR-DRAFT.md): row 7 mark `→ ADR-039 (committed)`
- create memory file `memory/sprint_2_sub_pr_8b_gdelt_closure_and_8b_llm_audit_s24_2026_05_07.md`

**留 sub-PR 8b-resilience (circuit breaker, 待办)**:
- circuit breaker **state machine** (CLOSED → OPEN → HALF_OPEN) + threshold (e.g. 5 consecutive transient fails) + cooldown
- 沿用 ADR-008 命名空间体例 circuit_breaker_state 表 (反 LLM-specific table)

**留 sub-PR 9 (DingTalk push, 待办)**:
- LL_AUDIT_INSERT_FAILED 触发 DingTalk alert (沿用 ADR-008 alert chain integration 体例)
- alert dedup TTL (沿用 DINGTALK_DEDUP_TTL_MIN 60min)

## References

- [ADR-DRAFT.md row 7](ADR-DRAFT.md) — Audit failure path coverage S2.4 sub-task **partial closure** sediment (本 ADR promote target)
- [ADR-031 §6](ADR-031-litellm-router-implementation-path.md) — S2 LiteLLMRouter implementation path 决议 (本 ADR 沿用 audit module sub-task scope)
- [ADR-032](ADR-032-caller-bootstrap-factory.md) — caller bootstrap factory + naked LiteLLMRouter export 限制 (本 ADR 沿用 conn_factory DI 体例)
- [ADR-037](ADR-037-internal-source-fresh-read-sop.md) — Internal source fresh read SOP (governance, 本 ADR 沿用同体例)
- LL-067 — Reviewer agent 第二把尺子 (本 ADR 沿用 single chunk PR + reviewer 体例)
- LL-098 (X10) — AI 自动驾驶 forward-progress reverse case (本 ADR 沿用 sequence-based + LL-100 chunked SOP)
- LL-110 — web_fetch 官方文档 verify SOP (本 ADR 沿用 LL-110 + LL-112 体例)
- drift catch case #17 sediment 加深 — 修复 metric ≠ 修复真生产 issue (本 ADR 沿用 production-level verify 反 paper sediment 体例)
- drift catch case #19 候选 sediment (我 frame drift 第 8 次 catch — sub-PR 8b-gdelt prompt premise 漂移 catch 沿用 audit chunk C 待办)
