#!/usr/bin/env python3
"""IC加权回测对比 — 5配置(基线 vs 3种IC加权 vs BP融合)。

背景: v1.1基线5因子等权Sharpe=1.054。之前测试的A/B/C/D是"改选股池"类方法。
本次测试"改因子权重"类方法 — 完全不同维度。

配置0(基线v1.1): 5因子等权 → Top15 → 月频 → IndCap=25%
配置1(最大化ICIR): w = Sigma^{-1} * mu, Ledoit-Wolf压缩
配置2(最大化IC): w = mu (IC均值), 正的保留负的设0
配置3(ICIR简单加权): w_i = ICIR_i = IC_mean / IC_std
配置4(BP融合): 等权但bp_ratio→bp_enhanced(stability+percentile)

IC计算: 每月末截面, Spearman rank IC, forward return = 20日超额收益(vs CSI300)
前12个月(2021-01~2021-12)无足够历史IC数据, 用等权fallback。

回测区间: 2021-01-01 ~ 2025-12-31, 100万初始资金
"""

import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.covariance import LedoitWolf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from run_backtest import (
    load_benchmark,
    load_factor_values,
    load_industry,
    load_price_data,
    load_universe,
)

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 基线5因子
BASELINE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]


# ============================================================
# IC计算模块
# ============================================================


def compute_monthly_ic_panel(
    conn,
    rebalance_dates: list[date],
    factor_names: list[str],
    fwd_days: int = 20,
) -> dict[date, dict[str, float]]:
    """计算每个调仓日的截面IC(Spearman rank correlation)。

    Args:
        conn: DB连接。
        rebalance_dates: 调仓日列表。
        factor_names: 因子名列表。
        fwd_days: 前瞻收益天数。

    Returns:
        {date: {factor_name: IC_value}}
    """
    # 预加载: 所有交易日的收盘价(用于计算forward return)
    logger.info("预加载收盘价(含adj)和CSI300...")
    price_df = pd.read_sql(
        """SELECT k.code, k.trade_date, k.close, k.pre_close,
                  k.volume
           FROM klines_daily k
           WHERE k.trade_date BETWEEN %s AND %s
           ORDER BY k.trade_date, k.code""",
        conn,
        params=(
            min(rebalance_dates) - timedelta(days=10),
            max(rebalance_dates) + timedelta(days=60),
        ),
    )
    # 复权价格: 使用close直接(factor_values中的neutral_value已经是中性化后的)
    # forward return需要用实际价格
    price_pivot = price_df.pivot_table(
        index="trade_date", columns="code", values="close", aggfunc="first"
    )

    # CSI300基准
    bench_df = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(
            min(rebalance_dates) - timedelta(days=10),
            max(rebalance_dates) + timedelta(days=60),
        ),
    )
    bench_close = bench_df.set_index("trade_date")["close"]

    # 所有交易日列表
    all_trade_dates = sorted(price_pivot.index.tolist())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}

    ic_panel = {}

    for rd in rebalance_dates:
        if rd not in date_to_idx:
            continue

        idx = date_to_idx[rd]
        # 找fwd_days后的交易日
        fwd_idx = idx + fwd_days
        if fwd_idx >= len(all_trade_dates):
            continue
        fwd_date = all_trade_dates[fwd_idx]

        # 计算forward return (超额 vs CSI300)
        if rd not in price_pivot.index or fwd_date not in price_pivot.index:
            continue
        close_t0 = price_pivot.loc[rd]
        close_t1 = price_pivot.loc[fwd_date]
        stock_ret = (close_t1 / close_t0 - 1).dropna()

        if rd not in bench_close.index or fwd_date not in bench_close.index:
            continue
        bench_ret = bench_close.loc[fwd_date] / bench_close.loc[rd] - 1
        excess_ret = stock_ret - bench_ret

        # 加载当日因子值
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue

        pivot = fv.pivot_table(
            index="code", columns="factor_name", values="neutral_value", aggfunc="first"
        )

        # 计算每个因子的截面Spearman IC
        date_ic = {}
        for fname in factor_names:
            if fname not in pivot.columns:
                continue

            # 方向调整: IC计算时按原方向(neutral_value已中性化)
            factor_vals = pivot[fname].dropna()
            direction = FACTOR_DIRECTION.get(fname, 1)

            # 取交集
            common = factor_vals.index.intersection(excess_ret.index)
            if len(common) < 50:  # 至少50只股票
                continue

            f_vals = factor_vals.loc[common].values * direction
            r_vals = excess_ret.loc[common].values

            # Spearman rank IC
            corr, _ = spearmanr(f_vals, r_vals)
            if not np.isnan(corr):
                date_ic[fname] = corr

        if date_ic:
            ic_panel[rd] = date_ic

    return ic_panel


