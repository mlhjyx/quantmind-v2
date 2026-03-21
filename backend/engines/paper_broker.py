"""Paper Trading状态化Broker — 持久化SimBroker状态。

从DB加载持仓状态 → 执行调仓 → 写回DB。
包装现有SimBroker，不修改原始引擎代码。
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import numpy as np
import pandas as pd

from engines.backtest_engine import BacktestConfig, Fill, SimBroker

logger = logging.getLogger(__name__)


@dataclass
class PaperState:
    """Paper Trading状态快照。"""

    cash: float
    holdings: dict[str, int]  # code → shares
    nav: float
    last_trade_date: Optional[date] = None
    last_rebalance_date: Optional[date] = None


class PaperBroker:
    """状态化Paper Trading Broker。

    负责:
    1. 从DB加载上一次的持仓/现金状态
    2. 委托SimBroker执行交易（复用封板检测、整手约束等逻辑）
    3. 将新状态写回DB（trade_log, position_snapshot, performance_series）
    """

    def __init__(
        self,
        strategy_id: str,
        initial_capital: float = 1_000_000.0,
    ):
        self.strategy_id = strategy_id
        self.initial_capital = initial_capital
        self.broker: Optional[SimBroker] = None
        self.state: Optional[PaperState] = None

    def load_state(self, conn) -> PaperState:
        """从DB加载最新Paper Trading状态。

        读取position_snapshot最新日期的全部持仓。
        如果是首次运行（无历史），初始化为全现金。
        """
        # 查找最新快照日期
        cur = conn.cursor()
        cur.execute(
            """SELECT MAX(trade_date)
               FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = 'paper'""",
            (self.strategy_id,),
        )
        row = cur.fetchone()
        last_date = row[0] if row else None

        if last_date is None:
            # 首次运行：全现金
            logger.info("[PaperBroker] 首次运行，初始化全现金状态")
            state = PaperState(
                cash=self.initial_capital,
                holdings={},
                nav=self.initial_capital,
            )
        else:
            # 加载持仓
            pos_df = pd.read_sql(
                """SELECT code, quantity, market_value
                   FROM position_snapshot
                   WHERE strategy_id = %s AND trade_date = %s
                     AND execution_mode = 'paper'""",
                conn,
                params=(self.strategy_id, last_date),
            )

            holdings = {}
            for _, r in pos_df.iterrows():
                if r["quantity"] > 0:
                    holdings[r["code"]] = int(r["quantity"])

            # 读取NAV和现金比率
            perf = pd.read_sql(
                """SELECT nav, cash_ratio
                   FROM performance_series
                   WHERE strategy_id = %s AND trade_date = %s
                     AND execution_mode = 'paper'""",
                conn,
                params=(self.strategy_id, last_date),
            )

            if not perf.empty:
                nav = float(perf.iloc[0]["nav"])
                cash_ratio = float(perf.iloc[0]["cash_ratio"] or 0)
                cash = nav * cash_ratio
            else:
                nav = self.initial_capital
                cash = self.initial_capital

            # 查最近一次调仓日
            cur.execute(
                """SELECT MAX(trade_date)
                   FROM trade_log
                   WHERE strategy_id = %s AND execution_mode = 'paper'""",
                (self.strategy_id,),
            )
            rebal_row = cur.fetchone()

            state = PaperState(
                cash=cash,
                holdings=holdings,
                nav=nav,
                last_trade_date=last_date,
                last_rebalance_date=rebal_row[0] if rebal_row else None,
            )
            logger.info(
                f"[PaperBroker] 加载状态: date={last_date}, "
                f"NAV={nav:.0f}, cash={cash:.0f}, "
                f"持仓={len(holdings)}只"
            )

        # 初始化SimBroker
        bt_config = BacktestConfig(initial_capital=self.initial_capital)
        self.broker = SimBroker(bt_config)
        self.broker.cash = state.cash
        self.broker.holdings = dict(state.holdings)
        self.state = state

        return state

    def needs_rebalance(self, trade_date: date, conn) -> bool:
        """判断今天是否需要调仓（月频：每月最后一个交易日）。

        逻辑：查询trading_calendar，如果今天是本月最后一个交易日，则调仓。
        首次运行（无历史持仓）也触发调仓。
        """
        if not self.state or not self.state.holdings:
            logger.info("[PaperBroker] 无持仓，需要初始建仓")
            return True

        cur = conn.cursor()
        cur.execute(
            """SELECT MAX(trade_date)
               FROM trading_calendar
               WHERE market = 'astock' AND is_trading_day = TRUE
                 AND DATE_TRUNC('month', trade_date) = DATE_TRUNC('month', %s::date)
                 AND trade_date <= %s""",
            (trade_date, trade_date),
        )
        row = cur.fetchone()
        last_trading_day_of_month = row[0] if row else None

        if last_trading_day_of_month and trade_date == last_trading_day_of_month:
            logger.info(
                f"[PaperBroker] {trade_date} 是本月最后交易日，触发调仓"
            )
            return True

        logger.info(f"[PaperBroker] {trade_date} 非调仓日")
        return False

    def execute_rebalance(
        self,
        target_weights: dict[str, float],
        trade_date: date,
        price_data: pd.DataFrame,
    ) -> list[Fill]:
        """执行调仓：先卖后买。

        复用SimpleBacktester._rebalance()的逻辑，
        但直接操作self.broker（状态化，非一次性）。

        Args:
            target_weights: {code: weight} 目标权重
            trade_date: 执行日期
            price_data: 当日全市场价格数据

        Returns:
            成交记录列表
        """
        assert self.broker is not None, "必须先调用load_state()"

        self.broker.new_day()

        # 构建price_idx和today_close
        day_data = price_data[price_data["trade_date"] == trade_date]
        if day_data.empty:
            logger.warning(f"[PaperBroker] {trade_date} 无价格数据")
            return []

        price_idx = {}
        today_close = {}
        for _, row in day_data.iterrows():
            price_idx[(row["code"], trade_date)] = row
            today_close[row["code"]] = row["close"]

        portfolio_value = self.broker.get_portfolio_value(today_close)

        # 复用_rebalance逻辑
        fills = self._do_rebalance(
            target_weights, portfolio_value, trade_date, price_idx, today_close
        )

        logger.info(
            f"[PaperBroker] 调仓完成: {len(fills)}笔成交, "
            f"NAV={self.broker.get_portfolio_value(today_close):.0f}"
        )
        return fills

    def _do_rebalance(
        self,
        target: dict[str, float],
        portfolio_value: float,
        exec_date: date,
        price_idx: dict,
        today_close: dict,
    ) -> list[Fill]:
        """先卖后买调仓（从SimpleBacktester._rebalance复制，适配PaperBroker）。"""
        broker = self.broker
        fills = []
        lot_size = broker.config.lot_size

        # 1. 计算目标股数
        target_shares = {}
        for code, weight in target.items():
            close_price = today_close.get(code, 0)
            if close_price > 0:
                target_value = portfolio_value * weight
                shares = int(target_value / close_price / lot_size) * lot_size
                if shares > 0:
                    target_shares[code] = shares

        # 2. 卖出
        for code, curr_shares in list(broker.holdings.items()):
            target_s = target_shares.get(code, 0)
            if curr_shares > target_s:
                row = price_idx.get((code, exec_date))
                if row is None:
                    continue
                if not broker.can_trade(code, "sell", row):
                    logger.debug(f"[{exec_date}] {code} 卖出受限")
                    continue
                fill = broker.execute_sell(code, curr_shares - target_s, row)
                if fill:
                    fills.append(fill)

        # 3. 买入（按金额降序）
        buy_orders = []
        for code, target_s in target_shares.items():
            curr_shares = broker.holdings.get(code, 0)
            if target_s > curr_shares:
                buy_amount = (target_s - curr_shares) * today_close.get(code, 0)
                buy_orders.append((code, buy_amount))
        buy_orders.sort(key=lambda x: -x[1])

        for code, buy_amount in buy_orders:
            if broker.cash < buy_amount * 0.1:
                break
            row = price_idx.get((code, exec_date))
            if row is None:
                continue
            if not broker.can_trade(code, "buy", row):
                logger.debug(f"[{exec_date}] {code} 买入受限")
                continue
            fill = broker.execute_buy(code, min(buy_amount, broker.cash), row)
            if fill:
                fills.append(fill)

        return fills

    def get_current_nav(self, today_close: dict[str, float]) -> float:
        """获取当前NAV。"""
        assert self.broker is not None
        return self.broker.get_portfolio_value(today_close)

    def save_state(
        self,
        trade_date: date,
        fills: list[Fill],
        today_close: dict[str, float],
        benchmark_close: float,
        conn,
    ) -> None:
        """将当前状态写入DB（单事务）。

        写入:
        1. trade_log — 每笔成交一行
        2. position_snapshot — 当前全部持仓
        3. performance_series — 当日绩效
        """
        assert self.broker is not None
        cur = conn.cursor()

        try:
            # ── 1. trade_log ──
            for fill in fills:
                cur.execute(
                    """INSERT INTO trade_log
                       (code, trade_date, strategy_id, direction, quantity,
                        fill_price, slippage_bps, commission, stamp_tax,
                        total_cost, execution_mode)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'paper')
                       ON CONFLICT DO NOTHING""",
                    (
                        fill.code,
                        fill.trade_date,
                        self.strategy_id,
                        fill.direction,
                        fill.shares,
                        float(fill.price),
                        float(fill.slippage),
                        float(fill.commission),
                        float(fill.tax),
                        float(fill.total_cost),
                    ),
                )

            # ── 2. position_snapshot ──
            # 删除当日旧快照（幂等）
            cur.execute(
                """DELETE FROM position_snapshot
                   WHERE trade_date = %s AND strategy_id = %s
                     AND execution_mode = 'paper'""",
                (trade_date, self.strategy_id),
            )

            nav = self.broker.get_portfolio_value(today_close)
            for code, shares in self.broker.holdings.items():
                price = today_close.get(code, 0)
                mv = shares * price
                weight = mv / nav if nav > 0 else 0
                cur.execute(
                    """INSERT INTO position_snapshot
                       (code, trade_date, strategy_id, quantity, market_value,
                        weight, execution_mode)
                       VALUES (%s, %s, %s, %s, %s, %s, 'paper')""",
                    (code, trade_date, self.strategy_id, shares, mv, weight),
                )

            # ── 3. performance_series ──
            cash_ratio = self.broker.cash / nav if nav > 0 else 1.0
            position_count = len(self.broker.holdings)

            # 计算日收益率
            prev_nav = self.state.nav if self.state else self.initial_capital
            daily_return = (nav / prev_nav - 1) if prev_nav > 0 else 0
            cum_return = (nav / self.initial_capital - 1)

            # 计算回撤（需要历史最高NAV）
            cur.execute(
                """SELECT COALESCE(MAX(nav), %s)
                   FROM performance_series
                   WHERE strategy_id = %s AND execution_mode = 'paper'""",
                (self.initial_capital, self.strategy_id),
            )
            peak_nav = float(cur.fetchone()[0])
            peak_nav = max(peak_nav, nav)
            drawdown = (nav / peak_nav - 1) if peak_nav > 0 else 0

            # 基准NAV
            cur.execute(
                """SELECT nav FROM performance_series
                   WHERE strategy_id = %s AND execution_mode = 'paper'
                   ORDER BY trade_date ASC LIMIT 1""",
                (self.strategy_id,),
            )
            first_row = cur.fetchone()
            if first_row:
                first_nav = float(first_row[0])
                # 计算基准NAV（假设初始与策略等值）
                cur.execute(
                    """SELECT close FROM index_daily
                       WHERE index_code = '000300.SH'
                       ORDER BY trade_date ASC LIMIT 1""",
                )
                # 简化：用benchmark_close直接存
                bench_nav_val = benchmark_close
            else:
                bench_nav_val = benchmark_close

            # 换手率
            turnover = sum(abs(f.amount) for f in fills) / nav if nav > 0 else 0

            cur.execute(
                """INSERT INTO performance_series
                   (trade_date, strategy_id, nav, daily_return, cumulative_return,
                    drawdown, cash_ratio, position_count, turnover,
                    benchmark_nav, execution_mode)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'paper')
                   ON CONFLICT (trade_date, strategy_id) DO UPDATE SET
                    nav=EXCLUDED.nav, daily_return=EXCLUDED.daily_return,
                    cumulative_return=EXCLUDED.cumulative_return,
                    drawdown=EXCLUDED.drawdown, cash_ratio=EXCLUDED.cash_ratio,
                    position_count=EXCLUDED.position_count, turnover=EXCLUDED.turnover,
                    benchmark_nav=EXCLUDED.benchmark_nav""",
                (
                    trade_date,
                    self.strategy_id,
                    nav,
                    daily_return,
                    cum_return,
                    drawdown,
                    cash_ratio,
                    position_count,
                    turnover,
                    bench_nav_val,
                ),
            )

            conn.commit()
            logger.info(
                f"[PaperBroker] 状态已保存: date={trade_date}, NAV={nav:.0f}, "
                f"positions={position_count}, fills={len(fills)}"
            )

        except Exception:
            conn.rollback()
            raise
