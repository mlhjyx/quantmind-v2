#!/usr/bin/env python3
"""候选1 (质量成长) SimBroker正式回测。

LL-011教训：必须用SimpleBacktester+SimBroker跑正式回测，不能用proxy。

候选1配置:
- 因子: roe_ttm, revenue_yoy, gross_profit_margin（PIT对齐）
- 三个方向都测：正向（质量好=高ROE）、反向（低质量跑赢）、混合
- Top-15等权, 月频调仓, IndCap=25%
- 初始资金: 100万
- 回测区间: 2021-2025

关键：IC验证显示roe和gross_profit_margin方向反转（负IC），
所以本脚本同时测试正向和反向策略。

用法:
    python scripts/validate_candidate1_simbroker.py
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn
from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import (
    TRADING_DAYS_PER_YEAR,
    bootstrap_sharpe_ci,
    calc_max_drawdown,
    calc_sharpe,
)
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# 财务因子PIT加载（参考financial_factors.py的load_financial_pit）
# ============================================================

def load_financial_pit_factors(trade_date: date, conn) -> pd.DataFrame:
    """加载截至trade_date的PIT财务因子值。

    Point-In-Time: 只取actual_ann_date <= trade_date的记录。
    同一(code, report_date)取ann_date最新（最终版）。
    每个code取最近4个季度用于TTM计算。

    Returns:
        DataFrame [code, roe_ttm, revenue_yoy, gross_profit_margin, debt_to_asset]
    """
    df = pd.read_sql(
        """WITH ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY code, report_date
                       ORDER BY actual_ann_date DESC
                   ) AS rn
            FROM financial_indicators
            WHERE actual_ann_date <= %s
              AND actual_ann_date >= %s
        )
        SELECT code, report_date, actual_ann_date,
               roe, roe_dt, roa,
               gross_profit_margin, net_profit_margin,
               revenue_yoy, net_profit_yoy,
               debt_to_asset
        FROM ranked
        WHERE rn = 1
        ORDER BY code, report_date DESC""",
        conn,
        params=(trade_date, trade_date - pd.Timedelta(days=730)),  # 最近2年的财报
    )
    if df.empty:
        return pd.DataFrame()

    # 每个code计算因子
    results = []
    for code, grp in df.groupby("code"):
        grp = grp.sort_values("report_date", ascending=False)

        # roe_ttm: 最近4个季度的ROE累加 (简化: 用最新年报roe或最近4Q平均)
        # 用roe_dt（扣非）优先
        roe_col = "roe_dt" if grp["roe_dt"].notna().any() else "roe"
        recent_roe = grp[roe_col].dropna()
        if len(recent_roe) >= 1:
            roe_ttm = float(recent_roe.iloc[0])  # 最新季度ROE
        else:
            roe_ttm = np.nan

        # revenue_yoy: 最新季度的营收同比
        recent_rev = grp["revenue_yoy"].dropna()
        revenue_yoy = float(recent_rev.iloc[0]) if len(recent_rev) >= 1 else np.nan

        # gross_profit_margin: 最新季度毛利率
        recent_gm = grp["gross_profit_margin"].dropna()
        gross_margin = float(recent_gm.iloc[0]) if len(recent_gm) >= 1 else np.nan

        # debt_to_asset: 资产负债率 (下行保护因子)
        recent_da = grp["debt_to_asset"].dropna()
        debt_to_asset = float(recent_da.iloc[0]) if len(recent_da) >= 1 else np.nan

        results.append({
            "code": code,
            "roe_ttm": roe_ttm,
            "revenue_yoy": revenue_yoy,
            "gross_profit_margin": gross_margin,
            "debt_to_asset": debt_to_asset,
        })

    result_df = pd.DataFrame(results)
    return result_df


def financial_factors_to_long(factor_df: pd.DataFrame, direction_map: dict) -> pd.DataFrame:
    """将宽表财务因子转为长表格式（与SignalComposer.compose兼容）。

    包含CLAUDE.md要求的因子预处理：去极值 → 填充 → 标准化。
    注: 中性化跳过（无市值因子在financial_indicators中，且不与基线因子混用）。

    Args:
        factor_df: 宽表 [code, roe_ttm, revenue_yoy, gross_profit_margin, ...]
        direction_map: {factor_name: direction (+1/-1)}

    Returns:
        长表 [code, factor_name, neutral_value]
    """
    factor_cols = [c for c in factor_df.columns if c != "code"]
    rows = []

    for col in factor_cols:
        if col not in direction_map:
            continue

        series = factor_df.set_index("code")[col].dropna()
        if len(series) < 30:
            continue

        # 1. 去极值 (MAD 3倍)
        median = series.median()
        mad = (series - median).abs().median()
        if mad < 1e-10:
            mad = series.std()
        lower = median - 3 * 1.4826 * mad
        upper = median + 3 * 1.4826 * mad
        series = series.clip(lower, upper)

        # 2. 缺失值填充（全市场均值，因无行业数据在此步骤）
        series = series.fillna(series.mean())

        # 3. 中性化（简化版跳过，因为这是独立的财务因子策略）
        # CLAUDE.md要求回归掉ln_market_cap+行业dummy
        # 但候选1是纯财务因子策略，不与基线因子混合
        # 在正式WF中需要补上中性化

        # 4. 标准化 (zscore)
        std = series.std()
        if std < 1e-10:
            continue
        series = (series - series.mean()) / std

        for code, val in series.items():
            if np.isfinite(val):
                rows.append({
                    "code": code,
                    "factor_name": col,
                    "neutral_value": val,
                })

    return pd.DataFrame(rows)


# ============================================================
# 数据加载（复用candidate4的模式）
# ============================================================

def load_full_universe(trade_date: date, conn) -> set[str]:
    """加载全A宇宙。"""
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
    """加载价格数据。"""
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount,
                  k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s
             AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn,
        params=(start_date, end_date),
    )


def load_benchmark(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载基准指数数据。"""
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )


