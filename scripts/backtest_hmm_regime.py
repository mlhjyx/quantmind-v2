#!/usr/bin/env python3
"""HMM Regime 三方案对比回测 — Sprint 1.12验证。

对比三个方案，使用v1.1配置(5因子等权Top15月度)：
  方案A: 无Regime (scale=1.0恒定)
  方案B: Vol Regime (启发式，baseline_vol/current_vol)
  方案C: HMM Regime (2状态risk-on/risk-off，rolling fit 252天)

quant+risk审查后修正:
  - 2-state替代3-state（参数6个 vs 33个）
  - 单特征(对数收益率)避免多重共线性
  - Rolling fit(252天窗口)每个调仓日refit，无look-ahead
  - 连续scale: bear_prob → position_scale
  - 去抖动: 概率阈值0.7 + 最小持续5天

用法:
    python scripts/backtest_hmm_regime.py
    python scripts/backtest_hmm_regime.py --scheme C  # 只跑HMM方案
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import generate_report, print_report
from engines.regime_detector import (
    HMMRegimeDetector,
    RegimeResult,
)
from engines.signal_engine import (
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from engines.slippage_model import SlippageConfig
from engines.vol_regime import calc_vol_regime

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# v1.1锁定配置 — 5因子等权Top15月度
V11_SIGNAL_CONFIG = SignalConfig(
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
    cash_buffer=0.03,
)

# v1.1基线参考值（CLAUDE.md 技术决策快查表）
BASELINE_SHARPE = 0.91  # sigma校准后
BASELINE_MDD = -0.584  # volume-impact
BASELINE_ANNUAL_RET = 0.2155

# HMM使用rolling fit，不需要持久化模型文件


# ──────────────────────────────────────────────────────────────────────────────
# 数据加载函数（与backtest_rsrs_weekly.py一致）
# ──────────────────────────────────────────────────────────────────────────────


def load_factor_values(trade_date: date, conn) -> pd.DataFrame:
    """加载v1.1五因子中性化值。"""
    return pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = %s
             AND factor_name IN (
               'turnover_mean_20', 'volatility_20', 'reversal_20',
               'amihud_20', 'bp_ratio'
             )""",
        conn,
        params=(trade_date,),
    )


def load_universe(trade_date: date, conn) -> set[str]:
    """加载Universe（排除ST/新股/停牌/低流动性）。"""
    df = pd.read_sql(
        """SELECT k.code
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000
        """,
        conn,
        params=(trade_date, trade_date),
    )
    return set(df["code"].tolist())


def load_industry(conn) -> pd.Series:
    """加载行业分类。"""
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
        conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


def load_price_data(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载回测价格数据（含total_mv和volatility_20用于volume-impact滑点）。"""
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount,
                  k.up_limit, k.down_limit,
                  db.turnover_rate,
                  db.total_mv,
                  fv.raw_value AS volatility_20
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           LEFT JOIN factor_values fv ON k.code = fv.code AND k.trade_date = fv.trade_date
                                         AND fv.factor_name = 'volatility_20'
           WHERE k.trade_date BETWEEN %s AND %s
             AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn,
        params=(start_date, end_date),
    )


def load_benchmark(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载基准数据（CSI300）。"""
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )


def load_csi300_history(
    end_date: date, conn, lookback_days: int = 600
) -> tuple[pd.Series, pd.Series]:
    """加载CSI300历史行情（用于regime计算）。

    Returns:
        (closes, volumes) - 收盘价序列和成交量序列（时间升序）
    """
    df = pd.read_sql(
        """SELECT trade_date, close, volume
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date <= %s
           ORDER BY trade_date ASC
           LIMIT %s""",
        conn,
        params=(end_date, lookback_days),
    )
    if df.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    df = df.set_index("trade_date")
    closes = df["close"]
    volumes = df["volume"] if "volume" in df.columns else pd.Series(dtype=float)
    return closes, volumes


