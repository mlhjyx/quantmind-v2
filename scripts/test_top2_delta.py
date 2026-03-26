"""方案6: 只加top 2个delta特征 (roe_delta + net_margin_delta) 到LightGBM。

Sprint 1.5b假设:
  Sprint 1.5全量13特征(5基线+8delta)导致OOS IC从0.082降到0.044。
  SHAP显示days_since_announcement(Gain=2966)远超其他，时间特征主导噪声。
  只加最强2个基本面delta (roe_delta IC=3.9%, net_margin_delta IC=4.2%)，
  不加时间特征，信噪比可能更好。

配置:
  特征集: 5基线 + roe_delta + net_margin_delta = 7个
  F1 Fold: Train=2020-07~2022-06, Valid=2022-07~2022-12, Test(OOS)=2023-01~2023-06
  Purge gap: 20个交易日
  LightGBM参数: 与Sprint 1.4b一致
  成功标准: best_iter>2 且 OOS IC>0.082 (5基线基准)
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

(project_root / "models").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(project_root / "models" / "test_top2_delta.log", mode="w"),
    ],
)
logger = logging.getLogger(__name__)

# ==========================================================
# 配置
# ==========================================================
BASELINE_FEATURES = [
    "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio",
]
TOP2_DELTA_FEATURES = ["roe_delta", "net_margin_delta"]
ALL_FEATURES = BASELINE_FEATURES + TOP2_DELTA_FEATURES  # 7个

# F1 Fold时间窗口
TRAIN_START = date(2020, 7, 1)
TRAIN_END = date(2022, 6, 30)
VALID_START = date(2022, 7, 1)
VALID_END = date(2022, 12, 31)
TEST_START = date(2023, 1, 1)
TEST_END = date(2023, 6, 30)

# 基线对比 (Sprint 1.4b F1 fold 5基线结果)
BASELINE_TRAIN_IC = 0.1308
BASELINE_VALID_IC = 0.1208
BASELINE_OOS_IC = 0.0823
BASELINE_BEST_ITER = 52
BASELINE_OVERFIT = 1.08


def load_features(conn) -> pd.DataFrame:
    """加载5基线因子(factor_values) + 2基本面delta(PIT) + target。"""
    from engines.factor_engine import load_fundamental_pit_data

    t0 = time.time()

    # 1. 加载5基线因子 (neutral_value from factor_values)
    placeholders = ",".join(["%s"] * len(BASELINE_FEATURES))
    sql_factors = f"""
    SELECT code, trade_date, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date BETWEEN %s AND %s
      AND factor_name IN ({placeholders})
      AND neutral_value IS NOT NULL
    ORDER BY trade_date, code
    """
    params = [TRAIN_START, TEST_END] + BASELINE_FEATURES
    df_long = pd.read_sql(sql_factors, conn, params=params)

    if df_long.empty:
        logger.error("无基线因子数据")
        return pd.DataFrame()

    df_wide = df_long.pivot_table(
        index=["trade_date", "code"],
        columns="factor_name",
        values="neutral_value",
        aggfunc="first",
    ).reset_index()
    df_wide.columns.name = None
    df_wide["trade_date"] = pd.to_datetime(df_wide["trade_date"]).dt.date

    t_baseline = time.time() - t0
    logger.info(f"基线因子: {len(df_long)}行 -> {len(df_wide)}行宽表, {t_baseline:.1f}s")

    # 2. 逐日加载2个基本面delta因子
    logger.info(f"加载 {len(TOP2_DELTA_FEATURES)} 个基本面delta因子 (PIT)...")
    all_trade_dates = sorted(df_wide["trade_date"].unique())
    logger.info(f"  交易日: {all_trade_dates[0]} ~ {all_trade_dates[-1]}, {len(all_trade_dates)}天")

    fund_rows = []
    for i, td in enumerate(all_trade_dates):
        if i % 50 == 0:
            logger.info(f"  基本面因子: {i}/{len(all_trade_dates)} ({td})")
        fund_data = load_fundamental_pit_data(td, conn)

        codes = df_wide[df_wide["trade_date"] == td]["code"].values
        for code in codes:
            row = {"trade_date": td, "code": code}
            for fname in TOP2_DELTA_FEATURES:
                series = fund_data.get(fname, pd.Series(dtype=float))
                row[fname] = series.get(code, np.nan)
            fund_rows.append(row)

    df_fund = pd.DataFrame(fund_rows)
    t_fund = time.time() - t0 - t_baseline
    logger.info(f"基本面因子: {len(df_fund)}行, {t_fund:.1f}s")

    # 3. 合并
    df_merged = df_wide.merge(df_fund, on=["trade_date", "code"], how="left")

    # 4. 目标变量: T+20日超额收益
    sql_target = """
    WITH latest_adj AS (
        SELECT DISTINCT ON (code)
            code, adj_factor AS latest_adj_factor
        FROM klines_daily
        ORDER BY code, trade_date DESC
    ),
    stock_ret AS (
        SELECT
            k1.code,
            k1.trade_date,
            k2.close * k2.adj_factor / la.latest_adj_factor
            / NULLIF(k1.close * k1.adj_factor / la.latest_adj_factor, 0) - 1
                AS stock_return_20
        FROM klines_daily k1
        JOIN latest_adj la ON k1.code = la.code
        JOIN LATERAL (
            SELECT code, close, adj_factor, trade_date
            FROM klines_daily k2
            WHERE k2.code = k1.code
              AND k2.trade_date > k1.trade_date
            ORDER BY k2.trade_date
            OFFSET 19 LIMIT 1
        ) k2 ON TRUE
        WHERE k1.trade_date BETWEEN %s AND %s
          AND k1.adj_factor IS NOT NULL
          AND k1.volume > 0
    ),
    index_ret AS (
        SELECT
            i1.trade_date,
            i2.close / NULLIF(i1.close, 0) - 1 AS index_return_20
        FROM index_daily i1
        JOIN LATERAL (
            SELECT close, trade_date
            FROM index_daily i2
            WHERE i2.index_code = '000300.SH'
              AND i2.trade_date > i1.trade_date
            ORDER BY i2.trade_date
            OFFSET 19 LIMIT 1
        ) i2 ON TRUE
        WHERE i1.index_code = '000300.SH'
          AND i1.trade_date BETWEEN %s AND %s
    )
    SELECT
        s.code,
        s.trade_date,
        LN(1 + s.stock_return_20) - LN(1 + i.index_return_20)
            AS excess_return_20
    FROM stock_ret s
    JOIN index_ret i ON s.trade_date = i.trade_date
    WHERE s.stock_return_20 IS NOT NULL
      AND i.index_return_20 IS NOT NULL
      AND ABS(s.stock_return_20) < 5.0
      AND ABS(i.index_return_20) < 5.0
    """
    df_target = pd.read_sql(
        sql_target, conn,
        params=(TRAIN_START, TEST_END, TRAIN_START, TEST_END),
    )
    df_target["trade_date"] = pd.to_datetime(df_target["trade_date"]).dt.date

    t_target = time.time() - t0 - t_baseline - t_fund
    logger.info(f"目标变量: {len(df_target)}行, {t_target:.1f}s")

    # 5. 合并特征+目标
    df_final = df_merged.merge(
        df_target[["code", "trade_date", "excess_return_20"]],
        on=["code", "trade_date"],
        how="inner",
    )
    df_final = df_final.dropna(subset=["excess_return_20"])

    total_time = time.time() - t0
    logger.info(
        f"特征矩阵: {len(df_final)}行, "
        f"{df_final['code'].nunique()}股, "
        f"{df_final['trade_date'].nunique()}天, "
        f"耗时{total_time:.1f}s"
    )

    # 缺失率
    for fname in TOP2_DELTA_FEATURES:
        if fname in df_final.columns:
            miss_rate = df_final[fname].isna().mean()
            logger.info(f"  {fname}: {miss_rate:.1%} missing")

    return df_final


def run_f1_fold(df: pd.DataFrame, gpu: bool = True) -> dict:
    """F1 fold LightGBM: 7特征 (5基线 + roe_delta + net_margin_delta)。"""
    import lightgbm as lgb
    from backend.engines.ml_engine import FeaturePreprocessor, compute_icir

    logger.info("=" * 70)
    logger.info("方案6: F1 Fold LightGBM (7特征 = 5基线 + 2 top delta)")
    logger.info(f"特征: {ALL_FEATURES}")
    logger.info("=" * 70)

    t0 = time.time()

    td_col = df["trade_date"]
    train_df = df[(td_col >= TRAIN_START) & (td_col <= TRAIN_END)].copy()
    valid_df = df[(td_col >= VALID_START) & (td_col <= VALID_END)].copy()
    test_df = df[(td_col >= TEST_START) & (td_col <= TEST_END)].copy()

    # Purge: 训练集末尾丢弃20个交易日
    all_train_dates = sorted(train_df["trade_date"].unique())
    if len(all_train_dates) > 20:
        train_cutoff = all_train_dates[-21]
        train_df = train_df[train_df["trade_date"] <= train_cutoff].copy()
        logger.info(f"Purge: 训练集末尾丢弃20天 (cutoff={train_cutoff})")

    logger.info(
        f"数据量: Train={len(train_df)} ({train_df['trade_date'].nunique()}天), "
        f"Valid={len(valid_df)} ({valid_df['trade_date'].nunique()}天), "
        f"Test={len(test_df)} ({test_df['trade_date'].nunique()}天)"
    )

    feature_cols = [c for c in ALL_FEATURES if c in df.columns]
    missing = set(ALL_FEATURES) - set(feature_cols)
    if missing:
        logger.warning(f"缺失特征: {missing}")
    logger.info(f"实际特征: {len(feature_cols)} 个: {feature_cols}")

    # 预处理: MAD + fill + zscore
    preprocessor = FeaturePreprocessor()
    preprocessor.fit(train_df, feature_cols)

    train_p = preprocessor.transform(train_df)
    valid_p = preprocessor.transform(valid_df)
    test_p = preprocessor.transform(test_df)

    X_train = train_p[feature_cols].values.astype(np.float32)
    y_train = train_p["excess_return_20"].values.astype(np.float32)
    X_valid = valid_p[feature_cols].values.astype(np.float32)
    y_valid = valid_p["excess_return_20"].values.astype(np.float32)
    X_test = test_p[feature_cols].values.astype(np.float32)
    y_test = test_p["excess_return_20"].values.astype(np.float32)

    logger.info(f"X_train: {X_train.shape}, X_valid: {X_valid.shape}, X_test: {X_test.shape}")

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    # LightGBM参数 (Sprint 1.4b配置)
    lgb_params = {
        "objective": "regression",
        "metric": "mse",
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "max_depth": 6,
        "min_child_samples": 50,
        "reg_alpha": 1.0,
        "reg_lambda": 5.0,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "subsample_freq": 1,
        "n_jobs": -1,
        "seed": 42,
        "verbose": -1,
    }
    if gpu:
        lgb_params.update({
            "device_type": "gpu",
            "gpu_platform_id": 0,
            "gpu_device_id": 0,
            "gpu_use_dp": False,
            "max_bin": 63,
        })
    else:
        lgb_params["max_bin"] = 255

    callbacks = [
        lgb.early_stopping(stopping_rounds=50, verbose=True),
        lgb.log_evaluation(period=50),
    ]

    logger.info("LightGBM训练开始...")
    model = lgb.train(
        lgb_params,
        train_data,
        num_boost_round=500,
        valid_sets=[valid_data],
        valid_names=["valid"],
        callbacks=callbacks,
    )

    best_iter = model.best_iteration
    logger.info(f"Best iteration: {best_iter}")

    # IC计算
    def compute_daily_ic(df_part, preds, method="pearson"):
        temp = df_part[["trade_date", "excess_return_20"]].copy()
        temp["predicted"] = preds
        daily_ics = {}
        for td, group in temp.groupby("trade_date"):
            if len(group) < 30:
                continue
            pred = group["predicted"]
            actual = group["excess_return_20"]
            if method == "spearman":
                ic = pred.rank().corr(actual.rank())
            else:
                ic = pred.corr(actual)
            if not np.isnan(ic):
                daily_ics[td] = ic
        return pd.Series(daily_ics)

    train_pred = model.predict(X_train, num_iteration=best_iter)
    valid_pred = model.predict(X_valid, num_iteration=best_iter)
    test_pred = model.predict(X_test, num_iteration=best_iter)

    train_ic_s = compute_daily_ic(train_p, train_pred)
    valid_ic_s = compute_daily_ic(valid_p, valid_pred)
    test_ic_s = compute_daily_ic(test_p, test_pred)
    test_rank_ic_s = compute_daily_ic(test_p, test_pred, method="spearman")

    train_ic = float(train_ic_s.mean()) if len(train_ic_s) > 0 else 0.0
    valid_ic = float(valid_ic_s.mean()) if len(valid_ic_s) > 0 else 0.0
    oos_ic = float(test_ic_s.mean()) if len(test_ic_s) > 0 else 0.0
    oos_rank_ic = float(test_rank_ic_s.mean()) if len(test_rank_ic_s) > 0 else 0.0
    oos_icir = compute_icir(test_ic_s)
    overfit_ratio = train_ic / valid_ic if valid_ic > 1e-8 else 99.0

    # 特征重要性
    importance = model.feature_importance(importance_type="gain")
    feat_imp = dict(zip(feature_cols, [float(v) for v in importance]))

    elapsed = time.time() - t0

    result = {
        "train_ic": train_ic,
        "valid_ic": valid_ic,
        "oos_ic": oos_ic,
        "oos_rank_ic": oos_rank_ic,
        "oos_icir": oos_icir,
        "overfit_ratio": overfit_ratio,
        "best_iter": best_iter,
        "feature_importance": feat_imp,
        "elapsed": elapsed,
    }

    # ========== 输出结果 ==========
    print("\n")
    print("=" * 80)
    print("方案6结果: F1 Fold LightGBM (7特征 = 5基线 + roe_delta + net_margin_delta)")
    print("=" * 80)
    print(f"  Train IC:      {train_ic:.4f}")
    print(f"  Valid IC:      {valid_ic:.4f}")
    print(f"  OOS IC:        {oos_ic:.4f}")
    print(f"  OOS RankIC:    {oos_rank_ic:.4f}")
    print(f"  OOS ICIR:      {oos_icir:.3f}")
    print(f"  Overfit Ratio: {overfit_ratio:.2f}")
    print(f"  Best Iter:     {best_iter}")
    print(f"  耗时:          {elapsed:.1f}s")

    # 特征重要性
    print(f"\n{'特征重要性 (Gain)':=^50}")
    max_imp = max(feat_imp.values()) if feat_imp else 1
    for feat, imp in sorted(feat_imp.items(), key=lambda x: -x[1]):
        bar = "#" * int(imp / max_imp * 30)
        print(f"  {feat:<28}: {imp:>10.1f}  {bar}")

    # 对比表
    print(f"\n{'对比表':=^60}")
    print(f"{'配置':<25} | {'Train IC':>9} | {'Valid IC':>9} | {'OOS IC':>9} | {'Best Iter':>9} | {'Overfit':>8}")
    print("-" * 85)
    print(f"{'5基线(Sprint1.4b)':<25} | {BASELINE_TRAIN_IC:>9.4f} | {BASELINE_VALID_IC:>9.4f} | {BASELINE_OOS_IC:>9.4f} | {BASELINE_BEST_ITER:>9d} | {BASELINE_OVERFIT:>8.2f}")
    print(f"{'7特征(5+2 top delta)':<25} | {train_ic:>9.4f} | {valid_ic:>9.4f} | {oos_ic:>9.4f} | {best_iter:>9d} | {overfit_ratio:>8.2f}")

    # delta增量
    delta_ic = oos_ic - BASELINE_OOS_IC
    print(f"\n  OOS IC增量: {delta_ic:+.4f} ({'改善' if delta_ic > 0 else '恶化'})")

    # 判定
    print(f"\n{'判定':=^50}")
    pass_iter = best_iter > 2
    pass_ic = oos_ic > BASELINE_OOS_IC
    print(f"  [{'PASS' if pass_iter else 'FAIL'}] best_iter > 2: {best_iter}")
    print(f"  [{'PASS' if pass_ic else 'FAIL'}] OOS IC > {BASELINE_OOS_IC}: {oos_ic:.4f}")

    if pass_iter and pass_ic:
        print(f"\n  >>> PASS: top-2 delta特征有增量价值，可考虑全量7-fold验证")
    elif pass_iter and not pass_ic:
        print(f"\n  >>> MARGINAL: 模型能学(iter>{2}), 但OOS IC未超基线")
    else:
        print(f"\n  >>> FAIL: top-2 delta特征增量不足")

    print("=" * 80)

    return result


def main():
    from app.services.price_utils import _get_sync_conn

    t_start = time.time()

    conn = _get_sync_conn()

    try:
        logger.info("=" * 70)
        logger.info("方案6: 只加top 2个delta特征到LightGBM")
        logger.info(f"特征集: {ALL_FEATURES}")
        logger.info("=" * 70)

        # 加载数据
        df = load_features(conn)
        if df.empty:
            logger.error("特征矩阵为空，退出")
            return

        # 运行F1 fold
        result = run_f1_fold(df, gpu=True)

        total = time.time() - t_start
        logger.info(f"\n总耗时: {total:.1f}s ({total/60:.1f}min)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
