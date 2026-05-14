"""DynamicThresholdEngine 5min Beat task — S7 production wire (post-audit fix).

V3 §6 + Plan §A S7 acceptance:
- crontab `*/5 9-14 * * 1-5` Asia/Shanghai (every 5min during trading hours)
- DynamicThresholdEngine.evaluate() → ThresholdCache.set_batch (TTL=300s, 与 Beat 同步)
- L1 RealtimeRiskEngine.set_threshold_cache(cache) 已经 wire (S5/S7 reverse loop, sub-PR 19)

Task body:
- Build MarketIndicators — index_return + limit_down_count wired via
  market_indicators_query (HC-2b3 G4 — index_daily 000300.SH + klines_daily 跌停家数);
  regime wired TB-2d (market_regime_log); northbound_flow still stub (留 TB-5 —
  no moneyflow_hsgt table in current DB schema)
- Build StockMetrics from holdings (stub via QMTClient.read_positions; ATR/beta wire deferred —
  current production qmt portfolio:current Hash 不含 ATR/beta, 加专门 metrics provider 是 follow-up sub-PR)
- engine.evaluate() → cache.set_batch (Redis 5min TTL fallback to in-memory per cache.py)

Sustains Plan §A S7 dependency: 前置 S5 ✅ / 后置 S5 reverse fed back loop ✅ (engine.set_threshold_cache).

Beat schedule per Plan §A:
- "risk-dynamic-threshold-5min" — `crontab(minute='*/5', hour='9-14', day_of_week='1-5')`
- Asia/Shanghai sustained per celery_app timezone config
- 反 hard collision: PT chain (16:25/16:30/09:31) + outbox 30s (different cadence) + daily_pipeline (post-15:00) + news cron `3,7,11,15,19,23 0` (hour offset 反)

铁律 17 not directly invoked (engine pure compute + cache write, 0 DataPipeline path).
铁律 31 sustained: engine module 0 IO, task layer is 真**事务边界 + Redis 写入**.
铁律 32 sustained: cache writes go through RedisThresholdCache.set_batch which uses
  pipeline.execute(), NOT psycopg2.commit().
铁律 33 sustained: fail-loud — task fail logger.exception + raise per Celery retry policy.
铁律 41 sustained: Asia/Shanghai timezone via celery_app.py.
铁律 44 X9: Beat schedule restart 必显式 — post-merge ops checklist `Servy restart
  QuantMind-CeleryBeat AND QuantMind-Celery` (沿用 LL-141 4-step sediment).

关联文档:
- docs/adr/ADR-055 (S7 DynamicThresholdEngine sediment + audit fix sub-PR addendum)
- backend/qm_platform/risk/dynamic_threshold/engine.py
- backend/qm_platform/risk/dynamic_threshold/cache.py
- backend/qm_platform/risk/realtime/engine.py:set_threshold_cache (S7→S5 wire)
- backend/app/tasks/beat_schedule.py (5min Beat entry)
"""

from __future__ import annotations

import logging
from typing import Any

from qm_platform.risk.dynamic_threshold.cache import (
    RedisThresholdCache,
    ThresholdCache,
)
from qm_platform.risk.dynamic_threshold.engine import (
    DynamicThresholdEngine,
    MarketIndicators,
    StockMetrics,
)

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.dynamic_threshold_tasks")

# Module-level singletons — survive across Beat invocations (engine is stateless,
# cache is per-process Redis client reference). 反 per-tick re-import overhead.
_engine: DynamicThresholdEngine | None = None
_cache: ThresholdCache | None = None
# Reviewer P2-6: one-time stub-active warning so operator sees in production
# logs that the remaining stub wire (per-stock metrics) is still deferred.
# HC-2b3 G4 wired market indicators (index_return / limit_down_count); stock
# metrics (ATR/beta/liquidity from holdings) still stub. Cleared once full wire lands.
_stub_warned: bool = False


def _get_engine() -> DynamicThresholdEngine:
    """Lazy singleton — pure compute engine reused across Beat ticks."""
    global _engine
    if _engine is None:
        _engine = DynamicThresholdEngine()
    return _engine


