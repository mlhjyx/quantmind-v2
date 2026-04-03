"""PMS Engine — 阶梯利润保护系统 v1.0。

三层阶梯保护规则（满足任一层即触发卖出）:
- 层级1: 浮盈>30% 且 从最高点回撤>15%
- 层级2: 浮盈>20% 且 从最高点回撤>12%
- 层级3: 浮盈>10% 且 从最高点回撤>10%

数据流: QMT Data Service → Redis缓存 → PMS引擎 → StreamBus → 通知
Service内部不commit，由调用方管理事务。
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def _to_qmt_code(code: str) -> str:
    """DB代码(601138) → QMT代码(601138.SH)。"""
    if "." in code:
        return code
    if code.startswith(("6",)):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("8", "9", "4")):
        return f"{code}.BJ"
    return f"{code}.SH"


def _from_qmt_code(code: str) -> str:
    """QMT代码(601138.SH) → DB代码(601138)。"""
    return code.split(".")[0] if "." in code else code


@dataclass
class PMSLevel:
    """单层保护阈值。"""

    level: int
    min_gain: float
    max_drawdown: float


@dataclass
class SellSignal:
    """PMS卖出信号。"""

    code: str
    level: int
    entry_price: float
    peak_price: float
    current_price: float
    unrealized_pnl_pct: float
    drawdown_from_peak_pct: float
    shares: int


def get_pms_levels() -> list[PMSLevel]:
    """从.env构建阶梯保护层级（优先级从高到低）。"""
    return [
        PMSLevel(1, settings.PMS_LEVEL1_GAIN, settings.PMS_LEVEL1_DRAWDOWN),
        PMSLevel(2, settings.PMS_LEVEL2_GAIN, settings.PMS_LEVEL2_DRAWDOWN),
        PMSLevel(3, settings.PMS_LEVEL3_GAIN, settings.PMS_LEVEL3_DRAWDOWN),
    ]


def check_protection(
    entry_price: float,
    peak_price: float,
    current_price: float,
    levels: list[PMSLevel] | None = None,
) -> int | None:
    """检查单只股票是否触发利润保护。

    Args:
        entry_price: 买入成本价。
        peak_price: 持仓期间最高收盘价。
        current_price: 当前价格。
        levels: 保护层级列表，None则用默认配置。

    Returns:
        触发的层级(1/2/3)，未触发返回None。
    """
    if entry_price <= 0 or peak_price <= 0 or current_price <= 0:
        return None

    unrealized_pnl = (current_price - entry_price) / entry_price
    drawdown = (peak_price - current_price) / peak_price

    if levels is None:
        levels = get_pms_levels()

    for level in levels:
        if unrealized_pnl >= level.min_gain and drawdown >= level.max_drawdown:
            return level.level

    return None


class PMSEngine:
    """PMS持仓监控与利润保护引擎。"""

    def __init__(self) -> None:
        self._levels = get_pms_levels()

    def sync_positions(self, conn, strategy_id: str) -> list[dict]:
        """从trade_log同步当前持仓的买入成本到position_monitor。

        计算每只股票的加权平均买入成本:
        avg_cost = sum(buy_price * buy_shares) / sum(buy_shares)

        Args:
            conn: psycopg2连接。
            strategy_id: 策略ID。

        Returns:
            当前持仓列表 [{code, entry_price, shares}]。
        """
        cur = conn.cursor()

        # 从position_snapshot获取当前持仓股票和股数
        cur.execute(
            """SELECT code, quantity FROM position_snapshot
            WHERE strategy_id = %s AND execution_mode = 'paper'
              AND trade_date = (
                SELECT MAX(trade_date) FROM position_snapshot
                WHERE strategy_id = %s AND execution_mode = 'paper'
              )
            AND quantity > 0""",
            (strategy_id, strategy_id),
        )
        holdings = {row[0]: int(row[1]) for row in cur.fetchall()}

        if not holdings:
            logger.info("[PMS] 当前无持仓")
            return []

        positions = []
        for code, shares in holdings.items():
            # 计算加权平均买入成本
            cur.execute(
                """SELECT fill_price, quantity FROM trade_log
                WHERE code = %s AND strategy_id = %s
                  AND direction = 'buy' AND execution_mode = 'paper'
                ORDER BY trade_date DESC""",
                (code, strategy_id),
            )
            buys = cur.fetchall()
            if buys:
                total_cost = sum(float(r[0]) * int(r[1]) for r in buys)
                total_shares = sum(int(r[1]) for r in buys)
                avg_cost = total_cost / total_shares if total_shares > 0 else 0
            else:
                avg_cost = 0

            positions.append(
                {
                    "code": code,
                    "entry_price": round(avg_cost, 4),
                    "shares": shares,
                }
            )

        logger.info("[PMS] 同步持仓: %d只股票", len(positions))
        return positions

    def get_peak_prices(self, conn, codes: list[str]) -> dict[str, float]:
        """从klines_daily获取每只股票持仓期间的历史最高收盘价。

        Args:
            conn: psycopg2连接。
            codes: 股票代码列表。

        Returns:
            {code: peak_close_price}。
        """
        if not codes:
            return {}

        cur = conn.cursor()
        peaks = {}
        for code in codes:
            # 获取最近一次买入日期
            cur.execute(
                """SELECT MIN(trade_date) FROM trade_log
                WHERE code = %s AND direction = 'buy'
                  AND execution_mode = 'paper'
                  AND trade_date >= (
                    SELECT COALESCE(MAX(trade_date), '1970-01-01')
                    FROM trade_log
                    WHERE code = %s AND direction = 'sell'
                      AND execution_mode = 'paper'
                  )""",
                (code, code),
            )
            row = cur.fetchone()
            entry_date = row[0] if row and row[0] else None

            if entry_date:
                cur.execute(
                    """SELECT MAX(close) FROM klines_daily
                    WHERE code = %s AND trade_date >= %s""",
                    (code, entry_date),
                )
                peak_row = cur.fetchone()
                if peak_row and peak_row[0]:
                    peaks[code] = float(peak_row[0])

        return peaks

    def check_all_positions(
        self,
        positions: list[dict],
        peak_prices: dict[str, float],
        current_prices: dict[str, float],
    ) -> list[SellSignal]:
        """检查所有持仓是否触发利润保护。

        Args:
            positions: [{code, entry_price, shares}] 从sync_positions获取。
            peak_prices: {code: peak_price} 从get_peak_prices获取。
            current_prices: {code: current_price} 从QMTClient获取。

        Returns:
            触发卖出的信号列表。
        """
        signals = []

        for pos in positions:
            code = pos["code"]
            qmt_code = _to_qmt_code(code)
            entry_price = pos["entry_price"]
            shares = pos["shares"]
            peak = peak_prices.get(code, entry_price)
            # 尝试DB代码和QMT代码两种格式匹配价格
            current = current_prices.get(code) or current_prices.get(qmt_code)

            if not current or current <= 0:
                logger.warning("[PMS] %s 无当前价格，跳过", code)
                continue

            # 更新peak（当前价可能更高）
            peak = max(peak, current)

            level = check_protection(entry_price, peak, current, self._levels)

            if level is not None:
                pnl_pct = (current - entry_price) / entry_price
                dd_pct = (peak - current) / peak
                signals.append(
                    SellSignal(
                        code=code,
                        level=level,
                        entry_price=entry_price,
                        peak_price=peak,
                        current_price=current,
                        unrealized_pnl_pct=round(pnl_pct, 4),
                        drawdown_from_peak_pct=round(dd_pct, 4),
                        shares=shares,
                    )
                )
                logger.info(
                    "[PMS] 触发层级%d: %s 浮盈=%.1f%% 回撤=%.1f%%",
                    level,
                    code,
                    pnl_pct * 100,
                    dd_pct * 100,
                )

        return signals

    def build_monitor_data(
        self,
        positions: list[dict],
        peak_prices: dict[str, float],
        current_prices: dict[str, float],
    ) -> list[dict]:
        """构建完整的持仓监控数据（供API返回）。"""
        result = []
        for pos in positions:
            code = pos["code"]
            qmt_code = _to_qmt_code(code)
            entry = pos["entry_price"]
            peak = peak_prices.get(code, entry)
            current = current_prices.get(code) or current_prices.get(qmt_code)

            if not current or entry <= 0:
                continue

            peak = max(peak, current)
            pnl_pct = (current - entry) / entry if entry > 0 else 0
            dd_pct = (peak - current) / peak if peak > 0 else 0

            # 计算距离最近保护层级的距离
            nearest_level = None
            nearest_gap = float("inf")
            for lvl in self._levels:
                if pnl_pct >= lvl.min_gain:
                    gap = lvl.max_drawdown - dd_pct
                    if 0 < gap < nearest_gap:
                        nearest_gap = gap
                        nearest_level = lvl.level

            result.append(
                {
                    "code": code,
                    "shares": pos["shares"],
                    "entry_price": entry,
                    "peak_price": round(peak, 4),
                    "current_price": round(current, 4),
                    "unrealized_pnl_pct": round(pnl_pct, 4),
                    "drawdown_from_peak_pct": round(dd_pct, 4),
                    "nearest_protection_level": nearest_level,
                    "nearest_protection_gap_pct": round(nearest_gap, 4) if nearest_level else None,
                    "status": "safe"
                    if nearest_level is None
                    else ("warning" if nearest_gap > 0.03 else "danger"),
                }
            )

        return result

    def record_trigger(
        self,
        conn,
        signal: SellSignal,
        strategy_id: str,
        trigger_date: date,
    ) -> None:
        """记录PMS触发到position_monitor表。"""
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO position_monitor
            (symbol, entry_date, entry_price, peak_price, current_price,
             unrealized_pnl_pct, drawdown_from_peak_pct,
             pms_level_triggered, trigger_date, trigger_price, status)
            VALUES (%s,
                    (SELECT MIN(trade_date) FROM trade_log
                     WHERE code = %s AND direction = 'buy' AND execution_mode = 'paper'),
                    %s, %s, %s, %s, %s, %s, %s, %s, 'triggered')""",
            (
                signal.code,
                signal.code,
                Decimal(str(signal.entry_price)),
                Decimal(str(signal.peak_price)),
                Decimal(str(signal.current_price)),
                Decimal(str(signal.unrealized_pnl_pct)),
                Decimal(str(signal.drawdown_from_peak_pct)),
                signal.level,
                trigger_date,
                Decimal(str(signal.current_price)),
            ),
        )

    def update_position_snapshot_after_sell(
        self,
        conn,
        strategy_id: str,
        sold_codes: list[str],
        trade_date: date,
    ) -> None:
        """PMS卖出后更新position_snapshot，确保信号生成时看到最新持仓。

        删除已卖出股票的最新position_snapshot记录。
        """
        if not sold_codes:
            return

        cur = conn.cursor()
        latest_date_sql = """
            SELECT MAX(trade_date) FROM position_snapshot
            WHERE strategy_id = %s AND execution_mode = 'paper'
        """
        cur.execute(latest_date_sql, (strategy_id,))
        row = cur.fetchone()
        latest_date = row[0] if row else None

        if not latest_date:
            return

        for code in sold_codes:
            cur.execute(
                """DELETE FROM position_snapshot
                WHERE code = %s AND trade_date = %s
                  AND strategy_id = %s AND execution_mode = 'paper'""",
                (code, latest_date, strategy_id),
            )
            logger.info("[PMS] position_snapshot已更新: 删除 %s @ %s", code, latest_date)
