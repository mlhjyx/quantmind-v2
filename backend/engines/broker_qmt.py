"""miniQMT实盘/模拟交易Broker — 对接国金miniQMT客户端。

通过xtquant SDK连接miniQMT交易端，提供下单、查询、撤单等功能。
遵循CLAUDE.md策略模式设计，与SimBroker/PaperBroker平行。

使用方式:
    broker = MiniQMTBroker(qmt_path="E:\\国金QMT交易端模拟\\userdata_mini",
                           account_id="81001102")
    broker.connect()
    broker.place_order("000001.SZ", "buy", 100, price=10.5)
    broker.disconnect()
"""

import asyncio
import hashlib
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.xtquant_path import ensure_xtquant_path
from engines.base_broker import BaseBroker

# Ensure xtquant path on sys.path at module load (idempotent).
# Before this fix: Mon 09:31 SH live-fire would hit
#   `ModuleNotFoundError: No module named 'xtquant'`
# inside MiniQMTBroker.connect() at line ~236 `from xtquant.xttrader import ...`
# because Celery workers + standalone Python invocations don't pre-call
# `ensure_xtquant_path()` (only qmt_data_service.py + realtime_risk_engine_service.py
# + scripts/emergency_close_all_positions.py + a few others do).
# This is the 5th 实证 sys.path drift pattern per LL-175 lesson 2 (different module
# but same architectural debt). Surfaced by P0 DingTalk alert "V3 L4 STAGED live
# broker wire FAILED" on 2026-05-17 ~18:30 SH.
ensure_xtquant_path()

logger = logging.getLogger("qmt_broker")


# ---------------------------------------------------------------------------
# 回调
# ---------------------------------------------------------------------------


class _QMTCallback:
    """xtquant回调实现，桥接到MiniQMTBroker的回调处理。"""

    def __init__(self, broker: "MiniQMTBroker"):
        self._broker = broker

    def on_disconnected(self) -> None:
        """连接断开回调。"""
        logger.warning("[QMT] 连接断开")
        self._broker._handle_disconnect()

    def on_stock_order(self, order: Any) -> None:
        """委托状态变化回调。"""
        logger.info(
            f"[QMT] 委托回报: order_id={order.order_id}, "
            f"code={order.stock_code}, status={order.order_status}, "
            f"traded={order.traded_volume}/{order.order_volume}"
        )
        for cb in self._broker._order_callbacks:
            try:
                cb(_order_to_dict(order))
            except Exception:
                logger.exception("[QMT] 外部委托回调异常")

    def on_stock_trade(self, trade: Any) -> None:
        """成交回报回调。"""
        logger.info(
            f"[QMT] 成交回报: order_id={trade.order_id}, "
            f"code={trade.stock_code}, price={trade.traded_price}, "
            f"volume={trade.traded_volume}"
        )
        for cb in self._broker._trade_callbacks:
            try:
                cb(_trade_to_dict(trade))
            except Exception:
                logger.exception("[QMT] 外部成交回调异常")

    def on_order_error(self, error: Any) -> None:
        """下单失败回调。"""
        logger.error(
            f"[QMT] 下单失败: order_id={error.order_id}, "
            f"error_id={error.error_id}, error_msg={error.error_msg}"
        )
        for cb in self._broker._error_callbacks:
            try:
                cb(
                    {
                        "order_id": error.order_id,
                        "error_id": error.error_id,
                        "error_msg": error.error_msg,
                    }
                )
            except Exception:
                logger.exception("[QMT] 外部错误回调异常")

    def on_account_status(self, status: Any) -> None:
        """账户状态变化回调（忽略）。"""
        pass


# ---------------------------------------------------------------------------
# 辅助函数：xtquant对象 → 标准化dict
# ---------------------------------------------------------------------------


def _asset_to_dict(asset: Any) -> dict[str, Any]:
    """XtAsset → dict。"""
    return {
        "cash": asset.cash,
        "frozen_cash": asset.frozen_cash,
        "market_value": asset.market_value,
        "total_asset": asset.total_asset,
    }


