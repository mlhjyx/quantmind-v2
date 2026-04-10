"""Walk-Forward 滚动验证引擎。

Sprint 1.2a — 过拟合检测核心组件。
严格时序分割，不允许随机分割。每折独立训练→OOS预测→拼接全部OOS。

设计要求（来自 DEV_BACKTEST_ENGINE.md §4.12）:
- 5折时序分割: train_window=3年(750天), gap=5天, test_window=1年(250天)
- 每折独立训练→OOS预测→拼接全部OOS预测
- 输出: OOS拼接后的 Sharpe/MDD/年化收益 + 每折详情
- 不允许随机分割（时序严格按时间正序）

signal_func 回调设计:
- 当前等权策略: signal_func 内部用 SignalComposer + PortfolioBuilder 生成信号
- 未来ML策略: signal_func 内部用 LightGBM 训练→预测

Step 6-D (2026-04-09): 与重构后 engines.backtest 包对齐
- Fix 5: import 路径从 backend.engines.backtest_engine 改为 engines.backtest
- Fix 2: 新增 per-date ST/BJ/suspended/new_stock 过滤 (`build_exclusion_map`), 跟
  run_hybrid_backtest 的过滤逻辑一致, 避免 signal_func 忘记过滤导致 BJ 股进入信号
- Fix 4: 提供 `make_equal_weight_signal_func` 工厂函数, 自动管理 factor_df/directions/exclude
- Fix 7: PMS 状态在 fold 之间重置 (每折新建 SimpleBacktester) — 这是正确行为
  (每折独立 OOS 评估), 不是 bug。跨 fold 的累计盈亏追踪见 WFResult.combined_oos_nav
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
import structlog

# Step 4-A 之后走新的 engines.backtest 包 re-export (原 backend.engines.backtest_engine 是 shim)
from engines.backtest import BacktestConfig, BacktestResult, SimpleBacktester
from engines.metrics import (
    TRADING_DAYS_PER_YEAR,
    calc_max_drawdown,
    calc_sharpe,
)

logger = structlog.get_logger(__name__)


# ============================================================
# Fix 2 — Universe 过滤 helper
# ============================================================

def build_exclusion_map(price_data: pd.DataFrame) -> dict[date, set[str]]:
    """从 price_data 构建 per-date 排除集合 (ST / suspended / new / BJ)。

    与 run_hybrid_backtest (runner.py) 里的 _status_by_date 逻辑一致,
    避免 walk_forward 的 signal_func 忘记过滤导致 BJ/ST 股进入信号。

    Args:
        price_data: 必须包含 code/trade_date 列, 以及可选的 is_st/is_suspended/
                    is_new_stock/board 列 (至少一个)

    Returns:
        {trade_date: set of codes to exclude on that date}
        如果 price_data 没有任何 status 列, 返回空 dict (不过滤)
    """
    status_by_date: dict[date, set[str]] = {}
    cols = set(price_data.columns)

    # ST / suspended / new_stock: 这些列是 bool
    for status_col in ("is_st", "is_suspended", "is_new_stock"):
        if status_col not in cols:
            continue
        excluded = price_data.loc[
            price_data[status_col] == True, ["code", "trade_date"]  # noqa: E712
        ]
        for td, grp in excluded.groupby("trade_date"):
            status_by_date.setdefault(td, set()).update(grp["code"].tolist())

    # BJ (board='bse')
    if "board" in cols:
        bj = price_data.loc[price_data["board"] == "bse", ["code", "trade_date"]]
        for td, grp in bj.groupby("trade_date"):
            status_by_date.setdefault(td, set()).update(grp["code"].tolist())

    logger.debug(
        "build_exclusion_map: %d 天有排除项, 总计排除 %d 条 (code,date)",
        len(status_by_date),
        sum(len(s) for s in status_by_date.values()),
    )
    return status_by_date


# ============================================================
# Fix 4 — 等权 signal_func 工厂
# ============================================================

def make_equal_weight_signal_func(
    factor_df: pd.DataFrame,
    directions: dict[str, int],
    price_data: pd.DataFrame,
    top_n: int = 20,
    rebalance_freq: str = "monthly",
    size_neutral_beta: float = 0.0,
    ln_mcap_pivot: pd.DataFrame | None = None,
) -> "SignalFunc":
    """构造一个标准的等权 Walk-Forward signal_func。

    自动处理:
      - 加载因子 (factor_df)
      - 方向注入 (directions) — 通过 SignalComposer.compose 的 direction_map 参数
      - per-date universe 过滤 (price_data 的 is_st/is_suspended/is_new_stock/board)
      - Top-N 等权组合
      - 调仓日计算 (monthly/weekly/biweekly)

    train_dates 参数被 **忽略** — 等权策略没有 train-dependent 参数, 纯稳定性测试。
    如果需要 train-dependent 信号 (选因子 / 调参), 需要自己写 signal_func。

    Args:
        factor_df: 因子长表 (code, trade_date, factor_name, neutral_value 或 raw_value)
                   注意: 如果列名是 raw_value 但内容是已中性化的值
                   (cache/backtest/*.parquet 的历史坑), 会自动 rename
        directions: {factor_name: +1|-1}
        price_data: 用于构建 per-date 排除集
        top_n: Top-N 选股 (默认 20)
        rebalance_freq: 调仓频率 ("monthly"/"biweekly"/"weekly")

    Returns:
        符合 SignalFunc 签名的回调
    """
    from engines.signal_engine import (
        FACTOR_DIRECTION,
        PortfolioBuilder,
        SignalComposer,
    )
    from engines.signal_engine import SignalConfig as SEConfig
    from engines.vectorized_signal import compute_rebalance_dates

    # factor_df 列名兼容 (cache/backtest/*.parquet 里列名是 raw_value 但内容已中性化)
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    # 构建 universe 排除集 (一次性, 所有 fold 共用)
    exclusion_map = build_exclusion_map(price_data)

    # 构建 SignalComposer/PortfolioBuilder (配置固定, 所有 fold 共用)
    se_config = SEConfig(
        factor_names=list(directions.keys()),
        top_n=top_n,
        weight_method="equal",
        rebalance_freq=rebalance_freq,
        industry_cap=1.0,
        turnover_cap=1.0,
        cash_buffer=0.0,
    )
    composer = SignalComposer(se_config)
    builder = PortfolioBuilder(se_config)

    # 预计算全部 rebal dates (后面按 fold 过滤)
    all_trading_days = sorted(price_data["trade_date"].unique())
    all_rebal_dates = compute_rebalance_dates(all_trading_days, rebalance_freq)

    def signal_func(
        train_dates: list[date], test_dates: list[date]
    ) -> dict[date, dict[str, float]]:
        # train_dates 被忽略 — 等权策略无 train-dependent 参数
        test_set = set(test_dates)
        fold_rebal = [rd for rd in all_rebal_dates if rd in test_set]

        if not fold_rebal:
            logger.warning(
                "make_equal_weight_signal_func: test 期 [%s..%s] 没有 rebal 日",
                test_dates[0], test_dates[-1],
            )
            return {}

        # 注入 directions (全局状态, 用完恢复)
        saved = dict(FACTOR_DIRECTION)
        FACTOR_DIRECTION.update(directions)

        target_portfolios: dict[date, dict[str, float]] = {}
        try:
            for rd in fold_rebal:
                day_data = factor_df[factor_df["trade_date"] <= rd]
                if day_data.empty:
                    continue
                latest_date = day_data["trade_date"].max()
                day_data = day_data[day_data["trade_date"] == latest_date]

                exclude = exclusion_map.get(latest_date, set())
                scores = composer.compose(day_data, exclude=exclude)
                if scores.empty:
                    continue

                # Size-neutral adjustment
                if size_neutral_beta > 0 and ln_mcap_pivot is not None and latest_date in ln_mcap_pivot.index:
                    from engines.size_neutral import apply_size_neutral
                    scores = apply_size_neutral(scores, ln_mcap_pivot.loc[latest_date], size_neutral_beta)

                weights = builder.build(scores, pd.Series(dtype=str))
                if weights:
                    target_portfolios[rd] = weights
        finally:
            # 恢复全局
            FACTOR_DIRECTION.clear()
            FACTOR_DIRECTION.update(saved)

        logger.info(
            "signal_func fold: test [%s..%s] 生成 %d 个调仓日信号",
            test_dates[0], test_dates[-1], len(target_portfolios),
        )
        return target_portfolios

    return signal_func


# ============================================================
# 配置与结果数据类型
# ============================================================

@dataclass
class WFConfig:
    """Walk-Forward 配置。

    默认5折: train=3年(750天), gap=5天, test=1年(250天)。
    总需 5×250 + 750 = 2000天数据 (约8年)。
    """
    n_splits: int = 5
    train_window: int = 750   # ~3年交易日
    gap: int = 5              # 防信息泄露 (purged gap)
    test_window: int = 250    # ~1年交易日


@dataclass
class WFFoldResult:
    """单折Walk-Forward结果。"""
    fold_idx: int
    train_period: tuple[date, date]   # (start, end) inclusive
    test_period: tuple[date, date]    # (start, end) inclusive
    oos_sharpe: float
    oos_mdd: float
    oos_annual_return: float
    oos_nav: pd.Series                # date → NAV (OOS期间)
    oos_returns: pd.Series            # date → daily return (OOS期间)
    oos_trades: list                  # Fill列表
    train_days: int                   # 实际训练天数
    test_days: int                    # 实际测试天数


@dataclass
class WFResult:
    """Walk-Forward 汇总结果。"""
    config: WFConfig
    backtest_config: BacktestConfig
    fold_results: list[WFFoldResult]
    combined_oos_nav: pd.Series       # 全部OOS拼接后的NAV
    combined_oos_returns: pd.Series   # 全部OOS拼接后的daily return
    combined_oos_sharpe: float
    combined_oos_mdd: float
    combined_oos_annual_return: float
    combined_oos_total_return: float
    total_oos_days: int

    def overfit_ratio(self, full_sample_sharpe: float) -> float:
        """过拟合比率 = WF-OOS Sharpe / 全样本Sharpe。

        < 0.5 表示严重过拟合（DEV_BACKTEST_ENGINE.md 验收标准）。
        """
        if abs(full_sample_sharpe) < 1e-12:
            return 0.0
        return self.combined_oos_sharpe / full_sample_sharpe


# 回调类型: 接受训练期日期列表，返回测试期的目标持仓
# signal_func(train_dates) -> dict[date, dict[str, float]]
#   即 {signal_date: {code: weight}}
SignalFunc = Callable[[list[date], list[date]], dict[date, dict[str, float]]]


# ============================================================
# Walk-Forward 引擎
# ============================================================

class WalkForwardEngine:
    """Walk-Forward 滚动验证引擎。

    时间轴示例 (n_splits=5, train=750, gap=5, test=250):
      Fold 0: |---train 750日---|gap|---test 250日---|
      Fold 1:          |---train 750日---|gap|---test 250日---|
      Fold 2:                   |---train 750日---|gap|---test 250日---|
      ...

    分割策略: 从数据末尾往前排test窗口，确保测试期不重叠且覆盖最近数据。
    """

    def __init__(
        self,
        wf_config: WFConfig,
        backtest_config: BacktestConfig | None = None,
    ):
        self.wf_config = wf_config
        self.bt_config = backtest_config or BacktestConfig()

    def generate_splits(
        self, all_dates: list[date]
    ) -> list[tuple[list[date], list[date]]]:
        """生成 train/test 日期分割。

        分割逻辑（从末尾往前排列，确保最近数据被测试）:
        1. 最后 n_splits × test_window 天用于OOS测试
        2. 每折的训练期 = 该折测试期前面的 train_window 天
        3. train和test之间留 gap 天防止信息泄露

        Args:
            all_dates: 全量交易日期列表（已排序）

        Returns:
            list of (train_dates, test_dates) 元组

        Raises:
            ValueError: 数据量不足以完成分割
        """
        all_dates = sorted(all_dates)
        n = len(all_dates)
        cfg = self.wf_config

        # 最少需要的数据量: train_window + gap + n_splits * test_window
        min_required = cfg.train_window + cfg.gap + cfg.n_splits * cfg.test_window
        if n < min_required:
            raise ValueError(
                f"数据量不足: 需要至少 {min_required} 个交易日, "
                f"实际只有 {n} 个。"
                f"(train={cfg.train_window}, gap={cfg.gap}, "
                f"test={cfg.test_window}, n_splits={cfg.n_splits})"
            )

        splits: list[tuple[list[date], list[date]]] = []

        # 从末尾往前排 test 窗口
        # Fold n_splits-1 的 test_end = all_dates[-1]
        # Fold n_splits-1 的 test_start = all_dates[-(test_window)]
        # Fold n_splits-2 的 test_end = Fold n_splits-1 的 test_start - 1
        # ...
        for fold_idx in range(cfg.n_splits):
            # 从后往前: fold 0 是最早的测试期, fold n_splits-1 是最近的
            reverse_idx = cfg.n_splits - 1 - fold_idx

            test_end_idx = n - 1 - reverse_idx * cfg.test_window
            test_start_idx = test_end_idx - cfg.test_window + 1

            # 训练期: test_start 前面留 gap, 再往前取 train_window
            train_end_idx = test_start_idx - cfg.gap - 1
            train_start_idx = train_end_idx - cfg.train_window + 1

            if train_start_idx < 0:
                raise ValueError(
                    f"Fold {fold_idx}: 训练期起始索引 {train_start_idx} < 0, "
                    f"数据量不足以完成 {cfg.n_splits} 折分割。"
                )

            train_dates = all_dates[train_start_idx : train_end_idx + 1]
            test_dates = all_dates[test_start_idx : test_end_idx + 1]

            splits.append((train_dates, test_dates))

        # 验证: 测试期不重叠
        for i in range(len(splits) - 1):
            _, test_i = splits[i]
            _, test_next = splits[i + 1]
            if test_i[-1] >= test_next[0]:
                raise ValueError(
                    f"Fold {i} 和 Fold {i+1} 的测试期重叠: "
                    f"{test_i[-1]} >= {test_next[0]}"
                )

        logger.info(
            f"Walk-Forward 分割完成: {len(splits)} 折, "
            f"总OOS天数 = {sum(len(t) for _, t in splits)}"
        )
        for i, (train, test) in enumerate(splits):
            logger.info(
                f"  Fold {i}: train[{train[0]}..{train[-1]}] "
                f"({len(train)}d) → test[{test[0]}..{test[-1]}] ({len(test)}d)"
            )

        return splits

    def run(
        self,
        signal_func: SignalFunc,
        price_data: pd.DataFrame,
        benchmark_data: pd.DataFrame | None = None,
        all_dates: list[date] | None = None,
    ) -> WFResult:
        """执行 Walk-Forward 回测。

        Args:
            signal_func: 回调函数，签名 (train_dates, test_dates) -> target_portfolios。
                train_dates: 训练期日期列表
                test_dates: 测试期日期列表
                返回: {signal_date: {code: weight}} 字典，仅覆盖test期

            price_data: 全量价格数据 DataFrame。
                必须包含列: code, trade_date, open, close, volume,
                           pre_close, up_limit, down_limit, turnover_rate

            benchmark_data: 基准数据 DataFrame (trade_date, close)。
                如果为None则不计算超额指标。

            all_dates: 全量交易日期列表。
                如果为None则从price_data中提取。

        Returns:
            WFResult: Walk-Forward 汇总结果
        """
        if all_dates is None:
            all_dates = sorted(price_data["trade_date"].unique())
        else:
            all_dates = sorted(all_dates)

        # 1. 生成分割
        splits = self.generate_splits(all_dates)

        # 2. 逐折执行
        fold_results: list[WFFoldResult] = []
        all_oos_navs: list[pd.Series] = []

        for fold_idx, (train_dates, test_dates) in enumerate(splits):
            logger.info(f"Walk-Forward Fold {fold_idx}/{len(splits)-1} 开始...")

            fold_result = self._run_single_fold(
                fold_idx=fold_idx,
                train_dates=train_dates,
                test_dates=test_dates,
                signal_func=signal_func,
                price_data=price_data,
                benchmark_data=benchmark_data,
            )
            fold_results.append(fold_result)
            all_oos_navs.append(fold_result.oos_nav)

            logger.info(
                f"  Fold {fold_idx} 完成: "
                f"OOS Sharpe={fold_result.oos_sharpe:.2f}, "
                f"MDD={fold_result.oos_mdd:.2%}, "
                f"Annual={fold_result.oos_annual_return:.2%}"
            )

        # 3. 拼接全部OOS的NAV
        combined_nav = self._combine_oos_navs(all_oos_navs)
        combined_returns = combined_nav.pct_change().fillna(0)

        # 4. 计算汇总指标
        combined_sharpe = calc_sharpe(combined_returns)
        combined_mdd = calc_max_drawdown(combined_nav)
        total_oos_days = len(combined_nav)
        years = total_oos_days / TRADING_DAYS_PER_YEAR
        total_return = float(combined_nav.iloc[-1] / combined_nav.iloc[0] - 1)
        annual_return = float(
            (1 + total_return) ** (1 / max(years, 0.01)) - 1
        )

        result = WFResult(
            config=self.wf_config,
            backtest_config=self.bt_config,
            fold_results=fold_results,
            combined_oos_nav=combined_nav,
            combined_oos_returns=combined_returns,
            combined_oos_sharpe=round(combined_sharpe, 4),
            combined_oos_mdd=round(combined_mdd, 6),
            combined_oos_annual_return=round(annual_return, 6),
            combined_oos_total_return=round(total_return, 6),
            total_oos_days=total_oos_days,
        )

        logger.info(
            f"Walk-Forward 完成: OOS拼接 Sharpe={result.combined_oos_sharpe:.2f}, "
            f"MDD={result.combined_oos_mdd:.2%}, "
            f"Annual={result.combined_oos_annual_return:.2%}, "
            f"OOS天数={result.total_oos_days}"
        )

        return result

    def _run_single_fold(
        self,
        fold_idx: int,
        train_dates: list[date],
        test_dates: list[date],
        signal_func: SignalFunc,
        price_data: pd.DataFrame,
        benchmark_data: pd.DataFrame | None,
    ) -> WFFoldResult:
        """执行单折 Walk-Forward。

        流程:
        1. 调用 signal_func(train_dates, test_dates) 获取测试期的目标持仓
        2. 用 SimpleBacktester 在测试期跑回测
        3. 计算OOS绩效指标
        """
        # 1. 调用信号函数: 用训练期数据训练，生成测试期信号
        target_portfolios = signal_func(train_dates, test_dates)

        if not target_portfolios:
            logger.warning(f"Fold {fold_idx}: signal_func 返回空信号")
            # 返回空结果（全现金）
            empty_nav = pd.Series(
                self.bt_config.initial_capital,
                index=pd.Index(test_dates, name="trade_date"),
            )
            return WFFoldResult(
                fold_idx=fold_idx,
                train_period=(train_dates[0], train_dates[-1]),
                test_period=(test_dates[0], test_dates[-1]),
                oos_sharpe=0.0,
                oos_mdd=0.0,
                oos_annual_return=0.0,
                oos_nav=empty_nav,
                oos_returns=pd.Series(0.0, index=empty_nav.index),
                oos_trades=[],
                train_days=len(train_dates),
                test_days=len(test_dates),
            )

        # 2. 筛选测试期的价格数据（需包含test期前一天用于建仓执行）
        # 信号日可能在test_dates之前（信号在T日，T+1执行），
        # 所以价格数据需要覆盖最早信号日到test最后一天
        earliest_signal = min(target_portfolios.keys())
        test_price_dates = sorted(
            set(test_dates)
            | {d for d in price_data["trade_date"].unique()
               if earliest_signal <= d <= test_dates[-1]}
        )

        test_price = price_data[
            price_data["trade_date"].isin(test_price_dates)
        ].copy()

        test_bench = None
        if benchmark_data is not None and not benchmark_data.empty:
            test_bench = benchmark_data[
                benchmark_data["trade_date"].isin(test_price_dates)
            ].copy()

        # 3. 用 SimpleBacktester 跑测试期回测
        backtester = SimpleBacktester(self.bt_config)
        bt_result: BacktestResult = backtester.run(
            target_portfolios=target_portfolios,
            price_data=test_price,
            benchmark_data=test_bench,
        )

        # 4. 只保留测试期内的NAV
        oos_nav = bt_result.daily_nav
        oos_returns = bt_result.daily_returns

        # 5. 计算OOS指标
        if len(oos_returns) > 1:
            oos_sharpe = calc_sharpe(oos_returns)
            oos_mdd = calc_max_drawdown(oos_nav)
            years = len(oos_returns) / TRADING_DAYS_PER_YEAR
            total_ret = float(oos_nav.iloc[-1] / oos_nav.iloc[0] - 1)
            oos_annual_return = float(
                (1 + total_ret) ** (1 / max(years, 0.01)) - 1
            )
        else:
            oos_sharpe = 0.0
            oos_mdd = 0.0
            oos_annual_return = 0.0

        return WFFoldResult(
            fold_idx=fold_idx,
            train_period=(train_dates[0], train_dates[-1]),
            test_period=(test_dates[0], test_dates[-1]),
            oos_sharpe=round(oos_sharpe, 4),
            oos_mdd=round(oos_mdd, 6),
            oos_annual_return=round(oos_annual_return, 6),
            oos_nav=oos_nav,
            oos_returns=oos_returns,
            oos_trades=bt_result.trades,
            train_days=len(train_dates),
            test_days=len(oos_nav),
        )

    @staticmethod
    def _combine_oos_navs(oos_navs: list[pd.Series]) -> pd.Series:
        """拼接多折OOS的NAV曲线。

        每折的NAV从 initial_capital 开始，拼接时需要做链式增长:
        - Fold 0 NAV 原样保留
        - Fold 1 NAV 按 Fold 0 末尾值缩放
        - Fold 2 NAV 按 Fold 1 缩放后的末尾值缩放
        - ...

        这样拼接后的NAV是连续的资金曲线。
        """
        if not oos_navs:
            return pd.Series(dtype=float)

        combined_parts: list[pd.Series] = []
        scale_factor = 1.0

        for i, nav in enumerate(oos_navs):
            if nav.empty:
                continue

            if i == 0:
                # 第一折原样保留
                combined_parts.append(nav)
                scale_factor = float(nav.iloc[-1])
            else:
                # 后续折: 按前一折末尾值缩放
                fold_start_val = float(nav.iloc[0])
                if abs(fold_start_val) < 1e-12:
                    continue
                ratio = scale_factor / fold_start_val
                scaled_nav = nav * ratio
                combined_parts.append(scaled_nav)
                scale_factor = float(scaled_nav.iloc[-1])

        if not combined_parts:
            return pd.Series(dtype=float)

        return pd.concat(combined_parts)


# ============================================================
# 辅助: 打印 Walk-Forward 报告
# ============================================================

def print_wf_report(wf_result: WFResult, full_sample_sharpe: float | None = None) -> None:
    """打印 Walk-Forward 报告到终端。

    Args:
        wf_result: Walk-Forward 结果
        full_sample_sharpe: 全样本回测的Sharpe（用于计算过拟合比率）
    """
    print("\n" + "=" * 70)
    print("QuantMind V2 — Walk-Forward 验证报告")
    print("=" * 70)

    cfg = wf_result.config
    print(f"\n配置: {cfg.n_splits}折, "
          f"train={cfg.train_window}d, gap={cfg.gap}d, test={cfg.test_window}d")

    print(f"\n{'--- 各折OOS绩效 ---':^70}")
    print(f"  {'Fold':>4}  {'训练期':^25}  {'测试期':^25}  "
          f"{'Sharpe':>7}  {'MDD':>7}  {'Annual':>7}")
    print(f"  {'----':>4}  {'-'*25:^25}  {'-'*25:^25}  "
          f"{'------':>7}  {'---':>7}  {'------':>7}")

    for fr in wf_result.fold_results:
        train_str = f"{fr.train_period[0]}~{fr.train_period[1]}"
        test_str = f"{fr.test_period[0]}~{fr.test_period[1]}"
        print(
            f"  {fr.fold_idx:>4}  {train_str:^25}  {test_str:^25}  "
            f"{fr.oos_sharpe:>7.2f}  {fr.oos_mdd:>6.2%}  "
            f"{fr.oos_annual_return:>6.2%}"
        )

    print(f"\n{'--- OOS拼接汇总 ---':^70}")
    print(f"  {'OOS总天数':>12}: {wf_result.total_oos_days}")
    print(f"  {'总收益':>12}: {wf_result.combined_oos_total_return:.2%}")
    print(f"  {'年化收益':>12}: {wf_result.combined_oos_annual_return:.2%}")
    print(f"  {'Sharpe':>12}: {wf_result.combined_oos_sharpe:.2f}")
    print(f"  {'最大回撤':>12}: {wf_result.combined_oos_mdd:.2%}")

    if full_sample_sharpe is not None:
        ratio = wf_result.overfit_ratio(full_sample_sharpe)
        print(f"\n{'--- 过拟合检测 ---':^70}")
        print(f"  全样本 Sharpe: {full_sample_sharpe:.2f}")
        print(f"  WF-OOS Sharpe: {wf_result.combined_oos_sharpe:.2f}")
        print(f"  过拟合比率:    {ratio:.2f} (WF-OOS / 全样本)")
        if ratio < 0.5:
            print("  ** 警告: 过拟合比率 < 0.5, 过拟合严重! 需简化模型 **")
        elif ratio < 0.7:
            print("  * 注意: 过拟合比率 < 0.7, 存在中等程度过拟合 *")
        else:
            print("  过拟合比率正常")

    print("\n" + "=" * 70)


# ============================================================
# 使用示例 (注释形式)
# ============================================================
#
# === 示例1: 等权策略的 Walk-Forward 验证 ===
#
# from engines.walk_forward import (
#     WalkForwardEngine, WFConfig, make_equal_weight_signal_func
# )
# from engines.backtest import BacktestConfig
#
# def equal_weight_signal_func(
#     train_dates: list[date],
#     test_dates: list[date],
# ) -> dict[date, dict[str, float]]:
#     """等权策略信号函数。
#
#     用训练期数据计算因子IC → 选因子 → 在测试期生成等权信号。
#     """
#     # 1. 在训练期计算因子 IC, 选出 top 因子
#     factor_ic = calc_factor_ic(train_dates)  # 你的因子IC计算
#     selected_factors = select_top_factors(factor_ic, top_k=10)
#
#     # 2. 用选出的因子, 在测试期每个调仓日生成信号
#     target_portfolios = {}
#     for signal_date in get_rebalance_dates(test_dates, freq="biweekly"):
#         scores = calc_composite_score(signal_date, selected_factors)
#         top_n = scores.nlargest(20)
#         weight = 1.0 / len(top_n)
#         target_portfolios[signal_date] = {
#             code: weight for code in top_n.index
#         }
#
#     return target_portfolios
#
#
# # 配置
# wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
# bt_config = BacktestConfig(initial_capital=1_000_000.0, top_n=20)
#
# # 执行
# engine = WalkForwardEngine(wf_config, bt_config)
# wf_result = engine.run(
#     signal_func=equal_weight_signal_func,
#     price_data=price_df,        # 全量价格数据
#     benchmark_data=bench_df,    # 沪深300数据
# )
#
# # 打印报告 (对比全样本Sharpe)
# print_wf_report(wf_result, full_sample_sharpe=1.21)
#
#
# === 示例2: 未来ML策略 (LightGBM) ===
#
# def lgbm_signal_func(
#     train_dates: list[date],
#     test_dates: list[date],
# ) -> dict[date, dict[str, float]]:
#     """LightGBM策略信号函数。"""
#     # 1. 训练
#     X_train, y_train = build_features(train_dates)
#     model = lgb.LGBMRegressor().fit(X_train, y_train)
#
#     # 2. 预测 + 生成信号
#     target_portfolios = {}
#     for signal_date in get_rebalance_dates(test_dates):
#         X_pred = build_features_for_date(signal_date)
#         preds = model.predict(X_pred)
#         top_n_idx = np.argsort(preds)[-20:]
#         weight = 1.0 / 20
#         target_portfolios[signal_date] = {
#             codes[i]: weight for i in top_n_idx
#         }
#     return target_portfolios
