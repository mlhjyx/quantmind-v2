"""QMT执行适配器测试。

验证:
1. target_weights → 订单生成逻辑（整手约束）
2. 先卖后买的执行顺序
3. _FillCollector回调收集
4. 下单失败 → PendingOrder
5. 空目标不执行
6. 全部卖出场景

S3 F76 修复 (2026-04-15): `_check_buy_protection` 改为 fail-safe —
无 xtdata tick 时拒单. 测试层使用 autouse fixture 注入健康 tick
mock, 保持原有测试语义. 要显式测试 fail-safe 的测试请用 monkeypatch
覆盖 _get_realtime_tick 返回 None.
"""

import threading
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from engines.qmt_execution_adapter import (
    LOT_SIZE,
    QMTExecutionAdapter,
    _FillCollector,
)
from engines.qmt_execution_adapter import (
    _WaitTracker as _OrderTracker,  # renamed in v2
)


@pytest.fixture(autouse=True)
def _mock_realtime_tick():
    """自动 mock _get_realtime_tick 返回健康 tick, 让 F76 fail-safe 不误触发。

    S3 F76: _check_buy_protection 现在拒绝无 tick 的订单. 测试默认注入
    一个"非涨停非跳空"的 tick, 让现有 order 逻辑测试继续工作.
    """

    def _fake_tick(qmt_code: str) -> dict:
        return {
            "lastPrice": 10.0,  # 非零, 有效
            "lastClose": 10.0,  # 同 lastPrice → 无跳空
            "open": 10.0,
            "askVol": [1000],  # 非空 → 非封板
        }

    with patch(
        "engines.qmt_execution_adapter._get_realtime_tick",
        side_effect=_fake_tick,
    ):
        yield


def _make_mock_broker(
    positions: dict[str, int] | None = None,
    cash: float = 500_000.0,
    total_asset: float = 1_000_000.0,
) -> MagicMock:
    """创建Mock MiniQMTBroker。"""
    broker = MagicMock()
    broker.get_positions.return_value = positions or {}
    broker.get_cash.return_value = cash
    broker.get_total_value.return_value = total_asset

    # 真实回调列表（P0-3测试需要）
    broker._trade_callbacks = []
    broker._order_callbacks = []
    broker._error_callbacks = []
    broker.register_trade_callback.side_effect = lambda fn: broker._trade_callbacks.append(fn)
    broker.register_order_callback.side_effect = lambda fn: broker._order_callbacks.append(fn)
    broker.register_error_callback.side_effect = lambda fn: broker._error_callbacks.append(fn)

    _order_counter = [0]

    def mock_place_order(code, direction, volume, price, price_type="limit", remark=""):
        _order_counter[0] += 1
        return _order_counter[0]

    broker.place_order.side_effect = mock_place_order
    return broker


class TestFillCollector:
    """_FillCollector回调收集器测试。"""

    def test_on_trade_sets_event(self) -> None:
        """成交回调设置event。"""
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=1,
            code="000001.SZ",
            direction="buy",
            volume=100,
            price=10.0,
        )
        collector.register(tracker)
        collector.on_trade(
            {
                "order_id": 1,
                "traded_volume": 100,
                "traded_price": 10.05,
                "traded_amount": 1005.0,
            }
        )
        assert tracker.is_done
        assert tracker.filled_volume == 100
        assert tracker.filled_price == 10.05
        assert tracker.event.is_set()

    def test_on_trade_partial_fill(self) -> None:
        """部分成交不触发done。"""
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=2,
            code="000001.SZ",
            direction="buy",
            volume=200,
            price=10.0,
        )
        collector.register(tracker)
        collector.on_trade(
            {
                "order_id": 2,
                "traded_volume": 100,
                "traded_price": 10.0,
                "traded_amount": 1000.0,
            }
        )
        assert not tracker.is_done
        assert tracker.filled_volume == 100

    def test_on_order_rejected(self) -> None:
        """废单回调标记error。"""
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=3,
            code="000001.SZ",
            direction="buy",
            volume=100,
            price=10.0,
        )
        collector.register(tracker)
        collector.on_order(
            {
                "order_id": 3,
                "order_status": 57,  # REJECTED
                "order_remark": "资金不足",
            }
        )
        assert tracker.is_done
        assert "废单" in tracker.error

    def test_on_error(self) -> None:
        """下单失败回调。"""
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=4,
            code="000001.SZ",
            direction="buy",
            volume=100,
            price=10.0,
        )
        collector.register(tracker)
        collector.on_error(
            {
                "order_id": 4,
                "error_msg": "连接断开",
            }
        )
        assert tracker.is_done
        assert "下单失败" in tracker.error

    def test_unknown_order_id_ignored(self) -> None:
        """未注册的order_id被忽略。"""
        collector = _FillCollector()
        # 不应抛异常
        collector.on_trade({"order_id": 999, "traded_volume": 100})
        collector.on_order({"order_id": 999, "order_status": 56})
        collector.on_error({"order_id": 999, "error_msg": "test"})


