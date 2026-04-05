"""Sprint 1.6: 业绩预告因子LightGBM F1 Fold增量测试。

对比:
  基线: 5特征 (Sprint 1.4b结果: OOS IC=0.0823, best_iter=52)
  方案A: 8特征 (5基线 + 3 forecast因子)

Forecast因子 (IC快筛全PASS):
  - forecast_surprise_type: 3.66%
  - forecast_magnitude: 3.07%
  - forecast_recency: 2.09%

数据源: models/forecast_cache.csv (Tushare forecast接口, PIT对齐)

F1 Fold:
  Train: 2020-07-01 ~ 2022-06-30
  Valid: 2022-07-01 ~ 2022-12-31
  Test(OOS): 2023-01-01 ~ 2023-06-30
  Purge gap: 20 trading days

成功标准: best_iter > 2 且 OOS IC > 0.0823
"""

import bisect
import gc
import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

(project_root / "models").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            project_root / "models" / "test_forecast_lgbm.log", mode="w"
        ),
    ],
)
logger = logging.getLogger(__name__)

DATE_START = date(2020, 7, 1)
DATE_END = date(2023, 6, 30)

# 预告类型 -> 方向分数
FORECAST_TYPE_MAP = {
    "预增": 1, "扭亏": 1, "续盈": 1, "略增": 1,
    "预减": -1, "首亏": -1, "续亏": -1, "略减": -1,
    "不确定": 0, "其他": 0,
}


# ============================================================
# 数据加载
# ============================================================


