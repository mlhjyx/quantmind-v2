#!/usr/bin/env python3
"""方案D回测: 因子专属股票池 + 选择性等权融合。

核心逻辑: 不是给因子不同权重，而是让每个因子只在适合它的股票上说话。

三个独立股票池(每月末截面):
- 价量因子池: amihud_20(+1) + turnover_mean_20(-1) + reversal_20(+1) + volatility_20(-1)
              等权打分 → Top50%
- 估值因子池: bp_ratio全市场, 剔除(1)市值<净资产80%的 (2)金融+房地产行业BP极端高(Top5%)
- PEAD因子池: earnings_surprise_car全市场, 剔除最近4季度有亏损的(roe<0的季度>=1个)

选择性等权融合:
- 每只股票: 在哪个池中就用哪个池的zscore
- 综合分 = sum(有值的分数) / count(有值的分数)
- 不在任何池中 → 排除
- Top15 → 月频 → IndCap=25%

对比: 方案D vs v1.1基线(5因子简单等权Top15)

回测区间: 2021-01-01 ~ 2025-12-31, 100万初始资金
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import generate_report
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
from run_pead_backtest import bootstrap_sharpe_ci, compute_pead_factor_panel

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

# 金融+房地产行业列表(申万一级)
FINANCE_RE_INDUSTRIES = {"银行", "证券", "保险", "多元金融", "区域地产", "全国地产"}


# ============================================================
# 估值池辅助: 加载市值与净资产数据
# ============================================================


def load_mv_and_bps(trade_date: date, conn) -> pd.DataFrame:
    """加载市值(万元)和每股净资产(bps)用于估值池过滤。

    Args:
        trade_date: 交易日。
        conn: psycopg2连接。

    Returns:
        DataFrame [code, total_mv, pb, industry_sw1]
    """
    df = pd.read_sql(
        """SELECT db.code, db.total_mv, db.pb,
                  s.industry_sw1
           FROM daily_basic db
           JOIN symbols s ON db.code = s.code
           WHERE db.trade_date = %s
             AND db.total_mv IS NOT NULL
             AND db.pb IS NOT NULL
             AND db.pb > 0""",
        conn,
        params=(trade_date,),
    )
    return df


# ============================================================
# PEAD池辅助: 加载最近4季度ROE
# ============================================================


def load_recent_roe(trade_date: date, conn) -> pd.DataFrame:
    """加载截至trade_date的PIT最近4季度ROE。

    Args:
        trade_date: 交易日。
        conn: psycopg2连接。

    Returns:
        DataFrame [code, report_date, roe]，每个code最近4季度。
    """
    df = pd.read_sql(
        """WITH ranked AS (
            SELECT code, report_date, roe, actual_ann_date,
                   ROW_NUMBER() OVER (
                       PARTITION BY code, report_date
                       ORDER BY actual_ann_date DESC
                   ) AS rn
            FROM financial_indicators
            WHERE actual_ann_date <= %s
              AND actual_ann_date >= %s - INTERVAL '2 years'
              AND roe IS NOT NULL
        )
        SELECT code, report_date, roe
        FROM ranked
        WHERE rn = 1
        ORDER BY code, report_date DESC""",
        conn,
        params=(trade_date, trade_date),
    )
    # 每个code取最近4个季度
    result = df.groupby("code").head(4)
    return result


# ============================================================
# 方案D核心: 因子专属股票池 + 选择性等权融合
# ============================================================


def method_d_select(
    factor_wide: pd.DataFrame,
    universe: set[str],
    mv_bps_df: pd.DataFrame,
    roe_df: pd.DataFrame,
    industry: pd.Series,
    pead_series: pd.Series | None,
    top_n: int = 15,
) -> pd.Series:
    """方案D选股: 因子专属股票池 + 选择性等权融合。

    Args:
        factor_wide: pivot后宽表(index=code, columns=factor_name, values=neutral_value)。
        universe: 可交易universe。
        mv_bps_df: 市值+pb数据 [code, total_mv, pb, industry_sw1]。
        roe_df: 最近4季度ROE数据 [code, report_date, roe]。
        industry: 行业分类 (code→industry_sw1)。
        pead_series: PEAD因子截面 (code→car值), 可为None。
        top_n: 最终选股数。

    Returns:
        pd.Series(code→composite_score), 长度=top_n。
    """
    # 限制在universe中
    candidates = factor_wide[factor_wide.index.isin(universe)].copy()
    codes_in_universe = set(candidates.index)

    # ================================================================
    # 池1: 价量因子池 — Top50%
    # ================================================================
    pq_factors = [
        ("amihud_20", 1),
        ("turnover_mean_20", -1),
        ("reversal_20", 1),
        ("volatility_20", -1),
    ]
    pq_available = [(f, d) for f, d in pq_factors if f in candidates.columns]

    pq_pool = set()
    pq_scores = pd.Series(dtype=float)  # code→price_quantity_score

    if pq_available:
        pq_score = pd.Series(0.0, index=candidates.index)
        for fname, direction in pq_available:
            vals = candidates[fname].copy()
            mean_v = vals.mean()
            std_v = vals.std()
            if std_v > 0:
                vals = (vals - mean_v) / std_v
            vals = vals * direction
            pq_score += vals / len(pq_available)

        pq_score = pq_score.dropna()
        # Top 50%
        n_keep = max(1, int(len(pq_score) * 0.50))
        pq_score_sorted = pq_score.sort_values(ascending=False)
        pq_pool = set(pq_score_sorted.head(n_keep).index)

        # 池内zscore重新计算(只对池内股票)
        pq_in_pool = pq_score.loc[pq_score.index.isin(pq_pool)]
        pq_mean = pq_in_pool.mean()
        pq_std = pq_in_pool.std()
        if pq_std > 0:
            pq_scores = (pq_in_pool - pq_mean) / pq_std
        else:
            pq_scores = pq_in_pool * 0

    logger.debug(f"  价量池: {len(pq_pool)}只")

    # ================================================================
    # 池2: 估值因子池 — bp_ratio全市场, 但剔除问题股
    # ================================================================
    val_pool = set()
    val_scores = pd.Series(dtype=float)

    if "bp_ratio" in candidates.columns and not mv_bps_df.empty:
        mv_bps = mv_bps_df.set_index("code")

        # 获取bp_ratio的原始值(neutral_value已经过中性化)
        bp_vals = candidates["bp_ratio"].dropna()
        bp_codes = set(bp_vals.index) & codes_in_universe

        # 过滤1: 市值 < 净资产*80% (total_mv万元, pb = 市值/净资产)
        # pb < 0.8 的股票(市净率<0.8, 即市值<净资产*80%)
        pb_data = mv_bps.reindex(list(bp_codes))
        exclude_low_pb = set()
        if "pb" in pb_data.columns:
            low_pb_mask = pb_data["pb"] < 0.8
            exclude_low_pb = set(pb_data[low_pb_mask].index)

        # 过滤2: 金融+房地产行业中BP极端高的(Top5%)
        exclude_fin_re_extreme = set()
        fin_re_codes = set()
        for code in bp_codes:
            ind = industry.get(code, "其他")
            if ind in FINANCE_RE_INDUSTRIES:
                fin_re_codes.add(code)

        if fin_re_codes:
            fin_re_bp = bp_vals.loc[bp_vals.index.isin(fin_re_codes)].dropna()
            if len(fin_re_bp) > 20:
                threshold = fin_re_bp.quantile(0.95)
                exclude_fin_re_extreme = set(fin_re_bp[fin_re_bp >= threshold].index)

        # 构建估值池
        excluded = exclude_low_pb | exclude_fin_re_extreme
        val_pool = bp_codes - excluded

        if val_pool:
            bp_in_pool = bp_vals.loc[bp_vals.index.isin(val_pool)]
            bp_mean = bp_in_pool.mean()
            bp_std = bp_in_pool.std()
            if bp_std > 0:
                # bp_ratio方向+1 (高BP好), neutral_value已经过中性化
                # FACTOR_DIRECTION['bp_ratio'] = 1
                val_scores = (bp_in_pool - bp_mean) / bp_std
            else:
                val_scores = bp_in_pool * 0

        logger.debug(
            f"  估值池: {len(val_pool)}只 "
            f"(剔除低PB: {len(exclude_low_pb)}, 剔除金融RE极端: {len(exclude_fin_re_extreme)})"
        )

    # ================================================================
    # 池3: PEAD因子池 — 剔除亏损股
    # ================================================================
    pead_pool = set()
    pead_scores = pd.Series(dtype=float)

    if pead_series is not None and not pead_series.empty and not roe_df.empty:
        # 找出最近4季度有亏损的(roe<0的季度>=1个)
        loss_stocks = set()
        for code, grp in roe_df.groupby("code"):
            if (grp["roe"] < 0).any():
                loss_stocks.add(code)

        pead_codes = set(pead_series.index) & codes_in_universe
        pead_pool = pead_codes - loss_stocks

        if pead_pool:
            pead_in_pool = pead_series.loc[pead_series.index.isin(pead_pool)].dropna()
            pead_mean = pead_in_pool.mean()
            pead_std = pead_in_pool.std()
            if pead_std > 0:
                pead_scores = (pead_in_pool - pead_mean) / pead_std
            else:
                pead_scores = pead_in_pool * 0

        logger.debug(
            f"  PEAD池: {len(pead_pool)}只 (剔除亏损: {len(loss_stocks & pead_codes)})"
        )

    # ================================================================
    # 选择性等权融合
    # ================================================================
    # 收集所有有分数的股票
    all_codes = set()
    if not pq_scores.empty:
        all_codes |= set(pq_scores.index)
    if not val_scores.empty:
        all_codes |= set(val_scores.index)
    if not pead_scores.empty:
        all_codes |= set(pead_scores.index)

    if not all_codes:
        logger.warning("  方案D: 无任何池有效股票")
        return pd.Series(dtype=float)

    composite = {}
    pool_counts = {1: 0, 2: 0, 3: 0}  # 1池, 2池, 3池

    for code in all_codes:
        scores_list = []
        if code in pq_scores.index and np.isfinite(pq_scores[code]):
            scores_list.append(pq_scores[code])
        if code in val_scores.index and np.isfinite(val_scores[code]):
            scores_list.append(val_scores[code])
        if code in pead_scores.index and np.isfinite(pead_scores[code]):
            scores_list.append(pead_scores[code])

        if scores_list:
            composite[code] = sum(scores_list) / len(scores_list)
            pool_counts[len(scores_list)] = pool_counts.get(len(scores_list), 0) + 1

    logger.debug(
        f"  融合: 1池={pool_counts.get(1,0)}, 2池={pool_counts.get(2,0)}, "
        f"3池={pool_counts.get(3,0)}, 总={len(composite)}"
    )

    composite_series = pd.Series(composite).sort_values(ascending=False)
    return composite_series.head(top_n)


# ============================================================
# 回测runner
# ============================================================


def run_baseline_backtest(
    label: str,
    rebalance_dates: list[date],
    industry: pd.Series,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    conn,
) -> dict:
    """运行基线v1.1回测(等权合成)。"""
    sig_config = SignalConfig(
        factor_names=[
            "turnover_mean_20",
            "volatility_20",
            "reversal_20",
            "amihud_20",
            "bp_ratio",
        ],
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

    for i, rd in enumerate(rebalance_dates):
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

    logger.info(f"  [{label}] 信号完成: {len(target_portfolios)}个调仓日")

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    return _extract_summary(label, result, sig_config.factor_names)


def run_method_d_backtest(
    label: str,
    rebalance_dates: list[date],
    industry: pd.Series,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    conn,
    pead_panel: dict[date, pd.Series],
) -> dict:
    """运行方案D回测。

    Args:
        label: 配置标签。
        rebalance_dates: 调仓日列表。
        industry: 行业分类。
        price_data: 价格数据。
        benchmark_data: 基准数据。
        conn: DB连接。
        pead_panel: PEAD因子面板。
    """
    top_n = 15
    sig_config = SignalConfig(
        top_n=top_n,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    bt_config = BacktestConfig(
        initial_capital=1_000_000.0,
        top_n=top_n,
        rebalance_freq="monthly",
        slippage_bps=10.0,
    )
    builder = PortfolioBuilder(sig_config)

    target_portfolios = {}
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)

        # Pivot到宽表
        pivot = fv.pivot_table(
            index="code",
            columns="factor_name",
            values="neutral_value",
            aggfunc="first",
        )

        # 加载辅助数据
        mv_bps_df = load_mv_and_bps(rd, conn)
        roe_df = load_recent_roe(rd, conn)

        # 获取当月PEAD截面
        pead_series = pead_panel.get(rd, None)

        # 方案D选股
        scores = method_d_select(
            factor_wide=pivot,
            universe=universe,
            mv_bps_df=mv_bps_df,
            roe_df=roe_df,
            industry=industry,
            pead_series=pead_series,
            top_n=top_n,
        )

        if scores.empty:
            continue

        # PortfolioBuilder加行业约束和换手率约束
        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

        if (i + 1) % 10 == 0:
            n_stocks = len(target) if target else 0
            logger.info(
                f"  [{label}] 信号 [{i + 1}/{len(rebalance_dates)}] "
                f"{rd}: {n_stocks}只"
            )

    logger.info(f"  [{label}] 信号完成: {len(target_portfolios)}个调仓日")

    # 回测
    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    factor_names = [
        "amihud_20", "turnover_mean_20", "reversal_20", "volatility_20",
        "bp_ratio", "earnings_surprise_car",
    ]
    return _extract_summary(label, result, factor_names)


def _extract_summary(label: str, result, factor_names: list[str]) -> dict:
    """从回测结果提取绩效摘要。"""
    dr = result.daily_returns.copy()
    dr.index = pd.to_datetime(dr.index)

    # Bootstrap CI
    sharpe_mean, ci_low, ci_high = bootstrap_sharpe_ci(dr)

    # 年度分解
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

    # 整体
    total_ret = (1 + dr).prod() - 1
    ann_ret = (1 + total_ret) ** (252 / len(dr)) - 1 if len(dr) > 0 else 0
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    cum_nav = (1 + dr).cumprod()
    mdd = (cum_nav / cum_nav.cummax() - 1).min()

    # Calmar / Sortino
    calmar = float(ann_ret / abs(mdd)) if mdd != 0 else 0
    downside = dr[dr < 0].std() * np.sqrt(252) if len(dr[dr < 0]) > 0 else 1
    sortino = float(ann_ret / downside) if downside > 0 else 0

    return {
        "label": label,
        "factors": factor_names,
        "n_factors": len(factor_names),
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
        "n_rebalances": len(result.trades) if hasattr(result, "trades") else 0,
    }


# ============================================================
# 对比输出
# ============================================================


def print_comparison(summaries: list[dict]) -> None:
    """打印方案D vs 基线对比表。"""
    print("\n" + "=" * 90)
    print("  方案D: 因子专属股票池 + 选择性等权融合 vs v1.1基线")
    print("  区间: 2021-01-01 ~ 2025-12-31, 100万, Top15, 月频, IndCap=25%")
    print("=" * 90)

    # 整体对比
    print(f"\n{'指标':<25}", end="")
    for s in summaries:
        print(f"  {s['label']:>20}", end="")
    print()
    print("-" * (25 + 22 * len(summaries)))

    rows = [
        ("因子数(池内)", "n_factors", "d"),
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
    print(f"\n{'年度分解':=^90}")
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

    # 增量效果
    if len(summaries) == 2:
        baseline, method_d = summaries
        print(f"\n{'增量效果(方案D - 基线)':=^90}")
        d_sharpe = method_d["sharpe"] - baseline["sharpe"]
        d_ret = method_d["ann_return"] - baseline["ann_return"]
        d_mdd = method_d["mdd"] - baseline["mdd"]
        d_ci_low = method_d["bootstrap_ci_low"] - baseline["bootstrap_ci_low"]

        print(f"  Sharpe增量:       {d_sharpe:+.3f}")
        print(f"  年化收益增量:     {d_ret:+.1%}")
        print(f"  MDD变化:          {d_mdd:+.1%}")
        print(f"  Bootstrap CI下界: {d_ci_low:+.3f}")

        # 年度逐年对比
        print(f"\n  年度优劣对比:")
        for year in range(2021, 2026):
            if year in baseline["annual"] and year in method_d["annual"]:
                b_sharpe = baseline["annual"][year]["sharpe"]
                d_sharpe_yr = method_d["annual"][year]["sharpe"]
                diff = d_sharpe_yr - b_sharpe
                winner = "方案D胜" if diff > 0.05 else ("基线胜" if diff < -0.05 else "平局")
                print(f"    {year}: Sharpe {d_sharpe_yr:.3f} vs {b_sharpe:.3f} ({diff:+.3f}) → {winner}")

        # 核心判定
        print(f"\n{'核心判定':=^90}")
        if method_d["sharpe"] > baseline["sharpe"] + 0.05:
            print(f"  方案D Sharpe={method_d['sharpe']:.3f} > 基线{baseline['sharpe']:.3f}+0.05")
            print("  结论: 方案D突破等权天花板, 因子专属池+选择性融合有效")
            if method_d["mdd"] > baseline["mdd"]:
                print(f"  注意: MDD也改善 ({method_d['mdd']:.1%} vs {baseline['mdd']:.1%})")
            else:
                print(f"  注意: MDD恶化 ({method_d['mdd']:.1%} vs {baseline['mdd']:.1%})")
        elif abs(method_d["sharpe"] - baseline["sharpe"]) <= 0.05:
            print(f"  方案D Sharpe={method_d['sharpe']:.3f} ≈ 基线{baseline['sharpe']:.3f} (差异<0.05)")
            print("  结论: 方案D未显著突破等权天花板")
        else:
            print(f"  方案D Sharpe={method_d['sharpe']:.3f} < 基线{baseline['sharpe']:.3f}")
            print("  结论: 方案D劣于基线, 因子专属池+选择性融合在当前因子集上无效")

    print()


# ============================================================
# 主程序
# ============================================================


def main():
    """方案D回测主程序。"""
    print("\n" + "=" * 60)
    print("  方案D: 因子专属股票池 + 选择性等权融合")
    print("  区间: 2021-01-01 ~ 2025-12-31")
    print("  资金: 100万, 月频, Top15, IndCap=25%")
    print("=" * 60)

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

    # 2. 计算PEAD因子面板
    logger.info("计算PEAD因子面板...")
    pead_panel = compute_pead_factor_panel(conn, start, end)
    if not pead_panel:
        logger.warning("PEAD因子面板为空, 方案D将不含PEAD池")

    summaries = []

    # ---- 基线v1.1 ----
    logger.info("\n[基线] v1.1 — 5因子等权")
    s_baseline = run_baseline_backtest(
        "v1.1基线(5F等权)",
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
    )
    summaries.append(s_baseline)

    # ---- 方案D ----
    logger.info("\n[方案D] 因子专属股票池 + 选择性等权融合")
    s_method_d = run_method_d_backtest(
        "D:专属池融合",
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
        pead_panel=pead_panel or {},
    )
    summaries.append(s_method_d)

    conn.close()

    # 输出对比
    print_comparison(summaries)

    elapsed = time.time() - t0
    logger.info(f"回测完成, 总耗时 {elapsed:.0f}s")


if __name__ == "__main__":
    main()
