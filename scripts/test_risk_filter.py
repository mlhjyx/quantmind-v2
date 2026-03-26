"""测试排除财务风险股后5因子等权表现是否提升。

risk角色 Sprint 1.5b 快速验证脚本。

背景：招商定量2025报告——财务风险股年化超额-9.96%，IR=-2.11。
排除比选入简单：只需识别"差公司"并排除。

财务风险股定义（在生产Universe基础上额外排除）：
1. ROE < -20%（连续亏损）          ← Tushare roe字段已×100
2. 资产负债率 > 80%（高杠杆）      ← debt_to_asset字段已×100
3. 营收同比增速 < -30%（严重萎缩）  ← revenue_yoy字段已×100

注：生产Universe已排除ST/新股/停牌/低市值，本脚本测试在生产Universe
基础上增加财务风险排除的增量效果。

对照：生产Universe 5因子等权Top15基线（v1.1配置）。
回测期：2021-01 ~ 2025-12，月度调仓。
"""

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
COST_ONE_WAY = 0.0015  # 单边1.5‰
BOOTSTRAP_N = 10000
BOOTSTRAP_BLOCK = 20
SEED = 42

BT_START = date(2021, 1, 4)
BT_END = date(2025, 12, 31)

BASELINE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

# 因子方向：与生产SignalComposer(signal_engine.py)完全一致
# direction=1: 值越大越好; direction=-1: 值越小越好 → 取反后越大越好
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,  # 低换手好
    "volatility_20": -1,     # 低波动好
    "reversal_20": 1,        # 计算时已取反，值越大越好
    "amihud_20": 1,          # 高非流动性=小盘溢价
    "bp_ratio": 1,           # 高B/P=价值股好
}

# 风险阈值
ROE_THRESHOLD = -20.0        # ROE < -20%（字段已×100）
DEBT_THRESHOLD = 80.0        # 资产负债率 > 80%
REVENUE_YOY_THRESHOLD = -30.0  # 营收同比 < -30%


def get_conn():
    """获取数据库连接（读.env配置）。"""
    return _get_sync_conn()


# ==============================================================
# 生产Universe（与run_backtest.py的load_universe一致）
# ==============================================================
def load_production_universe(conn, trade_date: date) -> set[str]:
    """加载生产Universe：排除ST/新股(<60天)/停牌/低市值(<10亿)/退市。

    与run_backtest.py的load_universe完全一致。
    """
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


# ==============================================================
# 财务风险股标记（在生产Universe基础上额外排除）
# ==============================================================
def load_financial_risk_flags_pit(conn, trade_date: date) -> set[str]:
    """基于PIT财务数据，标记截至trade_date的财务风险股。

    使用actual_ann_date做PIT对齐，每个code取最新一期已公告的财报。
    满足任一条件即为风险股：
    - ROE < -20%
    - debt_to_asset > 80%
    - revenue_yoy < -30%
    """
    sql = """
    WITH latest_report AS (
        SELECT DISTINCT ON (code)
            code, roe, debt_to_asset, revenue_yoy
        FROM financial_indicators
        WHERE actual_ann_date <= %s
        ORDER BY code, report_date DESC, actual_ann_date DESC
    )
    SELECT code FROM latest_report
    WHERE roe < %s
       OR debt_to_asset > %s
       OR revenue_yoy < %s
    """
    df = pd.read_sql(
        sql, conn,
        params=(trade_date, ROE_THRESHOLD, DEBT_THRESHOLD, REVENUE_YOY_THRESHOLD),
    )
    return set(df["code"].tolist())


