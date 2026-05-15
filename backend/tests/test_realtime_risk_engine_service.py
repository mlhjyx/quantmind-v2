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

    def test_dispatch_increments_trigger_count(self):
        """Each triggered result increments trigger_count for visibility."""
        service = _make_service()
        results = [self._make_result(rule_id=f"rule_{i}") for i in range(3)]
        service._dispatch_triggered(results)
        assert service._trigger_count == 3

    def test_dispatch_stream_failure_swallowed(self):
        """Stream publish raise → log warning, no propagation (sustained tick eval)."""
        service = _make_service()
        service._bus.publish_sync.side_effect = RuntimeError("stream-down")
        # Must not raise
        service._dispatch_triggered([self._make_result()])

    def test_dispatch_zero_broker_calls(self):
        """红线 sustained: WU-2 dispatch path makes 0 broker calls."""
        service = _make_service()
        # Service does not carry a broker dep at all
        assert not hasattr(service, "_broker")
        service._dispatch_triggered([self._make_result()])
        # Verify no MagicMock-broker-like attribute received calls
        for attr_name in dir(service):
            if "broker" in attr_name.lower():
                pytest.fail(f"Unexpected broker-like attribute: {attr_name}")


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
