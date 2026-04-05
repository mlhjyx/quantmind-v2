"""SHAP可解释性模块 -- LightGBM因子重要性分析。

为ML Walk-Forward训练框架提供三类解释:
  1. global: 全局特征重要性 (mean |SHAP|)
  2. local: 单预测特征贡献分解
  3. temporal: 时序因子重要性稳定性（特征漂移检测）

设计原则:
- 严格使用 shap.TreeExplainer（LightGBM专用，速度快）
- 所有输出为结构化dict，供FastAPI直接序列化为JSON给前端ECharts渲染
- 不依赖数据库，只依赖训练好的LightGBM模型和特征矩阵
"""
# ruff: noqa: N803 N806 B905 B007

import structlog
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = structlog.get_logger(__name__)


# ============================================================
# 输出数据类
# ============================================================


@dataclass
class FeatureImportance:
    """全局特征重要性结果。

    Attributes:
        feature_names: 特征名列表（按重要性降序排列）
        mean_abs_shap: 各特征的平均|SHAP|值（与feature_names对应）
        shap_std: 各特征SHAP值的标准差（衡量稳定性）
        total_samples: 计算使用的样本数
    """

    feature_names: list[str] = field(default_factory=list)
    mean_abs_shap: list[float] = field(default_factory=list)
    shap_std: list[float] = field(default_factory=list)
    total_samples: int = 0

    def to_echarts_bar(self) -> dict[str, Any]:
        """转换为ECharts横向柱状图格式。

        Returns:
            ECharts option dict，包含 categories 和 series
        """
        return {
            "categories": self.feature_names,
            "series": [
                {
                    "name": "Mean |SHAP|",
                    "data": self.mean_abs_shap,
                },
                {
                    "name": "SHAP Std",
                    "data": self.shap_std,
                },
            ],
            "total_samples": self.total_samples,
        }


@dataclass
class PredictionBreakdown:
    """单预测特征贡献分解结果。

    Attributes:
        base_value: SHAP基准值（期望预测值）
        prediction: 模型最终预测值
        feature_names: 特征名列表
        shap_values: 各特征的SHAP贡献值（正=助推，负=拉低）
        feature_values: 各特征的原始输入值
    """

    base_value: float = 0.0
    prediction: float = 0.0
    feature_names: list[str] = field(default_factory=list)
    shap_values: list[float] = field(default_factory=list)
    feature_values: list[float] = field(default_factory=list)

    def to_echarts_waterfall(self) -> dict[str, Any]:
        """转换为ECharts瀑布图格式（从base_value累加到prediction）。

        Returns:
            ECharts option dict
        """
        # 按|SHAP|降序排列，只展示top贡献因子
        pairs = sorted(
            zip(self.feature_names, self.shap_values, self.feature_values, strict=True),
            key=lambda x: abs(x[1]),
            reverse=True,
        )
        names = [p[0] for p in pairs]
        shaps = [p[1] for p in pairs]
        fvals = [p[2] for p in pairs]

        return {
            "base_value": self.base_value,
            "prediction": self.prediction,
            "features": [
                {
                    "name": n,
                    "shap_value": float(s),
                    "feature_value": float(v),
                }
                for n, s, v in zip(names, shaps, fvals, strict=True)
            ],
        }


@dataclass
class TemporalStability:
    """时序因子重要性稳定性结果。

    Attributes:
        periods: 时间段标签列表（如 ['2021H1', '2021H2', ...]）
        feature_names: 特征名列表
        importance_matrix: shape=(len(periods), len(feature_names)) 的二维列表
            每行是该时间段内各特征的mean|SHAP|
        drift_scores: 各特征的漂移分数（时间段间importance的变异系数CV）
            CV > 0.5 = 高漂移特征，CV < 0.2 = 稳定特征
    """

    periods: list[str] = field(default_factory=list)
    feature_names: list[str] = field(default_factory=list)
    importance_matrix: list[list[float]] = field(default_factory=list)
    drift_scores: list[float] = field(default_factory=list)

    def to_echarts_heatmap(self) -> dict[str, Any]:
        """转换为ECharts热力图格式。

        Returns:
            ECharts option dict，x轴=特征，y轴=时间段，值=importance
        """
        heatmap_data = []
        for i, _period in enumerate(self.periods):
            for j, _feat in enumerate(self.feature_names):
                val = self.importance_matrix[i][j] if i < len(self.importance_matrix) else 0.0
                heatmap_data.append([j, i, round(val, 6)])

        high_drift = [
            {"feature": f, "cv": round(cv, 3)}
            for f, cv in zip(self.feature_names, self.drift_scores, strict=True)
            if cv > 0.5
        ]

        return {
            "x_axis": self.feature_names,
            "y_axis": self.periods,
            "data": heatmap_data,
            "high_drift_features": high_drift,
        }


