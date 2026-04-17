"""Framework #1 Data — 统一数据源 / 契约 / 访问层 / 缓存.

目标: 从源头到消费统一数据契约, 消除 "数据改了没人知道" / "缓存过期" / "单位漂移".

关联铁律:
  - 17: 数据入库必须通过 DataPipeline (DataAccessLayer 是唯一读入口)
  - 30: 缓存一致性必须保证 (FactorCache 的 Cache Coherency Protocol)
  - 31: Engine 层纯计算 (Data 层独立, 承担所有 IO)
  - 34: 配置 single source of truth

实施时机 (Wave 2):
  - MVP 2.1 Data Framework: DataSource 三实现 (Tushare/Baostock/QMT)
  - MVP 2.2 Data Lineage: DataContract + lineage 字段
  - DataAccessLayer: MVP 1.3 Factor Framework 先落地读路径
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class DataContract:
    """数据契约 — 描述一张表 / 一个数据源的 schema + 单位 + 约束.

    Args:
      name: 契约名 (e.g. "klines_daily", "factor_values")
      version: 版本号 (变更 schema 需 bump)
      schema: 列名 → 类型 / 单位 映射 (e.g. {"close": "float64 元", "vol": "int64 手"})
      primary_key: 主键列表 (e.g. ["symbol_id", "trade_date"])
      source: 源头系统 (e.g. "tushare", "baostock", "qmt")
      unit_convention: 单位约定 (e.g. "元" vs "万元", "%" vs "decimal")
    """

    name: str
    version: str
    schema: dict[str, str]
    primary_key: tuple[str, ...]
    source: str
    unit_convention: dict[str, str]


@dataclass(frozen=True)
class ValidationResult:
    """DataSource.validate 结果.

    Args:
      passed: 是否通过所有校验
      row_count: 实际行数
      issues: 失败原因列表 (每条为人类可读字符串)
      metadata: 扩展信息 (如 NaN 比例 / 单位检查)
    """

    passed: bool
    row_count: int
    issues: list[str]
    metadata: dict[str, Any]


class DataSource(ABC):
    """数据源抽象.

    所有外部数据拉取 (Tushare / Baostock / QMT) 必须实现本接口.
    禁止 Application 跨过 DataSource 直接调用三方 SDK.

    关联铁律 17: 拉取后必须走 DataPipeline 入库.
    """

    @abstractmethod
    def fetch(self, contract: DataContract, since: date) -> pd.DataFrame:
        """从数据源拉取增量数据.

        Args:
          contract: 数据契约 (定义 schema + 单位)
          since: 起始日期 (inclusive, 交易日)

        Returns:
          DataFrame, 列对齐 contract.schema, 单位已归一

        Raises:
          DataSourceError: 源不可用 / auth 失败
          ContractViolation: 返回 schema 不匹配 contract
        """

    @abstractmethod
    def validate(self, df: pd.DataFrame, contract: DataContract) -> ValidationResult:
        """校验 df 符合 contract (单位 / 值域 / 主键唯一).

        Args:
          df: 待校验数据
          contract: 契约

        Returns:
          ValidationResult, passed=False 时 issues 列出所有问题
        """


class DataAccessLayer(ABC):
    """Platform 唯一数据读入口.

    禁止 Application / Engine 裸 read_sql / 直接访问 factor_values 表.
    所有读路径必须经 DAL, 由 DAL 统一决定查 DB 还是命中缓存 (FactorCache).

    关联铁律 17 + 31.
    """

    @abstractmethod
    def read_factor(
        self,
        factor: str,
        start: date,
        end: date,
        column: str = "neutral_value",
    ) -> pd.DataFrame:
        """读单因子时间序列.

        Args:
          factor: 因子名 (必须在 FactorRegistry 中注册)
          start: 起始日 (inclusive)
          end: 终止日 (inclusive)
          column: "raw_value" / "neutral_value" (默认 neutral, 铁律 19)

        Returns:
          DataFrame(columns=[symbol_id, trade_date, value])

        Raises:
          FactorNotFound: factor 未注册
          CacheCoherencyError: 缓存与 DB max_date 不一致
        """

    @abstractmethod
    def read_ohlc(
        self,
        codes: list[str],
        start: date,
        end: date,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        """读价量 OHLCV 数据.

        Args:
          codes: 证券代码列表 (带后缀, e.g. "600519.SH")
          start: 起始日
          end: 终止日
          adjusted: 是否复权 (默认 True, 用 adj_close)

        Returns:
          DataFrame(columns=[code, trade_date, open, high, low, close, volume, amount])
        """

    @abstractmethod
    def read_fundamentals(
        self,
        codes: list[str],
        fields: list[str],
        as_of: date,
    ) -> pd.DataFrame:
        """读基本面数据 (PIT, point-in-time).

        Args:
          codes: 证券代码列表
          fields: 字段名 (e.g. ["pe_ttm", "pb", "dv_ttm"])
          as_of: PIT 日期 (返回此日及之前最新 ann_date 的数据)

        Returns:
          DataFrame(columns=[code, ann_date, end_date, <fields>])

        Raises:
          PITViolation: 若字段无 ann_date (lookahead bias)
        """


class FactorCacheProtocol(ABC):
    """因子缓存协议 (Parquet / Redis 双层).

    DAL 内部调用, Application 不直接用.
    Cache Coherency Protocol:
      - 每次 read 前对比 DB max_date vs cache max_date
      - 不一致: invalidate + refill
      - TTL 兜底 (默认 24h)
    """

    @abstractmethod
    def get(self, factor: str, start: date, end: date, column: str) -> pd.DataFrame | None:
        """尝试从缓存取.

        Returns:
          DataFrame 若命中, None 若 miss 或 stale
        """

    @abstractmethod
    def put(self, factor: str, df: pd.DataFrame, column: str) -> None:
        """写入缓存.

        Args:
          factor: 因子名
          df: 数据 (必须含 symbol_id / trade_date / value)
          column: "raw_value" / "neutral_value"
        """

    @abstractmethod
    def invalidate(self, factor: str) -> None:
        """失效指定因子的所有缓存 (Cache Coherency 触发)."""
