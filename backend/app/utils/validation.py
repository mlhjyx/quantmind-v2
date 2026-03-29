"""数据质量验证工具函数。

提供通用数据验证方法，供数据拉取和因子计算模块使用。
设计文档: docs/TUSHARE_DATA_SOURCE_CHECKLIST.md 验证规则。

使用:
    from app.utils.validation import validate_klines, validate_factor_values
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """数据验证结果。"""

    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    row_count: int = 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_klines(df: pd.DataFrame, trade_date: date | None = None) -> ValidationResult:
    """验证K线数据质量。

    检查项:
    - 行数 > 3000（A股市场正常应有4000+只股票）
    - 无全NULL行
    - 价格合理（close > 0, volume >= 0）
    - trade_date一致（如提供）

    Args:
        df: K线数据DataFrame，需含 code/trade_date/close/volume 列。
        trade_date: 期望的交易日期。

    Returns:
        ValidationResult。
    """
    result = ValidationResult(row_count=len(df))

    if len(df) == 0:
        result.add_error("K线数据为空")
        return result

    if len(df) < 3000:
        result.add_warning(f"股票数偏少: {len(df)} < 3000")

    # 检查必要列
    required_cols = {"code", "trade_date", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        result.add_error(f"缺少必要列: {missing}")
        return result

    # 价格合理性
    if (df["close"] <= 0).any():
        bad_count = (df["close"] <= 0).sum()
        result.add_error(f"存在非正收盘价: {bad_count}条")

    if (df["volume"] < 0).any():
        bad_count = (df["volume"] < 0).sum()
        result.add_error(f"存在负成交量: {bad_count}条")

    # NULL检查
    null_pct = df[["close", "volume"]].isnull().mean()
    for col, pct in null_pct.items():
        if pct > 0.1:
            result.add_warning(f"{col} NULL占比 {pct:.1%} > 10%")

    # 日期一致性
    if trade_date is not None and "trade_date" in df.columns:
        unique_dates = df["trade_date"].nunique()
        if unique_dates != 1:
            result.add_warning(f"trade_date不唯一: {unique_dates}个日期")

    return result


def validate_factor_values(
    df: pd.DataFrame,
    factor_name: str,
    expected_count: int = 3000,
) -> ValidationResult:
    """验证因子值数据质量。

    检查项:
    - 覆盖率（非NULL占比）
    - 无inf值
    - 值域合理（zscore后应在[-10, 10]内）

    Args:
        df: 因子值DataFrame，需含 code/value 列。
        factor_name: 因子名称（用于日志）。
        expected_count: 期望的最小股票数。

    Returns:
        ValidationResult。
    """
    result = ValidationResult(row_count=len(df))

    if len(df) == 0:
        result.add_error(f"因子 {factor_name} 数据为空")
        return result

    if "value" not in df.columns:
        result.add_error(f"因子 {factor_name} 缺少 value 列")
        return result

    values = df["value"]

    # 覆盖率
    coverage = values.notna().mean()
    if coverage < 0.5:
        result.add_error(f"因子 {factor_name} 覆盖率仅 {coverage:.1%}")
    elif coverage < 0.8:
        result.add_warning(f"因子 {factor_name} 覆盖率 {coverage:.1%} < 80%")

    # inf检查
    import numpy as np

    inf_count = np.isinf(values.dropna()).sum()
    if inf_count > 0:
        result.add_error(f"因子 {factor_name} 存在 {inf_count} 个inf值")

    # 极端值检查（zscore > 10）
    valid = values.dropna()
    if len(valid) > 0:
        std = valid.std()
        if std > 0:
            max_zscore = ((valid - valid.mean()) / std).abs().max()
            if max_zscore > 10:
                result.add_warning(f"因子 {factor_name} 存在极端值: max_zscore={max_zscore:.1f}")

    if len(df) < expected_count:
        result.add_warning(f"因子 {factor_name} 股票数 {len(df)} < {expected_count}")

    return result
