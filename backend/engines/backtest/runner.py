"""回测入口函数。"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import TYPE_CHECKING, Any

import pandas as pd
import structlog

from engines.backtest.config import BacktestConfig
from engines.backtest.engine import SimpleBacktester
from engines.backtest.types import BacktestResult, CorporateAction

if TYPE_CHECKING:
    from engines.datafeed import DataFeed

logger = structlog.get_logger(__name__)


def _build_factor_date_index(
    factor_df: pd.DataFrame,
) -> tuple[list[date], dict[date, pd.DataFrame]]:
    """预索引factor_df: groupby一次, O(1)按日期查找。

    Phase 1.1 优化: 替代 factor_df[factor_df["trade_date"] <= rd] 的O(N)全表扫描。
    原代码每次调仓日扫描56.8M行(OBJECT dtype比较), 144次调仓=8.2B次Python比较。
    改为一次groupby + bisect查找, O(N+M*logM)。

    Returns:
        (sorted_dates, date_to_df) — 排序日期列表 + 日期→因子DataFrame字典
    """
    factor_by_date: dict[date, pd.DataFrame] = {}
    for td, grp in factor_df.groupby("trade_date"):
        factor_by_date[td] = grp
    sorted_dates = sorted(factor_by_date.keys())
    return sorted_dates, factor_by_date


def _find_latest_factor_date(
    sorted_dates: list[date],
    target_date: date,
) -> date | None:
    """用bisect找到 <= target_date 的最近因子日期。O(logN)。"""
    idx = bisect_right(sorted_dates, target_date)
    if idx == 0:
        return None
    return sorted_dates[idx - 1]


def run_hybrid_backtest(
    factor_df: pd.DataFrame,
    directions: dict[str, int],
    price_data: pd.DataFrame,
    config: BacktestConfig,
    benchmark_data: pd.DataFrame | None = None,
    signal_config: Any | None = None,  # SignalConfig (unused, kept for API compat)
    datafeed: DataFeed | None = None,
    dividend_calendar: dict[date, list[CorporateAction]] | None = None,
    conn=None,  # DB连接(size-neutral需要加载ln_mcap)
) -> BacktestResult:
    """Hybrid回测: Phase A向量化信号 → Phase B事件驱动执行。

    DEV_BACKTEST_ENGINE §3.1 Hybrid架构统一入口。

    Args:
        factor_df: 因子长表 (code, trade_date, factor_name, raw_value)
        directions: {factor_name: direction} (+1正向, -1反向)
        price_data: 全量价格数据（当datafeed非None时忽略此参数）
        config: 回测配置（Phase B使用）
        benchmark_data: 基准指数数据
        signal_config: Phase A信号配置（默认从config推断）
        datafeed: DataFeed数据源（优先于price_data）

    Returns:
        BacktestResult
    """
    from engines.signal_engine import PortfolioBuilder, SignalComposer
    from engines.signal_engine import SignalConfig as SEConfig
    from engines.vectorized_signal import compute_rebalance_dates

    # DataFeed兼容: 如果传入DataFeed对象，提取底层DataFrame
    if datafeed is not None:
        from engines.datafeed import DataFeed

        if isinstance(datafeed, DataFeed):
            price_data = datafeed.df

    # Phase A: 统一信号生成 (SignalComposer + PortfolioBuilder)
    # 从signal_config提取size_neutral_beta(如果传入了SignalConfig)
    _sn_beta_from_cfg = 0.0
    if signal_config is not None and hasattr(signal_config, "size_neutral_beta"):
        _sn_beta_from_cfg = signal_config.size_neutral_beta

    se_config = SEConfig(
        factor_names=list(directions.keys()),
        top_n=config.top_n,
        weight_method="equal",
        rebalance_freq=config.rebalance_freq,
        industry_cap=1.0,  # 回测默认无行业约束(可通过config覆盖)
        turnover_cap=1.0,  # 回测默认无换手约束
        cash_buffer=0.0,  # 回测默认无现金缓冲
        size_neutral_beta=_sn_beta_from_cfg,
    )
    # 覆盖FACTOR_DIRECTION: 用调用方传入的directions
    from engines.signal_engine import FACTOR_DIRECTION

    saved_directions = dict(FACTOR_DIRECTION)
    FACTOR_DIRECTION.update(directions)

    composer = SignalComposer(se_config)
    builder = PortfolioBuilder(se_config)

    trading_days = sorted(price_data["trade_date"].unique())
    rebal_dates = compute_rebalance_dates(trading_days, config.rebalance_freq)

    # Size-neutral: 一次性加载 ln_mcap pivot (beta=0.0 时跳过)
    _sn_beta = se_config.size_neutral_beta
    _ln_mcap_pivot = None
    if _sn_beta > 0:
        from engines.size_neutral import load_ln_mcap_pivot

        _ln_mcap_pivot = load_ln_mcap_pivot(min(trading_days), max(trading_days), conn)

    # 确保factor_df有neutral_value列(兼容raw_value输入)
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    # 构建per-date排除集(ST/停牌/新股/BJ) — 替代旧的set-level ST过滤
    _has_status = "is_st" in price_data.columns
    _status_by_date: dict[date, set[str]] = {}
    if _has_status:
        for col in ("is_st", "is_suspended", "is_new_stock"):
            if col in price_data.columns:
                excluded = price_data.loc[price_data[col] == True, ["code", "trade_date"]]  # noqa: E712
                for td, grp in excluded.groupby("trade_date"):
                    if td not in _status_by_date:
                        _status_by_date[td] = set()
                    _status_by_date[td].update(grp["code"].tolist())
        # BJ股(board='bse')
        if "board" in price_data.columns:
            bj = price_data.loc[price_data["board"] == "bse", ["code", "trade_date"]]
            for td, grp in bj.groupby("trade_date"):
                if td not in _status_by_date:
                    _status_by_date[td] = set()
                _status_by_date[td].update(grp["code"].tolist())

    # Phase 1.1 优化: 预索引factor_df, O(1)按日期查找
    # 原代码: factor_df[factor_df["trade_date"] <= rd] 每次扫描全表(56.8M行×OBJECT比较)
    # 优化后: groupby一次 + bisect查找, 消除8.2B次Python比较(12yr 144调仓日)
    factor_sorted_dates, factor_by_date = _build_factor_date_index(factor_df)

    target_portfolios: dict[date, dict[str, float]] = {}
    for rd in rebal_dates:
        latest_date = _find_latest_factor_date(factor_sorted_dates, rd)
        if latest_date is None:
            continue
        day_data = factor_by_date[latest_date]

        # per-date排除
        exclude = _status_by_date.get(latest_date, set())
        scores = composer.compose(day_data, exclude=exclude)
        if scores.empty:
            continue

        # Size-neutral adjustment (beta=0.0 时 apply_size_neutral 直接返回原值)
        if _sn_beta > 0 and _ln_mcap_pivot is not None and latest_date in _ln_mcap_pivot.index:
            from engines.size_neutral import apply_size_neutral

            scores = apply_size_neutral(scores, _ln_mcap_pivot.loc[latest_date], _sn_beta)

        weights = builder.build(scores, pd.Series(dtype=str))
        if weights:
            target_portfolios[rd] = weights

    # 恢复FACTOR_DIRECTION
    FACTOR_DIRECTION.clear()
    FACTOR_DIRECTION.update(saved_directions)

    if not target_portfolios:
        raise ValueError("Phase A信号生成失败: target_portfolios为空")

    logger.info(
        "Phase A信号生成完成(SignalComposer): %d个调仓日, %d个因子, Top-%d, SN_beta=%.2f",
        len(target_portfolios),
        len(directions),
        config.top_n,
        _sn_beta,
    )

    # Phase B: 事件驱动执行
    tester = SimpleBacktester(config)
    return tester.run(target_portfolios, price_data, benchmark_data, dividend_calendar)


# ============================================================
# Composite 回测入口 (Phase 4)
# ============================================================


def run_composite_backtest(
    factor_df: pd.DataFrame,
    directions: dict[str, int],
    price_data: pd.DataFrame,
    config: BacktestConfig,
    modifiers: list | None = None,
    benchmark_data: pd.DataFrame | None = None,
    signal_config: Any | None = None,  # SignalConfig (unused, kept for API compat)
    datafeed: DataFeed | None = None,
    dividend_calendar: dict[date, list[CorporateAction]] | None = None,
    conn=None,  # DB连接(Modifier需要查询北向等数据)
) -> BacktestResult:
    """CompositeStrategy回测: Phase A核心信号 + Modifier调节 → Phase B执行。

    与run_hybrid_backtest的区别: 在Phase A生成基础权重后，
    逐日应用Modifier链调节权重(RegimeModifier等)再交给Phase B执行。

    Args:
        factor_df: 因子长表 (code, trade_date, factor_name, raw_value)
        directions: {factor_name: direction}
        price_data: 全量价格数据
        config: 回测配置
        modifiers: ModifierBase实例列表(为None时等同run_hybrid_backtest)
        benchmark_data: 基准指数数据
        signal_config: Phase A信号配置
        datafeed: DataFeed数据源
        dividend_calendar: 分红日历

    Returns:
        BacktestResult
    """
    from engines.signal_engine import FACTOR_DIRECTION, PortfolioBuilder, SignalComposer
    from engines.signal_engine import SignalConfig as SEConfig
    from engines.vectorized_signal import compute_rebalance_dates

    if datafeed is not None:
        from engines.datafeed import DataFeed

        if isinstance(datafeed, DataFeed):
            price_data = datafeed.df

    # Phase A: 统一信号生成 (SignalComposer + PortfolioBuilder)
    _sn_beta_from_cfg_c = 0.0
    if signal_config is not None and hasattr(signal_config, "size_neutral_beta"):
        _sn_beta_from_cfg_c = signal_config.size_neutral_beta

    se_config = SEConfig(
        factor_names=list(directions.keys()),
        top_n=config.top_n,
        weight_method="equal",
        rebalance_freq=config.rebalance_freq,
        industry_cap=1.0,
        turnover_cap=1.0,
        cash_buffer=0.0,
        size_neutral_beta=_sn_beta_from_cfg_c,
    )
    saved_directions = dict(FACTOR_DIRECTION)
    FACTOR_DIRECTION.update(directions)

    composer = SignalComposer(se_config)
    builder = PortfolioBuilder(se_config)

    trading_days = sorted(price_data["trade_date"].unique())
    rebal_dates = compute_rebalance_dates(trading_days, config.rebalance_freq)

    # Size-neutral: 一次性加载 ln_mcap pivot (beta=0.0 时跳过)
    _sn_beta_c = se_config.size_neutral_beta
    _ln_mcap_pivot_c = None
    if _sn_beta_c > 0:
        from engines.size_neutral import load_ln_mcap_pivot

        _ln_mcap_pivot_c = load_ln_mcap_pivot(min(trading_days), max(trading_days), conn)

    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    # 构建per-date排除集(同run_hybrid_backtest逻辑)
    _has_status_c = "is_st" in price_data.columns
    _status_by_date_c: dict[date, set[str]] = {}
    if _has_status_c:
        for col in ("is_st", "is_suspended", "is_new_stock"):
            if col in price_data.columns:
                excluded = price_data.loc[price_data[col] == True, ["code", "trade_date"]]  # noqa: E712
                for td, grp in excluded.groupby("trade_date"):
                    if td not in _status_by_date_c:
                        _status_by_date_c[td] = set()
                    _status_by_date_c[td].update(grp["code"].tolist())
        if "board" in price_data.columns:
            bj = price_data.loc[price_data["board"] == "bse", ["code", "trade_date"]]
            for td, grp in bj.groupby("trade_date"):
                if td not in _status_by_date_c:
                    _status_by_date_c[td] = set()
                _status_by_date_c[td].update(grp["code"].tolist())

    # Phase 1.1 优化: 预索引factor_df (同run_hybrid_backtest)
    factor_sorted_dates_c, factor_by_date_c = _build_factor_date_index(factor_df)

    target_portfolios: dict[date, dict[str, float]] = {}
    for rd in rebal_dates:
        latest_date = _find_latest_factor_date(factor_sorted_dates_c, rd)
        if latest_date is None:
            continue
        day_data = factor_by_date_c[latest_date]
        exclude = _status_by_date_c.get(latest_date, set())
        scores = composer.compose(day_data, exclude=exclude)
        if scores.empty:
            continue

        # Size-neutral adjustment
        if (
            _sn_beta_c > 0
            and _ln_mcap_pivot_c is not None
            and latest_date in _ln_mcap_pivot_c.index
        ):
            from engines.size_neutral import apply_size_neutral

            scores = apply_size_neutral(scores, _ln_mcap_pivot_c.loc[latest_date], _sn_beta_c)

        weights = builder.build(scores, pd.Series(dtype=str))
        if weights:
            target_portfolios[rd] = weights

    FACTOR_DIRECTION.clear()
    FACTOR_DIRECTION.update(saved_directions)

    if not target_portfolios:
        raise ValueError("Phase A信号生成失败: target_portfolios为空")

    # Phase A.5: Modifier调节
    if modifiers:
        from engines.base_strategy import StrategyContext

        adjusted_portfolios: dict[date, dict[str, float]] = {}
        for signal_date, base_weights in target_portfolios.items():
            ctx = StrategyContext(
                strategy_id="backtest",
                trade_date=signal_date,
                factor_df=factor_df[factor_df["trade_date"] == signal_date]
                if "trade_date" in factor_df.columns
                else factor_df,
                universe=set(base_weights.keys()),
                industry_map={},
                prev_holdings=None,
                conn=conn,
            )

            adjusted = dict(base_weights)
            for modifier in modifiers:
                if modifier.should_trigger(ctx):
                    result = modifier.compute_adjustments(adjusted, ctx)
                    if result.triggered:
                        # 应用调节因子(不归一化 — 缩放意味着减仓到现金)
                        for code, factor in result.adjustment_factors.items():
                            if code in adjusted:
                                adjusted[code] *= max(
                                    modifier.clip_low,
                                    min(factor, modifier.clip_high),
                                )
                        logger.info(
                            "[Composite] %s: %s triggered (%s), weight_sum=%.2f",
                            signal_date,
                            modifier.name,
                            result.reasoning,
                            sum(adjusted.values()),
                        )

            adjusted_portfolios[signal_date] = adjusted
        target_portfolios = adjusted_portfolios

    # Phase B: 事件驱动执行
    tester = SimpleBacktester(config)
    return tester.run(target_portfolios, price_data, benchmark_data, dividend_calendar)
