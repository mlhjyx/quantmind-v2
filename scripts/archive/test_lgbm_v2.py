"""测试 5基线 + 8基本面delta 特征的 LightGBM F1 fold。

Sprint 1.5: 验证基本面delta特征在LightGBM中的增量价值。
- 基线: 5特征 (turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio)
  Sprint 1.4b结果: OOS IC=0.0823, best_iter=52
- 测试: 13特征 (5基线 + 8基本面delta)
- 成功标准: best_iter>2 且 OOS IC>0.082

F1 Fold:
  Train: 2020-07-01 ~ 2022-06-30
  Valid: 2022-07-01 ~ 2022-12-31
  Test(OOS): 2023-01-01 ~ 2023-06-30
  Purge gap: 5 trading days
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

# 项目根目录加入path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(project_root / "models" / "test_lgbm_v2.log", mode="w"),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================
# Step 1: 小样本IC快筛 (LL-024)
# ============================================================

def quick_ic_screen(conn) -> dict[str, dict]:
    """对8个基本面因子做快速IC验证。

    从factor_values表或PIT数据计算2024年每月截面Spearman IC。
    如果某因子>8/12个月IC=0，标记为frozen。

    Returns:
        dict[factor_name -> {"monthly_ics": list, "mean_ic": float,
                             "frozen_months": int, "is_frozen": bool}]
    """
    from engines.factor_engine import (
        FUNDAMENTAL_ALL_FEATURES,
        load_fundamental_pit_data,
    )

    logger.info("=" * 70)
    logger.info("Step 1: 小样本IC快筛 (8个基本面因子 x 2024年)")
    logger.info("=" * 70)

    # 获取2024年交易日
    sql_dates = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN '2024-01-01' AND '2024-12-31'
    ORDER BY trade_date
    """
    dates_df = pd.read_sql(sql_dates, conn)
    trade_dates = [d.date() if hasattr(d, "date") else d for d in dates_df["trade_date"]]
    logger.info(f"2024年交易日: {len(trade_dates)}天")

    # 按月取月末交易日
    month_end_dates = {}
    for td in trade_dates:
        month_end_dates[td.month] = td  # 后面的覆盖前面的，最终是月末
    month_ends = sorted(month_end_dates.values())
    logger.info(f"月末交易日: {[str(d) for d in month_ends]}")

    # 加载5日前瞻收益（用于IC计算）
    sql_ret = """
    WITH latest_adj AS (
        SELECT DISTINCT ON (code)
            code, adj_factor AS latest_adj_factor
        FROM klines_daily
        ORDER BY code, trade_date DESC
    )
    SELECT
        k1.code, k1.trade_date,
        k2.close * k2.adj_factor / la.latest_adj_factor
        / NULLIF(k1.close * k1.adj_factor / la.latest_adj_factor, 0) - 1
            AS fwd_return_5
    FROM klines_daily k1
    JOIN latest_adj la ON k1.code = la.code
    JOIN LATERAL (
        SELECT code, close, adj_factor
        FROM klines_daily k2
        WHERE k2.code = k1.code
          AND k2.trade_date > k1.trade_date
        ORDER BY k2.trade_date
        OFFSET 4 LIMIT 1
    ) k2 ON TRUE
    WHERE k1.trade_date BETWEEN '2024-01-01' AND '2024-12-31'
      AND k1.adj_factor IS NOT NULL
      AND k1.volume > 0
    """
    logger.info("加载2024年5日前瞻收益...")
    ret_df = pd.read_sql(sql_ret, conn)
    ret_df["trade_date"] = pd.to_datetime(ret_df["trade_date"]).dt.date
    logger.info(f"前瞻收益: {len(ret_df)}行, {ret_df['code'].nunique()}股")

    # 对每个月末交易日，加载基本面因子并计算IC
    results: dict[str, dict] = {name: {"monthly_ics": [], "frozen_months": 0}
                                for name in FUNDAMENTAL_ALL_FEATURES}

    for td in month_ends:
        logger.info(f"  处理 {td}...")
        fund_data = load_fundamental_pit_data(td, conn)

        # 获取当日收益
        day_ret = ret_df[ret_df["trade_date"] == td].set_index("code")["fwd_return_5"]

        for fname in FUNDAMENTAL_ALL_FEATURES:
            factor_vals = fund_data.get(fname, pd.Series(dtype=float))
            if factor_vals.empty:
                results[fname]["monthly_ics"].append(0.0)
                results[fname]["frozen_months"] += 1
                continue

            # 对齐: 取factor和return都有值的股票
            common = factor_vals.index.intersection(day_ret.index)
            if len(common) < 30:
                results[fname]["monthly_ics"].append(0.0)
                results[fname]["frozen_months"] += 1
                continue

            f_vals = factor_vals.loc[common]
            r_vals = day_ret.loc[common]

            # 检查因子是否frozen（方差接近0）
            if f_vals.std() < 1e-10:
                results[fname]["monthly_ics"].append(0.0)
                results[fname]["frozen_months"] += 1
                continue

            ic = sp_stats.spearmanr(f_vals, r_vals).statistic
            if np.isnan(ic):
                ic = 0.0
            results[fname]["monthly_ics"].append(ic)

    # 汇总
    logger.info("")
    logger.info("=" * 70)
    logger.info("Step 1 结果: 基本面因子 2024年月度IC快筛")
    logger.info("=" * 70)
    header = f"{'Factor':<28} | {'Mean IC':>8} | {'Std IC':>8} | {'Frozen':>6} | {'Status':>8}"
    logger.info(header)
    logger.info("-" * len(header))

    for fname in FUNDAMENTAL_ALL_FEATURES:
        r = results[fname]
        ics = np.array(r["monthly_ics"])
        r["mean_ic"] = float(np.mean(ics))
        r["std_ic"] = float(np.std(ics)) if len(ics) > 1 else 0.0
        r["is_frozen"] = r["frozen_months"] > 8
        status = "FROZEN!" if r["is_frozen"] else "OK"
        logger.info(
            f"  {fname:<26} | {r['mean_ic']:>8.4f} | {r['std_ic']:>8.4f} | "
            f"{r['frozen_months']:>3}/12  | {status:>8}"
        )

    print("\n")
    print("=" * 70)
    print("Step 1 结果: 基本面因子 2024年月度IC快筛")
    print("=" * 70)
    print(header)
    print("-" * len(header))
    for fname in FUNDAMENTAL_ALL_FEATURES:
        r = results[fname]
        status = "FROZEN!" if r["is_frozen"] else "OK"
        print(
            f"  {fname:<26} | {r['mean_ic']:>8.4f} | {r['std_ic']:>8.4f} | "
            f"{r['frozen_months']:>3}/12  | {status:>8}"
        )

    frozen_count = sum(1 for r in results.values() if r["is_frozen"])
    if frozen_count > 0:
        logger.warning(f"发现 {frozen_count} 个frozen因子，考虑剔除")

    return results


