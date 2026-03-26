"""方案5+6: F1 fold LightGBM对比测试。

方案5: 6特征 (5基线 + days_since_announcement)
方案6: 7特征 (5基线 + roe_delta + net_margin_delta)

基线: 5特征 Sprint 1.4b结果: OOS IC=0.0823, best_iter=52
成功标准: OOS IC>=0.082 且 best_iter>10

F1 Fold:
  Train: 2020-07-01 ~ 2022-06-30
  Valid: 2022-07-01 ~ 2022-12-31
  Test(OOS): 2023-01-01 ~ 2023-06-30
  Purge gap: 20 trading days

OOM修复: 批量SQL+Python端计算, 不逐日调用load_financial_pit。
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

(project_root / "models").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            project_root / "models" / "test_days_since_only.log", mode="w"
        ),
    ],
)
logger = logging.getLogger(__name__)

DATE_START = date(2020, 7, 1)
DATE_END = date(2023, 6, 30)


# ============================================================
# 数据加载 (OOM-safe)
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


def load_days_since_batch(conn, trade_dates: list[date]) -> pd.DataFrame:
    """批量计算days_since_announcement，单次SQL+bisect。"""
    t0 = time.time()
    min_date = min(trade_dates)
    max_date = max(trade_dates)
    lookback_date = min_date - timedelta(days=400)

    sql = """
    SELECT DISTINCT code, actual_ann_date
    FROM financial_indicators
    WHERE actual_ann_date BETWEEN %s AND %s
      AND actual_ann_date IS NOT NULL
    ORDER BY code, actual_ann_date
    """
    logger.info(f"查询公告日: {lookback_date} ~ {max_date}")
    df_ann = pd.read_sql(sql, conn, params=(lookback_date, max_date))
    df_ann["actual_ann_date"] = pd.to_datetime(df_ann["actual_ann_date"]).dt.date
    logger.info(f"公告日记录: {len(df_ann)}行, {df_ann['code'].nunique()}股")

    if df_ann.empty:
        return pd.DataFrame(columns=["trade_date", "code", "days_since_announcement"])

    code_anns = {}
    for code, grp in df_ann.groupby("code"):
        code_anns[code] = sorted(grp["actual_ann_date"].tolist())

    results = []
    codes = sorted(code_anns.keys())
    for i, code in enumerate(codes):
        if i % 500 == 0:
            logger.info(f"  days_since: {i}/{len(codes)}")
        anns = code_anns[code]
        for td in trade_dates:
            idx = bisect.bisect_right(anns, td)
            if idx == 0:
                continue
            days_val = float(max(0, min(365, (td - anns[idx - 1]).days)))
            results.append((td, code, days_val))

    df = pd.DataFrame(results, columns=["trade_date", "code", "days_since_announcement"])
    logger.info(f"days_since_announcement: {len(df)}行, {time.time()-t0:.1f}s")
    return df


def load_delta_features_batch(
    conn, trade_dates: list[date]
) -> pd.DataFrame:
    """批量计算roe_delta和net_margin_delta (OOM-safe)。

    一次性加载financial_indicators (~91K行), Python端计算delta,
    用bisect匹配到每个交易日。

    Returns:
        DataFrame[trade_date, code, roe_delta, net_margin_delta]
    """
    t0 = time.time()
    max_date = max(trade_dates)

    sql = """
    WITH ranked AS (
        SELECT code, report_date, actual_ann_date,
               roe, roe_dt, net_profit_margin,
               ROW_NUMBER() OVER (
                   PARTITION BY code, report_date
                   ORDER BY actual_ann_date DESC
               ) AS rn
        FROM financial_indicators
        WHERE actual_ann_date <= %s
          AND actual_ann_date IS NOT NULL
    )
    SELECT code, report_date, actual_ann_date, roe, roe_dt, net_profit_margin
    FROM ranked WHERE rn = 1
    ORDER BY code, report_date
    """
    logger.info(f"加载PIT财务数据 (截至{max_date})...")
    df_fina = pd.read_sql(sql, conn, params=(max_date,))
    df_fina["actual_ann_date"] = pd.to_datetime(df_fina["actual_ann_date"]).dt.date
    df_fina["report_date"] = pd.to_datetime(df_fina["report_date"]).dt.date
    logger.info(f"PIT财务数据: {len(df_fina)}行, {df_fina['code'].nunique()}股")

    # 对每只股票按report_date排序, 计算连续两季的delta
    delta_records = []
    for code, grp in df_fina.groupby("code"):
        grp = grp.sort_values("report_date")
        for i in range(1, len(grp)):
            curr = grp.iloc[i]
            prev = grp.iloc[i - 1]
            ann_date = curr["actual_ann_date"]

            # roe_delta
            roe_col = "roe_dt" if pd.notna(curr["roe_dt"]) and pd.notna(prev["roe_dt"]) else "roe"
            roe_curr = curr[roe_col]
            roe_prev = prev[roe_col]
            roe_delta = np.nan
            if pd.notna(roe_curr) and pd.notna(roe_prev):
                roe_delta = float(roe_curr - roe_prev) / (abs(float(roe_prev)) + 1e-8)
                roe_delta = max(-2.0, min(5.0, roe_delta))

            # net_margin_delta
            nm_curr = curr["net_profit_margin"]
            nm_prev = prev["net_profit_margin"]
            nm_delta = np.nan
            if pd.notna(nm_curr) and pd.notna(nm_prev):
                nm_delta = float(nm_curr) - float(nm_prev)
                nm_delta = max(-100.0, min(100.0, nm_delta))

            delta_records.append((code, ann_date, roe_delta, nm_delta))

    df_deltas = pd.DataFrame(
        delta_records,
        columns=["code", "ann_date", "roe_delta", "net_margin_delta"],
    )
    logger.info(f"Delta记录: {len(df_deltas)}行")

    # 用bisect匹配每个(trade_date, code)的最新delta
    code_deltas = {}
    for code, grp in df_deltas.groupby("code"):
        grp_sorted = grp.sort_values("ann_date")
        code_deltas[code] = (
            grp_sorted["ann_date"].tolist(),
            grp_sorted["roe_delta"].tolist(),
            grp_sorted["net_margin_delta"].tolist(),
        )

    results = []
    codes = sorted(code_deltas.keys())
    for i, code in enumerate(codes):
        if i % 500 == 0:
            logger.info(f"  delta匹配: {i}/{len(codes)}")
        ann_dates, roe_vals, nm_vals = code_deltas[code]
        for td in trade_dates:
            idx = bisect.bisect_right(ann_dates, td)
            if idx == 0:
                continue
            results.append((td, code, roe_vals[idx - 1], nm_vals[idx - 1]))

    df_result = pd.DataFrame(
        results, columns=["trade_date", "code", "roe_delta", "net_margin_delta"]
    )
    elapsed = time.time() - t0
    logger.info(f"roe_delta+net_margin_delta: {len(df_result)}行, {elapsed:.1f}s")
    return df_result


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
# F1 Fold LightGBM (通用)
# ============================================================


def run_f1_fold(
    df: pd.DataFrame,
    feature_names: list[str],
    scheme_label: str,
    gpu: bool = True,
) -> dict:
    """F1 fold LightGBM训练+评估 (通用版)。"""
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
    y_test = test_p["excess_return_20"].values.astype(np.float32)

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
            if method == "spearman":
                ic = pred.rank().corr(actual.rank())
            else:
                ic = pred.corr(actual)
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
    feat_imp = dict(zip(feature_cols, [float(v) for v in importance]))

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

    pass_iter = best_iter > 10
    pass_ic = oos_ic >= 0.082
    print(f"\n{'判定':=^50}")
    print(f"  [{'PASS' if pass_iter else 'FAIL'}] best_iter > 10: {best_iter}")
    print(f"  [{'PASS' if pass_ic else 'FAIL'}] OOS IC >= 0.082: {oos_ic:.4f}")
    if pass_iter and pass_ic:
        print(f"\n  >>> PASS")
    elif pass_iter and not pass_ic:
        print(f"\n  >>> PARTIAL: 模型能学习(iter>10)但OOS IC不足")
    else:
        print(f"\n  >>> FAIL")
    print("=" * 80)

    return result


# ============================================================
# Main
# ============================================================


def main():
    from app.services.price_utils import _get_sync_conn

    t_start = time.time()
    (project_root / "models").mkdir(parents=True, exist_ok=True)

    conn = _get_sync_conn()

    try:
        from engines.factor_engine import LGBM_V2_BASELINE_FACTORS

        baseline = LGBM_V2_BASELINE_FACTORS

        # ========== 共享数据加载 ==========
        logger.info("=" * 70)
        logger.info("共享数据加载 (方案5+6共用)")
        logger.info("=" * 70)

        logger.info("Step 1: 加载5基线因子...")
        df_baseline = load_baseline_factors(conn, DATE_START, DATE_END)
        if df_baseline.empty:
            logger.error("基线因子为空，退出")
            return
        trade_dates = sorted(df_baseline["trade_date"].unique())

        logger.info("Step 2: 批量计算days_since_announcement...")
        df_days = load_days_since_batch(conn, trade_dates)

        logger.info("Step 3: 批量计算roe_delta + net_margin_delta...")
        df_deltas = load_delta_features_batch(conn, trade_dates)

        logger.info("Step 4: 加载目标变量...")
        df_target = load_target(conn, DATE_START, DATE_END)

        # ========== 方案5: 5基线 + days_since ==========
        logger.info("\n" + "=" * 70)
        logger.info("方案5: 5基线 + days_since_announcement (6特征)")
        logger.info("=" * 70)

        df5 = df_baseline.merge(df_days, on=["trade_date", "code"], how="left")
        df5 = df5.merge(
            df_target[["code", "trade_date", "excess_return_20"]],
            on=["code", "trade_date"], how="inner",
        )
        df5 = df5.dropna(subset=["excess_return_20"])
        miss5 = df5["days_since_announcement"].isna().mean()
        logger.info(f"方案5矩阵: {len(df5)}行, days_since缺失率={miss5:.1%}")

        feat5 = baseline + ["days_since_announcement"]
        result5 = run_f1_fold(df5, feat5, "方案5: 5基线+days_since (6F)", gpu=True)
        del df5
        gc.collect()

        # ========== 方案6: 5基线 + roe_delta + net_margin_delta ==========
        logger.info("\n" + "=" * 70)
        logger.info("方案6: 5基线 + roe_delta + net_margin_delta (7特征)")
        logger.info("=" * 70)

        df6 = df_baseline.merge(df_deltas, on=["trade_date", "code"], how="left")
        df6 = df6.merge(
            df_target[["code", "trade_date", "excess_return_20"]],
            on=["code", "trade_date"], how="inner",
        )
        df6 = df6.dropna(subset=["excess_return_20"])
        miss_roe = df6["roe_delta"].isna().mean()
        miss_nm = df6["net_margin_delta"].isna().mean()
        logger.info(
            f"方案6矩阵: {len(df6)}行, "
            f"roe_delta缺失={miss_roe:.1%}, net_margin_delta缺失={miss_nm:.1%}"
        )

        feat6 = baseline + ["roe_delta", "net_margin_delta"]
        result6 = run_f1_fold(df6, feat6, "方案6: 5基线+top2delta (7F)", gpu=True)
        del df6
        gc.collect()

        # ========== 总对比表 ==========
        print("\n\n")
        print("=" * 90)
        print("方案5+6 总对比表")
        print("=" * 90)
        hdr = (
            f"{'配置':<30} | {'Train IC':>9} | {'Valid IC':>9} | "
            f"{'OOS IC':>9} | {'Best Iter':>9} | {'Overfit':>8}"
        )
        print(hdr)
        print("-" * 90)
        print(
            f"{'5基线(Sprint1.4b)':<30} | {'0.1308':>9} | {'0.1208':>9} | "
            f"{'0.0823':>9} | {'52':>9} | {'1.08':>8}"
        )
        print(
            f"{'5+7delta(Sprint1.5,13F)':<30} | {'0.1266':>9} | {'0.0901':>9} | "
            f"{'0.0439':>9} | {'6':>9} | {'1.41':>8}"
        )
        for r in [result5, result6]:
            print(
                f"{r['scheme']:<30} | {r['train_ic']:>9.4f} | {r['valid_ic']:>9.4f} | "
                f"{r['oos_ic']:>9.4f} | {r['best_iter']:>9d} | {r['overfit_ratio']:>8.2f}"
            )

        print(f"\n{'最终判定':=^60}")
        for r in [result5, result6]:
            p_iter = "PASS" if r["best_iter"] > 10 else "FAIL"
            p_ic = "PASS" if r["oos_ic"] >= 0.082 else "FAIL"
            overall = "PASS" if r["best_iter"] > 10 and r["oos_ic"] >= 0.082 else "FAIL"
            print(
                f"  {r['scheme']:<35}: iter={r['best_iter']:>3}({p_iter}) "
                f"IC={r['oos_ic']:.4f}({p_ic}) => {overall}"
            )
        print("=" * 90)

        total = time.time() - t_start
        logger.info(f"\n总耗时: {total:.1f}s ({total/60:.1f}min)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