# ==============================================================
# 行情数据
# ==============================================================
def load_price_data(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """加载收盘价和复权因子，在Python端计算adj_close，避免PG内存溢出。"""
    sql = """
    SELECT trade_date, code, close, adj_factor
    FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
      AND volume > 0
    ORDER BY trade_date, code
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    # 计算后复权价: close * adj_factor / latest_adj_factor
    latest_adj = df.groupby("code")["adj_factor"].transform("last")
    df["adj_close"] = df["close"] * df["adj_factor"] / latest_adj
    df = df[["trade_date", "code", "adj_close"]]

    logger.info(f"行情数据: {len(df)}行, {df['trade_date'].nunique()}天, "
                f"{df['code'].nunique()}股")
    return df


def load_trade_dates(conn, start_date: date, end_date: date) -> list[date]:
    sql = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
    ORDER BY trade_date
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    return [d.date() if hasattr(d, "date") else d for d in df["trade_date"]]


# ==============================================================
# 因子信号
# ==============================================================
def load_factor_signals_for_dates(
    conn,
    target_dates: list[date],
) -> pd.DataFrame:
    """加载指定日期的5因子neutral_value并计算等权排名综合得分。

    只加载调仓日的因子数据，避免全量加载OOM。

    Returns:
        DataFrame [trade_date, code, score]
    """
    factor_list = BASELINE_FACTORS
    factor_ph = ",".join(["%s"] * len(factor_list))
    date_ph = ",".join(["%s"] * len(target_dates))

    sql = f"""
    SELECT trade_date, code, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date IN ({date_ph})
      AND factor_name IN ({factor_ph})
      AND neutral_value IS NOT NULL
    ORDER BY trade_date, code
    """
    params = list(target_dates) + factor_list
    df = pd.read_sql(sql, conn, params=params)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    if df.empty:
        return pd.DataFrame(columns=["trade_date", "code", "score"])

    logger.info(f"因子数据: {len(df)}行, {df['trade_date'].nunique()}天")

    results = []
    for td in sorted(df["trade_date"].unique()):
        day_df = df[df["trade_date"] == td].copy()

        # Pivot for this day only
        wide = day_df.pivot_table(
            index="code",
            columns="factor_name",
            values="neutral_value",
            aggfunc="first",
        ).reset_index()
        wide.columns.name = None

        if len(wide) < TOP_N:
            continue

        # 与生产SignalComposer完全一致的等权合成:
        # direction=-1的因子取反，然后等权平均
        available = [f for f in factor_list if f in wide.columns]
        if not available:
            continue

        score = pd.Series(0.0, index=wide.index)
        for factor in available:
            direction = FACTOR_DIRECTIONS.get(factor, 1)
            vals = wide[factor].fillna(0)
            if direction == -1:
                vals = -vals
            score += vals / len(available)

        wide["score"] = score
        wide["trade_date"] = td
        results.append(wide[["trade_date", "code", "score"]])

    if not results:
        return pd.DataFrame(columns=["trade_date", "code", "score"])

    signal_df = pd.concat(results, ignore_index=True)
    logger.info(f"因子信号: {len(signal_df)}行, {signal_df['trade_date'].nunique()}天")
    return signal_df


# ==============================================================
# 组合构建
# ==============================================================
def get_monthly_rebalance_dates(trade_dates: list[date]) -> list[date]:
    rebal_dates = []
    current_month = None
    for d in trade_dates:
        ym = (d.year, d.month)
        if ym != current_month:
            rebal_dates.append(d)
            current_month = ym
    return rebal_dates


def compute_daily_returns(price_df: pd.DataFrame) -> pd.DataFrame:
    pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close")
    ret = pivot.pct_change().iloc[1:]
    return ret


def build_portfolio_returns(
    signal_df: pd.DataFrame,
    returns_pivot: pd.DataFrame,
    trade_dates: list[date],
    exclude_sets: dict[date, set[str]] | None = None,
    top_n: int = TOP_N,
    cost: float = COST_ONE_WAY,
) -> tuple[pd.DataFrame, dict]:
    """构建月度调仓Top-N等权组合。

    Args:
        signal_df: [trade_date, code, score]
        returns_pivot: 日频收益率矩阵
        trade_dates: 交易日列表
        exclude_sets: {rebal_date: set(codes_to_exclude)} 或 None
        top_n: 选股数量
        cost: 单边交易成本

    Returns:
        (daily_returns_df, holdings_info)
        holdings_info: {rebal_date: {"selected": [...], "excluded_count": int}}
    """
    rebalance_dates = get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(signal_df["trade_date"].unique())
    available_rebal = [d for d in rebalance_dates if d in signal_dates]

    if not available_rebal:
        return pd.DataFrame(columns=["trade_date", "portfolio_return"]), {}

    daily_returns = []
    prev_holdings = set()
    holdings_info = {}

    for i, rebal_date in enumerate(available_rebal):
        day_signals = signal_df[signal_df["trade_date"] == rebal_date].copy()

        # 排除风险股
        excluded_count = 0
        if exclude_sets and rebal_date in exclude_sets:
            before = len(day_signals)
            day_signals = day_signals[~day_signals["code"].isin(exclude_sets[rebal_date])]
            excluded_count = before - len(day_signals)

        day_signals = day_signals.sort_values("score", ascending=False)
        top_stocks = day_signals.head(top_n)["code"].tolist()

        holdings_info[rebal_date] = {
            "selected": top_stocks,
            "excluded_count": excluded_count,
        }

        if len(top_stocks) == 0:
            continue

        rebal_idx = trade_dates.index(rebal_date) if rebal_date in trade_dates else None
        if rebal_idx is None:
            continue

        hold_start_idx = rebal_idx + 1
        if hold_start_idx >= len(trade_dates):
            continue

        if i + 1 < len(available_rebal):
            next_rebal = available_rebal[i + 1]
            hold_end_idx = (
                trade_dates.index(next_rebal)
                if next_rebal in trade_dates
                else len(trade_dates) - 1
            )
        else:
            hold_end_idx = len(trade_dates)

        new_holdings = set(top_stocks)
        turnover = (
            len(new_holdings.symmetric_difference(prev_holdings)) / (2 * top_n)
            if prev_holdings
            else 1.0
        )
        rebal_cost = turnover * cost * 2

        for day_idx in range(hold_start_idx, hold_end_idx):
            td = trade_dates[day_idx]
            if td not in returns_pivot.index:
                continue

            day_ret = returns_pivot.loc[td]
            stock_rets = [
                day_ret[s]
                for s in top_stocks
                if s in day_ret.index and not np.isnan(day_ret[s])
            ]
            port_ret = np.mean(stock_rets) if stock_rets else 0.0

            if day_idx == hold_start_idx:
                port_ret -= rebal_cost

            daily_returns.append({"trade_date": td, "portfolio_return": port_ret})

        prev_holdings = new_holdings

    return pd.DataFrame(daily_returns), holdings_info


# ==============================================================
# 绩效指标
# ==============================================================
def calc_metrics(daily_rets: np.ndarray) -> dict:
    if len(daily_rets) == 0:
        return {}

    total_ret = np.prod(1 + daily_rets) - 1
    n_years = len(daily_rets) / 252.0
    ann_ret = (1 + total_ret) ** (1.0 / n_years) - 1 if n_years > 0 else 0

    ann_sharpe = (
        np.mean(daily_rets) / np.std(daily_rets, ddof=1) * np.sqrt(252)
        if np.std(daily_rets, ddof=1) > 0
        else 0
    )

    cum = np.cumprod(1 + daily_rets)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum / running_max - 1
    mdd = float(np.min(drawdowns))

    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-10 else 0

    downside = daily_rets[daily_rets < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else 1e-10
    sortino = np.mean(daily_rets) / downside_std * np.sqrt(252)

    return {
        "ann_return": ann_ret,
        "ann_sharpe": ann_sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "total_return": total_ret,
        "n_days": len(daily_rets),
    }


def bootstrap_sharpe_ci(
    daily_rets: np.ndarray,
    n_boot: int = BOOTSTRAP_N,
    block_size: int = BOOTSTRAP_BLOCK,
    seed: int = SEED,
) -> tuple[float, float]:
    rng = np.random.RandomState(seed)
    T = len(daily_rets)
    n_blocks = int(np.ceil(T / block_size))
    sharpes = np.zeros(n_boot)

    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        boot = daily_rets[indices]
        std_b = np.std(boot, ddof=1)
        if std_b > 1e-12:
            sharpes[b] = np.mean(boot) / std_b * np.sqrt(252)

    return float(np.percentile(sharpes, 2.5)), float(np.percentile(sharpes, 97.5))


def paired_block_bootstrap(
    test_rets: np.ndarray,
    base_rets: np.ndarray,
    n_boot: int = BOOTSTRAP_N,
    block_size: int = BOOTSTRAP_BLOCK,
    seed: int = SEED,
) -> dict:
    rng = np.random.RandomState(seed)
    T = len(test_rets)
    d = test_rets - base_rets

    orig_diff_sharpe = (
        np.mean(d) / np.std(d, ddof=1) * np.sqrt(252)
        if np.std(d, ddof=1) > 0
        else 0
    )

    n_blocks = int(np.ceil(T / block_size))
    boot_sharpes = np.zeros(n_boot)

    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        d_boot = d[indices]
        std_boot = np.std(d_boot, ddof=1)
        if std_boot > 1e-12:
            boot_sharpes[b] = np.mean(d_boot) / std_boot * np.sqrt(252)

    p_value = np.mean(boot_sharpes <= 0)
    ci_lo = np.percentile(boot_sharpes, 2.5)
    ci_hi = np.percentile(boot_sharpes, 97.5)

    return {
        "orig_diff_sharpe": orig_diff_sharpe,
        "p_value": p_value,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
    }


# ==============================================================
# 风险股收益分析
# ==============================================================
def analyze_risk_stock_returns(
    conn,
    risk_sets: dict[date, set[str]],
    returns_pivot: pd.DataFrame,
    trade_dates: list[date],
) -> dict:
    """分析被排除风险股在排除期间的平均收益。"""
    rebalance_dates = sorted(risk_sets.keys())
    risk_monthly_rets = []

    for i, rebal_date in enumerate(rebalance_dates):
        risk_codes = risk_sets[rebal_date]
        if not risk_codes:
            continue

        rebal_idx = (
            trade_dates.index(rebal_date) if rebal_date in trade_dates else None
        )
        if rebal_idx is None:
            continue

        hold_start_idx = rebal_idx + 1
        if hold_start_idx >= len(trade_dates):
            continue

        if i + 1 < len(rebalance_dates):
            next_rebal = rebalance_dates[i + 1]
            hold_end_idx = (
                trade_dates.index(next_rebal)
                if next_rebal in trade_dates
                else len(trade_dates) - 1
            )
        else:
            hold_end_idx = len(trade_dates)

        # 计算风险股在此持有期的平均收益
        period_rets = []
        for day_idx in range(hold_start_idx, hold_end_idx):
            td = trade_dates[day_idx]
            if td not in returns_pivot.index:
                continue
            day_ret = returns_pivot.loc[td]
            stock_rets = [
                day_ret[s]
                for s in risk_codes
                if s in day_ret.index and not np.isnan(day_ret[s])
            ]
            if stock_rets:
                period_rets.append(np.mean(stock_rets))

        if period_rets:
            month_ret = np.prod(1 + np.array(period_rets)) - 1
            risk_monthly_rets.append(month_ret)

    if not risk_monthly_rets:
        return {"avg_monthly": 0, "ann_return": 0, "n_months": 0}

    avg_monthly = np.mean(risk_monthly_rets)
    ann_return = (1 + avg_monthly) ** 12 - 1

    return {
        "avg_monthly": avg_monthly,
        "ann_return": ann_return,
        "n_months": len(risk_monthly_rets),
    }


def analyze_risk_list_turnover(risk_sets: dict[date, set[str]]) -> float:
    """风险名单月度变化率。"""
    dates_sorted = sorted(risk_sets.keys())
    turnovers = []
    for i in range(1, len(dates_sorted)):
        prev = risk_sets[dates_sorted[i - 1]]
        curr = risk_sets[dates_sorted[i]]
        if prev and curr:
            union = prev | curr
            changed = len(prev.symmetric_difference(curr))
            turnovers.append(changed / len(union) if union else 0)
    return np.mean(turnovers) if turnovers else 0


# ==============================================================
# Main
# ==============================================================
def main():
    t0 = time.time()

    print("=" * 80)
    print("  财务风险股排除测试 — 5因子等权 Top15 月度调仓")
    print(f"  回测期: {BT_START} ~ {BT_END}")
    print("=" * 80)

    conn = get_conn()
    try:
        # ----------------------------------------------------------
        # 1. 加载行情数据
        # ----------------------------------------------------------
        logger.info("Step 1: 加载行情数据...")
        price_start = BT_START - timedelta(days=10)
        price_end = BT_END + timedelta(days=40)
        price_df = load_price_data(conn, price_start, price_end)
        trade_dates_full = load_trade_dates(conn, price_start, price_end)
        trade_dates_bt = [d for d in trade_dates_full if BT_START <= d <= BT_END]

        returns_pivot = compute_daily_returns(price_df)

        # ----------------------------------------------------------
        # 2. 确定调仓日 + 构建Universe + 风险股集合
        # ----------------------------------------------------------
        logger.info("Step 2: 确定调仓日...")
        rebalance_dates = get_monthly_rebalance_dates(trade_dates_bt)
        logger.info(f"调仓日: {len(rebalance_dates)}个 ({rebalance_dates[0]} ~ {rebalance_dates[-1]})")

        logger.info("Step 3: 构建每月生产Universe + 风险股排除集合...")
        universe_sets: dict[date, set[str]] = {}
        risk_sets: dict[date, set[str]] = {}

        for rd in rebalance_dates:
            prod_universe = load_production_universe(conn, rd)
            universe_sets[rd] = prod_universe

            fin_risk = load_financial_risk_flags_pit(conn, rd)
            risk_in_universe = fin_risk & prod_universe
            risk_sets[rd] = risk_in_universe

        avg_universe = np.mean([len(v) for v in universe_sets.values()])
        avg_excluded = np.mean([len(v) for v in risk_sets.values()])
        logger.info(f"生产Universe: 平均{avg_universe:.0f}只/期")
        logger.info(f"财务风险排除: {len(risk_sets)}期, 平均每期额外排除{avg_excluded:.0f}只")

        for rd in sorted(risk_sets.keys())[:3]:
            logger.info(f"  {rd}: Universe={len(universe_sets[rd])}只, 财务风险排除={len(risk_sets[rd])}只")

        # ----------------------------------------------------------
        # 3. 加载因子信号（仅调仓日）
        # ----------------------------------------------------------
        logger.info("Step 4: 加载因子信号（仅调仓日）...")
        signal_df = load_factor_signals_for_dates(conn, rebalance_dates)
    finally:
        conn.close()

    # 过滤：只保留生产Universe内的股票
    filtered_rows = []
    for rd in rebalance_dates:
        if rd not in universe_sets:
            continue
        day_signals = signal_df[signal_df["trade_date"] == rd]
        day_in_universe = day_signals[day_signals["code"].isin(universe_sets[rd])]
        filtered_rows.append(day_in_universe)

    signal_df_universe = pd.concat(filtered_rows, ignore_index=True)
    logger.info(f"Universe过滤后信号: {len(signal_df_universe)}行 (原{len(signal_df)}行)")

    # ----------------------------------------------------------
    # 5. 构建两个组合
    # ----------------------------------------------------------
    logger.info("Step 5a: 生产Universe基线组合（与run_backtest.py一致）...")
    baseline_port, baseline_holdings = build_portfolio_returns(
        signal_df_universe, returns_pivot, trade_dates_bt,
        exclude_sets=None, top_n=TOP_N, cost=COST_ONE_WAY,
    )

    logger.info("Step 5b: 生产Universe + 排除财务风险股组合...")
    filtered_port, filtered_holdings = build_portfolio_returns(
        signal_df_universe, returns_pivot, trade_dates_bt,
        exclude_sets=risk_sets, top_n=TOP_N, cost=COST_ONE_WAY,
    )

    conn_analysis = get_conn()
    try:
        # ----------------------------------------------------------
        # 6. 对齐日期
        # ----------------------------------------------------------
        baseline_port.set_index("trade_date", inplace=True)
        filtered_port.set_index("trade_date", inplace=True)

        common_dates = baseline_port.index.intersection(filtered_port.index).sort_values()
        logger.info(f"对齐后: {len(common_dates)}天 ({common_dates[0]} ~ {common_dates[-1]})")

        base_rets = baseline_port.loc[common_dates, "portfolio_return"].values.astype(np.float64)
        filt_rets = filtered_port.loc[common_dates, "portfolio_return"].values.astype(np.float64)

        # ----------------------------------------------------------
        # 7. 绩效计算
        # ----------------------------------------------------------
        logger.info("Step 6: 计算绩效指标...")
        base_metrics = calc_metrics(base_rets)
        filt_metrics = calc_metrics(filt_rets)

        base_ci = bootstrap_sharpe_ci(base_rets, seed=SEED)
        filt_ci = bootstrap_sharpe_ci(filt_rets, seed=SEED + 1)

        # ----------------------------------------------------------
        # 8. Paired bootstrap
        # ----------------------------------------------------------
        logger.info("Step 7: Paired Block Bootstrap...")
        boot_result = paired_block_bootstrap(filt_rets, base_rets)

        # ----------------------------------------------------------
        # 9. 风险股收益分析
        # ----------------------------------------------------------
        logger.info("Step 8: 风险股收益分析...")
        risk_ret_analysis = analyze_risk_stock_returns(
            conn_analysis, risk_sets, returns_pivot, trade_dates_bt,
        )
        risk_turnover = analyze_risk_list_turnover(risk_sets)
    finally:
        conn_analysis.close()

    # ----------------------------------------------------------
    # 10. 年度分解
    # ----------------------------------------------------------
    yearly_base = {}
    yearly_filt = {}
    for year in sorted(set(d.year for d in common_dates)):
        mask = np.array([d.year == year for d in common_dates])
        if mask.sum() > 0:
            yearly_base[year] = calc_metrics(base_rets[mask])
            yearly_filt[year] = calc_metrics(filt_rets[mask])

    # ==============================================================
    # 输出报告
    # ==============================================================
    elapsed = time.time() - t0

    print("\n")
    print("=" * 80)
    print("  财务风险股排除 评估报告")
    print(f"  期间: {common_dates[0]} ~ {common_dates[-1]} ({len(common_dates)} 交易日)")
    print(f"  Top-{TOP_N} 等权 月度调仓 单边成本{COST_ONE_WAY*1000:.1f}‰")
    print("=" * 80)

    # --- 核心指标对比 ---
    print("\n{:=^80}".format(" 核心指标对比 "))
    print("{:<20} {:>18} {:>18} {:>12}".format("指标", "全宇宙(基线)", "排除风险股", "提升"))
    print("-" * 70)

    def fmt_delta(v_new: float, v_base: float, pct: bool = False) -> str:
        d = v_new - v_base
        if pct:
            return f"{d:+.2%}"
        return f"{d:+.3f}"

    print("{:<20} {:>17.2%} {:>17.2%} {:>12}".format(
        "年化收益率",
        base_metrics["ann_return"], filt_metrics["ann_return"],
        fmt_delta(filt_metrics["ann_return"], base_metrics["ann_return"], True)))

    print("{:<20} {:>18.3f} {:>18.3f} {:>12}".format(
        "年化Sharpe",
        base_metrics["ann_sharpe"], filt_metrics["ann_sharpe"],
        fmt_delta(filt_metrics["ann_sharpe"], base_metrics["ann_sharpe"])))

    print("{:<20} {:>17.2%} {:>17.2%} {:>12}".format(
        "最大回撤(MDD)",
        base_metrics["mdd"], filt_metrics["mdd"],
        fmt_delta(filt_metrics["mdd"], base_metrics["mdd"], True)))

    print("{:<20} {:>18.3f} {:>18.3f} {:>12}".format(
        "Calmar Ratio",
        base_metrics["calmar"], filt_metrics["calmar"],
        fmt_delta(filt_metrics["calmar"], base_metrics["calmar"])))

    print("{:<20} {:>18.3f} {:>18.3f} {:>12}".format(
        "Sortino Ratio",
        base_metrics["sortino"], filt_metrics["sortino"],
        fmt_delta(filt_metrics["sortino"], base_metrics["sortino"])))

    print("{:<20} {:>17.2%} {:>17.2%} {:>12}".format(
        "总收益率",
        base_metrics["total_return"], filt_metrics["total_return"],
        fmt_delta(filt_metrics["total_return"], base_metrics["total_return"], True)))

    print("{:<20} {:>17.0f}只/期 {:>17} {:>12}".format(
        "平均排除股数", avg_excluded, "—", "—"))

    # --- Bootstrap CI ---
    print("\n{:=^80}".format(" Bootstrap Sharpe 95% CI "))
    print("全宇宙:    Sharpe = {:.3f}  [{:.3f}, {:.3f}]".format(
        base_metrics["ann_sharpe"], base_ci[0], base_ci[1]))
    print("排除风险:  Sharpe = {:.3f}  [{:.3f}, {:.3f}]".format(
        filt_metrics["ann_sharpe"], filt_ci[0], filt_ci[1]))

    # --- Paired Bootstrap ---
    print("\n{:=^80}".format(" Paired Block Bootstrap (block=20, n=10000) "))
    print("差异Sharpe (排除 - 基线):  {:.3f}".format(boot_result["orig_diff_sharpe"]))
    print("Bootstrap 95% CI:          [{:.3f}, {:.3f}]".format(
        boot_result["ci_lo"], boot_result["ci_hi"]))
    print("p-value (H0: 排除<=基线):  {:.4f}".format(boot_result["p_value"]))

    if boot_result["p_value"] < 0.05:
        print(">>> 结论: p < 0.05, 排除风险股显著优于全宇宙基线 <<<")
    elif boot_result["p_value"] < 0.10:
        print(">>> 结论: 0.05 < p < 0.10, 弱显著 <<<")
    else:
        print(">>> 结论: p >= 0.10, 排除风险股未显著优于全宇宙基线 <<<")

    # --- 风险股收益分析 ---
    print("\n{:=^80}".format(" 风险股收益分析 "))
    print("被排除风险股等权月均收益: {:.2%}".format(risk_ret_analysis["avg_monthly"]))
    print("被排除风险股年化收益:     {:.2%}".format(risk_ret_analysis["ann_return"]))
    print("统计月数:                 {}".format(risk_ret_analysis["n_months"]))
    print("风险名单月度变化率:       {:.1%}".format(risk_turnover))
    if risk_ret_analysis["ann_return"] < 0:
        print(">>> 风险股年化为负 -> 排除有价值 <<<")
    else:
        print(">>> 风险股年化为正 -> 排除可能损失alpha <<<")

    # --- 年度分解 ---
    print("\n{:=^80}".format(" 年度分解 "))
    print("{:>6} | {:>10} {:>10} {:>10} | {:>10} {:>10} {:>10}".format(
        "年份", "Base收益", "Base Shrp", "Base MDD",
        "Filt收益", "Filt Shrp", "Filt MDD"))
    print("-" * 80)
    for year in sorted(yearly_base.keys()):
        b = yearly_base[year]
        f = yearly_filt[year]
        print("{:>6} | {:>9.2%} {:>10.3f} {:>10.2%} | {:>9.2%} {:>10.3f} {:>10.2%}".format(
            year,
            b["ann_return"], b["ann_sharpe"], b["mdd"],
            f["ann_return"], f["ann_sharpe"], f["mdd"]))

    # --- 风险排除分项拆解 ---
    print("\n{:=^80}".format(" 各风险条件命中分布 (最后一期,生产Universe内) "))
    last_rebal = sorted(risk_sets.keys())[-1]
    last_universe = universe_sets[last_rebal]
    conn2 = get_conn()
    try:
        for label, where_clause in [
            ("ROE < -20%", f"roe < {ROE_THRESHOLD}"),
            ("debt_to_asset > 80%", f"debt_to_asset > {DEBT_THRESHOLD}"),
            ("revenue_yoy < -30%", f"revenue_yoy < {REVENUE_YOY_THRESHOLD}"),
        ]:
            sql = f"""
            WITH latest_report AS (
                SELECT DISTINCT ON (code) code, roe, debt_to_asset, revenue_yoy
                FROM financial_indicators
                WHERE actual_ann_date <= %s
                ORDER BY code, report_date DESC, actual_ann_date DESC
            )
            SELECT code FROM latest_report WHERE {where_clause}
            """
            cur = conn2.cursor()
            cur.execute(sql, (last_rebal,))
            codes_hit = {r[0] for r in cur.fetchall()}
            # 只统计在生产Universe内的
            cnt_in_universe = len(codes_hit & last_universe)
            print(f"  {label}: {cnt_in_universe}只 (全市场{len(codes_hit)}只)")

        print(f"  合并去重(Universe内): {len(risk_sets[last_rebal])}只 / Universe {len(last_universe)}只")
    finally:
        conn2.close()

    print(f"\n总耗时: {elapsed:.1f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
