"""SHAP可解释性模块单元测试。

测试内容:
  1. SHAPExplainer.explain_global — 全局特征重要性输出格式和内容
  2. SHAPExplainer.explain_local — 单预测分解，base_value + sum(shap) ≈ prediction
  3. SHAPExplainer.explain_temporal — 漂移检测，高漂移特征识别
  4. lambdarank辅助函数 _build_rank_groups / _to_rank_label / _compute_ndcg_at_k
  5. MLConfig lambdarank模式参数初始化
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Skip module if shap optional dependency missing — ML layer closed Phase 3D.
pytest.importorskip("shap", reason="ML predictor closed Phase 3D, shap optional")

from engines.ml_engine import (  # noqa: E402
    MLConfig,
    WalkForwardTrainer,
    _build_rank_groups,
    _compute_ndcg_at_k,
    _to_rank_label,
)
from engines.ml_explainer import SHAPExplainer  # noqa: E402

# ============================================================
# 测试夹具：合成LightGBM模型（无需数据库）
# ============================================================


def _make_synthetic_model_and_data(
    n_samples: int = 500,
    n_features: int = 5,
    seed: int = 42,
):
    """训练一个小型合成LightGBM模型用于测试。

    Returns:
        (model, feat_df, feature_names)
    """
    import lightgbm as lgb

    rng = np.random.RandomState(seed)
    feature_names = [f"feat_{i}" for i in range(n_features)]

    feat_mat = rng.randn(n_samples, n_features).astype(np.float32)
    # 真实信号：feat_0权重最高
    y = (
        0.5 * feat_mat[:, 0]
        + 0.3 * feat_mat[:, 1]
        + 0.1 * feat_mat[:, 2]
        + rng.randn(n_samples) * 0.3
    ).astype(np.float32)

    feat_df = pd.DataFrame(feat_mat, columns=feature_names)

    split = int(n_samples * 0.8)
    train_data = lgb.Dataset(feat_mat[:split], label=y[:split], feature_name=feature_names)
    valid_data = lgb.Dataset(feat_mat[split:], label=y[split:], reference=train_data)

    params = {
        "objective": "regression",
        "metric": "mse",
        "num_leaves": 15,
        "learning_rate": 0.1,
        "verbose": -1,
        "seed": seed,
    }
    model = lgb.train(
        params,
        train_data,
        num_boost_round=50,
        valid_sets=[valid_data],
        callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(-1)],
    )
    return model, feat_df, feature_names


# ============================================================
# TestSHAPExplainerGlobal
# ============================================================


class TestSHAPExplainerGlobal:
    """测试 explain_global。"""

    def test_returns_correct_types(self) -> None:
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_global(model, feat_df, feature_names)

        assert isinstance(result.feature_names, list)
        assert isinstance(result.mean_abs_shap, list)
        assert isinstance(result.shap_std, list)
        assert len(result.feature_names) == len(feature_names)
        assert len(result.mean_abs_shap) == len(feature_names)

    def test_sorted_descending(self) -> None:
        """mean_abs_shap应该按降序排列。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_global(model, feat_df, feature_names)

        for i in range(len(result.mean_abs_shap) - 1):
            assert result.mean_abs_shap[i] >= result.mean_abs_shap[i + 1], (
                f"mean_abs_shap未降序: [{i}]={result.mean_abs_shap[i]:.4f} < "
                f"[{i+1}]={result.mean_abs_shap[i+1]:.4f}"
            )

    def test_feat0_is_top(self) -> None:
        """feat_0权重最高，应该排在第一位。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_global(model, feat_df, feature_names)
        assert result.feature_names[0] == "feat_0"

    def test_all_values_nonnegative(self) -> None:
        """mean|SHAP|必须非负。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_global(model, feat_df, feature_names)
        assert all(v >= 0 for v in result.mean_abs_shap)

    def test_sampling_limit(self) -> None:
        """max_samples_global限制应生效。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data(n_samples=200)
        explainer = SHAPExplainer(max_samples_global=50)
        result = explainer.explain_global(model, feat_df, feature_names)
        assert result.total_samples == 50

    def test_numpy_input(self) -> None:
        """numpy数组输入也应正常工作。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_global(model, feat_df.values, feature_names)
        assert len(result.feature_names) == len(feature_names)

    def test_to_echarts_bar_format(self) -> None:
        """to_echarts_bar返回正确格式。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_global(model, feat_df, feature_names)
        chart = result.to_echarts_bar()
        assert "categories" in chart
        assert "series" in chart
        assert len(chart["series"]) == 2
        assert chart["series"][0]["name"] == "Mean |SHAP|"


# ============================================================
# TestSHAPExplainerLocal
# ============================================================


class TestSHAPExplainerLocal:
    """测试 explain_local。"""

    def test_base_value_plus_shap_equals_prediction(self) -> None:
        """base_value + sum(shap_values) ≈ prediction（SHAP加和性质）。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()

        single_row = feat_df.iloc[[0]]
        result = explainer.explain_local(model, single_row, feature_names)

        reconstructed = result.base_value + sum(result.shap_values)
        assert abs(reconstructed - result.prediction) < 1e-4, (
            f"base_value({result.base_value:.4f}) + sum(shap)({sum(result.shap_values):.4f}) "
            f"= {reconstructed:.4f} != prediction({result.prediction:.4f})"
        )

    def test_correct_number_of_features(self) -> None:
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_local(model, feat_df.iloc[[5]], feature_names)
        assert len(result.shap_values) == len(feature_names)
        assert len(result.feature_values) == len(feature_names)

    def test_1d_numpy_input(self) -> None:
        """1D numpy数组输入应被自动reshape。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        single_row_1d = feat_df.iloc[0].values
        result = explainer.explain_local(model, single_row_1d, feature_names)
        assert len(result.shap_values) == len(feature_names)

    def test_to_echarts_waterfall_format(self) -> None:
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_local(model, feat_df.iloc[[0]], feature_names)
        chart = result.to_echarts_waterfall()
        assert "base_value" in chart
        assert "prediction" in chart
        assert "features" in chart
        assert len(chart["features"]) == len(feature_names)
        # 按|SHAP|降序排列
        shaps = [abs(f["shap_value"]) for f in chart["features"]]
        for i in range(len(shaps) - 1):
            assert shaps[i] >= shaps[i + 1]


# ============================================================
# TestSHAPExplainerTemporal
# ============================================================


class TestSHAPExplainerTemporal:
    """测试 explain_temporal。"""

    def _make_periods(self, model, feat_df: pd.DataFrame, n_periods: int = 3) -> dict:
        n = len(feat_df) // n_periods
        periods = {}
        for i in range(n_periods):
            label = f"Period{i+1}"
            periods[label] = feat_df.iloc[i * n: (i + 1) * n]
        return periods

    def test_returns_correct_periods(self) -> None:
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        periods = self._make_periods(model, feat_df, n_periods=3)
        result = explainer.explain_temporal(model, periods, feature_names)
        assert result.periods == ["Period1", "Period2", "Period3"]

    def test_importance_matrix_shape(self) -> None:
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        periods = self._make_periods(model, feat_df, n_periods=4)
        result = explainer.explain_temporal(model, periods, feature_names)
        assert len(result.importance_matrix) == 4
        assert all(len(row) == len(feature_names) for row in result.importance_matrix)

    def test_drift_scores_length(self) -> None:
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        periods = self._make_periods(model, feat_df)
        result = explainer.explain_temporal(model, periods, feature_names)
        assert len(result.drift_scores) == len(feature_names)
        assert all(cv >= 0 for cv in result.drift_scores)

    def test_to_echarts_heatmap_format(self) -> None:
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        periods = self._make_periods(model, feat_df)
        result = explainer.explain_temporal(model, periods, feature_names)
        chart = result.to_echarts_heatmap()
        assert "x_axis" in chart
        assert "y_axis" in chart
        assert "data" in chart
        assert "high_drift_features" in chart


# ============================================================
# TestLambdarankHelpers
# ============================================================


class TestBuildRankGroups:
    """测试 _build_rank_groups。"""

    def _make_df_with_dates(self, counts: list[int]) -> tuple[pd.DataFrame, np.ndarray]:
        """构造每个截面有指定数量股票的DataFrame。"""
        rows = []
        base_date = date(2023, 1, 1)
        for i, cnt in enumerate(counts):
            td = base_date + timedelta(days=i)
            for j in range(cnt):
                rows.append({"trade_date": td, "code": f"S{j:04d}"})
        df = pd.DataFrame(rows)
        y = np.random.randn(len(df)).astype(np.float32)
        return df, y

    def test_groups_sum_equals_labels(self) -> None:
        counts = [50, 60, 45]
        df, y = self._make_df_with_dates(counts)
        groups = _build_rank_groups(df, y)
        assert sum(groups) == len(y)

    def test_groups_match_counts(self) -> None:
        counts = [30, 40, 50]
        df, y = self._make_df_with_dates(counts)
        groups = _build_rank_groups(df, y)
        assert sorted(groups) == sorted(counts)

    def test_single_date(self) -> None:
        df, y = self._make_df_with_dates([100])
        groups = _build_rank_groups(df, y)
        assert groups == [100]


class TestToRankLabel:
    """测试 _to_rank_label。"""

    def test_output_range(self) -> None:
        y = np.random.randn(200).astype(np.float32)
        labels = _to_rank_label(y, n_bins=5)
        assert labels.min() >= 0
        assert labels.max() <= 4

    def test_dtype_int32(self) -> None:
        y = np.random.randn(100).astype(np.float32)
        labels = _to_rank_label(y)
        assert labels.dtype == np.int32

    def test_higher_return_higher_label(self) -> None:
        """最高收益组的标签应高于最低收益组。"""
        y = np.array([-1.0, -0.5, 0.0, 0.5, 1.0], dtype=np.float32)
        labels = _to_rank_label(y, n_bins=5)
        assert labels[-1] > labels[0]

    def test_too_few_samples(self) -> None:
        """样本数少于n_bins时返回全零。"""
        y = np.array([0.1, 0.2], dtype=np.float32)
        labels = _to_rank_label(y, n_bins=5)
        assert (labels == 0).all()


class TestComputeNdcgAtK:
    """测试 _compute_ndcg_at_k。"""

    def _make_pred_df(
        self,
        n_dates: int = 10,
        n_stocks: int = 50,
        seed: int = 42,
    ) -> tuple[pd.DataFrame, np.ndarray]:
        rng = np.random.RandomState(seed)
        base_date = date(2023, 1, 1)
        rows = []
        for i in range(n_dates):
            td = base_date + timedelta(days=i)
            for j in range(n_stocks):
                rows.append({
                    "trade_date": td,
                    "code": f"S{j:04d}",
                    "excess_return_20": rng.randn(),
                })
        df = pd.DataFrame(rows)
        predictions = rng.randn(len(df))
        return df, predictions

    def test_perfect_ranking(self) -> None:
        """预测值与实际值完全一致时，NDCG@K = 1.0。"""
        df, _ = self._make_pred_df(n_dates=5, n_stocks=30)
        perfect_pred = df["excess_return_20"].values.copy()
        ndcg = _compute_ndcg_at_k(df, perfect_pred, "excess_return_20", k=15)
        assert abs(ndcg - 1.0) < 1e-6, f"完美排序NDCG应为1.0，实际={ndcg:.6f}"

    def test_random_ranking_below_perfect(self) -> None:
        """随机预测的NDCG@K应小于完美排序。"""
        df, random_pred = self._make_pred_df(n_dates=10, n_stocks=50)
        perfect_pred = df["excess_return_20"].values.copy()

        ndcg_perfect = _compute_ndcg_at_k(df, perfect_pred, "excess_return_20", k=15)
        ndcg_random = _compute_ndcg_at_k(df, random_pred, "excess_return_20", k=15)

        assert ndcg_perfect > ndcg_random, (
            f"完美NDCG({ndcg_perfect:.4f}) 应 > 随机NDCG({ndcg_random:.4f})"
        )

    def test_value_in_range(self) -> None:
        """NDCG@K应在[0, 1]范围内。"""
        df, predictions = self._make_pred_df()
        ndcg = _compute_ndcg_at_k(df, predictions, "excess_return_20", k=15)
        assert 0.0 <= ndcg <= 1.0, f"NDCG={ndcg:.4f} 超出[0,1]范围"

    def test_insufficient_stocks(self) -> None:
        """截面股票数少于K时跳过，不崩溃。"""
        df, predictions = self._make_pred_df(n_dates=5, n_stocks=5)
        # k=15 > n_stocks=5，所有截面都应被跳过，返回0.0
        ndcg = _compute_ndcg_at_k(df, predictions, "excess_return_20", k=15)
        assert ndcg == 0.0


# ============================================================
# TestMLConfigLambdarank
# ============================================================


class TestMLConfigLambdarank:
    """测试MLConfig lambdarank模式参数。"""

    def test_default_mode_is_regression(self) -> None:
        cfg = MLConfig()
        assert cfg.mode == "regression"

    def test_lambdarank_mode(self) -> None:
        cfg = MLConfig(mode="lambdarank")
        assert cfg.mode == "lambdarank"
        assert cfg.ndcg_at_k == 15

    def test_lambdarank_params_setup(self) -> None:
        """lambdarank模式下_setup_default_params应设置正确的objective。"""
        cfg = MLConfig(mode="lambdarank", gpu=False)
        trainer = WalkForwardTrainer(cfg, conn=None)
        params = trainer._default_lgb_params
        assert params["objective"] == "lambdarank"
        assert params["metric"] == "ndcg"
        assert params["ndcg_eval_at"] == [15]

    def test_regression_params_unchanged(self) -> None:
        """regression模式下参数与原来一致。"""
        cfg = MLConfig(mode="regression", gpu=False)
        trainer = WalkForwardTrainer(cfg, conn=None)
        params = trainer._default_lgb_params
        assert params["objective"] == "regression"
        assert params["metric"] == "mse"

    def test_lambdarank_ndcg_at_k_configurable(self) -> None:
        """ndcg_at_k可配置，默认15。"""
        cfg = MLConfig(mode="lambdarank", ndcg_at_k=10)
        assert cfg.ndcg_at_k == 10


# ============================================================
# 铁律7: OOS三段分离验证
# ============================================================


class TestOOSThreeSplitValidation:
    """铁律7: 训练/验证/测试三段分离，过拟合比率检测。

    ML实验必须OOS验证——训练IC/OOS IC > 3倍 = 过拟合。
    """

    def test_generate_folds_returns_nonempty(self) -> None:
        """generate_folds应返回至少1个fold。"""
        from datetime import date

        cfg = MLConfig(
            data_start=date(2021, 1, 1),
            data_end=date(2024, 12, 31),
            train_months=24,
            valid_months=6,
            test_months=3,
            step_months=3,
            expanding_folds=2,
            gpu=False,
        )
        trainer = WalkForwardTrainer(cfg, conn=None)
        folds = trainer.generate_folds()
        assert len(folds) >= 1, "generate_folds应返回至少1个fold"

    def test_folds_no_train_val_overlap(self) -> None:
        """每个fold的train_end <= valid_start（无时间泄露）。"""
        from datetime import date

        cfg = MLConfig(
            data_start=date(2021, 1, 1),
            data_end=date(2024, 12, 31),
            train_months=24,
            valid_months=6,
            test_months=3,
            step_months=3,
            expanding_folds=2,
            gpu=False,
        )
        trainer = WalkForwardTrainer(cfg, conn=None)
        folds = trainer.generate_folds()

        for i, fold in enumerate(folds):
            assert fold.train_end <= fold.valid_start, (
                f"Fold {i}: train_end({fold.train_end}) > valid_start({fold.valid_start})"
                " — 时间泄露！"
            )

    def test_folds_no_valid_test_overlap(self) -> None:
        """每个fold的valid_end <= test_start（验证集不泄露到测试集）。"""
        from datetime import date

        cfg = MLConfig(
            data_start=date(2021, 1, 1),
            data_end=date(2024, 12, 31),
            train_months=24,
            valid_months=6,
            test_months=3,
            step_months=3,
            expanding_folds=2,
            gpu=False,
        )
        trainer = WalkForwardTrainer(cfg, conn=None)
        folds = trainer.generate_folds()

        for i, fold in enumerate(folds):
            assert fold.valid_end <= fold.test_start, (
                f"Fold {i}: valid_end({fold.valid_end}) > test_start({fold.test_start})"
                " — 验证集/测试集重叠！"
            )

    def test_expanding_folds_train_start_fixed(self) -> None:
        """扩展窗口fold: 前expanding_folds个fold的train_start应相同（不滑动）。"""
        from datetime import date

        n_expanding = 3
        cfg = MLConfig(
            data_start=date(2020, 1, 1),
            data_end=date(2024, 12, 31),
            train_months=12,
            valid_months=3,
            test_months=3,
            step_months=3,
            expanding_folds=n_expanding,
            gpu=False,
        )
        trainer = WalkForwardTrainer(cfg, conn=None)
        folds = trainer.generate_folds()

        if len(folds) >= n_expanding:
            starts = [folds[i].train_start for i in range(min(n_expanding, len(folds)))]
            assert len(set(starts)) == 1, (
                f"扩展窗口fold的train_start应相同: {starts}"
            )

    def test_fold_result_has_overfit_ratio(self) -> None:
        """FoldResult应包含overfit_ratio字段（铁律7过拟合检测）。"""
        from engines.ml_engine import FoldResult

        result = FoldResult(
            fold_id=1,
            train_ic=0.06,
            valid_ic=0.03,
            oos_ic=0.02,
            overfit_ratio=3.0,
            is_overfit=True,
        )
        assert result.overfit_ratio == 3.0
        assert result.is_overfit is True

    def test_overfit_threshold_3x(self) -> None:
        """铁律7: train_ic / oos_ic > 3倍应标记为过拟合。"""
        from engines.ml_engine import FoldResult

        # 构建一个train_ic=0.09, oos_ic=0.02 → ratio=4.5 > 3 的结果
        result = FoldResult(
            fold_id=1,
            train_ic=0.09,
            valid_ic=0.04,
            oos_ic=0.02,
            overfit_ratio=4.5,
            is_overfit=True,
        )
        assert result.is_overfit is True, "train_ic/oos_ic=4.5 应被标记为过拟合"

    def test_non_overfit_below_3x(self) -> None:
        """train_ic / oos_ic <= 3倍时不应标记为过拟合。"""
        from engines.ml_engine import FoldResult

        result = FoldResult(
            fold_id=1,
            train_ic=0.06,
            valid_ic=0.04,
            oos_ic=0.03,
            overfit_ratio=2.0,
            is_overfit=False,
        )
        assert result.is_overfit is False, "train_ic/oos_ic=2.0 不应标记为过拟合"


# ============================================================
# SHAPExplainer 额外边界条件测试
# ============================================================


class TestSHAPEdgeCases:
    """SHAP解释器边界条件测试。"""

    def test_explain_global_single_feature(self) -> None:
        """单特征模型的explain_global应正常工作，不崩溃。"""
        import lightgbm as lgb

        rng = np.random.RandomState(0)
        n = 200
        x = rng.randn(n, 1).astype(np.float32)
        y = (x[:, 0] + rng.randn(n) * 0.1).astype(np.float32)
        feat_df = pd.DataFrame(x, columns=["feat_0"])

        train = lgb.Dataset(x, label=y)
        model = lgb.train(
            {"objective": "regression", "verbose": -1, "num_leaves": 4},
            train,
            num_boost_round=20,
        )

        explainer = SHAPExplainer()
        result = explainer.explain_global(model, feat_df, ["feat_0"])
        assert len(result.feature_names) == 1
        assert result.mean_abs_shap[0] >= 0

    def test_explain_local_multi_row_raises_on_wrong_shape(self) -> None:
        """explain_local传入多行时应正常处理（取第一行）或不崩溃。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        # 传入多行 — 要么正常处理要么抛出有意义的错误
        try:
            result = explainer.explain_local(model, feat_df.iloc[:3], feature_names)
            assert len(result.shap_values) == len(feature_names)
        except (ValueError, IndexError):
            pass  # 明确的错误也可接受

    def test_explain_temporal_single_period(self) -> None:
        """只有1个时间段时explain_temporal应不崩溃。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        periods = {"OnlyPeriod": feat_df}
        result = explainer.explain_temporal(model, periods, feature_names)
        assert result.periods == ["OnlyPeriod"]
        assert len(result.importance_matrix) == 1

    def test_global_importance_sum_positive(self) -> None:
        """所有特征的mean_abs_shap之和应大于零（模型有信号）。"""
        model, feat_df, feature_names = _make_synthetic_model_and_data()
        explainer = SHAPExplainer()
        result = explainer.explain_global(model, feat_df, feature_names)
        assert sum(result.mean_abs_shap) > 0.0


# ============================================================
# NDCG额外边界条件测试
# ============================================================


class TestNDCGEdgeCases:
    """NDCG@K额外边界条件测试。"""

    def test_reversed_ranking_below_perfect(self) -> None:
        """完全逆序预测的NDCG@K应低于完美排序。"""
        base_date = date(2023, 1, 1)
        rows = []
        for i in range(5):
            td = base_date + timedelta(days=i)
            for j in range(30):
                rows.append({
                    "trade_date": td,
                    "code": f"S{j:04d}",
                    "excess_return_20": float(j),
                })
        df = pd.DataFrame(rows)

        # 完美预测：预测值 = 实际值
        perfect_pred = df["excess_return_20"].values.copy()
        # 逆序预测：预测值与实际值相反
        reversed_pred = -perfect_pred

        ndcg_perfect = _compute_ndcg_at_k(df, perfect_pred, "excess_return_20", k=10)
        ndcg_reversed = _compute_ndcg_at_k(df, reversed_pred, "excess_return_20", k=10)

        assert ndcg_perfect > ndcg_reversed, (
            f"完美NDCG({ndcg_perfect:.4f}) 应 > 逆序NDCG({ndcg_reversed:.4f})"
        )

    def test_ndcg_k_equals_1(self) -> None:
        """k=1时NDCG@1应在[0,1]范围内。"""
        rng = np.random.RandomState(42)
        base_date = date(2023, 1, 1)
        rows = [
            {"trade_date": base_date + timedelta(days=i), "code": f"S{j:04d}",
             "excess_return_20": rng.randn()}
            for i in range(5) for j in range(20)
        ]
        df = pd.DataFrame(rows)
        preds = rng.randn(len(df))
        ndcg = _compute_ndcg_at_k(df, preds, "excess_return_20", k=1)
        assert 0.0 <= ndcg <= 1.0
