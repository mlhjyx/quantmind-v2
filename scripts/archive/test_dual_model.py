"""方案9: 双模型融合 — 价量模型(M1) + 基本面模型(M2)。

研究报告#003方案C: 两个独立模型分别训练后融合预测。
- M1: 5基线价量特征LightGBM，月度调仓（已有fold_1 OOS预测）
- M2: 6基本面delta特征LightGBM，F1 fold单独训练
- 融合: final_score = 0.7 * M1_pred + 0.3 * M2_pred
- 评估: OOS期间(2023-01~2023-06) IC对比

F1 Fold:
  Train: 2020-07-01 ~ 2022-06-30
  Valid: 2022-07-01 ~ 2022-12-31
  Test(OOS): 2023-01-01 ~ 2023-06-30
  Purge gap: 5 trading days (target overlap ~20 days)
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(project_root / "models" / "test_dual_model.log", mode="w"),
    ],
)
logger = logging.getLogger(__name__)

# 6个基本面delta特征（不含2个时间特征——研究报告指出时间特征噪声大）
FUNDAMENTAL_DELTA_FEATURES = [
    "roe_delta",
    "revenue_growth_yoy",
    "gross_margin_delta",
    "eps_acceleration",
    "debt_change",
    "net_margin_delta",
]

BASELINE_FEATURES = [
    "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio",
]

# F1 Fold时间窗口
TRAIN_START = date(2020, 7, 1)
TRAIN_END = date(2022, 6, 30)
VALID_START = date(2022, 7, 1)
VALID_END = date(2022, 12, 31)
TEST_START = date(2023, 1, 1)
TEST_END = date(2023, 6, 30)


# ============================================================
# 工具函数
# ============================================================

def compute_daily_ic(
    df: pd.DataFrame,
    pred_col: str = "predicted",
    actual_col: str = "actual",
    method: str = "spearman",
) -> pd.Series:
    """按交易日计算截面IC。

    Args:
        df: 含trade_date, pred_col, actual_col列
        pred_col: 预测列名
        actual_col: 实际收益列名
        method: spearman或pearson

    Returns:
        pd.Series(index=trade_date, value=IC)
    """
    daily_ics = {}
    for td, group in df.groupby("trade_date"):
        if len(group) < 30:
            continue
        if method == "spearman":
            ic = group[pred_col].rank().corr(group[actual_col].rank())
        else:
            ic = group[pred_col].corr(group[actual_col])
        if not np.isnan(ic):
            daily_ics[td] = ic
    return pd.Series(daily_ics)


def compute_icir(daily_ics: pd.Series) -> float:
    """ICIR = mean(IC) / std(IC)。"""
    if len(daily_ics) < 2:
        return 0.0
    std = daily_ics.std()
    if std < 1e-8:
        return 0.0
    return float(daily_ics.mean() / std)


# ============================================================
# Step 1: 加载M1预测 (已有5基线价量模型 fold_1 OOS)
# ============================================================

def load_m1_predictions() -> pd.DataFrame:
    """从models/oos_predictions.csv加载M1的fold_1 OOS预测。

    Returns:
        DataFrame [trade_date, code, m1_pred, actual]
    """
    logger.info("=" * 70)
    logger.info("Step 1: 加载M1预测 (5基线价量 fold_1 OOS)")
    logger.info("=" * 70)

    path = project_root / "models" / "oos_predictions.csv"
    df = pd.read_csv(path)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    # 只取fold_1, OOS期间 2023-01 ~ 2023-06
    f1 = df[df["fold_id"] == 1].copy()
    f1 = f1[(f1["trade_date"] >= TEST_START) & (f1["trade_date"] <= TEST_END)]

    f1 = f1.rename(columns={"predicted": "m1_pred", "actual": "actual"})
    f1 = f1[["trade_date", "code", "m1_pred", "actual"]].copy()

    logger.info(f"M1 OOS: {len(f1)}行, {f1['code'].nunique()}股, "
                f"{f1['trade_date'].nunique()}天")
    logger.info(f"M1日期范围: {f1['trade_date'].min()} ~ {f1['trade_date'].max()}")

    # M1 OOS IC
    ic_series = compute_daily_ic(f1, pred_col="m1_pred", actual_col="actual")
    logger.info(f"M1 OOS IC: {ic_series.mean():.4f} (ICIR={compute_icir(ic_series):.3f})")

    return f1


# ============================================================
# Step 2: 训练M2 (6基本面delta特征 LightGBM F1 fold)
# ============================================================

def load_fundamental_features(
    start_date: date,
    end_date: date,
    conn,
) -> pd.DataFrame:
    """加载基本面delta特征 + target。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        conn: psycopg2连接

    Returns:
        DataFrame [trade_date, code, 6个delta特征, excess_return_20]
    """
    from engines.factor_engine import load_fundamental_pit_data

    t0 = time.time()

    # 获取交易日列表（从klines_daily）
    sql_dates = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
    ORDER BY trade_date
    """
    dates_df = pd.read_sql(sql_dates, conn, params=(start_date, end_date))
    trade_dates = [d.date() if hasattr(d, "date") else d
                   for d in dates_df["trade_date"]]
    logger.info(f"交易日: {len(trade_dates)}天 ({start_date} ~ {end_date})")

    # 月度调仓：只取月末交易日（基本面因子季度更新，月度足够）
    month_end_dates = {}
    for td in trade_dates:
        ym = (td.year, td.month)
        month_end_dates[ym] = td
    rebalance_dates = sorted(month_end_dates.values())
    logger.info(f"月末调仓日: {len(rebalance_dates)}个")

    # 获取全量股票代码（从factor_values抽取）
    sql_codes = """
    SELECT DISTINCT code FROM factor_values
    WHERE trade_date BETWEEN %s AND %s
      AND factor_name = 'turnover_mean_20'
      AND neutral_value IS NOT NULL
    """
    codes_df = pd.read_sql(sql_codes, conn, params=(start_date, end_date))
    all_codes = set(codes_df["code"].values)
    logger.info(f"股票数: {len(all_codes)}")

    # 逐月末加载基本面因子
    rows = []
    for i, td in enumerate(rebalance_dates):
        if i % 6 == 0:
            logger.info(f"  基本面因子: {i}/{len(rebalance_dates)} ({td})")
        fund_data = load_fundamental_pit_data(td, conn)

        # 对每只有数据的股票收集因子值
        codes_with_data = set()
        for fname in FUNDAMENTAL_DELTA_FEATURES:
            series = fund_data.get(fname, pd.Series(dtype=float))
            codes_with_data.update(series.index)

        for code in codes_with_data.intersection(all_codes):
            row = {"trade_date": td, "code": code}
            for fname in FUNDAMENTAL_DELTA_FEATURES:
                series = fund_data.get(fname, pd.Series(dtype=float))
                row[fname] = series.get(code, np.nan)
            rows.append(row)

    df_fund = pd.DataFrame(rows)
    t_fund = time.time() - t0
    logger.info(f"基本面特征: {len(df_fund)}行, {t_fund:.1f}s")

    if df_fund.empty:
        logger.error("基本面特征为空")
        return pd.DataFrame()

    # 加载目标变量: T+20日超额收益
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
    logger.info(f"目标变量: {len(df_target)}行")

    # 合并
    df_merged = df_fund.merge(
        df_target[["code", "trade_date", "excess_return_20"]],
        on=["code", "trade_date"],
        how="inner",
    )
    df_merged = df_merged.dropna(subset=["excess_return_20"])

    logger.info(f"合并后: {len(df_merged)}行, {df_merged['code'].nunique()}股, "
                f"{df_merged['trade_date'].nunique()}天")

    # 缺失率
    for fname in FUNDAMENTAL_DELTA_FEATURES:
        miss = df_merged[fname].isna().mean()
        logger.info(f"  {fname:<28}: {miss:.1%} missing")

    return df_merged