def load_baseline_factors(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """从factor_values读5基线因子neutral_value，pivot成宽表。"""
    from engines.factor_engine import LGBM_V2_BASELINE_FACTORS

    baseline_features = LGBM_V2_BASELINE_FACTORS
    placeholders = ",".join(["%s"] * len(baseline_features))
    sql = f"""
    SELECT code, trade_date, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date BETWEEN %s AND %s
      AND factor_name IN ({placeholders})
      AND neutral_value IS NOT NULL
    ORDER BY trade_date, code
    """
    params = [start_date, end_date] + baseline_features
    t0 = time.time()
    df_long = pd.read_sql(sql, conn, params=params)
    logger.info(f"基线因子加载: {len(df_long)}行, {time.time()-t0:.1f}s")

    if df_long.empty:
        return pd.DataFrame()

    df_wide = df_long.pivot_table(
        index=["trade_date", "code"],
        columns="factor_name",
        values="neutral_value",
        aggfunc="first",
    ).reset_index()
    df_wide.columns.name = None
    df_wide["trade_date"] = pd.to_datetime(df_wide["trade_date"]).dt.date
    logger.info(
        f"基线宽表: {len(df_wide)}行, {df_wide['code'].nunique()}股, "
        f"{df_wide['trade_date'].nunique()}天"
    )
    del df_long
    gc.collect()
    return df_wide


def load_forecast_factors(
    csv_path: Path, trade_dates: list[date]
) -> pd.DataFrame:
    """从forecast_cache.csv加载并计算3个PIT因子，匹配到每个交易日。

    Returns:
        DataFrame[trade_date, code, forecast_surprise_type,
                  forecast_magnitude, forecast_recency]
    """
    t0 = time.time()
    logger.info(f"加载forecast缓存: {csv_path}")
    raw = pd.read_csv(csv_path, dtype={"ann_date": str, "end_date": str})
    logger.info(f"原始数据: {len(raw)}行, {raw['ts_code'].nunique()}股")

    # 预处理
    raw["code"] = raw["ts_code"].str.replace(r"\.(SH|SZ|BJ)", "", regex=True)
    raw["ann_date"] = pd.to_datetime(raw["ann_date"])

    # 去重: 同一(code, end_date)取ann_date最新
    raw = raw.sort_values("ann_date", ascending=False)
    raw = raw.drop_duplicates(subset=["code", "end_date"], keep="first")
    logger.info(f"去重后: {len(raw)}行, {raw['code'].nunique()}股")

    # 预计算因子值: 每条记录的 surprise_type, magnitude
    raw["surprise_type_val"] = raw["type"].map(FORECAST_TYPE_MAP).fillna(0).astype(float)
    raw["magnitude_val"] = (
        (raw["p_change_max"].fillna(0) + raw["p_change_min"].fillna(0)) / 2 / 100
    ).clip(-3.0, 5.0)

    # 按code分组，用bisect做PIT匹配
    code_records: dict[str, tuple[list, list, list]] = {}
    for code, grp in raw.groupby("code"):
        grp_sorted = grp.sort_values("ann_date")
        ann_dates = grp_sorted["ann_date"].tolist()
        surprise_vals = grp_sorted["surprise_type_val"].tolist()
        magnitude_vals = grp_sorted["magnitude_val"].tolist()
        code_records[code] = (ann_dates, surprise_vals, magnitude_vals)

    results = []
    codes = sorted(code_records.keys())
    for i, code in enumerate(codes):
        if i % 500 == 0:
            logger.info(f"  forecast PIT匹配: {i}/{len(codes)}")
        ann_dates, surprise_vals, magnitude_vals = code_records[code]
        # Convert to date for bisect comparison
        ann_dates_ts = ann_dates  # already Timestamp

        for td in trade_dates:
            td_ts = pd.Timestamp(td)
            idx = bisect.bisect_right(ann_dates_ts, td_ts)
            if idx == 0:
                continue
            latest_ann = ann_dates_ts[idx - 1]
            recency = max(0, min(365, (td_ts - latest_ann).days))
            results.append((
                td, code,
                surprise_vals[idx - 1],
                magnitude_vals[idx - 1],
                float(recency),
            ))

    df = pd.DataFrame(
        results,
        columns=["trade_date", "code",
                 "forecast_surprise_type", "forecast_magnitude",
                 "forecast_recency"],
    )
    logger.info(
        f"Forecast因子: {len(df)}行, {df['code'].nunique()}股, "
        f"{time.time()-t0:.1f}s"
    )
    return df


def load_target(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """加载T+20日超额收益目标变量。"""
    sql = """
    WITH latest_adj AS (
        SELECT DISTINCT ON (code)
            code, adj_factor AS latest_adj_factor
        FROM klines_daily
        ORDER BY code, trade_date DESC
    ),
    stock_ret AS (
        SELECT
            k1.code, k1.trade_date,
            k2.close * k2.adj_factor / la.latest_adj_factor
            / NULLIF(k1.close * k1.adj_factor / la.latest_adj_factor, 0) - 1
                AS stock_return_20
        FROM klines_daily k1
        JOIN latest_adj la ON k1.code = la.code
        JOIN LATERAL (
            SELECT code, close, adj_factor, trade_date
            FROM klines_daily k2
            WHERE k2.code = k1.code AND k2.trade_date > k1.trade_date
            ORDER BY k2.trade_date OFFSET 19 LIMIT 1
        ) k2 ON TRUE
        WHERE k1.trade_date BETWEEN %s AND %s
          AND k1.adj_factor IS NOT NULL AND k1.volume > 0
    ),
    index_ret AS (
        SELECT i1.trade_date,
            i2.close / NULLIF(i1.close, 0) - 1 AS index_return_20
        FROM index_daily i1
        JOIN LATERAL (
            SELECT close, trade_date FROM index_daily i2
            WHERE i2.index_code = '000300.SH' AND i2.trade_date > i1.trade_date
            ORDER BY i2.trade_date OFFSET 19 LIMIT 1
        ) i2 ON TRUE
        WHERE i1.index_code = '000300.SH' AND i1.trade_date BETWEEN %s AND %s
    )
    SELECT s.code, s.trade_date,
        LN(1 + s.stock_return_20) - LN(1 + i.index_return_20) AS excess_return_20
    FROM stock_ret s
    JOIN index_ret i ON s.trade_date = i.trade_date
    WHERE s.stock_return_20 IS NOT NULL AND i.index_return_20 IS NOT NULL
      AND ABS(s.stock_return_20) < 5.0 AND ABS(i.index_return_20) < 5.0
    """
    t0 = time.time()
    df = pd.read_sql(sql, conn, params=(start_date, end_date, start_date, end_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    logger.info(f"目标变量: {len(df)}行, {time.time()-t0:.1f}s")
    return df


# ============================================================
# F1 Fold LightGBM
# ============================================================


def run_f1_fold(
    df: pd.DataFrame,
    feature_names: list[str],
    scheme_label: str,
    gpu: bool = True,
) -> dict:
    """F1 fold LightGBM训练+评估。"""
    import lightgbm as lgb
    from engines.ml_engine import FeaturePreprocessor, compute_icir

    logger.info("=" * 70)
    logger.info(f"F1 Fold LightGBM: {scheme_label}")
    logger.info(f"特征 ({len(feature_names)}): {feature_names}")
    logger.info("=" * 70)

    t0 = time.time()

    train_start, train_end = date(2020, 7, 1), date(2022, 6, 30)
    valid_start, valid_end = date(2022, 7, 1), date(2022, 12, 31)
    test_start, test_end = date(2023, 1, 1), date(2023, 6, 30)

    td_col = df["trade_date"]
    train_df = df[(td_col >= train_start) & (td_col <= train_end)].copy()
    valid_df = df[(td_col >= valid_start) & (td_col <= valid_end)].copy()
    test_df = df[(td_col >= test_start) & (td_col <= test_end)].copy()

    # Purge: 训练集末尾丢弃20天
    all_train_dates = sorted(train_df["trade_date"].unique())
    if len(all_train_dates) > 20:
        train_cutoff = all_train_dates[-21]
        train_df = train_df[train_df["trade_date"] <= train_cutoff].copy()
        logger.info(f"Purge: cutoff={train_cutoff}")

    logger.info(
        f"数据量: Train={len(train_df)} ({train_df['trade_date'].nunique()}天), "
        f"Valid={len(valid_df)} ({valid_df['trade_date'].nunique()}天), "
        f"Test={len(test_df)} ({test_df['trade_date'].nunique()}天)"
    )

    feature_cols = [c for c in feature_names if c in df.columns]
    missing = set(feature_names) - set(feature_cols)
    if missing:
        logger.warning(f"缺失特征: {missing}")
    logger.info(f"实际使用特征: {len(feature_cols)} 个")

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
    test_p["excess_return_20"].values.astype(np.float32)

    logger.info(f"X_train: {X_train.shape}, X_valid: {X_valid.shape}, X_test: {X_test.shape}")

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

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
        lgb_params, train_data,
        num_boost_round=500,
        valid_sets=[valid_data],
        valid_names=["valid"],
        callbacks=callbacks,
    )

    best_iter = model.best_iteration
    logger.info(f"Best iteration: {best_iter}")

    def compute_daily_ic(df_part, preds, method="pearson"):
        temp = df_part[["trade_date", "excess_return_20"]].copy()
        temp["predicted"] = preds
        daily_ics = {}
        for td_val, group in temp.groupby("trade_date"):
            if len(group) < 30:
                continue
            pred = group["predicted"]
            actual = group["excess_return_20"]
            ic = pred.rank().corr(actual.rank()) if method == "spearman" else pred.corr(actual)
            if not np.isnan(ic):
                daily_ics[td_val] = ic
        return pd.Series(daily_ics)

    train_pred = model.predict(X_train, num_iteration=best_iter)
    valid_pred = model.predict(X_valid, num_iteration=best_iter)
    test_pred = model.predict(X_test, num_iteration=best_iter)

    train_ic_s = compute_daily_ic(train_p, train_pred)
    valid_ic_s = compute_daily_ic(valid_p, valid_pred)
    test_ic_s = compute_daily_ic(test_p, test_pred)

    train_ic = float(train_ic_s.mean()) if len(train_ic_s) > 0 else 0.0
    valid_ic = float(valid_ic_s.mean()) if len(valid_ic_s) > 0 else 0.0
    oos_ic = float(test_ic_s.mean()) if len(test_ic_s) > 0 else 0.0
    oos_icir = compute_icir(test_ic_s)

    test_rank_ic_s = compute_daily_ic(test_p, test_pred, method="spearman")
    oos_rank_ic = float(test_rank_ic_s.mean()) if len(test_rank_ic_s) > 0 else 0.0

    overfit_ratio = train_ic / valid_ic if valid_ic > 1e-8 else 99.0

    importance = model.feature_importance(importance_type="gain")
    feat_imp = dict(zip(feature_cols, [float(v) for v in importance], strict=False))

    elapsed = time.time() - t0

    result = {
        "scheme": scheme_label,
        "train_ic": train_ic,
        "valid_ic": valid_ic,
        "oos_ic": oos_ic,
        "oos_rank_ic": oos_rank_ic,
        "oos_icir": oos_icir,
        "overfit_ratio": overfit_ratio,
        "best_iter": best_iter,
        "feature_importance": feat_imp,
        "elapsed": elapsed,
        "train_samples": len(train_df),
        "valid_samples": len(valid_df),
        "test_samples": len(test_df),
    }

    # 打印单方案结果
    print(f"\n{'=' * 80}")
    print(f"F1 Fold结果: {scheme_label}")
    print(f"{'=' * 80}")
    print(f"  Train IC:      {train_ic:.4f}")
    print(f"  Valid IC:      {valid_ic:.4f}")
    print(f"  OOS IC:        {oos_ic:.4f}")
    print(f"  OOS RankIC:    {oos_rank_ic:.4f}")
    print(f"  OOS ICIR:      {oos_icir:.3f}")
    print(f"  Overfit Ratio: {overfit_ratio:.2f}")
    print(f"  Best Iter:     {best_iter}")
    print(f"  耗时:          {elapsed:.1f}s")

    print(f"\n{'特征重要性 (Gain)':=^50}")
    max_imp = max(feat_imp.values()) if feat_imp else 1.0
    for feat, imp in sorted(feat_imp.items(), key=lambda x: -x[1]):
        bar = "#" * int(imp / max_imp * 30) if max_imp > 0 else ""
        print(f"  {feat:<28}: {imp:>10.1f}  {bar}")

    pass_iter = best_iter > 2
    pass_ic = oos_ic >= 0.0823
    print(f"\n{'判定':=^50}")
    print(f"  [{'PASS' if pass_iter else 'FAIL'}] best_iter > 2: {best_iter}")
    print(f"  [{'PASS' if pass_ic else 'FAIL'}] OOS IC >= 0.0823: {oos_ic:.4f}")
    if pass_iter and pass_ic:
        print("\n  >>> PASS: forecast因子有增量价值")
    elif pass_iter and not pass_ic:
        print("\n  >>> PARTIAL: 模型能学习(iter>2)但OOS IC不足")
    else:
        print("\n  >>> FAIL: best_iter<=2 说明forecast因子引入噪声")
    print("=" * 80)

    return result


# ============================================================
# Main
# ============================================================


def main():
    from app.services.price_utils import _get_sync_conn

    t_start = time.time()

    # 检查forecast缓存
    csv_path = project_root / "models" / "forecast_cache.csv"
    if not csv_path.exists():
        logger.error(f"Forecast缓存不存在: {csv_path}")
        logger.error("请先运行 scripts/test_forecast_factors.py 生成缓存")
        return

    conn = _get_sync_conn()

    try:
        from engines.factor_engine import LGBM_V2_BASELINE_FACTORS

        baseline = LGBM_V2_BASELINE_FACTORS
        forecast_features = [
            "forecast_surprise_type", "forecast_magnitude", "forecast_recency"
        ]

        # ========== 数据加载 ==========
        logger.info("=" * 70)
        logger.info("Sprint 1.6: 业绩预告因子LightGBM增量测试")
        logger.info("=" * 70)

        logger.info("Step 1: 加载5基线因子...")
        df_baseline = load_baseline_factors(conn, DATE_START, DATE_END)
        if df_baseline.empty:
            logger.error("基线因子为空，退出")
            return
        trade_dates = sorted(df_baseline["trade_date"].unique())
        logger.info(f"交易日范围: {trade_dates[0]} ~ {trade_dates[-1]}, {len(trade_dates)}天")

        logger.info("Step 2: 加载forecast因子 (PIT匹配)...")
        df_forecast = load_forecast_factors(csv_path, trade_dates)

        logger.info("Step 3: 加载目标变量...")
        df_target = load_target(conn, DATE_START, DATE_END)

        # ========== 合并数据 ==========
        logger.info("Step 4: 合并特征矩阵...")
        df_all = df_baseline.merge(df_forecast, on=["trade_date", "code"], how="left")
        df_all = df_all.merge(
            df_target[["code", "trade_date", "excess_return_20"]],
            on=["code", "trade_date"], how="inner",
        )
        df_all = df_all.dropna(subset=["excess_return_20"])

        # 缺失率统计
        for feat in forecast_features:
            miss = df_all[feat].isna().mean()
            logger.info(f"  {feat} 缺失率: {miss:.1%}")

        logger.info(f"合并后矩阵: {len(df_all)}行, {df_all['code'].nunique()}股")

        # ========== 方案A: 5基线 (对照组，同数据集) ==========
        logger.info("\n" + "=" * 70)
        logger.info("对照组: 5基线因子 (同数据集)")
        logger.info("=" * 70)
        result_baseline = run_f1_fold(
            df_all, baseline, "5基线 (对照组, 5F)", gpu=True
        )
        gc.collect()

        # ========== 方案B: 5基线 + 3 forecast ==========
        logger.info("\n" + "=" * 70)
        logger.info("实验组: 5基线 + 3 forecast因子 (8F)")
        logger.info("=" * 70)
        feat8 = baseline + forecast_features
        result_8f = run_f1_fold(
            df_all, feat8, "5基线+3forecast (8F)", gpu=True
        )
        gc.collect()

        # ========== 总对比表 ==========
        print("\n\n")
        print("=" * 100)
        print("Sprint 1.6 总对比表: 业绩预告因子增量测试")
        print("=" * 100)
        hdr = (
            f"{'配置':<30} | {'Train IC':>9} | {'Valid IC':>9} | "
            f"{'OOS IC':>9} | {'OOS ICIR':>9} | {'Best Iter':>9} | {'Overfit':>8}"
        )
        print(hdr)
        print("-" * 100)

        # 历史基线参考
        print(
            f"{'5基线(Sprint1.4b参考)':.<30} | {'0.1308':>9} | {'0.1208':>9} | "
            f"{'0.0823':>9} | {'---':>9} | {'52':>9} | {'1.08':>8}"
        )

        for r in [result_baseline, result_8f]:
            print(
                f"{r['scheme']:<30} | {r['train_ic']:>9.4f} | {r['valid_ic']:>9.4f} | "
                f"{r['oos_ic']:>9.4f} | {r['oos_icir']:>9.3f} | "
                f"{r['best_iter']:>9d} | {r['overfit_ratio']:>8.2f}"
            )

        # IC增量
        delta_ic = result_8f["oos_ic"] - result_baseline["oos_ic"]
        print(f"\nOOS IC增量 (8F - 5F): {delta_ic:+.4f}")

        # 最终判定
        print(f"\n{'最终判定':=^60}")
        p_iter = "PASS" if result_8f["best_iter"] > 2 else "FAIL"
        p_ic = "PASS" if result_8f["oos_ic"] >= 0.0823 else "FAIL"
        overall = "PASS" if result_8f["best_iter"] > 2 and result_8f["oos_ic"] >= 0.0823 else "FAIL"
        print(f"  [{ p_iter}] best_iter > 2:     {result_8f['best_iter']}")
        print(f"  [{p_ic}] OOS IC >= 0.0823:  {result_8f['oos_ic']:.4f}")
        print(f"  IC增量 vs 对照组:       {delta_ic:+.4f}")

        if overall == "PASS":
            print("\n  >>> PASS: forecast因子在LightGBM中有显著增量价值")
            print("  >>> 建议: 进入全7-fold walk-forward验证")
        elif result_8f["best_iter"] > 2:
            print("\n  >>> PARTIAL: 模型能学习forecast信号, 但OOS IC不达标")
            print("  >>> 建议: 检查forecast因子是否在特定市场状态下有效")
        else:
            print("\n  >>> FAIL: forecast因子引入噪声, best_iter<=2")
            print("  >>> 建议: 放弃forecast因子方向")

        print("=" * 100)

        total = time.time() - t_start
        logger.info(f"\n总耗时: {total:.1f}s ({total/60:.1f}min)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
