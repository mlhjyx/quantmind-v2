"""RiskBacktestAdapter — S5 sub-PR 5c: 回测适配器桩 (0 broker / 0 alert / 0 INSERT).

实现 BrokerProtocol / NotifierProtocol / PriceReaderProtocol 的桩版本:
  - sell() 记录调用到 _sell_calls, 不执行真 broker sell
  - send() 记录通知到 _alerts, 不发送真 DingTalk
  - get_prices() 返回注入价格或空, get_nav() 返回注入 NAV 或桩值

用于:
  - S10 paper-mode 5d dry-run: 历史 tick 回放时不需要真实 broker/alert/DB
  - unit test: 验证 RiskEngine 调用链 (sell/alert 触发正确性)
  - 铁律 10b smoke: 生产入口启动验证 (不依赖 QMT/网络)

设计: 所有调用记录在内部 list, 线程安全。测试可断言 sell 次数/参数/通知内容。

关联铁律: 31 (纯桩, 0 IO) / 33 (fail-loud on 重复注入) / 24
"""

from __future__ import annotations

import threading
from typing import Any


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
        """重置所有调用记录 (测试间复用)."""
        with self._lock:
            self._sell_calls.clear()
            self._alerts.clear()
            self._price_queries.clear()
            self._nav_queries = 0
