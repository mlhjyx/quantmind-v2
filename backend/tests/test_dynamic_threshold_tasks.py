"""S7 audit fix sub-PR: Celery Beat wire smoke tests for compute_dynamic_thresholds.

Coverage (沿用 sub-PR 14 fundamental_ingest_tasks test 体例):
- Task is registered with celery_app under canonical name
- Task module import does not crash
- Task call with stub MarketIndicators + empty StockMetrics returns expected dict shape
- engine + cache singletons cache across calls (反 per-tick re-init)
- Beat schedule entry exists in CELERY_BEAT_SCHEDULE with correct cron + queue
- task is included in celery_app imports list (反 Beat dispatch → unregistered error)
- Cache set_batch invoked with correct TTL=360

HC-2b3 G4 update: _build_market_indicators de-stubbed (index_return / limit_down_count
now query index_daily / klines_daily via market_indicators_query). Tests that call
.run() monkeypatch _build_market_indicators with `_stub_market_indicators` so the smoke
tests stay DB-independent; the de-stub query path is tested in test_market_indicators_query.

关联铁律: 32 (caller 真**事务边界**) / 33 (fail-loud) / 44 X9 (Beat restart enforce)
关联 ADR: ADR-055 (S7 audit fix wire addendum)
关联 LL: LL-149 (S7 sediment)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from qm_platform.risk.dynamic_threshold.engine import MarketIndicators

from app.tasks import dynamic_threshold_tasks as dtt
from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE
from app.tasks.celery_app import celery_app


def _stub_market_indicators() -> MarketIndicators:
    """All-None MarketIndicators stub — keeps .run() smoke tests DB-independent.

    HC-2b3 G4 de-stubbed the real _build_market_indicators (now queries
    index_daily / klines_daily). Smoke tests monkeypatch this in so engine
    behaviour (CALM default on all-None) is exercised without a live DB.
    """
    return MarketIndicators(
        index_return=None, limit_down_count=None, northbound_flow=None, regime=None
    )


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
    # HC-2b3 G4: _build_market_indicators now hits the DB — stub it for the smoke test
    monkeypatch.setattr(dtt, "_build_market_indicators", _stub_market_indicators)

    result = dtt.compute_dynamic_thresholds.run()

    assert result["ok"] is True
    assert result["market_state"] == "calm"
    assert result["rules_evaluated"] > 0
    assert result["stocks_evaluated"] == 0  # stub helper returns empty
    assert result["ttl"] == 360  # P1-1 fix: Beat cadence (300s) + 20% headroom


def test_compute_populates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """compute_dynamic_thresholds writes thresholds into the cache singleton."""
    from qm_platform.risk.dynamic_threshold.cache import InMemoryThresholdCache

    mem_cache = InMemoryThresholdCache()
    monkeypatch.setattr(dtt, "_cache", mem_cache)
    monkeypatch.setattr(dtt, "_engine", None)
    monkeypatch.setattr(dtt, "_build_market_indicators", _stub_market_indicators)

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


def test_cache_set_batch_called_with_ttl_360(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache.set_batch invoked with TTL=360s (Beat cadence 300s + 20% headroom, P1-1)."""
    mock_cache = MagicMock()
    monkeypatch.setattr(dtt, "_cache", mock_cache)
    monkeypatch.setattr(dtt, "_engine", None)
    monkeypatch.setattr(dtt, "_build_market_indicators", _stub_market_indicators)

    dtt.compute_dynamic_thresholds.run()

    mock_cache.set_batch.assert_called_once()
    kwargs = mock_cache.set_batch.call_args.kwargs
    args = mock_cache.set_batch.call_args.args
    # TTL passed as kwarg or as second positional
    if kwargs.get("ttl") is not None:
        assert kwargs["ttl"] == 360
    else:
        assert args[1] == 360