# ──────────────────────────────────────────────────────────────────────────────
# 信号生成（三方案共用的信号框架，只有regime_scale不同）
# ──────────────────────────────────────────────────────────────────────────────


def build_signals_for_scheme(
    rebalance_dates: list[date],
    industry: pd.Series,
    conn,
    regime_mode: str,
    hmm_detector: HMMRegimeDetector | None = None,
) -> dict[date, dict[str, float]]:
    """为指定regime方案生成全量目标持仓。

    Args:
        rebalance_dates: 调仓日历
        industry: 行业分类
        conn: 数据库连接
        regime_mode: "none" | "vol_regime" | "hmm_regime"
        hmm_detector: 已训练的HMM检测器（只在hmm_regime时需要）

    Returns:
        {trade_date: {code: weight}} 目标持仓字典
    """
    composer = SignalComposer(V11_SIGNAL_CONFIG)
    builder = PortfolioBuilder(V11_SIGNAL_CONFIG)
    target_portfolios: dict[date, dict[str, float]] = {}
    prev_weights: dict[str, float] = {}

    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values(rd, conn)
        if fv.empty:
            logger.debug(f"[{regime_mode}] {rd} 无因子数据，跳过")
            continue

        universe = load_universe(rd, conn)
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue

        # ── Regime scale计算 ──
        regime_scale = 1.0
        if regime_mode == "vol_regime":
            closes, _ = load_csi300_history(rd, conn, lookback_days=300)
            if len(closes) >= 22:
                try:
                    regime_scale = calc_vol_regime(closes)
                except Exception as e:
                    logger.debug(f"[vol_regime] {rd} 异常: {e}")
        elif regime_mode == "hmm_regime" and hmm_detector is not None:
            closes, _ = load_csi300_history(rd, conn, lookback_days=500)
            if len(closes) >= 253:
                try:
                    result: RegimeResult = hmm_detector.fit_predict(closes)
                    regime_scale = result.scale
                    logger.debug(
                        f"[hmm_regime] {rd} state={result.state}, "
                        f"bear_prob={result.bear_prob:.3f}, "
                        f"scale={regime_scale:.3f}, source={result.source}"
                    )
                except Exception as e:
                    logger.debug(f"[hmm_regime] {rd} 异常: {e}")

        target = builder.build(scores, industry, prev_weights, vol_regime_scale=regime_scale)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

        if (i + 1) % 12 == 0:
            logger.info(
                f"[{regime_mode}] 信号 [{i + 1}/{len(rebalance_dates)}] "
                f"{rd}: {len(target)}只, scale={regime_scale:.3f}"
            )

    logger.info(f"[{regime_mode}] 信号生成完成: {len(target_portfolios)}个调仓日")
    return target_portfolios


# ──────────────────────────────────────────────────────────────────────────────
# 回测与报告
# ──────────────────────────────────────────────────────────────────────────────


def run_backtest(
    target_portfolios: dict[date, dict[str, float]],
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    initial_capital: float,
):
    """运行SimBroker回测，返回结果。"""
    bt_config = BacktestConfig(
        initial_capital=initial_capital,
        top_n=15,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
    )
    backtester = SimpleBacktester(bt_config)
    return backtester.run(target_portfolios, price_data, benchmark_data)


def compute_yearly_breakdown(nav: pd.Series) -> list[dict]:
    """计算年度绩效分解。"""
    rows = []
    for year in sorted({d.year for d in nav.index}):
        year_nav = nav[[d.year == year for d in nav.index]]
        if len(year_nav) < 20:
            continue
        year_ret = year_nav.pct_change().dropna()
        annual_return = float(year_nav.iloc[-1] / year_nav.iloc[0] - 1)
        sharpe = (
            float(year_ret.mean() / year_ret.std() * np.sqrt(252)) if year_ret.std() > 0 else 0.0
        )
        peak = year_nav.expanding().max()
        mdd = float((year_nav - peak).div(peak).min())
        rows.append({"year": year, "annual_return": annual_return, "sharpe": sharpe, "mdd": mdd})
    return rows


