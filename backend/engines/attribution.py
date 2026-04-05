"""Brinson-Fachler归因分析 + 市场状态检测。

Sprint 1.2b: 将策略收益分解为行业配置效应、个股选择效应、交互效应。
市场状态检测器用于事后标注牛市/熊市/震荡，供回测结果分段分析使用。

参考:
- CLAUDE.md 回测报告必含指标 → 市场状态分段
- DEV_BACKTEST_ENGINE.md → 回测结果分析Tab "月度归因"
"""

import structlog
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

logger = structlog.get_logger(__name__)


# ============================================================
# Brinson归因数据类型
# ============================================================


@dataclass
class BrinsonResult:
    """单期Brinson归因结果。

    Attributes:
        total_excess: 总超额收益（策略收益 - 基准收益）。
        allocation_effect: 行业配置效应（行业权重偏离基准带来的收益）。
        selection_effect: 个股选择效应（行业内个股选择带来的超额收益）。
        interaction_effect: 交互效应（配置x选择的交叉项）。
        industry_detail: 每个行业的分解明细DataFrame。
            columns: [industry, w_p, w_b, r_p, r_b,
                       allocation, selection, interaction, total]
        period: 归因期间 (start_date, end_date)。
    """

    total_excess: float
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    industry_detail: pd.DataFrame
    period: tuple[date, date]


# ============================================================
# Brinson-Fachler归因引擎
# ============================================================


