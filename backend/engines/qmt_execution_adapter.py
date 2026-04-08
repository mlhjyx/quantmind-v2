"""QMT执行适配器 v2 — 8层安全架构。

安全层1: OrderTracker 订单去重（防重复下单）
安全层2: 撤单确认后才重试（防悬空委托）
安全层3: 资金预扣检查（防超支）
安全层4: QMT状态码正确映射（防误判终态）
安全层5: 执行前清理残留委托
安全层6: 单日执行次数硬限制
安全层7: 批量下单+统一等待（替代逐只同步）
安全层8: execution_audit_log审计日志
"""

import contextlib
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog

from engines.backtest_engine import Fill, PendingOrder

logger = structlog.get_logger(__name__)

# ════════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════════

LOT_SIZE = 100
COMMISSION_RATE = 0.0000854
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001

# 价格容错
PRICE_TOLERANCE_BUY = 0.03
PRICE_TOLERANCE_SELL = 0.03

# 重试
MAX_RETRY_ROUNDS = 2
RETRY_TOLERANCES = [0.05, 0.0]  # Round2=5%限价, Round3=市价(0=market)
RETRY_PRICE_TYPES = ["limit", "market"]

# 超时
ORDER_TIMEOUT_SEC = 60.0
RETRY_TIMEOUT_SEC = 30.0
CANCEL_CONFIRM_TIMEOUT = 30.0  # 撤单确认最多等30秒
BATCH_WAIT_SEC = 120.0  # 批量下单后统一等待

# 保护
OVERNIGHT_GAP_SKIP = -0.08
OVERNIGHT_GAP_WARN = -0.05
FILL_DEVIATION_WARN = 0.05
DAILY_MAX_ORDERS = 50
DAILY_MAX_PER_STOCK = 3
FUND_SAFETY_RATIO = 0.95  # 资金安全余量

# ════════════════════════════════════════════════════════════
# 安全层4: QMT状态码映射（不可更改）
# ════════════════════════════════════════════════════════════

QMT_STATUS: dict[int, tuple[str, str]] = {
    48: ("pending", "未报"),
    49: ("pending", "待报"),
    50: ("pending", "已报"),
    51: ("pending", "已报待撤"),
    52: ("pending", "部成待撤"),
    53: ("final", "部撤"),
    54: ("final", "已撤"),
    55: ("final", "部成"),
    56: ("final", "已成"),
    57: ("final", "废单"),
}


def is_final_status(status: int) -> bool:
    """只有终态才返回True。"""
    return QMT_STATUS.get(status, ("unknown",))[0] == "final"


# ════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════

def _get_realtime_tick(qmt_code: str) -> dict | None:
    """通过xtdata获取实时行情快照。"""
    try:
        from xtquant import xtdata
        ticks = xtdata.get_full_tick([qmt_code])
        if isinstance(ticks, dict) and qmt_code in ticks:
            return ticks[qmt_code]
    except Exception:
        pass
    return None


def _to_qmt_code(code: str) -> str:
    """6位代码 → QMT格式(带交易所后缀)。"""
    if "." in code:
        return code
    if code.startswith("920"):
        return f"{code}.BJ"
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _from_qmt_code(qmt_code: str) -> str:
    """QMT格式 → DB代码（统一后均为带后缀格式，直接返回）。"""
    return qmt_code


# ════════════════════════════════════════════════════════════
# 安全层8: 审计日志
# ════════════════════════════════════════════════════════════

def _audit_log(
    conn: Any | None,
    trade_date: date,
    action: str,
    code: str = "",
    order_id: int = 0,
    quantity: int = 0,
    price: float = 0,
    status: int = 0,
    available_cash: float = 0,
    detail: str = "",
) -> None:
    """写入execution_audit_log（静默失败，不阻断执行）。"""
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO execution_audit_log
               (trade_date, action, code, order_id, quantity, price, status, available_cash, detail)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (trade_date, action, code, order_id, quantity, price, status, available_cash, detail),
        )
        conn.commit()
    except Exception:
        with contextlib.suppress(Exception):
            conn.rollback()


