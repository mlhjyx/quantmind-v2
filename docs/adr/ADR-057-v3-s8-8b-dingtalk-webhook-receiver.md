# ADR-057: V3 §S8 8b DingTalk Webhook Receiver — STAGED 反向决策权 inbound 路径

**Status**: committed
**Date**: 2026-05-13 (PR #307 merged as `e68b00a`)
**Type**: V3 Tier A S8 8b implementation sediment
**Parents**: ADR-027 (L4 STAGED + 反向决策权 + 跌停 fallback design SSOT) + ADR-056 (S8 8a state machine + DDL)
**Children**: future S8 8c (broker_qmt sell wire + STAGED smoke + Celery sweep)

## §1 背景

V3 §S8 acceptance line cites `STAGED smoke + DingTalk webhook 双向`. ADR-056 sediment closed 8a state machine + DDL but the **inbound webhook receiver** (DingTalk POST → server) was untouched. Without 8b, the PENDING_CONFIRM → CONFIRMED/CANCELLED transition pathway exists only as in-process function calls — no production reverse-decision channel.

Sustains V3 governance batch closure cumulative pattern (ADR-054 sediments S5, ADR-055 sediments S7, ADR-056 sediments S8 8a, this ADR sediments S8 8b).

## §2 Decision 1: 3-layer architecture (parser PURE / service DB / endpoint async)

**真值**: webhook code is partitioned across 3 modules:
- `backend/qm_platform/risk/execution/webhook_parser.py` — PURE (HMAC verify + regex command parse), 铁律 31, 0 IO
- `backend/app/services/risk/dingtalk_webhook_service.py` — DB orchestration, 0 conn.commit (铁律 32)
- `backend/app/api/risk.py:POST /dingtalk-webhook` — async endpoint, raw body capture + sig verify + service call + transaction boundary

**论据**:
1. Sustains CLAUDE.md §3.1 layered architecture (Router → Service → Engine)
2. Pure parser is unit-testable without DB, asyncio, FastAPI — 24 tests cover all sig/parse branches
3. Service can be reused by future Celery sweep task (TIMEOUT_EXECUTED transition) without async wrapper
4. Endpoint owns commit/rollback — sustains 铁律 32

## §3 Decision 2: HMAC-SHA256 signature scheme (custom bot pattern)

**真值**: signature = `base64(HMAC-SHA256(secret, f"{timestamp}\n{body}"))`, verified with `secrets.compare_digest` constant-time compare (反 timing side-channel byte-by-byte leak). Replay window: `abs(now - timestamp) <= 300s`.

**论据**:
1. MVP simplicity — full DingTalk card-callback AES-CBC protocol is a separate spec requiring AES key + nonce + AES-encrypted body decode; deferred to follow-up sub-PR if user activates real card-callback bot type
2. Custom HMAC works for "DingTalk custom bot HTTP POST" pattern which covers our use case (user replies command, bot relays via webhook)
3. 300s replay window aligns with industry standard (DingTalk outbound sign protocol uses similar bound)
4. `secrets.compare_digest` is mandatory (铁律 1 prereq for HMAC primitives)

## §4 Decision 3: Idempotent 2xx response contract

**真值**: All non-error outcomes return HTTP 200 with `outcome` enum discriminator:
- `TRANSITIONED`: PENDING_CONFIRM → CONFIRMED/CANCELLED success (DB UPDATE committed)
- `ALREADY_TERMINAL`: plan in CONFIRMED/CANCELLED/EXECUTED/TIMEOUT_EXECUTED/FAILED (idempotent return, no UPDATE)
- `DEADLINE_EXPIRED`: `now >= cancel_deadline` before user acted (no UPDATE)
- `PLAN_NOT_FOUND`: empty SELECT (no UPDATE)
- `AMBIGUOUS_PREFIX`: >1 row match prefix (no UPDATE)

Error paths return 4xx (401 invalid_signature/stale_timestamp, 400 malformed_body/unknown_command/invalid_plan_id, 503 secret_unconfigured).

**论据**:
1. DingTalk webhook auto-retries on non-2xx responses → 4xx storm would re-send the same already-processed message
2. Idempotent 2xx with discriminator semantics → DingTalk treats as success, no retry
3. 4xx reserved for "this message will never succeed" (signature/body/command failures — DingTalk should give up)

## §5 Decision 4: Race-safe atomic UPDATE WHERE status='PENDING_CONFIRM'

**真值**: Service-layer UPDATE includes `AND status = 'PENDING_CONFIRM'` predicate. `cursor.rowcount=0` after UPDATE → status changed concurrently → re-SELECT + return `ALREADY_TERMINAL`.

**论据**:
1. Concurrent webhook posts (user double-taps button) or Celery sweep timeout could race the same plan_id
2. Atomic compare-and-set via WHERE clause is the only safe primitive without row-locking (反 SELECT ... FOR UPDATE overhead for a typically-single-shot operation)
3. Re-SELECT after rowcount=0 provides ALREADY_TERMINAL semantics matching the actual current state

## §6 Decision 5: LIKE wildcard injection defense-in-depth (reviewer P1-1)

**真值**: `_resolve_prefix` escapes `%` `_` `\` in user-controlled prefix + uses `LIKE %s ESCAPE '\\'` clause.

**论据**:
1. Current parser regex `[0-9a-fA-F\-]{8,36}` blocks `%` `_` `\` from arriving at the SQL layer
2. But safe-by-construction > safe-by-caller-contract — if validator is ever loosened (e.g. accept extended UUID notation), the LIKE wildcard would over-match
3. Reviewer P1-1 caught the implicit dependency; explicit escape closes the gap

## §7 Decision 6: async endpoint with asyncio.to_thread for sync psycopg2 (reviewer P1-2)

**真值**: Endpoint is `async def`, but the inline `get_sync_conn() + service.process_command + conn.commit/rollback` block is wrapped in `await asyncio.to_thread(_sync_db_block)`.

**论据**:
1. psycopg2 is sync — calling it directly in `async def` blocks the entire uvicorn event loop on any PG lock wait
2. Webhook traffic is low (~user clicks/min) but blast radius spreads to all other endpoints on the same worker (project runs `--workers 2`)
3. `asyncio.to_thread` is a standard library primitive (Python 3.9+) — no new dependency, minimal overhead

## §8 Decision 7: Empty DINGTALK_WEBHOOK_SECRET → 503 (反 silent skip)

**真值**: When `settings.DINGTALK_WEBHOOK_SECRET == ""`, endpoint logs WARNING + returns HTTP 503. NOT a silent pass-through.

**论据**:
1. 铁律 33 fail-loud at boundary — silent acceptance of unsigned webhooks would defeat the entire authentication layer
2. 铁律 35 secrets via env — empty default forces operator to explicitly set secret before activation
3. 503 is the right code (service temporarily unavailable due to config), distinct from 401 (authentication failed) — guides operator to fix `.env` not the webhook payload

## §9 Decision 8: errors='strict' UTF-8 decode (reviewer P2-3)

**真值**: Raw body decode uses `errors='strict'` + catches `UnicodeDecodeError` → HTTP 400 `malformed_body`. NOT `errors='replace'` (which would silently corrupt the body and produce opaque INVALID_SIGNATURE).

**论据**:
1. `errors='replace'` substitutes `�` for invalid bytes → HMAC computed over corrupted body → silent signature mismatch
2. Legitimate DingTalk payloads sending non-UTF-8 (e.g. GBK card content) would fail with no operator-actionable error
3. `errors='strict'` + 400 + log surfaces the real failure mode

## §10 测试覆盖

| Test file | Count | Scope |
|-----------|-------|-------|
| `test_dingtalk_webhook_parser.py` | 24 | HMAC verify (3 happy + 4 fail), command parse (9 happy + 6 fail), enum |
| `test_dingtalk_webhook_service.py` | 13 | TRANSITIONED 2 + ALREADY_TERMINAL 3 + DEADLINE 2 + RESOLVE 2 + RACE 1 + 铁律 32 (2) + frozen |
| `test_dingtalk_webhook_endpoint.py` | 11 | 200 happy 2 + 401 sig 2 + 400 body 3 + 503 secret + 400 UTF8 + 422 headers 2 |

**Total**: 48 new tests (was 39 from 8a → 39+48 = 87 across S8). All PASS.

**Full S5/S6/S7/S8 + 8b cumulative regression**: 312/312 PASS post-reviewer-fix.

## §11 已知限制 (留 8c / follow-up)

1. broker_qmt sell wire post-CONFIRMED — 8c scope (5/5 红线 关键点, requires quantmind-redline-guardian)
2. Celery Beat sweep PENDING_CONFIRM expired → TIMEOUT_EXECUTED auto-sell — 8c scope
3. STAGED smoke integration test (L1 trigger → L4 plan → DingTalk push → user CONFIRM → broker sell) — 8c scope
4. Full DingTalk card-callback AES-CBC protocol — current MVP uses custom simple HMAC; production card callback may need card-callback AES adapter (separate sub-PR)
5. Operator UI to inspect pending execution_plans + re-issue buttons after expiry
6. Multi-secret rotation (key rollover without downtime) — deferred operational feature

## §12 关联

- ADR-027 (design SSOT for L4 STAGED + 反向决策权 + 跌停 fallback)
- ADR-056 (S8 8a implementation — state machine + DDL)
- LL-151 (S8 8b sediment + reviewer P1+P2 lesson)
- 铁律 1 (外部 API 必读官方文档 — DingTalk simple HMAC scheme; full AES card-callback deferred)
- 铁律 31 (Engine pure compute — webhook_parser 0 IO 0 DB)
- 铁律 32 (Service 不 commit — process_command verified by 2 explicit tests)
- 铁律 33 (fail-loud — sig/timestamp/parse failures raise + HTTP 4xx)
- 铁律 35 (Secrets via env — DINGTALK_WEBHOOK_SECRET empty → 503)
- 铁律 41 (timezone — cancel_deadline UTC + ±5min replay window absolute)
- V3 §7 + §S8 acceptance + ADR-027 §2.2 5 guardrails (sustained from 8a)
- PR #307 (`58258b9` initial + `95db073` reviewer-fix → squash `e68b00a` merged 2026-05-13)
