"""Paper Trading状态化Broker — 持久化SimBroker状态。

从DB加载持仓状态 → 执行调仓 → 写回DB。
包装现有SimBroker，不修改原始引擎代码。
"""

from dataclasses import dataclass
from datetime import UTC, date

import pandas as pd
import structlog

from engines.backtest_engine import BacktestConfig, Fill, PendingOrder, SimBroker
from engines.base_broker import BaseBroker

logger = structlog.get_logger(__name__)


@dataclass
class PaperState:
    """Paper Trading状态快照。"""

    cash: float
    holdings: dict[str, int]  # code → shares
    nav: float
    last_trade_date: date | None = None
    last_rebalance_date: date | None = None


class PaperBroker(BaseBroker):
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
        self.broker: SimBroker | None = None
        self.state: PaperState | None = None

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

            # R3 fix: 直接读取cash列，不再从cash_ratio反推
            perf = pd.read_sql(
                """SELECT nav, cash, cash_ratio
                   FROM performance_series
                   WHERE strategy_id = %s AND trade_date = %s
                     AND execution_mode = 'paper'""",
                conn,
                params=(self.strategy_id, last_date),
            )

            if not perf.empty:
                nav = float(perf.iloc[0]["nav"])
                cash_val = perf.iloc[0]["cash"]
                if cash_val is not None:
                    cash = float(cash_val)
                else:
                    # fallback for old rows without cash column
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
        # R4 fix: 去掉 "trade_date <= %s" 约束，查整个月的最后交易日
        cur.execute(
            """SELECT MAX(trade_date)
               FROM trading_calendar
               WHERE market = 'astock' AND is_trading_day = TRUE
                 AND DATE_TRUNC('month', trade_date) = DATE_TRUNC('month', %s::date)""",
            (trade_date,),
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
        signal_date: date | None = None,
    ) -> tuple[list[Fill], list[PendingOrder]]:
        """执行调仓：先卖后买，封板记录为PendingOrder。

        复用SimpleBacktester._rebalance()的逻辑，
        但直接操作self.broker（状态化，非一次性）。

        Args:
            target_weights: {code: weight} 目标权重
            trade_date: 执行日期
            price_data: 当日全市场价格数据
            signal_date: 信号生成日期（用于PendingOrder记录）

        Returns:
            (成交记录列表, 新增的pending_orders列表)
        """
        assert self.broker is not None, "必须先调用load_state()"

        self.broker.new_day()

        # 构建price_idx和today_close
        day_data = price_data[price_data["trade_date"] == trade_date]
        if day_data.empty:
            logger.warning(f"[PaperBroker] {trade_date} 无价格数据")
            return [], []

        price_idx = {}
        today_close = {}
        for _, row in day_data.iterrows():
            price_idx[(row["code"], trade_date)] = row
            today_close[row["code"]] = row["close"]

        portfolio_value = self.broker.get_portfolio_value(today_close)

        # 执行调仓（封板记录为pending）
        fills, new_pending = self._do_rebalance(
            target_weights, portfolio_value, trade_date, price_idx, today_close,
            signal_date or trade_date,
        )

        logger.info(
            f"[PaperBroker] 调仓完成: {len(fills)}笔成交, "
            f"{len(new_pending)}只封板待补, "
            f"NAV={self.broker.get_portfolio_value(today_close):.0f}"
        )
        return fills, new_pending

    def process_pending_orders(
        self,
        pending_orders: list[PendingOrder],
        trade_date: date,
        price_data: pd.DataFrame,
        next_rebal_date: date | None = None,
        conn=None,
    ) -> tuple[list[Fill], list[PendingOrder]]:
        """处理封板补单。T+1日尝试买入。

        Args:
            pending_orders: 待处理的pending_orders列表
            trade_date: 当日日期（应为exec_date + 1交易日）
            price_data: 当日价格数据
            next_rebal_date: 下次调仓日（用于判断距离）
            conn: 数据库连接（用于计算交易日间隔）

        Returns:
            (成交列表, 更新后的pending_orders列表)
        """
        assert self.broker is not None, "必须先调用load_state()"

        self.broker.new_day()

        day_data = price_data[price_data["trade_date"] == trade_date]
        if day_data.empty:
            logger.warning(f"[PaperBroker] 补单: {trade_date} 无价格数据")
            return [], pending_orders

        price_idx = {}
        today_close = {}
        for _, row in day_data.iterrows():
            price_idx[(row["code"], trade_date)] = row
            today_close[row["code"]] = row["close"]

        # 检查距下次调仓是否太近
        min_days = 5
        if next_rebal_date and conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT COUNT(*) FROM trading_calendar
                   WHERE market='astock' AND is_trading_day=TRUE
                   AND trade_date > %s AND trade_date <= %s""",
                (trade_date, next_rebal_date),
            )
            days_to_next = cur.fetchone()[0]
            if days_to_next <= min_days:
                for po in pending_orders:
                    if po.status == "pending":
                        po.status = "cancelled"
                        po.cancel_reason = f"too_close_to_next_rebalance({days_to_next}d)"
                logger.info(f"[PaperBroker] 补单: 距下次调仓{days_to_next}d, 全部取消")
                return [], pending_orders

        # 筛选可执行的pending
        actionable = [po for po in pending_orders if po.status == "pending"]
        actionable.sort(key=lambda x: -x.original_score)

        max_retry = 3
        retry_weight_cap = 0.10
        to_execute = actionable[:max_retry]

        for po in actionable[max_retry:]:
            po.status = "cancelled"
            po.cancel_reason = "exceeded_max_retry_count"

        fills = []
        for po in to_execute:
            row = price_idx.get((po.code, trade_date))
            if row is None:
                po.status = "cancelled"
                po.cancel_reason = "no_price_data"
                continue

            if not self.broker.can_trade(po.code, "buy", row):
                po.status = "cancelled"
                po.cancel_reason = "still_limit_up_or_suspended"
                continue

            portfolio_value = self.broker.get_portfolio_value(today_close)
            target_amount = portfolio_value * min(po.target_weight, retry_weight_cap)

            open_price = row.get("open", 0)
            if open_price <= 0 or target_amount < open_price * self.broker.config.lot_size:
                po.status = "cancelled"
                po.cancel_reason = "insufficient_for_one_lot"
                continue

            fill = self.broker.execute_buy(po.code, min(target_amount, self.broker.cash), row)
            if fill:
                fills.append(fill)
                po.status = "filled"
                logger.info(f"[PaperBroker] 补单成功: {po.code} {fill.shares}股")
            else:
                po.status = "cancelled"
                po.cancel_reason = "insufficient_cash"

        return fills, pending_orders

    def _do_rebalance(
        self,
        target: dict[str, float],
        portfolio_value: float,
        exec_date: date,
        price_idx: dict,
        today_close: dict,
        signal_date: date | None = None,
    ) -> tuple[list[Fill], list[PendingOrder]]:
        """先卖后买调仓，封板记录为PendingOrder。"""
        broker = self.broker
        fills = []
        new_pending = []
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

        # 3. 买入（封板记录为pending）
        buy_orders = []
        for code, target_s in target_shares.items():
            curr_shares = broker.holdings.get(code, 0)
            if target_s > curr_shares:
                buy_amount = (target_s - curr_shares) * today_close.get(code, 0)
                weight = target.get(code, 0)
                buy_orders.append((code, buy_amount, weight))
        buy_orders.sort(key=lambda x: -x[1])

        for code, buy_amount, weight in buy_orders:
            if broker.cash < buy_amount * 0.1:
                break
            row = price_idx.get((code, exec_date))
            if row is None:
                continue
            if not broker.can_trade(code, "buy", row):
                logger.debug(f"[{exec_date}] {code} 买入封板，加入补单队列")
                new_pending.append(PendingOrder(
                    code=code,
                    signal_date=signal_date or exec_date,
                    exec_date=exec_date,
                    target_weight=weight,
                    original_score=buy_amount,
                ))
                continue
            fill = broker.execute_buy(code, min(buy_amount, broker.cash), row)
            if fill:
                fills.append(fill)

        return fills, new_pending

    def get_current_nav(self, today_close: dict[str, float]) -> float:
        """获取当前NAV。"""
        assert self.broker is not None
        return self.broker.get_portfolio_value(today_close)

    # ── BaseBroker统一接口 ──

    def get_positions(self) -> dict[str, int]:
        """获取当前持仓（委托给内部SimBroker）。"""
        if self.broker is None:
            return dict(self.state.holdings) if self.state else {}
        return dict(self.broker.holdings)

    def get_cash(self) -> float:
        """获取当前可用现金。"""
        if self.broker is None:
            return self.state.cash if self.state else self.initial_capital
        return self.broker.cash

    def get_total_value(self, prices: dict[str, float]) -> float:
        """计算组合总市值。"""
        if self.broker is None:
            # 未初始化时用state估算
            if self.state is None:
                return self.initial_capital
            holdings_value = sum(
                shares * prices.get(code, 0)
                for code, shares in self.state.holdings.items()
            )
            return holdings_value + self.state.cash
        return self.broker.get_portfolio_value(prices)

    def save_fills_only(
        self,
        fills: list[Fill],
        conn,
    ) -> None:
        """只写trade_log（成交记录），不更新NAV/position_snapshot。

        方案B拆分: execute阶段只写成交，NAV在signal阶段更新。
        """
        if not fills:
            return
        from datetime import datetime
        now_utc = datetime.now(UTC)
        cur = conn.cursor()
        try:
            for fill in fills:
                cur.execute(
                    """INSERT INTO trade_log
                       (code, trade_date, strategy_id, direction, quantity,
                        fill_price, slippage_bps, commission, stamp_tax,
                        total_cost, execution_mode, executed_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'paper', %s)
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
                        now_utc,
                    ),
                )
            conn.commit()
            logger.info(f"[PaperBroker] trade_log已保存: {len(fills)}笔成交")
        except Exception:
            conn.rollback()
            raise

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
        from datetime import datetime
        now_utc = datetime.now(UTC)
        cur = conn.cursor()

        try:
            # ── 1. trade_log ──
            for fill in fills:
                cur.execute(
                    """INSERT INTO trade_log
                       (code, trade_date, strategy_id, direction, quantity,
                        fill_price, slippage_bps, commission, stamp_tax,
                        total_cost, execution_mode, executed_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'paper', %s)
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
                        now_utc,
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

            # 计算日收益率（从DB读前一日NAV，防止重跑时self.state指向错误日期）
            cur.execute(
                """SELECT nav FROM performance_series
                   WHERE strategy_id = %s AND execution_mode = 'paper'
                     AND trade_date < %s
                   ORDER BY trade_date DESC LIMIT 1""",
                (self.strategy_id, trade_date),
            )
            prev_row = cur.fetchone()
            prev_nav = float(prev_row[0]) if prev_row else self.initial_capital
            daily_return = (nav / prev_nav - 1) if prev_nav > 0 else 0
            cum_return = (nav / self.initial_capital - 1)

            # 计算回撤（需要历史最高NAV）
            # peak = max(initial_capital, 当日及之前所有NAV)
            # - 必须包含initial_capital（首日买入即亏也算回撤）
            # - 必须限制 trade_date <= 当日（幂等重跑不被未来数据污染）
            cur.execute(
                """SELECT COALESCE(MAX(nav), %s)
                   FROM performance_series
                   WHERE strategy_id = %s AND execution_mode = 'paper'
                     AND trade_date <= %s""",
                (self.initial_capital, self.strategy_id, trade_date),
            )
            peak_nav = float(cur.fetchone()[0])
            peak_nav = max(peak_nav, nav, self.initial_capital)
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
                float(first_row[0])
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

            # R3 fix: 直接存cash金额，不依赖cash_ratio反推
            actual_cash = self.broker.cash

            cur.execute(
                """INSERT INTO performance_series
                   (trade_date, strategy_id, nav, daily_return, cumulative_return,
                    drawdown, cash_ratio, cash, position_count, turnover,
                    benchmark_nav, execution_mode)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'paper')
                   ON CONFLICT (trade_date, strategy_id) DO UPDATE SET
                    nav=EXCLUDED.nav, daily_return=EXCLUDED.daily_return,
                    cumulative_return=EXCLUDED.cumulative_return,
                    drawdown=EXCLUDED.drawdown, cash_ratio=EXCLUDED.cash_ratio,
                    cash=EXCLUDED.cash,
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
                    actual_cash,
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
