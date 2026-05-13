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

AvgVolumeProvider = Callable[[str, int], float | None]
"""Injectable provider: (code, days) -> avg daily volume.

Production wire path (deferred to S10 paper-mode 5d dry-run per Plan §A):
    SELECT AVG(volume) FROM klines_daily
    WHERE symbol_id=? AND trade_date >= today - days
"""

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

    def __init__(self, avg_volume_provider: AvgVolumeProvider | None = None) -> None:
        self._running = False
        self._symbols: list[str] = []
        self._lock = threading.Lock()
        # S5 audit fix P1-2: injectable provider for avg daily volume — production
        # caller wires DB-based fn (SELECT AVG(volume) FROM klines_daily ...).
        # None (default) keeps the safe-skip stub for unit tests and paper-mode.
        self._avg_volume_provider: AvgVolumeProvider | None = avg_volume_provider
        # Reviewer P2-5: rate-limited provider error counter — log WARNING per
        # failure, but escalate to ERROR every 100 consecutive failures so a
        # silently broken DB provider becomes operator-visible without flooding
        # tick-frequency logs. Reset on first successful call.
        self._provider_error_count: int = 0
        # Rolling state
        self._current_ticks: dict[str, dict[str, Any]] = {}
        self._price_snapshots: dict[str, list[tuple[datetime, float]]] = {}
        self._day_volume: dict[str, int] = {}
        self._callbacks: list[TickCallback] = []
        # xtquant 模块懒加载
        self._xtdata = None
        # Per-symbol subscribe seq ids returned by xtquant subscribe_quote
        # (S5 audit fix P1-1: needed for true unsubscribe on stop() — without
        # this the prior implementation just set _running=False and leaked the
        # xtquant native subscription across worker restarts).
        self._subscribe_ids: dict[str, int] = {}

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
                seq = self._xtdata.subscribe_quote(
                    stock_code=s,
                    period="tick",
                    count=-1,
                    callback=self._on_xt_tick,
                )
                if isinstance(seq, int) and seq >= 0:
                    self._subscribe_ids[s] = seq
                logger.info("[xt-subscriber] subscribed %s (tick) seq=%s", s, seq)
            except Exception as e:
                logger.error(
                    "[xt-subscriber] subscribe_quote failed for %s: %s: %s",
                    s,
                    type(e).__name__,
                    e,
                )

    def stop(self) -> None:
        """停止所有订阅.

        S5 audit fix P1-1: actually call xtdata.unsubscribe_quote(seq) for every
        registered subscribe seq id, so xtquant native subscription releases
        across worker restarts. Failure on individual unsubscribe is logged but
        does not abort the loop (best-effort cleanup).
        """
        if not self._running:
            return
        self._running = False

        if self._xtdata is not None and hasattr(self._xtdata, "unsubscribe_quote"):
            for s, seq in list(self._subscribe_ids.items()):
                # TODO(铁律 1: 外部 API 必须先读官方文档): xtquant 0.0.x SDK ships
                # `unsubscribe_quote(seq)` (single positional int arg per current
                # xtdata.py); production activation MUST verify the actual installed
                # xtquant version's signature — alternative forms `(stock_code,
                # period)` exist in some forks. If signature differs, the call
                # silently fails into the `except` below and the native sub leaks
                # (the bug this code aims to fix). Reviewer P1-4 acknowledged.
                try:
                    self._xtdata.unsubscribe_quote(seq)
                    logger.info("[xt-subscriber] unsubscribed %s seq=%d", s, seq)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "[xt-subscriber] unsubscribe_quote(%d) for %s failed: %s",
                        seq,
                        s,
                        e,
                    )
        self._subscribe_ids.clear()
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
        """获取 N 日均成交量 (injectable provider, S5 audit fix P1-2).

        生产 wire: ctor 接受 `avg_volume_provider=fn(code, days) -> float | None`
        指向 DB-backed implementation. 未注入时返 None → VolumeSpike /
        LiquidityCollapse silent skip (paper-mode + unit test safe).

        Caller responsibility: ensure provider is idempotent + thread-safe +
        cached (e.g. lru_cache or Redis SETEX). Provider 失败 (raise) 被本方法
        吞掉 silent return None (反 per-tick subscribe_quote callback 串行
        crash 整个 XtQuantTickSubscriber 进程; 错误已 logged).
        """
        if self._avg_volume_provider is None:
            return None
        try:
            value = self._avg_volume_provider(code, days)
            # Reviewer P2-5: reset error counter on first success
            if self._provider_error_count > 0:
                logger.info(
                    "[xt-subscriber] avg_volume_provider recovered after %d failures",
                    self._provider_error_count,
                )
                self._provider_error_count = 0
            return value
        except Exception as e:  # noqa: BLE001
            self._provider_error_count += 1
            # Reviewer P2-5: rate-limited operator-visible ERROR every 100 failures
            if self._provider_error_count % 100 == 1:
                logger.error(
                    "[xt-subscriber] avg_volume_provider(%s, %d) raised %s: %s "
                    "(consecutive_failures=%d, VolumeSpike/LiquidityCollapse "
                    "rules silent-skip until recovery)",
                    code,
                    days,
                    type(e).__name__,
                    e,
                    self._provider_error_count,
                )
            else:
                logger.warning(
                    "[xt-subscriber] avg_volume_provider(%s, %d) raised %s: %s",
                    code,
                    days,
                    type(e).__name__,
                    e,
                )
            return None
