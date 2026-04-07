"""ROE行业中位数宇宙过滤测试 — strategy角色 Sprint 1.5b。

测试假设: 用ROE>行业中位数筛选"质量宇宙"后，5因子等权Top15表现是否提升。

实现:
1. 每季度用PIT对齐的ROE数据，筛选ROE>行业中位数的股票
2. 在质量宇宙内跑5因子等权Top15月度调仓
3. 与全宇宙Top15对比 Sharpe/MDD/年化收益/换手率/年度分解
4. Paired block bootstrap检验差异显著性

注意:
- ROE筛选季度更新（跟随财报披露），月度调仓之间宇宙不变
- ROE为NULL的股票排除出质量宇宙
- 行业来自symbols.industry_sw1（申万一级）
- 不修改任何engine文件
"""

import bisect
import gc
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ==============================================================
# 常量
# ==============================================================
TOP_N = 15
COST_ONE_WAY = 0.0015
BOOTSTRAP_N = 10000
BOOTSTRAP_BLOCK = 20
SEED = 42

BT_START = date(2021, 1, 4)
BT_END = date(2025, 12, 31)

BASELINE_FACTORS = [
    "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio",
]

# 因子方向（与生产signal_engine.py FACTOR_DIRECTION完全一致）
# +1=越大越好, -1=越小越好
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,  # 低换手好
    "volatility_20": -1,     # 低波动好
    "reversal_20": 1,        # calc_reversal已取反, 高值=反转强=好
    "amihud_20": 1,          # 高Amihud=小盘溢价
    "bp_ratio": 1,           # 高B/P=价值
}


def get_conn():
    """获取数据库连接（读.env配置）。"""
    return _get_sync_conn()