def train_m2(conn) -> tuple[object, pd.DataFrame, dict]:
    """训练M2: 6基本面delta特征 LightGBM F1 fold。

    Returns:
        (model, test_df_with_predictions, result_dict)
    """
    import lightgbm as lgb

    from backend.engines.ml_engine import FeaturePreprocessor

    logger.info("=" * 70)
    logger.info("Step 2: 训练M2 (6基本面delta特征 LightGBM F1)")
    logger.info("=" * 70)

    t0 = time.time()

    # 加载数据
    df = load_fundamental_features(TRAIN_START, TEST_END, conn)
    if df.empty:
        raise ValueError("基本面特征矩阵为空")

    # 切分F1 fold
    td_col = df["trade_date"]
    train_df = df[(td_col >= TRAIN_START) & (td_col <= TRAIN_END)].copy()
    valid_df = df[(td_col >= VALID_START) & (td_col <= VALID_END)].copy()
    test_df = df[(td_col >= TEST_START) & (td_col <= TEST_END)].copy()

    # Purge: 训练集末尾丢弃最后20个交易日的target（防泄露）
    all_train_dates = sorted(train_df["trade_date"].unique())
    if len(all_train_dates) > 20:
        train_cutoff = all_train_dates[-21]
        train_df = train_df[train_df["trade_date"] <= train_cutoff].copy()
        logger.info(f"训练集Purge: cutoff={train_cutoff}")

    logger.info(f"Train: {len(train_df)}行 ({train_df['trade_date'].nunique()}天)")
    logger.info(f"Valid: {len(valid_df)}行 ({valid_df['trade_date'].nunique()}天)")
    logger.info(f"Test:  {len(test_df)}行 ({test_df['trade_date'].nunique()}天)")

    feature_cols = [c for c in FUNDAMENTAL_DELTA_FEATURES if c in df.columns]
    logger.info(f"特征: {feature_cols}")

    # 预处理: MAD + fill + zscore (fit on train)
    preprocessor = FeaturePreprocessor()
    preprocessor.fit(train_df, feature_cols)

    train_proc = preprocessor.transform(train_df)
    valid_proc = preprocessor.transform(valid_df)
    test_proc = preprocessor.transform(test_df)

    X_train = train_proc[feature_cols].values.astype(np.float32)
    y_train = train_proc["excess_return_20"].values.astype(np.float32)
    X_valid = valid_proc[feature_cols].values.astype(np.float32)
    y_valid = valid_proc["excess_return_20"].values.astype(np.float32)
    X_test = test_proc[feature_cols].values.astype(np.float32)

    logger.info(f"X_train: {X_train.shape}, X_valid: {X_valid.shape}, X_test: {X_test.shape}")

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    # LightGBM参数 (与Sprint 1.4b一致，适配6特征)
    lgb_params = {
        "objective": "regression",
        "metric": "mse",
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_leaves": 31,       # 更小：6特征不需要63叶
        "max_depth": 5,
        "min_child_samples": 100,  # 更保守：基本面因子样本少
        "reg_alpha": 2.0,
        "reg_lambda": 10.0,     # 更强正则化
        "subsample": 0.8,
        "colsample_bytree": 1.0,  # 只有6特征，全用
        "subsample_freq": 1,
        "n_jobs": -1,
        "seed": 42,
        "verbose": -1,
    }

    # 尝试GPU，失败则CPU
    try:
        lgb_params_gpu = {
            **lgb_params,
            "device_type": "gpu",
            "gpu_platform_id": 0,
            "gpu_device_id": 0,
            "gpu_use_dp": False,
            "max_bin": 63,
        }
        callbacks = [
            lgb.early_stopping(stopping_rounds=50, verbose=True),
            lgb.log_evaluation(period=50),
        ]
        model = lgb.train(
            lgb_params_gpu, train_data,
            num_boost_round=500,
            valid_sets=[valid_data],
            valid_names=["valid"],
            callbacks=callbacks,
        )
    except Exception as e:
        logger.warning(f"GPU训练失败({e})，回退CPU")
        lgb_params["max_bin"] = 255
        callbacks = [
            lgb.early_stopping(stopping_rounds=50, verbose=True),
            lgb.log_evaluation(period=50),
        ]
        model = lgb.train(
            lgb_params, train_data,
            num_boost_round=500,
            valid_sets=[valid_data],
            valid_names=["valid"],
            callbacks=callbacks,
        )

    best_iter = model.best_iteration
    logger.info(f"M2 best_iteration: {best_iter}")

    # 预测
    test_pred = model.predict(X_test, num_iteration=best_iter)
    test_proc_out = test_proc[["trade_date", "code", "excess_return_20"]].copy()
    test_proc_out["m2_pred"] = test_pred

    # M2 OOS IC
    ic_series = compute_daily_ic(
        test_proc_out, pred_col="m2_pred", actual_col="excess_return_20",
    )
    m2_ic = float(ic_series.mean()) if len(ic_series) > 0 else 0.0
    m2_icir = compute_icir(ic_series)

    # 特征重要性
    importance = model.feature_importance(importance_type="gain")
    feat_imp = dict(zip(feature_cols, [float(v) for v in importance], strict=False))

    # 训练集/验证集IC
    train_pred = model.predict(X_train, num_iteration=best_iter)
    valid_pred = model.predict(X_valid, num_iteration=best_iter)

    train_proc_tmp = train_proc[["trade_date", "excess_return_20"]].copy()
    train_proc_tmp["predicted"] = train_pred
    valid_proc_tmp = valid_proc[["trade_date", "excess_return_20"]].copy()
    valid_proc_tmp["predicted"] = valid_pred

    train_ic_s = compute_daily_ic(train_proc_tmp, pred_col="predicted", actual_col="excess_return_20")
    valid_ic_s = compute_daily_ic(valid_proc_tmp, pred_col="predicted", actual_col="excess_return_20")

    train_ic = float(train_ic_s.mean()) if len(train_ic_s) > 0 else 0.0
    valid_ic = float(valid_ic_s.mean()) if len(valid_ic_s) > 0 else 0.0

    elapsed = time.time() - t0

    result = {
        "train_ic": train_ic,
        "valid_ic": valid_ic,
        "oos_ic": m2_ic,
        "oos_icir": m2_icir,
        "best_iter": best_iter,
        "feature_importance": feat_imp,
        "elapsed": elapsed,
        "overfit_ratio": train_ic / valid_ic if abs(valid_ic) > 1e-8 else 99.0,
    }

    logger.info(f"M2结果: Train IC={train_ic:.4f}, Valid IC={valid_ic:.4f}, "
                f"OOS IC={m2_ic:.4f}, ICIR={m2_icir:.3f}, "
                f"best_iter={best_iter}, overfit={result['overfit_ratio']:.2f}")

    return model, test_proc_out, result


