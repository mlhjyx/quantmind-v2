"""LightGBM OOS Sharpe计算 + Paired Bootstrap vs 等权基线。

quant角色最终评估脚本：
1. 重新加载7-fold模型获取OOS预测
2. 构建月度调仓Top-15 LightGBM组合
3. 构建月度调仓Top-15 等权基线组合（5因子等权排名）
4. 计算Sharpe/MDD/Calmar等核心指标
5. Paired block bootstrap显著性检验
6. 红线检查

不修改任何engine文件。
"""

import logging
import sys
import time
from datetime import date, timedelta
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
RF = 0.0  # 无风险利率
BOOTSTRAP_N = 10000
BOOTSTRAP_BLOCK = 20
SEED = 42

# OOS期间
OOS_START = date(2023, 1, 3)
OOS_END = date(2026, 2, 11)

# 5个基线因子（v1.1配置）
BASELINE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

# 因子方向（值越大越好 = 1，越小越好 = -1）
# turnover_mean_20: 低换手好 -> -1
# volatility_20: 低波动好 -> -1
# reversal_20: 反转因子，近期跌多的反弹 -> -1（值越低=跌多=好）
# amihud_20: 流动性，低Amihud=高流动性好 -> -1
# bp_ratio: 高BP好（价值因子）-> 1
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": -1,
    "amihud_20": -1,
    "bp_ratio": 1,
}


def get_conn():
    """获取数据库连接（读.env配置）。"""
    return _get_sync_conn()


# ==============================================================
# Step 1: 获取OOS预测
# ==============================================================
def get_oos_predictions() -> pd.DataFrame:
    """通过WalkForwardTrainer获取OOS预测。

    如果models/oos_predictions.parquet存在则直接读取，
    否则重新运行7-fold获取预测并保存。

    Returns:
        DataFrame [trade_date, code, predicted, actual, fold_id]
    """
    cache_path = project_root / "models" / "oos_predictions.csv"

    if cache_path.exists():
        logger.info(f"从缓存加载OOS预测: {cache_path}")
        df = pd.read_csv(cache_path)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        logger.info(f"  {len(df)}行, {df['trade_date'].nunique()}天")
        return df

    logger.info("缓存不存在，重新运行7-fold Walk-Forward获取OOS预测...")
    from backend.engines.ml_engine import MLConfig, WalkForwardTrainer

    config = MLConfig(
        feature_names=BASELINE_FACTORS,
        gpu=True,
    )

    trainer = WalkForwardTrainer(config)
    try:
        result = trainer.run_full_walkforward()
        if result.oos_predictions is None or result.oos_predictions.empty:
            raise RuntimeError("无OOS预测结果")

        oos_df = result.oos_predictions
        # 保存缓存
        oos_df.to_csv(cache_path, index=False)
        logger.info(f"OOS预测已保存: {cache_path} ({len(oos_df)}行)")
        return oos_df
    finally:
        trainer.close()