def compute_ic_weights_maxicir(
    ic_panel: dict[date, dict[str, float]],
    current_date: date,
    factor_names: list[str],
    lookback_months: int = 12,
) -> dict[str, float]:
    """方法1: 最大化ICIR加权 (w = Sigma^{-1} * mu)。

    Args:
        ic_panel: {date: {factor_name: IC}}
        current_date: 当前调仓日。
        factor_names: 因子列表。
        lookback_months: 回看月数。

    Returns:
        {factor_name: weight}, 归一化到sum=1, 负权重设0。
    """
    # 取过去lookback_months个月的IC
    cutoff = current_date - timedelta(days=lookback_months * 31)
    past_dates = sorted([d for d in ic_panel if cutoff <= d < current_date])

    if len(past_dates) < 6:  # 至少6个月数据
        return None  # fallback到等权

    # 构建IC矩阵: rows=dates, cols=factors
    ic_matrix = []
    for d in past_dates:
        row = [ic_panel[d].get(f, np.nan) for f in factor_names]
        ic_matrix.append(row)
    ic_matrix = np.array(ic_matrix)

    # 去掉全NaN的列
    valid_mask = ~np.all(np.isnan(ic_matrix), axis=0)
    if not any(valid_mask):
        return None

    # 填充NaN为0(保守假设)
    ic_matrix = np.nan_to_num(ic_matrix, nan=0.0)

    # IC均值向量
    mu = np.mean(ic_matrix, axis=0)

    # Ledoit-Wolf压缩协方差
    try:
        lw = LedoitWolf()
        lw.fit(ic_matrix)
        sigma = lw.covariance_
    except Exception:
        # fallback: 样本协方差 + 对角正则化
        sigma = np.cov(ic_matrix, rowvar=False)
        sigma += np.eye(len(factor_names)) * 1e-6

    # w = Sigma^{-1} * mu
    try:
        sigma_inv = np.linalg.inv(sigma)
        w = sigma_inv @ mu
    except np.linalg.LinAlgError:
        # 奇异矩阵: 用伪逆
        sigma_inv = np.linalg.pinv(sigma)
        w = sigma_inv @ mu

    # 负权重设0, 归一化
    w = np.maximum(w, 0)
    if w.sum() <= 0:
        return None
    w = w / w.sum()

    return {f: float(w[i]) for i, f in enumerate(factor_names) if w[i] > 0.001}


def compute_ic_weights_maxic(
    ic_panel: dict[date, dict[str, float]],
    current_date: date,
    factor_names: list[str],
    lookback_months: int = 12,
) -> dict[str, float]:
    """方法2: 最大化IC加权 (w = mu, 更激进)。"""
    cutoff = current_date - timedelta(days=lookback_months * 31)
    past_dates = sorted([d for d in ic_panel if cutoff <= d < current_date])

    if len(past_dates) < 6:
        return None

    ic_matrix = []
    for d in past_dates:
        row = [ic_panel[d].get(f, np.nan) for f in factor_names]
        ic_matrix.append(row)
    ic_matrix = np.array(ic_matrix)
    ic_matrix = np.nan_to_num(ic_matrix, nan=0.0)

    mu = np.mean(ic_matrix, axis=0)

    # 正的保留, 负的设0
    w = np.maximum(mu, 0)
    if w.sum() <= 0:
        return None
    w = w / w.sum()

    return {f: float(w[i]) for i, f in enumerate(factor_names) if w[i] > 0.001}


