"""Realtime Risk Engine Service — V3 L1 production runner (IC-1c WU-2).

V3 PT Cutover Plan v0.4 §A IC-1c WU-2 — standalone Servy-managed process that
drives the L1 RealtimeRiskEngine in production. Sustains qmt_data_service.py
体例 (signal handler / backoff retry / SETEX zombie protection / T0-16
fail-loud escalation), adapted to xtquant tick callback flow.

Architecture:
  1. Read holdings from `portfolio:current` Hash (qmt_data_service writes 60s)
  2. XtQuantTickSubscriber.start(codes) — xtquant subscribe_quote stream
  3. RealtimeRiskEngine + rule_registry.register_all_realtime_rules (10 rules,
     SSOT per IC-1c WU-1 — replay-vs-production parity ADR-076 D1)
  4. engine.set_threshold_cache(RedisThresholdCache()) — read S7 Beat publishes
  5. tick callback → build RiskContext → engine.on_tick(ctx) → dispatch results
  6. heartbeat SETEX `risk:l1_heartbeat` TTL=300s per tick (LL-081 zombie protection)
  7. resync loop (60s): refresh holdings cache for tick-callback RiskContext build

Scope (WU-2 minimal — verify-driven per LL-100 chunked SOP):
  - tick cadence ONLY — 5min + 15min beat triggers DORMANT (follow-up sub-PR
    will add clock-aligned threads invoking engine.on_5min_beat / on_15min_beat)
  - dispatch via log + Redis stream `qm:risk:l1_triggered` (NOT L4 STAGED — IC-2
    scope, depends on signal_service V3 chain wire)
  - heartbeat WRITE — meta_monitor_service `_collect_l1_heartbeat` READ path
    replace is WU-3 scope (per IC-1c chunk plan, ADR-073 D3 sediment)

Servy registration (post-merge ops, NOT this script):
  servy-cli.exe create --name QuantMind-RealtimeRisk \
      --executable python --args "scripts/realtime_risk_engine_service.py" \
      --stdout logs/realtime-risk-stdout.log --stderr logs/realtime-risk-stderr.log \
      --start-mode AutomaticDelayedStart

Failure mode (V3 §0.5 + ADR-072 D2 fail-open):
  - subscriber crash / engine.evaluate raise → per-rule exception isolation in
    RealtimeRiskEngine._evaluate_group (engine.py:125 silent_ok per-rule), but
    callback crash NOT caught — sustained xt-subscriber callback error logger
    (subscriber.py:145) keeps subscription alive.
  - consecutive failure threshold (T0-16 体例) → DingTalk P0 escalation +
    sustained service retry loop (NOT auto-stop — risk engine outage is itself
    a P0 condition surfaced via 元告警 alert-on-alert HC-1 layer).

红线 5/5 sustained: 0 broker call / 0 .env mutation / 0 yaml mutation / 0 DB
  row mutation / 0 真账户 mutation. xtquant subscribe_quote is read-only.

关联铁律: 31 (engine PURE — service is Application orchestration) /
  33 (fail-loud on consecutive failure escalation) / 35 (settings injection,
  no fallback defaults) / 41 (UTC internal + ISO timestamps)
关联 ADR: ADR-029 (10 RealtimeRiskRule) / ADR-073 D3 (L1 production runner —
  THIS PR addresses the deferral) / ADR-076 D1 (replay-as-gate parity, sustains
  IC-1c WU-1 SSOT) / ADR-078 reserved (IC-1c closure cumulative)
关联 LL: LL-081 (Redis SETEX zombie protection 体例) / LL-098 X10 (per-sub-PR
  STOP gate) / LL-100 (chunked SOP) / LL-168/169 (net-new-wiring expected
  balloon — IC-1c WU-2 is net-new wiring) / LL-170 (V3-as-island detection —
  IC-1c WU-2 is the headline remediation)
关联 V3: §4.3 (L1 cadence map) / §0.5 (fail-open design) / §13.3 (元监控
  alert-on-alert — L1 heartbeat consumer is the dormant alert this PR
  re-activates via heartbeat write)
关联 Plan v0.4: §A IC-1c WU-2 (production runner skeleton + subscribe wire +
  heartbeat write)
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

# 项目路径设置 (沿用 qmt_data_service.py 体例)
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root / "backend"))

from qm_platform.risk.dynamic_threshold.cache import (  # noqa: E402
    RedisThresholdCache,
    ThresholdCache,
)
from qm_platform.risk.interface import Position, RiskContext  # noqa: E402
from qm_platform.risk.realtime import (  # noqa: E402
    RealtimeRiskEngine,
    XtQuantTickSubscriber,
    register_all_realtime_rules,
)

from app.config import settings  # noqa: E402
from app.core.qmt_client import QMTClient  # noqa: E402
from app.core.stream_bus import get_stream_bus  # noqa: E402
from app.core.xtquant_path import ensure_xtquant_path  # noqa: E402

if TYPE_CHECKING:
    from qm_platform.risk.interface import RuleResult

# 配置日志 (沿用 qmt_data_service.py 体例)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("realtime_risk_engine_service")

# Redis 键 (沿用 qmt_data_service.py 命名空间体例)
CACHE_L1_HEARTBEAT: Final[str] = "risk:l1_heartbeat"
"""LL-081 体例: SETEX TTL=300s. zombie 后自然 expire → meta_monitor_service
`_collect_l1_heartbeat` (WU-3 read path) 看到 None → 触发 P0 元告警."""

CACHE_L1_HEARTBEAT_TTL_SEC: Final[int] = 300
"""5min TTL — 与 ThresholdCache TTL + Beat cadence 对齐. 反 zombie 时 key
永不过期 silent failure (沿用 LL-081 qmt_data_service SETEX 修复体例)."""

STREAM_RISK_L1_TRIGGERED: Final[str] = "qm:risk:l1_triggered"
"""L1 RealtimeRiskEngine 触发的 RuleResult 发布 stream. 消费者 (IC-2 scope
信号链 / L4ExecutionPlanner) 后续接入. WU-2 minimal scope = publish only,
no consumer wire."""

# 同步间隔
SYNC_INTERVAL_SEC: Final[int] = 60
"""Position resync cadence. 与 qmt_data_service.py 60s 写 portfolio:current
同步, 反 stale position cache 推导 RiskContext."""

# T0-16 fail-loud (沿用 qmt_data_service.py 体例)
_CONSECUTIVE_FAILURE_THRESHOLD: Final[int] = 5
"""5 consecutive sync failures @ 60s = 5 min sustained failure → DingTalk P0."""


class RealtimeRiskEngineService:
    """L1 RealtimeRiskEngine production runner service.

    Sustains qmt_data_service.QMTDataService pattern: standalone process,
    Servy-managed, signal-handled graceful shutdown, backoff retry, T0-16
    consecutive-failure DingTalk escalation.

    Dependency injection (test-friendly):
        - strategy_id: defaults to settings.PAPER_STRATEGY_ID
        - qmt_client / subscriber / engine / threshold_cache / redis_client /
          stream_bus: all injectable for unit test mocking
    """

    def __init__(
        self,
        *,
        strategy_id: str | None = None,
        qmt_client: QMTClient | None = None,
        subscriber: XtQuantTickSubscriber | None = None,
        engine: RealtimeRiskEngine | None = None,
        threshold_cache: ThresholdCache | None = None,
        redis_client: Any = None,
        stream_bus: Any = None,
    ) -> None:
        self._strategy_id: str = strategy_id or getattr(
            settings, "PAPER_STRATEGY_ID", "unknown-strategy"
        )
        self._execution_mode: str = getattr(settings, "EXECUTION_MODE", "paper")

        # Dependency injection — components are lazy-constructed on start() if
        # not provided, so unit tests can inject mocks without triggering real
        # xtquant import (铁律 31 lazy import sustained per subscriber.py:86).
        self._qmt_client: QMTClient | None = qmt_client
        self._subscriber: XtQuantTickSubscriber | None = subscriber
        self._engine: RealtimeRiskEngine | None = engine
        self._threshold_cache: ThresholdCache | None = threshold_cache
        self._redis = redis_client
        self._bus = stream_bus or get_stream_bus()

        # Runtime state
        self._running = False
        self._lock = threading.Lock()
        self._positions: dict[str, int] = {}  # code → shares snapshot
        self._portfolio_nav: float = 0.0

        # T0-16 fail-loud (沿用 qmt_data_service.py 体例)
        self._consecutive_sync_failures: int = 0
        self._fail_loud_alerted: bool = False

        # Tick counters (operational visibility — sustained debug log every 100 ticks)
        self._tick_count: int = 0
        self._trigger_count: int = 0

    def _get_redis(self) -> Any:
        """Lazy Redis client (沿用 qmt_data_service.py 体例)."""
        if self._redis is None:
            import redis  # noqa: PLC0415

            self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    def _get_qmt_client(self) -> QMTClient:
        """Lazy QMTClient (沿用 qmt_client.py singleton 体例)."""
        if self._qmt_client is None:
            self._qmt_client = QMTClient()
        return self._qmt_client

    def _build_engine(self) -> RealtimeRiskEngine:
        """Construct RealtimeRiskEngine + register all rules + wire threshold cache.

        Uses rule_registry SSOT (IC-1c WU-1) — same rule set as replay/backtest
        path. Threshold cache reads S7 Beat publishes (cross-process via Redis).

        Reviewer fix (code-reviewer P1-1, 2026-05-15): rules are registered ONLY
        when the engine is freshly built here. An injected engine (DI test path,
        OR a future caller that wants to pre-populate custom rule subsets) is
        taken as-is — caller owns rule registration. Without this guard, calling
        `register_all_realtime_rules` on an injected engine that already has any
        of the 10 canonical rules raises `ValueError` from
        `RealtimeRiskEngine.register` (engine.py:67-69 fail-loud 铁律 33).
        """
        freshly_built = self._engine is None
        engine = self._engine or RealtimeRiskEngine()
        if freshly_built:
            register_all_realtime_rules(engine)

        if self._threshold_cache is None:
            self._threshold_cache = RedisThresholdCache()
        engine.set_threshold_cache(self._threshold_cache)

        return engine

    def _refresh_positions(self) -> bool:
        """Refresh holdings snapshot from QMT cache. Returns True on success."""
        try:
            positions = self._get_qmt_client().get_positions()
            nav_data = self._get_qmt_client().get_nav() or {}
            with self._lock:
                self._positions = dict(positions)
                self._portfolio_nav = float(nav_data.get("total_value", 0.0) or 0.0)
            logger.debug(
                "[realtime-risk] positions refreshed: count=%d nav=%.2f",
                len(positions),
                self._portfolio_nav,
            )
            # T0-16 success path: reset counter + alert flag
            self._consecutive_sync_failures = 0
            self._fail_loud_alerted = False
            return True
        except Exception:
            logger.warning("[realtime-risk] position refresh failed", exc_info=True)
            self._consecutive_sync_failures += 1
            if (
                self._consecutive_sync_failures >= _CONSECUTIVE_FAILURE_THRESHOLD
                and not self._fail_loud_alerted
            ):
                self._escalate_consecutive_failures()
                self._fail_loud_alerted = True
            return False

    def _escalate_consecutive_failures(self) -> None:
        """T0-16 fail-loud: write DingTalk P0 alert on sustained position refresh failure.

        Service does NOT auto-stop — risk engine outage IS a P0 condition that
        the 元告警 alert-on-alert layer (HC-1) should surface via L1 heartbeat
        rule (WU-3 read path). Sustained 铁律 33 fail-loud.
        """
        count = self._consecutive_sync_failures
        logger.error(
            "[T0-16 fail-loud] realtime_risk_engine_service consecutive position "
            "refresh failures = %d (>= threshold %d × 60s = %d min). "
            "tick callbacks will use stale position snapshot.",
            count,
            _CONSECUTIVE_FAILURE_THRESHOLD,
            _CONSECUTIVE_FAILURE_THRESHOLD,
        )
        try:
            from app.services.dingtalk_alert import send_with_dedup  # noqa: PLC0415

            send_with_dedup(
                dedup_key="realtime_risk_engine_service:consecutive_sync_failures",
                severity="p0",
                source="realtime_risk_engine_service",
                title="Realtime Risk Engine 持仓刷新连续失败",
                body=(
                    f"_consecutive_sync_failures={count} "
                    f"(>= {_CONSECUTIVE_FAILURE_THRESHOLD} = "
                    f"{_CONSECUTIVE_FAILURE_THRESHOLD} min). "
                    "T0-16 fail-loud escalation. L1 RealtimeRiskEngine tick "
                    "callbacks will use stale position snapshot — Risk eval "
                    "drift risk. 需人工 Servy restart QuantMind-RealtimeRisk "
                    "或 QuantMind-QMTData 后验证 sync 恢复."
                ),
            )
        except Exception:
            # 铁律 33-d silent_ok: alert 失败不 cascade 阻 service loop, 仅 log.
            # 主告警链路 (logger.error 上方) 已记录, dingtalk 是次告警通道.
            logger.exception(
                "[T0-16] dingtalk_alert escalation failed (next sync 将重试 dedup_hit)"
            )

    def _build_realtime_context(self, ticks: dict[str, dict[str, Any]]) -> RiskContext:
        """Build RiskContext from current positions snapshot + tick data.

        Position fields lacking from QMT cache (entry_price / peak_price /
        entry_date) are set to 0 / None — rules that depend on them (e.g.
        TrailingStop, NewPositionVolatilityRule) SHOULD skip per their own
        contract (sustained Position docstring at interface.py:30-34).

        Args:
            ticks: subscriber.get_current_realtime() output — {code: {price,
                volume, prev_close, open_price, price_5min_ago,
                price_15min_ago, day_volume}}

        Returns:
            RiskContext with realtime dict populated for L1 tick rules.
        """
        with self._lock:
            positions_snapshot = dict(self._positions)
            nav_snapshot = self._portfolio_nav

        positions: list[Position] = []
        for code, shares in positions_snapshot.items():
            tick = ticks.get(code, {})
            current_price = float(tick.get("price", 0.0) or 0.0)
            positions.append(
                Position(
                    code=code,
                    shares=int(shares),
                    entry_price=0.0,  # not available from QMT cache, rules skip
                    peak_price=0.0,  # not available from QMT cache, rules skip
                    current_price=current_price,
                    entry_date=None,  # not available, holding-time rules skip
                )
            )

        # Realtime dict per V3 §4.3 — feeds tick rules (LimitDown / GapDown /
        # NearLimitDown — they read prev_close, open_price, day_volume etc.)
        realtime = {code: dict(tick_data) for code, tick_data in ticks.items()}

        # execution_mode literal narrowing — Literal["paper", "live"] requires
        # str → "paper"/"live", sustained ADR-008 namespace contract
        mode: Any = self._execution_mode  # noqa: ANN401 — Literal narrow at boundary
        return RiskContext(
            strategy_id=self._strategy_id,
            execution_mode=mode,
            timestamp=datetime.now(UTC),
            positions=tuple(positions),
            portfolio_nav=nav_snapshot,
            prev_close_nav=None,
            realtime=realtime,
        )

    def _write_heartbeat(self, now: datetime) -> None:
        """Write L1 heartbeat to Redis (LL-081 SETEX zombie protection).

        Sustains qmt_data_service.py CACHE_QMT_STATUS SETEX pattern. WU-3 will
        wire meta_monitor_service `_collect_l1_heartbeat` to read this key —
        absent / expired → P0 元告警 (ADR-073 D3 dormant alert re-activated).
        """
        try:
            self._get_redis().setex(CACHE_L1_HEARTBEAT, CACHE_L1_HEARTBEAT_TTL_SEC, now.isoformat())
        except Exception:  # noqa: BLE001
            # silent_ok: heartbeat write is best-effort; loss of heartbeat in
            # one tick will self-correct on next tick. Redis-down condition
            # surfaces via meta_monitor PG-health / DingTalk-push collectors.
            logger.debug("[realtime-risk] heartbeat write failed (next tick retry)", exc_info=True)

    def _dispatch_triggered(self, results: list[RuleResult]) -> None:
        """Dispatch triggered RuleResults — WU-2 minimal scope: log + Redis stream.

        Full L4 STAGED workflow wiring is IC-2 scope (depends on signal_service
        V3 chain). WU-2 publishes RuleResults to Redis stream
        `qm:risk:l1_triggered` for downstream consumers (future IC-2+ scope).

        红线 sustained: 0 broker call, 0 sell, 0 .env mutation.

        Reviewer fix (code-reviewer P2-1 + python-reviewer P2-1, 2026-05-15):
        `_trigger_count` accumulation moved to `_on_tick` (under the same
        `_lock` block that owns `_tick_count`) so both counters are mutated
        atomically together and the periodic debug log shows a consistent
        snapshot. This method now only logs + publishes; counter math lives
        in the single tick orchestration path.
        """
        for result in results:
            logger.warning(
                "[realtime-risk] L1 rule triggered: rule_id=%s code=%s shares=%s reason=%s",
                result.rule_id,
                result.code,
                result.shares,
                result.reason,
            )
            try:
                self._bus.publish_sync(
                    STREAM_RISK_L1_TRIGGERED,
                    {
                        "rule_id": result.rule_id,
                        "code": result.code,
                        "shares": result.shares,
                        "reason": result.reason,
                        "metrics": json.dumps(result.metrics),
                        "triggered_at": datetime.now(UTC).isoformat(),
                        "strategy_id": self._strategy_id,
                    },
                    source="realtime_risk_engine_service",
                )
            except Exception:  # noqa: BLE001
                # silent_ok: stream publish failure does not block tick eval.
                # Logger.warning above already recorded the trigger event.
                logger.warning(
                    "[realtime-risk] stream publish failed for rule_id=%s",
                    result.rule_id,
                    exc_info=True,
                )

    def _on_tick(self, ticks: dict[str, dict[str, Any]]) -> None:
        """Tick callback — invoked by XtQuantTickSubscriber on each tick batch.

        Sustains subscriber.py:139-151 callback exception contract (subscriber
        wraps callbacks in try/except so a crashing callback never tears down
        the xtquant subscription). Reviewer fix (code-reviewer P2-2 +
        python-reviewer P2-2, 2026-05-15): the outer subscriber-level catch is
        the strict requirement; this method ALSO carries a service-internal
        try/except so the service does not rely on the subscriber's external
        catch for its own correctness invariants (heartbeat-on-success,
        counter-consistency).

        Flow per tick:
          1. Build RiskContext from cached positions + tick data
          2. engine.on_tick(ctx) → list[RuleResult]
          3. Dispatch triggered results (log + stream)
          4. Write heartbeat SETEX
          5. Periodic operational debug log (every 100 ticks)

        Concurrency (reviewer fix code-reviewer P2-1 + python-reviewer P2-1+P2-2,
        2026-05-15): all four counters/snapshots — `_tick_count`,
        `_trigger_count` increment, plus `_positions` length and
        `_portfolio_nav` reads — are taken inside a single `with self._lock`
        block so the periodic debug log shows a consistent snapshot from a
        single point in time (no torn read between sync-loop writer and
        xtquant-thread reader).
        """
        if not self._running:
            return
        if self._engine is None:
            return  # not yet started

        try:
            context = self._build_realtime_context(ticks)
            results = self._engine.on_tick(context)
            triggered_count = len(results)
            if results:
                self._dispatch_triggered(results)

            now = datetime.now(UTC)
            self._write_heartbeat(now)

            # All four reads/writes under one lock block — sustained snapshot
            with self._lock:
                self._tick_count += 1
                self._trigger_count += triggered_count
                tick_count = self._tick_count
                trigger_count_snapshot = self._trigger_count
                pos_count_snapshot = len(self._positions)
                nav_snapshot = self._portfolio_nav

            if tick_count % 100 == 0:
                logger.info(
                    "[realtime-risk] ticks_processed=%d triggers_total=%d positions=%d nav=%.2f",
                    tick_count,
                    trigger_count_snapshot,
                    pos_count_snapshot,
                    nav_snapshot,
                )
        except Exception:  # noqa: BLE001
            # Service-internal isolation guard (reviewer fix code-reviewer P2-2):
            # subscriber.py:145 also catches, but we add this guard so a future
            # subscriber implementation change cannot silently break the service's
            # heartbeat / counter invariants. Heartbeat write failure has its own
            # silent_ok in _write_heartbeat; this catches build_context /
            # engine.on_tick / dispatch crashes. # silent_ok: tick loss is self-
            # correcting on next tick; full stack trace logged for forensics.
            logger.exception("[realtime-risk] _on_tick failed (tick eval skipped)")

    def start(self) -> None:
        """Start the service — connect Redis + xtquant + subscribe + tick loop.

        Reviewer fix (code-reviewer P1-2, 2026-05-15): the try/finally guarding
        `_cleanup()` now wraps every step that could leave a resource leaked
        (subscriber.start() can raise `RuntimeError("already running")` or
        propagate subscribe_quote exceptions). The previous narrower scope
        only wrapped `_run_sync_loop()`, so a subscriber.start() failure left
        engine + Redis + (partially-started) subscriber uncleaned.
        """
        logger.info("=== Realtime Risk Engine Service 启动 ===")
        self._running = True

        # Register signal handlers (sustained qmt_data_service.py 体例)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        try:
            # Initial position refresh (used to determine subscribe symbol set)
            if not self._refresh_positions():
                logger.warning(
                    "[realtime-risk] initial position refresh failed — will retry "
                    "in sync loop, but no symbols subscribed yet"
                )

            # Build engine (rule_registry + threshold cache)
            self._engine = self._build_engine()

            # Build subscriber (lazy — xtquant only imported on subscribe)
            if self._subscriber is None:
                ensure_xtquant_path()
                self._subscriber = XtQuantTickSubscriber()
            self._subscriber.add_callback(self._on_tick)

            # Subscribe to current holdings — reviewer P1-2 covers raise here
            with self._lock:
                initial_codes = list(self._positions.keys())
            if initial_codes:
                self._subscriber.start(initial_codes)
                logger.info(
                    "[realtime-risk] subscribed to %d holdings: %s",
                    len(initial_codes),
                    initial_codes,
                )
            else:
                logger.warning(
                    "[realtime-risk] 0 holdings at startup (paper-mode 0 positions "
                    "sustained per 红线 5/5) — subscriber idle until next sync detects "
                    "new positions. Manual Servy restart needed if holdings appear."
                )

            # Resync loop — refreshes position cache + heartbeat (no auto-subscribe
            # of new codes in WU-2 minimal scope, doc as known limitation)
            self._run_sync_loop()
        finally:
            self._cleanup()

    def _run_sync_loop(self) -> None:
        """Main loop — refreshes positions every SYNC_INTERVAL_SEC."""
        logger.info("[realtime-risk] sync loop started, interval=%ds", SYNC_INTERVAL_SEC)

        while self._running:
            try:
                self._refresh_positions()
            except Exception:
                logger.exception("[realtime-risk] sync loop iteration failed")

            # Sleep with interrupt-aware fine-grained polling (沿用 qmt_data_service)
            for _ in range(SYNC_INTERVAL_SEC):
                if not self._running:
                    break
                time.sleep(1)

    def _cleanup(self) -> None:
        """Graceful shutdown — unsubscribe + log final stats."""
        if self._subscriber is not None:
            try:
                self._subscriber.stop()
            except Exception:
                logger.warning(
                    "[realtime-risk] subscriber.stop() raised (best-effort cleanup)",
                    exc_info=True,
                )
        logger.info(
            "=== Realtime Risk Engine Service 已停止 (ticks=%d triggers=%d) ===",
            self._tick_count,
            self._trigger_count,
        )

    def _handle_shutdown(self, signum: int, frame: Any) -> None:  # noqa: ARG002
        """Signal handler — graceful shutdown (沿用 qmt_data_service.py 体例)."""
        logger.info("[realtime-risk] received shutdown signal sig=%d", signum)
        self._running = False


def main() -> None:
    """Entry point."""
    service = RealtimeRiskEngineService()
    service.start()


if __name__ == "__main__":
    main()