def test_cache_set_batch_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1-2: cache.set_batch raise propagates to Celery (反 silent failure 铁律 33)."""
    mock_cache = MagicMock()
    mock_cache.set_batch.side_effect = RuntimeError("redis OOM")
    monkeypatch.setattr(dtt, "_cache", mock_cache)
    monkeypatch.setattr(dtt, "_engine", None)
    monkeypatch.setattr(dtt, "_build_market_indicators", _stub_market_indicators)

    with pytest.raises(RuntimeError, match="redis OOM"):
        dtt.compute_dynamic_thresholds.run()


def test_no_stub_warning_after_ic_2a_destub(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """IC-2a (2026-05-15) regression guard: partial-STUB warning is GONE.

    Pre-IC-2a behavior: `partial STUB inputs active` warning logged once on
    first Beat tick (P2-6 stub-warned flag). Post-IC-2a: _build_stock_metrics
    is fully wired (factor_values + daily_basic + stock_basic queries), so
    the warning + the `_stub_warned` module-level flag are removed.

    Asserting absence pins the de-stub closure — a future regression that
    re-introduces a stub posture would re-trigger this warning and fail this
    assertion.
    """
    from qm_platform.risk.dynamic_threshold.cache import InMemoryThresholdCache

    mem_cache = InMemoryThresholdCache()
    monkeypatch.setattr(dtt, "_cache", mem_cache)
    monkeypatch.setattr(dtt, "_engine", None)
    monkeypatch.setattr(dtt, "_build_market_indicators", _stub_market_indicators)
    # Stub holdings fetch to 0 positions (red-line paper-mode sustained)
    monkeypatch.setattr(dtt, "_build_stock_metrics", lambda: {})

    import logging

    with caplog.at_level(logging.WARNING, logger="celery.dynamic_threshold_tasks"):
        dtt.compute_dynamic_thresholds.run()
        dtt.compute_dynamic_thresholds.run()
        dtt.compute_dynamic_thresholds.run()

    stub_warnings = [r for r in caplog.records if "partial STUB inputs active" in r.message]
    assert len(stub_warnings) == 0, (
        "IC-2a regression: partial-STUB warning should not fire — _build_stock_metrics "
        "is fully wired. If this test fails, a stub posture was re-introduced."
    )
    # Module-level flag should also be gone (asserts symbol absence)
    assert not hasattr(dtt, "_stub_warned"), (
        "IC-2a regression: _stub_warned module-level flag should be removed."
    )


# ── IC-2a (2026-05-15): _build_stock_metrics de-stub tests ──


class _MockCursor:
    """Minimal DB cursor mock for _fetch_stock_metrics_from_db tests."""

    def __init__(self, fetchall_routes: dict[str, list[tuple]]) -> None:
        self._routes = fetchall_routes
        self._last_sql = ""

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._last_sql = sql

    def fetchall(self) -> list[tuple]:
        # Reviewer-fix (code-reviewer P2-A + python-reviewer P2-2, 2026-05-15):
        # route by MOST-SPECIFIC table name first. Original order had
        # "factor_values" first, but if future SQL refactor JOINs daily_basic
        # against factor_values, the substring "factor_values" would match
        # incorrectly. Disjoint table names (stock_basic / daily_basic) checked
        # before the more-broadly-referenced factor_values eliminates ordering
        # dependency on SQL text shape.
        sql = self._last_sql
        if "stock_basic" in sql:
            return self._routes.get("stock_basic", [])
        if "daily_basic" in sql or "PERCENT_RANK" in sql:
            return self._routes.get("daily_basic", [])
        if "factor_values" in sql:
            return self._routes.get("factor_values", [])
        return []

    def close(self) -> None:
        pass


class _MockConn:
    """Minimal DB conn mock that returns a _MockCursor per cursor() call."""

    def __init__(self, fetchall_routes: dict[str, list[tuple]] | None = None) -> None:
        self._routes = fetchall_routes or {}

    def cursor(self) -> _MockCursor:
        return _MockCursor(self._routes)

    def close(self) -> None:
        pass


def test_build_stock_metrics_zero_holdings_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 holdings (red-line paper-mode sustained) → empty dict, no DB calls.

    Monkeypatch target rationale (python-reviewer P2-1, 2026-05-15): patch
    the SOURCE MODULE (`app.core.qmt_client`), NOT the consumer module
    (`app.tasks.dynamic_threshold_tasks`). The lazy `from app.core.qmt_client
    import get_qmt_client` inside `_get_qmt_client_lazy` re-fetches the
    attribute from the source module on every call, so patching the source
    module's attribute correctly intercepts the call. Patching the consumer
    module would silently NOT intercept (lazy import binds a fresh local name).
    """
    from app.core import qmt_client as qc

    mock_client = MagicMock()
    mock_client.get_positions.return_value = {}
    monkeypatch.setattr(qc, "get_qmt_client", lambda: mock_client)

    result = dtt._build_stock_metrics()
    assert result == {}


def test_build_stock_metrics_qmt_failure_fails_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """QMT-down → fail-soft empty dict, market-only eval continues."""
    from app.core import qmt_client as qc

    def raising_client():
        raise ConnectionError("simulated QMT down")

    monkeypatch.setattr(qc, "get_qmt_client", raising_client)
    result = dtt._build_stock_metrics()
    assert result == {}