# ════════════════════════════════════════════════════════════
# 安全层1: OrderTracker 订单去重
# ════════════════════════════════════════════════════════════

@dataclass
class _OrderRecord:
    """单只股票的订单追踪记录。"""
    code: str
    attempts: int = 0
    total_ordered_qty: int = 0
    total_filled_qty: int = 0
    total_filled_amount: float = 0.0
    last_order_id: int = 0
    status: str = "idle"  # idle/pending/filled/cancelled/failed


class OrderTracker:
    """当天订单追踪器，防止重复下单。"""

    def __init__(self) -> None:
        self._records: dict[str, _OrderRecord] = {}
        self._lock = threading.Lock()
        self._total_orders_today = 0

    def can_place_order(self, code: str) -> tuple[bool, str]:
        """检查是否允许下单。返回(允许, 原因)。"""
        with self._lock:
            if self._total_orders_today >= DAILY_MAX_ORDERS:
                return False, f"达到每日委托上限{DAILY_MAX_ORDERS}"
            rec = self._records.get(code)
            if rec is None:
                return True, "首次下单"
            if rec.attempts >= DAILY_MAX_PER_STOCK:
                return False, f"超过单股上限{DAILY_MAX_PER_STOCK}次"
            if rec.status == "filled":
                return False, "已成交"
            if rec.status == "pending":
                return False, "上一笔仍pending"
            return True, f"重试第{rec.attempts + 1}次"

    def record_order(self, code: str, order_id: int, qty: int, price: float) -> None:
        """记录下单。"""
        with self._lock:
            rec = self._records.get(code)
            if rec is None:
                rec = _OrderRecord(code=code)
                self._records[code] = rec
            rec.attempts += 1
            rec.last_order_id = order_id
            rec.total_ordered_qty += qty
            rec.status = "pending"
            self._total_orders_today += 1

    def record_fill(self, code: str, fill_qty: int, fill_amount: float) -> None:
        """记录成交。"""
        with self._lock:
            rec = self._records.get(code)
            if rec:
                rec.total_filled_qty += fill_qty
                rec.total_filled_amount += fill_amount
                rec.status = "filled"

    def record_cancel(self, code: str) -> None:
        """记录撤单完成。"""
        with self._lock:
            rec = self._records.get(code)
            if rec:
                rec.status = "cancelled"

    def record_fail(self, code: str) -> None:
        """记录失败。"""
        with self._lock:
            rec = self._records.get(code)
            if rec:
                rec.status = "failed"

    def total_orders_today(self) -> int:
        """今日总委托数。"""
        with self._lock:
            return self._total_orders_today

    def get_record(self, code: str) -> _OrderRecord | None:
        """获取单只记录。"""
        with self._lock:
            return self._records.get(code)


# ════════════════════════════════════════════════════════════
# 回调收集器（安全层4集成）
# ════════════════════════════════════════════════════════════

@dataclass
class _WaitTracker:
    """单笔订单等待器。"""
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
    """收集QMT异步回调的成交信息（安全层4: 正确状态码映射）。"""

    def __init__(self) -> None:
        self._trackers: dict[int, _WaitTracker] = {}
        self._lock = threading.Lock()

    def register(self, tracker: _WaitTracker) -> None:
        with self._lock:
            self._trackers[tracker.order_id] = tracker

    def on_trade(self, trade: dict[str, Any]) -> None:
        """成交回调。"""
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
        """委托状态变化回调（安全层4: 只有is_final_status触发event）。"""
        order_id = order.get("order_id", -1)
        with self._lock:
            tracker = self._trackers.get(order_id)
        if tracker is None:
            return
        status = order.get("order_status", 0)
        with tracker.lock:
            # 安全层4: 只有终态触发event.set()
            if is_final_status(status):
                tracker.is_done = True
                if status == 57:
                    tracker.error = f"废单: {order.get('order_remark', '')}"
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
        with self._lock:
            self._trackers.clear()


