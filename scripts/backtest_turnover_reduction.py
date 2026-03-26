#!/usr/bin/env python3
"""换手率降低方案 A/B/C 回测对比。

目标: 年化换手率 < 300%, Sharpe >= 0.869
基线: v1.1 5因子等权 Top15 月度 行业25%

方案A: 限制最大换仓数 (K=3,5,7)
方案B: Turnover Penalty (lambda=0.1,0.2,0.5,1.0)
方案C: 最大重叠选股 (候选池Top20/25, 从中选overlap最大的15只)

输出: 对比表 含 Sharpe, Sharpe CI, MDD, 年化换手率, vs基线p-value
"""

import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "backend"))
sys.path.insert(0, str(project_root / "scripts"))

import numpy as np
import pandas as pd

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import (
    TRADING_DAYS_PER_YEAR,
    bootstrap_sharpe_ci,
    calc_annual_breakdown,
    calc_max_drawdown,
    calc_sharpe,
)
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalConfig,
    get_rebalance_dates,
)
from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────

START_DATE = date(2021, 1, 1)
END_DATE = date(2025, 12, 31)
INITIAL_CAPITAL = 1_000_000.0

FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]


# ─────────────────────────────────────────────
# 数据加载 (复用 backtest_7factor_comparison 模式)
# ─────────────────────────────────────────────

