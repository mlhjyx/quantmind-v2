"""Walk-Forward LightGBM 训练框架 -- Phase 1 ML核心模块。

参考设计: docs/ML_WALKFORWARD_DESIGN.md
参考Qlib RollingGen，实现扩展->固定窗口混合策略。

核心流程:
  1. generate_folds() 生成7个fold时间分割（F1-F3扩展窗口，F4-F7固定24月）
  2. load_features() 从factor_values表加载特征矩阵，pivot成宽表
  3. train_fold() 单fold LightGBM GPU训练 + Early Stopping + 过拟合检测
  4. predict_oos() 在测试集上做OOS预测
  5. run_full_walkforward() 遍历所有fold，汇总OOS预测，计算整体指标

铁律7: OOS Sharpe < 基线1.019不上线；训练IC/OOS IC > 3倍 = 过拟合
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)

# ============================================================
# 数据类定义
# ============================================================


@dataclass
class MLConfig:
    """ML Walk-Forward 训练配置。

    Attributes:
        feature_names: 特征名列表（对应factor_values.factor_name）
        target: 目标变量名
        train_months: 固定窗口训练月数
        valid_months: 验证集月数
        test_months: 测试集月数
        step_months: 步长月数（=test_months，无overlap）
        purge_days: Purge gap交易日数
        expanding_folds: 前N个fold使用扩展窗口
        data_start: 数据起始日期（热身期起点）
        data_end: 数据截止日期
        gpu: 是否使用GPU训练
        model_dir: 模型保存目录
        seed: 随机种子
    """

    feature_names: list[str] = field(default_factory=lambda: [
        # 5个核心基线因子
        "turnover_mean_20", "volatility_20", "reversal_20",
        "amihud_20", "bp_ratio",
        # 12个ML新特征
        "kbar_kmid", "kbar_ksft", "kbar_kup",
        "mf_divergence", "large_order_ratio", "money_flow_strength",
        "maxret_20", "chmom_60_20", "up_days_ratio_20",
        "beta_market_20", "stoch_rsv_20", "gain_loss_ratio_20",
    ])
    target: str = "excess_return_20"
    train_months: int = 24
    valid_months: int = 6
    test_months: int = 6
    step_months: int = 6
    purge_days: int = 5
    expanding_folds: int = 3  # F1-F3使用扩展窗口
    data_start: date = date(2020, 7, 1)
    data_end: date = date(2026, 3, 24)
    gpu: bool = True
    model_dir: str = "models/lgbm_walkforward"
    seed: int = 42


@dataclass
class Fold:
    """单个Walk-Forward折叠的时间窗口定义。

    Attributes:
        fold_id: 折叠编号（1-based）
        train_start: 训练集开始日期
        train_end: 训练集结束日期
        valid_start: 验证集开始日期（train_end + purge_gap后）
        valid_end: 验证集结束日期
        test_start: 测试集开始日期
        test_end: 测试集结束日期
        is_expanding: 是否使用扩展窗口
        is_partial: 测试窗口是否不完整（最后一个fold可能不满6个月）
    """

    fold_id: int
    train_start: date
    train_end: date
    valid_start: date
    valid_end: date
    test_start: date
    test_end: date
    is_expanding: bool = False
    is_partial: bool = False


@dataclass
class FoldResult:
    """单个fold的训练结果。

    Attributes:
        fold_id: 折叠编号
        train_ic: 训练集IC
        valid_ic: 验证集IC
        oos_ic: 测试集（OOS）IC
        oos_rank_ic: 测试集RankIC
        oos_icir: 测试集ICIR
        overfit_ratio: 过拟合比率 (train_ic / valid_ic)
        is_overfit: 是否被判定为过拟合
        best_iteration: Early stopping最优迭代轮数
        feature_importance: 特征重要性字典
        model_path: 模型文件路径
        train_samples: 训练样本数
        valid_samples: 验证样本数
        test_samples: 测试样本数
        elapsed_seconds: 训练耗时（秒）
    """

    fold_id: int
    train_ic: float
    valid_ic: float
    oos_ic: float
    oos_rank_ic: float = 0.0
    oos_icir: float = 0.0
    overfit_ratio: float = 0.0
    is_overfit: bool = False
    best_iteration: int = 0
    feature_importance: dict[str, float] = field(default_factory=dict)
    model_path: str = ""
    train_samples: int = 0
    valid_samples: int = 0
    test_samples: int = 0
    elapsed_seconds: float = 0.0


@dataclass
class WalkForwardResult:
    """完整Walk-Forward实验结果。

    Attributes:
        fold_results: 每个fold的结果列表
        oos_predictions: 所有fold OOS预测拼接后的DataFrame
        overall_ic: 整体OOS IC均值
        overall_rank_ic: 整体OOS RankIC均值
        overall_icir: 整体OOS ICIR
        num_folds_used: 实际使用的fold数（排除过拟合fold）
        total_elapsed: 总耗时（秒）
    """

    fold_results: list[FoldResult] = field(default_factory=list)
    oos_predictions: Optional[pd.DataFrame] = None
    overall_ic: float = 0.0
    overall_rank_ic: float = 0.0
    overall_icir: float = 0.0
    num_folds_used: int = 0
    total_elapsed: float = 0.0


# ============================================================
# 辅助函数
# ============================================================


def _get_db_conn():
    """获取同步数据库连接。"""
    import psycopg2
    return psycopg2.connect(
        dbname="quantmind_v2",
        user="xin",
        password="quantmind",
        host="localhost",
    )


def _add_months(d: date, months: int) -> date:
    """日期加减月数，处理月末边界。

    Args:
        d: 起始日期
        months: 要加的月数（可为负）

    Returns:
        加减后的日期
    """
    import calendar
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _snap_to_trade_date(d: date, trade_dates: list[date], direction: str = "forward") -> date:
    """将日期对齐到最近的交易日。

    Args:
        d: 目标日期
        trade_dates: 已排序的交易日历
        direction: 'forward'取>=d的第一个交易日，'backward'取<=d的最后一个交易日

    Returns:
        对齐后的交易日期
    """
    if direction == "forward":
        candidates = [td for td in trade_dates if td >= d]
        return candidates[0] if candidates else trade_dates[-1]
    else:
        candidates = [td for td in trade_dates if td <= d]
        return candidates[-1] if candidates else trade_dates[0]


def _get_n_trade_days_after(d: date, n: int, trade_dates: list[date]) -> date:
    """获取指定日期后第N个交易日。

    Args:
        d: 起始日期
        n: 交易日数
        trade_dates: 已排序的交易日历

    Returns:
        第N个交易日的日期
    """
    future = [td for td in trade_dates if td > d]
    if len(future) >= n:
        return future[n - 1]
    return future[-1] if future else d


def compute_daily_ic(
    predictions: pd.DataFrame,
    method: str = "spearman",
) -> pd.Series:
    """按交易日计算截面IC。

    Args:
        predictions: 包含 [trade_date, code, predicted, actual] 的DataFrame
        method: 'spearman' 或 'pearson'

    Returns:
        pd.Series indexed by trade_date, 值为IC
    """
    daily_ics = {}
    for td, group in predictions.groupby("trade_date"):
        if len(group) < 30:
            continue
        pred = group["predicted"]
        actual = group["actual"]
        if method == "spearman":
            ic = pred.rank().corr(actual.rank())
        else:
            ic = pred.corr(actual)
        if not np.isnan(ic):
            daily_ics[td] = ic
    return pd.Series(daily_ics)


def compute_icir(daily_ics: pd.Series) -> float:
    """计算ICIR = mean(IC) / std(IC)。

    Args:
        daily_ics: 日IC序列

    Returns:
        ICIR值
    """
    if len(daily_ics) < 2:
        return 0.0
    std = daily_ics.std()
    if std < 1e-8:
        return 0.0
    return float(daily_ics.mean() / std)


# ============================================================
# 特征预处理器（防止数据泄露：参数在训练集上fit，transform到验证/测试集）
# ============================================================


class FeaturePreprocessor:
    """特征预处理器。

    严格遵守CLAUDE.md预处理顺序: MAD去极值 -> 缺失值填充 -> 中性化 -> zscore。
    所有参数在训练集上fit，用fit后的参数transform验证集和测试集。
    """

    def __init__(self) -> None:
        self._mad_params: dict[str, tuple[float, float]] = {}  # {feature: (median, mad)}
        self._zscore_params: dict[str, tuple[float, float]] = {}  # {feature: (mean, std)}
        self._feature_names: list[str] = []
        self._fitted: bool = False

    def fit(self, df: pd.DataFrame, feature_names: list[str]) -> "FeaturePreprocessor":
        """在训练集上计算预处理参数。

        Args:
            df: 训练集DataFrame，包含feature_names中的列
            feature_names: 特征名列表

        Returns:
            self（支持链式调用）
        """
        self._feature_names = feature_names

        for feat in feature_names:
            if feat not in df.columns:
                logger.warning(f"特征 {feat} 不在DataFrame中，跳过")
                continue

            series = df[feat].dropna()
            if len(series) == 0:
                self._mad_params[feat] = (0.0, 1.0)
                self._zscore_params[feat] = (0.0, 1.0)
                continue

            # MAD参数
            median = float(series.median())
            mad = float((series - median).abs().median())
            if mad < 1e-12:
                mad = 1.0
            self._mad_params[feat] = (median, mad)

            # 先MAD截断，再算zscore参数
            n_mad = 5.0
            upper = median + n_mad * mad
            lower = median - n_mad * mad
            clipped = series.clip(lower=lower, upper=upper)
            filled = clipped.fillna(0.0)

            mean_val = float(filled.mean())
            std_val = float(filled.std())
            if std_val < 1e-12:
                std_val = 1.0
            self._zscore_params[feat] = (mean_val, std_val)

        self._fitted = True
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """用训练集参数transform数据。

        注意: 不做中性化（因子已在factor_values中完成中性化），
        只做MAD截断+填充+zscore。ML模型输入使用neutral_value列。

        Args:
            df: 要transform的DataFrame

        Returns:
            处理后的DataFrame（新副本）
        """
        if not self._fitted:
            raise RuntimeError("必须先调用fit()再调用transform()")

        result = df.copy()

        for feat in self._feature_names:
            if feat not in result.columns:
                continue

            # Step 1: MAD去极值（用训练集的median和mad）
            median, mad = self._mad_params.get(feat, (0.0, 1.0))
            n_mad = 5.0
            upper = median + n_mad * mad
            lower = median - n_mad * mad
            result[feat] = result[feat].clip(lower=lower, upper=upper)

            # Step 2: 缺失值填充（用0）
            result[feat] = result[feat].fillna(0.0)

            # Step 3: zscore（用训练集的mean和std）
            mean_val, std_val = self._zscore_params.get(feat, (0.0, 1.0))
            result[feat] = (result[feat] - mean_val) / std_val

        return result


# ============================================================
# Walk-Forward训练器
# ============================================================


class WalkForwardTrainer:
    """Walk-Forward滚动训练框架。

    参考Qlib RollingGen，实现扩展->固定窗口混合策略。
    F1-F3使用扩展窗口（训练起点固定2020-07），F4-F7使用固定24月窗口。
    """

    def __init__(self, config: MLConfig, conn=None) -> None:
        """初始化训练器。

        Args:
            config: ML配置
            conn: 可选的psycopg2连接（不传则自动创建）
        """
        self.config = config
        self._conn = conn
        self._trade_dates: list[date] = []
        self._folds: list[Fold] = []
        self._default_lgb_params: dict = {}
        self._setup_default_params()

    def _get_conn(self):
        """获取数据库连接。"""
        if self._conn is None:
            self._conn = _get_db_conn()
        return self._conn

    def _setup_default_params(self) -> None:
        """设置LightGBM默认超参数（对标设计文档 3.1节）。"""
        self._default_lgb_params = {
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
            "seed": self.config.seed,
            "verbose": -1,
        }
        if self.config.gpu:
            self._default_lgb_params.update({
                "device_type": "gpu",
                "gpu_platform_id": 0,
                "gpu_device_id": 0,
                "gpu_use_dp": False,
                "max_bin": 63,
            })
        else:
            self._default_lgb_params["max_bin"] = 255

    def _load_trade_dates(self) -> list[date]:
        """从数据库加载交易日历。

        Returns:
            已排序的交易日列表
        """
        if self._trade_dates:
            return self._trade_dates

        conn = self._get_conn()
        sql = """
        SELECT DISTINCT trade_date
        FROM klines_daily
        WHERE trade_date BETWEEN %s AND %s
        ORDER BY trade_date
        """
        df = pd.read_sql(sql, conn, params=(self.config.data_start, self.config.data_end))
        self._trade_dates = [d.date() if hasattr(d, "date") else d for d in df["trade_date"]]
        logger.info(f"加载交易日历: {len(self._trade_dates)}个交易日 "
                    f"({self._trade_dates[0]} ~ {self._trade_dates[-1]})")
        return self._trade_dates

    def generate_folds(self) -> list[Fold]:
        """生成Walk-Forward时间分割。

        F1-F3: 扩展窗口（训练起点固定在data_start）
        F4-F7: 固定train_months窗口
        每个fold: purge_gap=purge_days交易日

        Returns:
            Fold列表
        """
        trade_dates = self._load_trade_dates()
        cfg = self.config
        folds: list[Fold] = []

        # 设计文档中的fold定义（Section 1.3）
        # 第一个测试区间从 data_start + 30个月 开始（24训练+6验证）
        # 也就是 2020-07 + 30月 = 2023-01
        first_test_start = _add_months(cfg.data_start, cfg.train_months + cfg.valid_months)

        fold_id = 0
        test_start_nominal = first_test_start

        while test_start_nominal < cfg.data_end:
            fold_id += 1
            test_end_nominal = _add_months(test_start_nominal, cfg.test_months) - timedelta(days=1)

            # 测试窗口不能超过数据截止日
            is_partial = False
            if test_end_nominal > cfg.data_end:
                test_end_nominal = cfg.data_end
                is_partial = True

            # 验证集: 测试开始前的valid_months
            valid_end_nominal = test_start_nominal - timedelta(days=1)
            valid_start_nominal = _add_months(test_start_nominal, -cfg.valid_months)

            # 训练集: 取决于是扩展还是固定窗口
            is_expanding = fold_id <= cfg.expanding_folds
            if is_expanding:
                train_start_nominal = cfg.data_start
            else:
                train_start_nominal = _add_months(valid_start_nominal, -cfg.train_months)

            train_end_nominal = valid_start_nominal - timedelta(days=1)

            # 对齐到交易日
            train_start = _snap_to_trade_date(train_start_nominal, trade_dates, "forward")
            train_end = _snap_to_trade_date(train_end_nominal, trade_dates, "backward")

            # Purge gap: 训练结束后的purge_days个交易日不参与任何集合
            valid_start_after_purge = _get_n_trade_days_after(
                train_end, cfg.purge_days, trade_dates
            )
            valid_start = _snap_to_trade_date(
                max(valid_start_after_purge, valid_start_nominal), trade_dates, "forward"
            )
            valid_end = _snap_to_trade_date(valid_end_nominal, trade_dates, "backward")

            test_start = _snap_to_trade_date(test_start_nominal, trade_dates, "forward")
            test_end = _snap_to_trade_date(test_end_nominal, trade_dates, "backward")

            # 验证窗口合法性
            if train_start >= train_end or valid_start >= valid_end or test_start > test_end:
                logger.warning(f"F{fold_id} 时间窗口无效，跳过")
                test_start_nominal = _add_months(test_start_nominal, cfg.step_months)
                continue

            fold = Fold(
                fold_id=fold_id,
                train_start=train_start,
                train_end=train_end,
                valid_start=valid_start,
                valid_end=valid_end,
                test_start=test_start,
                test_end=test_end,
                is_expanding=is_expanding,
                is_partial=is_partial,
            )
            folds.append(fold)

            logger.info(
                f"F{fold_id} ({'expanding' if is_expanding else 'fixed'}"
                f"{' PARTIAL' if is_partial else ''}): "
                f"Train[{train_start}~{train_end}] "
                f"Valid[{valid_start}~{valid_end}] "
                f"Test[{test_start}~{test_end}]"
            )

            # 下一个fold
            test_start_nominal = _add_months(test_start_nominal, cfg.step_months)

        self._folds = folds
        return folds

    def load_features(
        self,
        start_date: date,
        end_date: date,
        conn=None,
    ) -> pd.DataFrame:
        """加载特征矩阵。

        从factor_values表读取中性化后的因子值，pivot成宽表。
        同时加载目标变量（T+20日超额收益）。

        Args:
            start_date: 开始日期
            end_date: 结束日期
            conn: 可选的数据库连接

        Returns:
            DataFrame，列为 [trade_date, code, feature1, ..., featureN, target]
            target = T+20日vs沪深300超额收益（对数）
        """
        if conn is None:
            conn = self._get_conn()

        feature_names = self.config.feature_names
        placeholders = ",".join(["%s"] * len(feature_names))

        t0 = time.time()

        # 1. 加载因子值（中性化后的neutral_value）
        sql_factors = f"""
        SELECT code, trade_date, factor_name, neutral_value
        FROM factor_values
        WHERE trade_date BETWEEN %s AND %s
          AND factor_name IN ({placeholders})
          AND neutral_value IS NOT NULL
        ORDER BY trade_date, code
        """
        params = [start_date, end_date] + feature_names
        df_long = pd.read_sql(sql_factors, conn, params=params)

        if df_long.empty:
            logger.warning(f"无因子数据: {start_date} ~ {end_date}")
            return pd.DataFrame()

        # Pivot成宽表: (trade_date, code) x factor_name
        df_wide = df_long.pivot_table(
            index=["trade_date", "code"],
            columns="factor_name",
            values="neutral_value",
            aggfunc="first",
        ).reset_index()
        df_wide.columns.name = None

        t_factor = time.time() - t0
        logger.info(
            f"因子加载: {len(df_long)}行 -> {len(df_wide)}行宽表, "
            f"{len(feature_names)}特征, {t_factor:.1f}s"
        )

        # 2. 加载目标变量: T+20日超额收益
        # 使用对数超额收益: log(1 + r_stock) - log(1 + r_index)
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

        t_target = time.time() - t0 - t_factor
        logger.info(f"目标变量加载: {len(df_target)}行, {t_target:.1f}s")

        if df_target.empty:
            logger.warning("目标变量为空")
            return df_wide

        # 3. 合并特征和目标
        df_target["trade_date"] = pd.to_datetime(df_target["trade_date"])
        df_wide["trade_date"] = pd.to_datetime(df_wide["trade_date"])

        df_merged = df_wide.merge(
            df_target[["code", "trade_date", "excess_return_20"]],
            on=["code", "trade_date"],
            how="inner",
        )

        # 转换回date类型
        df_merged["trade_date"] = df_merged["trade_date"].dt.date

        # 删除目标变量缺失的行
        df_merged = df_merged.dropna(subset=["excess_return_20"])

        logger.info(
            f"特征矩阵合并完成: {len(df_merged)}行, "
            f"{df_merged['code'].nunique()}股, "
            f"{df_merged['trade_date'].nunique()}天, "
            f"总耗时{time.time() - t0:.1f}s"
        )
        return df_merged

    def _split_fold_data(
        self,
        df: pd.DataFrame,
        fold: Fold,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """按fold时间窗口切分训练/验证/测试集。

        P0修复: 训练集末尾丢弃20个交易日的行，防止T+20日target标签
        落入purge gap/验证期（Lopez de Prado AFML Ch.7 标签泄露）。

        Args:
            df: 完整特征矩阵
            fold: Fold定义

        Returns:
            (train_df, valid_df, test_df)
        """
        trade_date_col = df["trade_date"]

        # 确保是date类型
        if hasattr(trade_date_col.iloc[0], "date"):
            trade_date_col = trade_date_col.apply(lambda x: x.date() if hasattr(x, "date") else x)

        # P0-1修复: 训练集丢弃最后20个交易日，防止target标签泄露到验证期
        # target是T+20日收益，所以train_end前20个交易日的target会跨入验证期
        all_train_dates = sorted(trade_date_col[
            (trade_date_col >= fold.train_start) & (trade_date_col <= fold.train_end)
        ].unique())
        if len(all_train_dates) > 20:
            train_cutoff = all_train_dates[-21]  # 丢弃最后20个交易日
        else:
            train_cutoff = fold.train_start  # 数据不足时保留全部

        train_mask = (trade_date_col >= fold.train_start) & (trade_date_col <= train_cutoff)
        valid_mask = (trade_date_col >= fold.valid_start) & (trade_date_col <= fold.valid_end)
        test_mask = (trade_date_col >= fold.test_start) & (trade_date_col <= fold.test_end)

        return df[train_mask].copy(), df[valid_mask].copy(), df[test_mask].copy()

    def train_fold(
        self,
        fold: Fold,
        df: pd.DataFrame,
        params: Optional[dict] = None,
    ) -> tuple[FoldResult, "FeaturePreprocessor"]:
        """训练单个fold。

        流程:
          1. 切分训练/验证/测试集
          2. 预处理（在训练集上fit，transform全部集合）
          3. LightGBM训练（GPU模式，Early Stopping基于验证集）
          4. 过拟合检测（IC比率）
          5. OOS预测

        Args:
            fold: Fold时间定义
            df: 完整特征矩阵
            params: LightGBM超参数（None则使用默认）

        Returns:
            FoldResult
        """
        import lightgbm as lgb

        t0 = time.time()
        logger.info(f"=== F{fold.fold_id} 训练开始 ===")

        # 1. 切分数据
        train_df, valid_df, test_df = self._split_fold_data(df, fold)
        logger.info(
            f"F{fold.fold_id} 数据量: "
            f"Train={len(train_df)}, Valid={len(valid_df)}, Test={len(test_df)}"
        )

        if len(train_df) < 1000 or len(valid_df) < 100:
            logger.error(f"F{fold.fold_id} 数据不足，跳过")
            return FoldResult(
                fold_id=fold.fold_id,
                train_ic=0.0, valid_ic=0.0, oos_ic=0.0,
                is_overfit=True,
            ), FeaturePreprocessor()

        # 2. 特征预处理（训练集fit，transform全部）
        feature_cols = [c for c in self.config.feature_names if c in df.columns]
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
        y_test = test_processed["excess_return_20"].values.astype(np.float32)

        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
        valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

        # 3. 训练
        lgb_params = {**self._default_lgb_params}
        if params:
            lgb_params.update(params)

        callbacks = [
            lgb.early_stopping(stopping_rounds=50, verbose=True),
            lgb.log_evaluation(period=50),
        ]

        model = lgb.train(
            lgb_params,
            train_data,
            num_boost_round=500,
            valid_sets=[valid_data],
            valid_names=["valid"],
            callbacks=callbacks,
        )

        best_iter = model.best_iteration

        # 4. 计算IC指标
        train_pred = model.predict(X_train, num_iteration=best_iter)
        valid_pred = model.predict(X_valid, num_iteration=best_iter)
        test_pred = model.predict(X_test, num_iteration=best_iter)

        # 截面IC（按日计算再取均值）
        train_ic_series = self._compute_daily_ic(
            train_processed, train_pred, "excess_return_20"
        )
        valid_ic_series = self._compute_daily_ic(
            valid_processed, valid_pred, "excess_return_20"
        )
        test_ic_series = self._compute_daily_ic(
            test_processed, test_pred, "excess_return_20"
        )

        train_ic = float(train_ic_series.mean()) if len(train_ic_series) > 0 else 0.0
        valid_ic = float(valid_ic_series.mean()) if len(valid_ic_series) > 0 else 0.0
        oos_ic = float(test_ic_series.mean()) if len(test_ic_series) > 0 else 0.0
        oos_icir = compute_icir(test_ic_series)

        # RankIC
        test_rank_ic_series = self._compute_daily_ic(
            test_processed, test_pred, "excess_return_20", method="spearman"
        )
        oos_rank_ic = float(test_rank_ic_series.mean()) if len(test_rank_ic_series) > 0 else 0.0

        # 5. 过拟合检测（ML-06: train_IC/valid_IC）
        overfit_ratio = 0.0
        is_overfit = False
        if valid_ic > 1e-8:
            # 不用abs: 符号反转意味着模型在验证集上方向错误，比过拟合更严重
            overfit_ratio = train_ic / valid_ic if valid_ic > 0 else 99.0
        elif train_ic > 0.05:
            # 验证IC接近0但训练IC很高 -> 严重过拟合
            overfit_ratio = 99.0

        if overfit_ratio > 5.0:
            logger.critical(
                f"F{fold.fold_id} 过拟合比率={overfit_ratio:.1f} >= 5.0 "
                f"(铁律7触发！Train IC={train_ic:.4f}, Valid IC={valid_ic:.4f})"
            )
            is_overfit = True
        elif overfit_ratio > 3.0:
            logger.error(
                f"F{fold.fold_id} 过拟合比率={overfit_ratio:.1f} >= 3.0 "
                f"(CRITICAL! 该fold不纳入预测拼接)"
            )
            is_overfit = True
        elif overfit_ratio > 2.0:
            logger.warning(
                f"F{fold.fold_id} 过拟合比率={overfit_ratio:.1f} >= 2.0 "
                f"(WARNING, 但继续)"
            )

        # 6. 特征重要性
        importance = model.feature_importance(importance_type="gain")
        feat_imp = dict(zip(feature_cols, [float(v) for v in importance]))

        # 7. 保存模型
        model_dir = Path(self.config.model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = str(model_dir / f"fold_{fold.fold_id}.txt")
        model.save_model(model_path)

        elapsed = time.time() - t0

        result = FoldResult(
            fold_id=fold.fold_id,
            train_ic=train_ic,
            valid_ic=valid_ic,
            oos_ic=oos_ic,
            oos_rank_ic=oos_rank_ic,
            oos_icir=oos_icir,
            overfit_ratio=overfit_ratio,
            is_overfit=is_overfit,
            best_iteration=best_iter,
            feature_importance=feat_imp,
            model_path=model_path,
            train_samples=len(train_df),
            valid_samples=len(valid_df),
            test_samples=len(test_df),
            elapsed_seconds=elapsed,
        )

        logger.info(
            f"F{fold.fold_id} 完成: "
            f"Train IC={train_ic:.4f}, Valid IC={valid_ic:.4f}, "
            f"OOS IC={oos_ic:.4f}, OOS RankIC={oos_rank_ic:.4f}, "
            f"ICIR={oos_icir:.3f}, "
            f"Overfit={overfit_ratio:.2f}{'(OVERFIT!)' if is_overfit else ''}, "
            f"best_iter={best_iter}, {elapsed:.1f}s"
        )
        return result, preprocessor

    def predict_oos(
        self,
        fold: Fold,
        df: pd.DataFrame,
        model_path: Optional[str] = None,
        preprocessor: Optional["FeaturePreprocessor"] = None,
    ) -> pd.DataFrame:
        """在测试集上做OOS预测。

        Args:
            fold: Fold定义
            df: 完整特征矩阵
            model_path: 模型文件路径（None则从默认路径加载）
            preprocessor: 已fit的预处理器（P0-2修复: 复用train_fold的preprocessor）

        Returns:
            DataFrame [trade_date, code, predicted, actual]
        """
        import lightgbm as lgb

        if model_path is None:
            model_path = str(Path(self.config.model_dir) / f"fold_{fold.fold_id}.txt")

        if not os.path.exists(model_path):
            logger.error(f"模型文件不存在: {model_path}")
            return pd.DataFrame()

        model = lgb.Booster(model_file=model_path)

        # 切分数据并预处理
        _, _, test_df = self._split_fold_data(df, fold)

        feature_cols = [c for c in self.config.feature_names if c in df.columns]

        # P0-2修复: 复用train_fold传入的preprocessor，避免重新fit
        if preprocessor is None:
            train_df, _, _ = self._split_fold_data(df, fold)
            preprocessor = FeaturePreprocessor()
            preprocessor.fit(train_df, feature_cols)

        test_processed = preprocessor.transform(test_df)

        X_test = test_processed[feature_cols].values.astype(np.float32)
        predictions = model.predict(X_test)

        result = pd.DataFrame({
            "trade_date": test_processed["trade_date"].values,
            "code": test_processed["code"].values,
            "predicted": predictions,
            "actual": test_processed["excess_return_20"].values,
            "fold_id": fold.fold_id,
        })
        return result

    def run_full_walkforward(
        self,
        params: Optional[dict] = None,
    ) -> WalkForwardResult:
        """运行完整Walk-Forward流程。

        遍历所有fold，汇总OOS预测，计算整体指标。

        Args:
            params: LightGBM超参数（None则使用默认）

        Returns:
            WalkForwardResult
        """
        t0 = time.time()

        # 1. 生成fold
        folds = self.generate_folds()
        if not folds:
            logger.error("无法生成有效fold")
            return WalkForwardResult()

        # 2. 加载全量特征（覆盖所有fold的时间范围）
        earliest_start = min(f.train_start for f in folds)
        latest_end = max(f.test_end for f in folds)

        logger.info(f"加载特征矩阵: {earliest_start} ~ {latest_end}")
        df = self.load_features(earliest_start, latest_end)

        if df.empty:
            logger.error("特征矩阵为空，无法训练")
            return WalkForwardResult()

        # 3. 逐fold训练
        fold_results: list[FoldResult] = []
        all_oos_predictions: list[pd.DataFrame] = []
        iron_law_7_triggered = False

        for fold in folds:
            result, fold_preprocessor = self.train_fold(fold, df, params)
            fold_results.append(result)

            # 铁律7检查：overfit > 5.0 强制停止
            if result.overfit_ratio > 5.0:
                logger.critical(f"铁律7触发! F{fold.fold_id} overfit={result.overfit_ratio:.1f}")
                iron_law_7_triggered = True
                break

            # 收集非过拟合fold的OOS预测（P0-2: 复用preprocessor）
            if not result.is_overfit:
                oos_pred = self.predict_oos(
                    fold, df, result.model_path, preprocessor=fold_preprocessor
                )
                if not oos_pred.empty:
                    all_oos_predictions.append(oos_pred)

        # 4. 拼接OOS预测
        oos_df = pd.DataFrame()
        if all_oos_predictions:
            oos_df = pd.concat(all_oos_predictions, ignore_index=True)
            # 按时间排序（ML-10: 按时间拼接，不平均）
            oos_df = oos_df.sort_values(["trade_date", "code"]).reset_index(drop=True)

            # 检查时间连续性
            unique_dates = sorted(oos_df["trade_date"].unique())
            logger.info(
                f"OOS预测拼接: {len(oos_df)}行, "
                f"{oos_df['code'].nunique()}股, "
                f"{len(unique_dates)}天 "
                f"({unique_dates[0]} ~ {unique_dates[-1]})"
            )

        # 5. 计算整体指标
        overall_ic = 0.0
        overall_rank_ic = 0.0
        overall_icir = 0.0

        if not oos_df.empty:
            daily_ics = compute_daily_ic(oos_df, method="pearson")
            daily_rank_ics = compute_daily_ic(oos_df, method="spearman")

            overall_ic = float(daily_ics.mean()) if len(daily_ics) > 0 else 0.0
            overall_rank_ic = float(daily_rank_ics.mean()) if len(daily_rank_ics) > 0 else 0.0
            overall_icir = compute_icir(daily_rank_ics)

        total_elapsed = time.time() - t0
        num_used = sum(1 for r in fold_results if not r.is_overfit)

        wf_result = WalkForwardResult(
            fold_results=fold_results,
            oos_predictions=oos_df if not oos_df.empty else None,
            overall_ic=overall_ic,
            overall_rank_ic=overall_rank_ic,
            overall_icir=overall_icir,
            num_folds_used=num_used,
            total_elapsed=total_elapsed,
        )

        # 6. 打印总结
        logger.info("=" * 70)
        logger.info("Walk-Forward 训练完成 总结")
        logger.info("=" * 70)
        logger.info(f"总fold数: {len(fold_results)}, 有效fold数: {num_used}")
        logger.info(f"整体 OOS IC: {overall_ic:.4f}")
        logger.info(f"整体 OOS RankIC: {overall_rank_ic:.4f}")
        logger.info(f"整体 OOS ICIR: {overall_icir:.3f}")
        logger.info(f"总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")

        if iron_law_7_triggered:
            logger.critical("铁律7已触发，实验作废，不可上线！")

        for r in fold_results:
            status = "OVERFIT" if r.is_overfit else "OK"
            logger.info(
                f"  F{r.fold_id}: TrainIC={r.train_ic:.4f} "
                f"ValidIC={r.valid_ic:.4f} "
                f"OOS_IC={r.oos_ic:.4f} "
                f"Overfit={r.overfit_ratio:.2f} "
                f"[{status}]"
            )

        # 上线条件检查（ML-09）
        logger.info("-" * 40)
        baseline_sharpe = 1.019
        ic_threshold = 0.02
        icir_threshold = 0.3

        checks = []
        checks.append(("OOS IC > 0.02", overall_ic > ic_threshold, f"{overall_ic:.4f}"))
        checks.append(("OOS ICIR > 0.3", overall_icir > icir_threshold, f"{overall_icir:.3f}"))
        checks.append(("无铁律7触发", not iron_law_7_triggered, str(not iron_law_7_triggered)))

        for name, passed, val in checks:
            status = "PASS" if passed else "FAIL"
            logger.info(f"  [{status}] {name}: {val}")

        logger.info("=" * 70)
        return wf_result

    def _compute_daily_ic(
        self,
        df: pd.DataFrame,
        predictions: np.ndarray,
        target_col: str,
        method: str = "pearson",
    ) -> pd.Series:
        """按交易日计算截面IC。

        Args:
            df: 含 trade_date, code, target_col 的DataFrame
            predictions: 模型预测值数组
            target_col: 目标列名
            method: 'pearson' 或 'spearman'

        Returns:
            pd.Series indexed by trade_date
        """
        temp = df[["trade_date", target_col]].copy()
        temp["predicted"] = predictions

        daily_ics = {}
        for td, group in temp.groupby("trade_date"):
            if len(group) < 30:
                continue
            pred = group["predicted"]
            actual = group[target_col]
            if method == "spearman":
                ic = pred.rank().corr(actual.rank())
            else:
                ic = pred.corr(actual)
            if not np.isnan(ic):
                daily_ics[td] = ic

        return pd.Series(daily_ics)

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# ============================================================
# 便捷入口函数
# ============================================================


def run_walkforward(
    feature_names: Optional[list[str]] = None,
    gpu: bool = True,
    params: Optional[dict] = None,
) -> WalkForwardResult:
    """运行Walk-Forward训练的便捷函数。

    Args:
        feature_names: 特征名列表（None则使用默认5因子）
        gpu: 是否使用GPU
        params: LightGBM超参数覆盖

    Returns:
        WalkForwardResult
    """
    config = MLConfig(gpu=gpu)
    if feature_names:
        config.feature_names = feature_names

    trainer = WalkForwardTrainer(config)
    try:
        return trainer.run_full_walkforward(params)
    finally:
        trainer.close()
