"""LightGBM信号平滑实验：降低换手率。

方案A: EMA平滑（alpha=0.5, 0.3）
方案B: 持仓惯性（bonus=0.3, 0.5, 0.7）

数据源: models/oos_predictions_clean.csv（7-fold干净OOS预测）
参考: scripts/evaluate_lgb_vs_baseline.py的build_portfolio_returns逻辑
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# 项目根目录
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
OOS_START = date(2023, 1, 3)
OOS_END = date(2026, 2, 11)


def get_conn():
    """获取数据库连接。"""
    return _get_sync_conn()


# ==============================================================
# 数据加载
# ==============================================================
def load_oos_predictions() -> pd.DataFrame:
    """加载干净的OOS预测数据。"""
    path = project_root / "models" / "oos_predictions_clean.csv"
    df = pd.read_csv(path)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    # CSV中code是int(如1)，DB中是string(如'000001')，需要对齐
    df["code"] = df["code"].astype(str).str.zfill(6)
    logger.info(f"OOS预测: {len(df)}行, {df['trade_date'].nunique()}天, "
                f"{df['code'].nunique()}股")
    return df


def load_price_data(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """加载复权收盘价。"""
    sql = """
    WITH latest_adj AS (
        SELECT DISTINCT ON (code)
            code, adj_factor AS latest_adj
        FROM klines_daily
        ORDER BY code, trade_date DESC
    )
    SELECT
        k.trade_date,
        k.code,
        k.close * k.adj_factor / la.latest_adj AS adj_close
    FROM klines_daily k
    JOIN latest_adj la ON k.code = la.code
    WHERE k.trade_date BETWEEN %s AND %s
      AND k.volume > 0
    ORDER BY k.trade_date, k.code
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    logger.info(f"行情数据: {len(df)}行, {df['trade_date'].nunique()}天")
    return df


def load_trade_dates(conn, start_date: date, end_date: date) -> list[date]:
    """加载交易日历。"""
    sql = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
    ORDER BY trade_date
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    return [d.date() if hasattr(d, "date") else d for d in df["trade_date"]]


