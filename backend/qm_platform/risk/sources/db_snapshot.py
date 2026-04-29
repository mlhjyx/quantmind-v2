"""DBPositionSource — position_snapshot fallback.

当 QMTPositionSource 挂时, 从 `position_snapshot` 读当日最新快照. 注意:
- 16:30 signal_phase 才写, 09:31-16:30 日内读取到前一日 (T-1 盲区)
- Session 28 PR 2 批 1 接受此缺口 (月度调仓策略可容忍), 未来 Wave 4 可加 tick-level event stream

仍需 PriceReader 读 Redis market:latest (current_price 来源是价格 Redis 非 DB).
Primary / fallback 区别只在 shares 来源, 价格+peak+entry 从 DB 共享.
"""
from __future__ import annotations

from ..interface import Position, PositionSource, PositionSourceError
from ._enricher import (
    PriceReader,
    build_positions,
    load_entry_dates,
    load_entry_prices,
    load_peak_prices,
)


class DBPositionSource(PositionSource):
    """position_snapshot fallback PositionSource.

    Args:
        conn_factory: callable → psycopg2 conn.
        price_reader: Redis market:latest 价格批量读取器 (fallback 仍需实时价).
    """

    def __init__(self, conn_factory, price_reader: PriceReader):
        self._conn_factory = conn_factory
        self._price_reader = price_reader

    def load(self, strategy_id: str, execution_mode: str) -> list[Position]:
        """从 position_snapshot 最新 trade_date + trade_log + klines_daily 拼装.

        Raises:
            PositionSourceError: DB 查询失败 / 无持仓快照 / 无 execution_mode 匹配行.
        """
        with self._conn_factory() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT code, quantity FROM position_snapshot
                WHERE strategy_id = %s AND execution_mode = %s
                  AND trade_date = (
                    SELECT MAX(trade_date) FROM position_snapshot
                    WHERE strategy_id = %s AND execution_mode = %s
                  )
                  AND quantity > 0""",
                (strategy_id, execution_mode, strategy_id, execution_mode),
            )
            rows = cur.fetchall()
            if not rows:
                raise PositionSourceError(
                    f"position_snapshot no rows for strategy={strategy_id} mode={execution_mode}"
                )
            shares_dict = {r[0]: int(r[1]) for r in rows}

            codes = list(shares_dict.keys())
            entry_prices = load_entry_prices(conn, strategy_id, execution_mode, codes)
            peak_prices = load_peak_prices(conn, strategy_id, execution_mode, codes)
            # Phase 1.5a (Session 44): entry_date 用于 future PositionHoldingTimeRule
            # + NewPositionVolatilityRule. 不影响现有 PMS / SingleStockStopLoss.
            entry_dates = load_entry_dates(conn, strategy_id, execution_mode, codes)

        current_prices = self._price_reader.get_prices(codes)
        return build_positions(
            shares_dict, entry_prices, peak_prices, current_prices,
            entry_dates=entry_dates,
        )
