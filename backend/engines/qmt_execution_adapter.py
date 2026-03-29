"""QMT执行适配器 — 桥接target_weights到MiniQMTBroker逐单下单。

将PaperBroker风格的 target_weights → (list[Fill], list[PendingOrder]) 接口
适配到MiniQMTBroker的 place_order() + 异步回调模式。

核心流程:
1. 从QMT查询实时持仓和现金（QMT是live模式的持仓源）
2. 计算目标股数（复用SimBroker的整手约束逻辑）
3. 生成订单序列：先卖后买
4. 逐单调用MiniQMTBroker.place_order()
5. 通过_FillCollector收集异步回调的成交
6. 映射结果回Fill/PendingOrder

PT代码隔离: 此模块是全新文件，不修改任何现有代码。
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from engines.backtest_engine import Fill, PendingOrder

logger = logging.getLogger(__name__)

# 默认配置（与SimBroker一致）
LOT_SIZE = 100
COMMISSION_RATE = 0.0000854  # 万0.854
STAMP_TAX_RATE = 0.0005      # 千0.5(仅卖出)
TRANSFER_FEE_RATE = 0.00001  # 万0.1
ORDER_TIMEOUT_SEC = 60.0     # 单笔订单等待成交超时


@dataclass
class _OrderTracker:
    """跟踪单笔订单的状态和成交。"""
    order_id: int
    code: str
    direction: str
    volume: int
    price: float
    filled_volume: int = 0
    filled_price: float = 0.0
    filled_amount: float = 0.0
    is_done: bool = False
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    event: threading.Event = field(default_factory=threading.Event)


class _FillCollector:
    """收集QMT异步回调的成交信息。

    注册为MiniQMTBroker的trade/order/error回调,
    将异步成交事件同步到主线程的_OrderTracker。
    所有tracker字段的修改都在tracker.lock内完成（P0-2 fix）。
    """

    def __init__(self) -> None:
        self._trackers: dict[int, _OrderTracker] = {}  # order_id → tracker
        self._lock = threading.Lock()

    def register(self, tracker: _OrderTracker) -> None:
        """注册一个订单跟踪器。"""
        with self._lock:
            self._trackers[tracker.order_id] = tracker

    def on_trade(self, trade: dict[str, Any]) -> None:
        """成交回调（在xtquant回调线程中执行）。"""
        order_id = trade.get("order_id", -1)
        with self._lock:
            tracker = self._trackers.get(order_id)
        if tracker is None:
            return
        with tracker.lock:
            tracker.filled_volume += trade.get("traded_volume", 0)
            tracker.filled_price = trade.get("traded_price", 0)
            tracker.filled_amount += trade.get("traded_amount", 0)
            if tracker.filled_volume >= tracker.volume:
                tracker.is_done = True
                tracker.event.set()

    def on_order(self, order: dict[str, Any]) -> None:
        """委托状态变化回调。

        status含义(xtquant):
        - 56: 已撤 (CANCELLED)
        - 57: 废单 (REJECTED)
        - 50: 部撤
        """
        order_id = order.get("order_id", -1)
        with self._lock:
            tracker = self._trackers.get(order_id)
        if tracker is None:
            return
        status = order.get("order_status")
        with tracker.lock:
            # 终态：已撤/废单/部撤 — 标记done但不覆盖已有的filled数据
            if status in (56, 57, 50):
                tracker.is_done = True
                if status == 57:
                    tracker.error = f"废单: {order.get('order_remark', '')}"
                # 56(已撤)/50(部撤) 不设error，因为可能有部分成交
                tracker.event.set()

    def on_error(self, error: dict[str, Any]) -> None:
        """下单失败回调。"""
        order_id = error.get("order_id", -1)
        with self._lock:
            tracker = self._trackers.get(order_id)
        if tracker is None:
            return
        with tracker.lock:
            tracker.is_done = True
            tracker.error = f"下单失败: {error.get('error_msg', 'unknown')}"
            tracker.event.set()

    def unregister_all(self) -> None:
        """清理所有跟踪器。"""
        with self._lock:
            self._trackers.clear()


class QMTExecutionAdapter:
    """QMT执行适配器。

    将target_weights转换为QMT逐单下单，收集成交后返回
    与PaperBroker兼容的 (list[Fill], list[PendingOrder]) 结果。
    """

    def __init__(self, broker: Any) -> None:
        """初始化适配器。

        Args:
            broker: MiniQMTBroker实例（已连接）。
        """
        self._broker = broker
        self._collector = _FillCollector()
        # 保存回调引用以便cleanup时注销（P0-3 fix）
        self._on_trade = self._collector.on_trade
        self._on_order = self._collector.on_order
        self._on_error = self._collector.on_error
        # 注册回调
        self._broker.register_trade_callback(self._on_trade)
        self._broker.register_order_callback(self._on_order)
        self._broker.register_error_callback(self._on_error)

    def execute_rebalance(
        self,
        target_weights: dict[str, float],
        exec_date: date,
        prices: dict[str, float],
        signal_date: date | None = None,
    ) -> tuple[list[Fill], list[PendingOrder]]:
        """执行调仓。

        Args:
            target_weights: {code: weight} 目标权重。
            exec_date: 执行日期。
            prices: {code: price} 当日开盘价（用于下限价单）。
            signal_date: 信号生成日期。

        Returns:
            (成交列表, 封板/失败的pending_orders列表)
        """
        # 1. 从QMT查询实时持仓和总资产
        current_positions = self._broker.get_positions()  # {code: shares}
        total_value = self._broker.get_total_value({})     # QMT直接查总资产
        cash = self._broker.get_cash()

        logger.info(
            f"[QMTAdapter] 开始调仓: 总资产={total_value:.0f}, "
            f"现金={cash:.0f}, 持仓={len(current_positions)}只, "
            f"目标={len(target_weights)}只"
        )

        # 2. 计算目标股数（整手约束）
        target_shares: dict[str, int] = {}
        for code, weight in target_weights.items():
            price = prices.get(code, 0)
            if price > 0:
                target_value = total_value * weight
                shares = int(target_value / price / LOT_SIZE) * LOT_SIZE
                if shares > 0:
                    target_shares[code] = shares

        # 3. 计算订单：先卖后买
        sell_orders: list[tuple[str, int, float]] = []  # (code, shares, price)
        buy_orders: list[tuple[str, int, float, float]] = []  # (code, shares, price, weight)

        # 3a. 卖出：当前持仓中需要减少或清仓的
        for code, curr_shares in current_positions.items():
            target_s = target_shares.get(code, 0)
            if curr_shares > target_s:
                sell_shares = curr_shares - target_s
                price = prices.get(code, 0)
                if price > 0 and sell_shares > 0:
                    sell_orders.append((code, sell_shares, price))

        # 3b. 买入：需要增加或新建仓的
        for code, target_s in target_shares.items():
            curr_shares = current_positions.get(code, 0)
            if target_s > curr_shares:
                buy_shares = target_s - curr_shares
                price = prices.get(code, 0)
                weight = target_weights.get(code, 0)
                if price > 0 and buy_shares > 0:
                    buy_orders.append((code, buy_shares, price, weight))

        # 按金额从大到小排序买入（优先执行大单）
        buy_orders.sort(key=lambda x: -(x[1] * x[2]))

        logger.info(
            f"[QMTAdapter] 订单计划: {len(sell_orders)}笔卖出, "
            f"{len(buy_orders)}笔买入"
        )

        fills: list[Fill] = []
        pending: list[PendingOrder] = []

        # 4. 执行卖出
        for code, shares, price in sell_orders:
            fill = self._place_and_wait(code, "sell", shares, price, exec_date)
            if fill:
                fills.append(fill)
            else:
                logger.warning(f"[QMTAdapter] 卖出失败/超时: {code} {shares}股")

        # 5. 执行买入
        for code, shares, price, weight in buy_orders:
            fill = self._place_and_wait(code, "buy", shares, price, exec_date)
            if fill:
                fills.append(fill)
            else:
                # 买入失败 → 记录为PendingOrder
                pending.append(PendingOrder(
                    code=code,
                    signal_date=signal_date or exec_date,
                    exec_date=exec_date,
                    target_weight=weight,
                    original_score=shares * price,
                ))
                logger.info(f"[QMTAdapter] 买入失败，加入pending: {code} {shares}股")

        # 6. 清理trackers（回调在cleanup中注销）
        self._collector.unregister_all()

        logger.info(
            f"[QMTAdapter] 调仓完成: {len(fills)}笔成交, "
            f"{len(pending)}笔pending"
        )
        return fills, pending

    def _place_and_wait(
        self,
        code: str,
        direction: str,
        volume: int,
        price: float,
        exec_date: date,
    ) -> Fill | None:
        """下单并等待成交。

        超时后无论是否有部分成交都会撤单（P0-1 fix）。
        基于实际filled_volume构建Fill，部分成交也记录。

        Args:
            code: 股票代码。
            direction: "buy"或"sell"。
            volume: 数量（股）。
            price: 限价。
            exec_date: 执行日期。

        Returns:
            Fill对象（含部分成交），完全失败返回None。
        """
        order_id = self._broker.place_order(
            code=code,
            direction=direction,
            volume=volume,
            price=price,
            price_type="limit",
            remark=f"rebal_{exec_date}",
        )

        if order_id < 0:
            logger.error(f"[QMTAdapter] 下单失败: {code} {direction} {volume}股")
            return None

        # 注册跟踪器
        tracker = _OrderTracker(
            order_id=order_id,
            code=code,
            direction=direction,
            volume=volume,
            price=price,
        )
        self._collector.register(tracker)

        # 等待成交或超时
        tracker.event.wait(timeout=ORDER_TIMEOUT_SEC)

        # P0-1 fix: 超时后总是撤单（无论部分成交与否），防止悬空委托
        with tracker.lock:
            filled_volume = tracker.filled_volume
            filled_price = tracker.filled_price
            error = tracker.error
            is_fully_filled = filled_volume >= volume

        if not is_fully_filled:
            # 未完全成交（超时或部撤） → 撤单
            logger.info(
                f"[QMTAdapter] 未完全成交: {code} {direction} "
                f"filled={filled_volume}/{volume}, 撤单"
            )
            self._broker.cancel_order(order_id)
            time.sleep(2)  # 等待撤单回调

        # 废单/下单失败 且 无任何成交 → 返回None
        if error and filled_volume <= 0:
            logger.warning(
                f"[QMTAdapter] 订单异常: {code} {direction} "
                f"order_id={order_id}, error={error}"
            )
            return None

        # 完全未成交（超时+撤单成功） → 返回None
        if filled_volume <= 0:
            logger.warning(
                f"[QMTAdapter] 超时未成交: {code} {direction} order_id={order_id}"
            )
            return None

        # 构建Fill（含部分成交）
        amount = filled_price * filled_volume

        if direction == "sell":
            commission = max(amount * COMMISSION_RATE, 5.0)
            tax = amount * STAMP_TAX_RATE
            transfer_fee = amount * TRANSFER_FEE_RATE
            total_cost = commission + tax + transfer_fee
            slippage = price - filled_price  # 卖出: 期望价 - 实际价
        else:
            commission = max(amount * COMMISSION_RATE, 5.0)
            tax = 0.0
            transfer_fee = amount * TRANSFER_FEE_RATE
            total_cost = commission + transfer_fee
            slippage = filled_price - price  # 买入: 实际价 - 期望价

        slippage_bps = (slippage / price * 10000) if price > 0 else 0

        if filled_volume < volume:
            logger.info(
                f"[QMTAdapter] 部分成交: {code} {direction} "
                f"{filled_volume}/{volume}股 @{filled_price:.3f}"
            )

        return Fill(
            code=code,
            trade_date=exec_date,
            direction=direction,
            price=filled_price,
            shares=filled_volume,
            amount=amount,
            commission=commission,
            tax=tax,
            slippage=slippage_bps,
            total_cost=total_cost,
        )

    def cleanup(self) -> None:
        """清理回调注册和trackers（P0-3 fix）。"""
        import contextlib

        self._collector.unregister_all()
        # 注销broker上的回调，防止多次实例化时回调累积
        with contextlib.suppress(ValueError, AttributeError):
            self._broker._trade_callbacks.remove(self._on_trade)
        with contextlib.suppress(ValueError, AttributeError):
            self._broker._order_callbacks.remove(self._on_order)
        with contextlib.suppress(ValueError, AttributeError):
            self._broker._error_callbacks.remove(self._on_error)