def _position_to_dict(pos: Any) -> dict[str, Any]:
    """XtPosition → dict。"""
    return {
        "stock_code": pos.stock_code,
        "volume": pos.volume,
        "can_use_volume": pos.can_use_volume,
        "avg_price": pos.open_price,  # xtquant用open_price不是avg_price
        "market_value": pos.market_value,
        "frozen_volume": pos.frozen_volume,
    }


def _order_to_dict(order: Any) -> dict[str, Any]:
    """XtOrder → dict。"""
    return {
        "order_id": order.order_id,
        "stock_code": order.stock_code,
        "order_type": order.order_type,
        "order_volume": order.order_volume,
        "price": order.price,
        "traded_volume": order.traded_volume,
        "traded_price": order.traded_price,
        "order_status": order.order_status,
        "order_remark": order.order_remark,
    }


def _trade_to_dict(trade: Any) -> dict[str, Any]:
    """XtTrade → dict。"""
    return {
        "order_id": trade.order_id,
        "stock_code": trade.stock_code,
        "traded_price": trade.traded_price,
        "traded_volume": trade.traded_volume,
        "traded_amount": trade.traded_amount,
        "order_type": trade.order_type,
    }


# ---------------------------------------------------------------------------
# LL-182: stable session_id helper (反 1414 stale mutex 累积)
# ---------------------------------------------------------------------------


def _stable_session_id(account_id: str, role: str = "default") -> int:
    """Generate stable session_id from (account_id, role) tuple — 12-digit int.

    **LL-182 fix** — replace time-based session_id (HHMMSSffffff) with deterministic
    hash for **long-running services** that benefit from session reuse across restart.
    Same (account, role) → same session_id always. miniQMT reuses existing session
    instead of creating new `down_queue_<id>__mutex` file per connect.

    **Multi-process safety**: different role → different session_id, avoid collision
    when QMTData service + execute_phase script try to connect simultaneously.
    Recommended roles: "qmtdata" (long-running) / "execute" (09:31 SH schtask) /
    "sell_adapter" / "staged_exec" (event-driven). 默认 "default" 仅 unit-test 用.

    **Opt-in only** — `MiniQMTBroker.__init__` 默认仍走 time-based (single-shot
    callers no stable session benefit + avoid multi-process conflict). Long-running
    services explicit pass `session_id=_stable_session_id(account, role)`.

    Root cause sediment: time-based session_id 2026-04-02 → 2026-05-18 累积 1412
    stale mutex files (~30/day) in `userdata_mini/down_queue_*__mutex`. Stable
    session 配合 `cleanup_stale_mutex_files` 在 connect() 自动 cleanup 双管齐下.

    Args:
        account_id: QMT account id (e.g. "81001102")
        role: process role string (e.g. "qmtdata", "execute"). Default "default".

    Returns:
        Deterministic 12-digit int session_id (same input → same output).
    """
    h = hashlib.md5(f"miniqmt_{account_id}_{role}".encode()).hexdigest()
    return int(h[:12], 16) % (10**12)


# ---------------------------------------------------------------------------
# MiniQMTBroker
# ---------------------------------------------------------------------------