# ============================================================
# Step 3: 融合 M1 + M2
# ============================================================

def fuse_predictions(
    m1_df: pd.DataFrame,
    m2_df: pd.DataFrame,
    w1: float = 0.7,
    w2: float = 0.3,
) -> pd.DataFrame:
    """融合M1和M2的OOS预测。

    Args:
        m1_df: M1预测 [trade_date, code, m1_pred, actual]
        m2_df: M2预测 [trade_date, code, m2_pred, excess_return_20]
        w1: M1权重
        w2: M2权重

    Returns:
        DataFrame [trade_date, code, m1_pred, m2_pred, fused_pred, actual]
    """
    logger.info("=" * 70)
    logger.info(f"Step 3: 融合 M1({w1}) + M2({w2})")
    logger.info("=" * 70)

    # M2的trade_date是月末日期，M1是每日。需要对齐。
    # 策略: 将M2的月末预测广播到该月的所有交易日。
    # 即: 对每个M2月末预测，匹配到M1中该月的所有交易日。

    # M2 月末日期 -> 年月
    m2_df = m2_df.copy()
    m2_df["year_month"] = m2_df["trade_date"].apply(lambda d: (d.year, d.month))

    # M1 每日 -> 年月
    m1_df = m1_df.copy()
    m1_df["year_month"] = m1_df["trade_date"].apply(lambda d: (d.year, d.month))

    # 在年月+code上做merge，M2的预测广播到M1的每一天
    m2_for_merge = m2_df[["year_month", "code", "m2_pred"]].copy()

    fused = m1_df.merge(m2_for_merge, on=["year_month", "code"], how="inner")

    logger.info(f"M1行数: {len(m1_df)}, M2行数: {len(m2_df)}")
    logger.info(f"融合后(inner join): {len(fused)}行, "
                f"{fused['code'].nunique()}股, {fused['trade_date'].nunique()}天")

    if len(fused) == 0:
        logger.error("融合后无数据！检查M1/M2的code格式是否一致。")
        return pd.DataFrame()

    # 标准化M1和M2预测到截面rank percentile，再融合
    # 这样避免不同模型的预测值量纲不同
    fused_rows = []
    for _td, group in fused.groupby("trade_date"):
        g = group.copy()
        # 截面rank -> [0,1]百分位
        g["m1_rank"] = g["m1_pred"].rank(pct=True)
        g["m2_rank"] = g["m2_pred"].rank(pct=True)
        g["fused_pred"] = w1 * g["m1_rank"] + w2 * g["m2_rank"]
        fused_rows.append(g)

    fused_all = pd.concat(fused_rows, ignore_index=True)

    logger.info(f"融合完成: {len(fused_all)}行")

    return fused_all


