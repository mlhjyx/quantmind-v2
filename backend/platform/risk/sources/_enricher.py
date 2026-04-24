"""Position 共享 enrichment 逻辑 (entry_price / peak_price / current_price).

两个 PositionSource (QMT + DB) 共用: 给定 {code: shares} dict, 补全 5 字段 Position 对象.

- entry_price: trade_log 加权平均买入成本 (execution_mode 动态, 非 hardcoded 'live')
- peak_price: klines_daily 持仓期间 MAX(close), entry_date 为最近一次买入 (非对等卖出)
- current_price: price_reader.get_prices 批量读 Redis market:latest

铁律 31 此模块仍 IO (读 DB + Redis), 归属 sources 子包 (Platform concrete 实现层 IO OK,
rules.pms / interface.py 则严格纯计算).
"""
from __future__ import annotations

import logging
from typing import Protocol

from ..interface import Position

logger = logging.getLogger(__name__)


class PriceReader(Protocol):
    """批量价格读取契约 (duck-typing 适配 app.core.qmt_client.QMTClient)."""

    def get_prices(self, codes: list[str]) -> dict[str, float]:
        """批量读 Redis market:latest:{code} → {code: current_price}. 失败返 {} 非 raise."""
        ...


def load_entry_prices(conn, strategy_id: str, execution_mode: str, codes: list[str]) -> dict[str, float]:
    """从 trade_log 加权平均买入成本.

    reviewer P1-2 采纳: 过滤"最近一次卖出之后的买入" (与 load_peak_prices entry_date
    语义对齐). 原实现加全历史 buy 导致场景错: 股 A 4-01 买 100 / 4-10 卖 100 / 4-15
    重买 100 → 加权 entry_price 吃入 4-01 的旧价, 使 unrealized_pnl 虚高, PMS 误卖.

    Args:
        conn: psycopg2 connection (调用方管理事务, 本函数不 commit).
        strategy_id: 策略 UUID.
        execution_mode: 'paper' | 'live' (ADR-008 命名空间, 非 hardcoded).
        codes: 股票代码列表.

    Returns:
        {code: avg_cost}, 缺失码返 0.0 entry.
    """
    if not codes:
        return {}
    result: dict[str, float] = {}
    with conn.cursor() as cur:
        for code in codes:
            cur.execute(
                """SELECT fill_price, quantity FROM trade_log
                WHERE code = %s AND strategy_id = %s
                  AND direction = 'buy' AND execution_mode = %s
                  AND trade_date >= (
                    SELECT COALESCE(MAX(trade_date), '1970-01-01') FROM trade_log
                    WHERE code = %s AND strategy_id = %s
                      AND direction = 'sell' AND execution_mode = %s
                  )
                ORDER BY trade_date DESC""",
                (code, strategy_id, execution_mode, code, strategy_id, execution_mode),
            )
            buys = cur.fetchall()
            if not buys:
                result[code] = 0.0
                continue
            total_cost = sum(float(r[0]) * int(r[1]) for r in buys)
            total_shares = sum(int(r[1]) for r in buys)
            result[code] = round(total_cost / total_shares, 4) if total_shares > 0 else 0.0
    return result


def load_peak_prices(conn, strategy_id: str, execution_mode: str, codes: list[str]) -> dict[str, float]:
    """从 klines_daily 持仓期间历史最高收盘价.

    持仓期间定义: entry_date = MIN(buy trade_date) since 最近一次 sell. 无卖出则取全部 buy.

    Args:
        conn: psycopg2 connection.
        strategy_id: 策略 UUID.
        execution_mode: 'paper' | 'live'.
        codes: 股票代码列表.

    Returns:
        {code: peak_close}, 缺失码不在 dict (调用方 fallback 到 entry_price).
    """
    if not codes:
        return {}
    peaks: dict[str, float] = {}
    with conn.cursor() as cur:
        for code in codes:
            cur.execute(
                """SELECT MIN(trade_date) FROM trade_log
                WHERE code = %s AND strategy_id = %s
                  AND direction = 'buy' AND execution_mode = %s
                  AND trade_date >= (
                    SELECT COALESCE(MAX(trade_date), '1970-01-01') FROM trade_log
                    WHERE code = %s AND strategy_id = %s
                      AND direction = 'sell' AND execution_mode = %s
                  )""",
                (code, strategy_id, execution_mode, code, strategy_id, execution_mode),
            )
            row = cur.fetchone()
            entry_date = row[0] if row and row[0] else None
            if not entry_date:
                continue
            cur.execute(
                """SELECT MAX(close) FROM klines_daily
                WHERE code = %s AND trade_date >= %s""",
                (code, entry_date),
            )
            peak_row = cur.fetchone()
            if peak_row and peak_row[0]:
                peaks[code] = float(peak_row[0])
    return peaks


def build_positions(
    shares_dict: dict[str, int],
    entry_prices: dict[str, float],
    peak_prices: dict[str, float],
    current_prices: dict[str, float],
) -> list[Position]:
    """纯函数: 拼装 Position 列表 (无 IO). 供单测重用.

    - peak_prices 缺失 → fallback 到 entry_price (规则层会 skip entry_price=0 异常)
    - current_prices 缺失 → 0.0 (规则层会 skip)
    - shares <= 0 的码跳过 (已平仓)
    """
    positions: list[Position] = []
    for code, shares in shares_dict.items():
        if shares <= 0:
            continue
        entry = entry_prices.get(code, 0.0)
        peak = peak_prices.get(code, entry)
        current = current_prices.get(code, 0.0)
        positions.append(
            Position(
                code=code,
                shares=shares,
                entry_price=entry,
                peak_price=peak,
                current_price=current,
            )
        )
    return positions