class BrinsonAttribution:
    """Brinson-Fachler归因分析。

    将策略相对基准的超额收益分解为:
    1. 配置效应 (Allocation): sum_j[(w_pj - w_bj) * (R_bj - R_b)]
    2. 选择效应 (Selection):  sum_j[w_bj * (R_pj - R_bj)]
    3. 交互效应 (Interaction): sum_j[(w_pj - w_bj) * (R_pj - R_bj)]
    4. 总超额 = 配置 + 选择 + 交互

    其中:
    - w_pj: 组合在行业j的权重
    - w_bj: 基准在行业j的权重
    - R_pj: 组合在行业j的收益率
    - R_bj: 基准在行业j的收益率
    - R_b:  基准总收益率
    """

    def single_period(
        self,
        portfolio_weights: dict[str, float],
        benchmark_weights: dict[str, float],
        portfolio_returns: dict[str, float],
        benchmark_returns: dict[str, float],
        industry_map: dict[str, str],
        period: tuple[date, date],
    ) -> BrinsonResult:
        """单期Brinson-Fachler归因。

        Args:
            portfolio_weights: 组合权重 {code: weight}，权重之和应为1。
            benchmark_weights: 基准权重 {code: weight}，权重之和应为1。
            portfolio_returns: 组合个股期间收益率 {code: return}。
            benchmark_returns: 基准个股期间收益率 {code: return}。
            industry_map: 行业映射 {code: industry_sw1}。
            period: 归因期间 (start_date, end_date)。

        Returns:
            BrinsonResult: 归因分解结果。
        """
        # 收集所有涉及的行业
        all_codes = set(portfolio_weights.keys()) | set(benchmark_weights.keys())
        industries = set()
        for code in all_codes:
            ind = industry_map.get(code)
            if ind:
                industries.add(ind)
            else:
                logger.warning("股票 %s 无行业分类，归入'未知'", code)
                industries.add("未知")

        # 按行业汇总权重和收益
        rows = []
        for ind in sorted(industries):
            # 该行业的组合股票
            p_codes = [c for c in portfolio_weights if industry_map.get(c, "未知") == ind]
            # 该行业的基准股票
            b_codes = [c for c in benchmark_weights if industry_map.get(c, "未知") == ind]

            # 组合行业权重 & 加权收益率
            w_p = sum(portfolio_weights[c] for c in p_codes)
            if w_p > 0:
                r_p = (
                    sum(portfolio_weights[c] * portfolio_returns.get(c, 0.0) for c in p_codes) / w_p
                )
            else:
                r_p = 0.0

            # 基准行业权重 & 加权收益率
            w_b = sum(benchmark_weights[c] for c in b_codes)
            if w_b > 0:
                r_b = (
                    sum(benchmark_weights[c] * benchmark_returns.get(c, 0.0) for c in b_codes) / w_b
                )
            else:
                r_b = 0.0

            rows.append(
                {
                    "industry": ind,
                    "w_p": w_p,
                    "w_b": w_b,
                    "r_p": r_p,
                    "r_b": r_b,
                }
            )

        df = pd.DataFrame(rows)
        if df.empty:
            return BrinsonResult(
                total_excess=0.0,
                allocation_effect=0.0,
                selection_effect=0.0,
                interaction_effect=0.0,
                industry_detail=pd.DataFrame(),
                period=period,
            )

        # 基准总收益率 R_b = sum(w_bj * R_bj)
        r_benchmark_total = (df["w_b"] * df["r_b"]).sum()

        # Brinson-Fachler分解（行业级）
        # 配置效应: (w_pj - w_bj) * (R_bj - R_b)
        df["allocation"] = (df["w_p"] - df["w_b"]) * (df["r_b"] - r_benchmark_total)
        # 选择效应: w_bj * (R_pj - R_bj)
        df["selection"] = df["w_b"] * (df["r_p"] - df["r_b"])
        # 交互效应: (w_pj - w_bj) * (R_pj - R_bj)
        df["interaction"] = (df["w_p"] - df["w_b"]) * (df["r_p"] - df["r_b"])
        # 行业总超额
        df["total"] = df["allocation"] + df["selection"] + df["interaction"]

        allocation_effect = df["allocation"].sum()
        selection_effect = df["selection"].sum()
        interaction_effect = df["interaction"].sum()
        total_excess = allocation_effect + selection_effect + interaction_effect

        return BrinsonResult(
            total_excess=total_excess,
            allocation_effect=allocation_effect,
            selection_effect=selection_effect,
            interaction_effect=interaction_effect,
            industry_detail=df,
            period=period,
        )

    def multi_period(
        self,
        holdings_history: dict[date, dict[str, int]],
        daily_prices: pd.DataFrame,
        benchmark_weights_monthly: dict[date, dict[str, float]],
        benchmark_prices: pd.DataFrame,
        industry_map: dict[str, str],
        rebalance_dates: list[date] | None = None,
    ) -> list[BrinsonResult]:
        """多期Brinson归因（按调仓周期分段）。

        从持仓历史和价格数据推算每期权重和收益，逐期做归因。

        Args:
            holdings_history: 每日持仓 {date: {code: shares}}。
            daily_prices: 复权收盘价DataFrame, index=date, columns=code。
            benchmark_weights_monthly: 基准月度权重 {month_start: {code: weight}}。
            benchmark_prices: 基准个股复权价DataFrame, index=date, columns=code。
            industry_map: 行业映射 {code: industry_sw1}。
            rebalance_dates: 调仓日列表。若None则按月划分。

        Returns:
            list[BrinsonResult]: 每期归因结果。
        """
        if not holdings_history:
            return []

        sorted_dates = sorted(holdings_history.keys())

        # 如果没有指定调仓日，按月首个交易日划分
        if rebalance_dates is None:
            rebalance_dates = self._infer_monthly_boundaries(sorted_dates)

        if len(rebalance_dates) < 2:
            return []

        results: list[BrinsonResult] = []
        for i in range(len(rebalance_dates) - 1):
            period_start = rebalance_dates[i]
            period_end = rebalance_dates[i + 1]

            # 该期间起始持仓权重
            start_holdings = holdings_history.get(period_start, {})
            if not start_holdings:
                # 找该期间最近一个有持仓的日期
                candidates = [d for d in sorted_dates if d <= period_start]
                if candidates:
                    start_holdings = holdings_history[candidates[-1]]

            if not start_holdings:
                continue

            # 计算组合权重（按起始市值）
            portfolio_weights = self._calc_weights_from_holdings(
                start_holdings, daily_prices, period_start
            )
            if not portfolio_weights:
                continue

            # 计算组合个股收益率
            portfolio_returns = self._calc_period_returns(
                list(portfolio_weights.keys()), daily_prices, period_start, period_end
            )

            # 基准权重（取该月对应的基准权重）
            bm_weights = self._get_benchmark_weights_for_period(
                benchmark_weights_monthly, period_start
            )
            if not bm_weights:
                logger.warning(
                    "期间 %s~%s 无基准权重数据，跳过",
                    period_start,
                    period_end,
                )
                continue

            # 基准个股收益率
            bm_returns = self._calc_period_returns(
                list(bm_weights.keys()), benchmark_prices, period_start, period_end
            )

            result = self.single_period(
                portfolio_weights=portfolio_weights,
                benchmark_weights=bm_weights,
                portfolio_returns=portfolio_returns,
                benchmark_returns=bm_returns,
                industry_map=industry_map,
                period=(period_start, period_end),
            )
            results.append(result)

        return results

    def summary(self, results: list[BrinsonResult]) -> dict:
        """多期归因汇总。

        Args:
            results: multi_period返回的归因结果列表。

        Returns:
            dict: 汇总结果，包含:
                - cumulative_excess: 累计超额收益
                - cumulative_allocation: 累计配置效应
                - cumulative_selection: 累计选择效应
                - cumulative_interaction: 累计交互效应
                - industry_summary: 按行业汇总的贡献DataFrame
                - period_count: 归因期数
        """
        if not results:
            return {
                "cumulative_excess": 0.0,
                "cumulative_allocation": 0.0,
                "cumulative_selection": 0.0,
                "cumulative_interaction": 0.0,
                "industry_summary": pd.DataFrame(),
                "period_count": 0,
            }

        cum_alloc = sum(r.allocation_effect for r in results)
        cum_select = sum(r.selection_effect for r in results)
        cum_interact = sum(r.interaction_effect for r in results)
        cum_excess = cum_alloc + cum_select + cum_interact

        # 按行业汇总
        all_details = pd.concat(
            [r.industry_detail for r in results if not r.industry_detail.empty],
            ignore_index=True,
        )
        if not all_details.empty:
            industry_summary = (
                all_details.groupby("industry")[["allocation", "selection", "interaction", "total"]]
                .sum()
                .sort_values("total", ascending=False)
                .reset_index()
            )
        else:
            industry_summary = pd.DataFrame()

        return {
            "cumulative_excess": cum_excess,
            "cumulative_allocation": cum_alloc,
            "cumulative_selection": cum_select,
            "cumulative_interaction": cum_interact,
            "industry_summary": industry_summary,
            "period_count": len(results),
        }

    # --------------------------------------------------------
    # 内部辅助方法
    # --------------------------------------------------------

    @staticmethod
    def _calc_weights_from_holdings(
        holdings: dict[str, int],
        prices: pd.DataFrame,
        as_of_date: date,
    ) -> dict[str, float]:
        """从持仓股数和价格计算权重。

        Args:
            holdings: {code: shares}。
            prices: 复权收盘价DataFrame，index=date, columns=code。
            as_of_date: 估值日。

        Returns:
            {code: weight}，权重之和为1。
        """
        if as_of_date not in prices.index:
            # 找最近的前一个交易日
            valid = prices.index[prices.index <= as_of_date]
            if valid.empty:
                return {}
            as_of_date = valid[-1]

        market_values: dict[str, float] = {}
        for code, shares in holdings.items():
            if code in prices.columns and not pd.isna(prices.loc[as_of_date, code]):
                mv = shares * float(prices.loc[as_of_date, code])
                if mv > 0:
                    market_values[code] = mv

        total_mv = sum(market_values.values())
        if total_mv <= 0:
            return {}

        return {code: mv / total_mv for code, mv in market_values.items()}

    @staticmethod
    def _calc_period_returns(
        codes: list[str],
        prices: pd.DataFrame,
        start_date: date,
        end_date: date,
    ) -> dict[str, float]:
        """计算个股在期间内的收益率。

        Args:
            codes: 股票代码列表。
            prices: 复权收盘价DataFrame。
            start_date: 期间起始日。
            end_date: 期间结束日。

        Returns:
            {code: period_return}。
        """
        result: dict[str, float] = {}
        for code in codes:
            if code not in prices.columns:
                result[code] = 0.0
                continue

            series = prices[code].dropna()
            # 找start_date当日或之前最近价格
            valid_start = series.index[series.index <= start_date]
            # 找end_date当日或之前最近价格
            valid_end = series.index[series.index <= end_date]

            if valid_start.empty or valid_end.empty:
                result[code] = 0.0
                continue

            p_start = float(series.loc[valid_start[-1]])
            p_end = float(series.loc[valid_end[-1]])

            if p_start > 0:
                result[code] = (p_end - p_start) / p_start
            else:
                result[code] = 0.0

        return result

    @staticmethod
    def _infer_monthly_boundaries(dates: list[date]) -> list[date]:
        """从交易日列表推断月度边界。

        Args:
            dates: 有序交易日列表。

        Returns:
            月度边界日期列表（每月第一个交易日 + 最后一个交易日）。
        """
        if not dates:
            return []

        boundaries: list[date] = [dates[0]]
        current_month = (dates[0].year, dates[0].month)

        for d in dates[1:]:
            month_key = (d.year, d.month)
            if month_key != current_month:
                boundaries.append(d)
                current_month = month_key

        # 加上最后一天作为终止边界
        if boundaries[-1] != dates[-1]:
            boundaries.append(dates[-1])

        return boundaries

    @staticmethod
    def _get_benchmark_weights_for_period(
        benchmark_weights_monthly: dict[date, dict[str, float]],
        period_start: date,
    ) -> dict[str, float]:
        """获取期间对应的基准权重。

        取period_start当月或之前最近的基准权重。

        Args:
            benchmark_weights_monthly: {month_date: {code: weight}}。
            period_start: 期间起始日。

        Returns:
            {code: weight}。
        """
        if not benchmark_weights_monthly:
            return {}

        valid = [d for d in benchmark_weights_monthly if d <= period_start]
        if not valid:
            return {}

        closest = max(valid)
        return benchmark_weights_monthly[closest]


