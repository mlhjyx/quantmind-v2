"""DynamicThresholdEngine 5min Beat task — S7 production wire (post-audit fix).

V3 §6 + Plan §A S7 acceptance:
- crontab `*/5 9-14 * * 1-5` Asia/Shanghai (every 5min during trading hours)
- DynamicThresholdEngine.evaluate() → ThresholdCache.set_batch (TTL=300s, 与 Beat 同步)
- L1 RealtimeRiskEngine.set_threshold_cache(cache) 已经 wire (S5/S7 reverse loop, sub-PR 19)

Task body (minimal wire, sub-PR S7-Beat-wire scope):
- Build MarketIndicators (currently stub fields; real CSI300/index_return wire deferred to S10
  paper-mode 5d dry-run period per Plan §A S10 acceptance + LL-141 4-step ops sustainability)
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

    sub-PR S7-Beat-wire SCOPE: stub fields (all None → engine returns CALM default).
    Production wire (real CSI300 index_return + limit_down_count + northbound_flow +
    L2 regime) deferred to S10 paper-mode 5d dry-run per Plan §A S10 acceptance.

    Real wire path (follow-up sub-PR):
    - index_return: SELECT close/prev_close FROM klines_daily WHERE symbol_id='000300' LIMIT 2
    - limit_down_count: SELECT COUNT(*) FROM realtime_quotes WHERE pct_chg <= -9.8
    - northbound_flow: read northbound netflow API or DB cached value
    - regime: read latest L2 MarketRegime row (Tier B scope, currently stub)
    """
    return MarketIndicators(
        index_return=None,
        limit_down_count=None,
        northbound_flow=None,
        regime=None,
    )


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
    indicators = _build_market_indicators()
    stock_metrics = _build_stock_metrics()
    engine = _get_engine()
    cache = _get_cache()

    state = engine.assess_market_state(indicators)
    thresholds = engine.evaluate(indicators, stock_metrics=stock_metrics or None)

    # 5min TTL aligns with Beat cadence — stale cache returns None → rules fallback
    # to hardcoded defaults (反 stale threshold leak across Beat down period).
    ttl_seconds = 300
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
