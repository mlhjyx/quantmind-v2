"""Sprint 1.6: Rolling Ensemble干净评估。

从7个已有fold模型重新生成:
1. 单fold OOS predictions (clean, 不覆盖旧文件)
2. Rolling ensemble predictions (多fold指数衰减加权)
3. 等权基线信号

然后三方对比: 单fold Sharpe vs ensemble Sharpe vs 等权基线Sharpe
+ paired bootstrap检验 ensemble vs 单fold

成功标准: ensemble Sharpe > 单fold Sharpe * 1.05 (提升>=5%)
"""

import gc
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

from backend.engines.ml_engine import (
    MLConfig,
    WalkForwardTrainer,
    FeaturePreprocessor,
    Fold,
    compute_icir,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            project_root / "models" / "eval_ensemble_clean.log", mode="w"
        ),
    ],
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
DECAY_LAMBDA = np.log(2)  # 半衰期=1 fold

BASELINE_FEATURES = [
    "turnover_mean_20", "volatility_20", "reversal_20",
    "amihud_20", "bp_ratio",
]
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": -1,
    "amihud_20": -1,
    "bp_ratio": 1,
}


def get_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin",
        password="quantmind", host="localhost",
    )


# ==============================================================
# Step 1: 生成干净的单fold + ensemble OOS预测
# ==============================================================
def generate_clean_predictions():
    """从已有fold模型重新生成OOS预测。

    Returns:
        (single_oos_df, ensemble_oos_df, folds)
        single: 每个fold只用自己模型预测
        ensemble: 每个fold用所有可用模型加权预测
    """
    import lightgbm as lgb

    config = MLConfig(
        feature_names=BASELINE_FEATURES,
        gpu=False,  # 预测不需GPU
    )
    trainer = WalkForwardTrainer(config)
    folds = trainer.generate_folds()
    logger.info(f"生成 {len(folds)} 个fold")

    # 加载全量特征矩阵
    earliest = min(f.train_start for f in folds)
    latest = max(f.test_end for f in folds)
    logger.info(f"加载特征矩阵: {earliest} ~ {latest}")
    df = trainer.load_features(earliest, latest)
    logger.info(f"特征矩阵: {len(df)}行, {df['trade_date'].nunique()}天")

    feature_cols = [c for c in BASELINE_FEATURES if c in df.columns]
    model_dir = Path(config.model_dir)

    # 加载所有模型
    models = {}
    for fold in folds:
        model_path = model_dir / f"fold_{fold.fold_id}.txt"
        if model_path.exists():
            models[fold.fold_id] = lgb.Booster(model_file=str(model_path))
            logger.info(f"加载模型 F{fold.fold_id}: {model_path}")
        else:
            logger.warning(f"模型不存在: {model_path}")

    # 为每个fold fit preprocessor
    preprocessors = {}
    for fold in folds:
        train_df, _, _ = trainer._split_fold_data(df, fold)
        pp = FeaturePreprocessor()
        pp.fit(train_df, feature_cols)
        preprocessors[fold.fold_id] = pp

    # 生成预测
    single_all = []
    ensemble_all = []

    for fold in folds:
        if fold.fold_id not in models:
            continue

        _, _, test_df = trainer._split_fold_data(df, fold)
        if test_df.empty:
            continue

        logger.info(
            f"F{fold.fold_id} OOS: {fold.test_start}~{fold.test_end}, "
            f"{len(test_df)}行, {test_df['trade_date'].nunique()}天"
        )

        # --- 单fold预测 ---
        pp = preprocessors[fold.fold_id]
        test_p = pp.transform(test_df)
        X_test = test_p[feature_cols].values.astype(np.float32)
        single_pred = models[fold.fold_id].predict(X_test)

        single_df = pd.DataFrame({
            "trade_date": test_df["trade_date"].values,
            "code": test_df["code"].values,
            "predicted": single_pred,
            "actual": test_df["excess_return_20"].values if "excess_return_20" in test_df.columns else np.nan,
            "fold_id": fold.fold_id,
        })
        single_all.append(single_df)

        # --- Ensemble预测 ---
        available = [f for f in folds if f.fold_id <= fold.fold_id and f.fold_id in models]
        weights = {}
        for af in available:
            dist = fold.fold_id - af.fold_id
            weights[af.fold_id] = np.exp(-DECAY_LAMBDA * dist)
        w_sum = sum(weights.values())
        for k in weights:
            weights[k] /= w_sum

        ens_pred = np.zeros(len(test_df))
        for af in available:
            pp_af = preprocessors[af.fold_id]
            test_p_af = pp_af.transform(test_df)
            X_af = test_p_af[feature_cols].values.astype(np.float32)
            pred_af = models[af.fold_id].predict(X_af)
            ens_pred += weights[af.fold_id] * pred_af

        ens_df = pd.DataFrame({
            "trade_date": test_df["trade_date"].values,
            "code": test_df["code"].values,
            "predicted": ens_pred,
            "actual": test_df["excess_return_20"].values if "excess_return_20" in test_df.columns else np.nan,
            "fold_id": fold.fold_id,
            "n_models": len(available),
        })
        ensemble_all.append(ens_df)

        wt_str = ", ".join(f"F{k}={v:.3f}" for k, v in sorted(weights.items()))
        logger.info(f"  Ensemble: {len(available)}个模型, 权重=[{wt_str}]")

    trainer.close()

    single_oos = pd.concat(single_all, ignore_index=True).sort_values(["trade_date", "code"]).reset_index(drop=True)
    ensemble_oos = pd.concat(ensemble_all, ignore_index=True).sort_values(["trade_date", "code"]).reset_index(drop=True)

    # 确保date类型
    for d in [single_oos, ensemble_oos]:
        if hasattr(d["trade_date"].iloc[0], "date"):
            d["trade_date"] = d["trade_date"].apply(
                lambda x: x.date() if hasattr(x, "date") else x
            )

    return single_oos, ensemble_oos, folds


