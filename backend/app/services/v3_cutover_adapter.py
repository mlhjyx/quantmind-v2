"""V3 Cutover Adapter — facade for run_paper_trading 调用 V3 PlatformRiskEngine.

Plan v0.4 §A IC-1a — surgical replace of legacy `check_circuit_breaker_sync` 2
call sites in `scripts/run_paper_trading.py` (line 285 signal_phase Step 1.6 +
line 453 execute_phase Step 5.9). Facade pattern:

  - run_paper_trading 不再直接 import `risk_control_service.check_circuit_breaker_sync`
  - 改 import 本模块 `check_v3_circuit_breaker` 作为 V3 cutover-era 调用入口
  - 函数 sigs + 返回 dict shape 1:1 与 legacy 兼容 → 下游 execute_rebalance / signal_phase
    不需 任何改动 (sustained ADR-022 反 silent overwrite + 最小 blast radius)

**IC-1a 诚实 scope** (Phase 0 finding-driven, sustained LL-169 lesson 2):

V3 `CircuitBreakerRule.evaluate()` 是 transition detector (line 156: `if new_level
== prev_level: return []`), 不是 level reader; 内部仍调 legacy `_check_cb_sync`
(circuit_breaker.py line 31 import) — V3 design choice, NOT Plan v0.4 oversight.
所以 IC-1a 的 "Replace" = **abstraction seam 层 replace** (orchestration 走 V3
adapter facade), 而 CB level 计算逻辑 internally 仍走 legacy `_check_cb_sync`.

**Future sub-PR sequence** (per Plan v0.4 §A IC-1 chunked 3 sub-PR baseline,
post-Phase-0 reshape):
  - IC-1a (本): facade abstraction seam + 2 call sites replace + fail-open scaffolding
  - IC-1c: L1 RealtimeRiskEngine production runner (XtQuantTickSubscriber +
    subscribe loop, 沿用 ADR-073 D3 留 cutover scope deferral)
  - IC-1b: 视 Phase 0 后 reshape 决议是否还需 (signal_service/signal_engine 实际
    不直接调 vol_regime — 走 regime_modifier.py 的 fallback path; 留 IC-2 处理)

**Failure mode**: V3 facade 内任何 exception → legacy `_check_cb_sync` 仍 run +
返 valid dict; V3 telemetry side-effects (future sub-PR 加) fail-open per V3
§0.5 design (P0 alert via DingTalk, 不 block trades). 沿用 user 决议 "Fail-open
+ P0 告警" (AskUserQuestion 1 round 2026-05-15).

返 dict shape (legacy `check_circuit_breaker_sync` 1:1 contract):
  `{"level": 0-4, "action": str, "reason": str, "position_multiplier": float,
    "recovery_info": str}`

关联铁律: 31 (Engine PURE — 本 adapter 在 App 层不在 Engine 层) / 33 (fail-loud —
          P0 alert on V3 path failure) / 42 (backend/** 走 PR)
关联 ADR: ADR-076 (横切层 closed prereq) / Plan v0.4 §A IC-1a / ADR-022 / ADR-072 D2
关联 LL: LL-098 X10 / LL-169 lesson 2 (carried-deferral 真值 fresh-verify) / LL-170
        候选 (V3-as-island detection + integrate-first-then-cutover 体例)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.services.risk_control_service import (
    check_circuit_breaker_sync as _legacy_cb_sync,
)

logger = logging.getLogger(__name__)


def check_v3_circuit_breaker(
    conn: Any,
    strategy_id: str,
    exec_date: date,
    initial_capital: float,
) -> dict[str, Any]:
    """V3 cutover-era CB check — facade for `risk_control_service.check_circuit_breaker_sync`.

    Drop-in replacement: same args + same return dict shape. Establishes the
    `v3_cutover_adapter` abstraction seam through which run_paper_trading will
    incrementally integrate V3 PlatformRiskEngine in future IC sub-PRs (IC-1c
    L1 production runner + IC-2 de-stub + IC-3 replay-as-gate validation).

    **IC-1a behavior** (intentionally minimal): pure pass-through to legacy
    `_check_cb_sync`. No V3 `PlatformRiskEngine.run()` invocation in IC-1a to
    avoid double-call of `_check_cb_sync` (V3 `CircuitBreakerRule.evaluate`
    internally calls the same `_check_cb_sync` — circuit_breaker.py:31 import).
    Future sub-PRs will add V3 telemetry side-effects with proper dedup
    coordination.

    **IC-1a value** (despite minimal behavior delta): establishes the import
    seam (run_paper_trading no longer directly imports legacy) + fail-open
    scaffolding ready for future V3 engine integration + observability log line.

    Args:
        conn: psycopg2 connection (caller manages transaction).
        strategy_id: Strategy UUID string.
        exec_date: Trading day for CB evaluation (Asia/Shanghai date).
        initial_capital: Strategy initial capital basis for L4 累计亏损 threshold.

    Returns:
        Legacy CB dict: `{level, action, reason, position_multiplier, recovery_info}`.
        Identical shape to `risk_control_service.check_circuit_breaker_sync`.

    Raises:
        Anything `_legacy_cb_sync` raises (DB errors etc) — fail-loud per 铁律 33,
        consistent with legacy behavior. V3 path additions in future sub-PRs
        will be wrapped in try/except → fail-open + P0 alert per V3 §0.5.
    """
    cb_dict = _legacy_cb_sync(
        conn=conn,
        strategy_id=strategy_id,
        exec_date=exec_date,
        initial_capital=initial_capital,
    )
    logger.info(
        "[v3-cutover] CB level=%s action=%s position_multiplier=%s "
        "(IC-1a facade — V3 engine telemetry deferred to future IC sub-PR)",
        cb_dict.get("level"),
        cb_dict.get("action", "n/a"),
        cb_dict.get("position_multiplier"),
    )
    return cb_dict
