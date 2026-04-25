"""QMTPositionSource — Redis portfolio:current primary source.

读 QMT Data Service 60s 同步到 Redis 的 portfolio:current hash.
读不到 → raise PositionSourceError (Engine 切 fallback + P1 钉钉, 铁律 33).

Platform/App 边界: 本模块不 import xtquant (QMT Data Service 专属),
通过 PriceReader + PositionReader Protocol 注入 QMTClient 实例.
"""
from __future__ import annotations

from typing import Protocol

from ..interface import Position, PositionSource, PositionSourceError
from ._enricher import build_positions, load_entry_prices, load_peak_prices


class PositionReader(Protocol):
    """QMT 持仓读取契约 (duck-typing 适配 app.core.qmt_client.QMTClient)."""

    def is_connected(self) -> bool:
        """QMT Data Service 连接状态. False = 断连."""
        ...

    def get_positions(self) -> dict[str, int]:
        """Redis portfolio:current → {code: shares}. 失败 / 空返 {}."""
        ...

    def get_prices(self, codes: list[str]) -> dict[str, float]:
        """Redis market:latest:{code} → {code: current_price}. 失败返 {}."""
        ...


class QMTPositionSource(PositionSource):
    """QMT Redis primary PositionSource.

    Args:
        reader: QMTClient-like (is_connected + get_positions + get_prices).
        conn_factory: callable → psycopg2 conn (for trade_log entry_price + klines_daily peak).
    """

    def __init__(self, reader: PositionReader, conn_factory):
        self._reader = reader
        self._conn_factory = conn_factory

    def load(self, strategy_id: str, execution_mode: str) -> list[Position]:
        """返 primary Redis 持仓, 失败 raise PositionSourceError."""
        if not self._reader.is_connected():
            raise PositionSourceError("QMT Data Service disconnected (is_connected=False)")

        shares_dict = self._reader.get_positions()
        if not shares_dict:
            # reviewer P1-1 采纳: 区分"合法空仓" vs "Redis 读失败".
            # is_connected=True 已确认 QMT Data Service 正常, 此时空 dict = 真空仓
            # (PT 全清 / 新 strategy 未建仓), 返 [] 非 raise. 避免合法状态炸调用方.
            # Redis 断连由 is_connected() 捕获在前.
            return []

        codes = list(shares_dict.keys())
        with self._conn_factory() as conn:
            entry_prices = load_entry_prices(conn, strategy_id, execution_mode, codes)
            peak_prices = load_peak_prices(conn, strategy_id, execution_mode, codes)

        current_prices = self._reader.get_prices(codes)
        return build_positions(shares_dict, entry_prices, peak_prices, current_prices)
