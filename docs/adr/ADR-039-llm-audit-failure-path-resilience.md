---
adr_id: ADR-039
title: LLM audit failure path resilience — retry policy + transient/permanent classifier (S2.4 sub-task partial closure)
status: accepted
related_ironlaws: [33, 34, 41]
recorded_at: 2026-05-07
---

## Context

**5-07 sub-PR 8b-llm-audit-S2.4 sediment trigger**: ADR-DRAFT row 7 真**残余 sub-task** promote — Sprint 1 PR #224 真**success-only audit** deferred S2.4+ → 5-07 sub-PR 8a-followup-B-audit PR #248 已**部分 closed** (BUG #2 dynamic detect 4-case error_class + BUG #3 try/except 包络 failure path audit row + re-raise).

**真残余 sub-task** (per ADR-DRAFT row 7):
1. retry policy (本 ADR scope ✅)
2. circuit breaker (defer sub-PR 8b-resilience 真预约)
3. DingTalk push 触发 LL_AUDIT_INSERT_FAILED (defer sub-PR 9 真预约)

**真因 sediment** (5-07 sub-PR 8a-followup-B-audit PR #248 + sub-PR 8b-llm-fix PR #253 sediment 沿用):

post-PR #248 audit failure path 真**0 retry sustained**: `LLMCallLogger.log_call` 真 INSERT 失败 → `logger.warning("llm_audit_insert_failed")` → `return False`. **0 transient retry path** 真**connection loss / cursor state error / serialization deadlock** sustained 漂移:

| transient case | post-PR #248 behavior | 真**residual** risk |
|---|---|---|
| psycopg2.OperationalError (connection lost mid-INSERT) | logger.warning + return False | audit row 真**silent loss** sustained |
| psycopg2.InterfaceError (cursor state error) | logger.warning + return False | audit row 真**silent loss** sustained |
| psycopg2.errors.SerializationFailure (concurrent deadlock) | logger.warning + return False | audit row 真**silent loss** sustained |

post-PR #253 (sub-PR 8b-llm-fix Pydantic propagate primary path 真生效) DeepSeek primary 真**100% success path sustained 沿用 18:03+ batches**, audit row 真**全 INSERT 真生效** sustained 0 trigger above transient cases. 但**真生产 transient** (e.g. PG restart / network blip / serialization conflict) sustained risk — 沿用 ADR-008 命名空间 partial-write 漂移历史 + LL-100 chunked SOP 真**production resilience** 体例 sustained.

**真**反**真生产真值** sub-PR 8a-followup-pre meta-verify 4 days production 0 catch (沿用 LL-109 hook governance reverse case): retry policy 真**production-level** verify 反 paper sediment.

## Decision

**Retry policy 双层防御** sediment (本 ADR-039 scope):

1. **Transient/permanent classifier**: `_TRANSIENT_DB_EXC_CLASSES` frozenset (`OperationalError`, `InterfaceError`, `SerializationFailure`) — 沿用 psycopg2 真**connection-level / cursor-level / deadlock** 体例. 反 hard `import psycopg2` couple (沿用 audit module conn:Any **connection-agnostic** 体例 sustained sub-PR 7c contract). Heuristic 真 type(exc).__name__ 字符串 match.

2. **Retry rule** (LLMCallLogger._insert_with_retry):
   - transient match → retry up to `max_retries` (默认 2 真 3 attempts total) with exponential backoff `retry_wait_base * 2^attempt` (默认 0.1s → 0.2s, max ~0.3s total).
   - permanent (其他 Exception subclass) → immediate fail-loud (反 retry same permanent error waste budget — IntegrityError / ProgrammingError 等 retry 反**改变 outcome**).
   - exhausted retries → `logger.warning("llm_audit_insert_failed", attempts=N, transient=True/False)` + return False (反 break caller completion).
   - retry success → `logger.warning("llm_audit_insert_retry_success", attempts=N+1)` 沿用铁律 33 fail-loud sediment 反 silent recovery.

3. **反 break completion contract** sustained (沿用 sub-PR 7c contract + 决议 7):
   - max retry overhead: `0.1 + 0.2 = 0.3s` 真**caller latency budget** ~5s (V3 §16.2 cost guardrails) 反**break**.
   - rollback on each failed attempt (反 cumulative DB state corruption).

## Alternatives Considered

**(1) Tenacity decorator 真**retry mechanism**** — 沿用 backend/qm_platform/news/*.py fetcher 体例 sustained. **未选**: tenacity 真**function-level decorator** 体例 反 LLMCallLogger 真**class method 真 instance state** (max_retries/retry_wait_base 真 instance config). 反 audit module 真**hard coupling** 真 tenacity (反 already-imported 体例, 反 sub-task feature creep). 真 manual `while + time.sleep` 真**simpler control flow** + 反 third-party retry behavior surprise.

**(2) Hard psycopg2 import + isinstance 真 transient classifier** — `from psycopg2 import OperationalError; isinstance(exc, OperationalError)`. **未选**: 沿用 audit module conn:Any **connection-agnostic** 体例 sustained sub-PR 7c contract — 反**hard couple** specific DB driver. Heuristic `type(exc).__name__ in frozenset(...)` 真**generic** sustained 反 driver-specific (e.g. asyncpg / SQLAlchemy 真**类似 exc class names**, hot-swappable). 真**production evidence**: psycopg2 真**唯一 production driver** sustained, frozenset cover 100% transient cases.

**(3) Sediment-only ADR-039 (反 implementation patch)** — `docs/adr/ADR-039-...md` create + REGISTRY/ADR-DRAFT update, 0 audit.py change. **未选**: 沿用 ADR-037 governance pattern + 真讽刺 #17 sediment 加深 (修复 metric ≠ 修复真生产 issue). ADR-039 真**production verify** 反 paper sediment 沿用 LL-100 chunked SOP 真**production-level e2e re-run** 体例 sustained.

**(4) 全 sub-task 同 PR cover (retry + circuit breaker + DingTalk push)** — single mega-chunk PR. **未选**: 沿用 LL-100 chunked SOP <400 line single chunk + sub-PR 8b-resilience (circuit breaker) + sub-PR 9 (DingTalk push) 真预约. circuit breaker 真**state machine + threshold + cooldown** 真**重 implementation** + DingTalk push 真**LL_AUDIT_INSERT_FAILED 真 alert chain integration**, 全独立 sub-task 沿用 user 决议精神 #4 反留尾巴 + #2 sequence-based.

## Consequences

**正面**:
- audit row 真**transient loss recovery** sustained — production resilience 真**双层防御** (retry + fail-loud)
- 沿用 ADR-037 governance pattern + ADR-031 §6 渐进 deprecate plan + ADR-032 caller bootstrap factory 体例 sustained
- 真**connection-agnostic** sustained (反 hard psycopg2 couple) 沿用 audit module 真 future driver swap path open
- 真**fail-loud sediment** sustained (transient+permanent 沿用 logger.warning structured event log, 反 silent miss 铁律 33)
- max retry overhead 0.3s 真**caller latency budget** ~5s 反 break completion contract sustained sub-PR 7c

**负面**:
- audit module 真**stateful retry config** (max_retries / retry_wait_base) 沿用 instance attr 真**caller config exposure** 体例 — 反 default-only API
- transient classifier 真**string match heuristic** sustained 反 isinstance — 真**driver-specific exc class name change** sustained 真**silent miss** risk (audit Week 2 batch C 真预约 — sub-PR 9 DingTalk push 触发 audit alarm)
- 真**残余 sub-task** 2 个 (circuit breaker + DingTalk push) 沿用 sub-PR 8b-resilience + sub-PR 9 真预约 sustained — ADR-DRAFT row 7 真**partial closed**, 0 全 closed
- **Conn-reuse limitation** (HIGH reviewer adopt sub-PR 8b-llm-audit-S2.4): 真**retry on same conn** 真**effective scope**:
  - `SerializationFailure` (deadlock): conn alive, rollback + retry 真生效 ✅
  - `InterfaceError` (cursor state): conn alive, rollback + retry 真生效 ✅
  - `OperationalError` (connection lost / TCP reset): conn dead, rollback 走 suppress 反**retry on same dead conn** 真**subsequent InterfaceError 链 retry budget exhausted**, 真**反 break completion** sustained (return False).
  真**connection-loss recovery 真预约** sub-PR 8b-resilience circuit breaker + fresh `conn_factory()` reissue 体例 sustained — 真**避免 silent infinite reconnect loop** 沿用 ADR-008 命名空间 circuit breaker 体例 sustained.

## Implementation

**本 PR (sub-PR 8b-llm-audit-S2.4)**:
- patch [`backend/qm_platform/llm/_internal/audit.py`](../../backend/qm_platform/llm/_internal/audit.py): 新 `_TRANSIENT_DB_EXC_CLASSES` constant + LLMCallLogger `__init__` 加 `max_retries` + `retry_wait_base` 参数 + 新 `_insert_with_retry()` method (refactor `log_call` 真 INSERT 路径)
- create [`backend/tests/test_litellm_audit_retry.py`](../../backend/tests/test_litellm_audit_retry.py): retry policy smoke tests
- update [`docs/adr/REGISTRY.md`](REGISTRY.md): +ADR-039 row (committed)
- update [`docs/adr/ADR-DRAFT.md`](ADR-DRAFT.md): row 7 mark `→ ADR-039 (committed)`
- create memory file `memory/sprint_2_sub_pr_8b_gdelt_closure_and_8b_llm_audit_s24_2026_05_07.md`

**留 sub-PR 8b-resilience (circuit breaker, 真预约)**:
- circuit breaker 真**state machine** (CLOSED → OPEN → HALF_OPEN) + threshold (e.g. 5 consecutive transient fails) + cooldown
- 沿用 ADR-008 命名空间体例 sustained circuit_breaker_state 表 (反 LLM-specific table)

**留 sub-PR 9 (DingTalk push, 真预约)**:
- LL_AUDIT_INSERT_FAILED 触发 DingTalk alert (沿用 ADR-008 alert chain integration 体例)
- alert dedup TTL (沿用 DINGTALK_DEDUP_TTL_MIN 60min)

## References

- [ADR-DRAFT.md row 7](ADR-DRAFT.md) — Audit failure path coverage S2.4 sub-task 真**partial closure** sediment (本 ADR promote target)
- [ADR-031 §6](ADR-031-litellm-router-implementation-path.md) — S2 LiteLLMRouter implementation path 决议 (本 ADR 沿用 audit module 真 sub-task scope)
- [ADR-032](ADR-032-caller-bootstrap-factory.md) — caller bootstrap factory + naked LiteLLMRouter export 限制 (本 ADR 沿用 conn_factory DI 体例)
- [ADR-037](ADR-037-internal-source-fresh-read-sop.md) — Internal source fresh read SOP (governance, 本 ADR 沿用同体例 sustained)
- LL-067 — Reviewer agent 真第二把尺子 (本 ADR 沿用 single chunk PR + reviewer 体例 sustained)
- LL-098 (X10) — AI 自动驾驶 forward-progress reverse case (本 ADR 沿用 sequence-based + LL-100 chunked SOP)
- LL-110 — web_fetch 官方文档 verify SOP (本 ADR 沿用 LL-110 + LL-112 体例 sustained)
- 真讽刺案例 #17 sediment 加深 — 修复 metric ≠ 修复真生产 issue (本 ADR 沿用 production-level verify 反 paper sediment 体例)
- 真讽刺案例 #19 候选 sediment (我 frame drift 第 8 次 catch — sub-PR 8b-gdelt prompt premise 漂移 catch 沿用 audit chunk C 真预约)