class MiniQMTBroker(BaseBroker):
    """miniQMT实盘/模拟交易Broker。

    连接管理:
        connect()    — 连接miniQMT + 订阅账户推送
        disconnect() — 断开连接
        is_connected — 连接状态属性

    交易操作:
        place_order(code, direction, volume, price, price_type) → int
        cancel_order(order_id) → bool

    查询:
        query_asset()     → dict
        query_positions() → list[dict]
        query_orders()    → list[dict]
        query_trades()    → list[dict]

    回调注册:
        register_order_callback(fn)
        register_trade_callback(fn)
        register_error_callback(fn)
    """

    # 最大自动重连次数
    MAX_RECONNECT_ATTEMPTS: int = 3
    RECONNECT_INTERVAL_SEC: float = 5.0

    def __init__(
        self,
        qmt_path: str,
        account_id: str,
        session_id: int | None = None,
    ):
        """初始化Broker。

        Args:
            qmt_path: miniQMT userdata_mini目录路径
            account_id: 资金账号（如"81001102"）
            session_id: 会话ID，默认用时间戳避免冲突
        """
        self._qmt_path = qmt_path
        self._account_id = account_id
        # LL-182 architecture revised — multi-process safety:
        # - Default time-based session_id (each process unique, avoids multi-process
        #   collision when QMTData service + execute_phase script connect 同时).
        # - Long-running services explicit pass `session_id=_stable_session_id(account, role)`
        #   for session reuse across restart (e.g. qmt_data_service.py role="qmtdata").
        # - `cleanup_stale_mutex_files` auto-called in connect() handles accumulation.
        self._session_id = session_id or int(datetime.now().strftime("%H%M%S%f"))

        self._trader: Any = None  # XtQuantTrader实例
        self._account: Any = None  # StockAccount实例
        self._connected = False
        self._lock = threading.Lock()

        # 外部回调注册列表
        self._order_callbacks: list[Callable[[dict], None]] = []
        self._trade_callbacks: list[Callable[[dict], None]] = []
        self._error_callbacks: list[Callable[[dict], None]] = []

        # 重连状态
        self._reconnecting = False
        self._reconnect_count = 0

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """当前是否已连接。"""
        return self._connected

    @property
    def account_id(self) -> str:
        """资金账号。"""
        return self._account_id

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def cleanup_stale_mutex_files(self, max_age_days: int = 7) -> int:
        """删除 userdata_mini 中过期的 down_queue_*__mutex 文件 (LL-182).

        **LL-182 fix** — auto-cleanup stale session mutex files to prevent miniQMT
        internal session pool exhaustion. 配合 stable session_id (`_stable_session_id`)
        消除 4-02→5-18 累积 1412 stale mutex (~30/day) connect_failed 真根因.

        Args:
            max_age_days: 删 mtime 早于 N day 的 mutex 文件. connect() 默认 7d
                (保留 last 7d 防误删 active session); disconnect() 用 1d 激进 cleanup.

        Returns:
            实际删除的文件数. 0 = 0 stale OR path 不存在.

        Safety:
            - 仅删 `down_queue_*__mutex` 文件 (per-session marker, 非 order book)
            - mtime 严格阈值, 不删 active session current mutex
            - 失败 silent_ok (file lock / permission, 下次 cleanup 重试)
        """
        try:
            qmt_dir = Path(self._qmt_path)
            if not qmt_dir.exists():
                return 0
            cutoff = time.time() - max_age_days * 86400
            deleted = 0
            for f in qmt_dir.glob("down_queue_*__mutex"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        deleted += 1
                except OSError:
                    pass  # silent_ok: file lock / permission, retry next cleanup
            if deleted:
                logger.info(
                    f"[QMT] cleanup stale mutex: deleted {deleted} files older than {max_age_days}d"
                )
            return deleted
        except OSError:
            logger.exception("[QMT] cleanup_stale_mutex_files glob failed")
            return 0

    def connect(self) -> None:
        """连接miniQMT交易端并订阅账户推送。

        Raises:
            RuntimeError: 连接失败或路径不存在
        """
        path = Path(self._qmt_path)
        if not path.exists():
            raise RuntimeError(
                f"miniQMT路径不存在: {self._qmt_path}，请确认QMT客户端已安装且路径正确"
            )

        # LL-182: cleanup stale mutex files 前置 (反 1414 stale mutex 累积 connect_failed
        # 真根因). 配合 stable session_id 消除 per-connect mutex 累积.
        self.cleanup_stale_mutex_files(max_age_days=7)

        # 延迟导入xtquant（仅在实际使用时需要）
        from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
        from xtquant.xttype import StockAccount

        # M3 fix 2026-05-18 14:02 SH P0 incident — xtquant.xttrader internally
        # uses asyncio/Tornado; Celery worker thread (--pool=solo MainThread) +
        # Python 3.10+ raises RuntimeError "no current event loop in thread
        # 'MainThread'" if no loop set before XtQuantTrader() instantiation.
        # PR #377 fixed ModuleNotFoundError (sys.path drift) but did NOT cover
        # this asyncio compat sub-class. Defensive bootstrap: ensure event loop
        # set before any xtquant API call. Idempotent: if loop exists, no-op.
        # Sediment LL-180 candidate. 6th 实证 sys.path/asyncio drift sub-class.
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        # 创建回调子类（动态继承，因为xtquant需要XtQuantTraderCallback子类）
        broker_ref = self
        callback_impl = _QMTCallback(broker_ref)

        class _Callback(XtQuantTraderCallback):
            def on_disconnected(self_cb):
                callback_impl.on_disconnected()

            def on_stock_order(self_cb, order):
                callback_impl.on_stock_order(order)

            def on_stock_trade(self_cb, trade):
                callback_impl.on_stock_trade(trade)

            def on_order_error(self_cb, order_error):
                callback_impl.on_order_error(order_error)

            def on_account_status(self_cb, status):
                callback_impl.on_account_status(status)

        self._trader = XtQuantTrader(str(path), self._session_id)
        self._account = StockAccount(self._account_id)

        self._trader.register_callback(_Callback())
        self._trader.start()

        # LL-2026-05-27: start() 后任何失败路径必 stop() 释放 xtquant 内部线程/socket.
        # 反 PID 11008 真生产事故 (38h × 5min 重试 × ~40MB/次泄漏 = 8.4 GB / 874 threads
        # / 438 bound sockets). 之前 `self._trader = None` 只丢 Python 引用, GC 不会
        # 回收 xtquant C 层资源. 唯一安全释放手段是显式 stop(). 沿用铁律 33
        # (禁 silent failure - fail-safe cleanup 路径).
        try:
            result = self._trader.connect()
            if result != 0:
                raise RuntimeError(f"miniQMT连接失败，返回码: {result}")

            sub_result = self._trader.subscribe(self._account)
            if sub_result != 0:
                logger.warning(f"[QMT] 账户订阅返回非零: {sub_result}")
        except Exception:
            # 必须显式 stop() 释放 xtquant 内部资源, 然后才丢引用
            try:
                self._trader.stop()
            except Exception:
                logger.exception("[QMT] connect失败后stop异常 (resource leak 兜底)")
            self._trader = None
            raise

        self._connected = True
        self._reconnect_count = 0
        logger.info(
            f"[QMT] 连接成功: path={self._qmt_path}, "
            f"account={self._account_id}, session={self._session_id}"
        )

    def disconnect(self) -> None:
        """断开miniQMT连接。"""
        if self._trader is not None:
            try:
                self._trader.stop()
            except Exception:
                logger.exception("[QMT] 停止trader时异常")
            self._trader = None
        self._connected = False
        logger.info("[QMT] 已断开连接")

    def _handle_disconnect(self) -> None:
        """断线重连处理（在回调线程中执行）。"""
        self._connected = False
        if self._reconnecting:
            return

        self._reconnecting = True
        try:
            for attempt in range(1, self.MAX_RECONNECT_ATTEMPTS + 1):
                logger.info(f"[QMT] 尝试重连 ({attempt}/{self.MAX_RECONNECT_ATTEMPTS})")
                time.sleep(self.RECONNECT_INTERVAL_SEC)
                try:
                    self.connect()
                    logger.info("[QMT] 重连成功")
                    return
                except Exception:
                    logger.exception(f"[QMT] 第{attempt}次重连失败")
            logger.error("[QMT] 重连次数耗尽，需要手动重连")
        finally:
            self._reconnecting = False

    # ------------------------------------------------------------------
    # 前置检查
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        """检查连接状态。"""
        if not self._connected or self._trader is None:
            raise RuntimeError("miniQMT未连接，请先调用connect()")

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def query_asset(self) -> dict[str, Any]:
        """查询账户资产。

        Returns:
            包含cash/frozen_cash/market_value/total_asset的dict
        """
        self._ensure_connected()
        asset = self._trader.query_stock_asset(self._account)
        if asset is None:
            raise RuntimeError("查询资产失败，返回None")
        result = _asset_to_dict(asset)
        logger.debug(f"[QMT] 资产: {result}")
        return result

    def query_positions(self) -> list[dict[str, Any]]:
        """查询当前持仓。

        Returns:
            持仓列表，每项包含stock_code/volume/can_use_volume/avg_price/market_value
        """
        self._ensure_connected()
        positions = self._trader.query_stock_positions(self._account)
        if positions is None:
            return []
        result = [_position_to_dict(p) for p in positions if p.volume > 0]
        logger.debug(f"[QMT] 持仓: {len(result)}只")
        return result

    def query_orders(self) -> list[dict[str, Any]]:
        """查询当日委托。

        Returns:
            委托列表，每项包含order_id/stock_code/order_status/traded_volume等
        """
        self._ensure_connected()
        orders = self._trader.query_stock_orders(self._account)
        if orders is None:
            return []
        return [_order_to_dict(o) for o in orders]

    def query_trades(self) -> list[dict[str, Any]]:
        """查询当日成交。

        Returns:
            成交列表，每项包含order_id/stock_code/traded_price/traded_volume等
        """
        self._ensure_connected()
        trades = self._trader.query_stock_trades(self._account)
        if trades is None:
            return []
        return [_trade_to_dict(t) for t in trades]

    # ------------------------------------------------------------------
    # 交易
    # ------------------------------------------------------------------

    def place_order(
        self,
        code: str,
        direction: str,
        volume: int,
        price: float | None = None,
        price_type: str = "limit",
        remark: str = "",
    ) -> int:
        """提交委托。

        Args:
            code: 合约代码，格式"000001.SZ"
            direction: "buy"或"sell"
            volume: 委托数量（股，非手）
            price: 委托价格（限价单必填，市价单可不填）
            price_type: "limit"(限价) 或 "market"(最新价)
            remark: 备注（最大24字符，超出截断）

        Returns:
            order_id（正整数），下单失败返回-1

        Raises:
            RuntimeError: 未连接
            ValueError: 参数不合法
            LiveTradingDisabledError: 真金保护激活 (T1 sprint link-pause).
                双因素 OVERRIDE 才允许 bypass. 见 backend/app/security/live_trading_guard.py
        """
        self._ensure_connected()

        # 真金保护 (T1 sprint link-pause, 2026-04-29): 默认 LIVE_TRADING_DISABLED=true
        # 阻断真实 xtquant.order_stock. 双因素 OVERRIDE 才允许 bypass + 审计 + 钉钉 P0.
        # 撤销: docs/audit/link_paused_2026_04_29.md
        from app.security.live_trading_guard import assert_live_trading_allowed

        assert_live_trading_allowed(operation="place_order", code=code)

        from xtquant import xtconstant

        # 参数校验
        if direction not in ("buy", "sell"):
            raise ValueError(f"direction必须是'buy'或'sell'，收到: {direction}")
        if volume <= 0:
            raise ValueError(f"volume必须>0，收到: {volume}")
        if price_type == "limit" and price is None:
            raise ValueError("限价单必须指定price")

        # 方向映射
        xt_direction = xtconstant.STOCK_BUY if direction == "buy" else xtconstant.STOCK_SELL

        # 价格类型映射
        # 市价单需根据交易所选择正确类型:
        #   LATEST_PRICE(5) 在模拟盘卖单不撮合（实测2026-03-30确认）
        #   SH: MARKET_SH_CONVERT_5_CANCEL(42) — 最优五档即时成交剩余撤销
        #   SZ: MARKET_SZ_CONVERT_5_CANCEL(47) — 同上
        if price_type == "limit":
            xt_price_type = xtconstant.FIX_PRICE
        elif price_type == "market":
            if code.endswith(".SH"):
                xt_price_type = xtconstant.MARKET_SH_CONVERT_5_CANCEL
            else:
                # SZ/BJ 统一用深市五档
                xt_price_type = xtconstant.MARKET_SZ_CONVERT_5_CANCEL
        else:
            # fallback: 其他price_type值直接用LATEST_PRICE
            xt_price_type = xtconstant.LATEST_PRICE

        # 市价单price设0
        order_price = price if price is not None else 0.0

        # 备注截断
        safe_remark = remark[:24] if remark else "qm_v2"

        logger.info(
            f"[QMT] 下单: {code} {direction} {volume}股 "
            f"@{order_price:.3f} type={price_type} remark={safe_remark}"
        )

        with self._lock:
            order_id = self._trader.order_stock(
                self._account,
                code,
                xt_direction,
                volume,
                xt_price_type,
                order_price,
                "quantmind_v2",
                safe_remark,
            )

        if order_id is None or order_id < 0:
            logger.error(f"[QMT] 下单失败: code={code}, order_id={order_id}")
            return -1

        logger.info(f"[QMT] 下单成功: order_id={order_id}")
        return order_id

    def cancel_order(self, order_id: int) -> bool:
        """撤销委托。

        Args:
            order_id: 委托编号

        Returns:
            True=撤单请求已提交，False=撤单失败

        Raises:
            LiveTradingDisabledError: 真金保护激活 (T1 sprint link-pause).
                双因素 OVERRIDE 才允许 bypass. 见 backend/app/security/live_trading_guard.py
        """
        self._ensure_connected()

        # 真金保护 (T1 sprint link-pause, 2026-04-29): cancel 也是真金行为, 同 place_order 守门.
        # 撤销: docs/audit/link_paused_2026_04_29.md
        # reviewer P2 (oh-my-claudecode:code-reviewer) 采纳: code 字段语义是"stock code",
        # cancel_order 传 order_id 会让审计 trail 写"股票: 12345678"误导. 加 order_id= 前缀.
        from app.security.live_trading_guard import assert_live_trading_allowed

        assert_live_trading_allowed(operation="cancel_order", code=f"order_id={order_id}")

        logger.info(f"[QMT] 撤单: order_id={order_id}")

        with self._lock:
            result = self._trader.cancel_order_stock(self._account, order_id)

        success = result == 0
        if success:
            logger.info(f"[QMT] 撤单请求已提交: order_id={order_id}")
        else:
            logger.warning(f"[QMT] 撤单失败: order_id={order_id}, result={result}")
        return success

    # ------------------------------------------------------------------
    # 回调注册
    # ------------------------------------------------------------------

    def register_order_callback(self, fn: Callable[[dict], None]) -> None:
        """注册委托状态变化回调。

        Args:
            fn: 回调函数，参数为标准化委托dict
        """
        self._order_callbacks.append(fn)

    def register_trade_callback(self, fn: Callable[[dict], None]) -> None:
        """注册成交回报回调。

        Args:
            fn: 回调函数，参数为标准化成交dict
        """
        self._trade_callbacks.append(fn)

    def register_error_callback(self, fn: Callable[[dict], None]) -> None:
        """注册下单失败回调。

        Args:
            fn: 回调函数，参数包含order_id/error_id/error_msg
        """
        self._error_callbacks.append(fn)

    # ------------------------------------------------------------------
    # BaseBroker统一接口
    # ------------------------------------------------------------------

    def get_positions(self) -> dict[str, int]:
        """获取当前持仓（查询miniQMT）。"""
        positions = self.query_positions()
        return {p["stock_code"]: p["volume"] for p in positions}

    def get_cash(self) -> float:
        """获取当前可用现金。"""
        asset = self.query_asset()
        return float(asset["cash"])

    def get_total_value(self, prices: dict[str, float]) -> float:
        """计算组合总市值（查询miniQMT资产）。

        prices参数未使用——MiniQMTBroker直接从交易端查询实时市值。
        保留参数以满足BaseBroker接口统一性。
        """
        asset = self.query_asset()
        return float(asset["total_asset"])

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def __enter__(self) -> "MiniQMTBroker":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"MiniQMTBroker(account={self._account_id}, {status})"