# ============================================================
# Step 2: F1 Fold LightGBM (5基线 + 8基本面)
# ============================================================

def load_features_with_fundamental(
    start_date: date,
    end_date: date,
    baseline_features: list[str],
    fundamental_features: list[str],
    conn,
) -> pd.DataFrame:
    """加载5基线因子(from factor_values) + 8基本面因子(PIT) + target。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        baseline_features: 基线因子名列表
        fundamental_features: 基本面因子名列表
        conn: psycopg2连接

    Returns:
        DataFrame [trade_date, code, feature1, ..., feature13, excess_return_20]
    """
    from engines.factor_engine import load_fundamental_pit_data

    t0 = time.time()

    # 1. 加载5基线因子 (neutral_value from factor_values)
    placeholders = ",".join(["%s"] * len(baseline_features))
    sql_factors = f"""
    SELECT code, trade_date, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date BETWEEN %s AND %s
      AND factor_name IN ({placeholders})
      AND neutral_value IS NOT NULL
    ORDER BY trade_date, code
    """
    params = [start_date, end_date] + baseline_features
    df_long = pd.read_sql(sql_factors, conn, params=params)

    if df_long.empty:
        logger.error(f"无基线因子数据: {start_date} ~ {end_date}")
        return pd.DataFrame()

    # Pivot成宽表
    df_wide = df_long.pivot_table(
        index=["trade_date", "code"],
        columns="factor_name",
        values="neutral_value",
        aggfunc="first",
    ).reset_index()
    df_wide.columns.name = None

    # 确保trade_date是date类型
    df_wide["trade_date"] = pd.to_datetime(df_wide["trade_date"]).dt.date

    t_baseline = time.time() - t0
    logger.info(f"基线因子加载: {len(df_long)}行 -> {len(df_wide)}行宽表, {t_baseline:.1f}s")

    # 2. 逐日加载8个基本面因子
    logger.info(f"加载 {len(fundamental_features)} 个基本面因子 (PIT)...")
    all_trade_dates = sorted(df_wide["trade_date"].unique())
    logger.info(f"  交易日范围: {all_trade_dates[0]} ~ {all_trade_dates[-1]}, {len(all_trade_dates)}天")

    fund_rows = []
    for i, td in enumerate(all_trade_dates):
        if i % 50 == 0:
            logger.info(f"  基本面因子: {i}/{len(all_trade_dates)} ({td})")
        fund_data = load_fundamental_pit_data(td, conn)

        # 收集当日所有股票的基本面因子值
        for code in df_wide[df_wide["trade_date"] == td]["code"].values:
            row = {"trade_date": td, "code": code}
            for fname in fundamental_features:
                series = fund_data.get(fname, pd.Series(dtype=float))
                row[fname] = series.get(code, np.nan)
            fund_rows.append(row)

    df_fund = pd.DataFrame(fund_rows)
    t_fund = time.time() - t0 - t_baseline
    logger.info(f"基本面因子加载: {len(df_fund)}行, {t_fund:.1f}s")

    # 3. 合并基线 + 基本面
    df_merged = df_wide.merge(df_fund, on=["trade_date", "code"], how="left")
    logger.info(f"合并后: {len(df_merged)}行, {df_merged.columns.tolist()}")

    # 4. 加载目标变量: T+20日超额收益
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
        params=(start_date, end_date, start_date, end_date),
    )
    df_target["trade_date"] = pd.to_datetime(df_target["trade_date"]).dt.date

    t_target = time.time() - t0 - t_baseline - t_fund
    logger.info(f"目标变量加载: {len(df_target)}行, {t_target:.1f}s")

    # 5. 合并特征和目标
    df_final = df_merged.merge(
        df_target[["code", "trade_date", "excess_return_20"]],
        on=["code", "trade_date"],
        how="inner",
    )
    df_final = df_final.dropna(subset=["excess_return_20"])

    total_time = time.time() - t0
    logger.info(
        f"特征矩阵完成: {len(df_final)}行, "
        f"{df_final['code'].nunique()}股, "
        f"{df_final['trade_date'].nunique()}天, "
        f"总耗时{total_time:.1f}s"
    )

    # 基本面因子缺失率统计
    logger.info("基本面因子缺失率:")
    for fname in fundamental_features:
        if fname in df_final.columns:
            miss_rate = df_final[fname].isna().mean()
            logger.info(f"  {fname:<28}: {miss_rate:.1%} missing")

    return df_final