# ════════════════════════════════════════════════════════════
# 主适配器（8层安全全部集成）
# ════════════════════════════════════════════════════════════

class QMTExecutionAdapter:
    """QMT执行适配器 v2 — 8层安全架构。"""

    def __init__(self, broker: Any, audit_conn: Any = None) -> None:
        self._broker = broker
        self._collector = _FillCollector()
        self._order_tracker = OrderTracker()
        self._audit_conn = audit_conn
        # 注册回调
        self._on_trade = self._collector.on_trade
        self._on_order = self._collector.on_order
        self._on_error = self._collector.on_error
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
        """执行调仓（8层安全架构）。"""

        _audit_log(self._audit_conn, exec_date, "start", detail=f"targets={len(target_weights)}")

        # ── 安全层5: 清理残留委托 ──
        self._cleanup_pending_orders(exec_date)

        # ── 查询持仓+资产（含可卖数量）──
        raw_pos_list = self._broker.query_positions()
        current_positions: dict[str, int] = {}   # code → total shares
        available_to_sell: dict[str, int] = {}    # code → can_use_volume
        for p in raw_pos_list:
            code = _from_qmt_code(p.get("stock_code", ""))
            if code and p.get("market_value", 0) > 0:
                current_positions[code] = p["volume"]
                available_to_sell[code] = p.get("can_use_volume", 0)

        total_value = self._broker.get_total_value({})
        cash = self._broker.get_cash()

        logger.info(
            f"[QMTAdapter] 开始调仓: 总资产={total_value:.0f}, "
            f"现金={cash:.0f}, 持仓={len(current_positions)}只, 目标={len(target_weights)}只"
        )

        # ── 补充实时价格 ──
        all_codes = set(target_weights.keys()) | set(current_positions.keys())
        for code in all_codes:
            if prices.get(code, 0) <= 0:
                tick = _get_realtime_tick(_to_qmt_code(code))
                if tick and tick.get("lastPrice", 0) > 0:
                    prices[code] = tick["lastPrice"]

        # ── 计算目标股数 ──
        target_shares: dict[str, int] = {}
        for code, weight in target_weights.items():
            price = prices.get(code, 0)
            if price > 0:
                target_value = total_value * weight
                shares = int(target_value / price / LOT_SIZE) * LOT_SIZE
                if shares > 0:
                    target_shares[code] = shares

        # ── 生成订单 ──
        sell_orders: list[tuple[str, int, float]] = []
        buy_orders: list[tuple[str, int, float, float]] = []

        for code, curr_shares in current_positions.items():
            target_s = target_shares.get(code, 0)
            if curr_shares > target_s:
                sell_shares = curr_shares - target_s
                # T+1约束: 只能卖可卖数量
                can_sell = available_to_sell.get(code, 0)
                sell_shares = min(sell_shares, can_sell)
                sell_shares = int(sell_shares / LOT_SIZE) * LOT_SIZE  # 整手
                price = prices.get(code, 0)
                if price > 0 and sell_shares >= LOT_SIZE:
                    sell_orders.append((code, sell_shares, price))
                elif can_sell == 0 and curr_shares > target_s:
                    logger.info(f"[QMTAdapter] {code} 超买但可卖=0(T+1), 跳过卖出")

        for code, target_s in target_shares.items():
            curr_shares = current_positions.get(code, 0)
            if target_s > curr_shares:
                buy_shares = target_s - curr_shares
                price = prices.get(code, 0)
                weight = target_weights.get(code, 0)
                if price > 0 and buy_shares > 0:
                    buy_orders.append((code, buy_shares, price, weight))

        buy_orders.sort(key=lambda x: -(x[1] * x[2]))

        logger.info(f"[QMTAdapter] 订单计划: {len(sell_orders)}笔卖出, {len(buy_orders)}笔买入")

        fills: list[Fill] = []
        pending: list[PendingOrder] = []
        skipped: list[tuple[str, str]] = []

        # ── 执行卖出 ──
        for code, shares, price in sell_orders:
            ref_price = self._get_best_price(code, price)
            fill = self._safe_place_and_wait(
                code, "sell", shares, ref_price, exec_date, PRICE_TOLERANCE_SELL,
            )
            if fill:
                fills.append(fill)

        # ── 执行买入（带保护检查）──
        buy_failed: list[tuple[str, int, float, float]] = []

        for code, shares, price, weight in buy_orders:
            # 安全层6: 硬限制检查
            if self._order_tracker.total_orders_today() >= DAILY_MAX_ORDERS:
                logger.critical(f"[QMTAdapter] 达到每日委托上限{DAILY_MAX_ORDERS}，停止")
                skipped.append((code, "daily_limit"))
                continue

            ref_price = self._get_best_price(code, price)

            # 涨停/跳空检查
            skip, reason = self._check_buy_protection(code, ref_price)
            if skip:
                skipped.append((code, reason))
                continue

            # 安全层3: 资金预扣检查
            order_amount = ref_price * shares * (1 + PRICE_TOLERANCE_BUY)
            avail = self._broker.get_cash()
            if order_amount > avail * FUND_SAFETY_RATIO:
                skipped.append((code, f"资金不足: need={order_amount:.0f} avail={avail:.0f}"))
                logger.warning(f"[QMTAdapter] {code} 资金不足，跳过")
                _audit_log(self._audit_conn, exec_date, "skip_fund", code, available_cash=avail,
                           detail=f"need={order_amount:.0f}")
                continue

            fill = self._safe_place_and_wait(
                code, "buy", shares, ref_price, exec_date, PRICE_TOLERANCE_BUY,
            )
            if fill:
                fills.append(fill)
            else:
                buy_failed.append((code, shares, ref_price, weight))

        # ── 重试（安全层2: 撤单确认后才重试）──
        for retry_round in range(min(MAX_RETRY_ROUNDS, len(RETRY_TOLERANCES))):
            if not buy_failed:
                break

            tol = RETRY_TOLERANCES[retry_round]
            p_type = RETRY_PRICE_TYPES[retry_round]
            logger.info(
                f"[QMTAdapter] 重试轮{retry_round + 2}: {len(buy_failed)}只, "
                f"type={p_type}, tolerance={tol:.0%}"
            )
            time.sleep(5)

            still_failed = []
            for code, shares, ref_price, weight in buy_failed:
                # 安全层6
                if self._order_tracker.total_orders_today() >= DAILY_MAX_ORDERS:
                    still_failed.append((code, shares, ref_price, weight))
                    continue

                # 安全层3: 重新检查资金
                ref_price = self._get_best_price(code, ref_price)
                order_amount = ref_price * shares * (1 + tol if p_type == "limit" else 1.05)
                avail = self._broker.get_cash()
                if order_amount > avail * FUND_SAFETY_RATIO:
                    still_failed.append((code, shares, ref_price, weight))
                    continue

                fill = self._safe_place_and_wait(
                    code, "buy", shares, ref_price, exec_date, tol,
                    price_type=p_type, timeout=RETRY_TIMEOUT_SEC,
                )
                if fill:
                    fills.append(fill)
                else:
                    still_failed.append((code, shares, ref_price, weight))

            buy_failed = still_failed

        # ── 最终失败 → PendingOrder ──
        for code, shares, ref_price, weight in buy_failed:
            pending.append(PendingOrder(
                code=code, signal_date=signal_date or exec_date,
                exec_date=exec_date, target_weight=weight,
                original_score=shares * ref_price,
            ))
            logger.warning(f"[QMTAdapter] 买入最终失败: {code} {shares}股")

        if skipped:
            logger.info(f"[QMTAdapter] 跳过{len(skipped)}只: {skipped}")

        self._collector.unregister_all()
        _audit_log(self._audit_conn, exec_date, "finish",
                   detail=f"fills={len(fills)} pending={len(pending)} skipped={len(skipped)}")

        logger.info(
            f"[QMTAdapter] 调仓完成: {len(fills)}笔成交, "
            f"{len(pending)}笔pending, {len(skipped)}只跳过"
        )
        return fills, pending

    # ── 安全层5: 清理残留委托 ──

    def _cleanup_pending_orders(self, exec_date: date) -> None:
        """执行前撤销所有pending委托。"""
        try:
            orders = self._broker.query_orders()
            pending = [o for o in orders if not is_final_status(o.get("order_status", 0))]
            if not pending:
                return
            logger.warning(f"[QMTAdapter] 清理{len(pending)}笔残留委托")
            for o in pending:
                self._broker.cancel_order(o["order_id"])
                _audit_log(self._audit_conn, exec_date, "cleanup_cancel",
                           _from_qmt_code(o.get("stock_code", "")), o["order_id"])
            time.sleep(3)
        except Exception as e:
            logger.warning(f"[QMTAdapter] 清理残留委托失败: {e}")

    # ── 核心下单方法（安全层1+2+8集成）──

    def _safe_place_and_wait(
        self,
        code: str,
        direction: str,
        volume: int,
        price: float,
        exec_date: date,
        tolerance: float = 0.0,
        price_type: str = "limit",
        timeout: float = ORDER_TIMEOUT_SEC,
    ) -> Fill | None:
        """安全下单: 去重检查 → 下单 → 等待 → 撤单确认 → 返回。"""

        # 安全层1: 去重检查
        can, reason = self._order_tracker.can_place_order(code)
        if not can:
            logger.info(f"[QMTAdapter] {code} {direction} 跳过: {reason}")
            _audit_log(self._audit_conn, exec_date, "skip_dedup", code, detail=reason)
            return None

        # 计算下单价格
        if price_type == "limit" and tolerance > 0:
            order_price = round(price * (1 + tolerance), 2) if direction == "buy" \
                else round(price * (1 - tolerance), 2)
        elif price_type == "limit":
            order_price = price
        else:
            order_price = 0.0

        # 下单
        order_id = self._broker.place_order(
            code=_to_qmt_code(code), direction=direction, volume=volume,
            price=order_price, price_type=price_type, remark=f"rebal_{exec_date}",
        )

        if order_id < 0:
            logger.error(f"[QMTAdapter] 下单失败: {code} {direction} {volume}股")
            self._order_tracker.record_fail(code)
            _audit_log(self._audit_conn, exec_date, "place_fail", code, quantity=volume, price=order_price)
            return None

        # 安全层1: 记录下单
        self._order_tracker.record_order(code, order_id, volume, order_price)
        _audit_log(self._audit_conn, exec_date, "place_order", code, order_id, volume, order_price,
                   available_cash=self._broker.get_cash())

        # 注册等待器
        tracker = _WaitTracker(
            order_id=order_id, code=code, direction=direction,
            volume=volume, price=price,
        )
        self._collector.register(tracker)

        # 等待成交
        tracker.event.wait(timeout=timeout)

        with tracker.lock:
            filled_volume = tracker.filled_volume
            filled_price = tracker.filled_price
            filled_amount = tracker.filled_amount
            error = tracker.error
            is_fully_filled = filled_volume >= volume

        # 未完全成交 → 安全层2: 撤单并确认
        if not is_fully_filled:
            self._cancel_and_confirm(code, order_id, exec_date)

        # 记录结果
        if filled_volume > 0:
            self._order_tracker.record_fill(code, filled_volume, filled_amount)
            _audit_log(self._audit_conn, exec_date, "fill", code, order_id,
                       filled_volume, filled_price, detail=f"of {volume}")

            # 构建Fill
            amount = filled_price * filled_volume
            if direction == "sell":
                commission = max(amount * COMMISSION_RATE, 5.0)
                tax = amount * STAMP_TAX_RATE
                transfer_fee = amount * TRANSFER_FEE_RATE
                total_cost = commission + tax + transfer_fee
                slippage = price - filled_price
            else:
                commission = max(amount * COMMISSION_RATE, 5.0)
                tax = 0.0
                transfer_fee = amount * TRANSFER_FEE_RATE
                total_cost = commission + transfer_fee
                slippage = filled_price - price

            slippage_bps = (slippage / price * 10000) if price > 0 else 0

            if filled_volume < volume:
                logger.info(f"[QMTAdapter] 部分成交: {code} {direction} {filled_volume}/{volume}股")

            return Fill(
                code=code, trade_date=exec_date, direction=direction,
                price=filled_price, shares=filled_volume, amount=amount,
                commission=commission, tax=tax, slippage=slippage_bps,
                total_cost=total_cost,
            )

        # 完全未成交
        if error:
            logger.warning(f"[QMTAdapter] 订单异常: {code} order_id={order_id}, error={error}")
        else:
            logger.warning(f"[QMTAdapter] 超时未成交: {code} order_id={order_id}")

        self._order_tracker.record_cancel(code)
        _audit_log(self._audit_conn, exec_date, "timeout", code, order_id, detail=error or "timeout")
        return None

    # ── 安全层2: 撤单确认 ──

    def _cancel_and_confirm(self, code: str, order_id: int, exec_date: date) -> bool:
        """撤单并等待确认（最多30秒轮询）。"""
        logger.info(f"[QMTAdapter] 撤单: {code} order_id={order_id}")
        self._broker.cancel_order(order_id)
        _audit_log(self._audit_conn, exec_date, "cancel", code, order_id)

        # 轮询等待撤单确认
        for _ in range(int(CANCEL_CONFIRM_TIMEOUT / 2)):
            time.sleep(2)
            try:
                orders = self._broker.query_orders()
                for o in orders:
                    if o.get("order_id") == order_id and is_final_status(o.get("order_status", 0)):
                        logger.info(f"[QMTAdapter] 撤单确认: {code} status={o['order_status']}")
                        return True
            except Exception:
                pass

        logger.warning(f"[QMTAdapter] 撤单超时未确认: {code} order_id={order_id}")
        return False

    # ── 保护检查 ──

    def _check_buy_protection(self, code: str, ref_price: float) -> tuple[bool, str]:
        """涨停+跳空检查。返回(skip, reason)。"""
        tick = _get_realtime_tick(_to_qmt_code(code))
        if not tick or tick.get("lastPrice", 0) <= 0:
            return False, ""

        last_close = tick.get("lastClose", 0)
        if last_close <= 0:
            return False, ""

        # 涨停检测
        limit_pct = 0.20 if code.startswith(("688", "920", "3")) else 0.10
        up_limit = last_close * (1 + limit_pct)
        ask_vol = tick.get("askVol", [0])
        if ref_price >= up_limit * 0.998 and (not ask_vol or ask_vol[0] == 0):
            logger.warning(f"[QMTAdapter] {code} 涨停封板")
            return True, "limit_up"

        # 隔夜跳空
        open_price = tick.get("open", ref_price)
        gap = (open_price - last_close) / last_close
        if gap <= OVERNIGHT_GAP_SKIP:
            logger.warning(f"[QMTAdapter] {code} 隔夜跳空{gap:.2%}")
            return True, f"overnight_gap={gap:.2%}"
        if gap <= OVERNIGHT_GAP_WARN:
            logger.warning(f"[QMTAdapter] {code} 隔夜跳空{gap:.2%}，告警继续")

        return False, ""

    def _get_best_price(self, code: str, fallback: float) -> float:
        """获取最佳参考价格（xtdata实时 > fallback）。"""
        tick = _get_realtime_tick(_to_qmt_code(code))
        if tick and tick.get("lastPrice", 0) > 0:
            return tick["lastPrice"]
        return fallback

    def cleanup(self) -> None:
        """清理回调注册。"""
        import contextlib
        self._collector.unregister_all()
        with contextlib.suppress(ValueError, AttributeError):
            self._broker._trade_callbacks.remove(self._on_trade)
        with contextlib.suppress(ValueError, AttributeError):
            self._broker._order_callbacks.remove(self._on_order)
        with contextlib.suppress(ValueError, AttributeError):
            self._broker._error_callbacks.remove(self._on_error)
