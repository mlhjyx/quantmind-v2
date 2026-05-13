"""V3 §5.3 MarketRegime Celery Beat task — TB-2c sub-PR (3 daily schedules wire).

V3 §5.3 line 664 cadence: 每日 9:00 + 14:30 + 16:00 (3 次更新, Asia/Shanghai trading days).

Task body:
  1. Fetch MarketIndicators via IndicatorsProvider (TB-2c stub returns all-None)
  2. MarketRegimeService.classify(indicators) → 3 V4-Pro LLM calls (Bull/Bear/Judge)
  3. persist_market_regime(conn, regime) → market_regime_log INSERT
  4. conn.commit() (caller manages transaction per 铁律 32)

3-layer pattern sustained (反 hidden coupling):
  - qm_platform/risk/regime/ = Engine PURE side (provider + agents + repository)
  - app/services/risk/market_regime_service.py = Application orchestration
  - 本 module = Beat schedule dispatch + DB conn lifecycle

Beat schedule per V3 §5.3 (beat_schedule.py amend):
  - "risk-market-regime-0900" — crontab(hour=9, minute=0, day_of_week='1-5')
  - "risk-market-regime-1430" — crontab(hour=14, minute=30, day_of_week='1-5')
  - "risk-market-regime-1600" — crontab(hour=16, minute=0, day_of_week='1-5')

Schedule collision risk (反 hard collision, sustained dynamic_threshold_tasks 体例):
  - 09:00 — clean (no existing entry)
  - 14:30 — risk-l4-sweep-1min fires every minute incl 14:30 + DEPRECATED risk-daily-check (paused);
    Beat sequential dispatch + --pool=solo Windows tolerates sub-second queue
  - 16:00 — fundamental-context-daily-1600 minute=0 collision; sequential queue tolerated
    (independent V4-Pro tasks, ~3-5s combined)

铁律 17 not directly invoked (single-row INSERT per LL-066 例外, repository.py 已 wire).
铁律 31 sustained: qm_platform/risk/regime engine PURE; 本 task = Application 事务边界.
铁律 32 sustained: 本 task **explicit conn.commit()** after persist_market_regime (caller responsibility).
铁律 33 sustained: fail-loud — MarketRegimeError / DB error propagate per Celery retry.
铁律 41 sustained: Asia/Shanghai timezone via celery_app.py.
铁律 44 X9 sustained: post-merge ops `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
  per docs/runbook/cc_automation/v3_tb_2c_market_regime_beat_wire.md (LL-141 4-step sediment).

关联文档:
- docs/adr/ADR-036 (BULL/BEAR/JUDGE V4-Pro mapping sustained)
- docs/adr/ADR-064 (Plan v0.2 D2 Tier B Bull/Bear regime cadence sustained)
- backend/qm_platform/risk/regime/agents.py (BullAgent / BearAgent / RegimeJudge)
- backend/app/services/risk/market_regime_service.py (MarketRegimeService.classify)
- backend/qm_platform/risk/regime/repository.py (persist_market_regime)
- backend/qm_platform/risk/regime/indicators_provider.py (IndicatorsProvider Protocol)
- backend/app/tasks/beat_schedule.py (3 Beat entries)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qm_platform.risk.regime.indicators_provider import StubIndicatorsProvider
from qm_platform.risk.regime.repository import persist_market_regime

from app.services.risk.market_regime_service import MarketRegimeService
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from qm_platform.risk.regime.indicators_provider import IndicatorsProvider

logger = logging.getLogger("celery.market_regime_tasks")

# Module-level singletons — survive across Beat invocations (router + service
# initialization is non-trivial; reuse across 3 daily fires).
_service: MarketRegimeService | None = None
_provider: IndicatorsProvider | None = None


def _get_service() -> MarketRegimeService:
    """Lazy singleton — MarketRegimeService with shared LiteLLMRouter."""
    global _service
    if _service is None:
        from backend.qm_platform.llm import get_llm_router  # noqa: PLC0415

        router = get_llm_router()
        _service = MarketRegimeService(router=router)
    return _service


def _get_provider() -> IndicatorsProvider:
    """Lazy singleton — IndicatorsProvider (TB-2c stub; TB-2d/5 default real wire)."""
    global _provider
    if _provider is None:
        _provider = StubIndicatorsProvider()
    return _provider


@celery_app.task(
    name="app.tasks.market_regime_tasks.classify_market_regime",
    soft_time_limit=60,  # 1min soft — 3 V4-Pro LLM calls typically 5-15s
    time_limit=120,  # 2min hard kill (反 hung LLM)
)
def classify_market_regime(decision_id: str | None = None) -> dict[str, Any]:
    """Run V3 §5.3 Bull/Bear/Judge V4-Pro × 3 debate + persist to market_regime_log.

    Beat schedules per V3 §5.3 line 664:
        crontab(hour=9, minute=0, day_of_week='1-5')   # 09:00 pre-market probe
        crontab(hour=14, minute=30, day_of_week='1-5') # 14:30 mid-session
        crontab(hour=16, minute=0, day_of_week='1-5')  # 16:00 post-close

    Args:
        decision_id: optional caller-traceable ID. If None, auto-generated from
            UTC timestamp at task start (e.g. "market-regime-2026-05-14T09:00:00").

    Returns:
        {"ok": bool, "regime_id": int, "regime": str, "confidence": float,
         "cost_usd": float, "decision_id": str}.

    Raises:
        Re-raises MarketRegimeError / DB error per Celery retry policy
        (task_acks_late=True + task_reject_on_worker_lost=True per celery_app).
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    if decision_id is None:
        decision_id = f"market-regime-{datetime.now(UTC).isoformat(timespec='seconds')}"

    logger.info(
        "[market-regime-beat] classify start: decision_id=%s",
        decision_id,
    )

    provider = _get_provider()
    service = _get_service()

    indicators = provider.fetch()
    regime = service.classify(indicators, decision_id=decision_id)

    # Persist + commit (铁律 32 — task is caller / transaction owner).
    from app.services.db import get_sync_conn  # noqa: PLC0415

    conn = get_sync_conn()
    try:
        regime_id = persist_market_regime(conn, regime)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    result: dict[str, Any] = {
        "ok": True,
        "regime_id": regime_id,
        "regime": regime.regime.value,
        "confidence": regime.confidence,
        "cost_usd": regime.cost_usd,
        "decision_id": decision_id,
    }
    logger.info(
        "[market-regime-beat] classify result: regime_id=%d regime=%s "
        "confidence=%.4f cost_usd=%.4f decision_id=%s",
        regime_id,
        regime.regime.value,
        regime.confidence,
        regime.cost_usd,
        decision_id,
    )
    return result