# ============================================================
# 市场状态检测器
# ============================================================


class MarketStateDetector:
    """市场状态检测（事后标注，非实时预测）。

    用于回测结果按市场环境分段分析:
    - 牛市: 60日累计收益>10% + 20日MA>60日MA
    - 熊市: 60日累计收益<-10% + 20日MA<60日MA
    - 震荡: 其余

    CLAUDE.md要求: 回测报告→市场状态分段→自动分牛市/熊市/震荡三段，分别看绩效。
    """

    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"

    def classify(
        self,
        benchmark_returns: pd.Series,
        window: int = 60,
        bull_threshold: float = 0.10,
        bear_threshold: float = -0.10,
        short_ma: int = 20,
        long_ma: int = 60,
    ) -> pd.Series:
        """分类每个交易日的市场状态。

        Args:
            benchmark_returns: 基准日收益率Series (index=date, values=daily_return)。
            window: 累计收益回看窗口（交易日）。
            bull_threshold: 牛市累计收益阈值。
            bear_threshold: 熊市累计收益阈值（负数）。
            short_ma: 短期MA窗口。
            long_ma: 长期MA窗口。

        Returns:
            pd.Series: index=date, values='bull'/'bear'/'sideways'。
        """
        if benchmark_returns.empty or len(benchmark_returns) < long_ma:
            return pd.Series(
                self.SIDEWAYS,
                index=benchmark_returns.index,
                dtype="object",
            )

        # 从日收益率构建净值
        nav = (1 + benchmark_returns).cumprod()

        # 滚动累计收益: nav / nav_shifted - 1
        cum_return = nav / nav.shift(window) - 1

        # 均线: 对净值做MA
        ma_short = nav.rolling(window=short_ma, min_periods=short_ma).mean()
        ma_long = nav.rolling(window=long_ma, min_periods=long_ma).mean()

        # 分类
        states = pd.Series(self.SIDEWAYS, index=benchmark_returns.index, dtype="object")

        bull_mask = (cum_return > bull_threshold) & (ma_short > ma_long)
        bear_mask = (cum_return < bear_threshold) & (ma_short < ma_long)

        states[bull_mask] = self.BULL
        states[bear_mask] = self.BEAR

        return states

    def segment_performance(
        self,
        daily_returns: pd.Series,
        benchmark_returns: pd.Series,
        states: pd.Series | None = None,
    ) -> dict[str, dict[str, float]]:
        """按市场状态分段统计策略绩效。

        Args:
            daily_returns: 策略日收益率。
            benchmark_returns: 基准日收益率。
            states: 市场状态Series。若None则自动classify。

        Returns:
            dict: {state: {ann_return, sharpe, mdd, trading_days, excess_return}}。
        """
        if states is None:
            states = self.classify(benchmark_returns)

        # 对齐index
        common_idx = daily_returns.index.intersection(benchmark_returns.index).intersection(
            states.index
        )
        daily_returns = daily_returns.loc[common_idx]
        benchmark_returns = benchmark_returns.loc[common_idx]
        states = states.loc[common_idx]

        result: dict[str, dict[str, float]] = {}
        for state in [self.BULL, self.BEAR, self.SIDEWAYS]:
            mask = states == state
            if mask.sum() == 0:
                result[state] = {
                    "ann_return": 0.0,
                    "sharpe": 0.0,
                    "mdd": 0.0,
                    "trading_days": 0,
                    "excess_return": 0.0,
                }
                continue

            strat_rets = daily_returns[mask]
            bm_rets = benchmark_returns[mask]
            n_days = len(strat_rets)

            # 年化收益
            cum_ret = (1 + strat_rets).prod() - 1
            ann_return = (1 + cum_ret) ** (244 / max(n_days, 1)) - 1

            # Sharpe
            if strat_rets.std() > 0:
                sharpe = float(strat_rets.mean() / strat_rets.std() * np.sqrt(244))
            else:
                sharpe = 0.0

            # MDD（该状态下连续交易日的最大回撤）
            nav = (1 + strat_rets).cumprod()
            running_max = nav.cummax()
            drawdown = (nav - running_max) / running_max
            mdd = float(drawdown.min())

            # 超额收益
            bm_cum = (1 + bm_rets).prod() - 1
            excess = cum_ret - bm_cum

            result[state] = {
                "ann_return": float(ann_return),
                "sharpe": sharpe,
                "mdd": mdd,
                "trading_days": n_days,
                "excess_return": float(excess),
            }

        return result