# ==============================================================
# 数据加载
# ==============================================================
def load_price_data(conn, start_date, end_date):
    sql = """
    WITH latest_adj AS (
        SELECT DISTINCT ON (code) code, adj_factor AS latest_adj
        FROM klines_daily ORDER BY code, trade_date DESC
    )
    SELECT k.trade_date, k.code,
           k.close * k.adj_factor / la.latest_adj AS adj_close
    FROM klines_daily k
    JOIN latest_adj la ON k.code = la.code
    WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
    ORDER BY k.trade_date, k.code
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    logger.info(f"行情: {len(df)}行, {df['trade_date'].nunique()}天, {df['code'].nunique()}股")
    return df


def load_trade_dates(conn, start_date, end_date):
    sql = "SELECT DISTINCT trade_date FROM klines_daily WHERE trade_date BETWEEN %s AND %s ORDER BY trade_date"
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    return [d.date() if hasattr(d, "date") else d for d in df["trade_date"]]


def load_industry_map(conn):
    df = pd.read_sql("SELECT code, industry_sw1 FROM symbols WHERE industry_sw1 IS NOT NULL", conn)
    return dict(zip(df["code"], df["industry_sw1"], strict=False))


def load_roe_pit(conn, start_date, end_date):
    lookback_start = date(start_date.year - 1, 1, 1)
    sql = """
    WITH ranked AS (
        SELECT code, report_date, actual_ann_date, roe,
               ROW_NUMBER() OVER (PARTITION BY code, report_date ORDER BY actual_ann_date DESC) AS rn
        FROM financial_indicators
        WHERE actual_ann_date BETWEEN %s AND %s AND roe IS NOT NULL
    )
    SELECT code, report_date, actual_ann_date, roe FROM ranked WHERE rn = 1
    ORDER BY code, actual_ann_date
    """
    df = pd.read_sql(sql, conn, params=(lookback_start, end_date))
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    df["actual_ann_date"] = pd.to_datetime(df["actual_ann_date"]).dt.date
    logger.info(f"ROE PIT: {len(df)}行, {df['code'].nunique()}股")
    return df


def load_factor_wide(conn, start_date, end_date):
    """加载5因子neutral_value并pivot为宽表（只加载一次）。"""
    placeholders = ",".join(["%s"] * len(BASELINE_FACTORS))
    sql = f"""
    SELECT trade_date, code, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date BETWEEN %s AND %s
      AND factor_name IN ({placeholders})
      AND neutral_value IS NOT NULL
    ORDER BY trade_date, code
    """
    params = [start_date, end_date] + BASELINE_FACTORS
    df = pd.read_sql(sql, conn, params=params)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    logger.info(f"因子长表: {len(df)}行")

    wide = df.pivot_table(
        index=["trade_date", "code"], columns="factor_name",
        values="neutral_value", aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    del df
    gc.collect()
    logger.info(f"因子宽表: {len(wide)}行, {wide['trade_date'].nunique()}天")
    return wide


# ==============================================================
# ROE宇宙过滤
# ==============================================================
def get_monthly_rebalance_dates(trade_dates):
    rebal, cur = [], None
    for d in trade_dates:
        ym = (d.year, d.month)
        if ym != cur:
            rebal.append(d)
            cur = ym
    return rebal


def build_roe_universe(roe_df, industry_map, trade_dates):
    roe_sorted = roe_df.sort_values(["code", "actual_ann_date", "report_date"])
    universe_map = {}
    rebal_dates = get_monthly_rebalance_dates(trade_dates)

    for td in rebal_dates:
        visible = roe_sorted[roe_sorted["actual_ann_date"] <= td]
        if visible.empty:
            universe_map[td] = set()
            continue
        latest = (
            visible.sort_values("report_date", ascending=False)
            .groupby("code").first().reset_index()
        )
        latest["industry"] = latest["code"].map(industry_map)
        latest = latest.dropna(subset=["industry", "roe"])
        if latest.empty:
            universe_map[td] = set()
            continue
        med = latest.groupby("industry")["roe"].median()
        latest["ind_med"] = latest["industry"].map(med)
        passed = latest[latest["roe"] > latest["ind_med"]]
        universe_map[td] = set(passed["code"].tolist())

    sizes = [len(v) for v in universe_map.values() if v]
    if sizes:
        logger.info(f"ROE宇宙: {len(rebal_dates)}个调仓日, 均{np.mean(sizes):.0f}股, [{min(sizes)},{max(sizes)}]")
    return universe_map


# ==============================================================
# 信号计算
# ==============================================================
def compute_signals(wide, universe_filter=None):
    """从宽表计算5因子等权合成信号（与生产signal_engine.py一致）。

    方法: sign-flip + 等权加和（不是pct_rank），与signal_engine.py完全一致。
    direction=-1的因子乘以-1翻转，然后等权求和，高分=好。
    """
    all_dates = sorted(wide["trade_date"].unique())

    if universe_filter is not None:
        sorted_filter_dates = sorted(universe_filter.keys())

    results = []
    for td in all_dates:
        day_df = wide.loc[wide["trade_date"] == td].copy()

        if universe_filter is not None:
            idx = bisect.bisect_right(sorted_filter_dates, td) - 1
            if idx < 0:
                continue
            allowed = universe_filter[sorted_filter_dates[idx]]
            if not allowed:
                continue
            day_df = day_df[day_df["code"].isin(allowed)]

        if len(day_df) < TOP_N:
            continue

        # 与signal_engine.py一致: sign-flip + 等权加和
        available = [f for f in BASELINE_FACTORS if f in day_df.columns]
        if not available:
            continue

        composite = np.zeros(len(day_df))
        w = 1.0 / len(available)
        for factor in available:
            vals = day_df[factor].values.copy()
            direction = FACTOR_DIRECTIONS.get(factor, 1)
            if direction == -1:
                vals = -vals
            # NaN处理: 用0替代（中性化后均值接近0）
            vals = np.where(np.isnan(vals), 0.0, vals)
            composite += vals * w

        results.append(pd.DataFrame({
            "trade_date": day_df["trade_date"].values,
            "code": day_df["code"].values,
            "score": composite,
        }))

    if not results:
        return pd.DataFrame(columns=["trade_date", "code", "score"])
    signal_df = pd.concat(results, ignore_index=True)
    logger.info(f"信号: {len(signal_df)}行, {signal_df['trade_date'].nunique()}天 "
                f"(filter={'ON' if universe_filter else 'OFF'})")
    return signal_df


# ==============================================================
# 组合构建 + 绩效
# ==============================================================
def compute_daily_returns(price_df):
    pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close")
    return pivot.pct_change().iloc[1:]


def build_portfolio_returns(signal_df, returns_pivot, trade_dates, top_n=TOP_N, cost=COST_ONE_WAY):
    rebal_dates = get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(signal_df["trade_date"].unique())
    avail_rebal = [d for d in rebal_dates if d in signal_dates]
    if not avail_rebal:
        return pd.DataFrame(columns=["trade_date", "portfolio_return"])

    daily_returns = []
    prev_holdings = set()

    for i, rd in enumerate(avail_rebal):
        ds = signal_df[signal_df["trade_date"] == rd].nlargest(top_n, "score")
        top_stocks = ds["code"].tolist()
        if not top_stocks:
            continue
        ri = trade_dates.index(rd) if rd in trade_dates else None
        if ri is None:
            continue
        hsi = ri + 1
        if hsi >= len(trade_dates):
            continue
        hei = trade_dates.index(avail_rebal[i + 1]) if i + 1 < len(avail_rebal) and avail_rebal[i + 1] in trade_dates else len(trade_dates)
        new_h = set(top_stocks)
        turnover = len(new_h.symmetric_difference(prev_holdings)) / (2 * top_n) if prev_holdings else 1.0
        rc = turnover * cost * 2

        for di in range(hsi, hei):
            td = trade_dates[di]
            if td not in returns_pivot.index:
                continue
            day_ret = returns_pivot.loc[td]
            srets = [day_ret[s] for s in top_stocks if s in day_ret.index and not np.isnan(day_ret[s])]
            pr = np.mean(srets) if srets else 0.0
            if di == hsi:
                pr -= rc
            daily_returns.append({"trade_date": td, "portfolio_return": pr})
        prev_holdings = new_h

    return pd.DataFrame(daily_returns)


def calc_metrics(daily_rets, af=252.0):
    if len(daily_rets) == 0:
        return {}
    tr = np.prod(1 + daily_rets) - 1
    ny = len(daily_rets) / af
    ar = (1 + tr) ** (1.0 / ny) - 1 if ny > 0 else 0
    s = np.std(daily_rets, ddof=1)
    sharpe = np.mean(daily_rets) / s * np.sqrt(af) if s > 0 else 0
    cum = np.cumprod(1 + daily_rets)
    mdd = float(np.min(cum / np.maximum.accumulate(cum) - 1))
    calmar = ar / abs(mdd) if abs(mdd) > 1e-10 else 0
    ds = daily_rets[daily_rets < 0]
    dstd = np.std(ds, ddof=1) if len(ds) > 1 else 1e-10
    sortino = np.mean(daily_rets) / dstd * np.sqrt(af)
    ls, mls = 0, 0
    for r in daily_rets:
        if r < 0:
            ls += 1
            mls = max(mls, ls)
        else:
            ls = 0
    return {"ann_return": ar, "ann_sharpe": sharpe, "mdd": mdd, "calmar": calmar,
            "sortino": sortino, "total_return": tr, "n_days": len(daily_rets), "max_losing_streak": mls}


def compute_annual_turnover(signal_df, trade_dates, top_n=TOP_N):
    rebal_dates = get_monthly_rebalance_dates(trade_dates)
    sd = set(signal_df["trade_date"].unique())
    ar = [d for d in rebal_dates if d in sd]
    tvs, prev = [], None
    for rd in ar:
        cur = set(signal_df[signal_df["trade_date"] == rd].nlargest(top_n, "score")["code"].tolist())
        if prev is not None and cur:
            tvs.append(len(cur.symmetric_difference(prev)) / (2 * top_n))
        prev = cur
    return np.mean(tvs) * 12 if tvs else 0.0


def bootstrap_sharpe_ci(daily_rets, n_boot=BOOTSTRAP_N, block_size=BOOTSTRAP_BLOCK, seed=SEED):
    rng = np.random.RandomState(seed)
    T = len(daily_rets)
    nb = int(np.ceil(T / block_size))
    sharpes = np.zeros(n_boot)
    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=nb)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        boot = daily_rets[indices]
        s = np.std(boot, ddof=1)
        sharpes[b] = np.mean(boot) / s * np.sqrt(252) if s > 1e-12 else 0.0
    return float(np.percentile(sharpes, 2.5)), float(np.percentile(sharpes, 97.5))


def paired_block_bootstrap(test_rets, base_rets, n_boot=BOOTSTRAP_N, block_size=BOOTSTRAP_BLOCK, seed=SEED):
    rng = np.random.RandomState(seed)
    T = len(test_rets)
    d = test_rets - base_rets
    orig = np.mean(d) / np.std(d, ddof=1) * np.sqrt(252) if np.std(d, ddof=1) > 0 else 0
    nb = int(np.ceil(T / block_size))
    bs = np.zeros(n_boot)
    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=nb)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        db = d[indices]
        s = np.std(db, ddof=1)
        bs[b] = np.mean(db) / s * np.sqrt(252) if s > 1e-12 else 0.0
    return {"orig_diff_sharpe": orig, "p_value": float(np.mean(bs <= 0)),
            "ci_lo": float(np.percentile(bs, 2.5)), "ci_hi": float(np.percentile(bs, 97.5)),
            "boot_mean": float(np.mean(bs)), "boot_std": float(np.std(bs))}


# ==============================================================
# Main
# ==============================================================
def main():
    t0 = time.time()
    print("=" * 80)
    print("  ROE行业中位数宇宙过滤测试")
    print("  5因子等权 Top-15 月度调仓 2021-2025全期")
    print("=" * 80)

    conn = get_conn()
    try:
        # 1. 行情 + 交易日历
        logger.info("Step 1: 加载行情...")
        price_df = load_price_data(conn, BT_START - timedelta(days=10), BT_END + timedelta(days=40))
        trade_dates_full = load_trade_dates(conn, BT_START - timedelta(days=10), BT_END + timedelta(days=40))
        trade_dates_bt = [d for d in trade_dates_full if BT_START <= d <= BT_END]
        returns_pivot = compute_daily_returns(price_df)
        del price_df
        gc.collect()

        # 2. ROE + 行业
        logger.info("Step 2: ROE PIT + 行业映射...")
        roe_df = load_roe_pit(conn, BT_START, BT_END)
        industry_map = load_industry_map(conn)

        # 3. ROE宇宙
        logger.info("Step 3: 构建ROE质量宇宙...")
        roe_universe = build_roe_universe(roe_df, industry_map, trade_dates_bt)
        del roe_df
        gc.collect()

        # 样本
        rebal_dates = get_monthly_rebalance_dates(trade_dates_bt)
        for sd in rebal_dates[::12][:5]:
            logger.info(f"  {sd}: {len(roe_universe.get(sd, set()))}股")

        # 4. 加载因子宽表（只加载一次）
        logger.info("Step 4: 加载因子宽表...")
        wide = load_factor_wide(conn, BT_START, BT_END)

        # 5. 全宇宙信号
        logger.info("Step 5: 全宇宙信号...")
        baseline_signals = compute_signals(wide, universe_filter=None)

        # 6. ROE筛选信号
        logger.info("Step 6: ROE筛选信号...")
        roe_signals = compute_signals(wide, universe_filter=roe_universe)
        del wide
        gc.collect()
    finally:
        conn.close()

    # 7. 组合收益
    logger.info("Step 7: 组合收益...")
    baseline_port = build_portfolio_returns(baseline_signals, returns_pivot, trade_dates_bt)
    roe_port = build_portfolio_returns(roe_signals, returns_pivot, trade_dates_bt)

    # 8. 对齐
    baseline_port.set_index("trade_date", inplace=True)
    roe_port.set_index("trade_date", inplace=True)
    common = baseline_port.index.intersection(roe_port.index).sort_values()
    logger.info(f"共同交易日: {len(common)} ({common[0]} ~ {common[-1]})")

    base_rets = baseline_port.loc[common, "portfolio_return"].values.astype(np.float64)
    roe_rets = roe_port.loc[common, "portfolio_return"].values.astype(np.float64)

    # 9. 绩效
    logger.info("Step 8: 绩效 + Bootstrap...")
    bm = calc_metrics(base_rets)
    rm = calc_metrics(roe_rets)
    bci = bootstrap_sharpe_ci(base_rets, seed=SEED)
    rci = bootstrap_sharpe_ci(roe_rets, seed=SEED + 1)
    bt = compute_annual_turnover(baseline_signals, trade_dates_bt)
    rt = compute_annual_turnover(roe_signals, trade_dates_bt)
    boot = paired_block_bootstrap(roe_rets, base_rets)

    # 10. 年度分解
    yb, yr = {}, {}
    for y in sorted(set(d.year for d in common)):
        mask = np.array([d.year == y for d in common])
        if mask.sum() > 0:
            yb[y] = calc_metrics(base_rets[mask])
            yr[y] = calc_metrics(roe_rets[mask])

    # ==============================================================
    # 报告
    # ==============================================================
    elapsed = time.time() - t0
    print("\n" + "=" * 80)
    print(f"  评估期间: {common[0]} ~ {common[-1]} ({len(common)} 交易日)")
    print(f"  Top-{TOP_N} 等权 月度调仓 单边成本{COST_ONE_WAY*1000:.1f}permil")
    print("=" * 80)

    print(f"\n{'='*25} 核心指标对比 {'='*25}")
    print(f"{'指标':<25} {'全宇宙(基线)':>20} {'ROE筛选宇宙':>20}")
    print("-" * 65)
    print(f"{'年化收益率':<25} {bm['ann_return']:>19.2%} {rm['ann_return']:>19.2%}")
    print(f"{'年化Sharpe':<25} {bm['ann_sharpe']:>20.3f} {rm['ann_sharpe']:>20.3f}")
    print(f"{'最大回撤(MDD)':<25} {bm['mdd']:>19.2%} {rm['mdd']:>19.2%}")
    print(f"{'Calmar Ratio':<25} {bm['calmar']:>20.3f} {rm['calmar']:>20.3f}")
    print(f"{'Sortino Ratio':<25} {bm['sortino']:>20.3f} {rm['sortino']:>20.3f}")
    print(f"{'总收益率':<25} {bm['total_return']:>19.2%} {rm['total_return']:>19.2%}")
    print(f"{'年化换手率':<25} {bt*100:>19.1f}% {rt*100:>19.1f}%")
    print(f"{'最大连续亏损天数':<25} {bm['max_losing_streak']:>20d} {rm['max_losing_streak']:>20d}")

    print(f"\n{'='*20} Bootstrap Sharpe 95% CI {'='*20}")
    print(f"全宇宙:  Sharpe = {bm['ann_sharpe']:.3f}  [{bci[0]:.3f}, {bci[1]:.3f}]")
    print(f"ROE筛选: Sharpe = {rm['ann_sharpe']:.3f}  [{rci[0]:.3f}, {rci[1]:.3f}]")

    print(f"\n{'='*15} Paired Block Bootstrap (block=20, n=10000) {'='*15}")
    print(f"差异Sharpe (ROE - Base):  {boot['orig_diff_sharpe']:.3f}")
    print(f"Bootstrap 95% CI:         [{boot['ci_lo']:.3f}, {boot['ci_hi']:.3f}]")
    print(f"p-value (H0: ROE <= Base): {boot['p_value']:.4f}")

    if boot["p_value"] < 0.05:
        print(">>> ROE筛选显著优于全宇宙基线 <<<")
    elif boot["p_value"] < 0.10:
        print(">>> 弱显著 (0.05 < p < 0.10) <<<")
    else:
        print(">>> ROE筛选未显著优于全宇宙基线 <<<")

    print(f"\n{'='*25} 年度分解 {'='*25}")
    print(f"{'年份':>6} | {'Base收益':>10} {'Base Sharpe':>12} {'Base MDD':>10} | {'ROE收益':>10} {'ROE Sharpe':>12} {'ROE MDD':>10}")
    print("-" * 82)
    for y in sorted(yb.keys()):
        print(f"{y:>6} | {yb[y]['ann_return']:>9.2%} {yb[y]['ann_sharpe']:>12.3f} {yb[y]['mdd']:>10.2%} | "
              f"{yr[y]['ann_return']:>9.2%} {yr[y]['ann_sharpe']:>12.3f} {yr[y]['mdd']:>10.2%}")

    print(f"\n{'='*25} 结论 {'='*25}")
    sd = rm["ann_sharpe"] - bm["ann_sharpe"]
    md = rm["mdd"] - bm["mdd"]
    print(f"Sharpe差异: {sd:+.3f} (ROE - Base)")
    print(f"MDD差异:    {md:+.2%} (ROE - Base)")
    print(f"p-value:    {boot['p_value']:.4f}")

    if boot["p_value"] < 0.05 and sd > 0:
        print("\n>>> ROE宇宙过滤有效，可考虑纳入v1.2 <<<")
    elif sd > 0 and boot["p_value"] < 0.20:
        print("\n>>> ROE过滤有正向趋势但不显著，需更长验证 <<<")
    else:
        print("\n>>> ROE宇宙过滤无增量价值，维持v1.1全宇宙配置 <<<")

    print(f"\n总耗时: {elapsed:.1f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
