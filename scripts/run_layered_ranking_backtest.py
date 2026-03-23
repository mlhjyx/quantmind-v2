#!/usr/bin/env python3
"""分层排序回测对比 — 4配置(基线v1.1 vs 分层排序A/B/C)。

背景: 等权合成天花板确认(LL-017), 5因子等权Sharpe=1.054, 加任何因子都降Sharpe。
测试"分层排序"方法 — 不改框架代码, 只改打分逻辑。

配置0(基线v1.1): 5因子等权打分 → Top15 → 月频 → IndCap=25%
配置A(分层排序5因子):
  L1: amihud_20(+1) + turnover_mean_20(-1) → Top30% (流动性筛)
  L2: reversal_20(+1) + volatility_20(-1) → L1中Top20% (质量筛)
  L3: bp_ratio(+1) → L2中Top15 (价值选股)
配置B(分层+PEAD替换bp):
  L1/L2同A, L3: earnings_surprise_car(+1) → Top15
配置C(分层+PEAD+bp混合):
  L1/L2同A, L3: earnings_surprise_car(+1) + bp_ratio(+1) 等权 → Top15

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
from run_pead_backtest import compute_pead_factor_panel, bootstrap_sharpe_ci

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# 分层排序选股逻辑
# ============================================================


def layered_ranking_select(
    factor_wide: pd.DataFrame,
    universe: set[str],
    layer_config: list[dict],
    top_n: int = 15,
) -> pd.Series:
    """分层排序选股。

    Args:
        factor_wide: pivot后的宽表(index=code, columns=factor_name, values=neutral_value)。
        universe: 可交易universe。
        layer_config: 分层配置列表, 每层:
            {
                "factors": [("factor_name", direction), ...],
                "keep_ratio": float (0-1) 或 "top_n" (int, 最后一层)
            }
        top_n: 最终选股数(最后一层用)。

    Returns:
        pd.Series(code→score), 按score降序, 长度=top_n。
    """
    # 从universe开始
    candidates = factor_wide[factor_wide.index.isin(universe)].copy()

    for i, layer in enumerate(layer_config):
        factors = layer["factors"]
        is_last = i == len(layer_config) - 1

        # 计算该层的综合得分
        available = [(f, d) for f, d in factors if f in candidates.columns]
        if not available:
            logger.warning(f"  层{i+1}: 无可用因子, 跳过")
            continue

        # 每个因子的截面zscore(避免量纲问题)
        layer_scores = pd.Series(0.0, index=candidates.index)
        for fname, direction in available:
            vals = candidates[fname].copy()
            # zscore归一化
            mean_v = vals.mean()
            std_v = vals.std()
            if std_v > 0:
                vals = (vals - mean_v) / std_v
            # 方向调整
            vals = vals * direction
            layer_scores += vals / len(available)  # 等权

        layer_scores = layer_scores.dropna()

        if is_last:
            # 最后一层: 取top_n
            layer_scores = layer_scores.sort_values(ascending=False)
            return layer_scores.head(top_n)
        else:
            # 非最后一层: 按keep_ratio筛选
            keep_ratio = layer["keep_ratio"]
            n_keep = max(1, int(len(layer_scores) * keep_ratio))
            layer_scores = layer_scores.sort_values(ascending=False)
            kept_codes = layer_scores.head(n_keep).index
            candidates = candidates.loc[candidates.index.isin(kept_codes)]
            logger.debug(
                f"  层{i+1}: {len(layer_scores)}只→{len(candidates)}只 "
                f"(keep_ratio={keep_ratio})"
            )

    # fallback: 不应该到这里
    return pd.Series(dtype=float)


# ============================================================
# 配置定义
# ============================================================

# 分层配置A: 5因子分层
LAYER_CONFIG_A = [
    {
        # L1: 流动性筛 — amihud(+1, 高非流动性) + turnover(-1, 低换手)
        "factors": [("amihud_20", 1), ("turnover_mean_20", -1)],
        "keep_ratio": 0.30,
    },
    {
        # L2: 质量筛 — reversal(+1, 反转) + volatility(-1, 低波)
        "factors": [("reversal_20", 1), ("volatility_20", -1)],
        "keep_ratio": 0.20,
    },
    {
        # L3: 价值选股 — bp_ratio(+1)
        "factors": [("bp_ratio", 1)],
        "keep_ratio": None,  # 最后一层用top_n
    },
]

# 分层配置B: PEAD替换bp
LAYER_CONFIG_B = [
    {
        "factors": [("amihud_20", 1), ("turnover_mean_20", -1)],
        "keep_ratio": 0.30,
    },
    {
        "factors": [("reversal_20", 1), ("volatility_20", -1)],
        "keep_ratio": 0.20,
    },
    {
        # L3: PEAD选股
        "factors": [("earnings_surprise_car", 1)],
        "keep_ratio": None,
    },
]

# 分层配置C: PEAD + bp混合
LAYER_CONFIG_C = [
    {
        "factors": [("amihud_20", 1), ("turnover_mean_20", -1)],
        "keep_ratio": 0.30,
    },
    {
        "factors": [("reversal_20", 1), ("volatility_20", -1)],
        "keep_ratio": 0.20,
    },
    {
        # L3: PEAD + bp等权
        "factors": [("earnings_surprise_car", 1), ("bp_ratio", 1)],
        "keep_ratio": None,
    },
]


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
    from engines.signal_engine import SignalComposer

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


def run_layered_backtest(
    label: str,
    layer_config: list[dict],
    rebalance_dates: list[date],
    industry: pd.Series,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    conn,
    pead_panel: dict[date, pd.Series] | None = None,
) -> dict:
    """运行分层排序回测。

    Args:
        label: 配置标签。
        layer_config: 分层配置。
        rebalance_dates: 调仓日列表。
        industry: 行业分类。
        price_data: 价格数据。
        benchmark_data: 基准数据。
        conn: DB连接。
        pead_panel: PEAD因子面板(配置B/C需要)。
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

    # 收集所有需要的因子名
    all_factors = set()
    needs_pead = False
    for layer in layer_config:
        for fname, _ in layer["factors"]:
            if fname == "earnings_surprise_car":
                needs_pead = True
            else:
                all_factors.add(fname)

    target_portfolios = {}
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)

        # pivot到宽表
        pivot = fv.pivot_table(
            index="code",
            columns="factor_name",
            values="neutral_value",
            aggfunc="first",
        )

        # 注入PEAD因子(如果需要)
        if needs_pead and pead_panel and rd in pead_panel:
            pead_series = pead_panel[rd]
            # zscore处理PEAD, 与其他因子一致
            pead_mean = pead_series.mean()
            pead_std = pead_series.std()
            if pead_std > 0:
                pead_zscore = (pead_series - pead_mean) / pead_std
            else:
                pead_zscore = pead_series * 0
            pivot["earnings_surprise_car"] = pead_zscore

        # 分层排序选股
        scores = layered_ranking_select(pivot, universe, layer_config, top_n=top_n)
        if scores.empty:
            continue

        # 用PortfolioBuilder加行业约束和换手率约束
        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

        if (i + 1) % 20 == 0:
            logger.info(
                f"  [{label}] 信号 [{i + 1}/{len(rebalance_dates)}] "
                f"{rd}: {len(target)}只"
            )

    logger.info(f"  [{label}] 信号完成: {len(target_portfolios)}个调仓日")

    # 回测
    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    factor_names = []
    for layer in layer_config:
        for fname, _ in layer["factors"]:
            if fname not in factor_names:
                factor_names.append(fname)

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
    """打印4配置对比表。"""
    print("\n" + "=" * 100)
    print("分层排序回测对比 — 4配置")
    print("=" * 100)

    # 整体对比
    print(f"\n{'指标':<25}", end="")
    for s in summaries:
        print(f"  {s['label']:>18}", end="")
    print()
    print("-" * (25 + 20 * len(summaries)))

    rows = [
        ("因子数", "n_factors", "d"),
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
            print(f"  {val:>18{fmt}}", end="")
        print()

    # 年度分解
    print(f"\n{'年度分解':=^100}")
    for year in range(2021, 2026):
        print(f"\n  {year}年:")
        print(f"  {'指标':<22}", end="")
        for s in summaries:
            print(f"  {s['label']:>18}", end="")
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
                    print(f"  {val:>18{fmt}}", end="")
                else:
                    print(f"  {'N/A':>18}", end="")
            print()

    # 增量效果(相对基线)
    baseline = summaries[0]
    print(f"\n{'增量效果(vs 基线v1.1)':=^100}")
    print(f"  {'配置':<22}{'Sharpe增量':>12}{'年化收益增量':>14}{'MDD变化':>12}{'CI下界增量':>14}")
    print(f"  {'-' * 72}")
    for s in summaries[1:]:
        d_sharpe = s["sharpe"] - baseline["sharpe"]
        d_ret = s["ann_return"] - baseline["ann_return"]
        d_mdd = s["mdd"] - baseline["mdd"]
        d_ci = s["bootstrap_ci_low"] - baseline["bootstrap_ci_low"]
        print(
            f"  {s['label']:<22}"
            f"{d_sharpe:>+12.3f}"
            f"{d_ret:>+14.1%}"
            f"{d_mdd:>+12.1%}"
            f"{d_ci:>+14.3f}"
        )

    # 判定
    print(f"\n{'判定':=^100}")
    best = max(summaries, key=lambda s: s["sharpe"])
    print(f"  最高Sharpe: {best['label']} ({best['sharpe']:.3f})")

    # 分层 vs 等权
    config_a = summaries[1] if len(summaries) > 1 else None
    config_b = summaries[2] if len(summaries) > 2 else None
    config_c = summaries[3] if len(summaries) > 3 else None

    if config_a:
        if config_a["sharpe"] > baseline["sharpe"] + 0.05:
            print(f"  分层排序(5F) vs 等权: Sharpe +{config_a['sharpe'] - baseline['sharpe']:.3f}, 分层有效")
        elif abs(config_a["sharpe"] - baseline["sharpe"]) <= 0.05:
            print(f"  分层排序(5F) vs 等权: Sharpe差异<0.05, 分层对这组因子无增量")
        else:
            print(f"  分层排序(5F) vs 等权: Sharpe {config_a['sharpe'] - baseline['sharpe']:+.3f}, 等权更优")

    if config_b:
        if config_b["sharpe"] > baseline["sharpe"] + 0.05:
            print(
                f"  分层+PEAD vs 等权基线: Sharpe +{config_b['sharpe'] - baseline['sharpe']:.3f}, "
                f"分层排序有效, PEAD被释放"
            )
        else:
            print(
                f"  分层+PEAD vs 等权基线: Sharpe {config_b['sharpe'] - baseline['sharpe']:+.3f}, "
                f"PEAD在分层中未释放alpha"
            )

    if config_c:
        if config_c["sharpe"] > baseline["sharpe"] + 0.05:
            print(
                f"  分层+PEAD+bp vs 等权基线: Sharpe +{config_c['sharpe'] - baseline['sharpe']:.3f}, "
                f"混合L3有效"
            )
        elif config_c and config_b:
            if config_c["sharpe"] > config_b["sharpe"]:
                print(f"  混合L3 > 纯PEAD L3: bp_ratio在L3有增量")
            else:
                print(f"  混合L3 <= 纯PEAD L3: bp在L3无增量")

    print()


# ============================================================
# 主程序
# ============================================================


def main():
    """分层排序回测主程序。"""
    print("\n" + "=" * 60)
    print("  分层排序回测对比 — 4配置")
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

    # 2. 计算PEAD因子面板(配置B/C需要)
    pead_panel = compute_pead_factor_panel(conn, start, end)
    if not pead_panel:
        logger.warning("PEAD因子面板为空, 配置B/C将跳过")

    summaries = []

    # ---- 配置0: 基线v1.1(等权合成) ----
    logger.info("\n[配置0] 基线v1.1 — 5因子等权")
    s0 = run_baseline_backtest(
        "0:基线v1.1(等权)",
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
    )
    summaries.append(s0)

    # ---- 配置A: 分层排序5因子 ----
    logger.info("\n[配置A] 分层排序5因子")
    sa = run_layered_backtest(
        "A:分层5F",
        LAYER_CONFIG_A,
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
    )
    summaries.append(sa)

    # ---- 配置B: 分层+PEAD ----
    if pead_panel:
        logger.info("\n[配置B] 分层+PEAD替换bp")
        sb = run_layered_backtest(
            "B:分层+PEAD",
            LAYER_CONFIG_B,
            rebalance_dates,
            industry,
            price_data,
            benchmark_data,
            conn,
            pead_panel=pead_panel,
        )
        summaries.append(sb)
    else:
        logger.warning("跳过配置B(无PEAD数据)")

    # ---- 配置C: 分层+PEAD+bp ----
    if pead_panel:
        logger.info("\n[配置C] 分层+PEAD+bp混合")
        sc = run_layered_backtest(
            "C:分层+PEAD+bp",
            LAYER_CONFIG_C,
            rebalance_dates,
            industry,
            price_data,
            benchmark_data,
            conn,
            pead_panel=pead_panel,
        )
        summaries.append(sc)
    else:
        logger.warning("跳过配置C(无PEAD数据)")

    conn.close()

    # 输出对比
    print_comparison(summaries)

    elapsed = time.time() - t0
    logger.info(f"回测完成, 总耗时 {elapsed:.0f}s")


if __name__ == "__main__":
    main()