# ============================================================
# Step 4: 评估
# ============================================================

def evaluate_fusion(fused_df: pd.DataFrame, m1_df: pd.DataFrame, m2_result: dict) -> dict:
    """评估融合效果，与M1-only对比。

    Returns:
        dict with all comparison metrics
    """
    logger.info("=" * 70)
    logger.info("Step 4: 评估融合效果")
    logger.info("=" * 70)

    # M1-only IC (在融合的公共集上重新计算，保证可比)
    m1_ic_series = compute_daily_ic(fused_df, pred_col="m1_pred", actual_col="actual")
    m1_ic = float(m1_ic_series.mean()) if len(m1_ic_series) > 0 else 0.0
    m1_icir = compute_icir(m1_ic_series)

    # M2-only IC (用m2_pred列)
    m2_ic_series = compute_daily_ic(fused_df, pred_col="m2_pred", actual_col="actual")
    m2_ic = float(m2_ic_series.mean()) if len(m2_ic_series) > 0 else 0.0
    m2_icir = compute_icir(m2_ic_series)

    # Fused IC
    fused_ic_series = compute_daily_ic(fused_df, pred_col="fused_pred", actual_col="actual")
    fused_ic = float(fused_ic_series.mean()) if len(fused_ic_series) > 0 else 0.0
    fused_icir = compute_icir(fused_ic_series)

    # M1 vs M2 预测相关性
    corr_m1_m2 = fused_df["m1_pred"].corr(fused_df["m2_pred"])

    # Top-15选股回测 (简单版: 月末选Top15, 计算平均收益)
    top_n = 15
    monthly_returns = {"m1": [], "m2": [], "fused": []}
    month_labels = []

    for _td, _group in fused_df.groupby("trade_date"):
        # 只取月末日期（每月最后一个交易日）
        pass

    # 按月汇总: 取每月最后一个交易日做选股
    fused_df_sorted = fused_df.sort_values("trade_date")
    fused_df_sorted["year_month"] = fused_df_sorted["trade_date"].apply(
        lambda d: f"{d.year}-{d.month:02d}"
    )

    for ym, month_group in fused_df_sorted.groupby("year_month"):
        # 取该月最后一个交易日
        last_day = month_group["trade_date"].max()
        day_df = month_group[month_group["trade_date"] == last_day].copy()

        if len(day_df) < top_n:
            continue

        month_labels.append(ym)

        for signal_col, key in [("m1_pred", "m1"), ("m2_pred", "m2"), ("fused_pred", "fused")]:
            top = day_df.nlargest(top_n, signal_col)
            avg_ret = top["actual"].mean()
            monthly_returns[key].append(avg_ret)

    result = {
        "m1_ic": m1_ic,
        "m1_icir": m1_icir,
        "m2_ic": m2_ic,
        "m2_icir": m2_icir,
        "fused_ic": fused_ic,
        "fused_icir": fused_icir,
        "corr_m1_m2": corr_m1_m2,
        "overlap_stocks": len(fused_df),
        "overlap_days": fused_df["trade_date"].nunique(),
        "monthly_returns": monthly_returns,
        "month_labels": month_labels,
        "m2_train_result": m2_result,
    }

    # 打印报告
    print("\n")
    print("=" * 80)
    print("方案9: 双模型融合评估报告")
    print("=" * 80)

    print(f"\n{'OOS期间: 2023-01 ~ 2023-06':^80}")
    print(f"{'融合权重: M1=0.7(价量) + M2=0.3(基本面)':^80}")
    print(f"{'Rank百分位融合(避免量纲差异)':^80}")

    print(f"\n{'IC对比':=^60}")
    header = f"{'模型':<20} | {'OOS IC':>10} | {'OOS ICIR':>10}"
    print(header)
    print("-" * len(header))
    print(f"{'M1(5价量)':.<20} | {m1_ic:>10.4f} | {m1_icir:>10.3f}")
    print(f"{'M2(6基本面delta)':.<20} | {m2_ic:>10.4f} | {m2_icir:>10.3f}")
    print(f"{'Fused(0.7+0.3)':.<20} | {fused_ic:>10.4f} | {fused_icir:>10.3f}")

    # IC增量
    ic_delta = fused_ic - m1_ic
    print(f"\n融合 vs M1-only IC增量: {ic_delta:+.4f} ({'改善' if ic_delta > 0 else '退化'})")
    print(f"M1-M2预测相关性: {corr_m1_m2:.4f} ({'正交性好' if abs(corr_m1_m2) < 0.3 else '相关性较高'})")

    # M2训练诊断
    print(f"\n{'M2训练诊断':=^60}")
    print(f"  Train IC:      {m2_result['train_ic']:.4f}")
    print(f"  Valid IC:      {m2_result['valid_ic']:.4f}")
    print(f"  OOS IC:        {m2_result['oos_ic']:.4f}")
    print(f"  Overfit Ratio: {m2_result['overfit_ratio']:.2f}")
    print(f"  Best Iter:     {m2_result['best_iter']}")

    # M2特征重要性
    print(f"\n{'M2特征重要性 (Gain)':=^60}")
    feat_imp = m2_result.get("feature_importance", {})
    max_imp = max(feat_imp.values()) if feat_imp else 1.0
    for feat, imp in sorted(feat_imp.items(), key=lambda x: -x[1]):
        bar = "#" * int(imp / max_imp * 30) if max_imp > 0 else ""
        print(f"  {feat:<28}: {imp:>10.1f}  {bar}")

    # Top-15月度收益
    if month_labels:
        print(f"\n{'Top-15月度平均超额收益':=^60}")
        print(f"{'月份':<12} | {'M1':>10} | {'M2':>10} | {'Fused':>10}")
        print("-" * 48)
        for i, ym in enumerate(month_labels):
            print(f"  {ym:<10} | {monthly_returns['m1'][i]:>10.4f} | "
                  f"{monthly_returns['m2'][i]:>10.4f} | {monthly_returns['fused'][i]:>10.4f}")
        print("-" * 48)
        m1_avg = np.mean(monthly_returns["m1"]) if monthly_returns["m1"] else 0
        m2_avg = np.mean(monthly_returns["m2"]) if monthly_returns["m2"] else 0
        fused_avg = np.mean(monthly_returns["fused"]) if monthly_returns["fused"] else 0
        print(f"  {'均值':<10} | {m1_avg:>10.4f} | {m2_avg:>10.4f} | {fused_avg:>10.4f}")

    # 判定
    print(f"\n{'最终判定':=^60}")
    if fused_ic > m1_ic and fused_icir > m1_icir:
        print("  PASS: 融合模型IC和ICIR均优于M1-only")
        verdict = "PASS"
    elif fused_ic > m1_ic:
        print("  MARGINAL: 融合IC改善但ICIR未改善")
        verdict = "MARGINAL"
    else:
        print("  FAIL: 融合未改善M1-only")
        verdict = "FAIL"

    print("\n  建议: ", end="")
    if abs(corr_m1_m2) < 0.3 and m2_ic > 0.02:
        print("M2有独立alpha，值得继续优化融合权重")
    elif abs(corr_m1_m2) >= 0.3:
        print("M1-M2相关性偏高，基本面特征未提供足够正交信息")
    else:
        print("M2信号太弱，基本面delta特征在ML框架中增量有限")

    print("=" * 80)

    result["verdict"] = verdict
    return result