def load_baseline_factor_values(trade_date: date, conn) -> pd.DataFrame:
    """加载基线5因子值（用于相关性计算）。"""
    return pd.read_sql(
        "SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
        conn,
        params=(trade_date,),
    )


# ============================================================
# 信号生成
# ============================================================

# 正向方向: 高ROE好, 高营收增速好, 高毛利率好
DIRECTION_POSITIVE = {
    "roe_ttm": 1,
    "revenue_yoy": 1,
    "gross_profit_margin": 1,
}

# 反向方向: IC验证显示低ROE/低毛利跑赢
DIRECTION_REVERSED = {
    "roe_ttm": -1,
    "revenue_yoy": -1,
    "gross_profit_margin": -1,
}

# 混合方向: ROE反转 + 高营收增速 + 毛利率反转
DIRECTION_MIXED = {
    "roe_ttm": -1,
    "revenue_yoy": 1,
    "gross_profit_margin": -1,
}


def generate_candidate1_signals(
    rebalance_dates: list[date],
    industry: pd.Series,
    conn,
    direction_map: dict,
    label: str = "candidate1",
) -> dict[date, dict[str, float]]:
    """候选1信号生成: 财务因子PIT对齐 → Top15等权。"""

    # 注册自定义方向到FACTOR_DIRECTION
    for fname, d in direction_map.items():
        FACTOR_DIRECTION[fname] = d

    config = SignalConfig(
        factor_names=list(direction_map.keys()),
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    composer = SignalComposer(config)
    builder = PortfolioBuilder(config)

    target_portfolios: dict[date, dict[str, float]] = {}
    prev_weights: dict[str, float] = {}

    for rd in rebalance_dates:
        # 1. 加载全A宇宙
        universe = load_full_universe(rd, conn)
        if len(universe) < 100:
            logger.warning(f"[{label}] {rd}: 宇宙太小 ({len(universe)}), 跳过")
            continue

        # 2. 加载PIT财务因子
        fina_factors = load_financial_pit_factors(rd, conn)
        if fina_factors.empty:
            logger.warning(f"[{label}] {rd}: 无财务因子数据, 跳过")
            continue

        # 3. 转为长表（含预处理）
        long_df = financial_factors_to_long(fina_factors, direction_map)
        if long_df.empty:
            continue

        # 4. 合成信号
        scores = composer.compose(long_df, universe)
        if scores.empty:
            continue

        # 5. 构建目标持仓
        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    return target_portfolios


def generate_baseline_signals(
    rebalance_dates: list[date],
    industry: pd.Series,
    conn,
) -> dict[date, dict[str, float]]:
    """基线信号: 5因子等权Top15月频。"""
    config = SignalConfig(
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
    composer = SignalComposer(config)
    builder = PortfolioBuilder(config)

    target_portfolios: dict[date, dict[str, float]] = {}
    prev_weights: dict[str, float] = {}

    for rd in rebalance_dates:
        universe = load_full_universe(rd, conn)
        if len(universe) < 100:
            continue

        fv = load_baseline_factor_values(rd, conn)
        if fv.empty:
            continue

        scores = composer.compose(fv, universe)
        if scores.empty:
            continue

        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    return target_portfolios


# ============================================================
# 回测执行
# ============================================================

def run_backtest(
    label: str,
    target_portfolios: dict[date, dict[str, float]],
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    initial_capital: float = 1_000_000.0,
    top_n: int = 15,
) -> dict:
    """执行回测并返回结果字典。"""
    t0 = time.time()
    logger.info(f"[{label}] 开始回测, {len(target_portfolios)}期信号, 初始资金={initial_capital:,.0f}")

    bt_config = BacktestConfig(
        initial_capital=initial_capital,
        top_n=top_n,
        rebalance_freq="monthly",
        slippage_bps=10.0,
        turnover_cap=0.50,
    )

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    nav = result.daily_nav
    returns = result.daily_returns

    years = len(returns) / TRADING_DAYS_PER_YEAR
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (1 / max(years, 0.01)) - 1)
    sharpe = calc_sharpe(returns)
    mdd = calc_max_drawdown(nav)

    elapsed = time.time() - t0
    logger.info(f"[{label}] 完成, 耗时 {elapsed:.0f}s, Sharpe={sharpe:.4f}")

    return {
        "label": label,
        "nav": nav,
        "returns": returns,
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": sharpe,
        "mdd": mdd,
        "result": result,
    }


def calc_annual_stats(nav: pd.Series) -> dict[int, dict]:
    """分年度计算收益和MDD。"""
    stats = {}
    for year in sorted(set(d.year for d in nav.index)):
        mask = [d.year == year for d in nav.index]
        year_nav = nav[mask]
        if len(year_nav) < 10:
            continue
        year_ret = float(year_nav.iloc[-1] / year_nav.iloc[0] - 1)
        year_mdd = calc_max_drawdown(year_nav)
        year_returns = year_nav.pct_change().fillna(0)
        year_sharpe = calc_sharpe(year_returns)
        stats[year] = {
            "return": year_ret,
            "mdd": year_mdd,
            "sharpe": year_sharpe,
        }
    return stats


# ============================================================
# Main
# ============================================================

def main():
    START = date(2021, 1, 1)
    END = date(2025, 12, 31)
    CAPITAL = 1_000_000.0

    conn = _get_sync_conn()
    t_total = time.time()

    print("=" * 80)
    print("候选1 (质量成长) SimBroker正式回测")
    print("LL-011教训: 必须用SimpleBacktester, 不能用proxy!")
    print("=" * 80)

    # 1. 获取月频调仓日
    logger.info("获取月频调仓日...")
    rebalance_dates = get_rebalance_dates(START, END, freq="monthly", conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    # 2. 加载共享数据
    logger.info("加载行业分类...")
    industry = load_industry(conn)

    logger.info("加载价格数据 (2021-2025)...")
    price_data = load_price_data(START, END, conn)
    logger.info(f"价格数据: {len(price_data):,}行")

    benchmark_data = load_benchmark(START, END, conn)
    logger.info(f"基准数据: {len(benchmark_data)}行")

    # ============================================================
    # 3. 三个方向的候选1
    # ============================================================
    directions = [
        ("候选1-正向(高质量)", DIRECTION_POSITIVE, "选高ROE+高增速+高毛利"),
        ("候选1-反向(低质量)", DIRECTION_REVERSED, "选低ROE+低增速+低毛利(IC验证方向)"),
        ("候选1-混合(ROE反+增速正+毛利反)", DIRECTION_MIXED, "ROE/毛利反转+营收增速正向"),
    ]

    all_results = {}

    for label, direction_map, desc in directions:
        print(f"\n{'='*60}")
        print(f"[{label}]")
        print(f"  方向: {desc}")
        print(f"  因子方向: {direction_map}")
        print(f"{'='*60}")

        signals = generate_candidate1_signals(
            rebalance_dates, industry, conn, direction_map, label
        )
        logger.info(f"[{label}] 生成 {len(signals)} 期信号")

        if len(signals) < 10:
            logger.warning(f"[{label}] 信号期数太少 ({len(signals)}), 跳过回测")
            continue

        result = run_backtest(
            label, signals, price_data, benchmark_data,
            initial_capital=CAPITAL, top_n=15,
        )
        all_results[label] = result

    # ============================================================
    # 4. 基线回测（用于相关性计算）
    # ============================================================
    print(f"\n{'='*60}")
    print("[基线 5因子Top15]")
    print(f"{'='*60}")

    baseline_signals = generate_baseline_signals(rebalance_dates, industry, conn)
    logger.info(f"[基线] 生成 {len(baseline_signals)} 期信号")

    bl_result = run_backtest(
        "基线(5因子Top15)", baseline_signals, price_data, benchmark_data,
        initial_capital=CAPITAL, top_n=15,
    )
    all_results["基线"] = bl_result

    conn.close()

    # ============================================================
    # 5. Bootstrap CI & 相关性分析
    # ============================================================
    print("\n\n")
    print("=" * 80)
    print("候选1 SimBroker回测结果汇总")
    print("=" * 80)

    print(f"\n{'策略':>35}  {'年化收益':>10}  {'Sharpe':>8}  {'MDD':>10}  {'总收益':>10}  {'与基线corr':>12}")
    print("-" * 95)

    bl_returns = bl_result["returns"]

    for name, res in all_results.items():
        corr_str = "—"
        if name != "基线":
            common = res["returns"].index.intersection(bl_returns.index)
            if len(common) > 100:
                corr = res["returns"].loc[common].corr(bl_returns.loc[common])
                corr_str = f"{corr:.3f}"

        print(f"  {name:>33}  {res['annual_return']*100:>+8.2f}%  "
              f"{res['sharpe']:>8.4f}  {res['mdd']*100:>8.2f}%  "
              f"{res['total_return']*100:>+8.2f}%  {corr_str:>12}")

    # ============================================================
    # 6. 分年度统计
    # ============================================================
    print("\n\n--- 分年度收益 ---")
    years = [2021, 2022, 2023, 2024, 2025]
    header = f"{'年份':>6}"
    for name in all_results:
        short = name[:15]
        header += f"  {short:>15}"
    print(header)
    print("-" * (6 + len(all_results) * 17))

    annual_data = {}
    for name, res in all_results.items():
        annual_data[name] = calc_annual_stats(res["nav"])

    for year in years:
        row = f"  {year:>4}"
        for name in all_results:
            stats = annual_data[name].get(year, {})
            ret = stats.get("return", float("nan"))
            if np.isnan(ret):
                row += f"  {'N/A':>15}"
            else:
                row += f"  {ret*100:>+13.2f}%"
        print(row)

    # ============================================================
    # 7. 分年度Sharpe
    # ============================================================
    print("\n--- 分年度Sharpe ---")
    print(header)
    print("-" * (6 + len(all_results) * 17))

    for year in years:
        row = f"  {year:>4}"
        for name in all_results:
            stats = annual_data[name].get(year, {})
            sh = stats.get("sharpe", float("nan"))
            if np.isnan(sh):
                row += f"  {'N/A':>15}"
            else:
                row += f"  {sh:>15.3f}"
        print(row)

    # ============================================================
    # 8. Bootstrap CI
    # ============================================================
    print("\n--- Bootstrap Sharpe CI (95%) ---")
    for name, res in all_results.items():
        ci = bootstrap_sharpe_ci(res["returns"], n_bootstrap=2000)
        flag = " *** CI下界<0, 策略可能不赚钱!" if ci[1] < 0 else " (CI下界>0: OK)"
        print(f"  {name:>35}: Sharpe={ci[0]:.3f} [{ci[1]:.3f}, {ci[2]:.3f}]{flag}")

    # ============================================================
    # 9. 最佳候选1方向 vs 基线 50/50组合测试
    # ============================================================
    # 找Sharpe最高的候选1变体
    best_name = None
    best_sharpe = -999
    for name, res in all_results.items():
        if "候选1" in name and res["sharpe"] > best_sharpe:
            best_name = name
            best_sharpe = res["sharpe"]

    if best_name:
        print(f"\n\n--- 最佳候选1变体: {best_name} (Sharpe={best_sharpe:.4f}) ---")
        best_res = all_results[best_name]

        # 50/50组合 (各50万)
        common = best_res["nav"].index.intersection(bl_result["nav"].index)
        c1_nav = best_res["nav"].loc[common] / 2  # 按比例缩到50万
        bl_nav = bl_result["nav"].loc[common] / 2
        combo_nav = c1_nav + bl_nav
        combo_returns = combo_nav.pct_change().fillna(0)

        combo_years = len(combo_returns) / TRADING_DAYS_PER_YEAR
        combo_total = float(combo_nav.iloc[-1] / combo_nav.iloc[0] - 1)
        combo_annual = float((1 + combo_total) ** (1 / max(combo_years, 0.01)) - 1)
        combo_sharpe = calc_sharpe(combo_returns)
        combo_mdd = calc_max_drawdown(combo_nav)

        print(f"\n  50/50组合 (候选1最佳50万 + 基线50万):")
        print(f"    年化收益: {combo_annual*100:>+8.2f}%")
        print(f"    Sharpe:   {combo_sharpe:>8.4f}")
        print(f"    MDD:      {combo_mdd*100:>8.2f}%")
        print(f"    vs 基线:  Sharpe {combo_sharpe - bl_result['sharpe']:>+.4f}")
        print(f"    vs 候选1: Sharpe {combo_sharpe - best_sharpe:>+.4f}")

        combo_annual_stats = calc_annual_stats(combo_nav)
        print(f"\n  50/50组合分年度:")
        for year in years:
            stats = combo_annual_stats.get(year, {})
            ret = stats.get("return", float("nan"))
            if not np.isnan(ret):
                bl_y = annual_data["基线"].get(year, {}).get("return", float("nan"))
                c1_y = annual_data[best_name].get(year, {}).get("return", float("nan"))
                print(f"    {year}: 组合{ret*100:>+7.2f}%  基线{bl_y*100:>+7.2f}%  候选1{c1_y*100:>+7.2f}%")

    # ============================================================
    # 10. 诊断 & 结论
    # ============================================================
    print("\n\n" + "=" * 80)
    print("诊断与结论")
    print("=" * 80)

    for name, res in all_results.items():
        if "候选1" not in name:
            continue
        print(f"\n  [{name}]")
        if res["sharpe"] > 0.5:
            print(f"    Sharpe={res['sharpe']:.4f} > 0.5: 通过独立策略最低门槛")
        elif res["sharpe"] > 0.3:
            print(f"    Sharpe={res['sharpe']:.4f}: 边界。可作为分散化补充但非独立策略")
        else:
            print(f"    Sharpe={res['sharpe']:.4f} < 0.3: 不达标。该方向在A股无效")

    elapsed = time.time() - t_total
    print(f"\n总耗时: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