def _get_cache() -> ThresholdCache:
    """Lazy singleton — Redis-backed cache with in-memory fallback (cache.py lazy init).

    First call: try Redis; on failure, RedisThresholdCache._ensure_redis sets
    _connected=True (反 per-tick 2s blocking) and subsequent get/set become no-ops.
    To recover Redis: requires worker process restart (沿用 cache.py docstring).
    """
    global _cache
    if _cache is None:
        # RedisThresholdCache with built-in fallback (cache.py lazy init pattern)
        _cache = RedisThresholdCache()
    return _cache


def _build_market_indicators() -> MarketIndicators:
    """Build current market indicators snapshot.

    Wire status:
    - regime: TB-2d — latest market_regime_log row (V3 §5.3 + ADR-067 TB-2 closure)
    - index_return + limit_down_count: HC-2b3 G4 — index_daily 000300.SH 最新交易日
      pct_change + klines_daily 最新交易日跌停家数, via market_indicators_query
      (铁律 34 — 与 meta_monitor_service._collect_market_crisis 单源共用)
    - northbound_flow: still stub (留 TB-5 — no moneyflow_hsgt table in current DB schema)
    """
    index_return, limit_down_count = _fetch_market_crisis_indicators()
    return MarketIndicators(
        index_return=index_return,
        limit_down_count=limit_down_count,
        northbound_flow=None,
        regime=_fetch_latest_regime(),
    )


def _fetch_market_crisis_indicators() -> tuple[float | None, int | None]:
    """Query (index_return, limit_down_count) via shared market_indicators_query (HC-2b3 G4).

    Returns:
        (index_return, limit_down_count) — index_return as fraction (e.g. -0.07),
        limit_down_count as int. Either may be None when the underlying feed has
        no data (index_daily 无 000300.SH row / klines_daily 空).

    Fail-soft to (None, None) on any query/connection failure — sustained
    _fetch_latest_regime 体例: a transient DB hiccup degrades to CALM-default
    (None inputs → assess_market_state CALM) rather than crashing the 5min Beat
    tick. The meta_monitor Crisis collector takes the fail-loud path instead
    (psycopg2.Error propagate) — different caller, different error policy.

    Per-call connection — opens + closes per Beat tick (沿用 _fetch_latest_regime
    cost rationale: 5min cadence, PK-indexed SELECT <5ms typical).
    """
    try:
        from app.services.db import get_sync_conn  # noqa: PLC0415
        from app.services.risk.market_indicators_query import (  # noqa: PLC0415
            query_index_return,
            query_limit_down_count,
        )

        conn = get_sync_conn()
        try:
            return query_index_return(conn), query_limit_down_count(conn)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[dynamic-threshold-beat] failed to fetch market crisis indicators "
            "(index_daily / klines_daily query): %s; defaulting to (None, None) → CALM",
            e,
        )
        return None, None


def _fetch_latest_regime() -> str | None:
    """Query latest market_regime_log row → regime str (TB-2d L3 integration).

    Returns:
        "bull"/"bear"/"neutral"/"transitioning" lowercase OR None on:
        - query failure
        - 0 rows (no regime classification yet, e.g. fresh DB)
        - PG connection failure

    Sustained DynamicThresholdEngine.assess_market_state: `regime.lower() == "bear"`
    → STRESS state (V3 §6.1). Other labels OR None → CALM (sustained default).

    Per-call connection — opens + closes per Beat tick. Acceptable cost:
    - Beat cadence 5min (288 fires/day during trading hours)
    - market_regime_log writes only 3 times/day (9:00/14:30/16:00)
    - SELECT with PK index O(log N), <5ms typical
    """
    try:
        from app.services.db import get_sync_conn  # noqa: PLC0415

        conn = get_sync_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT regime FROM market_regime_log ORDER BY timestamp DESC LIMIT 1")
                row = cur.fetchone()
                if row is None or row[0] is None:
                    return None
                # Normalize to lowercase — DynamicThresholdEngine expects "bear"/"bull"/"neutral"
                # while DB stores "Bull"/"Bear"/"Neutral"/"Transitioning" per DDL CHECK.
                return str(row[0]).lower()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[dynamic-threshold-beat] failed to fetch latest regime "
            "(market_regime_log query): %s; defaulting to CALM via regime=None",
            e,
        )
        return None


