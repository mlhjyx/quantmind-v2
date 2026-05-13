# ADR-056: V3 §S8 8a L4 STAGED 状态机 + ExecutionPlan DDL 实施决议

**Status**: committed
**Date**: 2026-05-11 (code commit `dbf55c0`) / 2026-05-13 (sediment closure backfill)
**Type**: V3 Tier A S8 8a implementation sediment
**Parents**: ADR-027 (L4 STAGED + 反向决策权 + 跌停 fallback design SSOT) + ADR-022 (反 silent overwrite)
**Children**: future S8 8b (DingTalk webhook receiver) + S8 8c (broker_qmt sell wire + STAGED smoke)

## §1 背景

V3 §S8 acceptance line cites `STAGED PENDING_CONFIRM → CONFIRMED / CANCELLED / TIMEOUT_EXECUTED 状态机; cancel_deadline 严格 30min SLA`. ADR-027 design 锁定 3 ExecutionMode (OFF/STAGED/AUTO) + 5 cancel-deadline guardrails. 本 ADR sediments 8a implementation (state machine + DDL only; 8b webhook + 8c broker wire 留后续 sub-PR).

沿用 V3 governance batch closure cumulative pattern 体例 (ADR-054 sediments S5, ADR-055 sediments S7, 本 ADR sediments S8 8a).

## §2 Decision 1: ExecutionPlan dataclass 不可变 + transition() 创建新实例

**真值**: `@dataclass` ExecutionPlan 不用 `frozen=True` 但 state transitions 通过返回新实例实现 (`confirm` / `cancel` / `timeout_execute` / `mark_executed` / `mark_failed` 全返回 `ExecutionPlan`).

**论据**:
1. 不可变 semantics 反 mutation race condition (多 worker / 多 thread 共享同 plan_id 时)
2. transition() audit trail (旧 state 仍可保留, caller 选择是否 INSERT 新行 vs UPDATE)
3. Python `@dataclass(frozen=True)` 与 `field(default_factory=dict)` 在 risk_metrics 字段交互限制 — 选择软不可变 (transition 创建新实例) 而非硬 frozen

## §3 Decision 2: 状态机 valid_transition 静态查表

**真值**: `L4ExecutionPlanner.valid_transition(from_status, to_status)` 静态方法 + frozenset-based 邻接表:
- `PENDING_CONFIRM` → `{CONFIRMED, CANCELLED, TIMEOUT_EXECUTED, FAILED}`
- `CONFIRMED` → `{EXECUTED, FAILED}`
- `TIMEOUT_EXECUTED` → `{EXECUTED, FAILED}`
- `CANCELLED` / `EXECUTED` / `FAILED` → `frozenset()` (terminal states)

**论据**:
1. 静态查表 O(1) verify (反 if/elif chain 易漏 transition)
2. 显式 terminal states (CANCELLED/EXECUTED/FAILED 不可回滚 — 反 silent state regression)
3. Caller (Celery task / FastAPI endpoint) 在 INSERT/UPDATE 前可 pre-check, 反 invalid transition 进 DB

## §4 Decision 3: cancel_deadline ADR-027 §2.2 5 guardrails

**真值**: `_compute_cancel_deadline(mode, now)` 实现 ADR-027 §2.2 5 condition:
| condition | guard | floor |
|---|---|---|
| (a) Normal (9:30-11:30 / 13:00-14:55) | default 30min | — |
| (b) Auction (9:15-9:25) | adaptive min(30min, remaining_to_9:25) | 2min |
| (c) Late session (14:55-15:00) | adaptive min(30min, remaining_to_15:00) | 2min |
| (d) Cross-day | FINAL clamp to 14:55 if deadline > 14:55 | — |
| (e) User offline | TIMEOUT_EXECUTED default execute (caller responsibility) | — |

OFF mode: deadline = now (immediate, no window).

**论据**:
1. Auction window 短 → 30min 默认会跨过 9:25 进 continuous trading session → adaptive cap
2. Late session 短 → 30min 默认会跨过 15:00 → adaptive cap
3. Cross-day clamp 反 deadline 14:55 后 user 误操作 → 强制 final batch 截止
4. Floor 2min 反 cancel window 太短 user 反应不及 (auction/late edge case)

