"""VWAP+RSRS LightGBM F1 Fold增量测试。

对比:
  对照组: 5基线特征 (Sprint 1.4b参考: OOS IC=0.0823, best_iter=52)
  实验组A: 5基线 + vwap_bias_1d (6F)
  实验组B: 5基线 + rsrs_raw_18 (6F)
  实验组C: 5基线 + vwap_bias_1d + rsrs_raw_18 (7F)

因子定义:
  vwap_bias_1d = (close - VWAP) / VWAP, 其中 VWAP = amount*10000 / (volume*100)
  rsrs_raw_18 = rolling Cov(high, low, 18) / Var(low, 18)

F1 Fold:
  Train: 2020-07-01 ~ 2022-06-30
  Valid: 2022-07-01 ~ 2022-12-31
  Test(OOS): 2023-01-01 ~ 2023-06-30
  Purge gap: 20 trading days

成功标准: best_iter > 10, OOS IC > 0.0823, overfit < 1.30
"""

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
            project_root / "models" / "test_vwap_rsrs_lgbm.log", mode="w"
        ),
    ],
)
logger = logging.getLogger(__name__)

DATE_START = date(2020, 7, 1)
DATE_END = date(2023, 6, 30)


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


def load_klines_for_features(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """从klines_daily加载计算VWAP和RSRS所需的字段。

    需要额外往前取18+几天的数据用于rolling窗口。
    """
    # 往前多取30个自然日以覆盖rolling窗口
    extended_start = date(start_date.year, start_date.month, start_date.day)
    extended_start = extended_start.replace(
        month=max(1, extended_start.month - 2) if extended_start.month > 2
        else extended_start.month,
    )
    # 简单处理：往前60天
    from datetime import timedelta
    extended_start = start_date - timedelta(days=60)

    sql = """
    SELECT code, trade_date, open, high, low, close, volume, amount
    FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
      AND volume > 0
    ORDER BY code, trade_date
    """
    t0 = time.time()
    df = pd.read_sql(sql, conn, params=(extended_start, end_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    logger.info(
        f"K线数据加载: {len(df)}行, {df['code'].nunique()}股, "
        f"{df['trade_date'].nunique()}天, {time.time()-t0:.1f}s"
    )
    return df


def compute_vwap_bias(df_klines: pd.DataFrame) -> pd.DataFrame:
    """计算 vwap_bias_1d = (close - VWAP) / VWAP。

    VWAP = amount(千元)*1000 / (volume(手)*100)
    注意: klines_daily中 amount单位=千元, volume单位=手
    """
    t0 = time.time()
    df = df_klines[["code", "trade_date", "close", "volume", "amount"]].copy()

    # amount(千元) -> 元: *1000; volume(手) -> 股: *100
    vwap = (df["amount"] * 1000) / (df["volume"] * 100)
    df["vwap_bias_1d"] = (df["close"] - vwap) / vwap

    # 极端值clip
    df["vwap_bias_1d"] = df["vwap_bias_1d"].clip(-1.0, 1.0)

    result = df[["code", "trade_date", "vwap_bias_1d"]].dropna(subset=["vwap_bias_1d"])
    logger.info(f"VWAP bias计算完成: {len(result)}行, {time.time()-t0:.1f}s")
    return result


def compute_rsrs_raw(df_klines: pd.DataFrame, window: int = 18) -> pd.DataFrame:
    """计算 rsrs_raw_18 = rolling Cov(high, low, window) / Var(low, window)。

    等价于 high 对 low 的rolling OLS斜率。
    """
    t0 = time.time()
    df = df_klines[["code", "trade_date", "high", "low"]].copy()
    df = df.sort_values(["code", "trade_date"])

    # 按code分组计算rolling统计量
    cov_hl = df.groupby("code").apply(
        lambda g: g["high"].rolling(window, min_periods=window).cov(g["low"]),
        include_groups=False,
    )
    var_l = df.groupby("code").apply(
        lambda g: g["low"].rolling(window, min_periods=window).var(),
        include_groups=False,
    )

    # 展平index
    df["cov_hl"] = cov_hl.droplevel(0) if isinstance(cov_hl.index, pd.MultiIndex) else cov_hl.values
    df["var_l"] = var_l.droplevel(0) if isinstance(var_l.index, pd.MultiIndex) else var_l.values

    df["rsrs_raw_18"] = df["cov_hl"] / df["var_l"].replace(0, np.nan)

    # clip极端值
    df["rsrs_raw_18"] = df["rsrs_raw_18"].clip(-5.0, 5.0)

    result = df[["code", "trade_date", "rsrs_raw_18"]].dropna(subset=["rsrs_raw_18"])
    logger.info(f"RSRS计算完成: {len(result)}行, {time.time()-t0:.1f}s")
    return result


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
    pass_ic = oos_ic >= 0.0823
    pass_overfit = overfit_ratio < 1.30
    print(f"\n{'判定':=^50}")
    print(f"  [{'PASS' if pass_iter else 'FAIL'}] best_iter > 10:    {best_iter}")
    print(f"  [{'PASS' if pass_ic else 'FAIL'}] OOS IC >= 0.0823:  {oos_ic:.4f}")
    print(f"  [{'PASS' if pass_overfit else 'FAIL'}] Overfit < 1.30:   {overfit_ratio:.2f}")

    all_pass = pass_iter and pass_ic and pass_overfit
    if all_pass:
        print(f"\n  >>> PASS: 新因子有增量价值")
    elif pass_iter and not pass_ic:
        print(f"\n  >>> PARTIAL: 模型能学习(iter>10)但OOS IC不足")
    elif not pass_iter:
        print(f"\n  >>> FAIL: best_iter<=10 说明新因子引入噪声")
    else:
        print(f"\n  >>> PARTIAL: 部分指标不达标")
    print("=" * 80)

    return result


# ============================================================
# Main
# ============================================================


def main():
    from app.services.price_utils import _get_sync_conn

    t_start = time.time()
    conn = _get_sync_conn()

    try:
        from engines.factor_engine import LGBM_V2_BASELINE_FACTORS

        baseline = LGBM_V2_BASELINE_FACTORS

        # ========== 数据加载 ==========
        logger.info("=" * 70)
        logger.info("VWAP+RSRS LightGBM F1 Fold增量测试")
        logger.info("=" * 70)

        logger.info("Step 1: 加载5基线因子...")
        df_baseline = load_baseline_factors(conn, DATE_START, DATE_END)
        if df_baseline.empty:
            logger.error("基线因子为空，退出")
            return

        logger.info("Step 2: 加载K线数据 (用于VWAP+RSRS计算)...")
        df_klines = load_klines_for_features(conn, DATE_START, DATE_END)

        logger.info("Step 3: 计算VWAP bias...")
        df_vwap = compute_vwap_bias(df_klines)

        logger.info("Step 4: 计算RSRS...")
        df_rsrs = compute_rsrs_raw(df_klines)
        del df_klines
        gc.collect()

        # 只保留目标日期范围内的新因子
        df_vwap = df_vwap[
            (df_vwap["trade_date"] >= DATE_START) & (df_vwap["trade_date"] <= DATE_END)
        ]
        df_rsrs = df_rsrs[
            (df_rsrs["trade_date"] >= DATE_START) & (df_rsrs["trade_date"] <= DATE_END)
        ]
        logger.info(f"VWAP因子(日期范围内): {len(df_vwap)}行")
        logger.info(f"RSRS因子(日期范围内): {len(df_rsrs)}行")

        logger.info("Step 5: 加载目标变量...")
        df_target = load_target(conn, DATE_START, DATE_END)

        # ========== 构建独立对照组DataFrame ==========
        logger.info("Step 6: 构建各组数据...")

        # 对照组: 纯5基线 (独立DataFrame, 不做left-join)
        df_control = df_baseline.merge(
            df_target[["code", "trade_date", "excess_return_20"]],
            on=["code", "trade_date"], how="inner",
        ).dropna(subset=["excess_return_20"])
        logger.info(f"对照组(5基线): {len(df_control)}行, {df_control['code'].nunique()}股")

        # 实验组A: 5基线 + vwap
        df_exp_a = df_baseline.merge(
            df_vwap, on=["code", "trade_date"], how="inner",
        ).merge(
            df_target[["code", "trade_date", "excess_return_20"]],
            on=["code", "trade_date"], how="inner",
        ).dropna(subset=["excess_return_20"])
        logger.info(f"实验组A(+vwap): {len(df_exp_a)}行")

        # 实验组B: 5基线 + rsrs
        df_exp_b = df_baseline.merge(
            df_rsrs, on=["code", "trade_date"], how="inner",
        ).merge(
            df_target[["code", "trade_date", "excess_return_20"]],
            on=["code", "trade_date"], how="inner",
        ).dropna(subset=["excess_return_20"])
        logger.info(f"实验组B(+rsrs): {len(df_exp_b)}行")

        # 实验组C: 5基线 + vwap + rsrs
        df_exp_c = df_baseline.merge(
            df_vwap, on=["code", "trade_date"], how="inner",
        ).merge(
            df_rsrs, on=["code", "trade_date"], how="inner",
        ).merge(
            df_target[["code", "trade_date", "excess_return_20"]],
            on=["code", "trade_date"], how="inner",
        ).dropna(subset=["excess_return_20"])
        logger.info(f"实验组C(+vwap+rsrs): {len(df_exp_c)}行")

        del df_baseline, df_vwap, df_rsrs, df_target
        gc.collect()

        # ========== 新因子统计 ==========
        print("\n" + "=" * 70)
        print("新因子截面统计 (实验组C)")
        print("=" * 70)
        for feat in ["vwap_bias_1d", "rsrs_raw_18"]:
            vals = df_exp_c[feat]
            print(f"  {feat}:")
            print(f"    mean={vals.mean():.4f}, std={vals.std():.4f}")
            print(f"    min={vals.min():.4f}, 25%={vals.quantile(0.25):.4f}, "
                  f"50%={vals.median():.4f}, 75%={vals.quantile(0.75):.4f}, "
                  f"max={vals.max():.4f}")
            print(f"    缺失率={vals.isna().mean():.1%}")

        # ========== 运行4组F1 Fold ==========
        results = []

        # 对照组
        logger.info("\n对照组: 5基线因子")
        r0 = run_f1_fold(df_control, baseline, "5基线 (对照组, 5F)", gpu=True)
        results.append(r0)
        gc.collect()

        # 实验组A: +vwap
        logger.info("\n实验组A: 5基线 + vwap_bias_1d")
        r_a = run_f1_fold(
            df_exp_a, baseline + ["vwap_bias_1d"],
            "5基线+vwap (6F)", gpu=True,
        )
        results.append(r_a)
        gc.collect()

        # 实验组B: +rsrs
        logger.info("\n实验组B: 5基线 + rsrs_raw_18")
        r_b = run_f1_fold(
            df_exp_b, baseline + ["rsrs_raw_18"],
            "5基线+rsrs (6F)", gpu=True,
        )
        results.append(r_b)
        gc.collect()

        # 实验组C: +vwap+rsrs
        logger.info("\n实验组C: 5基线 + vwap + rsrs")
        r_c = run_f1_fold(
            df_exp_c, baseline + ["vwap_bias_1d", "rsrs_raw_18"],
            "5基线+vwap+rsrs (7F)", gpu=True,
        )
        results.append(r_c)
        gc.collect()

        # ========== 总对比表 ==========
        print("\n\n")
        print("=" * 110)
        print("VWAP+RSRS 总对比表")
        print("=" * 110)
        hdr = (
            f"{'配置':<30} | {'Train IC':>9} | {'Valid IC':>9} | "
            f"{'OOS IC':>9} | {'OOS ICIR':>9} | {'Best Iter':>9} | "
            f"{'Overfit':>8} | {'判定':>6}"
        )
        print(hdr)
        print("-" * 110)

        # 历史基线参考
        print(
            f"{'5基线(Sprint1.4b参考)':.<30} | {'0.1308':>9} | {'0.1208':>9} | "
            f"{'0.0823':>9} | {'---':>9} | {'52':>9} | {'1.08':>8} | {'REF':>6}"
        )

        for r in results:
            p_iter = r["best_iter"] > 10
            p_ic = r["oos_ic"] >= 0.0823
            p_of = r["overfit_ratio"] < 1.30
            verdict = "PASS" if (p_iter and p_ic and p_of) else "FAIL"
            print(
                f"{r['scheme']:<30} | {r['train_ic']:>9.4f} | {r['valid_ic']:>9.4f} | "
                f"{r['oos_ic']:>9.4f} | {r['oos_icir']:>9.3f} | "
                f"{r['best_iter']:>9d} | {r['overfit_ratio']:>8.2f} | {verdict:>6}"
            )

        # IC增量
        print(f"\nOOS IC增量 vs 对照组:")
        baseline_ic = r0["oos_ic"]
        for r in results[1:]:
            delta = r["oos_ic"] - baseline_ic
            print(f"  {r['scheme']}: {delta:+.4f}")

        # 最终判定
        print(f"\n{'最终判定':=^60}")
        best_result = max(results[1:], key=lambda x: x["oos_ic"])
        print(f"  最佳实验组: {best_result['scheme']}")
        print(f"  OOS IC: {best_result['oos_ic']:.4f} (基线: {baseline_ic:.4f}, "
              f"delta: {best_result['oos_ic'] - baseline_ic:+.4f})")
        print(f"  Best Iter: {best_result['best_iter']}")
        print(f"  Overfit: {best_result['overfit_ratio']:.2f}")

        best_pass = (
            best_result["best_iter"] > 10
            and best_result["oos_ic"] >= 0.0823
            and best_result["overfit_ratio"] < 1.30
        )
        if best_pass:
            print(f"\n  >>> PASS: {best_result['scheme']}有显著增量价值")
            print(f"  >>> 建议: 进入全7-fold walk-forward验证")
        elif best_result["best_iter"] > 10:
            print(f"\n  >>> PARTIAL: 模型能学习新因子, 但指标不全达标")
        else:
            print(f"\n  >>> FAIL: 新因子无增量价值")
            print(f"  >>> 建议: 放弃VWAP/RSRS方向或调整因子定义")

        print("=" * 110)

        total = time.time() - t_start
        logger.info(f"\n总耗时: {total:.1f}s ({total/60:.1f}min)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
