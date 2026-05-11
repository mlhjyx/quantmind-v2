"""XtQuantTickSubscriber — xtquant subscribe_quote 实时 tick 订阅器 (S5 L1 实时化).

职责:
  1. 订阅 xtquant tick 推送 (subscribe_quote)
  2. 维护 rolling 窗口 (5min/15min price snapshot)
  3. 维护 day volume accumulators
  4. 构造 RealtimeRiskEngine 所需的 realtime dict

用法:
    subscriber = XtQuantTickSubscriber()
    subscriber.start(["600519.SH", "000001.SZ"])  # 启动订阅
    # tick callback 自动触发, 业务方轮询 get_current_realtime() 取最新数据

延迟加载: xtquant 在首次订阅时才 import (铁律 31, 反非 QMT 环境 import).

关联铁律: 31 (lazy import xtquant) / 33 (fail-loud on subscribe failure)
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Rolling window params
_5MIN_WINDOW: float = 300.0  # 5min in seconds
_15MIN_WINDOW: float = 900.0  # 15min in seconds

TickCallback = Callable[[dict[str, dict[str, Any]]], None]
"""tick 数据回调: {code: {price, volume, timestamp, prev_close, ...}}."""


class XtQuantTickSubscriber:
    """xtquant subscribe_quote tick 订阅器.

    管理 subscribe_quote 生命周期 (start/stop), 维护 rolling 窗口.
    非单例 — 业务方可持多个实例 (e.g. 不同 symbol 组).
    """

    def __init__(self) -> None:
        self._running = False
        self._symbols: list[str] = []
        self._lock = threading.Lock()
        # Rolling state
        self._current_ticks: dict[str, dict[str, Any]] = {}
        self._price_snapshots: dict[str, list[tuple[datetime, float]]] = {}
        self._day_volume: dict[str, int] = {}
        self._callbacks: list[TickCallback] = []
        # xtquant 模块懒加载
        self._xtdata = None

    @property
    def is_running(self) -> bool:
        return self._running

    def add_callback(self, cb: TickCallback) -> None:
        """注册 tick 回调 (e.g. 连接 RealtimeRiskEngine)."""
        self._callbacks.append(cb)

    def _lazy_import_xtquant(self) -> None:
        """首次调用时 import xtquant (铁律 31 懒加载)."""
        if self._xtdata is None:
            from xtquant import xtdata  # type: ignore[import-untyped]  # noqa: PLC0415

            self._xtdata = xtdata

    def _on_xt_tick(self, data: dict[str, Any]) -> None:
        """xtquant subscribe_quote callback 处理.

        解析 tick 数据, 更新 rolling 窗口, 通知注册回调.
        """
        with self._lock:
            now = datetime.now(UTC)
            for code, tick in data.items():
                if not isinstance(tick, dict):
                    continue
                price = tick.get("lastPrice") or tick.get("price", 0)
                volume = tick.get("volume", 0) or tick.get("cumVolume", 0)
                if price <= 0:
                    continue

                prev_tick = self._current_ticks.get(code, {})
                prev_price = prev_tick.get("price", price)

                self._current_ticks[code] = {
                    "price": price,
                    "volume": volume,
                    "timestamp": now,
                    "prev_close": prev_tick.get("prev_close", tick.get("lastClose", 0)),
                    "open_price": prev_tick.get("open_price", tick.get("open", 0)),
                }

                # Rolling price snapshots (pruned to _15MIN_WINDOW + 60s buffer)
                if code not in self._price_snapshots:
                    self._price_snapshots[code] = []
                snapshots = self._price_snapshots[code]
                snapshots.append((now, prev_price))
                # Prune entries older than 16 min (15min window + 60s buffer)
                cutoff_ts = now.timestamp() - (_15MIN_WINDOW + 60)
                while snapshots and snapshots[0][0].timestamp() < cutoff_ts:
                    snapshots.pop(0)

                # Day volume accumulator
                if volume > 0:
                    prev_vol = self._day_volume.get(code, 0)
                    vol_delta = volume - prev_vol
                    if vol_delta > 0:
                        self._day_volume[code] = volume
                    else:
                        # New day: volume reset detected
                        self._day_volume[code] = volume

        # Notify callbacks (outside lock to avoid deadlock)
        for cb in self._callbacks:
            try:
                with self._lock:
                    ticks_copy = dict(self._current_ticks)
                cb(ticks_copy)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "[xt-subscriber] callback %s failed: %s: %s",
                    getattr(cb, "__name__", "?"),
                    type(e).__name__,
                    e,
                )

    def start(self, symbols: list[str]) -> None:
        """订阅实时 tick.

        Args:
            symbols: QMT code list (带后缀, e.g. ["600519.SH", "000001.SZ"]).

        Raises:
            RuntimeError: 已运行.
        """
        if self._running:
            raise RuntimeError("XtQuantTickSubscriber already running")

        self._lazy_import_xtquant()
        self._symbols = symbols
        self._running = True

        for s in symbols:
            try:
                self._xtdata.subscribe_quote(
                    stock_code=s,
                    period="tick",
                    count=-1,
                    callback=self._on_xt_tick,
                )
                logger.info("[xt-subscriber] subscribed %s (tick)", s)
            except Exception as e:
                logger.error(
                    "[xt-subscriber] subscribe_quote failed for %s: %s: %s",
                    s,
                    type(e).__name__,
                    e,
                )

    def stop(self) -> None:
        """停止所有订阅."""
        if not self._running:
            return
        self._running = False
        logger.info("[xt-subscriber] stopped, symbols=%s", self._symbols)

    def get_current_realtime(
        self,
    ) -> dict[str, dict[str, Any]]:
        """获取当前实时 tick 数据, 含 rolling 窗口.

        Returns:
            {code: {price, volume, prev_close, open_price,
                    price_5min_ago, price_15min_ago, day_volume}}.
        """
        now = datetime.now(UTC)
        result: dict[str, dict[str, Any]] = {}

        with self._lock:
            for code, tick in self._current_ticks.items():
                entry = dict(tick)

                # Rolling windows
                snapshots = self._price_snapshots.get(code, [])
                price_5min = self._find_price_at(now, snapshots, _5MIN_WINDOW)
                price_15min = self._find_price_at(now, snapshots, _15MIN_WINDOW)
                if price_5min is not None:
                    entry["price_5min_ago"] = price_5min
                if price_15min is not None:
                    entry["price_15min_ago"] = price_15min

                day_vol = self._day_volume.get(code, 0)
                entry["day_volume"] = day_vol

                result[code] = entry

        return result

    @staticmethod
    def _find_price_at(
        now: datetime, snapshots: list[tuple[datetime, float]], window: float
    ) -> float | None:
        """在 snapshot 历史中找 ~window 秒前的价格."""
        if not snapshots:
            return None
        cutoff = now.timestamp() - window
        # 从后往前找第一个 <= cutoff 的 snapshot
        for ts, price in reversed(snapshots):
            if ts.timestamp() <= cutoff:
                return price
        # 无足够历史: 返回最早 snapshot (最接近可用)
        return snapshots[0][1]

    def get_avg_daily_volume(self, code: str, days: int = 20) -> float | None:
        """获取 20 日均成交量 (需外部注入 DB 数据).

        TODO(S5-followup): Wire klines_daily avg_volume from DB.
        当前返 None → VolumeSpike / LiquidityCollapse silent skip
        (production activation requires this wire + avg_daily_volume in
        get_current_realtime() + industry classification in _current_ticks).
        """
        return None