def load_factor_values_for_date(trade_date: date, conn) -> pd.DataFrame:
    return pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = %s
             AND factor_name IN (
               'turnover_mean_20','volatility_20','reversal_20',
               'amihud_20','bp_ratio'
             )""",
        conn,
        params=(trade_date,),
    )


def load_universe(trade_date: date, conn) -> set[str]:
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


def load_price_data(start_date: date, end_date: date, conn) -> pd.DataFrame:
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
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )


def load_industry(conn) -> pd.Series:
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
        conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


# ─────────────────────────────────────────────
# 信号合成 (基线等权)
# ─────────────────────────────────────────────

def build_scores(factor_df: pd.DataFrame, universe: set[str]) -> pd.Series:
    """等权composite score，返回排序后的Series。"""
    pivot = factor_df.pivot_table(
        index="code", columns="factor_name", values="neutral_value", aggfunc="first",
    )
    if universe:
        pivot = pivot[pivot.index.isin(universe)]

    available = [f for f in FACTORS if f in pivot.columns]
    if not available:
        return pd.Series(dtype=float)

    pivot = pivot[available].copy()
    for fname in available:
        direction = FACTOR_DIRECTION.get(fname, 1)
        if direction == -1:
            pivot[fname] = -pivot[fname]

    composite = pivot[available].mean(axis=1)
    return composite.sort_values(ascending=False)


# ─────────────────────────────────────────────
# 方案A: 限制最大换仓数
# ─────────────────────────────────────────────

def select_with_max_replace(
    scores: pd.Series,
    industry: pd.Series,
    prev_codes: set[str],
    top_n: int = 15,
    industry_cap: float = 0.25,
    max_replace: int = 5,
) -> dict[str, float]:
    """每月最多换K只，其余保留。

    1. 选Top-N候选 (含行业约束)
    2. 计算新旧差集
    3. 如果新增>max_replace，只换排名最差的max_replace只旧持仓
    """
    max_per_industry = int(top_n * industry_cap)

    # Step 1: 选出无约束Top-N
    candidates = []
    ind_count = {}
    for code in scores.index:
        if len(candidates) >= top_n * 2:  # 候选池放宽
            break
        ind = industry.get(code, "其他")
        cnt = ind_count.get(ind, 0)
        if cnt >= max_per_industry:
            continue
        candidates.append(code)
        ind_count[ind] = cnt + 1

    if not candidates:
        return {}

    if not prev_codes:
        # 初始建仓: 直接选Top-N
        selected = candidates[:top_n]
        weight = 1.0 / len(selected)
        return {c: weight for c in selected}

    # Step 2: 分离保留和替换
    new_top_n = set(candidates[:top_n])
    to_sell = prev_codes - new_top_n  # 旧持仓中不在新Top-N的
    to_buy = new_top_n - prev_codes   # 新Top-N中不在旧持仓的

    if len(to_sell) <= max_replace:
        # 换的不多，直接用新Top-N
        selected = list(new_top_n)
    else:
        # 换的太多: 只卖排名最差的max_replace只
        # 对旧持仓按score排名，卖最差的max_replace只
        old_in_scores = {c: scores.get(c, -999) for c in prev_codes}
        sorted_old = sorted(old_in_scores.items(), key=lambda x: x[1])
        worst_to_sell = set(c for c, _ in sorted_old[:max_replace])

        # 保留: 旧持仓中不卖的
        keep = prev_codes - worst_to_sell
        # 新增: 从候选池中按score排序，补到top_n
        remaining_candidates = [c for c in candidates if c not in keep]
        need = top_n - len(keep)
        # 行业约束重新检查
        ind_count_keep = {}
        for c in keep:
            ind = industry.get(c, "其他")
            ind_count_keep[ind] = ind_count_keep.get(ind, 0) + 1

        new_adds = []
        for c in remaining_candidates:
            if len(new_adds) >= need:
                break
            ind = industry.get(c, "其他")
            cnt = ind_count_keep.get(ind, 0)
            if cnt >= max_per_industry:
                continue
            new_adds.append(c)
            ind_count_keep[ind] = cnt + 1

        selected = list(keep) + new_adds

    if not selected:
        return {}

    weight = 1.0 / len(selected)
    return {c: weight for c in selected}


# ─────────────────────────────────────────────
# 方案B: Turnover Penalty
# ─────────────────────────────────────────────

def select_with_turnover_penalty(
    scores: pd.Series,
    industry: pd.Series,
    prev_codes: set[str],
    top_n: int = 15,
    industry_cap: float = 0.25,
    lam: float = 0.5,
) -> dict[str, float]:
    """综合得分 = 因子zscore - lambda * (不在当前持仓)。

    已持有的股票得到加分(penalty=0)，新股票被扣lambda。
    """
    max_per_industry = int(top_n * industry_cap)

    # 调整分数
    adjusted = scores.copy()
    if prev_codes:
        # zscore标准化scores以使lambda有可比意义
        std = scores.std()
        if std > 1e-10:
            adjusted = (scores - scores.mean()) / std
        # 不在持仓中的扣分
        for code in adjusted.index:
            if code not in prev_codes:
                adjusted[code] -= lam

    adjusted = adjusted.sort_values(ascending=False)

    # 选Top-N (行业约束)
    selected = []
    ind_count = {}
    for code in adjusted.index:
        if len(selected) >= top_n:
            break
        ind = industry.get(code, "其他")
        cnt = ind_count.get(ind, 0)
        if cnt >= max_per_industry:
            continue
        selected.append(code)
        ind_count[ind] = cnt + 1

    if not selected:
        return {}

    weight = 1.0 / len(selected)
    return {c: weight for c in selected}


# ─────────────────────────────────────────────
# 方案C: 最大重叠选股
# ─────────────────────────────────────────────

def select_with_max_overlap(
    scores: pd.Series,
    industry: pd.Series,
    prev_codes: set[str],
    top_n: int = 15,
    industry_cap: float = 0.25,
    pool_size: int = 20,
) -> dict[str, float]:
    """先选Top-pool_size候选池，从中选与当前持仓overlap最大的top_n只。"""
    max_per_industry = int(top_n * industry_cap)

    # Step 1: 选候选池 (行业约束)
    pool = []
    ind_count = {}
    for code in scores.index:
        if len(pool) >= pool_size:
            break
        ind = industry.get(code, "其他")
        cnt = ind_count.get(ind, 0)
        if cnt >= max_per_industry:
            continue
        pool.append(code)
        ind_count[ind] = cnt + 1

    if not pool:
        return {}

    if not prev_codes:
        selected = pool[:top_n]
        weight = 1.0 / len(selected)
        return {c: weight for c in selected}

    # Step 2: 优先选overlap
    overlap = [c for c in pool if c in prev_codes]
    non_overlap = [c for c in pool if c not in prev_codes]

    # 行业约束重新检查 (overlap优先)
    selected = []
    ind_count2 = {}
    for c in overlap:
        if len(selected) >= top_n:
            break
        ind = industry.get(c, "其他")
        cnt = ind_count2.get(ind, 0)
        if cnt >= max_per_industry:
            continue
        selected.append(c)
        ind_count2[ind] = cnt + 1

    # 补充non-overlap
    for c in non_overlap:
        if len(selected) >= top_n:
            break
        ind = industry.get(c, "其他")
        cnt = ind_count2.get(ind, 0)
        if cnt >= max_per_industry:
            continue
        selected.append(c)
        ind_count2[ind] = cnt + 1

    if not selected:
        return {}

    weight = 1.0 / len(selected)
    return {c: weight for c in selected}


# ─────────────────────────────────────────────
# 回测框架
# ─────────────────────────────────────────────

def generate_portfolios(
    rebalance_dates: list[date],
    industry: pd.Series,
    conn,
    method: str = "baseline",
    **kwargs,
) -> dict[date, dict[str, float]]:
    """生成各方案的target_portfolios。

    method:
        "baseline" - 标准PortfolioBuilder
        "max_replace" - 方案A
        "turnover_penalty" - 方案B
        "max_overlap" - 方案C
    """
    sig_config = SignalConfig(
        factor_names=FACTORS,
        top_n=PAPER_TRADING_CONFIG.top_n,
        rebalance_freq=PAPER_TRADING_CONFIG.rebalance_freq,
        industry_cap=PAPER_TRADING_CONFIG.industry_cap,
    )
    builder = PortfolioBuilder(sig_config)

    target_portfolios = {}
    prev_weights = {}
    prev_codes: set[str] = set()

    for rd in rebalance_dates:
        fv = load_factor_values_for_date(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)
        scores = build_scores(fv, universe)
        if scores.empty:
            continue

        if method == "baseline":
            target = builder.build(scores, industry, prev_weights)
        elif method == "max_replace":
            target = select_with_max_replace(
                scores, industry, prev_codes,
                top_n=sig_config.top_n,
                industry_cap=sig_config.industry_cap,
                max_replace=kwargs.get("max_replace", 5),
            )
        elif method == "turnover_penalty":
            target = select_with_turnover_penalty(
                scores, industry, prev_codes,
                top_n=sig_config.top_n,
                industry_cap=sig_config.industry_cap,
                lam=kwargs.get("lam", 0.5),
            )
        elif method == "max_overlap":
            target = select_with_max_overlap(
                scores, industry, prev_codes,
                top_n=sig_config.top_n,
                industry_cap=sig_config.industry_cap,
                pool_size=kwargs.get("pool_size", 20),
            )
        else:
            raise ValueError(f"Unknown method: {method}")

        if target:
            target_portfolios[rd] = target
            prev_weights = target
            prev_codes = set(target.keys())

    return target_portfolios


def run_single_backtest(
    target_portfolios: dict,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    label: str = "",
) -> dict:
    """运行单次回测并计算所有指标。"""
    bt_config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        top_n=PAPER_TRADING_CONFIG.top_n,
        rebalance_freq=PAPER_TRADING_CONFIG.rebalance_freq,
        slippage_bps=10.0,
    )
    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    nav = result.daily_nav
    returns = result.daily_returns
    sharpe, ci_lo, ci_hi = bootstrap_sharpe_ci(returns, n_bootstrap=2000)
    mdd = calc_max_drawdown(nav)

    # 年化换手率
    if not result.turnover_series.empty:
        avg_monthly = result.turnover_series.mean()
        annual_turn = avg_monthly * 12
    else:
        annual_turn = 0.0

    # 年度分解
    bench_nav = result.benchmark_nav
    breakdown = calc_annual_breakdown(nav, bench_nav)

    logger.info(f"[{label}] Sharpe={sharpe:.3f} [{ci_lo:.3f},{ci_hi:.3f}], "
                f"MDD={mdd:.2%}, Turnover={annual_turn:.0%}")

    return {
        "label": label,
        "result": result,
        "sharpe": sharpe,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "mdd": mdd,
        "annual_turnover": annual_turn,
        "breakdown": breakdown,
        "returns": returns,
        "nav": nav,
    }


def paired_bootstrap_pvalue(
    returns_a: pd.Series,
    returns_b: pd.Series,
    n_bootstrap: int = 5000,
    seed: int = 42,
) -> float:
    """Paired bootstrap p-value (双侧)。"""
    common_idx = returns_a.index.intersection(returns_b.index)
    ra = returns_a.loc[common_idx].values
    rb = returns_b.loc[common_idx].values

    obs_diff = calc_sharpe(pd.Series(rb)) - calc_sharpe(pd.Series(ra))

    rng = np.random.RandomState(seed)
    n = len(ra)
    diffs = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        sa = calc_sharpe(pd.Series(ra[idx]))
        sb = calc_sharpe(pd.Series(rb[idx]))
        diffs[i] = sb - sa

    p_two_sided = float(np.mean(np.abs(diffs) >= abs(obs_diff)))
    return p_two_sided


# ─────────────────────────────────────────────
# 输出报告
# ─────────────────────────────────────────────

def print_final_report(baseline: dict, variants: list[dict]) -> None:
    """输出对比表。"""
    print("\n")
    print("=" * 110)
    print("  换手率降低方案 SimBroker回测对比")
    print(f"  周期: {START_DATE} ~ {END_DATE}  |  初始资金: {INITIAL_CAPITAL:,.0f}")
    print(f"  基线: v1.1 5因子等权 Top15 月度 行业25%")
    print("=" * 110)

    # 对比表
    print(f"\n{'方案':<28} {'参数':<12} {'Sharpe':>8} {'Sharpe CI':>20} {'MDD':>8} "
          f"{'年化换手率':>10} {'vs基线p':>10}")
    print("-" * 100)

    # 基线行
    b = baseline
    print(f"  {'基线(v1.1)':<26} {'—':<12} {b['sharpe']:>8.3f} "
          f"[{b['ci_lo']:.3f}, {b['ci_hi']:.3f}]   {b['mdd']:>8.2%} "
          f"{b['annual_turnover']:>9.0%} {'—':>10}")

    for v in variants:
        p_val = paired_bootstrap_pvalue(b["returns"], v["returns"])
        sig = ""
        if p_val < 0.05:
            sig = " **"
        elif p_val < 0.10:
            sig = " *"

        pass_flag = ""
        if v["annual_turnover"] < 3.0 and v["sharpe"] >= 0.869:
            pass_flag = " PASS"
        elif v["annual_turnover"] < 3.0:
            pass_flag = " (TO OK)"
        elif v["sharpe"] >= 0.869:
            pass_flag = " (SR OK)"

        print(f"  {v['label']:<26} {v.get('param',''):<12} {v['sharpe']:>8.3f} "
              f"[{v['ci_lo']:.3f}, {v['ci_hi']:.3f}]   {v['mdd']:>8.2%} "
              f"{v['annual_turnover']:>9.0%} {p_val:>9.4f}{sig}{pass_flag}")

    # 年度分解 (只打印最优方案和基线)
    # 找PASS或换手率最低的
    passed = [v for v in variants if v["annual_turnover"] < 3.0 and v["sharpe"] >= 0.869]
    if passed:
        best = max(passed, key=lambda x: x["sharpe"])
    else:
        best = min(variants, key=lambda x: v["annual_turnover"])

    print(f"\n{'年度分解 (基线 vs 最优方案: ' + best['label'] + ')':=^100}")
    bd_b = b["breakdown"]
    bd_v = best["breakdown"]
    all_years = sorted(set(bd_b.index.tolist()) | set(bd_v.index.tolist()))

    print(f"  {'年份':<6} | {'基线收益':>8} {'基线Sharpe':>10} {'基线MDD':>8} "
          f"{'基线换手':>8} | {'方案收益':>8} {'方案Sharpe':>10} {'方案MDD':>8}")
    print("  " + "-" * 90)

    for yr in all_years:
        b_row = bd_b.loc[yr] if yr in bd_b.index else None
        v_row = bd_v.loc[yr] if yr in bd_v.index else None
        b_str = (f"{b_row['return']/100:>8.2%} {b_row['sharpe']:>10.3f} {b_row['mdd']/100:>8.2%}"
                 if b_row is not None else f"{'N/A':>8} {'N/A':>10} {'N/A':>8}")
        v_str = (f"{v_row['return']/100:>8.2%} {v_row['sharpe']:>10.3f} {v_row['mdd']/100:>8.2%}"
                 if v_row is not None else f"{'N/A':>8} {'N/A':>10} {'N/A':>8}")
        print(f"  {yr:<6} | {b_str} {'':>8} | {v_str}")

    print(f"\n{'=' * 110}\n")


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

def main():
    t_start = time.time()
    conn = _get_sync_conn()

    try:
        logger.info("加载基础数据...")
        industry = load_industry(conn)
        price_data = load_price_data(START_DATE, END_DATE, conn)
        benchmark_data = load_benchmark(START_DATE, END_DATE, conn)
        logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

        rebalance_dates = get_rebalance_dates(
            START_DATE, END_DATE, freq="monthly", conn=conn
        )
        logger.info(f"调仓日: {len(rebalance_dates)}个")

        # ── 基线 ──
        logger.info("\n>>> 基线回测 (v1.1 标准)...")
        baseline_ports = generate_portfolios(
            rebalance_dates, industry, conn, method="baseline"
        )
        baseline = run_single_backtest(
            baseline_ports, price_data, benchmark_data, label="基线(v1.1)"
        )

        variants = []

        # ── 方案A: 限制最大换仓数 ──
        for k in [3, 5, 7]:
            logger.info(f"\n>>> 方案A: max_replace={k}...")
            ports = generate_portfolios(
                rebalance_dates, industry, conn,
                method="max_replace", max_replace=k,
            )
            r = run_single_backtest(
                ports, price_data, benchmark_data,
                label=f"A: max_replace={k}",
            )
            r["param"] = f"K={k}"
            variants.append(r)

        # ── 方案B: Turnover Penalty ──
        for lam in [0.1, 0.2, 0.5, 1.0]:
            logger.info(f"\n>>> 方案B: lambda={lam}...")
            ports = generate_portfolios(
                rebalance_dates, industry, conn,
                method="turnover_penalty", lam=lam,
            )
            r = run_single_backtest(
                ports, price_data, benchmark_data,
                label=f"B: penalty={lam}",
            )
            r["param"] = f"lam={lam}"
            variants.append(r)

        # ── 方案C: 最大重叠选股 ──
        for pool in [20, 25]:
            logger.info(f"\n>>> 方案C: pool_size={pool}...")
            ports = generate_portfolios(
                rebalance_dates, industry, conn,
                method="max_overlap", pool_size=pool,
            )
            r = run_single_backtest(
                ports, price_data, benchmark_data,
                label=f"C: pool={pool}",
            )
            r["param"] = f"pool={pool}"
            variants.append(r)

        # ── 输出报告 ──
        print_final_report(baseline, variants)

        elapsed = time.time() - t_start
        logger.info(f"总耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