def run_f1_fold(
    df: pd.DataFrame,
    feature_names: list[str],
    gpu: bool = True,
) -> dict:
    """运行F1 fold LightGBM训练。

    F1: Train=2020-07~2022-06, Valid=2022-07~2022-12, Test=2023-01~2023-06
    Purge: 训练集末尾丢弃20个交易日target标签。

    Args:
        df: 完整特征矩阵 (含trade_date, code, features, excess_return_20)
        feature_names: 特征列名
        gpu: 是否使用GPU

    Returns:
        dict with train_ic, valid_ic, oos_ic, best_iter, overfit_ratio, feature_importance
    """
    import lightgbm as lgb

    logger.info("=" * 70)
    logger.info("Step 2: F1 Fold LightGBM (13特征)")
    logger.info(f"特征: {feature_names}")
    logger.info("=" * 70)

    t0 = time.time()

    # F1 Fold时间窗口
    train_start = date(2020, 7, 1)
    train_end = date(2022, 6, 30)
    valid_start = date(2022, 7, 1)  # 实际会对齐到purge后
    valid_end = date(2022, 12, 31)
    test_start = date(2023, 1, 1)
    test_end = date(2023, 6, 30)

    # 切分数据
    td_col = df["trade_date"]
    train_mask = (td_col >= train_start) & (td_col <= train_end)
    valid_mask = (td_col >= valid_start) & (td_col <= valid_end)
    test_mask = (td_col >= test_start) & (td_col <= test_end)

    train_df = df[train_mask].copy()
    valid_df = df[valid_mask].copy()
    test_df = df[test_mask].copy()

    # P0修复: 训练集丢弃最后20个交易日（防target泄露到验证期）
    all_train_dates = sorted(train_df["trade_date"].unique())
    if len(all_train_dates) > 20:
        train_cutoff = all_train_dates[-21]
        train_df = train_df[train_df["trade_date"] <= train_cutoff].copy()
        logger.info(f"训练集末尾丢弃20天 (cutoff={train_cutoff})")

    logger.info(
        f"数据量: Train={len(train_df)} ({train_df['trade_date'].nunique()}天), "
        f"Valid={len(valid_df)} ({valid_df['trade_date'].nunique()}天), "
        f"Test={len(test_df)} ({test_df['trade_date'].nunique()}天)"
    )

    # 只保留df中实际存在的特征列
    feature_cols = [c for c in feature_names if c in df.columns]
    missing_feats = set(feature_names) - set(feature_cols)
    if missing_feats:
        logger.warning(f"缺失特征: {missing_feats}")

    logger.info(f"实际使用特征: {len(feature_cols)} 个")

    # 特征预处理: MAD + fill + zscore (在训练集fit, transform all)
    from backend.engines.ml_engine import FeaturePreprocessor, compute_icir

    preprocessor = FeaturePreprocessor()
    preprocessor.fit(train_df, feature_cols)

    train_processed = preprocessor.transform(train_df)
    valid_processed = preprocessor.transform(valid_df)
    test_processed = preprocessor.transform(test_df)

    # 准备LightGBM数据
    X_train = train_processed[feature_cols].values.astype(np.float32)
    y_train = train_processed["excess_return_20"].values.astype(np.float32)
    X_valid = valid_processed[feature_cols].values.astype(np.float32)
    y_valid = valid_processed["excess_return_20"].values.astype(np.float32)
    X_test = test_processed[feature_cols].values.astype(np.float32)
    test_processed["excess_return_20"].values.astype(np.float32)

    logger.info(f"X_train shape: {X_train.shape}")
    logger.info(f"X_valid shape: {X_valid.shape}")
    logger.info(f"X_test shape:  {X_test.shape}")

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    # LightGBM参数 (与Sprint 1.4b一致)
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

    logger.info("开始LightGBM训练...")
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

    # 计算IC指标
    def compute_daily_ic(df_part, preds, method="pearson"):
        """按交易日计算截面IC。"""
        temp = df_part[["trade_date", "excess_return_20"]].copy()
        temp["predicted"] = preds
        daily_ics = {}
        for td, group in temp.groupby("trade_date"):
            if len(group) < 30:
                continue
            pred = group["predicted"]
            actual = group["excess_return_20"]
            ic = pred.rank().corr(actual.rank()) if method == "spearman" else pred.corr(actual)
            if not np.isnan(ic):
                daily_ics[td] = ic
        return pd.Series(daily_ics)

    train_pred = model.predict(X_train, num_iteration=best_iter)
    valid_pred = model.predict(X_valid, num_iteration=best_iter)
    test_pred = model.predict(X_test, num_iteration=best_iter)

    train_ic_series = compute_daily_ic(train_processed, train_pred)
    valid_ic_series = compute_daily_ic(valid_processed, valid_pred)
    test_ic_series = compute_daily_ic(test_processed, test_pred)

    train_ic = float(train_ic_series.mean()) if len(train_ic_series) > 0 else 0.0
    valid_ic = float(valid_ic_series.mean()) if len(valid_ic_series) > 0 else 0.0
    oos_ic = float(test_ic_series.mean()) if len(test_ic_series) > 0 else 0.0
    oos_icir = compute_icir(test_ic_series)

    # RankIC
    test_rank_ic_series = compute_daily_ic(test_processed, test_pred, method="spearman")
    oos_rank_ic = float(test_rank_ic_series.mean()) if len(test_rank_ic_series) > 0 else 0.0

    # 过拟合比率
    overfit_ratio = train_ic / valid_ic if valid_ic > 1e-8 else 99.0

    # 特征重要性
    importance = model.feature_importance(importance_type="gain")
    feat_imp = dict(zip(feature_cols, [float(v) for v in importance], strict=False))

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
        "train_samples": len(train_df),
        "valid_samples": len(valid_df),
        "test_samples": len(test_df),
    }

    # 打印结果
    print("\n")
    print("=" * 80)
    print("Step 2 结果: F1 Fold LightGBM (13特征 = 5基线 + 8基本面delta)")
    print("=" * 80)
    print(f"  Train IC:      {train_ic:.4f}")
    print(f"  Valid IC:      {valid_ic:.4f}")
    print(f"  OOS IC:        {oos_ic:.4f}")
    print(f"  OOS RankIC:    {oos_rank_ic:.4f}")
    print(f"  OOS ICIR:      {oos_icir:.3f}")
    print(f"  Overfit Ratio: {overfit_ratio:.2f}")
    print(f"  Best Iter:     {best_iter}")
    print(f"  耗时:          {elapsed:.1f}s")
    print(f"  样本数:        Train={len(train_df)}, Valid={len(valid_df)}, Test={len(test_df)}")

    # 特征重要性排序
    print(f"\n{'特征重要性 (Gain)':=^50}")
    for feat, imp in sorted(feat_imp.items(), key=lambda x: -x[1]):
        bar = "#" * int(imp / max(feat_imp.values()) * 30) if max(feat_imp.values()) > 0 else ""
        print(f"  {feat:<28}: {imp:>10.1f}  {bar}")

    # 与基线对比
    print(f"\n{'对比表':=^60}")
    print(f"{'配置':<20} | {'Train IC':>9} | {'Valid IC':>9} | {'OOS IC':>9} | {'Best Iter':>9} | {'Overfit':>8}")
    print("-" * 80)
    print(f"{'5基线(Sprint1.4b)':<20} | {'0.1308':>9} | {'0.1208':>9} | {'0.0823':>9} | {'52':>9} | {'1.08':>8}")
    print(f"{'13特征(5+8delta)':<20} | {train_ic:>9.4f} | {valid_ic:>9.4f} | {oos_ic:>9.4f} | {best_iter:>9d} | {overfit_ratio:>8.2f}")

    # 判定
    print(f"\n{'判定':=^50}")
    pass_iter = best_iter > 2
    pass_ic = oos_ic > 0.082
    print(f"  [{'PASS' if pass_iter else 'FAIL'}] best_iter > 2: {best_iter}")
    print(f"  [{'PASS' if pass_ic else 'FAIL'}] OOS IC > 0.082: {oos_ic:.4f}")
    if pass_iter and pass_ic:
        print("\n  >>> PASS: 基本面delta特征有增量价值，可进入全量7-fold验证")
    else:
        print("\n  >>> FAIL: 基本面delta特征增量不足")

    print("=" * 80)

    return result


