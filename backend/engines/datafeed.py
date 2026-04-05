"""DataFeed — 回测数据多源加载器。

设计文档: DEV_BACKTEST_ENGINE P10，支持三种数据来源:
1. from_database: PostgreSQL读取（生产回测）
2. from_parquet: Parquet文件读取（确定性测试）
3. from_dataframe: 内存DataFrame读取（压力测试/注入）

Engine层规范: 纯计算无IO（from_database除外，它是数据加载边界）。
"""

import structlog
from datetime import date
from pathlib import Path
from typing import Optional, Union

import pandas as pd

logger = structlog.get_logger(__name__)

# 回测行情数据必需列
REQUIRED_COLUMNS = [
    "code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
]

# 可选但推荐的列（缺失时发出警告，不阻断）
RECOMMENDED_COLUMNS = [
    "adj_factor",
    "turnover_rate",
    "industry_sw1",
    "total_mv",
    "pre_close",
    "up_limit",
    "down_limit",
]


class DataFeedValidationError(Exception):
    """DataFeed数据验证失败。"""


class DataFeed:
    """回测数据统一加载器。

    提供统一接口访问行情数据，无论来源是数据库、Parquet文件还是内存DataFrame。

    用法:
        feed = DataFeed.from_parquet("data/snapshot_2024.parquet")
        feed.validate()
        df = feed.df
    """

    def __init__(self, data: pd.DataFrame) -> None:
        self._data = data

    # ────────────────── 工厂方法 ──────────────────

    @classmethod
    def from_database(
        cls,
        start_date: Union[str, date],
        end_date: Union[str, date],
        universe: Optional[list[str]] = None,
        db_url: Optional[str] = None,
    ) -> "DataFeed":
        """从PostgreSQL读取行情数据。

        Args:
            start_date: 回测起始日期。
            end_date: 回测结束日期。
            universe: 股票代码列表（None=全市场）。
            db_url: 数据库连接串（None=从config读取）。

        Returns:
            DataFeed实例。
        """
        import psycopg2

        if db_url is None:
            from app.config import settings
            # Settings用大写DATABASE_URL，去掉asyncpg前缀给psycopg2用
            db_url = settings.DATABASE_URL.replace("+asyncpg", "")

        conn = psycopg2.connect(db_url)
        try:
            # 基础行情 + 日线指标
            universe_clause = ""
            params: dict = {
                "start": str(start_date),
                "end": str(end_date),
            }
            if universe:
                universe_clause = "AND k.ts_code = ANY(%(codes)s)"
                params["codes"] = universe

            sql = f"""
                SELECT
                    k.ts_code AS code,
                    k.trade_date,
                    k.open, k.high, k.low, k.close,
                    k.vol AS volume,
                    k.amount,
                    k.pre_close,
                    COALESCE(af.adj_factor, 1.0) AS adj_factor,
                    db.turnover_rate,
                    db.total_mv,
                    si.industry_sw1,
                    ll.up_limit,
                    ll.down_limit
                FROM klines_daily k
                LEFT JOIN adj_factor af
                    ON k.ts_code = af.ts_code AND k.trade_date = af.trade_date
                LEFT JOIN daily_basic db
                    ON k.ts_code = db.ts_code AND k.trade_date = db.trade_date
                LEFT JOIN symbols_info si
                    ON k.ts_code = si.ts_code
                LEFT JOIN stk_limit ll
                    ON k.ts_code = ll.ts_code AND k.trade_date = ll.trade_date
                WHERE k.trade_date >= %(start)s
                  AND k.trade_date <= %(end)s
                  {universe_clause}
                ORDER BY k.trade_date, k.ts_code
            """
            df = pd.read_sql(sql, conn, params=params)
        finally:
            conn.close()

        # trade_date转换
        if not df.empty and not pd.api.types.is_datetime64_any_dtype(df["trade_date"]):
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        logger.info(
            "DataFeed.from_database: %d行, %d只股票, %s ~ %s",
            len(df),
            df["code"].nunique() if not df.empty else 0,
            start_date,
            end_date,
        )
        feed = cls(df)
        feed.validate()
        return feed

    @classmethod
    def from_parquet(cls, path: Union[str, Path]) -> "DataFeed":
        """从Parquet文件读取行情数据。

        用途: 确定性测试数据快照，保证同一输入永远产出同一结果。

        Args:
            path: Parquet文件路径。

        Returns:
            DataFeed实例。
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Parquet文件不存在: {path}")

        df = pd.read_parquet(path)

        # trade_date可能被序列化为Timestamp，转回date
        if not df.empty and "trade_date" in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df["trade_date"]):
                df["trade_date"] = df["trade_date"].dt.date

        logger.info(
            "DataFeed.from_parquet: %d行, 文件=%s",
            len(df),
            path.name,
        )
        feed = cls(df)
        feed.validate()
        return feed

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> "DataFeed":
        """从内存DataFrame读取（压力测试/合成数据注入）。

        Args:
            df: 已构造好的DataFrame，需包含必需列。

        Returns:
            DataFeed实例。
        """
        feed = cls(df.copy())
        feed.validate()
        return feed

    # ────────────────── 属性 ──────────────────

    @property
    def df(self) -> pd.DataFrame:
        """返回底层DataFrame。"""
        return self._data

    @property
    def date_range(self) -> tuple:
        """返回(start_date, end_date)。"""
        if self._data.empty:
            return (None, None)
        dates = self._data["trade_date"]
        return (dates.min(), dates.max())

    @property
    def codes(self) -> list[str]:
        """返回股票代码列表（去重排序）。"""
        if self._data.empty:
            return []
        return sorted(self._data["code"].unique().tolist())

    # ────────────────── 方法 ──────────────────

    def get_daily(self, trade_date) -> pd.DataFrame:
        """返回单日截面数据。

        Args:
            trade_date: 交易日期。

        Returns:
            该日所有股票的行情数据。
        """
        result: pd.DataFrame = self._data.loc[
            self._data["trade_date"] == trade_date
        ].copy()
        return result

    def validate(self) -> None:
        """检查必需列是否存在、数据类型是否正确。

        Raises:
            DataFeedValidationError: 缺少必需列或数据类型错误。
        """
        if self._data.empty:
            return

        # 1. 必需列检查
        missing = [c for c in REQUIRED_COLUMNS if c not in self._data.columns]
        if missing:
            raise DataFeedValidationError(
                f"缺少必需列: {missing}。"
                f"必需列: {REQUIRED_COLUMNS}"
            )

        # 2. 推荐列警告
        missing_rec = [c for c in RECOMMENDED_COLUMNS if c not in self._data.columns]
        if missing_rec:
            logger.warning("DataFeed缺少推荐列(不阻断): %s", missing_rec)

        # 3. 数值列类型检查
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in self._data.columns:
                if not pd.api.types.is_numeric_dtype(self._data[col]):
                    raise DataFeedValidationError(
                        f"列 '{col}' 应为数值类型，实际为 {self._data[col].dtype}"
                    )

    def to_parquet(self, path: Union[str, Path]) -> None:
        """将数据导出为Parquet文件（用于创建测试快照）。

        Args:
            path: 输出Parquet文件路径。
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # trade_date转Timestamp以便Parquet序列化
        df_out = self._data.copy()
        if not df_out.empty and "trade_date" in df_out.columns:
            df_out["trade_date"] = pd.to_datetime(df_out["trade_date"])

        df_out.to_parquet(path, index=False, engine="pyarrow")
        logger.info("DataFeed导出Parquet: %d行 → %s", len(df_out), path)
