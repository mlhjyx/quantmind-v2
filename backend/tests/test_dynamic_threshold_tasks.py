"""S7 audit fix sub-PR: Celery Beat wire smoke tests for compute_dynamic_thresholds.

Coverage (沿用 sub-PR 14 fundamental_ingest_tasks test 体例):
- Task is registered with celery_app under canonical name
- Task module import does not crash
- Task call with stub MarketIndicators + empty StockMetrics returns expected dict shape
- engine + cache singletons cache across calls (反 per-tick re-init)
- Beat schedule entry exists in CELERY_BEAT_SCHEDULE with correct cron + queue
- task is included in celery_app imports list (反 Beat dispatch → unregistered error)
- Cache set_batch invoked with correct TTL=300

关联铁律: 32 (caller 真**事务边界**) / 33 (fail-loud) / 44 X9 (Beat restart enforce)
关联 ADR: ADR-055 (S7 audit fix wire addendum)
关联 LL: LL-149 (S7 sediment)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.tasks import dynamic_threshold_tasks as dtt
from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE
from app.tasks.celery_app import celery_app

# §1 Task registration


def test_task_registered_in_celery_app() -> None:
    """compute_dynamic_thresholds is registered under canonical task name."""
    assert "app.tasks.dynamic_threshold_tasks.compute_dynamic_thresholds" in celery_app.tasks


def test_task_module_in_celery_imports() -> None:
    """celery_app.conf.imports contains the module so Beat dispatch succeeds."""
    imports = celery_app.conf.get("imports") or []
    assert "app.tasks.dynamic_threshold_tasks" in imports


# §2 Beat schedule entry


def test_beat_schedule_entry_exists() -> None:
    """risk-dynamic-threshold-5min entry exists in CELERY_BEAT_SCHEDULE."""
    assert "risk-dynamic-threshold-5min" in CELERY_BEAT_SCHEDULE


def test_beat_schedule_entry_correct_task_and_options() -> None:
    """Beat entry points to canonical task name, queue=default, expires=240s."""
    entry = CELERY_BEAT_SCHEDULE["risk-dynamic-threshold-5min"]
    assert entry["task"] == "app.tasks.dynamic_threshold_tasks.compute_dynamic_thresholds"
    assert entry["options"]["queue"] == "default"
    # 4min expire within 5min cycle (反 backlog across consecutive ticks)
    assert entry["options"]["expires"] == 240


def test_beat_schedule_entry_trading_hours_only() -> None:
    """Beat schedule cron is `*/5 9-14 * * 1-5` (trading hours, Mon-Fri)."""
    entry = CELERY_BEAT_SCHEDULE["risk-dynamic-threshold-5min"]
    schedule = entry["schedule"]
    # crontab stores expanded hour/dow fields as int sets
    assert schedule.hour == {9, 10, 11, 12, 13, 14}
    # Mon-Fri only (Celery: 1=Mon..5=Fri, 0=Sun, 6=Sat)
    assert schedule.day_of_week == {1, 2, 3, 4, 5}


# §3 Task body smoke


def test_compute_returns_calm_with_stub_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """With stub MarketIndicators (all None) the engine returns CALM state."""
    # Force a fresh in-memory cache for isolation
    from qm_platform.risk.dynamic_threshold.cache import InMemoryThresholdCache

    mem_cache = InMemoryThresholdCache()
    monkeypatch.setattr(dtt, "_cache", mem_cache)
    # Reset engine singleton to pick up clean state
    monkeypatch.setattr(dtt, "_engine", None)

    result = dtt.compute_dynamic_thresholds.run()

    assert result["ok"] is True
    assert result["market_state"] == "calm"
    assert result["rules_evaluated"] > 0
    assert result["stocks_evaluated"] == 0  # stub helper returns empty
    assert result["ttl"] == 300


def test_compute_populates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """compute_dynamic_thresholds writes thresholds into the cache singleton."""
    from qm_platform.risk.dynamic_threshold.cache import InMemoryThresholdCache

    mem_cache = InMemoryThresholdCache()
    monkeypatch.setattr(dtt, "_cache", mem_cache)
    monkeypatch.setattr(dtt, "_engine", None)

    dtt.compute_dynamic_thresholds.run()

    # Cache populated for each default rule under "" (market-level only key) since
    # stock_metrics is empty stub
    assert len(mem_cache) > 0  # at least 1 (rule_id, code) entry
    assert mem_cache.get("limit_down_detection", "") is not None


def test_singletons_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine + cache singletons survive across Beat ticks."""
    # Reset both singletons
    monkeypatch.setattr(dtt, "_engine", None)
    monkeypatch.setattr(dtt, "_cache", None)

    engine1 = dtt._get_engine()
    engine2 = dtt._get_engine()
    assert engine1 is engine2  # same instance, 反 per-tick re-init

    cache1 = dtt._get_cache()
    cache2 = dtt._get_cache()
    assert cache1 is cache2


def test_cache_set_batch_called_with_ttl_300(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache.set_batch is invoked with TTL=300s aligned with Beat cadence."""
    mock_cache = MagicMock()
    monkeypatch.setattr(dtt, "_cache", mock_cache)
    monkeypatch.setattr(dtt, "_engine", None)

    dtt.compute_dynamic_thresholds.run()

    mock_cache.set_batch.assert_called_once()
    kwargs = mock_cache.set_batch.call_args.kwargs
    args = mock_cache.set_batch.call_args.args
    # TTL passed as kwarg or as second positional
    if kwargs.get("ttl") is not None:
        assert kwargs["ttl"] == 300
    else:
        assert args[1] == 300


# §4 Build-helper unit tests (反 silent stub drift in follow-up sub-PR)


def test_build_market_indicators_stub_returns_all_none() -> None:
    """Current sub-PR scope: all fields None → engine returns CALM default."""
    ind = dtt._build_market_indicators()
    assert ind.index_return is None
    assert ind.limit_down_count is None
    assert ind.northbound_flow is None
    assert ind.regime is None


def test_build_stock_metrics_stub_returns_empty() -> None:
    """Current sub-PR scope: empty dict → engine evaluates market-level only."""
    sm = dtt._build_stock_metrics()
    assert sm == {}