# ==============================================================
# 方案A: EMA平滑
# ==============================================================
def apply_ema_smoothing(oos_df: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """对每只股票的predicted score做时序EMA平滑。

    smoothed_t = alpha * raw_t + (1-alpha) * smoothed_{t-1}

    Args:
        oos_df: [trade_date, code, predicted, actual, fold_id]
        alpha: EMA衰减系数，越大越贴近原始信号

    Returns:
        DataFrame [trade_date, code, score] 用smoothed score
    """
    df = oos_df.sort_values(["code", "trade_date"]).copy()

    smoothed = []
    for code, group in df.groupby("code"):
        scores = group["predicted"].values
        dates = group["trade_date"].values

        ema = np.empty_like(scores)
        ema[0] = scores[0]
        for i in range(1, len(scores)):
            ema[i] = alpha * scores[i] + (1 - alpha) * ema[i - 1]

        for i in range(len(scores)):
            smoothed.append({
                "trade_date": dates[i],
                "code": code,
                "score": ema[i],
            })

    result = pd.DataFrame(smoothed)
    logger.info(f"EMA平滑(alpha={alpha}): {len(result)}行")
    return result


# ==============================================================
# 方案B: 持仓惯性
# ==============================================================
def apply_holding_inertia(
    oos_df: pd.DataFrame,
    trade_dates: list[date],
    bonus_std: float,
    safety_valve_top_n: int = 0,
) -> pd.DataFrame:
    """已在Top-N中的股票加bonus分，降低被换出概率。

    在每个月度调仓日，对上期持仓的股票加bonus（以截面标准差为单位）。

    Args:
        oos_df: [trade_date, code, predicted, actual, fold_id]
        trade_dates: 交易日列表
        bonus_std: 加分量（截面标准差的倍数）
        safety_valve_top_n: 安全阀。如果>0，原始排名跌出此阈值的股票不加bonus，
            强制卖出（防止持有已失去alpha的股票）。0=不启用。

    Returns:
        DataFrame [trade_date, code, score]
    """
    rebalance_dates = _get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(oos_df["trade_date"].unique())
    available_rebal = [d for d in rebalance_dates if d in signal_dates]

    results = []
    prev_holdings = set()

    for rebal_date in available_rebal:
        day_df = oos_df[oos_df["trade_date"] == rebal_date].copy()
        raw_scores = day_df["predicted"].values
        cs_std = np.std(raw_scores) if len(raw_scores) > 1 else 1.0

        # 安全阀: 确定哪些持仓股票的原始排名仍在阈值内
        eligible_for_bonus = prev_holdings
        if safety_valve_top_n > 0 and prev_holdings:
            # 按原始分数排名
            day_df_sorted = day_df.sort_values("predicted", ascending=False)
            top_n_codes = set(day_df_sorted.head(safety_valve_top_n)["code"].values)
            eligible_for_bonus = prev_holdings & top_n_codes

        # 加持仓惯性bonus
        adjusted = raw_scores.copy()
        codes = day_df["code"].values
        for i, code in enumerate(codes):
            if code in eligible_for_bonus:
                adjusted[i] += bonus_std * cs_std

        day_df["score"] = adjusted

        # 更新holdings
        top = day_df.nlargest(TOP_N, "score")
        prev_holdings = set(top["code"].values)

        results.append(day_df[["trade_date", "code", "score"]])

    result = pd.concat(results, ignore_index=True) if results else pd.DataFrame(
        columns=["trade_date", "code", "score"]
    )
    sv_label = f"+SV{safety_valve_top_n}" if safety_valve_top_n > 0 else ""
    logger.info(f"持仓惯性(bonus={bonus_std}σ{sv_label}): {len(result)}行, "
                f"{result['trade_date'].nunique()}调仓日")
    return result


# ==============================================================
# 方案C: EMA + 持仓惯性组合
# ==============================================================
def apply_ema_plus_inertia(
    oos_df: pd.DataFrame,
    trade_dates: list[date],
    alpha: float,
    bonus_std: float,
    safety_valve_top_n: int = 0,
) -> pd.DataFrame:
    """先EMA平滑再加持仓惯性。

    Step 1: EMA平滑每只股票的predicted score
    Step 2: 在调仓日对上期持仓加bonus（以平滑后截面std为单位）

    Args:
        oos_df: [trade_date, code, predicted, actual, fold_id]
        trade_dates: 交易日列表
        alpha: EMA衰减系数
        bonus_std: 持仓惯性加分（截面std倍数）
        safety_valve_top_n: 安全阀阈值（0=不启用）

    Returns:
        DataFrame [trade_date, code, score]
    """
    # Step 1: EMA平滑
    ema_df = apply_ema_smoothing(oos_df, alpha=alpha)
    # ema_df has [trade_date, code, score]

    # Step 2: 在调仓日加持仓惯性
    rebalance_dates = _get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(ema_df["trade_date"].unique())
    available_rebal = [d for d in rebalance_dates if d in signal_dates]

    results = []
    prev_holdings = set()

    for rebal_date in available_rebal:
        day_df = ema_df[ema_df["trade_date"] == rebal_date].copy()
        smoothed_scores = day_df["score"].values
        cs_std = np.std(smoothed_scores) if len(smoothed_scores) > 1 else 1.0

        # 安全阀
        eligible_for_bonus = prev_holdings
        if safety_valve_top_n > 0 and prev_holdings:
            day_df_sorted = day_df.sort_values("score", ascending=False)
            top_n_codes = set(day_df_sorted.head(safety_valve_top_n)["code"].values)
            eligible_for_bonus = prev_holdings & top_n_codes

        # 加bonus
        adjusted = smoothed_scores.copy()
        codes = day_df["code"].values
        for i, code in enumerate(codes):
            if code in eligible_for_bonus:
                adjusted[i] += bonus_std * cs_std

        day_df["score"] = adjusted
        top = day_df.nlargest(TOP_N, "score")
        prev_holdings = set(top["code"].values)

        results.append(day_df[["trade_date", "code", "score"]])

    result = pd.concat(results, ignore_index=True) if results else pd.DataFrame(
        columns=["trade_date", "code", "score"]
    )
    sv_label = f"+SV{safety_valve_top_n}" if safety_valve_top_n > 0 else ""
    logger.info(f"EMA({alpha})+Inertia({bonus_std}σ{sv_label}): {len(result)}行, "
                f"{result['trade_date'].nunique()}调仓日")
    return result


# ==============================================================
# 组合构建（复用evaluate_lgb_vs_baseline逻辑）
# ==============================================================
def _get_monthly_rebalance_dates(trade_dates: list[date]) -> list[date]:
    """获取每月第一个交易日。"""
    rebal_dates = []
    current_month = None
    for d in trade_dates:
        ym = (d.year, d.month)
        if ym != current_month:
            rebal_dates.append(d)
            current_month = ym
    return rebal_dates


def build_portfolio_returns(
    signal_df: pd.DataFrame,
    returns_pivot: pd.DataFrame,
    trade_dates: list[date],
    signal_col: str = "score",
    top_n: int = TOP_N,
    cost: float = COST_ONE_WAY,
) -> tuple[pd.DataFrame, dict]:
    """构建月度调仓Top-N等权组合，返回日频收益和换手统计。

    Returns:
        (daily_returns_df, turnover_stats)
    """
    rebalance_dates = _get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(signal_df["trade_date"].unique())
    available_rebal = [d for d in rebalance_dates if d in signal_dates]

    if not available_rebal:
        return pd.DataFrame(columns=["trade_date", "portfolio_return"]), {}

    daily_returns = []
    prev_holdings = set()
    turnovers = []

    for i, rebal_date in enumerate(available_rebal):
        day_signals = signal_df[signal_df["trade_date"] == rebal_date].copy()
        day_signals = day_signals.sort_values(signal_col, ascending=False)
        top_stocks = day_signals.head(top_n)["code"].tolist()

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
            next_rebal_idx = (trade_dates.index(next_rebal)
                              if next_rebal in trade_dates else len(trade_dates) - 1)
            hold_end_idx = next_rebal_idx
        else:
            hold_end_idx = len(trade_dates)

        new_holdings = set(top_stocks)
        turnover = (len(new_holdings.symmetric_difference(prev_holdings)) / (2 * top_n)
                    if prev_holdings else 1.0)
        turnovers.append(turnover)
        rebal_cost = turnover * cost * 2

        for day_idx in range(hold_start_idx, hold_end_idx):
            td = trade_dates[day_idx]
            if td not in returns_pivot.index:
                continue
            day_ret = returns_pivot.loc[td]
            stock_rets = [day_ret[s] for s in top_stocks
                          if s in day_ret.index and not np.isnan(day_ret[s])]
            port_ret = np.mean(stock_rets) if stock_rets else 0.0
            if day_idx == hold_start_idx:
                port_ret -= rebal_cost
            daily_returns.append({"trade_date": td, "portfolio_return": port_ret})

        prev_holdings = new_holdings

    ret_df = pd.DataFrame(daily_returns)

    # 换手统计
    avg_turnover = np.mean(turnovers) if turnovers else 0
    ann_turnover = avg_turnover * 12  # 月度调仓 * 12
    turnover_stats = {
        "avg_monthly_turnover": avg_turnover,
        "ann_turnover_pct": ann_turnover * 100,
        "n_rebalances": len(turnovers),
        "turnovers": turnovers,
    }
    return ret_df, turnover_stats


# ==============================================================
# 绩效计算
# ==============================================================
def calc_metrics(daily_rets: np.ndarray) -> dict:
    """计算核心绩效指标。"""
    if len(daily_rets) == 0:
        return {}
    total_ret = np.prod(1 + daily_rets) - 1
    n_years = len(daily_rets) / 252.0
    ann_ret = (1 + total_ret) ** (1.0 / n_years) - 1 if n_years > 0 else 0
    ann_sharpe = (np.mean(daily_rets) / np.std(daily_rets, ddof=1) * np.sqrt(252)
                  if np.std(daily_rets, ddof=1) > 0 else 0)
    cum = np.cumprod(1 + daily_rets)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum / running_max - 1
    mdd = float(np.min(drawdowns))
    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-10 else 0

    return {
        "ann_return": ann_ret,
        "ann_sharpe": ann_sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "total_return": total_ret,
        "n_days": len(daily_rets),
    }


def paired_block_bootstrap(
    lgb_rets: np.ndarray,
    base_rets: np.ndarray,
    n_boot: int = 10000,
    block_size: int = 20,
    seed: int = 42,
) -> dict:
    """Paired block bootstrap: H0: smoothed Sharpe <= raw Sharpe."""
    rng = np.random.RandomState(seed)
    T = min(len(lgb_rets), len(base_rets))
    lgb_rets = lgb_rets[:T]
    base_rets = base_rets[:T]

    d = lgb_rets - base_rets
    orig_diff_sharpe = (np.mean(d) / np.std(d, ddof=1) * np.sqrt(252)
                        if np.std(d, ddof=1) > 0 else 0)

    n_blocks = int(np.ceil(T / block_size))
    boot_sharpes = np.zeros(n_boot)

    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        d_boot = d[indices]
        std_boot = np.std(d_boot, ddof=1)
        if std_boot > 1e-12:
            boot_sharpes[b] = np.mean(d_boot) / std_boot * np.sqrt(252)
        else:
            boot_sharpes[b] = 0.0

    p_value = np.mean(boot_sharpes <= 0)
    ci_lo = np.percentile(boot_sharpes, 2.5)
    ci_hi = np.percentile(boot_sharpes, 97.5)

    return {
        "orig_diff_sharpe": orig_diff_sharpe,
        "p_value": p_value,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
    }


def calc_yearly_metrics(ret_df: pd.DataFrame) -> pd.DataFrame:
    """年度分解。"""
    ret_df = ret_df.copy()
    ret_df["year"] = [d.year for d in ret_df["trade_date"]]
    rows = []
    for year, group in ret_df.groupby("year"):
        rets = group["portfolio_return"].values
        m = calc_metrics(rets)
        m["year"] = year
        rows.append(m)
    return pd.DataFrame(rows)


# ==============================================================
# 主流程
# ==============================================================
def run_experiment(
    label: str,
    signal_df: pd.DataFrame,
    returns_pivot: pd.DataFrame,
    trade_dates: list[date],
) -> dict:
    """运行单个实验，返回完整结果。"""
    ret_df, turnover_stats = build_portfolio_returns(
        signal_df, returns_pivot, trade_dates
    )

    if ret_df.empty:
        logger.warning(f"[{label}] 无收益数据！")
        return {"label": label, "metrics": {}, "turnover": {}}

    rets = ret_df["portfolio_return"].values
    metrics = calc_metrics(rets)
    yearly = calc_yearly_metrics(ret_df)

    logger.info(f"\n{'='*60}")
    logger.info(f"[{label}]")
    logger.info(f"  Sharpe:   {metrics['ann_sharpe']:.3f}")
    logger.info(f"  AnnRet:   {metrics['ann_return']:.2%}")
    logger.info(f"  MDD:      {metrics['mdd']:.2%}")
    logger.info(f"  Calmar:   {metrics['calmar']:.3f}")
    logger.info(f"  换手率:   {turnover_stats['ann_turnover_pct']:.1f}% (年化)")
    logger.info(f"  月均换手: {turnover_stats['avg_monthly_turnover']:.1%}")
    logger.info(f"  调仓次数: {turnover_stats['n_rebalances']}")
    logger.info(f"  交易天数: {metrics['n_days']}")
    logger.info("  年度分解:")
    for _, row in yearly.iterrows():
        logger.info(f"    {int(row['year'])}: Sharpe={row['ann_sharpe']:.3f} "
                     f"Ret={row['ann_return']:.2%} MDD={row['mdd']:.2%}")

    return {
        "label": label,
        "metrics": metrics,
        "turnover": turnover_stats,
        "yearly": yearly,
        "daily_rets": rets,
        "ret_df": ret_df,
    }


def main():
    t0 = time.time()

    # 加载数据
    oos_df = load_oos_predictions()
    conn = get_conn()
    try:
        price_df = load_price_data(conn, OOS_START, OOS_END)
        trade_dates = load_trade_dates(conn, OOS_START, OOS_END)
    finally:
        conn.close()

    returns_pivot = price_df.pivot(
        index="trade_date", columns="code", values="adj_close"
    ).pct_change().iloc[1:]

    # 构建原始LightGBM信号（无平滑，作为baseline）
    raw_signal = oos_df[["trade_date", "code", "predicted"]].copy()
    raw_signal = raw_signal.rename(columns={"predicted": "score"})

    results = []

    # === Baseline: 原始LightGBM ===
    logger.info("\n" + "=" * 70)
    logger.info("BASELINE: 原始LightGBM（无平滑）")
    logger.info("=" * 70)
    raw_result = run_experiment("Raw LGB", raw_signal, returns_pivot, trade_dates)
    results.append(raw_result)
    raw_rets = raw_result["daily_rets"]

    # === 纯Inertia: 0.7σ, 1.0σ, 1.5σ, 2.0σ ===
    for bonus in [0.7, 1.0, 1.5, 2.0]:
        logger.info("\n" + "=" * 70)
        logger.info(f"纯Inertia bonus={bonus}σ")
        logger.info("=" * 70)
        inertia_signal = apply_holding_inertia(
            oos_df, trade_dates, bonus_std=bonus
        )
        results.append(run_experiment(
            f"Inertia({bonus}σ)", inertia_signal, returns_pivot, trade_dates
        ))

    # === EMA(0.3) + Inertia(0.7σ) ===
    logger.info("\n" + "=" * 70)
    logger.info("方案C: EMA(0.3)+Inertia(0.7σ)")
    logger.info("=" * 70)
    combo1 = apply_ema_plus_inertia(
        oos_df, trade_dates, alpha=0.3, bonus_std=0.7,
    )
    results.append(run_experiment(
        "EMA0.3+Inr0.7σ", combo1, returns_pivot, trade_dates
    ))

    # === EMA(0.3) + Inertia(1.0σ) ===
    logger.info("\n" + "=" * 70)
    logger.info("方案C: EMA(0.3)+Inertia(1.0σ)")
    logger.info("=" * 70)
    combo2 = apply_ema_plus_inertia(
        oos_df, trade_dates, alpha=0.3, bonus_std=1.0,
    )
    results.append(run_experiment(
        "EMA0.3+Inr1.0σ", combo2, returns_pivot, trade_dates
    ))

    # === Paired Block Bootstrap: 每个方案 vs Raw LGB ===
    logger.info("\n" + "=" * 70)
    logger.info("Paired Block Bootstrap (block=20, n=10000) vs Raw LGB")
    logger.info("=" * 70)
    for r in results[1:]:  # skip Raw LGB itself
        smoothed_rets = r["daily_rets"]
        if len(smoothed_rets) == 0:
            continue
        boot = paired_block_bootstrap(smoothed_rets, raw_rets)
        r["bootstrap"] = boot
        sig = "***" if boot["p_value"] < 0.01 else "**" if boot["p_value"] < 0.05 else "*" if boot["p_value"] < 0.10 else ""
        logger.info(
            f"  {r['label']:<25} "
            f"ΔSharpe={boot['orig_diff_sharpe']:+.3f}  "
            f"p={boot['p_value']:.4f}{sig}  "
            f"95%CI=[{boot['ci_lo']:.3f}, {boot['ci_hi']:.3f}]"
        )

    # === 汇总对比表 ===
    logger.info("\n" + "=" * 70)
    logger.info("汇总对比")
    logger.info("=" * 70)

    header = f"{'方案':<25} {'Sharpe':>8} {'AnnRet':>8} {'MDD':>8} {'Calmar':>8} {'换手率%':>8} {'p-value':>8}"
    logger.info(header)
    logger.info("-" * len(header))
    for r in results:
        m = r["metrics"]
        t = r["turnover"]
        if not m:
            continue
        boot = r.get("bootstrap", {})
        p_str = f"{boot['p_value']:.4f}" if boot else "  base"
        logger.info(
            f"{r['label']:<25} "
            f"{m['ann_sharpe']:>8.3f} "
            f"{m['ann_return']:>7.2%} "
            f"{m['mdd']:>7.2%} "
            f"{m['calmar']:>8.3f} "
            f"{t.get('ann_turnover_pct', 0):>7.1f} "
            f"{p_str:>8}"
        )

    # === 保存日收益率到CSV ===
    csv_path = project_root / "models" / "smoothing_daily_returns.csv"
    frames = []
    for r in results:
        if r.get("ret_df") is not None and not r["ret_df"].empty:
            df_tmp = r["ret_df"][["trade_date", "portfolio_return"]].copy()
            df_tmp["scheme"] = r["label"]
            frames.append(df_tmp)
    if frames:
        all_rets = pd.concat(frames, ignore_index=True)
        all_rets.to_csv(csv_path, index=False)
        logger.info(f"\n日收益率已保存: {csv_path} ({len(all_rets)}行)")

    elapsed = time.time() - t0
    logger.info(f"\n总耗时: {elapsed:.1f}秒")

    return results


if __name__ == "__main__":
    results = main()