class TestQMTExecutionAdapter:
    """QMTExecutionAdapter测试。"""

    def test_empty_target_no_orders(self) -> None:
        """空目标权重不执行任何订单。"""
        broker = _make_mock_broker()
        adapter = QMTExecutionAdapter(broker)
        fills, pending = adapter.execute_rebalance(
            {},
            date(2026, 3, 29),
            {},
            signal_date=date(2026, 3, 28),
        )
        assert fills == []
        assert pending == []
        broker.place_order.assert_not_called()

    def test_lot_size_constraint(self) -> None:
        """目标股数遵循整手约束（100股倍数）。"""
        broker = _make_mock_broker(total_asset=100_000.0, cash=100_000.0)

        # 模拟即时成交
        def place_and_fill(code, direction, volume, price, price_type="limit", remark=""):
            oid = 1
            # 模拟回调线程立即成交
            threading.Timer(
                0.01,
                lambda: _trigger_fill(
                    adapter,
                    oid,
                    volume,
                    price,
                ),
            ).start()
            return oid

        broker.place_order.side_effect = place_and_fill
        adapter = QMTExecutionAdapter(broker)

        prices = {"000001.SZ": 15.0}  # 100000 * 0.5 / 15 = 3333 → 3300股
        fills, pending = adapter.execute_rebalance(
            {"000001.SZ": 0.5},
            date(2026, 3, 29),
            prices,
        )

        # 验证下单数量是100的倍数
        call_args = broker.place_order.call_args
        volume = call_args[1].get("volume") or call_args[0][2]
        assert volume % LOT_SIZE == 0

    def test_sell_before_buy(self) -> None:
        """先卖后买：卖出在买入之前执行。"""
        call_order: list[str] = []

        broker = _make_mock_broker(
            positions={"600519.SH": 200},
            total_asset=100_000.0,
            cash=50_000.0,
        )

        def track_order(code, direction, volume, price, price_type="limit", remark=""):
            call_order.append(f"{direction}:{code}")
            return -1  # 模拟失败，不需要等成交

        broker.place_order.side_effect = track_order
        adapter = QMTExecutionAdapter(broker)

        fills, pending = adapter.execute_rebalance(
            {"000001.SZ": 0.5},  # 买新股
            date(2026, 3, 29),
            {"600519.SH": 1800.0, "000001.SZ": 10.0},
        )

        # 应该先卖600519（不在目标中），再买000001
        sell_indices = [i for i, c in enumerate(call_order) if c.startswith("sell")]
        buy_indices = [i for i, c in enumerate(call_order) if c.startswith("buy")]
        if sell_indices and buy_indices:
            assert max(sell_indices) < min(buy_indices), "卖出应在买入之前"

    def test_place_order_failure_creates_pending(self) -> None:
        """下单失败（返回-1）创建PendingOrder。"""
        broker = _make_mock_broker(total_asset=100_000.0, cash=100_000.0)
        broker.place_order.return_value = -1  # 所有下单失败

        adapter = QMTExecutionAdapter(broker)
        fills, pending = adapter.execute_rebalance(
            {"000001.SZ": 0.5},
            date(2026, 3, 29),
            {"000001.SZ": 10.0},
            signal_date=date(2026, 3, 28),
        )

        assert len(fills) == 0
        assert len(pending) == 1
        assert pending[0].code == "000001.SZ"
        assert pending[0].signal_date == date(2026, 3, 28)

    def test_full_liquidation(self) -> None:
        """清仓场景：全部卖出，无买入。"""
        call_directions: list[str] = []
        broker = _make_mock_broker(
            positions={"000001.SZ": 500, "600519.SH": 100},
            total_asset=100_000.0,
            cash=0.0,
        )

        def track(code, direction, volume, price, price_type="limit", remark=""):
            call_directions.append(direction)
            return -1  # 不需要等成交

        broker.place_order.side_effect = track
        adapter = QMTExecutionAdapter(broker)

        fills, pending = adapter.execute_rebalance(
            {},  # 空目标 = 全部卖出
            date(2026, 3, 29),
            {"000001.SZ": 10.0, "600519.SH": 1800.0},
        )

        assert all(d == "sell" for d in call_directions)
        assert len(pending) == 0  # 卖出失败不产生pending

    def test_partial_fill_then_cancel(self) -> None:
        """部分成交后超时 → 撤单 + 返回部分成交的Fill。"""
        broker = _make_mock_broker(total_asset=100_000.0, cash=100_000.0)
        cancel_called: list[int] = []

        def place_and_partial(code, direction, volume, price, price_type="limit", remark=""):
            oid = 10
            # 模拟50%成交（100/200），不触发done
            threading.Timer(
                0.01,
                lambda: adapter._collector.on_trade(
                    {
                        "order_id": oid,
                        "traded_volume": volume // 2,
                        "traded_price": price,
                        "traded_amount": (volume // 2) * price,
                    }
                ),
            ).start()
            return oid

        def mock_cancel(order_id):
            cancel_called.append(order_id)
            return True

        broker.place_order.side_effect = place_and_partial
        broker.cancel_order.side_effect = mock_cancel
        adapter = QMTExecutionAdapter(broker)

        # 用极短超时（避免测试慢）
        import engines.qmt_execution_adapter as mod

        orig_timeout = mod.ORDER_TIMEOUT_SEC
        mod.ORDER_TIMEOUT_SEC = 0.5
        try:
            fills, pending = adapter.execute_rebalance(
                {"000001.SZ": 0.5},
                date(2026, 3, 29),
                {"000001.SZ": 10.0},
            )
        finally:
            mod.ORDER_TIMEOUT_SEC = orig_timeout

        # 应有部分成交的Fill
        assert len(fills) == 1
        assert fills[0].shares > 0
        assert fills[0].shares < 5000  # 不是全量
        # 应调用了cancel_order
        assert len(cancel_called) == 1
        assert cancel_called[0] == 10

    def test_concurrent_trade_callbacks(self) -> None:
        """并发on_trade回调正确累积filled_volume（P0-2验证）。"""
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=5,
            code="000001.SZ",
            direction="buy",
            volume=300,
            price=10.0,
        )
        collector.register(tracker)

        # 模拟3个并发成交回调，各100股
        threads = []
        for i in range(3):
            t = threading.Thread(
                target=collector.on_trade,
                args=(
                    {
                        "order_id": 5,
                        "traded_volume": 100,
                        "traded_price": 10.0 + i * 0.01,
                        "traded_amount": 100 * (10.0 + i * 0.01),
                    },
                ),
            )
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert tracker.filled_volume == 300
        assert tracker.is_done
        assert tracker.event.is_set()

    def test_cleanup_unregisters_callbacks(self) -> None:
        """cleanup注销broker回调（P0-3验证）。"""
        broker = _make_mock_broker()
        adapter = QMTExecutionAdapter(broker)

        # 注册后应有回调
        assert len(broker._trade_callbacks) == 1
        assert len(broker._order_callbacks) == 1
        assert len(broker._error_callbacks) == 1

        adapter.cleanup()

        # cleanup后应已注销
        assert len(broker._trade_callbacks) == 0
        assert len(broker._order_callbacks) == 0
        assert len(broker._error_callbacks) == 0

    def test_cancel_with_partial_fill_no_error(self) -> None:
        """部撤(status=50)不设error，部分成交仍返回Fill。"""
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=6,
            code="000001.SZ",
            direction="buy",
            volume=200,
            price=10.0,
        )
        collector.register(tracker)

        # 先收到100股成交
        collector.on_trade(
            {
                "order_id": 6,
                "traded_volume": 100,
                "traded_price": 10.05,
                "traded_amount": 1005.0,
            }
        )
        # 再收到部撤通知
        collector.on_order(
            {
                "order_id": 6,
                "order_status": 53,  # 部撤 (50=已报/pending, 53=部撤/final)
            }
        )

        assert tracker.is_done
        assert tracker.error is None  # 部撤不设error
        assert tracker.filled_volume == 100

    def test_on_order_status_55_partial_fill_stays_pending(self) -> None:
        """F19 根因回归 (ADR-011): status=55 '部成' 是 pending, 不应提前 done.

        原 bug: QMT_STATUS[55]=("final", "部成") → on_order(55) 触发 event.set() →
        wait() 提前退出 → 后续成交回调被吞 → 4-17 9663 股丢失 trade_log.
        修复后: 55 是 pending, on_order(55) 只更新状态不触发 done, 等真正终态 56.
        """
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=100,
            code="002441.SZ",
            direction="buy",
            volume=4800,
            price=10.15,
        )
        collector.register(tracker)

        # QMT 推送 "部成" 回报 (实盘首个部成回调)
        collector.on_order(
            {
                "order_id": 100,
                "order_status": 55,  # 部成 — 修复后应为 pending
                "stock_code": "002441.SZ",
            }
        )

        # 关键断言: 55 不应提前结束等待
        assert not tracker.is_done, "status=55 部成是 pending, 不应触发 done"
        assert not tracker.event.is_set(), "status=55 不应 event.set()"
        assert tracker.error is None

    def test_f19_scenario_multiple_fills_full_aggregation(self) -> None:
        """F19 真实场景回归: 2 个 on_trade + 1 个 on_order(55) + 1 个 on_order(56).

        原 bug 行为: on_order(55) 提前 event.set() → 后续 on_trade 虽被记录
        但 wait() 已退出, _FillCollector 之外的 wait 循环会提前看到 is_done=True.
        修复后: 55 是 pending, is_done 只由 on_trade 累积达 volume 或 on_order(56)
        触发, 完整聚合 4800 股.

        模拟 4-17 002441.SZ order_id=1090520685 回调序列 (qmt-data-stderr.log):
          09:31:10.369 成交回报 1200 股
          09:31:10.415 成交回报 3600 股 (累计 4800)
          09:31:10.415 委托回报 status=56 traded=4800/4800
        实盘中间还会有 status=55 部成回报 (已验证 qmt-data-stderr.log).
        """
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=1090520685,
            code="002441.SZ",
            direction="buy",
            volume=4800,
            price=10.15,
        )
        collector.register(tracker)

        # 序列 1: 首笔成交 1200 股
        collector.on_trade(
            {
                "order_id": 1090520685,
                "traded_volume": 1200,
                "traded_price": 10.15,
                "traded_amount": 12180.0,
            }
        )
        assert not tracker.is_done, "首笔 1200/4800 不应 done"
        assert tracker.filled_volume == 1200

        # 序列 2: QMT 推送 "部成" 回报 (原 bug 在此提前退出)
        collector.on_order(
            {
                "order_id": 1090520685,
                "order_status": 55,  # 部成 — 修复后 pending, 不提前触发 done
                "stock_code": "002441.SZ",
            }
        )
        assert not tracker.is_done, "on_order(55) 不应提前触发 done (F19 根因)"
        assert not tracker.event.is_set(), "on_order(55) 不应 event.set()"

        # 序列 3: 第二笔成交 3600 股 (原 bug 下此回调仍会累加但 wait() 已退出)
        collector.on_trade(
            {
                "order_id": 1090520685,
                "traded_volume": 3600,
                "traded_price": 10.14,
                "traded_amount": 36504.0,
            }
        )
        # 累计 4800 == volume → on_trade 自己触发 done (filled_volume >= volume 分支)
        assert tracker.is_done, "累计 4800 股应触发 done"
        assert tracker.filled_volume == 4800
        assert tracker.event.is_set(), "完整聚合后 event 应 set (wait() 放行)"

    @pytest.mark.parametrize(
        "status_code,label,expected_error_substr",
        [
            (53, "部撤", None),
            (54, "已撤", None),
            (56, "已成", None),
            (57, "废单", "废单"),  # status=57 还会设 error
        ],
    )
    def test_on_order_terminal_statuses_still_trigger_done(
        self,
        status_code: int,
        label: str,
        expected_error_substr: str | None,
    ) -> None:
        """确认修复未误伤: 53/54/56/57 仍然是 final, on_order 仍触发 done."""
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=200 + status_code,
            code="000001.SZ",
            direction="buy",
            volume=100,
            price=10.0,
        )
        collector.register(tracker)

        collector.on_order(
            {
                "order_id": 200 + status_code,
                "order_status": status_code,
                "order_remark": "资金不足" if status_code == 57 else "",
            }
        )

        assert tracker.is_done, f"status={status_code}({label}) 应触发 done"
        assert tracker.event.is_set(), f"status={status_code}({label}) 应 event.set()"
        if expected_error_substr:
            assert expected_error_substr in (tracker.error or ""), (
                f"status={status_code} 应设 error 含 '{expected_error_substr}'"
            )
        else:
            assert tracker.error is None, f"status={status_code}({label}) 不应设 error"

    @pytest.mark.parametrize(
        "status_code,label",
        [
            (48, "未报"),
            (49, "待报"),
            (50, "已报"),
            (51, "已报待撤"),
            (52, "部成待撤"),
            # 55 (部成) 已由 test_on_order_status_55_partial_fill_stays_pending 专项覆盖
        ],
    )
    def test_on_order_pending_statuses_do_not_trigger_done(
        self,
        status_code: int,
        label: str,
    ) -> None:
        """QMT pending 状态码回归: 48/49/50/51/52 不应提前触发 done.

        与 status=55 的 F19 专项测试互补, 防止未来 dict 改动再次把 pending
        错标 final. 52 "部成待撤" 特别重要 — 语义与 55 最相近, 最易混淆.
        """
        collector = _FillCollector()
        tracker = _OrderTracker(
            order_id=300 + status_code,
            code="000001.SZ",
            direction="buy",
            volume=100,
            price=10.0,
        )
        collector.register(tracker)

        collector.on_order(
            {
                "order_id": 300 + status_code,
                "order_status": status_code,
                "stock_code": "000001.SZ",
            }
        )

        assert not tracker.is_done, f"status={status_code}({label}) 是 pending, 不应触发 done"
        assert not tracker.event.is_set(), f"status={status_code}({label}) 不应 event.set()"
        assert tracker.error is None, f"status={status_code}({label}) 不应设 error"


def _trigger_fill(adapter: QMTExecutionAdapter, order_id: int, volume: int, price: float) -> None:
    """辅助：触发adapter的collector成交回调。"""
    adapter._collector.on_trade(
        {
            "order_id": order_id,
            "traded_volume": volume,
            "traded_price": price,
            "traded_amount": volume * price,
        }
    )
