"""Tests for `scripts.realtime_risk_engine_service` (IC-1c WU-2).

V3 PT Cutover Plan v0.4 §A IC-1c WU-2 — L1 RealtimeRiskEngine production
runner service. Tests cover lifecycle, tick callback flow, RiskContext build,
heartbeat write, dispatch via stream, and T0-16 fail-loud escalation.

Test strategy:
  - DI all heavy deps (xtquant subscriber / Redis / QMTClient / stream bus)
  - 0 real xtquant import (subscriber is mocked via injection)
  - 0 real Redis connection (FakeRedis or MagicMock injection)
  - Unit-level coverage of: context build / heartbeat write / dispatch /
    T0-16 escalation / position refresh / lifecycle (start/stop)
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 项目路径设置 (沿用 service 文件体例 — backend/scripts 入口)
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "backend"))
sys.path.insert(0, str(_project_root / "scripts"))

# Import under test (must come after path manipulation)
from qm_platform.risk.dynamic_threshold.cache import (  # noqa: E402
    InMemoryThresholdCache,
)
from qm_platform.risk.interface import RuleResult  # noqa: E402
from qm_platform.risk.realtime import RealtimeRiskEngine  # noqa: E402

from scripts.realtime_risk_engine_service import (  # noqa: E402
    CACHE_L1_HEARTBEAT,
    CACHE_L1_HEARTBEAT_TTL_SEC,
    STREAM_RISK_L1_TRIGGERED,
    RealtimeRiskEngineService,
)

# ---------- Test fixtures ----------


def _make_mock_qmt_client(
    positions: dict[str, int] | None = None,
    nav: dict | None = None,
) -> MagicMock:
    """Build a MagicMock QMTClient with deterministic position/nav returns."""
    client = MagicMock()
    client.get_positions.return_value = positions or {}
    client.get_nav.return_value = nav or {"cash": 0.0, "total_value": 0.0}
    return client


def _make_service(
    positions: dict[str, int] | None = None,
    nav: dict | None = None,
    engine: RealtimeRiskEngine | None = None,
) -> RealtimeRiskEngineService:
    """Build a service with all heavy deps mocked for unit testing."""
    return RealtimeRiskEngineService(
        strategy_id="test-strategy-uuid",
        qmt_client=_make_mock_qmt_client(positions=positions, nav=nav),
        subscriber=MagicMock(),
        engine=engine,
        threshold_cache=InMemoryThresholdCache(),
        redis_client=MagicMock(),
        stream_bus=MagicMock(),
    )


# ---------- TestRefreshPositions ----------


class TestRefreshPositions:
    """Position refresh from QMT cache + T0-16 fail-loud escalation."""

    def test_refresh_success_populates_state(self):
        """Successful refresh populates _positions and _portfolio_nav."""
        service = _make_service(
            positions={"600519.SH": 100, "000001.SZ": 200},
            nav={"cash": 50_000.0, "total_value": 1_000_000.0},
        )
        ok = service._refresh_positions()
        assert ok is True
        assert service._positions == {"600519.SH": 100, "000001.SZ": 200}
        assert service._portfolio_nav == 1_000_000.0
        assert service._consecutive_sync_failures == 0

    def test_refresh_failure_increments_counter(self):
        """QMTClient.get_positions raises → counter increments, returns False."""
        service = _make_service()
        service._qmt_client.get_positions.side_effect = RuntimeError("redis-down")
        ok = service._refresh_positions()
        assert ok is False
        assert service._consecutive_sync_failures == 1

    def test_t0_16_escalation_fires_at_threshold(self):
        """5 consecutive failures triggers DingTalk P0 alert + fail_loud_alerted flag."""
        service = _make_service()
        service._qmt_client.get_positions.side_effect = RuntimeError("sustained-failure")
        # Patch _escalate to spy
        service._escalate_consecutive_failures = MagicMock()
        for _ in range(5):
            service._refresh_positions()
        service._escalate_consecutive_failures.assert_called_once()
        assert service._fail_loud_alerted is True

    def test_t0_16_escalation_only_once_per_episode(self):
        """Sustained failure past threshold escalates exactly once (not per-tick spam)."""
        service = _make_service()
        service._qmt_client.get_positions.side_effect = RuntimeError("sustained")
        service._escalate_consecutive_failures = MagicMock()
        for _ in range(10):  # 10 failures, threshold is 5
            service._refresh_positions()
        assert service._escalate_consecutive_failures.call_count == 1

    def test_t0_16_recovery_resets_counter_and_flag(self):
        """First success after failure episode resets counter + alert flag."""
        service = _make_service(positions={"600519.SH": 100})
        # Simulate failure → escalation → recovery
        service._qmt_client.get_positions.side_effect = RuntimeError("transient")
        service._escalate_consecutive_failures = MagicMock()
        for _ in range(5):
            service._refresh_positions()
        assert service._fail_loud_alerted is True
        # Recovery
        service._qmt_client.get_positions.side_effect = None
        service._qmt_client.get_positions.return_value = {"600519.SH": 100}
        ok = service._refresh_positions()
        assert ok is True
        assert service._consecutive_sync_failures == 0
        assert service._fail_loud_alerted is False


# ---------- TestRiskContextBuild ----------


class TestRiskContextBuild:
    """RiskContext construction from QMT positions + tick data."""

    def test_context_has_strategy_and_mode(self):
        """RiskContext carries strategy_id + execution_mode from settings."""
        service = _make_service(positions={"600519.SH": 100}, nav={"total_value": 500_000.0})
        service._refresh_positions()
        ctx = service._build_realtime_context(
            ticks={"600519.SH": {"price": 1700.0, "prev_close": 1750.0}}
        )
        assert ctx.strategy_id == "test-strategy-uuid"
        assert ctx.execution_mode in ("paper", "live")
        assert ctx.portfolio_nav == 500_000.0
        assert ctx.timestamp.tzinfo == UTC  # 铁律 41 tz-aware

    def test_context_positions_use_tick_price(self):
        """Position.current_price comes from tick data when available."""
        service = _make_service(positions={"600519.SH": 100}, nav={"total_value": 200_000.0})
        service._refresh_positions()
        ctx = service._build_realtime_context(ticks={"600519.SH": {"price": 1700.0}})
        assert len(ctx.positions) == 1
        pos = ctx.positions[0]
        assert pos.code == "600519.SH"
        assert pos.shares == 100
        assert pos.current_price == 1700.0
        # WU-2 minimal scope: entry/peak/entry_date not available from QMT cache
        assert pos.entry_price == 0.0
        assert pos.peak_price == 0.0
        assert pos.entry_date is None

    def test_context_realtime_dict_populated(self):
        """Tick fields are passed through to RiskContext.realtime."""
        service = _make_service(positions={"600519.SH": 100}, nav={"total_value": 200_000.0})
        service._refresh_positions()
        tick = {
            "price": 1700.0,
            "prev_close": 1750.0,
            "open_price": 1745.0,
            "day_volume": 50_000,
        }
        ctx = service._build_realtime_context(ticks={"600519.SH": tick})
        assert ctx.realtime is not None
        assert ctx.realtime["600519.SH"] == tick

    def test_context_with_empty_positions(self):
        """0 positions (sustained 红线 paper-mode) → empty positions tuple."""
        service = _make_service()
        ctx = service._build_realtime_context(ticks={})
        assert ctx.positions == ()
        assert ctx.realtime == {}


# ---------- TestHeartbeatWrite ----------


class TestHeartbeatWrite:
    """L1 heartbeat SETEX write — WU-3 alert rule activation prerequisite."""

    def test_heartbeat_write_uses_setex_with_correct_ttl(self):
        """_write_heartbeat calls Redis SETEX with documented key + TTL."""
        service = _make_service()
        now = datetime.now(UTC)
        service._write_heartbeat(now)
        service._redis.setex.assert_called_once_with(
            CACHE_L1_HEARTBEAT, CACHE_L1_HEARTBEAT_TTL_SEC, now.isoformat()
        )

    def test_heartbeat_write_redis_failure_swallowed(self):
        """Redis SETEX raise → silent (best-effort, next tick retries)."""
        service = _make_service()
        service._redis.setex.side_effect = RuntimeError("redis-blip")
        # Must not raise
        service._write_heartbeat(datetime.now(UTC))


# ---------- TestDispatchTriggered ----------


class TestDispatchTriggered:
    """Dispatch L1 RuleResult — log + Redis stream (NO broker call)."""

    def _make_result(
        self, rule_id: str = "limit_down_detection", code: str = "600519.SH"
    ) -> RuleResult:
        return RuleResult(
            rule_id=rule_id,
            code=code,
            shares=100,
            reason="test trigger reason",
            metrics={"pct_change": -0.099},
        )

    def test_dispatch_publishes_to_l1_stream(self):
        """Triggered RuleResult publishes to STREAM_RISK_L1_TRIGGERED via stream_bus."""
        service = _make_service()
        result = self._make_result()
        service._dispatch_triggered([result])
        service._bus.publish_sync.assert_called_once()
        call_args = service._bus.publish_sync.call_args
        assert call_args.args[0] == STREAM_RISK_L1_TRIGGERED
        payload = call_args.args[1]
        assert payload["rule_id"] == "limit_down_detection"
        assert payload["code"] == "600519.SH"
        # metrics serialized as JSON for stream compatibility
        assert json.loads(payload["metrics"]) == {"pct_change": -0.099}
        assert call_args.kwargs["source"] == "realtime_risk_engine_service"

    def test_dispatch_publishes_one_per_result(self):
        """Each triggered result publishes exactly one stream message.

        Reviewer fix (both reviewers P2-1, 2026-05-15): `_trigger_count`
        is no longer mutated by `_dispatch_triggered` — it lives in `_on_tick`
        under the lock so both counters are atomic. This test verifies the
        publish path independently.
        """
        service = _make_service()
        results = [self._make_result(rule_id=f"rule_{i}") for i in range(3)]
        service._dispatch_triggered(results)
        assert service._bus.publish_sync.call_count == 3

    def test_dispatch_stream_failure_swallowed(self):
        """Stream publish raise → log warning, no propagation (sustained tick eval)."""
        service = _make_service()
        service._bus.publish_sync.side_effect = RuntimeError("stream-down")
        # Must not raise
        service._dispatch_triggered([self._make_result()])

    def test_dispatch_zero_broker_calls(self):
        """红线 sustained: WU-2 dispatch path makes 0 broker calls.

        Reviewer fix (code-reviewer P2-4 + python-reviewer P2-3, 2026-05-15):
        replaced the fragile `dir(service)` substring scan with explicit
        mock-call assertions on QMTClient broker-mutation methods + a stream
        name invariant check. The dir-scan proved only "no broker-named
        attribute" — not "0 broker calls". The new assertions prove that
        QMTClient.place_order / cancel_order are never invoked AND the
        publish_sync target stream contains 'risk' (not 'execution').
        """
        service = _make_service()
        service._dispatch_triggered([self._make_result()])
        # QMTClient must not receive ANY order placement / cancellation call
        service._qmt_client.place_order.assert_not_called()
        service._qmt_client.cancel_order.assert_not_called()
        # Stream publish target must be the L1 risk stream, not an execution stream
        call_args = service._bus.publish_sync.call_args
        assert call_args is not None
        stream_name = call_args.args[0]
        assert "risk" in stream_name, (
            f"Unexpected stream target {stream_name!r} — must be 'risk' family"
        )
        assert "execution" not in stream_name, (
            f"Forbidden execution stream target {stream_name!r} in dispatch path"
        )


# ---------- TestOnTickFlow ----------


class TestOnTickFlow:
    """End-to-end tick callback flow with real RealtimeRiskEngine."""

    def test_on_tick_writes_heartbeat_and_increments_counter(self):
        """Single tick callback writes heartbeat + bumps tick_count."""
        engine = RealtimeRiskEngine()  # 0 rules registered
        service = _make_service(
            positions={"600519.SH": 100},
            nav={"total_value": 200_000.0},
            engine=engine,
        )
        service._engine = engine
        service._running = True
        service._refresh_positions()

        service._on_tick({"600519.SH": {"price": 1700.0, "prev_close": 1750.0}})

        assert service._tick_count == 1
        service._redis.setex.assert_called_once()

    def test_on_tick_skips_when_not_running(self):
        """_running=False short-circuits the callback (graceful shutdown safety)."""
        service = _make_service()
        service._running = False
        service._on_tick({"600519.SH": {"price": 1700.0}})
        # No heartbeat written, no tick counted
        service._redis.setex.assert_not_called()
        assert service._tick_count == 0

    def test_on_tick_skips_when_engine_none(self):
        """_engine=None (pre-start) short-circuits (safety vs race)."""
        service = _make_service()
        service._running = True
        service._engine = None
        service._on_tick({"600519.SH": {"price": 1700.0}})
        # No heartbeat, no tick counted
        service._redis.setex.assert_not_called()
        assert service._tick_count == 0

    def test_on_tick_internal_exception_swallowed_with_log(self):
        """Build/eval exception is caught by service-internal guard (reviewer P2-2).

        Verifies the service does not rely on subscriber.py:145 external catch
        for its own correctness — a `_build_realtime_context` or `engine.on_tick`
        crash is logged with full stack trace and the callback returns cleanly.
        """
        service = _make_service(positions={"600519.SH": 100})
        service._refresh_positions()
        # Mock engine that raises on on_tick
        mock_engine = MagicMock()
        mock_engine.on_tick.side_effect = RuntimeError("engine crashed")
        service._engine = mock_engine
        service._running = True
        # Must not raise (service-internal try/except guard)
        service._on_tick({"600519.SH": {"price": 1700.0}})

    def test_on_tick_increments_trigger_count_atomically(self):
        """`_trigger_count` accumulates under lock in `_on_tick` (reviewer P2-1).

        After WU-2 reviewer-fix: counter is mutated in `_on_tick` (not in
        `_dispatch_triggered`) so both `_tick_count` and `_trigger_count` are
        consistent within the same lock acquisition.
        """
        # Build a mock engine that returns 2 triggered RuleResults
        mock_engine = MagicMock()
        mock_engine.on_tick.return_value = [
            RuleResult(
                rule_id="limit_down_detection",
                code="600519.SH",
                shares=100,
                reason="test",
                metrics={"pct_change": -0.099},
            ),
            RuleResult(
                rule_id="near_limit_down",
                code="600519.SH",
                shares=100,
                reason="test",
                metrics={"pct_change": -0.08},
            ),
        ]
        service = _make_service(positions={"600519.SH": 100})
        service._engine = mock_engine
        service._running = True
        service._refresh_positions()

        service._on_tick({"600519.SH": {"price": 1700.0}})

        # 1 tick, 2 triggers — atomically accumulated
        assert service._tick_count == 1
        assert service._trigger_count == 2
        assert service._bus.publish_sync.call_count == 2


# ---------- TestBuildEngine ----------


class TestBuildEngine:
    """Engine construction — rule_registry SSOT + threshold cache wiring."""

    def test_build_engine_registers_10_rules(self):
        """_build_engine registers all 10 rules via rule_registry SSOT (WU-1)."""
        service = _make_service()
        engine = service._build_engine()
        total = sum(len(rules) for rules in engine.registered_rules.values())
        assert total == 10  # ADR-029 §2.2 canonical count

    def test_build_engine_wires_threshold_cache(self):
        """_build_engine calls set_threshold_cache with injected cache."""
        service = _make_service()
        engine = service._build_engine()
        # _threshold_cache must be set on the engine (S7→S5 wire)
        assert engine._threshold_cache is service._threshold_cache


# ---------- TestShutdown ----------


class TestShutdown:
    """Signal handler graceful shutdown."""

    def test_shutdown_flips_running_flag(self):
        """SIGTERM/SIGINT handler sets _running=False."""
        service = _make_service()
        service._running = True
        service._handle_shutdown(15, None)  # SIGTERM=15
        assert service._running is False


# ---------- TestStartLifecycle ----------


class TestStartLifecycle:
    """`start()` lifecycle — cleanup invariants on success + failure paths.

    Reviewer fix (code-reviewer P1-2 + P2-3, 2026-05-15): verify that
    `_cleanup` is invoked even when `subscriber.start()` raises mid-startup,
    so the subscriber + engine + redis client never leak.
    """

    def test_start_subscriber_raise_calls_cleanup(self):
        """subscriber.start() RuntimeError → cleanup runs, exception propagates."""
        service = _make_service(
            positions={"600519.SH": 100},
            nav={"total_value": 200_000.0},
        )
        # Make subscriber.start() raise — simulates xtquant disconnect / already-running
        service._subscriber.start.side_effect = RuntimeError("xtquant subscribe failed")

        with pytest.raises(RuntimeError, match="xtquant subscribe failed"):
            service.start()

        # P1-2 fix verified: _cleanup must have been called even though
        # subscriber.start() raised mid-startup. The try/finally now wraps
        # the whole startup sequence (engine build + subscriber start +
        # sync loop), so subscriber.stop() runs in the finally clause.
        service._subscriber.stop.assert_called_once()

    def test_start_sync_loop_returns_calls_cleanup(self):
        """Normal sync-loop exit (graceful shutdown) → cleanup runs."""
        service = _make_service(
            positions={"600519.SH": 100},
            nav={"total_value": 200_000.0},
        )
        # Mock _run_sync_loop to exit immediately
        service._run_sync_loop = MagicMock()

        service.start()

        service._subscriber.stop.assert_called_once()
        service._run_sync_loop.assert_called_once()

    def test_start_with_zero_holdings_does_not_call_subscriber_start(self):
        """0 positions (paper-mode 红线 sustained) → subscriber.start() skipped."""
        service = _make_service(
            positions={},
            nav={"total_value": 1_000_000.0, "cash": 1_000_000.0},
        )
        service._run_sync_loop = MagicMock()

        service.start()

        # 0 holdings → no subscribe call; but cleanup still runs
        service._subscriber.start.assert_not_called()
        service._subscriber.stop.assert_called_once()


# ---------- TestBuildEngineGuard ----------


class TestBuildEngineGuard:
    """`_build_engine` rule registration guard (reviewer P1-1, 2026-05-15).

    Verify that an injected engine with pre-existing rules is NOT
    auto-double-registered (which would crash with ValueError).
    """

    def test_injected_engine_with_rules_not_double_registered(self):
        """Injected engine with rules → _build_engine respects caller-owned state.

        Without the P1-1 fix, calling _build_engine on an injected engine
        that already has any of the 10 canonical rules raises ValueError.
        After fix: register_all_realtime_rules is skipped when engine is
        injected (freshly_built=False).
        """
        from backend.qm_platform.risk.rules.realtime.limit_down import (
            LimitDownDetection,
        )

        # Pre-populate an engine
        prepopulated_engine = RealtimeRiskEngine()
        prepopulated_engine.register(LimitDownDetection(), cadence="tick")

        service = RealtimeRiskEngineService(
            strategy_id="test-strategy",
            qmt_client=_make_mock_qmt_client(),
            subscriber=MagicMock(),
            engine=prepopulated_engine,  # injected, NOT freshly built
            threshold_cache=InMemoryThresholdCache(),
            redis_client=MagicMock(),
            stream_bus=MagicMock(),
        )

        # MUST NOT raise — fix bypasses register_all_realtime_rules
        engine = service._build_engine()

        # Engine remains as-injected (only the manually-registered rule)
        assert engine is prepopulated_engine
        assert engine.registered_rules["tick"] == ["limit_down_detection"]
        # threshold_cache still gets wired
        assert engine._threshold_cache is service._threshold_cache

    def test_fresh_engine_path_still_registers_all_rules(self):
        """engine=None → freshly built → 10 rules registered (regression guard)."""
        service = _make_service()  # engine=None → freshly built path
        engine = service._build_engine()
        total = sum(len(rules) for rules in engine.registered_rules.values())
        assert total == 10