def main():
    """主函数。"""
    from app.services.price_utils import _get_sync_conn

    t_start = time.time()

    # 确保模型目录存在
    (project_root / "models").mkdir(parents=True, exist_ok=True)

    conn = _get_sync_conn()

    try:
        # ---- Step 1: IC快筛 ----
        ic_results = quick_ic_screen(conn)

        frozen_factors = [name for name, r in ic_results.items() if r["is_frozen"]]
        if frozen_factors:
            logger.warning(f"Frozen因子(将从LightGBM中剔除): {frozen_factors}")

        # ---- Step 2: F1 Fold LightGBM ----
        from engines.factor_engine import (
            FUNDAMENTAL_ALL_FEATURES,
            LGBM_V2_BASELINE_FACTORS,
        )

        baseline_features = LGBM_V2_BASELINE_FACTORS
        # 剔除frozen因子
        fundamental_features = [f for f in FUNDAMENTAL_ALL_FEATURES
                                if f not in frozen_factors]
        all_features = baseline_features + fundamental_features

        logger.info(f"\n基线特征 ({len(baseline_features)}): {baseline_features}")
        logger.info(f"基本面特征 ({len(fundamental_features)}): {fundamental_features}")
        logger.info(f"总特征数: {len(all_features)}")

        # 加载数据 (需要覆盖从train_start到test_end)
        logger.info("\n加载特征矩阵 (2020-07 ~ 2023-06)...")
        df = load_features_with_fundamental(
            start_date=date(2020, 7, 1),
            end_date=date(2023, 6, 30),
            baseline_features=baseline_features,
            fundamental_features=fundamental_features,
            conn=conn,
        )

        if df.empty:
            logger.error("特征矩阵为空，退出")
            return

        # 运行F1 fold
        run_f1_fold(df, all_features, gpu=True)

        total_elapsed = time.time() - t_start
        logger.info(f"\n总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
