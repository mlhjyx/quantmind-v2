"""Unit + smoke tests for RiskBacktestAdapter (S5 sub-PR 5c).

覆盖:
  - BrokerProtocol: sell stub 记录 + 返回值验证
  - NotifierProtocol: send stub 记录
  - PriceReaderProtocol: get_prices 注入价格 / 缺值 / get_nav 桩值
  - 线程安全 (concurrent sell + send)
  - reset() 重置调用记录
  - Protocol 兼容性检查 (可注入到 PlatformRiskEngine)
"""

from __future__ import annotations

import threading

from backend.qm_platform.risk.backtest_adapter import RiskBacktestAdapter


class TestRiskBacktestAdapter:
    def test_sell_stub_records_call(self):
        """sell() 记录调用到 sell_calls, 返 stub 结果."""
        adapter = RiskBacktestAdapter()
        result = adapter.sell("600519.SH", 1000, "test sell")

        assert result["status"] == "stub_sell_ok"
        assert result["code"] == "600519.SH"
        assert result["shares"] == 1000
        assert result["filled_shares"] == 0  # stub: 0 filled

        calls = adapter.sell_calls
        assert len(calls) == 1
        assert calls[0]["code"] == "600519.SH"
        assert calls[0]["shares"] == 1000
        assert calls[0]["reason"] == "test sell"

    def test_sell_returns_injected_price(self):
        """sell 返回值含注入价格."""
        adapter = RiskBacktestAdapter(prices={"000001.SZ": 50.0})
        result = adapter.sell("000001.SZ", 500, "limit down sell")
        assert result["price"] == 50.0

    def test_sell_returns_zero_for_missing_price(self):
        """未注入价格返 0.0."""
        adapter = RiskBacktestAdapter()
        result = adapter.sell("999999.SZ", 100, "unknown stock")
        assert result["price"] == 0.0

    def test_send_stub_records_alert(self):
        """send() 记录告警到 alerts."""
        adapter = RiskBacktestAdapter()
        adapter.send("Risk Alert", "600519 limit down detected", severity="critical")

        assert len(adapter.alerts) == 1
        assert adapter.alerts[0]["title"] == "Risk Alert"
        assert adapter.alerts[0]["severity"] == "critical"
        assert "600519" in adapter.alerts[0]["text"]

    def test_send_default_severity(self):
        """send() 默认 severity='warning'."""
        adapter = RiskBacktestAdapter()
        adapter.send("Test", "message")
        assert adapter.alerts[0]["severity"] == "warning"

    def test_get_prices_returns_injected(self):
        """get_prices 返注入价格, 缺值不包含."""
        adapter = RiskBacktestAdapter(prices={"600519.SH": 100.0, "000001.SZ": 50.0})
        prices = adapter.get_prices(["600519.SH", "000001.SZ", "999999.SZ"])
        assert prices == {"600519.SH": 100.0, "000001.SZ": 50.0}
        assert "999999.SZ" not in prices
        assert adapter.price_query_count == 1

    def test_get_prices_empty(self):
        """空注入或空查询."""
        adapter = RiskBacktestAdapter()
        assert adapter.get_prices([]) == {}
        assert adapter.get_prices(["600519.SH"]) == {}

    def test_get_nav_returns_injected(self):
        """get_nav 返注入 NAV."""
        adapter = RiskBacktestAdapter(nav={"cash": 500000.0, "total_value": 520000.0})
        nav = adapter.get_nav()
        assert nav["cash"] == 500000.0
        assert nav["total_value"] == 520000.0
        assert adapter.nav_query_count == 1

    def test_get_nav_default_stub(self):
        """无注入 NAV 返默认桩值."""
        adapter = RiskBacktestAdapter()
        nav = adapter.get_nav()
        assert nav["cash"] == 1_000_000.0
        assert nav["total_value"] == 1_000_000.0
        assert nav["positions_market_value"] == 0.0

    def test_get_nav_returns_copy_not_ref(self):
        """get_nav 返回 copy, 修改不影响内部状态."""
        adapter = RiskBacktestAdapter(nav={"cash": 100.0})
        nav1 = adapter.get_nav()
        nav1["cash"] = 999.0
        nav2 = adapter.get_nav()
        assert nav2["cash"] == 100.0  # 不受 nav1 修改影响

    def test_reset_clears_all_records(self):
        """reset() 清空 sell/alerts/price_queries/nav_queries."""
        adapter = RiskBacktestAdapter(prices={"600519.SH": 100.0})
        adapter.sell("600519.SH", 100, "test")
        adapter.send("Alert", "message")
        adapter.get_prices(["600519.SH"])
        adapter.get_nav()

        assert len(adapter.sell_calls) == 1
        assert len(adapter.alerts) == 1
        assert adapter.price_query_count == 1
        assert adapter.nav_query_count == 1

        adapter.reset()

        assert len(adapter.sell_calls) == 0
        assert len(adapter.alerts) == 0
        assert adapter.price_query_count == 0
        assert adapter.nav_query_count == 0

    def test_multiple_sell_calls_recorded(self):
        """多次 sell 全记录."""
        adapter = RiskBacktestAdapter()
        for i in range(5):
            adapter.sell(f"00000{i}.SZ", 100, f"sell #{i}")
        assert len(adapter.sell_calls) == 5
        assert adapter.sell_calls[0]["code"] == "000000.SZ"
        assert adapter.sell_calls[4]["code"] == "000004.SZ"

    def test_multiple_alerts_recorded(self):
        """多次 send 全记录."""
        adapter = RiskBacktestAdapter()
        adapter.send("A1", "body1")
        adapter.send("A2", "body2", severity="critical")
        adapter.send("A3", "body3", severity="info")
        assert len(adapter.alerts) == 3
        assert [a["severity"] for a in adapter.alerts] == ["warning", "critical", "info"]

    def test_mixed_price_queries(self):
        """多次 get_prices 分别记录."""
        adapter = RiskBacktestAdapter(prices={"A": 1.0, "B": 2.0, "C": 3.0})
        adapter.get_prices(["A"])
        adapter.get_prices(["B", "C"])
        adapter.get_prices(["D"])
        assert adapter.price_query_count == 3

    def test_concurrent_sell_and_alert(self):
        """线程安全: 并发 sell + send 不丢记录."""
        adapter = RiskBacktestAdapter()
        errors = []

        def sell_worker(start: int, n: int):
            for i in range(start, start + n):
                try:
                    adapter.sell(f"code_{i}", 100, f"sell {i}")
                except Exception as e:
                    errors.append(str(e))

        def alert_worker(start: int, n: int):
            for i in range(start, start + n):
                try:
                    adapter.send(f"title_{i}", f"text_{i}")
                except Exception as e:
                    errors.append(str(e))

        threads = [
            threading.Thread(target=sell_worker, args=(0, 20)),
            threading.Thread(target=sell_worker, args=(20, 20)),
            threading.Thread(target=alert_worker, args=(0, 20)),
            threading.Thread(target=alert_worker, args=(20, 20)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(adapter.sell_calls) == 40
        assert len(adapter.alerts) == 40

    def test_smoke_platform_engine_compatibility(self):
        """验证 RiskBacktestAdapter 满足 Protocol 接口 (可注入到 PlatformRiskEngine)."""

        adapter = RiskBacktestAdapter(prices={"600519.SH": 100.0})

        # 类型兼容性: adapter 实现了三个 Protocol 的方法
        assert hasattr(adapter, "sell")
        assert hasattr(adapter, "send")
        assert hasattr(adapter, "get_prices")
        assert hasattr(adapter, "get_nav")

        # 接口签名验证
        assert callable(adapter.sell)
        assert callable(adapter.send)
        assert callable(adapter.get_prices)
        assert callable(adapter.get_nav)