# ============================================================
# SHAP解释器
# ============================================================


class SHAPExplainer:
    """LightGBM SHAP可解释性包装器。

    使用 shap.TreeExplainer，对LightGBM模型进行三类解释:
    - global: 全局特征重要性
    - local: 单样本预测贡献分解
    - temporal: 跨时间段因子漂移检测
    """

    def __init__(self, max_samples_global: int = 5000) -> None:
        """初始化。

        Args:
            max_samples_global: 全局重要性计算使用的最大样本数。
                SHAP TreeExplainer对大矩阵较慢，限制样本数防止超时。
        """
        self.max_samples_global = max_samples_global

    def _get_explainer(self, model: Any) -> Any:
        """构建shap.TreeExplainer。

        Args:
            model: 训练好的LightGBM Booster

        Returns:
            shap.TreeExplainer实例
        """
        import shap

        return shap.TreeExplainer(model)

    def explain_global(
        self,
        model: Any,
        features: pd.DataFrame | np.ndarray,
        feature_names: list[str] | None = None,
    ) -> FeatureImportance:
        """计算全局特征重要性（mean |SHAP|）。

        Args:
            model: 训练好的LightGBM Booster
            features: 特征矩阵，shape=(n_samples, n_features)
            feature_names: 特征名列表。若features是DataFrame则自动使用列名。

        Returns:
            FeatureImportance（按重要性降序排列）
        """
        if isinstance(features, pd.DataFrame):
            if feature_names is None:
                feature_names = list(features.columns)
            feat_arr = features.values.astype(np.float32)
        else:
            feat_arr = features.astype(np.float32)
            if feature_names is None:
                feature_names = [f"f{i}" for i in range(feat_arr.shape[1])]

        # 随机采样防止超时
        n = len(feat_arr)
        if n > self.max_samples_global:
            rng = np.random.RandomState(42)
            idx = rng.choice(n, self.max_samples_global, replace=False)
            feat_arr = feat_arr[idx]
            logger.info(
                f"explain_global: 采样 {self.max_samples_global}/{n} 行计算SHAP"
            )

        explainer = self._get_explainer(model)
        shap_values = explainer.shap_values(feat_arr)

        # shap_values shape: (n_samples, n_features)
        mean_abs = np.abs(shap_values).mean(axis=0)
        shap_std = np.abs(shap_values).std(axis=0)

        # 按mean_abs降序排列
        order = np.argsort(mean_abs)[::-1]
        sorted_names = [feature_names[i] for i in order]
        sorted_mean_abs = [float(mean_abs[i]) for i in order]
        sorted_std = [float(shap_std[i]) for i in order]

        logger.info(
            f"explain_global: top3={sorted_names[:3]}, "
            f"mean_abs={[round(v, 4) for v in sorted_mean_abs[:3]]}"
        )

        return FeatureImportance(
            feature_names=sorted_names,
            mean_abs_shap=sorted_mean_abs,
            shap_std=sorted_std,
            total_samples=len(feat_arr),
        )

    def explain_local(
        self,
        model: Any,
        features_single: pd.DataFrame | np.ndarray,
        feature_names: list[str] | None = None,
    ) -> PredictionBreakdown:
        """单预测特征贡献分解。

        Args:
            model: 训练好的LightGBM Booster
            features_single: 单行特征，shape=(1, n_features) 或 (n_features,)
            feature_names: 特征名列表

        Returns:
            PredictionBreakdown（包含base_value, prediction, 各特征贡献）
        """
        if isinstance(features_single, pd.DataFrame):
            if feature_names is None:
                feature_names = list(features_single.columns)
            feat_arr = features_single.values.astype(np.float32)
        else:
            feat_arr = features_single.astype(np.float32)
            if feature_names is None:
                feature_names = [f"f{i}" for i in range(feat_arr.shape[-1])]

        # 确保是2D
        if feat_arr.ndim == 1:
            feat_arr = feat_arr.reshape(1, -1)

        explainer = self._get_explainer(model)
        shap_values = explainer.shap_values(feat_arr)  # shape: (1, n_features)
        base_value = float(explainer.expected_value)

        row_shap = shap_values[0]  # shape: (n_features,)
        row_feat = feat_arr[0]
        prediction = base_value + float(row_shap.sum())

        return PredictionBreakdown(
            base_value=base_value,
            prediction=prediction,
            feature_names=feature_names,
            shap_values=[float(v) for v in row_shap],
            feature_values=[float(v) for v in row_feat],
        )

    def explain_temporal(
        self,
        model: Any,
        features_by_period: dict[str, pd.DataFrame | np.ndarray],
        feature_names: list[str] | None = None,
    ) -> TemporalStability:
        """时序因子重要性稳定性分析。

        对每个时间段分别计算全局mean|SHAP|，然后计算各特征的
        变异系数CV = std/mean（CV > 0.5为高漂移）。

        Args:
            model: 训练好的LightGBM Booster
            features_by_period: 有序字典 {period_label: features_array}
                例如 {'2021H1': df_2021h1, '2021H2': df_2021h2, ...}
            feature_names: 特征名列表

        Returns:
            TemporalStability
        """
        periods = list(features_by_period.keys())
        importance_matrix: list[list[float]] = []

        # 从第一个period推断feature_names
        first_feat = next(iter(features_by_period.values()))
        if feature_names is None:
            if isinstance(first_feat, pd.DataFrame):
                feature_names = list(first_feat.columns)
            else:
                feature_names = [f"f{i}" for i in range(first_feat.shape[1])]

        explainer = self._get_explainer(model)

        for period_label, feat in features_by_period.items():
            if isinstance(feat, pd.DataFrame):
                feat_arr = feat.values.astype(np.float32)
            else:
                feat_arr = feat.astype(np.float32)

            # 每个时间段也限制采样
            n = len(feat_arr)
            if n > self.max_samples_global:
                rng = np.random.RandomState(42)
                idx = rng.choice(n, self.max_samples_global, replace=False)
                feat_arr = feat_arr[idx]

            shap_values = explainer.shap_values(feat_arr)
            mean_abs = np.abs(shap_values).mean(axis=0)
            importance_matrix.append([float(v) for v in mean_abs])

            logger.info(
                f"explain_temporal [{period_label}]: "
                f"top_feature={feature_names[int(np.argmax(mean_abs))]}, "
                f"max_importance={float(mean_abs.max()):.4f}"
            )

        # 计算各特征的漂移分数（变异系数CV）
        if len(importance_matrix) < 2:
            drift_scores = [0.0] * len(feature_names)
        else:
            imp_arr = np.array(importance_matrix)  # shape: (n_periods, n_features)
            means = imp_arr.mean(axis=0)
            stds = imp_arr.std(axis=0)
            # 避免除零：mean接近0的特征直接设CV=0
            drift_scores = []
            for m, s in zip(means, stds, strict=True):
                cv = float(s / m) if m > 1e-8 else 0.0
                drift_scores.append(round(cv, 4))

        # 重排列：按整体重要性降序排列特征
        overall_importance = np.array(importance_matrix).mean(axis=0)
        order = np.argsort(overall_importance)[::-1]

        sorted_names = [feature_names[i] for i in order]
        sorted_matrix = [
            [row[i] for i in order]
            for row in importance_matrix
        ]
        sorted_drift = [drift_scores[i] for i in order]

        high_drift_count = sum(1 for cv in sorted_drift if cv > 0.5)
        logger.info(
            f"explain_temporal: {len(periods)}个时间段, "
            f"高漂移特征数={high_drift_count}/{len(feature_names)}"
        )

        return TemporalStability(
            periods=periods,
            feature_names=sorted_names,
            importance_matrix=sorted_matrix,
            drift_scores=sorted_drift,
        )
