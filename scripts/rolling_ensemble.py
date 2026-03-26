"""Rolling Ensemble: 多fold模型加权平均预测。

strategy角色 Sprint 1.5 并行任务。

核心思想:
  对于OOS期间的每个trade_date，用"该日期之前所有已训练完成的fold模型"做预测，
  然后指数衰减加权平均。例如2024-07-01在F4的OOS期间，但F1/F2/F3模型也已可用，
  用F1+F2+F3+F4四个模型分别预测再加权平均。

  权重: w_i = exp(-lambda * (current_fold - i)), 半衰期=1 fold -> lambda=ln(2)

对比:
  - 单fold(Sprint 1.4b): OOS Sharpe=0.869
  - Rolling ensemble目标: Sharpe >= 0.912 (提升>=5%)
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

from backend.engines.ml_engine import (
    MLConfig,
    WalkForwardTrainer,
    FeaturePreprocessor,
    Fold,
)

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
SEED = 42
BOOTSTRAP_N = 10000
BOOTSTRAP_BLOCK = 20

# 5个基线因子
BASELINE_FEATURES = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

# 半衰期=1 fold -> lambda=ln(2)
DECAY_LAMBDA = np.log(2)


def get_conn():
    """获取数据库连接（读.env配置）。"""
    return _get_sync_conn()


# ==============================================================
# Step 1: 生成fold + 加载数据 + 训练preprocessor
# ==============================================================
def setup_folds_and_data():
    """初始化WalkForwardTrainer，生成fold，加载特征矩阵。

    Returns:
        (trainer, folds, df_features)
    """
    config = MLConfig(
        feature_names=BASELINE_FEATURES,
        gpu=False,  # 预测不需要GPU
    )

    trainer = WalkForwardTrainer(config)
    folds = trainer.generate_folds()

    # 加载全量特征矩阵
    earliest = min(f.train_start for f in folds)
    latest = max(f.test_end for f in folds)
    logger.info(f"加载特征矩阵: {earliest} ~ {latest}")
    df = trainer.load_features(earliest, latest)

    return trainer, folds, df


def fit_preprocessors(trainer, folds, df):
    """为每个fold fit一个FeaturePreprocessor（用该fold的训练集）。

    Returns:
        dict: {fold_id: FeaturePreprocessor}
    """
    feature_cols = [c for c in BASELINE_FEATURES if c in df.columns]
    preprocessors = {}

    for fold in folds:
        train_df, _, _ = trainer._split_fold_data(df, fold)
        pp = FeaturePreprocessor()
        pp.fit(train_df, feature_cols)
        preprocessors[fold.fold_id] = pp
        logger.info(f"F{fold.fold_id} preprocessor fitted on {len(train_df)} samples")

    return preprocessors


# ==============================================================
# Step 2: Rolling Ensemble预测
# ==============================================================
def rolling_ensemble_predict(trainer, folds, df, preprocessors):
    """对OOS期间每个trade_date，用所有可用fold模型做加权平均预测。

    对于fold N的OOS期间(test_start ~ test_end):
      - 可用模型: fold 1 ~ fold N（都已训练完成）
      - 权重: w_i = exp(-lambda * (N - i)), i=1..N
      - 归一化: w_i / sum(w)

    Returns:
        DataFrame [trade_date, code, predicted, fold_id]
        其中predicted是ensemble后的预测值
    """
    import lightgbm as lgb

    feature_cols = [c for c in BASELINE_FEATURES if c in df.columns]
    model_dir = Path(trainer.config.model_dir)

    # 加载所有模型
    models = {}
    for fold in folds:
        model_path = model_dir / f"fold_{fold.fold_id}.txt"
        if model_path.exists():
            models[fold.fold_id] = lgb.Booster(model_file=str(model_path))
            logger.info(f"加载模型: F{fold.fold_id} ({model_path})")
        else:
            logger.warning(f"模型文件不存在: {model_path}")

    all_predictions = []

    for fold in folds:
        logger.info(f"--- 处理 F{fold.fold_id} OOS期间: {fold.test_start} ~ {fold.test_end} ---")

        # 获取该fold的测试集数据
        _, _, test_df = trainer._split_fold_data(df, fold)
        if test_df.empty:
            logger.warning(f"F{fold.fold_id} 测试集为空，跳过")
            continue

        # 可用模型: fold 1 ~ fold N
        available_folds = [f for f in folds if f.fold_id <= fold.fold_id and f.fold_id in models]
        n_available = len(available_folds)

        if n_available == 0:
            logger.warning(f"F{fold.fold_id} 无可用模型")
            continue

        # 计算指数衰减权重
        weights = {}
        for af in available_folds:
            distance = fold.fold_id - af.fold_id  # 0 for current fold, 1 for previous, etc.
            weights[af.fold_id] = np.exp(-DECAY_LAMBDA * distance)

        # 归一化
        w_sum = sum(weights.values())
        for k in weights:
            weights[k] /= w_sum

        logger.info(f"  可用模型: {n_available}个, 权重: " +
                    ", ".join(f"F{k}={v:.3f}" for k, v in sorted(weights.items())))

        # 对每个可用模型做预测
        model_preds = {}
        for af in available_folds:
            # 用该fold自己的preprocessor来transform测试数据
            pp = preprocessors[af.fold_id]
            test_processed = pp.transform(test_df)
            X_test = test_processed[feature_cols].values.astype(np.float32)
            pred = models[af.fold_id].predict(X_test)
            model_preds[af.fold_id] = pred

        # 加权平均
        ensemble_pred = np.zeros(len(test_df))
        for fid, pred in model_preds.items():
            ensemble_pred += weights[fid] * pred

        # 构建结果
        result_df = pd.DataFrame({
            "trade_date": test_df["trade_date"].values,
            "code": test_df["code"].values,
            "predicted": ensemble_pred,
            "actual": test_df["excess_return_20"].values if "excess_return_20" in test_df.columns else np.nan,
            "fold_id": fold.fold_id,
            "n_models": n_available,
        })
        all_predictions.append(result_df)

    if not all_predictions:
        return pd.DataFrame()

    oos_df = pd.concat(all_predictions, ignore_index=True)
    oos_df = oos_df.sort_values(["trade_date", "code"]).reset_index(drop=True)

    # 确保trade_date是date类型
    if hasattr(oos_df["trade_date"].iloc[0], "date"):
        oos_df["trade_date"] = oos_df["trade_date"].apply(
            lambda x: x.date() if hasattr(x, "date") else x
        )

    return oos_df


# ==============================================================
# Step 3: 组合构建 + 绩效评估（复用evaluate脚本的逻辑）
# ==============================================================
def load_price_data(conn, start_date, end_date):
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
    return df


def load_trade_dates(conn, start_date, end_date):
    """加载交易日历。"""
    sql = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
    ORDER BY trade_date
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    return [d.date() if hasattr(d, "date") else d for d in df["trade_date"]]


def compute_daily_returns(price_df):
    """计算日频收益率矩阵。"""
    pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close")
    ret = pivot.pct_change().iloc[1:]
    return ret


def get_monthly_rebalance_dates(trade_dates):
    """获取每月第一个交易日。"""
    rebal_dates = []
    current_month = None
    for d in trade_dates:
        ym = (d.year, d.month)
        if ym != current_month:
            rebal_dates.append(d)
            current_month = ym
    return rebal_dates


def build_portfolio_returns(signal_df, returns_pivot, trade_dates, signal_col="score",
                            top_n=TOP_N, cost=COST_ONE_WAY):
    """构建月度调仓Top-N等权组合的日频收益序列。"""
    rebalance_dates = get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(signal_df["trade_date"].unique())
    available_rebal = [d for d in rebalance_dates if d in signal_dates]

    if not available_rebal:
        return pd.DataFrame(columns=["trade_date", "portfolio_return"])

    daily_returns = []
    prev_holdings = set()

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
            next_rebal_idx = trade_dates.index(next_rebal) if next_rebal in trade_dates else len(trade_dates) - 1
            hold_end_idx = next_rebal_idx
        else:
            hold_end_idx = len(trade_dates)

        new_holdings = set(top_stocks)
        turnover = len(new_holdings.symmetric_difference(prev_holdings)) / (2 * top_n) if prev_holdings else 1.0
        rebal_cost = turnover * cost * 2

        for day_idx in range(hold_start_idx, hold_end_idx):
            td = trade_dates[day_idx]
            if td not in returns_pivot.index:
                continue

            day_ret = returns_pivot.loc[td]
            stock_rets = []
            for s in top_stocks:
                if s in day_ret.index and not np.isnan(day_ret[s]):
                    stock_rets.append(day_ret[s])
            port_ret = np.mean(stock_rets) if stock_rets else 0.0

            if day_idx == hold_start_idx:
                port_ret -= rebal_cost

            daily_returns.append({"trade_date": td, "portfolio_return": port_ret})

        prev_holdings = new_holdings

    return pd.DataFrame(daily_returns)


def calc_metrics(daily_rets, annual_factor=252.0):
    """计算核心绩效指标。"""
    if len(daily_rets) == 0:
        return {}

    total_ret = np.prod(1 + daily_rets) - 1
    n_years = len(daily_rets) / annual_factor
    ann_ret = (1 + total_ret) ** (1.0 / n_years) - 1 if n_years > 0 else 0

    ann_sharpe = (np.mean(daily_rets) / np.std(daily_rets, ddof=1) * np.sqrt(annual_factor)
                  if np.std(daily_rets, ddof=1) > 0 else 0)

    cum = np.cumprod(1 + daily_rets)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum / running_max - 1
    mdd = float(np.min(drawdowns))

    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-10 else 0

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

    return {
        "ann_return": ann_ret,
        "ann_sharpe": ann_sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "total_return": total_ret,
        "n_days": len(daily_rets),
        "max_losing_streak": max_losing_streak,
    }


def bootstrap_sharpe_ci(daily_rets, n_boot=BOOTSTRAP_N, block_size=BOOTSTRAP_BLOCK, seed=SEED):
    """Block Bootstrap Sharpe 95% CI。"""
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
        else:
            sharpes[b] = 0.0

    return float(np.percentile(sharpes, 2.5)), float(np.percentile(sharpes, 97.5))


def paired_block_bootstrap(lgb_rets, base_rets, n_boot=BOOTSTRAP_N,
                           block_size=BOOTSTRAP_BLOCK, seed=SEED):
    """Paired block bootstrap: ensemble vs 单fold。"""
    rng = np.random.RandomState(seed)
    T = len(lgb_rets)
    assert T == len(base_rets)

    d = lgb_rets - base_rets
    orig_diff_sharpe = np.mean(d) / np.std(d, ddof=1) * np.sqrt(252) if np.std(d, ddof=1) > 0 else 0

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


def compute_annual_turnover(signal_df, trade_dates, signal_col="score", top_n=TOP_N):
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
    return np.mean(turnovers) * 12


# ==============================================================
# Main
# ==============================================================
def main():
    t0 = time.time()

    print("=" * 80)
    print("  Rolling Ensemble: 多Fold模型加权平均")
    print("  半衰期=1 fold (lambda=ln(2))")
    print("=" * 80)

    # ----------------------------------------------------------
    # 1. 初始化: 生成fold + 加载特征
    # ----------------------------------------------------------
    logger.info("Step 1: 初始化WalkForwardTrainer + 加载特征矩阵...")
    trainer, folds, df = setup_folds_and_data()
    logger.info(f"  {len(folds)} folds, 特征矩阵 {len(df)} 行")

    # ----------------------------------------------------------
    # 2. 为每个fold fit preprocessor
    # ----------------------------------------------------------
    logger.info("Step 2: Fit preprocessors...")
    preprocessors = fit_preprocessors(trainer, folds, df)

    # ----------------------------------------------------------
    # 3. Rolling Ensemble预测
    # ----------------------------------------------------------
    logger.info("Step 3: Rolling Ensemble预测...")
    ensemble_oos = rolling_ensemble_predict(trainer, folds, df, preprocessors)
    logger.info(f"  Ensemble OOS: {len(ensemble_oos)} 行, "
                f"{ensemble_oos['trade_date'].nunique()} 天")

    # 保存ensemble预测
    cache_path = project_root / "models" / "ensemble_predictions.csv"
    ensemble_oos.to_csv(cache_path, index=False)
    logger.info(f"  保存到: {cache_path}")

    # ----------------------------------------------------------
    # 4. 加载单fold预测（Sprint 1.4b基线）
    # ----------------------------------------------------------
    logger.info("Step 4: 加载单fold OOS预测...")
    single_oos_path = project_root / "models" / "oos_predictions.csv"
    single_oos = pd.read_csv(single_oos_path)
    single_oos["trade_date"] = pd.to_datetime(single_oos["trade_date"]).dt.date

    # ----------------------------------------------------------
    # 5. 加载行情 + 构建组合
    # ----------------------------------------------------------
    logger.info("Step 5: 加载行情数据...")
    conn = get_conn()
    try:
        oos_dates = sorted(ensemble_oos["trade_date"].unique())
        price_start = oos_dates[0] - timedelta(days=10)
        price_end = oos_dates[-1] + timedelta(days=40)
        price_df = load_price_data(conn, price_start, price_end)
        trade_dates_full = load_trade_dates(conn, price_start, price_end)
        trade_dates_oos = [d for d in trade_dates_full if oos_dates[0] <= d <= oos_dates[-1]]

        returns_pivot = compute_daily_returns(price_df)

        # Ensemble组合
        logger.info("Step 6: 构建Ensemble Top-15组合...")
        ens_signals = ensemble_oos[["trade_date", "code", "predicted"]].copy()
        ens_signals.rename(columns={"predicted": "score"}, inplace=True)

        ens_port = build_portfolio_returns(
            ens_signals, returns_pivot, trade_dates_oos,
            signal_col="score", top_n=TOP_N, cost=COST_ONE_WAY,
        )
        logger.info(f"  Ensemble组合: {len(ens_port)} 天")

        # 单fold组合
        logger.info("Step 7: 构建单Fold Top-15组合...")
        single_signals = single_oos[["trade_date", "code", "predicted"]].copy()
        single_signals.rename(columns={"predicted": "score"}, inplace=True)

        single_port = build_portfolio_returns(
            single_signals, returns_pivot, trade_dates_oos,
            signal_col="score", top_n=TOP_N, cost=COST_ONE_WAY,
        )
        logger.info(f"  单Fold组合: {len(single_port)} 天")
    finally:
        conn.close()

    # ----------------------------------------------------------
    # 6. 对齐日期 + 计算指标
    # ----------------------------------------------------------
    logger.info("Step 8: 对齐日期 + 绩效计算...")
    ens_port.set_index("trade_date", inplace=True)
    single_port.set_index("trade_date", inplace=True)

    common_dates = ens_port.index.intersection(single_port.index).sort_values()
    logger.info(f"  共同交易日: {len(common_dates)} 天 ({common_dates[0]} ~ {common_dates[-1]})")

    ens_rets = ens_port.loc[common_dates, "portfolio_return"].values.astype(np.float64)
    single_rets = single_port.loc[common_dates, "portfolio_return"].values.astype(np.float64)

    ens_metrics = calc_metrics(ens_rets)
    single_metrics = calc_metrics(single_rets)

    # Bootstrap CI
    ens_ci = bootstrap_sharpe_ci(ens_rets, seed=SEED)
    single_ci = bootstrap_sharpe_ci(single_rets, seed=SEED + 1)

    # 年化换手率
    ens_turnover = compute_annual_turnover(ens_signals, trade_dates_oos, "score", TOP_N)
    single_turnover = compute_annual_turnover(single_signals, trade_dates_oos, "score", TOP_N)

    # Paired bootstrap
    logger.info("Step 9: Paired Block Bootstrap (10000次)...")
    boot = paired_block_bootstrap(ens_rets, single_rets)

    # ----------------------------------------------------------
    # 7. 年度分解
    # ----------------------------------------------------------
    yearly_ens = {}
    yearly_single = {}
    for year in sorted(set(d.year for d in common_dates)):
        mask = np.array([d.year == year for d in common_dates])
        if mask.sum() > 20:
            yearly_ens[year] = calc_metrics(ens_rets[mask])
            yearly_single[year] = calc_metrics(single_rets[mask])

    # ==============================================================
    # 输出报告
    # ==============================================================
    elapsed = time.time() - t0

    print("\n")
    print("=" * 80)
    print("  Rolling Ensemble 评估报告")
    print(f"  评估期间: {common_dates[0]} ~ {common_dates[-1]} ({len(common_dates)} 交易日)")
    print(f"  Top-{TOP_N} 等权 月度调仓 单边成本{COST_ONE_WAY*1000:.1f}‰")
    print(f"  Ensemble权重: 指数衰减, 半衰期=1 fold (lambda={DECAY_LAMBDA:.4f})")
    print("=" * 80)

    # --- 核心指标对比 ---
    print(f"\n{'':=^80}")
    print(f" {'核心指标对比':^76} ")
    print(f"{'':=^80}")
    print(f"{'指标':<25} {'Rolling Ensemble':>20} {'单Fold(1.4b)':>20}")
    print("-" * 65)

    rows = [
        ("年化收益", f"{ens_metrics['ann_return']:.2%}", f"{single_metrics['ann_return']:.2%}"),
        ("年化Sharpe", f"{ens_metrics['ann_sharpe']:.3f}", f"{single_metrics['ann_sharpe']:.3f}"),
        ("Sharpe 95% CI", f"[{ens_ci[0]:.3f}, {ens_ci[1]:.3f}]",
         f"[{single_ci[0]:.3f}, {single_ci[1]:.3f}]"),
        ("最大回撤", f"{ens_metrics['mdd']:.2%}", f"{single_metrics['mdd']:.2%}"),
        ("Calmar", f"{ens_metrics['calmar']:.3f}", f"{single_metrics['calmar']:.3f}"),
        ("Sortino", f"{ens_metrics['sortino']:.3f}", f"{single_metrics['sortino']:.3f}"),
        ("总收益", f"{ens_metrics['total_return']:.2%}", f"{single_metrics['total_return']:.2%}"),
        ("交易天数", f"{ens_metrics['n_days']}", f"{single_metrics['n_days']}"),
        ("最长连亏天数", f"{ens_metrics['max_losing_streak']}", f"{single_metrics['max_losing_streak']}"),
        ("年化换手率", f"{ens_turnover:.1%}", f"{single_turnover:.1%}"),
    ]
    for label, v1, v2 in rows:
        print(f"{label:<25} {v1:>20} {v2:>20}")

    # --- 变化量 ---
    sharpe_diff = ens_metrics["ann_sharpe"] - single_metrics["ann_sharpe"]
    sharpe_pct = sharpe_diff / single_metrics["ann_sharpe"] * 100 if single_metrics["ann_sharpe"] != 0 else 0
    mdd_diff = ens_metrics["mdd"] - single_metrics["mdd"]

    print(f"\n{'':=^80}")
    print(f" {'Ensemble vs 单Fold 差异':^74} ")
    print(f"{'':=^80}")
    print(f"  Sharpe差异:    {sharpe_diff:+.3f} ({sharpe_pct:+.1f}%)")
    print(f"  MDD差异:       {mdd_diff:+.2%}")
    print(f"  达标(>=5%):    {'YES' if sharpe_pct >= 5.0 else 'NO'}")

    # --- Paired Bootstrap ---
    print(f"\n{'':=^80}")
    print(f" {'Paired Block Bootstrap (Ensemble > 单Fold?)':^74} ")
    print(f"{'':=^80}")
    print(f"  差异Sharpe:  {boot['orig_diff_sharpe']:.3f}")
    print(f"  p-value:     {boot['p_value']:.4f}")
    print(f"  95% CI:      [{boot['ci_lo']:.3f}, {boot['ci_hi']:.3f}]")
    print(f"  显著(p<0.05): {'YES' if boot['p_value'] < 0.05 else 'NO'}")

    # --- 年度分解 ---
    print(f"\n{'':=^80}")
    print(f" {'年度分解':^76} ")
    print(f"{'':=^80}")
    print(f"{'Year':>6} | {'Ens Sharpe':>10} {'Ens Return':>12} {'Ens MDD':>10} | "
          f"{'1F Sharpe':>10} {'1F Return':>12} {'1F MDD':>10}")
    print("-" * 85)
    for year in sorted(yearly_ens.keys()):
        em = yearly_ens[year]
        sm = yearly_single[year]
        marker = " <-- worst" if em["ann_sharpe"] < 0 else ""
        print(f"{year:>6} | {em['ann_sharpe']:>10.3f} {em['ann_return']:>11.2%} {em['mdd']:>10.2%} | "
              f"{sm['ann_sharpe']:>10.3f} {sm['ann_return']:>11.2%} {sm['mdd']:>10.2%}{marker}")

    # --- Ensemble模型数量分布 ---
    print(f"\n{'':=^80}")
    print(f" {'Ensemble模型数量分布':^74} ")
    print(f"{'':=^80}")
    for fid in sorted(ensemble_oos["fold_id"].unique()):
        sub = ensemble_oos[ensemble_oos["fold_id"] == fid]
        n_models = sub["n_models"].iloc[0]
        dates = sorted(sub["trade_date"].unique())
        print(f"  F{fid} OOS ({dates[0]} ~ {dates[-1]}): {n_models}个模型")

    # --- 判定 ---
    print(f"\n{'':=^80}")
    print(f" {'最终判定':^76} ")
    print(f"{'':=^80}")
    target_sharpe = 0.912
    achieved = ens_metrics["ann_sharpe"] >= target_sharpe
    print(f"  目标Sharpe: >= {target_sharpe:.3f} (单fold {single_metrics['ann_sharpe']:.3f} + 5%)")
    print(f"  实际Sharpe: {ens_metrics['ann_sharpe']:.3f}")
    print(f"  结果: {'PASS - Rolling Ensemble提升显著' if achieved else 'NOT PASS - 提升不足'}")
    print(f"  耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")

    print("=" * 80)

    # 保存简要结果
    summary = {
        "method": "rolling_ensemble",
        "decay": "exp(-ln2 * distance)",
        "ens_sharpe": ens_metrics["ann_sharpe"],
        "single_sharpe": single_metrics["ann_sharpe"],
        "sharpe_diff_pct": sharpe_pct,
        "ens_mdd": ens_metrics["mdd"],
        "single_mdd": single_metrics["mdd"],
        "p_value": boot["p_value"],
        "target_met": achieved,
    }
    summary_df = pd.DataFrame([summary])
    summary_path = project_root / "models" / "ensemble_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    logger.info(f"摘要保存到: {summary_path}")

    trainer.close()


if __name__ == "__main__":
    main()