def compute_ic_weights_icir(
    ic_panel: dict[date, dict[str, float]],
    current_date: date,
    factor_names: list[str],
    lookback_months: int = 12,
) -> dict[str, float]:
    """方法3: ICIR简单加权 (w_i = IC_mean / IC_std)。"""
    cutoff = current_date - timedelta(days=lookback_months * 31)
    past_dates = sorted([d for d in ic_panel if cutoff <= d < current_date])

    if len(past_dates) < 6:
        return None

    ic_matrix = []
    for d in past_dates:
        row = [ic_panel[d].get(f, np.nan) for f in factor_names]
        ic_matrix.append(row)
    ic_matrix = np.array(ic_matrix)
    ic_matrix = np.nan_to_num(ic_matrix, nan=0.0)

    mu = np.mean(ic_matrix, axis=0)
    std = np.std(ic_matrix, axis=0, ddof=1)

    # ICIR = mu / std
    icir = np.where(std > 1e-6, mu / std, 0)

    # ICIR<0 设0
    w = np.maximum(icir, 0)
    if w.sum() <= 0:
        return None
    w = w / w.sum()

    return {f: float(w[i]) for i, f in enumerate(factor_names) if w[i] > 0.001}


# ============================================================
# BP子维度融合
# ============================================================


def compute_bp_enhanced_panel(
    conn,
    rebalance_dates: list[date],
) -> dict[date, pd.Series]:
    """计算bp_enhanced因子面板。

    bp_enhanced = zscore(bp_ratio) + zscore(-bp_stability) + zscore(bp_percentile)

    - bp_ratio: 从factor_values读(已有)
    - bp_stability: 过去12季度BP(=1/PB)的标准差, 方向-1(低=好)
    - bp_percentile: 当前BP在过去3年中的分位数, 方向+1(高=好)
    """
    logger.info("计算BP子维度面板...")

    # 1. 加载daily_basic的pb(用于bp_percentile)
    logger.info("  加载daily_basic pb...")
    pb_daily = pd.read_sql(
        """SELECT code, trade_date, pb FROM daily_basic
           WHERE pb IS NOT NULL AND pb > 0
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(
            min(rebalance_dates) - timedelta(days=800),  # 3年+buffer
            max(rebalance_dates),
        ),
    )
    pb_daily_pivot = pb_daily.pivot_table(
        index="trade_date", columns="code", values="pb", aggfunc="first"
    )
    # BP = 1/PB
    bp_daily_pivot = 1.0 / pb_daily_pivot

    # 2. 加载financial_indicators的bps(用于bp_stability)
    logger.info("  加载financial_indicators bps...")
    fi_df = pd.read_sql(
        """SELECT code, report_date, actual_ann_date, bps
           FROM financial_indicators
           WHERE bps IS NOT NULL AND bps > 0
             AND actual_ann_date IS NOT NULL
             AND actual_ann_date BETWEEN %s AND %s
           ORDER BY actual_ann_date""",
        conn,
        params=(
            min(rebalance_dates) - timedelta(days=1200),  # 4年buffer for 12 quarters
            max(rebalance_dates),
        ),
    )

    panel = {}
    all_trade_dates = sorted(bp_daily_pivot.index.tolist())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}

    for rd in rebalance_dates:
        # --- bp_ratio: 从factor_values读 ---
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        fv_pivot = fv.pivot_table(
            index="code", columns="factor_name", values="neutral_value", aggfunc="first"
        )
        if "bp_ratio" not in fv_pivot.columns:
            continue
        bp_ratio_series = fv_pivot["bp_ratio"]

        # --- bp_stability: 过去12季度BPS的变异系数 ---
        # 用PIT: actual_ann_date <= rd
        fi_pit = fi_df[fi_df["actual_ann_date"] <= rd].copy()
        # 每个code取最近12个report_date
        bp_stability = {}
        for code, grp in fi_pit.groupby("code"):
            # 去重保留每个report_date最新的公告
            grp_dedup = grp.sort_values("actual_ann_date").drop_duplicates(
                subset=["code", "report_date"], keep="last"
            )
            recent = grp_dedup.sort_values("report_date", ascending=False).head(12)
            if len(recent) < 4:  # 最少4个季度
                continue
            bp_stability[code] = recent["bps"].std()

        bp_stability_series = pd.Series(bp_stability)

        # --- bp_percentile: 当前BP在过去750个交易日中的分位数 ---
        if rd not in date_to_idx:
            # 找最近的交易日
            close_dates = [d for d in all_trade_dates if d <= rd]
            if not close_dates:
                continue
            rd_actual = close_dates[-1]
        else:
            rd_actual = rd

        idx = date_to_idx.get(rd_actual)
        if idx is None:
            continue

        lookback_start = max(0, idx - 750)
        bp_window = bp_daily_pivot.iloc[lookback_start : idx + 1]

        if len(bp_window) < 60:  # 至少60天
            continue

        # 当前BP
        current_bp = bp_window.iloc[-1]
        # 分位数: 当前值在历史中的百分位
        bp_percentile = {}
        for code in current_bp.dropna().index:
            hist = bp_window[code].dropna()
            if len(hist) < 60:
                continue
            current_val = current_bp[code]
            pctile = (hist < current_val).sum() / len(hist)
            bp_percentile[code] = pctile

        bp_percentile_series = pd.Series(bp_percentile)

        # --- 融合: zscore(bp_ratio) + zscore(-bp_stability) + zscore(bp_percentile) ---
        common = (
            bp_ratio_series.dropna().index
            .intersection(bp_stability_series.dropna().index)
            .intersection(bp_percentile_series.dropna().index)
        )

        if len(common) < 30:
            # fallback: 只用bp_ratio
            panel[rd] = bp_ratio_series
            continue

        z_ratio = _zscore(bp_ratio_series.loc[common])
        z_stability = _zscore(-bp_stability_series.loc[common])  # 方向-1
        z_percentile = _zscore(bp_percentile_series.loc[common])

        bp_enhanced = (z_ratio + z_stability + z_percentile) / 3.0
        panel[rd] = bp_enhanced

    logger.info(f"  BP融合面板: {len(panel)}个日期")
    return panel


def _zscore(s: pd.Series) -> pd.Series:
    """截面zscore。"""
    mean = s.mean()
    std = s.std()
    if std > 1e-8:
        return (s - mean) / std
    return s * 0


# ============================================================
# 回测runner
# ============================================================


def run_baseline(
    rebalance_dates: list[date],
    industry: pd.Series,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    conn,
) -> dict:
    """配置0: 基线v1.1(等权)。"""
    sig_config = SignalConfig(
        factor_names=BASELINE_FACTORS,
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    bt_config = BacktestConfig(
        initial_capital=1_000_000.0,
        top_n=15,
        rebalance_freq="monthly",
        slippage_bps=10.0,
    )

    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    target_portfolios = {}
    prev_weights = {}

    for rd in rebalance_dates:
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    logger.info(f"  [基线v1.1] 信号完成: {len(target_portfolios)}个调仓日")

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    return _extract_summary("0:基线v1.1(等权)", result, BASELINE_FACTORS)


def run_ic_weighted(
    label: str,
    weight_method: str,  # 'max_icir', 'max_ic', 'icir_simple'
    ic_panel: dict[date, dict[str, float]],
    rebalance_dates: list[date],
    industry: pd.Series,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    conn,
) -> dict:
    """配置1/2/3: IC加权方法。"""
    bt_config = BacktestConfig(
        initial_capital=1_000_000.0,
        top_n=15,
        rebalance_freq="monthly",
        slippage_bps=10.0,
    )
    sig_config = SignalConfig(
        factor_names=BASELINE_FACTORS,
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    builder = PortfolioBuilder(sig_config)

    # 权重函数选择
    weight_funcs = {
        "max_icir": compute_ic_weights_maxicir,
        "max_ic": compute_ic_weights_maxic,
        "icir_simple": compute_ic_weights_icir,
    }
    weight_func = weight_funcs[weight_method]

    target_portfolios = {}
    prev_weights = {}
    weight_history = {}  # 记录每期权重

    fallback_count = 0
    ic_weight_count = 0

    for rd in rebalance_dates:
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)

        # 计算IC权重
        ic_weights = weight_func(ic_panel, rd, BASELINE_FACTORS, lookback_months=12)

        if ic_weights is None:
            # Fallback到等权
            fallback_count += 1
            composer = SignalComposer(sig_config)
            scores = composer.compose(fv, universe)
        else:
            # 用IC权重合成
            ic_weight_count += 1
            scores = _compose_with_weights(fv, universe, ic_weights)
            weight_history[rd] = ic_weights

        if scores.empty:
            continue

        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    logger.info(
        f"  [{label}] 信号完成: {len(target_portfolios)}个调仓日 "
        f"(IC加权{ic_weight_count}期, fallback等权{fallback_count}期)"
    )

    # 打印权重变化摘要
    if weight_history:
        _print_weight_summary(label, weight_history, BASELINE_FACTORS)

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    return _extract_summary(label, result, BASELINE_FACTORS)


def _compose_with_weights(
    factor_df: pd.DataFrame,
    universe: set[str],
    weights: dict[str, float],
) -> pd.Series:
    """用自定义权重合成因子得分。"""
    pivot = factor_df.pivot_table(
        index="code", columns="factor_name", values="neutral_value", aggfunc="first"
    )

    if universe:
        pivot = pivot[pivot.index.isin(universe)]

    available = [f for f in weights if f in pivot.columns]
    if not available:
        return pd.Series(dtype=float)

    # 方向调整
    for fname in available:
        direction = FACTOR_DIRECTION.get(fname, 1)
        if direction == -1:
            pivot[fname] = -pivot[fname]

    # 加权合成
    composite = sum(pivot[fname] * weights[fname] for fname in available)

    return composite.sort_values(ascending=False)


def run_bp_enhanced(
    bp_panel: dict[date, pd.Series],
    rebalance_dates: list[date],
    industry: pd.Series,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    conn,
) -> dict:
    """配置4: 等权但bp_ratio→bp_enhanced。"""
    bt_config = BacktestConfig(
        initial_capital=1_000_000.0,
        top_n=15,
        rebalance_freq="monthly",
        slippage_bps=10.0,
    )
    sig_config = SignalConfig(
        factor_names=BASELINE_FACTORS,
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    builder = PortfolioBuilder(sig_config)

    # 替换后的因子列表
    enhanced_factors = [
        f if f != "bp_ratio" else "bp_enhanced" for f in BASELINE_FACTORS
    ]

    target_portfolios = {}
    prev_weights = {}

    for rd in rebalance_dates:
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)

        # pivot到宽表
        pivot = fv.pivot_table(
            index="code", columns="factor_name", values="neutral_value", aggfunc="first"
        )

        if universe:
            pivot = pivot[pivot.index.isin(universe)]

        # 替换bp_ratio为bp_enhanced
        if rd in bp_panel:
            bp_enhanced = bp_panel[rd]
            # 对齐index
            common = pivot.index.intersection(bp_enhanced.index)
            if len(common) > 0:
                pivot.loc[common, "bp_enhanced"] = bp_enhanced.loc[common]
                # 没有bp_enhanced的股票: 用原bp_ratio
                missing = pivot.index.difference(bp_enhanced.index)
                if len(missing) > 0 and "bp_ratio" in pivot.columns:
                    pivot.loc[missing, "bp_enhanced"] = pivot.loc[missing, "bp_ratio"]
            else:
                # fallback
                if "bp_ratio" in pivot.columns:
                    pivot["bp_enhanced"] = pivot["bp_ratio"]
        else:
            if "bp_ratio" in pivot.columns:
                pivot["bp_enhanced"] = pivot["bp_ratio"]

        # 等权合成(用enhanced_factors)
        available = [f for f in enhanced_factors if f in pivot.columns]
        if not available:
            continue

        for fname in available:
            direction = FACTOR_DIRECTION.get(
                "bp_ratio" if fname == "bp_enhanced" else fname, 1
            )
            if direction == -1:
                pivot[fname] = -pivot[fname]

        n_factors = len(available)
        composite = sum(pivot[f] / n_factors for f in available)
        scores = composite.sort_values(ascending=False)

        if scores.empty:
            continue

        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    logger.info(f"  [BP融合] 信号完成: {len(target_portfolios)}个调仓日")

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    return _extract_summary("4:BP融合(等权)", result, enhanced_factors)


# ============================================================
# 结果提取和展示
# ============================================================


def bootstrap_sharpe_ci(
    daily_returns: pd.Series, n_bootstrap: int = 1000, ci: float = 0.95
) -> tuple[float, float, float]:
    """计算Sharpe的Bootstrap置信区间。"""
    returns = daily_returns.dropna().values
    n = len(returns)
    if n < 30:
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        return float(sharpe), float(sharpe) - 0.5, float(sharpe) + 0.5

    rng = np.random.RandomState(42)
    sharpes = []
    for _ in range(n_bootstrap):
        sample = rng.choice(returns, size=n, replace=True)
        std = np.std(sample, ddof=1)
        if std > 1e-10:
            sharpes.append(np.mean(sample) / std * np.sqrt(252))

    if not sharpes:
        return 0.0, 0.0, 0.0

    alpha = (1 - ci) / 2
    return (
        float(np.mean(sharpes)),
        float(np.percentile(sharpes, alpha * 100)),
        float(np.percentile(sharpes, (1 - alpha) * 100)),
    )


def _extract_summary(label: str, result, factor_names: list[str]) -> dict:
    """从回测结果提取绩效摘要。"""
    dr = result.daily_returns.copy()
    dr.index = pd.to_datetime(dr.index)

    sharpe_mean, ci_low, ci_high = bootstrap_sharpe_ci(dr)

    annual = {}
    for year in range(2021, 2026):
        mask = dr.index.year == year
        yr = dr[mask]
        if len(yr) > 0:
            ann_ret = (1 + yr).prod() - 1
            ann_sharpe = yr.mean() / yr.std() * np.sqrt(252) if yr.std() > 0 else 0
            cum = (1 + yr).cumprod()
            drawdown = cum / cum.cummax() - 1
            mdd = drawdown.min()
            annual[year] = {
                "return": float(ann_ret),
                "sharpe": float(ann_sharpe),
                "mdd": float(mdd),
            }

    total_ret = (1 + dr).prod() - 1
    ann_ret = (1 + total_ret) ** (252 / len(dr)) - 1 if len(dr) > 0 else 0
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    cum_nav = (1 + dr).cumprod()
    mdd = (cum_nav / cum_nav.cummax() - 1).min()

    calmar = float(ann_ret / abs(mdd)) if mdd != 0 else 0
    downside = dr[dr < 0].std() * np.sqrt(252) if len(dr[dr < 0]) > 0 else 1
    sortino = float(ann_ret / downside) if downside > 0 else 0

    return {
        "label": label,
        "factors": factor_names,
        "total_return": float(total_ret),
        "ann_return": float(ann_ret),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": calmar,
        "sortino": sortino,
        "bootstrap_sharpe_mean": sharpe_mean,
        "bootstrap_ci_low": ci_low,
        "bootstrap_ci_high": ci_high,
        "annual": annual,
    }


def _print_weight_summary(
    label: str, weight_history: dict[date, dict[str, float]], factor_names: list[str]
) -> None:
    """打印权重变化摘要。"""
    print(f"\n  [{label}] 因子权重时序 (最近6期):")
    recent = sorted(weight_history.keys())[-6:]
    print(f"  {'日期':<14}", end="")
    for f in factor_names:
        print(f"  {f[:12]:>12}", end="")
    print()
    for d in recent:
        w = weight_history[d]
        print(f"  {str(d):<14}", end="")
        for f in factor_names:
            val = w.get(f, 0)
            print(f"  {val:>12.1%}", end="")
        print()


def print_comparison(summaries: list[dict]) -> None:
    """打印5配置对比表。"""
    print("\n" + "=" * 120)
    print("IC加权回测对比 — 5配置 (改因子权重, 非改选股池)")
    print("=" * 120)

    # 整体对比
    print(f"\n{'指标':<25}", end="")
    for s in summaries:
        print(f"  {s['label']:>20}", end="")
    print()
    print("-" * (25 + 22 * len(summaries)))

    rows = [
        ("总收益", "total_return", ".1%"),
        ("年化收益", "ann_return", ".1%"),
        ("Sharpe", "sharpe", ".3f"),
        ("最大回撤", "mdd", ".1%"),
        ("Calmar", "calmar", ".2f"),
        ("Sortino", "sortino", ".2f"),
        ("Bootstrap Sharpe", "bootstrap_sharpe_mean", ".3f"),
        ("  95% CI 下界", "bootstrap_ci_low", ".3f"),
        ("  95% CI 上界", "bootstrap_ci_high", ".3f"),
    ]

    for label, key, fmt in rows:
        print(f"{label:<25}", end="")
        for s in summaries:
            val = s[key]
            print(f"  {val:>20{fmt}}", end="")
        print()

    # 年度分解
    print(f"\n{'年度分解':=^120}")
    for year in range(2021, 2026):
        print(f"\n  {year}年:")
        print(f"  {'指标':<22}", end="")
        for s in summaries:
            print(f"  {s['label']:>20}", end="")
        print()

        for label, key, fmt in [
            ("收益", "return", ".1%"),
            ("Sharpe", "sharpe", ".3f"),
            ("MDD", "mdd", ".1%"),
        ]:
            print(f"  {label:<22}", end="")
            for s in summaries:
                if year in s["annual"]:
                    val = s["annual"][year][key]
                    print(f"  {val:>20{fmt}}", end="")
                else:
                    print(f"  {'N/A':>20}", end="")
            print()

    # 增量分析
    baseline = summaries[0]
    print(f"\n{'增量效果(vs 基线v1.1)':=^120}")
    print(f"  {'配置':<25}{'Sharpe增量':>12}{'年化收益增量':>14}{'MDD变化':>12}{'CI下界增量':>14}")
    print(f"  {'-' * 75}")
    for s in summaries[1:]:
        d_sharpe = s["sharpe"] - baseline["sharpe"]
        d_ret = s["ann_return"] - baseline["ann_return"]
        d_mdd = s["mdd"] - baseline["mdd"]
        d_ci = s["bootstrap_ci_low"] - baseline["bootstrap_ci_low"]
        print(
            f"  {s['label']:<25}"
            f"{d_sharpe:>+12.3f}"
            f"{d_ret:>+14.1%}"
            f"{d_mdd:>+12.1%}"
            f"{d_ci:>+14.3f}"
        )

    # 核心判断
    print(f"\n{'核心判断':=^120}")
    best = max(summaries, key=lambda s: s["sharpe"])
    print(f"  最高Sharpe: {best['label']} ({best['sharpe']:.3f})")

    # IC加权 vs 等权
    ic_methods = summaries[1:4]
    best_ic = max(ic_methods, key=lambda s: s["sharpe"])
    if best_ic["sharpe"] > baseline["sharpe"] + 0.05:
        print(
            f"  最优IC加权 vs 等权: {best_ic['label']} Sharpe +{best_ic['sharpe'] - baseline['sharpe']:.3f}, "
            f"IC加权有效, 建议替换等权"
        )
    elif best_ic["sharpe"] > baseline["sharpe"]:
        print(
            f"  最优IC加权 vs 等权: {best_ic['label']} Sharpe +{best_ic['sharpe'] - baseline['sharpe']:.3f}, "
            f"微弱优势, 增量<0.05不显著"
        )
    else:
        print(
            f"  最优IC加权 vs 等权: {best_ic['label']} Sharpe {best_ic['sharpe'] - baseline['sharpe']:+.3f}, "
            f"等权仍然更优, IC加权无增量"
        )

    # BP融合
    if len(summaries) > 4:
        bp_s = summaries[4]
        if bp_s["sharpe"] > baseline["sharpe"] + 0.05:
            print(
                f"  BP融合 vs 等权: Sharpe +{bp_s['sharpe'] - baseline['sharpe']:.3f}, "
                f"子维度融合有效"
            )
        elif bp_s["sharpe"] > baseline["sharpe"]:
            print(
                f"  BP融合 vs 等权: Sharpe +{bp_s['sharpe'] - baseline['sharpe']:.3f}, "
                f"微弱改善, 不显著"
            )
        else:
            print(
                f"  BP融合 vs 等权: Sharpe {bp_s['sharpe'] - baseline['sharpe']:+.3f}, "
                f"融合无增量"
            )

    # 三种IC加权方法对比
    print("\n  IC加权方法排名:")
    ic_sorted = sorted(ic_methods, key=lambda s: s["sharpe"], reverse=True)
    for i, s in enumerate(ic_sorted):
        marker = " <-- 最优" if i == 0 else ""
        print(f"    {i+1}. {s['label']}: Sharpe={s['sharpe']:.3f}, MDD={s['mdd']:.1%}{marker}")

    # 风险调整评估
    print("\n  风险调整评估:")
    for s in summaries:
        risk_flag = ""
        if s["mdd"] < -0.40:
            risk_flag = " [!MDD过大]"
        if s["bootstrap_ci_low"] < 0:
            risk_flag += " [!CI下界<0]"
        print(
            f"    {s['label']}: Sharpe={s['sharpe']:.3f} [{s['bootstrap_ci_low']:.3f}, "
            f"{s['bootstrap_ci_high']:.3f}] MDD={s['mdd']:.1%}{risk_flag}"
        )

    print()


# ============================================================
# 主程序
# ============================================================


def main():
    print("\n" + "=" * 70)
    print("  IC加权回测对比 — 5配置")
    print("  方法1: 最大化ICIR (Sigma^{-1} * mu)")
    print("  方法2: 最大化IC (w = mu)")
    print("  方法3: ICIR简单加权 (w_i = IC_mean/IC_std)")
    print("  方法4: BP子维度融合 (stability + percentile)")
    print("  区间: 2021-01-01 ~ 2025-12-31, 100万, 月频, Top15")
    print("=" * 70)

    start = date(2021, 1, 1)
    end = date(2025, 12, 31)

    conn = _get_sync_conn()
    t0 = time.time()

    # 1. 公共数据
    logger.info("获取调仓日历...")
    rebalance_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    logger.info("加载行业分类...")
    industry = load_industry(conn)

    logger.info("加载价格数据...")
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

    # 2. IC面板计算 (需要更早的数据来计算2021年的IC)
    # 为了计算2021-01的IC, 需要2020-01开始的因子数据
    logger.info("计算IC面板(含2020年回看期)...")
    ic_start = date(2020, 1, 1)
    ic_rebalance_dates = get_rebalance_dates(ic_start, end, freq="monthly", conn=conn)
    ic_panel = compute_monthly_ic_panel(
        conn, ic_rebalance_dates, BASELINE_FACTORS, fwd_days=20
    )
    logger.info(f"IC面板: {len(ic_panel)}个月度IC")

    # 打印IC统计
    _print_ic_stats(ic_panel, BASELINE_FACTORS)

    summaries = []

    # ---- 配置0: 基线v1.1(等权) ----
    logger.info("\n[配置0] 基线v1.1 — 5因子等权")
    s0 = run_baseline(rebalance_dates, industry, price_data, benchmark_data, conn)
    summaries.append(s0)

    # ---- 配置1: 最大化ICIR ----
    logger.info("\n[配置1] 最大化ICIR (Sigma^{-1} * mu)")
    s1 = run_ic_weighted(
        "1:最大化ICIR",
        "max_icir",
        ic_panel,
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
    )
    summaries.append(s1)

    # ---- 配置2: 最大化IC ----
    logger.info("\n[配置2] 最大化IC (w = mu)")
    s2 = run_ic_weighted(
        "2:最大化IC",
        "max_ic",
        ic_panel,
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
    )
    summaries.append(s2)

    # ---- 配置3: ICIR简单加权 ----
    logger.info("\n[配置3] ICIR简单加权")
    s3 = run_ic_weighted(
        "3:ICIR简单加权",
        "icir_simple",
        ic_panel,
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
    )
    summaries.append(s3)

    # ---- 配置4: BP融合(等权) ----
    logger.info("\n[配置4] BP融合(等权)")
    bp_panel = compute_bp_enhanced_panel(conn, rebalance_dates)
    if bp_panel:
        s4 = run_bp_enhanced(
            bp_panel, rebalance_dates, industry, price_data, benchmark_data, conn
        )
        summaries.append(s4)
    else:
        logger.warning("BP融合面板为空, 跳过配置4")

    conn.close()

    # 输出对比
    print_comparison(summaries)

    elapsed = time.time() - t0
    logger.info(f"回测完成, 总耗时 {elapsed:.0f}s")


def _print_ic_stats(
    ic_panel: dict[date, dict[str, float]], factor_names: list[str]
) -> None:
    """打印IC统计概览。"""
    print(f"\n{'IC统计概览 (Spearman Rank IC, 20日超额)':=^80}")
    print(f"  {'因子':<20}{'IC均值':>10}{'IC标准差':>10}{'ICIR':>10}{'IC>0占比':>10}{'月数':>8}")
    print(f"  {'-' * 68}")

    for fname in factor_names:
        ics = [ic_panel[d][fname] for d in ic_panel if fname in ic_panel[d]]
        if not ics:
            print(f"  {fname:<20}{'N/A':>10}")
            continue
        ic_arr = np.array(ics)
        ic_mean = np.mean(ic_arr)
        ic_std = np.std(ic_arr, ddof=1)
        icir = ic_mean / ic_std if ic_std > 1e-6 else 0
        ic_pos = np.mean(ic_arr > 0)
        print(
            f"  {fname:<20}"
            f"{ic_mean:>10.4f}"
            f"{ic_std:>10.4f}"
            f"{icir:>10.3f}"
            f"{ic_pos:>10.1%}"
            f"{len(ics):>8}"
        )
    print()


if __name__ == "__main__":
    main()
