"""RiskBacktestAdapter — S5 sub-PR 5c (stub) + TB-1a (full evaluator extension).

## S5 sub-PR 5c 体例 sustained: 回测适配器桩 (0 broker / 0 alert / 0 INSERT)

实现 BrokerProtocol / NotifierProtocol / PriceReaderProtocol 的桩版本:
  - sell() 记录调用到 _sell_calls, 不执行真 broker sell
  - send() 记录通知到 _alerts, 不发送真 DingTalk
  - get_prices() 返回注入价格或空, get_nav() 返回注入 NAV 或桩值

用于:
  - S10 paper-mode 5d dry-run: 历史 tick 回放时不需要真实 broker/alert/DB
  - unit test: 验证 RiskEngine 调用链 (sell/alert 触发正确性)
  - 铁律 10b smoke: 生产入口启动验证 (不依赖 QMT/网络)

## TB-1a (Plan v0.2 §A TB-1, 本 sub-PR) — evaluator extension

post-(α) architecture decision (sustained user ack 2026-05-13 + ADR-066 候选 sediment):
同 class 加 evaluate_at(timestamp, context, engine) → list[RuleResult] —
**production parity 优先**, replay 走 RealtimeRiskEngine 真实路径 + 0 IO 注入。

  - evaluate_at(): pure-function evaluator, 按 timestamp cadence boundary
    分发到 engine.on_tick / on_5min_beat / on_15min_beat
  - dedup contract: per (timestamp, code, rule_id) unique (V3 §11.4 line 1298)
  - 纯函数契约 audit: 0 broker call / 0 INSERT / 0 alert during evaluate_at
    (verify via _sell_calls / _alerts 长度不变 before/after)
  - register_all_realtime_rules() helper: 注册 10 rules per ADR-029 amend
    (LimitDownDetection tick / NearLimitDown tick / RapidDrop5min 5min /
     RapidDrop15min 15min / GapDownOpen tick / VolumeSpike 5min /
     LiquidityCollapse 5min / IndustryConcentration 5min / CorrelatedDrop 5min /
     TrailingStop tick)

设计: 所有调用记录在内部 list, 线程安全。测试可断言 sell 次数 / 通知内容 /
evaluate_at 返回 RuleResult 列表 / dedup behavior。

关联铁律: 31 (纯桩 + evaluate_at 0 IO) / 33 (fail-loud on 重复注入) / 24
关联 ADR: ADR-029 (10 RealtimeRiskRule) / ADR-064 (Plan v0.2 5 决议 lock D3=b
2 关键窗口) / ADR-066 候选 (TB-1a sediment)
关联 LL: LL-098 X10 / LL-159 (CC self silent drift family + 4-step preflight SOP)
关联 V3: §11.4 (RiskBacktestAdapter pure function) / §15.5 (sim-to-real gap)
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from .interface import RiskContext, RuleResult
    from .realtime.engine import RealtimeRiskEngine


class RiskBacktestAdapter:
    """回测适配器桩 — 实现 BrokerProtocol + NotifierProtocol + PriceReaderProtocol.

    用法:
        adapter = RiskBacktestAdapter(
            prices={"600519.SH": 100.0},
            nav={"cash": 1_000_000.0, "total_value": 1_000_000.0},
        )
        # 注入到 PlatformRiskEngine
        engine = PlatformRiskEngine(..., broker=adapter, notifier=adapter, price_reader=adapter)
        # ... run rules ...
        assert len(adapter.sell_calls) == 0  # 验证无 sell
        assert len(adapter.alerts) == 3       # 验证 3 条通知
    """

    def __init__(
        self,
        prices: dict[str, float] | None = None,
        nav: dict[str, Any] | None = None,
    ) -> None:
        self._prices: dict[str, float] = prices or {}
        self._nav: dict[str, Any] | None = nav
        self._lock = threading.Lock()
        # 调用记录
        self._sell_calls: list[dict[str, Any]] = []
        self._alerts: list[dict[str, Any]] = []
        self._price_queries: list[list[str]] = []
        self._nav_queries: int = 0
        # TB-1a evaluate_at() dedup state — per V3 §11.4 line 1298:
        #   "events 通过 (timestamp, symbol_id, rule_id) 唯一. backtest 重跑同一时段不重复触发."
        self._evaluated_keys: set[tuple[str, str, str]] = set()

    # ---- BrokerProtocol ----

    def sell(self, code: str, shares: int, reason: str, timeout: float = 5.0) -> dict[str, Any]:
        """桩 sell: 记录调用, 返 stub 结果. 0 真 broker 调用."""
        with self._lock:
            self._sell_calls.append(
                {
                    "code": code,
                    "shares": shares,
                    "reason": reason,
                    "timeout": timeout,
                }
            )
        return {
            "status": "stub_sell_ok",
            "code": code,
            "shares": shares,
            "filled_shares": 0,  # stub: 0 filled (回测不真卖)
            "price": self._prices.get(code, 0.0),
        }

    # ---- NotifierProtocol ----

    def send(self, title: str, text: str, severity: str = "warning") -> None:
        """桩 send: 记录通知, 0 真 DingTalk 推送."""
        with self._lock:
            self._alerts.append(
                {
                    "title": title,
                    "text": text,
                    "severity": severity,
                }
            )

    # ---- PriceReaderProtocol ----

    def get_prices(self, codes: list[str]) -> dict[str, float]:
        """桩 get_prices: 从注入字典返价格, 缺值不包含在结果中."""
        with self._lock:
            self._price_queries.append(list(codes))
        return {c: self._prices[c] for c in codes if c in self._prices}

    def get_nav(self) -> dict[str, Any] | None:
        """桩 get_nav: 返注入 NAV 或默认桩值."""
        with self._lock:
            self._nav_queries += 1
        if self._nav is not None:
            return dict(self._nav)
        return {
            "cash": 1_000_000.0,
            "total_value": 1_000_000.0,
            "positions_market_value": 0.0,
        }

    # ---- Call record accessors (test assertions) ----

    @property
    def sell_calls(self) -> list[dict[str, Any]]:
        """sell() 调用记录 (线程安全 copy)."""
        with self._lock:
            return list(self._sell_calls)

    @property
    def alerts(self) -> list[dict[str, Any]]:
        """send() 调用记录 (线程安全 copy)."""
        with self._lock:
            return list(self._alerts)

    @property
    def price_query_count(self) -> int:
        """get_prices() 调用次数."""
        with self._lock:
            return len(self._price_queries)

    @property
    def nav_query_count(self) -> int:
        """get_nav() 调用次数."""
        with self._lock:
            return self._nav_queries

    def reset(self) -> None:
        """重置所有调用记录 + dedup state (测试间复用)."""
        with self._lock:
            self._sell_calls.clear()
            self._alerts.clear()
            self._price_queries.clear()
            self._nav_queries = 0
            self._evaluated_keys.clear()

    # ---- TB-1a Evaluator extension (Plan v0.2 §A TB-1, post-(α) architecture) ----

    def evaluate_at(
        self,
        timestamp: datetime,
        context: RiskContext,
        engine: RealtimeRiskEngine,
    ) -> list[RuleResult]:
        """Pure-function evaluator: dispatch engine by cadence + dedup events.

        V3 §11.4 contract: 0 broker / 0 alert / 0 INSERT during evaluate_at.
        Implementation per (α) architecture (sustained user ack 2026-05-13):
        invoke RealtimeRiskEngine.on_tick / on_5min_beat / on_15min_beat
        according to timestamp cadence boundary — production parity.

        Cadence dispatch logic:
          - tick cadence: always invoked
          - 5min cadence: invoked when timestamp minute % 5 == 0
          - 15min cadence: invoked when timestamp minute % 15 == 0

        Dedup per (timestamp_iso, code, rule_id) — V3 §11.4 line 1298.
        Subsequent evaluate_at(same_timestamp, ...) returns empty list for
        already-seen events.

        Args:
            timestamp: backtest timestamp (timezone-aware per 铁律 41).
            context: RiskContext with realtime tick data.
            engine: RealtimeRiskEngine instance with rules registered.

        Returns:
            Deduped RuleResult list for this timestamp.

        Raises:
            ValueError: timestamp 非 timezone-aware (铁律 41 enforcement).
        """
        if timestamp.tzinfo is None:
            raise ValueError("evaluate_at timestamp must be timezone-aware (铁律 41 sustained)")

        results: list[RuleResult] = []

        # 1. tick cadence — always invoke
        results.extend(engine.on_tick(context))

        # 2. 5min cadence — invoke on 5min boundary
        if timestamp.minute % 5 == 0 and timestamp.second == 0 and timestamp.microsecond == 0:
            results.extend(engine.on_5min_beat(context))

        # 3. 15min cadence — invoke on 15min boundary
        if timestamp.minute % 15 == 0 and timestamp.second == 0 and timestamp.microsecond == 0:
            results.extend(engine.on_15min_beat(context))

        # Dedup per (timestamp_iso, code, rule_id) — V3 §11.4 line 1298
        deduped: list[RuleResult] = []
        ts_iso = timestamp.isoformat()
        with self._lock:
            for r in results:
                key = (ts_iso, r.code, r.rule_id)
                if key in self._evaluated_keys:
                    continue
                self._evaluated_keys.add(key)
                deduped.append(r)

        return deduped

    def register_all_realtime_rules(self, engine: RealtimeRiskEngine) -> None:
        """Helper: register 10 RealtimeRiskRule on engine per ADR-029 amend.

        Thin delegate to `realtime.rule_registry.register_all_realtime_rules` —
        the SSOT for L1 rule set wiring (IC-1c WU-1, ADR-076 D1 replay-vs-
        production parity invariant). The L1 production runner imports the
        same free function directly, so both replay and production paths
        register identical rule sets / cadences by construction.

        Cadence assignment per V3 §4.3 + ADR-029 §2.2 — see rule_registry
        docstring for the 10-rule cadence map.

        Args:
            engine: RealtimeRiskEngine instance to register rules into.

        Raises:
            ValueError: any rule_id already registered (engine fail-loud per 铁律 33).
        """
        from .realtime.rule_registry import (
            register_all_realtime_rules as _register_all,
        )

        _register_all(engine)

    def verify_pure_function_contract(
        self,
        *,
        before_sell_count: int,
        before_alert_count: int,
    ) -> None:
        """Assert 0 broker call / 0 alert during evaluate_at (V3 §11.4 contract).

        Call before evaluate_at + after evaluate_at to verify pure-function
        guarantee. Raise AssertionError if any IO occurred.

        Usage:
            before_s, before_a = len(adapter.sell_calls), len(adapter.alerts)
            adapter.evaluate_at(ts, ctx, engine)
            adapter.verify_pure_function_contract(
                before_sell_count=before_s, before_alert_count=before_a
            )

        Args:
            before_sell_count: sell_calls 长度 before evaluate_at.
            before_alert_count: alerts 长度 before evaluate_at.

        Raises:
            AssertionError: 0 broker/alert 契约 violated.
        """
        current_sell = len(self.sell_calls)
        current_alert = len(self.alerts)
        if current_sell != before_sell_count:
            raise AssertionError(
                f"V3 §11.4 pure-function contract violated: "
                f"sell_calls grew from {before_sell_count} to {current_sell} during evaluate_at"
            )
        if current_alert != before_alert_count:
            raise AssertionError(
                f"V3 §11.4 pure-function contract violated: "
                f"alerts grew from {before_alert_count} to {current_alert} during evaluate_at"
            )

    @property
    def evaluated_keys_count(self) -> int:
        """Dedup state size (number of unique (timestamp, code, rule_id) seen)."""
        with self._lock:
            return len(self._evaluated_keys)