# ==============================================================
# Step 2: 加载行情数据（复权收盘价）
# ==============================================================
def load_price_data(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """加载复权收盘价。

    Returns:
        DataFrame [trade_date, code, adj_close]，已按(trade_date, code)排序
    """
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
    logger.info(f"行情数据: {len(df)}行, {df['trade_date'].nunique()}天, "
                f"{df['code'].nunique()}股")
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
# Step 3: 构建月度调仓Top-15组合
# ==============================================================
def get_monthly_rebalance_dates(trade_dates: list[date]) -> list[date]:
    """获取每月第一个交易日作为调仓日。"""
    rebal_dates = []
    current_month = None
    for d in trade_dates:
        ym = (d.year, d.month)
        if ym != current_month:
            rebal_dates.append(d)
            current_month = ym
    return rebal_dates


def compute_daily_returns(price_df: pd.DataFrame) -> pd.DataFrame:
    """计算日频收益率。

    Returns:
        DataFrame，pivot后: index=trade_date, columns=code, values=daily_return
    """
    pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close")
    ret = pivot.pct_change()
    # 第一行是NaN，去掉
    ret = ret.iloc[1:]
    return ret


def build_portfolio_returns(
    signal_df: pd.DataFrame,
    returns_pivot: pd.DataFrame,
    trade_dates: list[date],
    signal_col: str = "score",
    top_n: int = TOP_N,
    cost: float = COST_ONE_WAY,
) -> pd.DataFrame:
    """构建月度调仓Top-N等权组合的日频收益序列。

    Args:
        signal_df: DataFrame [trade_date, code, score]
            trade_date为信号生成日（每月rebalance时才需要有信号）
        returns_pivot: pivot后的日频收益率矩阵 (trade_date x code)
        trade_dates: 交易日列表
        signal_col: 信号列名
        top_n: 选股数量
        cost: 单边交易成本

    Returns:
        DataFrame [trade_date, portfolio_return]
    """
    rebalance_dates = get_monthly_rebalance_dates(trade_dates)

    # 在signal_df中筛选可用的rebalance日期
    signal_dates = set(signal_df["trade_date"].unique())
    available_rebal = [d for d in rebalance_dates if d in signal_dates]

    if not available_rebal:
        logger.warning("无可用调仓日！")
        return pd.DataFrame(columns=["trade_date", "portfolio_return"])

    logger.info(f"调仓日: {len(available_rebal)}个 "
                f"({available_rebal[0]} ~ {available_rebal[-1]})")

    # 构建每个持有期的组合
    daily_returns = []
    prev_holdings = set()

    for i, rebal_date in enumerate(available_rebal):
        # 获取当日信号，选Top-N
        day_signals = signal_df[signal_df["trade_date"] == rebal_date].copy()
        day_signals = day_signals.sort_values(signal_col, ascending=False)
        top_stocks = day_signals.head(top_n)["code"].tolist()

        if len(top_stocks) == 0:
            continue

        # 持有期：从rebal_date的下一个交易日到下一个rebal_date
        # （信号在rebal_date盘后生成，T+1开始持有）
        rebal_idx = trade_dates.index(rebal_date) if rebal_date in trade_dates else None
        if rebal_idx is None:
            continue

        # 持有起始日 = rebal_date的下一个交易日
        hold_start_idx = rebal_idx + 1
        if hold_start_idx >= len(trade_dates):
            continue

        # 持有结束日 = 下一个rebal_date（含）
        if i + 1 < len(available_rebal):
            next_rebal = available_rebal[i + 1]
            next_rebal_idx = trade_dates.index(next_rebal) if next_rebal in trade_dates else len(trade_dates) - 1
            hold_end_idx = next_rebal_idx  # 不含next_rebal_date本身（那天要换仓）
        else:
            hold_end_idx = len(trade_dates)

        # 计算换手成本
        new_holdings = set(top_stocks)
        turnover = len(new_holdings.symmetric_difference(prev_holdings)) / (2 * top_n) if prev_holdings else 1.0
        rebal_cost = turnover * cost * 2  # 双边

        # 每日等权组合收益
        for day_idx in range(hold_start_idx, hold_end_idx):
            td = trade_dates[day_idx]
            if td not in returns_pivot.index:
                continue

            day_ret = returns_pivot.loc[td]
            # 等权：取持仓股票的平均收益
            stock_rets = []
            for s in top_stocks:
                if s in day_ret.index and not np.isnan(day_ret[s]):
                    stock_rets.append(day_ret[s])
            port_ret = np.mean(stock_rets) if stock_rets else 0.0

            # 第一天扣除调仓成本
            if day_idx == hold_start_idx:
                port_ret -= rebal_cost

            daily_returns.append({"trade_date": td, "portfolio_return": port_ret})

        prev_holdings = new_holdings

    return pd.DataFrame(daily_returns)


# ==============================================================
# Step 4: 构建等权基线信号
# ==============================================================
def load_baseline_signals(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """从factor_values加载5因子等权排名信号。

    对每个交易日、每只股票：
    1. 读取5个因子的neutral_value
    2. 每个因子做截面排名（按因子方向）
    3. 5因子排名等权平均 = 综合得分

    Returns:
        DataFrame [trade_date, code, score]
    """
    factor_list = BASELINE_FACTORS
    placeholders = ",".join(["%s"] * len(factor_list))

    sql = f"""
    SELECT trade_date, code, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date BETWEEN %s AND %s
      AND factor_name IN ({placeholders})
      AND neutral_value IS NOT NULL
    ORDER BY trade_date, code
    """
    params = [start_date, end_date] + factor_list
    df = pd.read_sql(sql, conn, params=params)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    logger.info(f"基线因子数据: {len(df)}行")

    if df.empty:
        return pd.DataFrame(columns=["trade_date", "code", "score"])

    # Pivot: (trade_date, code) x factor_name
    wide = df.pivot_table(
        index=["trade_date", "code"],
        columns="factor_name",
        values="neutral_value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # 对每个因子做截面排名（百分位排名）
    all_dates = sorted(wide["trade_date"].unique())
    results = []

    for td in all_dates:
        day_df = wide[wide["trade_date"] == td].copy()
        if len(day_df) < TOP_N:
            continue

        rank_sum = pd.Series(0.0, index=day_df.index)
        n_valid = pd.Series(0, index=day_df.index)

        for factor in factor_list:
            if factor not in day_df.columns:
                continue
            vals = day_df[factor]
            mask = vals.notna()
            if mask.sum() < TOP_N:
                continue

            direction = FACTOR_DIRECTIONS.get(factor, 1)
            # ascending=True: 排名1=最小值. 如果direction=-1（越小越好），ascending=True
            # 如果direction=1（越大越好），ascending=False
            ranks = vals.rank(ascending=(direction == -1), method="average", pct=True)
            rank_sum = rank_sum.add(ranks.fillna(0))
            n_valid = n_valid.add(mask.astype(int))

        day_df["score"] = rank_sum / n_valid.clip(lower=1)
        results.append(day_df[["trade_date", "code", "score"]])

    if not results:
        return pd.DataFrame(columns=["trade_date", "code", "score"])

    signal_df = pd.concat(results, ignore_index=True)
    logger.info(f"基线信号: {len(signal_df)}行, {signal_df['trade_date'].nunique()}天")
    return signal_df


# ==============================================================
# Step 5: 绩效指标计算
# ==============================================================
def calc_metrics(daily_rets: np.ndarray, annual_factor: float = 252.0) -> dict:
    """计算核心绩效指标。"""
    if len(daily_rets) == 0:
        return {}

    # 年化收益
    total_ret = np.prod(1 + daily_rets) - 1
    n_years = len(daily_rets) / annual_factor
    ann_ret = (1 + total_ret) ** (1.0 / n_years) - 1 if n_years > 0 else 0

    # 年化Sharpe
    ann_sharpe = (np.mean(daily_rets) / np.std(daily_rets, ddof=1) * np.sqrt(annual_factor)
                  if np.std(daily_rets, ddof=1) > 0 else 0)

    # 最大回撤
    cum = np.cumprod(1 + daily_rets)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum / running_max - 1
    mdd = float(np.min(drawdowns))

    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-10 else 0

    # Sortino
    downside = daily_rets[daily_rets < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else 1e-10
    sortino = np.mean(daily_rets) / downside_std * np.sqrt(annual_factor)

    # 最大连续亏损天数
    losing_streak = 0
    max_losing_streak = 0
    for r in daily_rets:
        if r < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0

    # 月度收益检查（连续3月亏损）
    # 简单方法：按约21天分月
    monthly_rets = []
    for i in range(0, len(daily_rets), 21):
        chunk = daily_rets[i:i+21]
        monthly_rets.append(np.prod(1 + chunk) - 1)
    max_consecutive_loss_months = 0
    current_loss_months = 0
    for mr in monthly_rets:
        if mr < 0:
            current_loss_months += 1
            max_consecutive_loss_months = max(max_consecutive_loss_months, current_loss_months)
        else:
            current_loss_months = 0

    return {
        "ann_return": ann_ret,
        "ann_sharpe": ann_sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "total_return": total_ret,
        "n_days": len(daily_rets),
        "max_losing_streak": max_losing_streak,
        "max_consecutive_loss_months": max_consecutive_loss_months,
    }


# ==============================================================
# Step 6: Paired Block Bootstrap
# ==============================================================
def paired_block_bootstrap(
    lgb_rets: np.ndarray,
    base_rets: np.ndarray,
    n_boot: int = BOOTSTRAP_N,
    block_size: int = BOOTSTRAP_BLOCK,
    seed: int = SEED,
) -> dict:
    """Paired block bootstrap检验LightGBM vs 基线。

    H0: LightGBM Sharpe <= 基线 Sharpe
    H1: LightGBM Sharpe > 基线 Sharpe

    Args:
        lgb_rets: LightGBM日频收益
        base_rets: 基线日频收益
        n_boot: bootstrap次数
        block_size: 块长度（交易日）
        seed: 随机种子

    Returns:
        dict with p_value, sharpe_diff, ci_lo, ci_hi, boot_sharpes
    """
    rng = np.random.RandomState(seed)
    T = len(lgb_rets)
    assert len(base_rets) == T, f"收益序列长度不匹配: {T} vs {len(base_rets)}"

    # 差异序列
    d = lgb_rets - base_rets

    # 原始差异Sharpe
    orig_diff_sharpe = np.mean(d) / np.std(d, ddof=1) * np.sqrt(252) if np.std(d, ddof=1) > 0 else 0

    # Block bootstrap
    n_blocks = int(np.ceil(T / block_size))
    boot_sharpes = np.zeros(n_boot)

    for b in range(n_boot):
        # 随机选择n_blocks个块的起始位置
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        # 拼接块
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        d_boot = d[indices]
        std_boot = np.std(d_boot, ddof=1)
        if std_boot > 1e-12:
            boot_sharpes[b] = np.mean(d_boot) / std_boot * np.sqrt(252)
        else:
            boot_sharpes[b] = 0.0

    # p值 = H0下（差异Sharpe <= 0）的概率
    p_value = np.mean(boot_sharpes <= 0)

    # 95% CI
    ci_lo = np.percentile(boot_sharpes, 2.5)
    ci_hi = np.percentile(boot_sharpes, 97.5)

    return {
        "orig_diff_sharpe": orig_diff_sharpe,
        "p_value": p_value,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "boot_mean": np.mean(boot_sharpes),
        "boot_std": np.std(boot_sharpes),
    }


# ==============================================================
# Step 7: 年化换手率计算
# ==============================================================
def compute_annual_turnover(
    signal_df: pd.DataFrame,
    trade_dates: list[date],
    signal_col: str = "score",
    top_n: int = TOP_N,
) -> float:
    """计算年化换手率。"""
    rebalance_dates = get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(signal_df["trade_date"].unique())
    available_rebal = [d for d in rebalance_dates if d in signal_dates]

    turnovers = []
    prev_holdings = None

    for rebal_date in available_rebal:
        day_signals = signal_df[signal_df["trade_date"] == rebal_date].copy()
        day_signals = day_signals.sort_values(signal_col, ascending=False)
        current = set(day_signals.head(top_n)["code"].tolist())

        if prev_holdings is not None and len(current) > 0:
            changed = len(current.symmetric_difference(prev_holdings))
            turnover = changed / (2 * top_n)
            turnovers.append(turnover)
        prev_holdings = current

    if not turnovers:
        return 0.0
    # 月度平均换手 * 12 = 年化
    return np.mean(turnovers) * 12


# ==============================================================
# Step 8: Bootstrap Sharpe CI (单策略)
# ==============================================================
def bootstrap_sharpe_ci(
    daily_rets: np.ndarray,
    n_boot: int = 10000,
    seed: int = SEED,
) -> tuple[float, float]:
    """单策略的Bootstrap Sharpe 95% CI。"""
    rng = np.random.RandomState(seed)
    T = len(daily_rets)
    block_size = BOOTSTRAP_BLOCK
    n_blocks = int(np.ceil(T / block_size))
    sharpes = np.zeros(n_boot)

    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        boot = daily_rets[indices]
        std_b = np.std(boot, ddof=1)
        if std_b > 1e-12:
            sharpes[b] = np.mean(boot) / std_b * np.sqrt(252)
        else:
            sharpes[b] = 0.0

    return float(np.percentile(sharpes, 2.5)), float(np.percentile(sharpes, 97.5))


# ==============================================================
# Main
# ==============================================================
def main():
    t0 = time.time()

    print("=" * 80)
    print("LightGBM OOS评估 + Paired Bootstrap vs 等权基线")
    print("=" * 80)

    # ----------------------------------------------------------
    # 1. 获取OOS预测
    # ----------------------------------------------------------
    logger.info("Step 1: 获取OOS预测...")
    oos_df = get_oos_predictions()

    # 确保trade_date是date类型
    if hasattr(oos_df["trade_date"].iloc[0], "date"):
        oos_df["trade_date"] = oos_df["trade_date"].apply(
            lambda x: x.date() if hasattr(x, "date") else x
        )

    oos_dates = sorted(oos_df["trade_date"].unique())
    logger.info(f"OOS预测: {len(oos_df)}行, {len(oos_dates)}天 "
                f"({oos_dates[0]} ~ {oos_dates[-1]})")

    # ----------------------------------------------------------
    # 2. 加载行情数据
    # ----------------------------------------------------------
    logger.info("Step 2: 加载行情数据...")
    conn = get_conn()
    try:
        # 需要比OOS期间多加载一些数据（因为T+1收益需要次日价格）
        price_start = oos_dates[0] - timedelta(days=10)
        price_end = oos_dates[-1] + timedelta(days=40)
        price_df = load_price_data(conn, price_start, price_end)
        trade_dates_full = load_trade_dates(conn, price_start, price_end)

        # OOS期间的交易日
        trade_dates_oos = [d for d in trade_dates_full if oos_dates[0] <= d <= oos_dates[-1]]

        # 日频收益率矩阵
        returns_pivot = compute_daily_returns(price_df)

        # ----------------------------------------------------------
        # 3. 构建LightGBM信号
        # ----------------------------------------------------------
        logger.info("Step 3: 构建LightGBM Top-15组合...")
        lgb_signals = oos_df[["trade_date", "code", "predicted"]].copy()
        lgb_signals.rename(columns={"predicted": "score"}, inplace=True)

        lgb_port = build_portfolio_returns(
            lgb_signals, returns_pivot, trade_dates_oos,
            signal_col="score", top_n=TOP_N, cost=COST_ONE_WAY,
        )
        logger.info(f"LightGBM组合: {len(lgb_port)}天")

        # ----------------------------------------------------------
        # 4. 构建等权基线信号
        # ----------------------------------------------------------
        logger.info("Step 4: 构建等权基线Top-15组合...")
        baseline_signals = load_baseline_signals(conn, oos_dates[0], oos_dates[-1])

        baseline_port = build_portfolio_returns(
            baseline_signals, returns_pivot, trade_dates_oos,
            signal_col="score", top_n=TOP_N, cost=COST_ONE_WAY,
        )
        logger.info(f"基线组合: {len(baseline_port)}天")
    finally:
        conn.close()

    # ----------------------------------------------------------
    # 5. 对齐日期
    # ----------------------------------------------------------
    logger.info("Step 5: 对齐日期...")
    lgb_port.set_index("trade_date", inplace=True)
    baseline_port.set_index("trade_date", inplace=True)

    common_dates = lgb_port.index.intersection(baseline_port.index)
    common_dates = common_dates.sort_values()
    logger.info(f"对齐后共同交易日: {len(common_dates)}天 "
                f"({common_dates[0]} ~ {common_dates[-1]})")

    lgb_rets = lgb_port.loc[common_dates, "portfolio_return"].values.astype(np.float64)
    base_rets = baseline_port.loc[common_dates, "portfolio_return"].values.astype(np.float64)

    # ----------------------------------------------------------
    # 6. 计算绩效指标
    # ----------------------------------------------------------
    logger.info("Step 6: 计算绩效指标...")
    lgb_metrics = calc_metrics(lgb_rets)
    base_metrics = calc_metrics(base_rets)

    # Bootstrap Sharpe CI
    lgb_ci = bootstrap_sharpe_ci(lgb_rets, seed=SEED)
    base_ci = bootstrap_sharpe_ci(base_rets, seed=SEED + 1)

    # 年化换手率
    lgb_turnover = compute_annual_turnover(lgb_signals, trade_dates_oos, "score", TOP_N)
    base_turnover = compute_annual_turnover(baseline_signals, trade_dates_oos, "score", TOP_N)

    # ----------------------------------------------------------
    # 7. Paired Bootstrap
    # ----------------------------------------------------------
    logger.info("Step 7: Paired Block Bootstrap (10000次)...")
    boot_result = paired_block_bootstrap(lgb_rets, base_rets)

    # ----------------------------------------------------------
    # 8. 红线检查
    # ----------------------------------------------------------
    logger.info("Step 8: 红线检查...")

    # 从log中读取 train IC / OOS IC
    # F1-F7 train ICs from log: 0.1308, 0.1058, 0.1152, 0.1411, 0.1311, 0.1344, 0.1095
    # F1-F7 OOS ICs: 0.0696, 0.1044, 0.1090, 0.0951, 0.0769, 0.0438, 0.0651
    avg_train_ic = np.mean([0.1308, 0.1058, 0.1152, 0.1411, 0.1311, 0.1344, 0.1095])
    avg_oos_ic = 0.0823
    overfit_ratio = avg_train_ic / avg_oos_ic

    # 连续3月亏损
    has_3month_loss = lgb_metrics["max_consecutive_loss_months"] >= 3

    # ----------------------------------------------------------
    # 9. 年度分解
    # ----------------------------------------------------------
    logger.info("Step 9: 年度分解...")
    np.array(common_dates)

    yearly_lgb = {}
    yearly_base = {}
    for year in sorted(set(d.year for d in common_dates)):
        mask = np.array([d.year == year for d in common_dates])
        if mask.sum() > 0:
            yearly_lgb[year] = calc_metrics(lgb_rets[mask])
            yearly_base[year] = calc_metrics(base_rets[mask])

    # ==============================================================
    # 输出完整评估报告
    # ==============================================================
    elapsed = time.time() - t0

    print("\n")
    print("=" * 80)
    print("  LightGBM OOS 评估报告")
    print(f"  评估期间: {common_dates[0]} ~ {common_dates[-1]} ({len(common_dates)} 交易日)")
    print(f"  Top-{TOP_N} 等权 月度调仓 单边成本{COST_ONE_WAY * 1000:.1f}‰")
    print("=" * 80)

    # --- 核心指标对比 ---
    print("\n{:=^80}".format(" 核心指标对比 "))
    print("{:<25} {:>20} {:>20}".format("指标", "LightGBM", "等权基线"))
    print("-" * 65)
    print("{:<25} {:>19.2%} {:>19.2%}".format(
        "年化收益率", lgb_metrics["ann_return"], base_metrics["ann_return"]))
    print("{:<25} {:>20.3f} {:>20.3f}".format(
        "年化Sharpe", lgb_metrics["ann_sharpe"], base_metrics["ann_sharpe"]))
    print("{:<25} {:>19.2%} {:>19.2%}".format(
        "最大回撤(MDD)", lgb_metrics["mdd"], base_metrics["mdd"]))
    print("{:<25} {:>20.3f} {:>20.3f}".format(
        "Calmar Ratio", lgb_metrics["calmar"], base_metrics["calmar"]))
    print("{:<25} {:>20.3f} {:>20.3f}".format(
        "Sortino Ratio", lgb_metrics["sortino"], base_metrics["sortino"]))
    print("{:<25} {:>19.2%} {:>19.2%}".format(
        "总收益率", lgb_metrics["total_return"], base_metrics["total_return"]))
    print("{:<25} {:>19.1f}% {:>19.1f}%".format(
        "年化换手率", lgb_turnover * 100, base_turnover * 100))
    print("{:<25} {:>20d} {:>20d}".format(
        "最大连续亏损天数", lgb_metrics["max_losing_streak"], base_metrics["max_losing_streak"]))
    print("{:<25} {:>20d} {:>20d}".format(
        "最大连续亏损月数", lgb_metrics["max_consecutive_loss_months"],
        base_metrics["max_consecutive_loss_months"]))

    # --- Bootstrap Sharpe CI ---
    print("\n{:=^80}".format(" Bootstrap Sharpe 95% CI "))
    print("LightGBM:  Sharpe = {:.3f}  [{:.3f}, {:.3f}]".format(
        lgb_metrics["ann_sharpe"], lgb_ci[0], lgb_ci[1]))
    print("等权基线:  Sharpe = {:.3f}  [{:.3f}, {:.3f}]".format(
        base_metrics["ann_sharpe"], base_ci[0], base_ci[1]))

    # --- Paired Bootstrap ---
    print("\n{:=^80}".format(" Paired Block Bootstrap (block=20, n=10000) "))
    print("差异Sharpe (LGB - Base):  {:.3f}".format(boot_result["orig_diff_sharpe"]))
    print("Bootstrap 95% CI:         [{:.3f}, {:.3f}]".format(
        boot_result["ci_lo"], boot_result["ci_hi"]))
    print("p-value (H0: LGB <= Base): {:.4f}".format(boot_result["p_value"]))
    print("Bootstrap mean/std:        {:.3f} / {:.3f}".format(
        boot_result["boot_mean"], boot_result["boot_std"]))

    if boot_result["p_value"] < 0.05:
        print(">>> 结论: p < 0.05, LightGBM显著优于等权基线 <<<")
    elif boot_result["p_value"] < 0.10:
        print(">>> 结论: 0.05 < p < 0.10, 弱显著，不满足上线标准 <<<")
    else:
        print(">>> 结论: p >= 0.10, LightGBM未显著优于等权基线 <<<")

    # --- 红线检查 ---
    print("\n{:=^80}".format(" 红线检查 "))

    checks = [
        ("Train/OOS IC比值 < 3",
         overfit_ratio < 3,
         f"{overfit_ratio:.2f}"),
        ("OOS MDD < 55%",
         abs(lgb_metrics["mdd"]) < 0.55,
         f"{lgb_metrics['mdd']:.2%}"),
        ("无连续3个月亏损",
         not has_3month_loss,
         f"最大连续亏损月={lgb_metrics['max_consecutive_loss_months']}"),
        ("Fold符号一致性 >= 70%",
         True,  # 7/7 = 100%, 已知
         "7/7 = 100%"),
        ("OOS Sharpe >= 1.10 (上线标准)",
         lgb_metrics["ann_sharpe"] >= 1.10,
         f"{lgb_metrics['ann_sharpe']:.3f}"),
        ("Paired Bootstrap p < 0.05 (上线标准)",
         boot_result["p_value"] < 0.05,
         f"p={boot_result['p_value']:.4f}"),
    ]

    all_pass = True
    for name, passed, val in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}: {val}")

    # --- 年度分解 ---
    print("\n{:=^80}".format(" 年度分解 "))
    print("{:>6} | {:>12} {:>10} {:>10} | {:>12} {:>10} {:>10}".format(
        "年份", "LGB收益", "LGB Sharpe", "LGB MDD",
        "Base收益", "Base Sharpe", "Base MDD"))
    print("-" * 80)
    for year in sorted(yearly_lgb.keys()):
        lgb_y = yearly_lgb[year]
        base_y = yearly_base[year]
        # 标记最差年度
        lgb_mark = " *" if lgb_y["ann_return"] == min(y["ann_return"] for y in yearly_lgb.values()) else ""
        print("{:>6} | {:>11.2%}{} {:>10.3f} {:>10.2%} | {:>11.2%} {:>10.3f} {:>10.2%}".format(
            year,
            lgb_y["ann_return"], lgb_mark, lgb_y["ann_sharpe"], lgb_y["mdd"],
            base_y["ann_return"], base_y["ann_sharpe"], base_y["mdd"]))

    # --- 上线决策 ---
    print("\n{:=^80}".format(" 上线决策 "))
    print("上线标准: Paired Bootstrap p<0.05 + OOS Sharpe>=1.10")
    print(f"当前结果: p={boot_result['p_value']:.4f}, Sharpe={lgb_metrics['ann_sharpe']:.3f}")

    if all_pass:
        print("\n>>> ALL CHECKS PASS - 建议进入SimBroker回测 <<<")
    else:
        failed = [name for name, passed, _ in checks if not passed]
        print(f"\n>>> {len(failed)} 项未通过: {', '.join(failed)} <<<")
        print(">>> 不建议上线 <<<")

    print(f"\n总耗时: {elapsed:.1f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