def _build_stock_metrics() -> dict[str, StockMetrics]:
    """Build per-stock metrics for current positions.

    sub-PR S7-Beat-wire SCOPE: returns empty dict (engine evaluates market-level only,
    cache stores "" key globals). Production wire (real ATR / beta / liquidity from
    DB + holdings from QMTClient) deferred to S10 paper-mode 5d dry-run.

    Real wire path (follow-up sub-PR):
    - holdings: QMTClient().read_positions() → list of codes
    - ATR(20): SELECT close/atr_20 FROM factor_values WHERE symbol_id IN holdings
    - beta: SELECT beta_60 FROM factor_values WHERE symbol_id IN holdings
    - liquidity_percentile: dv_ttm rank pctile from daily_basic
    - industry: SELECT industry_sw1 FROM stock_basic WHERE symbol_id IN holdings
    """
    return {}


@celery_app.task(
    name="app.tasks.dynamic_threshold_tasks.compute_dynamic_thresholds",
    soft_time_limit=60,  # 1min soft — engine + cache write should be <1s typically
    time_limit=120,  # 2min hard kill
)
def compute_dynamic_thresholds() -> dict[str, Any]:
    """Compute dynamic thresholds + populate ThresholdCache (S7 5min Beat).

    Beat: crontab(minute='*/5', hour='9-14', day_of_week='1-5') Asia/Shanghai.

    Returns:
        {
            "ok": bool,
            "market_state": str (calm/stress/crisis),
            "rules_evaluated": int,
            "stocks_evaluated": int,
            "cache_writes": int (rules × stocks),
            "ttl": int (seconds),
        }

    Raises:
        Re-raises any unhandled exception from engine.evaluate() for Celery retry.
    """
    global _stub_warned
    if not _stub_warned:
        # Reviewer P2-6: surface remaining stub posture once at first invocation.
        # HC-2b3 G4 wired market indicators (index_return / limit_down_count);
        # _build_stock_metrics still returns {} → engine evaluates market-level only.
        logger.warning(
            "[dynamic-threshold-beat] partial STUB inputs active — market indicators "
            "wired (HC-2b3 G4) but _build_stock_metrics returns {}; per-stock "
            "ATR/beta/liquidity adjustment not applied. Wire real holdings/ATR/beta "
            "data path before S10 paper-mode 5d (LL-141)."
        )
        _stub_warned = True

    indicators = _build_market_indicators()
    stock_metrics = _build_stock_metrics()
    engine = _get_engine()
    cache = _get_cache()

    state = engine.assess_market_state(indicators)
    thresholds = engine.evaluate(indicators, stock_metrics=stock_metrics or None)

    # TTL = Beat cadence + 20% headroom (reviewer P1-1) — at TTL=300s exactly,
    # queue jitter / pipeline latency could let keys expire just before the next
    # Beat tick. 360s closes the expiry race; L1 still falls back to hardcoded
    # defaults if cache.get() returns None (反 stale threshold leak).
    ttl_seconds = 360
    # Reviewer P1-2: cache.set_batch now re-raises on Redis pipe.execute failure
    # (see cache.py docstring) → exception propagates here → Celery retry per
    # task_acks_late + task_reject_on_worker_lost. Redis-unavailable silent
    # fallback path (no Redis daemon at all) still no-ops without raise.
    cache.set_batch(thresholds, ttl=ttl_seconds)

    cache_writes = sum(len(stocks) for stocks in thresholds.values())
    result: dict[str, Any] = {
        "ok": True,
        "market_state": state.value,
        "rules_evaluated": len(thresholds),
        "stocks_evaluated": len(stock_metrics),
        "cache_writes": cache_writes,
        "ttl": ttl_seconds,
    }
    logger.info(
        "[dynamic-threshold-beat] state=%s rules=%d stocks=%d cache_writes=%d ttl=%ds",
        state.value,
        len(thresholds),
        len(stock_metrics),
        cache_writes,
        ttl_seconds,
    )
    return result