def test_fetch_stock_metrics_from_db_populates_all_three_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: factor_values + daily_basic + stock_basic all return data → full StockMetrics."""
    from app.services import db as db_mod

    codes = ["600519.SH", "000001.SZ"]
    mock_conn = _MockConn(
        fetchall_routes={
            "factor_values": [
                ("600519.SH", "atr_norm_20", 0.025),
                ("600519.SH", "beta_market_20", 1.15),
                ("000001.SZ", "atr_norm_20", 0.035),
                ("000001.SZ", "beta_market_20", 0.85),
            ],
            "daily_basic": [
                ("600519.SH", 0.95),
                ("000001.SZ", 0.40),
            ],
            "stock_basic": [
                ("600519.SH", "食品饮料"),
                ("000001.SZ", "银行"),
            ],
        }
    )
    monkeypatch.setattr(db_mod, "get_sync_conn", lambda: mock_conn)

    result = dtt._fetch_stock_metrics_from_db(codes)

    assert set(result.keys()) == set(codes)
    assert result["600519.SH"].atr_ratio == 0.025
    assert result["600519.SH"].beta == 1.15
    assert result["600519.SH"].liquidity_percentile == 0.95
    assert result["600519.SH"].industry == "食品饮料"
    assert result["000001.SZ"].atr_ratio == 0.035
    assert result["000001.SZ"].beta == 0.85
    assert result["000001.SZ"].liquidity_percentile == 0.40
    assert result["000001.SZ"].industry == "银行"


def test_fetch_stock_metrics_partial_source_missing_returns_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """factor_values empty → atr/beta=None; daily_basic + stock_basic still populate."""
    from app.services import db as db_mod

    codes = ["600519.SH"]
    mock_conn = _MockConn(
        fetchall_routes={
            "factor_values": [],  # no data
            "daily_basic": [("600519.SH", 0.95)],
            "stock_basic": [("600519.SH", "食品饮料")],
        }
    )
    monkeypatch.setattr(db_mod, "get_sync_conn", lambda: mock_conn)

    result = dtt._fetch_stock_metrics_from_db(codes)
    m = result["600519.SH"]
    assert m.atr_ratio is None
    assert m.beta is None
    assert m.liquidity_percentile == 0.95
    assert m.industry == "食品饮料"


def test_fetch_stock_metrics_db_connection_failure_fails_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PG connection failure → code-only StockMetrics (all fields None), 0 raise."""
    from app.services import db as db_mod

    def raising_conn():
        raise ConnectionError("simulated PG down")

    monkeypatch.setattr(db_mod, "get_sync_conn", raising_conn)
    result = dtt._fetch_stock_metrics_from_db(["600519.SH"])
    assert "600519.SH" in result
    m = result["600519.SH"]
    assert m.code == "600519.SH"
    assert m.atr_ratio is None
    assert m.beta is None
    assert m.liquidity_percentile is None
    assert m.industry is None


def test_build_stock_metrics_full_path_with_holdings(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: holdings + factor_values + daily_basic + stock_basic all wired."""
    from app.core import qmt_client as qc
    from app.services import db as db_mod

    mock_client = MagicMock()
    mock_client.get_positions.return_value = {"600519.SH": 100}
    monkeypatch.setattr(qc, "get_qmt_client", lambda: mock_client)

    mock_conn = _MockConn(
        fetchall_routes={
            "factor_values": [
                ("600519.SH", "atr_norm_20", 0.025),
                ("600519.SH", "beta_market_20", 1.15),
            ],
            "daily_basic": [("600519.SH", 0.95)],
            "stock_basic": [("600519.SH", "食品饮料")],
        }
    )
    monkeypatch.setattr(db_mod, "get_sync_conn", lambda: mock_conn)

    result = dtt._build_stock_metrics()
    assert "600519.SH" in result
    m = result["600519.SH"]
    assert m.atr_ratio == 0.025
    assert m.beta == 1.15
    assert m.liquidity_percentile == 0.95
    assert m.industry == "食品饮料"


# §4 Build-helper unit tests


def test_build_market_indicators_wires_market_crisis_indicators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HC-2b3 G4: _build_market_indicators wires index_return + limit_down_count
    from _fetch_market_crisis_indicators; regime from _fetch_latest_regime;
    northbound_flow stays stub (None)."""
    monkeypatch.setattr(dtt, "_fetch_market_crisis_indicators", lambda: (-0.06, 312))
    monkeypatch.setattr(dtt, "_fetch_latest_regime", lambda: "bear")

    ind = dtt._build_market_indicators()
    assert ind.index_return == -0.06
    assert ind.limit_down_count == 312
    assert ind.regime == "bear"
    assert ind.northbound_flow is None  # 留 TB-5 (no moneyflow_hsgt table)


def test_fetch_market_crisis_indicators_fail_soft_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HC-2b3 G4: _fetch_market_crisis_indicators fail-softs to (None, None) on
    DB error (沿用 _fetch_latest_regime 体例 — degrades to CALM, 反 crash Beat tick)."""

    def _boom() -> object:
        raise RuntimeError("simulated DB connection failure")

    # get_sync_conn is imported inside the function from app.services.db — patch source
    monkeypatch.setattr("app.services.db.get_sync_conn", _boom)

    index_return, limit_down_count = dtt._fetch_market_crisis_indicators()
    assert index_return is None
    assert limit_down_count is None


def test_build_stock_metrics_stub_returns_empty() -> None:
    """Current sub-PR scope: empty dict → engine evaluates market-level only."""
    sm = dtt._build_stock_metrics()
    assert sm == {}