# ============================================================
# Main
# ============================================================

def main():
    """主函数。"""
    from app.services.price_utils import _get_sync_conn

    t_start = time.time()
    (project_root / "models").mkdir(parents=True, exist_ok=True)

    conn = _get_sync_conn()

    try:
        # Step 1: 加载M1预测
        m1_df = load_m1_predictions()

        # 检查M1的code格式（可能是纯数字 vs 带后缀）
        sample_code = m1_df["code"].iloc[0]
        logger.info(f"M1 code样例: {sample_code} (type={type(sample_code).__name__})")

        # 如果M1的code是整数，转为6位字符串
        if isinstance(sample_code, (int, np.integer)):
            m1_df["code"] = m1_df["code"].apply(lambda x: f"{int(x):06d}")
            logger.info(f"M1 code已转为6位字符串: {m1_df['code'].iloc[0]}")

        # Step 2: 训练M2
        m2_model, m2_test_df, m2_result = train_m2(conn)

        # 检查M2 code格式
        m2_sample = m2_test_df["code"].iloc[0]
        logger.info(f"M2 code样例: {m2_sample}")

        # Step 3: 融合
        fused_df = fuse_predictions(m1_df, m2_test_df, w1=0.7, w2=0.3)

        if fused_df.empty:
            logger.error("融合失败，无重叠数据")
            return

        # Step 4: 评估
        evaluate_fusion(fused_df, m1_df, m2_result)

        total_elapsed = time.time() - t_start
        print(f"\n总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")
        logger.info(f"总耗时: {total_elapsed:.1f}s")

        # 保存结果
        fused_df[["trade_date", "code", "m1_pred", "m2_pred", "fused_pred", "actual"]].to_csv(
            project_root / "models" / "dual_model_fusion.csv", index=False,
        )
        logger.info("融合预测已保存: models/dual_model_fusion.csv")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
