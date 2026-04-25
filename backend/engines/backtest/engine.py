"""SimpleBacktester — 回测主循环。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import structlog

from engines.backtest.broker import SimBroker
from engines.backtest.config import BacktestConfig
from engines.backtest.types import (
    BacktestResult,
    CorporateAction,
    Fill,
    PendingOrder,
    PendingOrderStats,
)

logger = structlog.get_logger(__name__)


class SimpleBacktester:
    """Phase 0 简单回测引擎。

    流程:
    1. 遍历每个交易日
    2. 处理封板补单（如果有pending_orders）
    3. 在调仓日: 读取目标持仓 → 先卖后买 → 记录成交（封板记录为pending）
    4. 非调仓日: 更新NAV
    5. 计算绩效指标
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.pending_orders: list[PendingOrder] = []
        self.max_retry_orders: int = 3         # 单次调仓最多补3只
        self.retry_weight_cap: float = 0.10    # 单只补单上限10%
        self.min_days_to_next_rebal: int = 5   # 距下次调仓<5天不补

    def run(
        self,
        target_portfolios: dict[date, dict[str, float]],
        price_data: pd.DataFrame,
        benchmark_data: pd.DataFrame | None = None,
        dividend_calendar: dict[date, list[CorporateAction]] | None = None,
    ) -> BacktestResult:
        """执行回测。

        Args:
            target_portfolios: {signal_date: {code: weight}}
                signal_date是信号日(周五), 执行在下一个交易日
            price_data: 全量价格数据 (code, trade_date, open, close, ...)
                        必须包含up_limit, down_limit, turnover_rate
            benchmark_data: 基准指数数据 (trade_date, close)

        Returns:
            BacktestResult
        """
        broker = SimBroker(self.config)

        # 准备数据
        all_dates = sorted(price_data["trade_date"].unique())
        signal_dates = sorted(target_portfolios.keys())

        # 构建执行日映射: signal_date → exec_date (下一个交易日)
        exec_map = {}
        for sd in signal_dates:
            # 找到signal_date之后的第一个交易日
            future_dates = [d for d in all_dates if d > sd]
            if future_dates:
                exec_map[future_dates[0]] = sd

        # P17: 单位标准化(千元→元, 万元→元) — 在索引构建前完成
        from engines.datafeed import DataFeed as _DataFeed
        _feed = _DataFeed(price_data)
        _feed.standardize_units()
        price_data = _feed.df

        # 价格索引: MultiIndex (code, trade_date) → 快速.loc查询
        # P15: 替代iterrows()遍历6M行，回测启动从分钟级→秒级
        if "code" not in price_data.columns or "trade_date" not in price_data.columns:
            raise ValueError("price_data必须包含code和trade_date列")
        price_data = price_data.sort_values(["code", "trade_date"], kind="mergesort")
        # 构建(code,trade_date)→row dict, 避免MultiIndex set_index消耗大量内存
        _price_dict: dict[tuple, int] = {}
        for idx, (code, td) in enumerate(
            zip(price_data["code"].values, price_data["trade_date"].values, strict=False)
        ):
            _price_dict[(code, td)] = idx

        class _PriceIdx:
            """price_idx.get((code, date))兼容层，底层用dict→iloc查询。"""
            __slots__ = ()
            def get(self, key, default=None):
                idx = _price_dict.get(key)
                if idx is not None:
                    return price_data.iloc[idx]
                return default

        price_idx = _PriceIdx()

        # 每日收盘价: groupby构建(避免pivot_table OOM, 12年×5000+股)
        daily_close: dict[date, dict[str, float]] = {}
        for td, grp in price_data.groupby("trade_date"):
            daily_close[td] = dict(zip(grp["code"], grp["close"], strict=False))

        # 每日adj_close: PMS用(避免除权日false trigger)
        _has_adj_close = "adj_close" in price_data.columns
        daily_adj_close: dict[date, dict[str, float]] = {}
        if _has_adj_close:
            for td, grp in price_data.groupby("trade_date"):
                daily_adj_close[td] = dict(zip(grp["code"], grp["adj_close"], strict=False))

        # 回测主循环
        nav_series = {}
        trades = []
        holdings_history = {}
        turnover_dates = {}
        prev_weights = {}
        self.pending_orders = []  # 重置pending_orders

        # PMS利润保护状态: {code: {buy_price, buy_date, max_price}}
        pms_state: dict[str, dict] = {}
        pms_pending_sells: list[str] = []  # next_open模式下延迟到T+1卖出的code
        pms_events: list[dict] = []  # 记录触发事件

        # P14: 退市检测状态
        _delist_count: dict[str, int] = {}  # code → 连续无数据天数
        _last_known_price: dict[str, float] = {}  # code → 最后已知收盘价

        for _i, td in enumerate(all_dates):
            broker.new_day()

            # ===== P1+P2: 分红/送股处理(开盘前) =====
            if dividend_calendar:
                day_actions = dividend_calendar.get(td, [])
                if day_actions:
                    broker.process_corporate_actions(day_actions)

            # ===== P14: 退市检测+自动清算 =====
            if broker.holdings:
                today_codes = daily_close.get(td, {})
                for code in list(broker.holdings.keys()):
                    if code in today_codes:
                        # 有价格数据 → 清除退市计数
                        _delist_count.pop(code, None)
                    else:
                        # 无价格数据 → 累计天数
                        _delist_count[code] = _delist_count.get(code, 0) + 1
                        if _delist_count[code] >= 20:
                            # 连续20日无数据 → 退市清算(按最后已知价格)
                            shares = broker.holdings.pop(code, 0)
                            last_price = _last_known_price.get(code, 0)
                            if shares > 0 and last_price > 0:
                                proceeds = shares * last_price
                                broker.cash += proceeds
                                logger.warning(
                                    "[%s] %s 退市清算: %d股 @ %.2f = ¥%.0f",
                                    td, code, shares, last_price, proceeds,
                                )
                            _delist_count.pop(code, None)
                    # 记录最后已知价格
                    if code in today_codes and today_codes[code] > 0:
                        _last_known_price[code] = today_codes[code]

            # ===== PMS: 执行T+1延迟卖出 =====
            if self.config.pms.enabled and pms_pending_sells:
                # NOTE (Session 36 PR audit §3.3 closure): 7 处 broker.can_trade
                # 均不传 symbols_info — by design. 当前 PT/回测 universe 通过
                # `load_universe` 在入口过滤 ST (data_pipeline 层), 故引擎 day loop
                # 中 ST 永不到达 broker. PriceLimitValidator 用 `_infer_price_limit`
                # 默认 (主板 10%) 即可. 若未来策略允许 ST (e.g. PEAD on ST), 需:
                # (a) 引擎构造 symbols_info DataFrame[code, 'price_limit'=0.05 for ST]
                # (b) 7 处 broker.can_trade(code, dir, row, symbols_info) 全部更新
                # (c) Universe filter 同步放开 ST
                # 当前 dormant 路径已在 validators.py + broker.py 完成签名透传, 测试
                # backend/tests/test_can_trade_board.py::test_st_5pct_limit_up 验证.
                for code in list(pms_pending_sells):
                    if code not in broker.holdings:
                        pms_pending_sells.remove(code)
                        continue
                    row = price_idx.get((code, td))
                    if row is None:
                        continue
                    if not broker.can_trade(code, "sell", row):
                        continue  # 跌停卖不出,保留在pending
                    shares = broker.holdings.get(code, 0)
                    if shares > 0:
                        fill = broker.execute_sell(code, shares, row)
                        if fill:
                            trades.append(fill)
                            pms_state.pop(code, None)
                    pms_pending_sells.remove(code)

            # ===== 处理封板补单 =====
            if self.pending_orders:
                self._process_pending_orders(
                    broker, td, price_idx, daily_close.get(td, {}),
                    all_dates, exec_map, trades
                )

            # ===== PMS: 日频利润保护检查(用adj_close避免除权日false trigger) =====
            if self.config.pms.enabled and broker.holdings:
                today_prices = daily_close.get(td, {})
                today_adj = daily_adj_close.get(td, {}) if _has_adj_close else {}
                for code in list(broker.holdings.keys()):
                    if code in pms_pending_sells:
                        continue  # 已在待卖队列
                    close = today_prices.get(code, 0)
                    if close <= 0:
                        continue
                    state = pms_state.get(code)
                    if state is None:
                        continue  # 无买入记录(不应发生)

                    # 用adj_close做PMS判断(除权日raw close跳变不代表真实亏损)
                    adj = today_adj.get(code, close)  # fallback to raw if no adj

                    # 更新max_price(adj_close)
                    state["max_price"] = max(state["max_price"], adj)

                    # 计算PnL和从峰值回撤
                    pnl = (adj - state["buy_price"]) / state["buy_price"]
                    dd = (adj - state["max_price"]) / state["max_price"] if state["max_price"] > 0 else 0

                    # 阶梯式检查(tiers按pnl从高到低)
                    triggered = False
                    for pnl_thresh, trail_stop in self.config.pms.tiers:
                        if pnl > pnl_thresh and dd < -trail_stop:
                            triggered = True
                            pms_events.append({
                                "date": td, "code": code,
                                "pnl": pnl, "dd": dd,
                                "tier": f">{pnl_thresh:.0%}/>{trail_stop:.0%}",
                                "buy_price": state["buy_price"],
                                "close": close, "max_price": state["max_price"],
                            })
                            break

                    if triggered:
                        if self.config.pms.exec_mode == "same_close":
                            # 当日收盘卖(乐观)
                            row = price_idx.get((code, td))
                            if row is not None and broker.can_trade(code, "sell", row):
                                shares = broker.holdings.get(code, 0)
                                if shares > 0:
                                    fill = broker.execute_sell(code, shares, row)
                                    if fill:
                                        trades.append(fill)
                                        pms_state.pop(code, None)
                        else:
                            # next_open: 延迟到T+1
                            pms_pending_sells.append(code)

            # 检查是否是执行日
            if td in exec_map:
                signal_date = exec_map[td]
                target = target_portfolios[signal_date]

                # 计算当前组合市值
                portfolio_value = broker.get_portfolio_value(daily_close.get(td, {}))

                # 先卖后买（封板记录为pending）
                day_fills, new_pending = self._rebalance_with_pending(
                    broker, target, portfolio_value, td, price_idx,
                    daily_close.get(td, {}), signal_date
                )
                trades.extend(day_fills)
                self.pending_orders.extend(new_pending)

                # PMS: 记录新买入股票的buy_price(用adj_close避免除权日偏差)
                if self.config.pms.enabled:
                    today_adj_pms = daily_adj_close.get(td, {}) if _has_adj_close else {}
                    for fill in day_fills:
                        if fill.direction == "buy":
                            adj_buy = today_adj_pms.get(fill.code, fill.price)
                            pms_state[fill.code] = {
                                "buy_price": adj_buy,
                                "buy_date": fill.trade_date,
                                "max_price": adj_buy,
                            }
                    # 清理已卖出的pms_state
                    for code in list(pms_state.keys()):
                        if code not in broker.holdings:
                            pms_state.pop(code, None)

                holdings_history[td] = dict(broker.holdings)

            # P13: 每日记录换手率(含PMS卖出/封板补单, 不限于调仓日)
            pv = broker.get_portfolio_value(daily_close.get(td, {}))
            new_weights = {}
            for code, shares in broker.holdings.items():
                p = daily_close.get(td, {}).get(code, 0)
                if pv > 0:
                    new_weights[code] = shares * p / pv

            turnover = sum(
                abs(new_weights.get(c, 0) - prev_weights.get(c, 0))
                for c in set(new_weights) | set(prev_weights)
            ) / 2
            if turnover > 0.001:  # 忽略浮点噪声
                turnover_dates[td] = turnover
            prev_weights = new_weights

            # 每日NAV
            nav_series[td] = pv

        # 转换结果
        nav = pd.Series(nav_series).sort_index()
        daily_ret = nav.pct_change().fillna(0)

        # 基准
        if benchmark_data is not None and not benchmark_data.empty:
            bench = benchmark_data.set_index("trade_date")["close"]
            bench_nav = bench / bench.iloc[0] * self.config.initial_capital
            bench_ret = bench.pct_change().fillna(0)
        else:
            bench_nav = pd.Series(self.config.initial_capital, index=nav.index)
            bench_ret = pd.Series(0.0, index=nav.index)

        turnover = pd.Series(turnover_dates).sort_index()

        # 补单统计
        po_stats = self._calc_pending_order_stats(price_idx)

        return BacktestResult(
            daily_nav=nav,
            daily_returns=daily_ret,
            benchmark_nav=bench_nav,
            benchmark_returns=bench_ret,
            trades=trades,
            holdings_history=holdings_history,
            config=self.config,
            turnover_series=turnover,
            pending_order_stats=po_stats,
            pms_events=pms_events,
        )

    def _rebalance(
        self,
        broker: SimBroker,
        target: dict[str, float],
        portfolio_value: float,
        exec_date: date,
        price_idx: dict,
        today_close: dict,
    ) -> list[Fill]:
        """执行调仓: 先卖后买（向后兼容，不记录pending）。"""
        fills, _ = self._rebalance_with_pending(
            broker, target, portfolio_value, exec_date, price_idx,
            today_close, exec_date,
        )
        return fills

    def _rebalance_with_pending(
        self,
        broker: SimBroker,
        target: dict[str, float],
        portfolio_value: float,
        exec_date: date,
        price_idx: dict,
        today_close: dict,
        signal_date: date,
    ) -> tuple[list[Fill], list[PendingOrder]]:
        """执行调仓: 先卖后买，封板记录为PendingOrder。

        Returns:
            (成交列表, 新增pending_orders列表)
        """
        fills = []
        new_pending = []

        # 1. 计算目标持仓股数
        target_shares = {}
        for code, weight in target.items():
            close_price = today_close.get(code, 0)
            if close_price > 0:
                target_value = portfolio_value * weight
                shares = int(target_value / close_price / self.config.lot_size) * self.config.lot_size
                if shares > 0:
                    target_shares[code] = shares

        # 2. 卖出 (持有但不在目标中的, 或需要减仓的)
        sell_codes = []
        for code, curr_shares in list(broker.holdings.items()):
            target_s = target_shares.get(code, 0)
            if curr_shares > target_s:
                sell_codes.append((code, curr_shares - target_s))

        for code, sell_shares in sell_codes:
            row = price_idx.get((code, exec_date))
            if row is None:
                continue
            if not broker.can_trade(code, "sell", row):
                logger.debug(f"[{exec_date}] {code} 卖出受限(封板/停牌)")
                continue
            fill = broker.execute_sell(code, sell_shares, row)
            if fill:
                fills.append(fill)

        # 3. 买入 (封板记录为pending)
        buy_orders = []
        for code, target_s in target_shares.items():
            curr_shares = broker.holdings.get(code, 0)
            if target_s > curr_shares:
                buy_amount = (target_s - curr_shares) * today_close.get(code, 0)
                weight = target.get(code, 0)
                buy_orders.append((code, buy_amount, weight))

        # 按金额降序买入(优先买最大权重)
        buy_orders.sort(key=lambda x: -x[1])

        for code, buy_amount, weight in buy_orders:
            if broker.cash < buy_amount * 0.1:  # 现金太少停止买入
                break
            row = price_idx.get((code, exec_date))
            if row is None:
                continue

            if not broker.can_trade(code, "buy", row):
                # ===== 封板: 记录为pending_order =====
                logger.debug(f"[{exec_date}] {code} 买入封板，加入补单队列")
                new_pending.append(PendingOrder(
                    code=code,
                    signal_date=signal_date,
                    exec_date=exec_date,
                    target_weight=weight,
                    original_score=buy_amount,  # 用金额排序（等权下weight相同）
                ))
                continue

            fill = broker.execute_buy(code, min(buy_amount, broker.cash), row)
            if fill:
                fills.append(fill)

        return fills, new_pending

    def _process_pending_orders(
        self,
        broker: SimBroker,
        today: date,
        price_idx: dict,
        today_close: dict,
        all_dates: list[date],
        exec_map: dict[date, date],
        trades_list: list[Fill],
    ) -> None:
        """处理封板补单。T+1日尝试买入。

        规则（SPRINT_1_3B_STRATEGY_DESIGN.md §2.2）:
        - 仅买入方向
        - 最多补1次（T+1日尝试，失败放弃）
        - 距下次调仓<5天不补
        - 单次最多补3只
        - 单只不超过组合市值10%
        """
        actionable = []
        today_idx = all_dates.index(today) if today in all_dates else -1

        for po in self.pending_orders:
            if po.status != "pending":
                continue

            # 找到exec_date的下一个交易日作为retry_date
            retry_date = None
            for d in all_dates:
                if d > po.exec_date:
                    retry_date = d
                    break

            if retry_date is None or retry_date != today:
                # 不是今天该处理的
                if retry_date is not None and today > retry_date:
                    po.status = "cancelled"
                    po.cancel_reason = "expired"
                continue

            # 检查距下次调仓是否太近
            next_rebal_dates = [d for d in exec_map if d > today]
            if next_rebal_dates:
                next_rebal = min(next_rebal_dates)
                next_rebal_idx = all_dates.index(next_rebal) if next_rebal in all_dates else len(all_dates)
                days_to_next = next_rebal_idx - today_idx
                if days_to_next <= self.min_days_to_next_rebal:
                    po.status = "cancelled"
                    po.cancel_reason = f"too_close_to_next_rebalance({days_to_next}d)"
                    continue

            actionable.append(po)

        # 按original_score降序，最多补3只
        actionable.sort(key=lambda x: -x.original_score)
        to_execute = actionable[:self.max_retry_orders]

        # 超出数量上限的标记取消
        for po in actionable[self.max_retry_orders:]:
            po.status = "cancelled"
            po.cancel_reason = "exceeded_max_retry_count"

        for po in to_execute:
            row = price_idx.get((po.code, today))
            if row is None:
                po.status = "cancelled"
                po.cancel_reason = "no_price_data"
                continue

            if not broker.can_trade(po.code, "buy", row):
                po.status = "cancelled"
                po.cancel_reason = "still_limit_up_or_suspended"
                continue

            # 按当前组合市值重算目标金额
            portfolio_value = broker.get_portfolio_value(today_close)
            target_amount = portfolio_value * min(po.target_weight, self.retry_weight_cap)

            # 检查能否买入1手
            open_price = row.get("open", 0)
            if open_price <= 0 or target_amount < open_price * self.config.lot_size:
                po.status = "cancelled"
                po.cancel_reason = "insufficient_for_one_lot"
                continue

            fill = broker.execute_buy(po.code, min(target_amount, broker.cash), row)
            if fill:
                trades_list.append(fill)
                po.status = "filled"
                logger.debug(f"[{today}] 补单成功: {po.code} {fill.shares}股")
            else:
                po.status = "cancelled"
                po.cancel_reason = "insufficient_cash"

    def _calc_pending_order_stats(self, price_idx: dict) -> PendingOrderStats:
        """计算补单统计。"""
        stats = PendingOrderStats()
        if not self.pending_orders:
            return stats

        stats.total_pending = len(self.pending_orders)
        stats.filled_count = sum(1 for po in self.pending_orders if po.status == "filled")
        stats.cancelled_count = sum(1 for po in self.pending_orders if po.status == "cancelled")
        stats.fill_rate = (
            stats.filled_count / stats.total_pending
            if stats.total_pending > 0 else 0.0
        )

        # cancel_reasons统计
        for po in self.pending_orders:
            if po.status == "cancelled" and po.cancel_reason:
                stats.cancel_reasons[po.cancel_reason] = (
                    stats.cancel_reasons.get(po.cancel_reason, 0) + 1
                )

        # 补单股票T+1日平均涨幅（衡量追涨风险）
        retry_returns = []
        for po in self.pending_orders:
            if po.status == "filled":
                row = price_idx.get((po.code, po.exec_date))
                if row is not None:
                    pre_close = row.get("close", 0)
                    # 找retry_date的close
                    # retry_date = exec_date + 1 trading day，用open近似
                    open_price = row.get("open", 0)
                    if pre_close > 0 and open_price > 0:
                        retry_returns.append(open_price / pre_close - 1)

        stats.avg_retry_return_1d = (
            float(np.mean(retry_returns)) if retry_returns else 0.0
        )

        return stats