def print_comparison_table(results_map: dict[str, object]) -> None:
    """打印三方案对比汇总表。

    Args:
        results_map: {"A_none": report_A, "B_vol_regime": report_B, "C_hmm_regime": report_C}
    """
    print("\n" + "=" * 80)
    print("三方案对比汇总 (v1.1配置, volume-impact滑点)")
    print("=" * 80)
    header = f"{'方案':>20} {'Sharpe':>8} {'MDD':>10} {'年化收益':>10} {'Bootstrap CI':>25}"
    print(header)
    print("-" * 80)

    labels = {
        "A_none": "方案A: 无Regime",
        "B_vol_regime": "方案B: Vol Regime",
        "C_hmm_regime": "方案C: HMM Regime",
    }

    for key, report in results_map.items():
        label = labels.get(key, key)
        sharpe = report.get("sharpe", float("nan"))
        mdd = report.get("max_drawdown", float("nan"))
        ann_ret = report.get("annual_return", float("nan"))
        ci_low = report.get("bootstrap_sharpe_ci_low", float("nan"))
        ci_high = report.get("bootstrap_sharpe_ci_high", float("nan"))
        ci_str = f"[{ci_low:.2f}, {ci_high:.2f}]"

        # 标红：Sharpe vs基线对比
        flag = (
            " +"
            if isinstance(sharpe, float)
            and not np.isnan(sharpe)
            and sharpe >= BASELINE_SHARPE * 0.9
            else " -"
        )

        print(f"{label:>20} {sharpe:>8.3f} {mdd:>10.2%} {ann_ret:>10.2%} {ci_str:>25}{flag}")

    print("-" * 80)
    print(
        f"{'v1.1基线(参考)':>20} {BASELINE_SHARPE:>8.3f} {BASELINE_MDD:>10.2%} {BASELINE_ANNUAL_RET:>10.2%}"
    )
    print("=" * 80)

    # MDD改善判断
    print("\nMDD改善分析（优化目标: MDD > Sharpe）:")
    for key, report in results_map.items():
        mdd = report.get("max_drawdown", float("nan"))
        if not np.isnan(mdd):
            mdd_improvement = mdd - BASELINE_MDD  # 正数=改善（MDD变小）
            label = labels.get(key, key)
            direction = "改善" if mdd_improvement > 0 else "恶化"
            print(f"  {label}: MDD={mdd:.2%}, 相对基线{direction} {abs(mdd_improvement):.2%}")


def print_yearly_comparison(yearly_maps: dict[str, list[dict]]) -> None:
    """打印年度分解对比。"""
    print("\n--- 年度分解对比 ---")
    all_years = sorted(set(row["year"] for rows in yearly_maps.values() for row in rows))

    labels_short = {
        "A_none": "A-无Regime",
        "B_vol_regime": "B-VolRegime",
        "C_hmm_regime": "C-HMMRegime",
    }

    header = f"{'年份':>6}" + "".join(f" {labels_short.get(k, k):>18}" for k in yearly_maps)
    print(header)
    print("-" * (8 + 20 * len(yearly_maps)))

    for year in all_years:
        row_str = f"{year:>6}"
        for key in yearly_maps:
            rows = yearly_maps[key]
            year_data = next((r for r in rows if r["year"] == year), None)
            if year_data:
                s = year_data["sharpe"]
                mdd = year_data["mdd"]
                row_str += f" Sh={s:+.2f}/MDD={mdd:.0%}"
            else:
                row_str += f" {'N/A':>18}"
        print(row_str)


# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="HMM Regime三方案对比回测")
    parser.add_argument("--start", default="2021-01-01", help="回测开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="回测结束日期 (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=1_000_000, help="初始资金")
    parser.add_argument(
        "--scheme",
        choices=["A", "B", "C", "all"],
        default="all",
        help="只跑指定方案 (all=全部)",
    )
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    print("=" * 80)
    print("HMM Regime 三方案对比回测 (2-state rolling fit)")
    print("=" * 80)
    print(f"回测区间: {start} ~ {end}")
    print("HMM: 2-state, rolling fit 252天, 去抖动(prob>0.7, min 5天)")
    print(f"初始资金: {args.capital:,.0f}")
    print("v1.1配置: 5因子等权Top15月度 行业25%")
    print("滑点: volume_impact（与基线一致）")
    print("=" * 80)

    conn = _get_sync_conn()
    t0 = time.time()

    # ── 1. 获取调仓日历 ──
    logger.info("获取月度调仓日历...")
    rebalance_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    # ── 2. 加载行业分类 ──
    industry = load_industry(conn)

    # ── 3. 初始化HMM检测器（rolling fit，每个调仓日refit）──
    hmm_detector: HMMRegimeDetector | None = None
    if args.scheme in ("C", "all"):
        hmm_detector = HMMRegimeDetector(
            n_states=2,
            min_train=252,
            rolling_window=252,
            min_duration=5,
            switch_threshold=0.7,
            random_state=42,
        )
        logger.info("HMM检测器初始化完成（2-state, rolling fit 252天, 去抖动）")

    # ── 4. 生成各方案信号 ──
    results_map: dict = {}
    yearly_maps: dict = {}
    schemes_to_run = (
        ["A_none", "B_vol_regime", "C_hmm_regime"]
        if args.scheme == "all"
        else {
            "A": ["A_none"],
            "B": ["B_vol_regime"],
            "C": ["C_hmm_regime"],
        }[args.scheme]
    )

    scheme_config = {
        "A_none": ("none", None),
        "B_vol_regime": ("vol_regime", None),
        "C_hmm_regime": ("hmm_regime", hmm_detector),
    }

    # ── 5. 加载价格数据（三方案共用）──
    logger.info("加载价格数据...")
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

    for scheme_key in schemes_to_run:
        regime_mode, detector = scheme_config[scheme_key]
        print(f"\n{'─' * 60}")
        print(f"运行 {scheme_key} (regime_mode={regime_mode})...")

        t_scheme = time.time()
        target_portfolios = build_signals_for_scheme(
            rebalance_dates=rebalance_dates,
            industry=industry,
            conn=conn,
            regime_mode=regime_mode,
            hmm_detector=detector,
        )

        if not target_portfolios:
            logger.warning(f"{scheme_key}: 无有效信号，跳过")
            continue

        result = run_backtest(target_portfolios, price_data, benchmark_data, args.capital)
        report = generate_report(result, price_data)
        print_report(report)

        results_map[scheme_key] = report
        yearly_maps[scheme_key] = compute_yearly_breakdown(result.daily_nav)

        elapsed_scheme = time.time() - t_scheme
        logger.info(f"{scheme_key} 完成，耗时 {elapsed_scheme:.0f}s")

    conn.close()

    # ── 6. 汇总对比报告 ──
    if len(results_map) > 1:
        print_comparison_table(results_map)
        print_yearly_comparison(yearly_maps)

    # ── 7. 年度分析（方案C: rolling fit无IS/OOS区分，每年独立评估）──
    if "C_hmm_regime" in results_map:
        print("\n" + "=" * 80)
        print("方案C HMM Regime 年度分析")
        print("=" * 80)
        print("说明: 2-state HMM rolling fit(252天窗口)，每个调仓日用之前数据refit")
        print("      无IS/OOS区分——每年的训练数据都只包含该年之前的历史")

        yearly_c = yearly_maps.get("C_hmm_regime", [])
        for row in yearly_c:
            print(
                f"  {row['year']}: Sharpe={row['sharpe']:+.2f}, "
                f"MDD={row['mdd']:.1%}, 年化={row['annual_return']:.1%}"
            )

    elapsed = time.time() - t0
    logger.info(f"全部完成，总耗时 {elapsed:.0f}s")


if __name__ == "__main__":
    main()