# ==============================================================
# Step 2: 行情 + 基线信号 + 组合构建
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
    return df


def load_trade_dates(conn, start_date, end_date):
    sql = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s ORDER BY trade_date
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    return [d.date() if hasattr(d, "date") else d for d in df["trade_date"]]


def load_baseline_signals(conn, start_date, end_date):
    """5因子等权排名信号。"""
    placeholders = ",".join(["%s"] * len(BASELINE_FEATURES))
    sql = f"""
    SELECT trade_date, code, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date BETWEEN %s AND %s
      AND factor_name IN ({placeholders})
      AND neutral_value IS NOT NULL
    ORDER BY trade_date, code
    """
    params = [start_date, end_date] + BASELINE_FEATURES
    df = pd.read_sql(sql, conn, params=params)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    if df.empty:
        return pd.DataFrame(columns=["trade_date", "code", "score"])

    wide = df.pivot_table(
        index=["trade_date", "code"], columns="factor_name",
        values="neutral_value", aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    results = []
    for td in sorted(wide["trade_date"].unique()):
        day_df = wide[wide["trade_date"] == td].copy()
        if len(day_df) < TOP_N:
            continue
        rank_sum = pd.Series(0.0, index=day_df.index)
        n_valid = pd.Series(0, index=day_df.index)
        for factor in BASELINE_FEATURES:
            if factor not in day_df.columns:
                continue
            vals = day_df[factor]
            mask = vals.notna()
            if mask.sum() < TOP_N:
                continue
            direction = FACTOR_DIRECTIONS[factor]
            ranks = vals.rank(ascending=(direction == -1), method="average", pct=True)
            rank_sum = rank_sum.add(ranks.fillna(0))
            n_valid = n_valid.add(mask.astype(int))
        day_df["score"] = rank_sum / n_valid.clip(lower=1)
        results.append(day_df[["trade_date", "code", "score"]])

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame(columns=["trade_date", "code", "score"])


def get_monthly_rebalance_dates(trade_dates):
    rebal = []
    current_month = None
    for d in trade_dates:
        ym = (d.year, d.month)
        if ym != current_month:
            rebal.append(d)
            current_month = ym
    return rebal


def build_portfolio_returns(signal_df, returns_pivot, trade_dates,
                            signal_col="score", top_n=TOP_N, cost=COST_ONE_WAY):
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
        if not top_stocks:
            continue

        rebal_idx = trade_dates.index(rebal_date) if rebal_date in trade_dates else None
        if rebal_idx is None:
            continue
        hold_start_idx = rebal_idx + 1
        if hold_start_idx >= len(trade_dates):
            continue

        if i + 1 < len(available_rebal):
            next_rebal = available_rebal[i + 1]
            hold_end_idx = trade_dates.index(next_rebal) if next_rebal in trade_dates else len(trade_dates) - 1
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
            stock_rets = [day_ret[s] for s in top_stocks if s in day_ret.index and not np.isnan(day_ret[s])]
            port_ret = np.mean(stock_rets) if stock_rets else 0.0
            if day_idx == hold_start_idx:
                port_ret -= rebal_cost
            daily_returns.append({"trade_date": td, "portfolio_return": port_ret})

        prev_holdings = new_holdings

    return pd.DataFrame(daily_returns)


# ==============================================================
# Step 3: 统计
# ==============================================================
def calc_metrics(daily_rets, annual_factor=252.0):
    if len(daily_rets) == 0:
        return {}
    total_ret = np.prod(1 + daily_rets) - 1
    n_years = len(daily_rets) / annual_factor
    ann_ret = (1 + total_ret) ** (1.0 / n_years) - 1 if n_years > 0 else 0
    ann_sharpe = (np.mean(daily_rets) / np.std(daily_rets, ddof=1) * np.sqrt(annual_factor)
                  if np.std(daily_rets, ddof=1) > 0 else 0)
    cum = np.cumprod(1 + daily_rets)
    running_max = np.maximum.accumulate(cum)
    mdd = float(np.min(cum / running_max - 1))
    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-10 else 0
    downside = daily_rets[daily_rets < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else 1e-10
    sortino = np.mean(daily_rets) / downside_std * np.sqrt(annual_factor)
    losing_streak = max_ls = 0
    for r in daily_rets:
        if r < 0:
            losing_streak += 1
            max_ls = max(max_ls, losing_streak)
        else:
            losing_streak = 0
    return {
        "ann_return": ann_ret, "ann_sharpe": ann_sharpe, "mdd": mdd,
        "calmar": calmar, "sortino": sortino, "total_return": total_ret,
        "n_days": len(daily_rets), "max_losing_streak": max_ls,
    }


def bootstrap_sharpe_ci(daily_rets, n_boot=BOOTSTRAP_N, block_size=BOOTSTRAP_BLOCK, seed=SEED):
    rng = np.random.RandomState(seed)
    T = len(daily_rets)
    n_blocks = int(np.ceil(T / block_size))
    sharpes = np.zeros(n_boot)
    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        boot = daily_rets[indices]
        std_b = np.std(boot, ddof=1)
        sharpes[b] = np.mean(boot) / std_b * np.sqrt(252) if std_b > 1e-12 else 0.0
    return float(np.percentile(sharpes, 2.5)), float(np.percentile(sharpes, 97.5))


def paired_block_bootstrap(rets_a, rets_b, n_boot=BOOTSTRAP_N, block_size=BOOTSTRAP_BLOCK, seed=SEED):
    """Paired bootstrap: A vs B. H0: A <= B."""
    rng = np.random.RandomState(seed)
    T = len(rets_a)
    assert T == len(rets_b)
    d = rets_a - rets_b
    orig = np.mean(d) / np.std(d, ddof=1) * np.sqrt(252) if np.std(d, ddof=1) > 0 else 0
    n_blocks = int(np.ceil(T / block_size))
    boots = np.zeros(n_boot)
    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        d_b = d[indices]
        std_b = np.std(d_b, ddof=1)
        boots[b] = np.mean(d_b) / std_b * np.sqrt(252) if std_b > 1e-12 else 0.0
    return {
        "orig_diff_sharpe": orig,
        "p_value": float(np.mean(boots <= 0)),
        "ci_lo": float(np.percentile(boots, 2.5)),
        "ci_hi": float(np.percentile(boots, 97.5)),
    }


def compute_annual_turnover(signal_df, trade_dates, signal_col="score", top_n=TOP_N):
    rebalance_dates = get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(signal_df["trade_date"].unique())
    available_rebal = [d for d in rebalance_dates if d in signal_dates]
    turnovers = []
    prev = None
    for rd in available_rebal:
        day_s = signal_df[signal_df["trade_date"] == rd].sort_values(signal_col, ascending=False)
        cur = set(day_s.head(top_n)["code"].tolist())
        if prev is not None and cur:
            turnovers.append(len(cur.symmetric_difference(prev)) / (2 * top_n))
        prev = cur
    return np.mean(turnovers) * 12 if turnovers else 0.0


# ==============================================================
# Main
# ==============================================================
def main():
    t0 = time.time()
    (project_root / "models").mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("  Sprint 1.6: Rolling Ensemble 干净评估")
    print("  从已有7 fold模型重新生成预测, 三方对比")
    print("=" * 80)

    # Step 1: 生成干净预测
    logger.info("Step 1: 生成干净的单fold + ensemble OOS预测...")
    single_oos, ensemble_oos, folds = generate_clean_predictions()
    logger.info(
        f"单fold OOS: {len(single_oos)}行, {single_oos['trade_date'].nunique()}天\n"
        f"Ensemble OOS: {len(ensemble_oos)}行, {ensemble_oos['trade_date'].nunique()}天"
    )

    # 保存干净预测
    single_oos.to_csv(project_root / "models" / "oos_predictions_clean.csv", index=False)
    ensemble_oos.to_csv(project_root / "models" / "ensemble_predictions_clean.csv", index=False)
    logger.info("预测已保存到 models/oos_predictions_clean.csv + ensemble_predictions_clean.csv")

    # Step 2: 行情 + 基线信号
    logger.info("Step 2: 加载行情 + 等权基线信号...")
    conn = get_conn()

    oos_dates = sorted(single_oos["trade_date"].unique())
    price_start = oos_dates[0] - timedelta(days=10)
    price_end = oos_dates[-1] + timedelta(days=40)

    price_df = load_price_data(conn, price_start, price_end)
    trade_dates_full = load_trade_dates(conn, price_start, price_end)
    trade_dates_oos = [d for d in trade_dates_full if oos_dates[0] <= d <= oos_dates[-1] + timedelta(days=30)]
    returns_pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close").pct_change().iloc[1:]

    baseline_signals = load_baseline_signals(conn, oos_dates[0], oos_dates[-1])
    logger.info(f"等权基线信号: {len(baseline_signals)}行, {baseline_signals['trade_date'].nunique()}天")

    conn.close()

    # Step 3: 构建三个组合
    logger.info("Step 3: 构建三个组合...")

    single_signals = single_oos[["trade_date", "code", "predicted"]].copy()
    single_signals.rename(columns={"predicted": "score"}, inplace=True)
    single_port = build_portfolio_returns(single_signals, returns_pivot, trade_dates_oos)

    ens_signals = ensemble_oos[["trade_date", "code", "predicted"]].copy()
    ens_signals.rename(columns={"predicted": "score"}, inplace=True)
    ens_port = build_portfolio_returns(ens_signals, returns_pivot, trade_dates_oos)

    base_port = build_portfolio_returns(baseline_signals, returns_pivot, trade_dates_oos)

    logger.info(f"单fold组合: {len(single_port)}天, Ensemble: {len(ens_port)}天, 基线: {len(base_port)}天")

    # Step 4: 对齐日期
    logger.info("Step 4: 对齐日期 + 绩效计算...")
    single_port.set_index("trade_date", inplace=True)
    ens_port.set_index("trade_date", inplace=True)
    base_port.set_index("trade_date", inplace=True)

    common = single_port.index.intersection(ens_port.index).intersection(base_port.index).sort_values()
    logger.info(f"三方共同日期: {len(common)}天 ({common[0]} ~ {common[-1]})")

    single_rets = single_port.loc[common, "portfolio_return"].values.astype(np.float64)
    ens_rets = ens_port.loc[common, "portfolio_return"].values.astype(np.float64)
    base_rets = base_port.loc[common, "portfolio_return"].values.astype(np.float64)

    sm = calc_metrics(single_rets)
    em = calc_metrics(ens_rets)
    bm = calc_metrics(base_rets)

    # Bootstrap CI
    s_ci = bootstrap_sharpe_ci(single_rets, seed=SEED)
    e_ci = bootstrap_sharpe_ci(ens_rets, seed=SEED + 1)
    b_ci = bootstrap_sharpe_ci(base_rets, seed=SEED + 2)

    # 换手率
    s_to = compute_annual_turnover(single_signals, trade_dates_oos)
    e_to = compute_annual_turnover(ens_signals, trade_dates_oos)
    b_to = compute_annual_turnover(baseline_signals, trade_dates_oos)

    # Paired bootstrap: ensemble vs single
    logger.info("Step 5: Paired bootstrap (ensemble vs 单fold)...")
    boot_ens_vs_single = paired_block_bootstrap(ens_rets, single_rets, seed=SEED)

    # Paired bootstrap: ensemble vs baseline
    logger.info("Step 6: Paired bootstrap (ensemble vs 等权基线)...")
    boot_ens_vs_base = paired_block_bootstrap(ens_rets, base_rets, seed=SEED + 10)

    # 年度分解
    yearly = {}
    for year in sorted(set(d.year for d in common)):
        mask = np.array([d.year == year for d in common])
        if mask.sum() > 20:
            yearly[year] = {
                "single": calc_metrics(single_rets[mask]),
                "ensemble": calc_metrics(ens_rets[mask]),
                "baseline": calc_metrics(base_rets[mask]),
            }

    # ==============================================================
    # 输出报告
    # ==============================================================
    elapsed = time.time() - t0

    print("\n\n")
    print("=" * 90)
    print("  Rolling Ensemble 干净评估报告")
    print(f"  OOS期间: {common[0]} ~ {common[-1]} ({len(common)} 交易日)")
    print(f"  Top-{TOP_N} 等权 月度调仓 单边成本{COST_ONE_WAY*1000:.1f}‰")
    print(f"  Ensemble: 指数衰减, 半衰期=1 fold")
    print("=" * 90)

    print(f"\n{'核心指标三方对比':=^70}")
    print(f"{'指标':<22} {'Ensemble':>16} {'单Fold':>16} {'等权基线':>16}")
    print("-" * 70)
    rows = [
        ("年化收益", f"{em['ann_return']:.2%}", f"{sm['ann_return']:.2%}", f"{bm['ann_return']:.2%}"),
        ("年化Sharpe", f"{em['ann_sharpe']:.3f}", f"{sm['ann_sharpe']:.3f}", f"{bm['ann_sharpe']:.3f}"),
        ("Sharpe 95%CI", f"[{e_ci[0]:.2f},{e_ci[1]:.2f}]", f"[{s_ci[0]:.2f},{s_ci[1]:.2f}]", f"[{b_ci[0]:.2f},{b_ci[1]:.2f}]"),
        ("最大回撤", f"{em['mdd']:.2%}", f"{sm['mdd']:.2%}", f"{bm['mdd']:.2%}"),
        ("Calmar", f"{em['calmar']:.3f}", f"{sm['calmar']:.3f}", f"{bm['calmar']:.3f}"),
        ("Sortino", f"{em['sortino']:.3f}", f"{sm['sortino']:.3f}", f"{bm['sortino']:.3f}"),
        ("总收益", f"{em['total_return']:.2%}", f"{sm['total_return']:.2%}", f"{bm['total_return']:.2%}"),
        ("最长连亏", f"{em['max_losing_streak']}天", f"{sm['max_losing_streak']}天", f"{bm['max_losing_streak']}天"),
        ("年化换手率", f"{e_to:.1%}", f"{s_to:.1%}", f"{b_to:.1%}"),
    ]
    for label, v1, v2, v3 in rows:
        print(f"  {label:<20} {v1:>14} {v2:>14} {v3:>14}")

    # Sharpe差异
    ens_vs_single_pct = (em["ann_sharpe"] - sm["ann_sharpe"]) / sm["ann_sharpe"] * 100 if sm["ann_sharpe"] != 0 else 0
    ens_vs_base_pct = (em["ann_sharpe"] - bm["ann_sharpe"]) / bm["ann_sharpe"] * 100 if bm["ann_sharpe"] != 0 else 0

    print(f"\n{'Sharpe差异':=^70}")
    print(f"  Ensemble vs 单Fold:  {em['ann_sharpe'] - sm['ann_sharpe']:+.3f} ({ens_vs_single_pct:+.1f}%)")
    print(f"  Ensemble vs 等权基线: {em['ann_sharpe'] - bm['ann_sharpe']:+.3f} ({ens_vs_base_pct:+.1f}%)")

    print(f"\n{'Paired Bootstrap: Ensemble vs 单Fold':=^70}")
    b1 = boot_ens_vs_single
    print(f"  差异Sharpe: {b1['orig_diff_sharpe']:.3f}")
    print(f"  p-value:    {b1['p_value']:.4f}")
    print(f"  95% CI:     [{b1['ci_lo']:.3f}, {b1['ci_hi']:.3f}]")
    print(f"  显著(p<0.05): {'YES' if b1['p_value'] < 0.05 else 'NO'}")

    print(f"\n{'Paired Bootstrap: Ensemble vs 等权基线':=^70}")
    b2 = boot_ens_vs_base
    print(f"  差异Sharpe: {b2['orig_diff_sharpe']:.3f}")
    print(f"  p-value:    {b2['p_value']:.4f}")
    print(f"  95% CI:     [{b2['ci_lo']:.3f}, {b2['ci_hi']:.3f}]")
    print(f"  显著(p<0.05): {'YES' if b2['p_value'] < 0.05 else 'NO'}")

    print(f"\n{'年度分解':=^70}")
    print(f"{'Year':>6} | {'Ens Sharpe':>10} {'Ens Ret':>10} | {'1F Sharpe':>10} {'1F Ret':>10} | {'Base Sharpe':>11} {'Base Ret':>10}")
    print("-" * 85)
    for year in sorted(yearly.keys()):
        ye, ys, yb = yearly[year]["ensemble"], yearly[year]["single"], yearly[year]["baseline"]
        print(
            f"{year:>6} | {ye['ann_sharpe']:>10.3f} {ye['ann_return']:>9.2%} | "
            f"{ys['ann_sharpe']:>10.3f} {ys['ann_return']:>9.2%} | "
            f"{yb['ann_sharpe']:>11.3f} {yb['ann_return']:>9.2%}"
        )

    # Ensemble模型数量分布
    print(f"\n{'Ensemble模型数量':=^70}")
    for fid in sorted(ensemble_oos["fold_id"].unique()):
        sub = ensemble_oos[ensemble_oos["fold_id"] == fid]
        n_models = sub["n_models"].iloc[0]
        dates = sorted(sub["trade_date"].unique())
        print(f"  F{fid} ({dates[0]} ~ {dates[-1]}): {n_models}个模型")

    # 判定
    target_sharpe = sm["ann_sharpe"] * 1.05
    achieved = em["ann_sharpe"] >= target_sharpe

    print(f"\n{'最终判定':=^70}")
    print(f"  单Fold Sharpe:     {sm['ann_sharpe']:.3f}")
    print(f"  目标(+5%):         {target_sharpe:.3f}")
    print(f"  Ensemble Sharpe:   {em['ann_sharpe']:.3f}")
    print(f"  提升:              {ens_vs_single_pct:+.1f}%")
    print(f"  Bootstrap p-value: {b1['p_value']:.4f}")
    if achieved:
        print(f"  结果: PASS - Ensemble Sharpe提升 >= 5%")
    else:
        print(f"  结果: FAIL - Ensemble Sharpe提升不足5%")
    print(f"  耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print("=" * 90)

    # 保存摘要
    summary = {
        "ensemble_sharpe": em["ann_sharpe"],
        "single_sharpe": sm["ann_sharpe"],
        "baseline_sharpe": bm["ann_sharpe"],
        "ens_vs_single_pct": ens_vs_single_pct,
        "ens_vs_base_pct": ens_vs_base_pct,
        "bootstrap_p_ens_vs_single": b1["p_value"],
        "bootstrap_p_ens_vs_base": b2["p_value"],
        "ensemble_mdd": em["mdd"],
        "single_mdd": sm["mdd"],
        "baseline_mdd": bm["mdd"],
        "target_met": achieved,
    }
    pd.DataFrame([summary]).to_csv(project_root / "models" / "ensemble_clean_summary.csv", index=False)


if __name__ == "__main__":
    main()
