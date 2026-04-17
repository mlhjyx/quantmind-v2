"""MVP 2.1a Framework #1 Data — BaseDataSource Template method + validation helpers.

3 concrete fetcher (Tushare / Baostock / QMT) 继承本类, 只实现 `_fetch_raw`,
validation 逻辑由本类公共 helpers 处理 (DRY).

关联 MVP 1.1:
  - 继承 `backend.platform.data.interface.DataSource` (ABC)
  - 返 `ValidationResult` (MVP 1.1 dataclass)
  - 消费 `DataContract` (MVP 1.1 dataclass)

职责边界 (设计稿 §D4):
  - `BaseDataSource.validate` = 拉取后入库前 (schema + PK + NaN + value range)
  - `DataPipeline.ingest` = 入库 (rename + L1 sanity + FK 过滤 + upsert)

MVP 2.1b 扩展路径 (3 concrete fetcher):
  - `backend/app/data_fetcher/fetch_base_data.py` 598 行 → `TushareDataSource(BaseDataSource)`
  - `scripts/fetch_minute_bars.py` 280 行 → `BaostockDataSource(BaseDataSource)`
  - `scripts/qmt_data_service.py` 274 行 → `QMTDataSource(BaseDataSource)`

Usage:
    class MyDataSource(BaseDataSource):
        def _fetch_raw(self, contract, since):
            df = tushare_api.daily(since=since)
            return df  # 单位已归一 (元 不是 万元)

        # 可选 override: 加业务特定 range 检查
        def _check_value_ranges(self, df, contract):
            issues = []
            if "close" in df.columns and (df["close"] < 0).any():
                issues.append("close 列含负值")
            return issues
"""
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from backend.platform.data.interface import (
    DataContract,
    DataSource,
    ValidationResult,
)

if TYPE_CHECKING:
    import pandas as pd


# ---------- 错误类型 ----------


class ContractViolation(RuntimeError):  # noqa: N818 — 语义名, Platform 同策略 (MVP 1.3c OnboardingBlocked / MVP 1.4 ADRNotFound)
    """数据与 Contract 不匹配 (schema / PK / NaN / range)."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(f"Contract validation failed with {len(issues)} issues: {issues}")


# ---------- Base class ----------


class BaseDataSource(DataSource):
    """DataSource 抽象基类 — Template method pattern.

    子类只实现 `_fetch_raw(contract, since) -> DataFrame` (原始拉取, 单位归一).
    公共逻辑 (validate, fetch orchestration) 由本类提供.

    Args:
      nan_ratio_threshold: NaN 比例警戒阈值 (默认 0.1 = 10%).
        子类可在 __init__ 覆盖, e.g. super().__init__(nan_ratio_threshold=0.05).
    """

    def __init__(self, nan_ratio_threshold: float = 0.1) -> None:
        if not 0.0 <= nan_ratio_threshold <= 1.0:
            raise ValueError(
                f"nan_ratio_threshold 必须在 [0.0, 1.0], 现: {nan_ratio_threshold}"
            )
        self._nan_ratio_threshold = nan_ratio_threshold

    # ---------- Template method ----------

    def fetch(self, contract: DataContract, since) -> pd.DataFrame:
        """公共 fetch 入口: _fetch_raw → validate → raise if invalid.

        Raises:
          ContractViolation: validation.passed=False 时自动 raise (铁律 33 fail-loud).
        """
        df = self._fetch_raw(contract, since)
        result = self.validate(df, contract)
        if not result.passed:
            raise ContractViolation(result.issues)
        return df

    @abstractmethod
    def _fetch_raw(self, contract: DataContract, since) -> pd.DataFrame:
        """子类必实现: 从外部源拉取原始数据 (已单位归一, 未 validate)."""

    # ---------- validate (MVP 1.1 DataSource ABC 要求) ----------

    def validate(self, df: pd.DataFrame, contract: DataContract) -> ValidationResult:
        """4 大 check 聚合: schema + PK + NaN + value_ranges.

        各 helper 返 issues list (空 = 通过). 本方法组合成 ValidationResult.
        """
        issues: list[str] = []
        issues.extend(self._check_schema(df, contract))
        issues.extend(self._check_primary_key(df, contract))
        issues.extend(self._check_nan_ratio(df, contract))
        issues.extend(self._check_value_ranges(df, contract))

        return ValidationResult(
            passed=len(issues) == 0,
            row_count=len(df),
            issues=issues,
            metadata={
                "validator": self.__class__.__name__,
                "nan_ratio_threshold": self._nan_ratio_threshold,
            },
        )

    # ---------- Helpers (protected, 子类可 override 扩展) ----------

    def _check_schema(self, df: pd.DataFrame, contract: DataContract) -> list[str]:
        """检查 df 列名覆盖 contract.schema 所有 required 列.

        简化版: 只检查列存在性, 不做 dtype 严格校验 (pandas/PG 单位格式不统一, 留 2.1c 集成).
        """
        issues: list[str] = []
        required = set(contract.schema.keys())
        present = set(df.columns)
        missing = required - present
        if missing:
            issues.append(
                f"[schema] missing required columns: {sorted(missing)} "
                f"(contract={contract.name})"
            )
        return issues

    def _check_primary_key(self, df: pd.DataFrame, contract: DataContract) -> list[str]:
        """检查 primary_key 组合无重复."""
        issues: list[str] = []
        pk_cols = list(contract.primary_key)
        missing_pk = [c for c in pk_cols if c not in df.columns]
        if missing_pk:
            issues.append(f"[pk] PK columns not in df: {missing_pk}")
            return issues  # 缺列就不能检重复

        if df.empty:
            return issues
        duped = df.duplicated(subset=pk_cols, keep=False)
        n_duped = int(duped.sum())
        if n_duped > 0:
            issues.append(
                f"[pk] {n_duped} rows violate primary_key uniqueness on {pk_cols}"
            )
        return issues

    def _check_nan_ratio(
        self, df: pd.DataFrame, contract: DataContract
    ) -> list[str]:
        """检查每列 NaN 比例 ≤ nan_ratio_threshold.

        PK 列 NaN 不允许 (100% 强制), 其他列看 threshold.
        """
        issues: list[str] = []
        if df.empty:
            return issues

        pk_cols = set(contract.primary_key)
        total = len(df)

        for col in contract.schema:
            if col not in df.columns:
                continue  # _check_schema 已报
            n_nan = int(df[col].isna().sum())
            if col in pk_cols and n_nan > 0:
                issues.append(f"[nan] PK column {col!r} has {n_nan} NaN values (not allowed)")
            else:
                ratio = n_nan / total
                if ratio > self._nan_ratio_threshold:
                    issues.append(
                        f"[nan] column {col!r} NaN ratio {ratio:.2%} > "
                        f"threshold {self._nan_ratio_threshold:.2%}"
                    )
        return issues

    def _check_value_ranges(
        self, df: pd.DataFrame, contract: DataContract
    ) -> list[str]:
        """默认 no-op — 子类 override 实现业务特定 range 检查.

        e.g. TushareDataSource 可检查 close > 0, QMTDataSource 可检查 price >= 0.01.
        """
        del df, contract  # unused in base
        return []


__all__ = [
    "BaseDataSource",
    "ContractViolation",
]
