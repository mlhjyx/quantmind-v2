"""因子计算确定性测试。

CLAUDE.md规则3: 同参数跑两次结果bit-identical(精确到小数点后6位)。
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.factor_engine import compute_daily_factors, preprocess_pipeline


def test_factor_determinism():
    """同一天计算两次, 结果必须完全一致。"""
    td = date(2025, 3, 14)

    result1 = compute_daily_factors(td, factor_set="core")
    result2 = compute_daily_factors(td, factor_set="core")

    assert len(result1) == len(result2), "行数不一致"

    # 按(code, factor_name)排序确保对齐
    r1 = result1.sort_values(["code", "factor_name"]).reset_index(drop=True)
    r2 = result2.sort_values(["code", "factor_name"]).reset_index(drop=True)

    # raw_value精确比较(6位小数)
    for col in ["raw_value", "neutral_value", "zscore"]:
        v1 = r1[col].fillna(-999999).round(6)
        v2 = r2[col].fillna(-999999).round(6)
        diff = (v1 - v2).abs()
        assert diff.max() < 1e-6, (
            f"{col} 不一致: max_diff={diff.max()}, "
            f"at index={diff.idxmax()}"
        )


def test_preprocess_determinism():
    """预处理管道确定性测试。"""
    rng = np.random.RandomState(42)
    n = 100

    series = pd.Series(rng.randn(n), index=[f"s{i:04d}" for i in range(n)])
    ln_mcap = pd.Series(rng.randn(n) + 13, index=series.index)
    industry = pd.Series(
        rng.choice(["银行", "地产", "科技", "消费", "医药"], n),
        index=series.index,
    )

    raw1, nv1 = preprocess_pipeline(series.copy(), ln_mcap.copy(), industry.copy())
    raw2, nv2 = preprocess_pipeline(series.copy(), ln_mcap.copy(), industry.copy())

    pd.testing.assert_series_equal(raw1, raw2, check_exact=False, atol=1e-10)
    pd.testing.assert_series_equal(nv1, nv2, check_exact=False, atol=1e-10)


if __name__ == "__main__":
    print("Running determinism tests...")
    test_preprocess_determinism()
    print("  preprocess_determinism: PASSED")
    test_factor_determinism()
    print("  factor_determinism: PASSED")
    print("All tests passed!")
