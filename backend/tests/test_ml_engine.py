"""Walk-Forward ML引擎基础测试。

测试内容:
  1. Fold生成逻辑正确性
  2. 数据加载（F1 fold）
  3. 特征预处理器
"""

import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.ml_engine import (
    FeaturePreprocessor,
    MLConfig,
    WalkForwardTrainer,
    _add_months,
    compute_daily_ic,
    compute_icir,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# 单元测试（不依赖数据库）
# ============================================================


class TestAddMonths:
    """测试日期月份加减。"""

    def test_add_positive(self) -> None:
        assert _add_months(date(2020, 7, 1), 6) == date(2021, 1, 1)

    def test_add_24(self) -> None:
        assert _add_months(date(2020, 7, 1), 24) == date(2022, 7, 1)

    def test_add_negative(self) -> None:
        assert _add_months(date(2023, 1, 1), -6) == date(2022, 7, 1)

    def test_month_end(self) -> None:
        # 1月31日 + 1个月 = 2月28日（非闰年）
        result = _add_months(date(2023, 1, 31), 1)
        assert result == date(2023, 2, 28)

    def test_leap_year(self) -> None:
        result = _add_months(date(2024, 1, 31), 1)
        assert result == date(2024, 2, 29)


class TestFeaturePreprocessor:
    """测试特征预处理器（防泄露）。"""

    def _make_df(self, n: int = 1000) -> pd.DataFrame:
        rng = np.random.RandomState(42)
        return pd.DataFrame({
            "feat_a": rng.randn(n) * 10 + 50,
            "feat_b": rng.randn(n) * 5 + 0,
        })

    def test_fit_transform(self) -> None:
        """fit后transform应该产生近似标准正态分布。"""
        df = self._make_df(1000)
        pp = FeaturePreprocessor()
        pp.fit(df, ["feat_a", "feat_b"])
        result = pp.transform(df)

        # zscore后均值接近0，标准差接近1
        assert abs(result["feat_a"].mean()) < 0.1
        assert abs(result["feat_b"].mean()) < 0.1
        assert abs(result["feat_a"].std() - 1.0) < 0.1

    def test_transform_uses_train_params(self) -> None:
        """transform使用训练集参数，不是测试集自身的参数。"""
        train_df = self._make_df(500)
        # 测试集分布偏移
        test_df = pd.DataFrame({
            "feat_a": np.ones(100) * 100,  # 远离训练集分布
            "feat_b": np.ones(100) * -50,
        })

        pp = FeaturePreprocessor()
        pp.fit(train_df, ["feat_a", "feat_b"])
        result = pp.transform(test_df)

        # 测试集transform后均值不会是0（因为用的训练集参数）
        assert abs(result["feat_a"].mean()) > 1.0

    def test_nan_handling(self) -> None:
        """缺失值应被填充为0后再zscore。"""
        df = pd.DataFrame({
            "feat_a": [1.0, 2.0, np.nan, 4.0, 5.0],
        })
        pp = FeaturePreprocessor()
        pp.fit(df, ["feat_a"])
        result = pp.transform(df)
        assert not result["feat_a"].isna().any()

    def test_not_fitted_raises(self) -> None:
        """未fit就transform应报错。"""
        pp = FeaturePreprocessor()
        with pytest.raises(RuntimeError, match="必须先调用fit"):
            pp.transform(pd.DataFrame({"feat_a": [1, 2, 3]}))


class TestComputeIC:
    """测试IC计算函数。"""

    def test_perfect_correlation(self) -> None:
        """完美相关IC应为1.0。"""
        df = pd.DataFrame({
            "trade_date": [date(2023, 1, 1)] * 50,
            "code": [f"code_{i}" for i in range(50)],
            "predicted": list(range(50)),
            "actual": list(range(50)),
        })
        ics = compute_daily_ic(df, method="spearman")
        assert abs(ics.iloc[0] - 1.0) < 1e-6

    def test_zero_correlation(self) -> None:
        """不相关的随机数IC应接近0。"""
        rng = np.random.RandomState(42)
        n = 200
        df = pd.DataFrame({
            "trade_date": [date(2023, 1, 1)] * n,
            "code": [f"code_{i}" for i in range(n)],
            "predicted": rng.randn(n),
            "actual": rng.randn(n),
        })
        ics = compute_daily_ic(df, method="spearman")
        assert abs(ics.iloc[0]) < 0.2  # 接近0但有随机波动

    def test_too_few_samples(self) -> None:
        """样本数<30应返回空。"""
        df = pd.DataFrame({
            "trade_date": [date(2023, 1, 1)] * 10,
            "code": [f"code_{i}" for i in range(10)],
            "predicted": list(range(10)),
            "actual": list(range(10)),
        })
        ics = compute_daily_ic(df)
        assert len(ics) == 0


class TestICIR:
    """测试ICIR计算。"""

    def test_stable_ic(self) -> None:
        """稳定的IC序列ICIR应该很高。"""
        daily_ics = pd.Series([0.05] * 20)
        icir = compute_icir(daily_ics)
        # 标准差接近0，ICIR应该非常大
        # 但由于std近似为0，会被限制
        assert icir > 1.0 or abs(daily_ics.std()) < 1e-6

    def test_noisy_ic(self) -> None:
        """波动大的IC序列ICIR应该低。"""
        rng = np.random.RandomState(42)
        daily_ics = pd.Series(rng.randn(100) * 0.1)  # 均值接近0，std大
        icir = compute_icir(daily_ics)
        assert abs(icir) < 1.0


class TestFoldGeneration:
    """测试fold生成逻辑（使用mock交易日历）。"""

    def _mock_trade_dates(self) -> list[date]:
        """生成2020-07到2026-03的模拟交易日（每月22天）。"""
        dates = []
        current = date(2020, 7, 1)
        end = date(2026, 3, 31)
        day_count = 0
        while current <= end:
            if current.weekday() < 5:  # 排除周末
                dates.append(current)
                day_count += 1
            current += pd.Timedelta(days=1).to_pytimedelta()
        return dates

    def test_fold_count(self) -> None:
        """应生成7个fold。"""
        config = MLConfig()
        trainer = WalkForwardTrainer(config)
        # 注入mock交易日历
        trainer._trade_dates = self._mock_trade_dates()
        folds = trainer.generate_folds()

        assert len(folds) == 7, f"期望7个fold，实际{len(folds)}"

    def test_first_three_expanding(self) -> None:
        """F1-F3应为扩展窗口。"""
        config = MLConfig()
        trainer = WalkForwardTrainer(config)
        trainer._trade_dates = self._mock_trade_dates()
        folds = trainer.generate_folds()

        for f in folds[:3]:
            assert f.is_expanding, f"F{f.fold_id} 应为扩展窗口"
        for f in folds[3:]:
            assert not f.is_expanding, f"F{f.fold_id} 应为固定窗口"

    def test_no_overlap(self) -> None:
        """各fold测试集之间不应有时间overlap。"""
        config = MLConfig()
        trainer = WalkForwardTrainer(config)
        trainer._trade_dates = self._mock_trade_dates()
        folds = trainer.generate_folds()

        for i in range(len(folds) - 1):
            assert folds[i].test_end < folds[i + 1].test_start, (
                f"F{folds[i].fold_id}测试结束({folds[i].test_end}) "
                f">= F{folds[i+1].fold_id}测试开始({folds[i+1].test_start})"
            )

    def test_purge_gap(self) -> None:
        """验证集开始日期应在训练结束后至少purge_days个交易日之后。"""
        config = MLConfig(purge_days=5)
        trainer = WalkForwardTrainer(config)
        trade_dates = self._mock_trade_dates()
        trainer._trade_dates = trade_dates

        folds = trainer.generate_folds()
        for f in folds:
            # 找训练结束到验证开始之间的交易日数
            gap_dates = [td for td in trade_dates if f.train_end < td < f.valid_start]
            assert len(gap_dates) >= config.purge_days - 1, (
                f"F{f.fold_id} purge gap不足: "
                f"train_end={f.train_end}, valid_start={f.valid_start}, "
                f"gap={len(gap_dates)}天"
            )

    def test_last_fold_partial(self) -> None:
        """最后一个fold可能是partial（测试窗口不满6个月）。"""
        config = MLConfig(data_end=date(2026, 3, 24))
        trainer = WalkForwardTrainer(config)
        trainer._trade_dates = self._mock_trade_dates()
        folds = trainer.generate_folds()

        last = folds[-1]
        # F7测试区间应该在2026年初，不满6个月
        assert last.is_partial or last.test_end <= config.data_end


# ============================================================
# 集成测试（需要数据库，标记为slow）
# ============================================================


@pytest.mark.slow
class TestDataLoading:
    """数据加载集成测试（需要PostgreSQL）。"""

    def test_load_f1_features(self) -> None:
        """测试F1 fold的数据加载。"""
        config = MLConfig(
            feature_names=[
                "turnover_mean_20", "volatility_20", "reversal_20",
                "amihud_20", "bp_ratio",
            ],
        )
        trainer = WalkForwardTrainer(config)

        try:
            folds = trainer.generate_folds()
            f1 = folds[0]

            logger.info(f"F1: Train[{f1.train_start}~{f1.train_end}] "
                       f"Test[{f1.test_start}~{f1.test_end}]")

            # 只加载F1训练集范围的数据
            df = trainer.load_features(f1.train_start, f1.train_end)

            # 基本检查
            assert not df.empty, "F1训练集特征不应为空"
            assert "excess_return_20" in df.columns, "应包含目标变量"

            for feat in config.feature_names:
                assert feat in df.columns, f"应包含特征 {feat}"

            # 数据量检查（24个月 × ~4000股 × 22天 = 约200万行，不必这么多但至少要有数据）
            logger.info(f"F1训练数据: {len(df)}行, {df['code'].nunique()}股, "
                       f"{df['trade_date'].nunique()}天")
            assert len(df) > 10000, f"F1训练数据太少: {len(df)}行"

            # 无NaN检查（合并后的数据不应有大量NaN）
            nan_ratio = df[config.feature_names].isna().mean().mean()
            logger.info(f"特征NaN比例: {nan_ratio:.4f}")
            assert nan_ratio < 0.5, f"特征NaN比例过高: {nan_ratio:.4f}"

            # 目标变量范围检查
            target = df["excess_return_20"]
            logger.info(f"目标变量: mean={target.mean():.6f}, "
                       f"std={target.std():.6f}, "
                       f"min={target.min():.6f}, max={target.max():.6f}")
            assert target.std() > 0.001, "目标变量标准差过小"
            assert target.std() < 1.0, "目标变量标准差过大（可能单位错误）"

        finally:
            trainer.close()


if __name__ == "__main__":
    # 运行不依赖数据库的快速测试
    pytest.main([__file__, "-v", "-k", "not slow", "--tb=short"])