## §5 Decision 4: STAGED_ENABLED default=False (ADR-027 §2.1 短期)

**真值**: `L4ExecutionPlanner(staged_enabled=False)` default → `_resolve_mode()` 返 OFF → 所有 plan 立即 CONFIRMED → broker layer 立即执行 (反 silent STAGED activation pre-prerequisite verify).

**论据**:
1. ADR-027 §2.1 短期 default=OFF 锁定 (5 prerequisite 未满足前禁 STAGED 全自动反向决策)
2. 反 deepseek 类 agent 自决议 STAGED activation → silent risk delegation (沿用 LL-098 X10 反 forward-progress default)
3. 长期 5 prerequisite (V3 §15.4 paper-mode 5d / 元监控 0 P0 / Tier A ADR / 5 SLA / user 显式授权) 满足后 caller 显式 `staged_enabled=True` activation

## §6 Decision 5: TimescaleDB hypertable + 180d retention + 2 indexes

**真值**: `execution_plans` table 走 TimescaleDB hypertable (chunk 1 day) + retention policy 180d + 2 indexes:
- `idx_exec_plans_status_deadline` (status, cancel_deadline) WHERE status='PENDING_CONFIRM' — for 30min cancel sweep
- `idx_exec_plans_symbol_status` (symbol_id, status, created_at DESC) — for per-stock plan history query

**论据**:
1. Hypertable 反 single huge table query 漂移 (180d × 多 sprint × N symbols × M plans/day → 累积 row 量级)
2. PENDING_CONFIRM partial index 反 SELECT all-rows-then-filter (sweep job 每 5min 跑, 全表 scan 不可行)
3. 180d retention 沿用 risk_event_log + dynamic_threshold_adjustments 体例 (V3 §10 row 7)

## §7 测试覆盖

39 tests in `backend/tests/test_l4_execution_planner.py`:
- TestExecutionPlan (10) — dataclass + transition methods + is_expired
- TestL4PlannerGeneratePlan (10) — generate_plan + mode resolution + RuleResult non-actionable path
- TestCancelDeadline (8) — 5 ADR-027 §2.2 guardrails
- TestValidTransition (6) — state machine adjacency
- TestTimeoutCheck (3) — check_timeout static helper
- TestStagedFlow (2) — full lifecycle (PENDING_CONFIRM → CONFIRMED → EXECUTED 链)

**Unit coverage**: 39/39 PASS. Plan §A acceptance unit ≥95% 由本 39 test + 后续 8b/8c sub-PR test 累计验收.

## §8 已知限制 (留 8b/8c sub-PR)

1. broker layer wire 未做 (Plan §A 8c scope — broker_qmt sell 单 wire)
2. DingTalk webhook receiver 未做 (Plan §A 8b scope — CONFIRM/CANCEL 反向决策 inbound 路径)
3. Celery Beat sweep task 未做 (PENDING_CONFIRM expired 扫 + auto TIMEOUT_EXECUTED transition + caller invoke 8c broker wire)
4. ExecutionPlan repository (DB read/write helpers) 未做 (留 8b/8c sub-PR 决议: 走 service layer vs Celery task 内联)
5. AUTO mode 仅占位 (V3 §7.1 reserved Crisis regime; 5 prerequisite 满足 + L2 MarketRegimeService Tier B 实现后 activate)

## §9 关联

- ADR-027 (design SSOT for L4 STAGED + 反向决策权 + 跌停 fallback)
- ADR-022 (反 silent overwrite)
- LL-150 (本 implementation sediment + sprint closure gate 第 5 次实证教训)
- 铁律 31 (Engine pure compute, broker/DB by injection)
- 铁律 33 (fail-loud — `_resolve_mode` / `_compute_cancel_deadline` 不 silent fallback to OFF, 必显式 mode 决议)
- V3 §7.1 (ExecutionMode 3 档) + V3 §7.5 (ExecutionPlan schema) + V3 §10 (DDL retention)
- commit `dbf55c0` (S8 8a code + DDL + 39 tests, 2026-05-11)
- sediment cycle commit (本 ADR + LL-150 + REGISTRY + Plan §A S8 amend, 2026-05-13)
