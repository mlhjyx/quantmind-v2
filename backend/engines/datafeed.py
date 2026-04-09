"""DataFeed — 回测数据多源加载器。

设计文档: DEV_BACKTEST_ENGINE P10，支持三种数据来源:
1. from_database: PostgreSQL读取（生产回测）
2. from_parquet: Parquet文件读取（确定性测试）
3. from_dataframe: 内存DataFrame读取（压力测试/注入）

Engine层规范: 纯计算无IO（from_database除外，它是数据加载边界）。
"""

from datetime import date
from pathlib import Path

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# 回测行情数据必需列
REQUIRED_COLUMNS = [
    "code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",  # P6: 涨跌停判断必需，缺失会导致0成交静默bug
    "volume",
    "amount",
]

# 可选但推荐的列（缺失时发出警告，不阻断）
RECOMMENDED_COLUMNS = [
    "adj_factor",
    "adj_close",
    "turnover_rate",
    "industry_sw1",
    "total_mv",
    "up_limit",
    "down_limit",
    "is_st",
    "is_suspended",
    "is_new_stock",
    "board",
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
        start_date: str | date,
        end_date: str | date,
        universe: list[str] | None = None,
        db_url: str | None = None,
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
            # Step 3-B: SQL修复 — 对齐实际DDL schema + 加adj_close + stock_status
            universe_clause = ""
            params: dict = {
                "start": str(start_date),
                "end": str(end_date),
            }
            if universe:
                universe_clause = "AND k.code = ANY(%(codes)s)"
                params["codes"] = universe

            sql = f"""
                WITH latest_af AS (
                    SELECT DISTINCT ON (code) code, adj_factor AS latest_adj_factor
                    FROM klines_daily
                    WHERE adj_factor IS NOT NULL AND adj_factor > 0
                    ORDER BY code, trade_date DESC
                )
                SELECT
                    k.code,
                    k.trade_date,
                    k.open, k.high, k.low, k.close,
                    k.volume,
                    k.amount,
                    k.pre_close,
                    COALESCE(k.adj_factor, 1.0) AS adj_factor,
                    k.up_limit,
                    k.down_limit,
                    CASE WHEN laf.latest_adj_factor > 0
                         THEN k.close * COALESCE(k.adj_factor, 1.0) / laf.latest_adj_factor
                         ELSE k.close END AS adj_close,
                    db.turnover_rate,
                    db.total_mv,
                    s.industry_sw1,
                    COALESCE(ss.is_st, FALSE) AS is_st,
                    COALESCE(ss.is_suspended, FALSE) AS is_suspended,
                    COALESCE(ss.is_new_stock, FALSE) AS is_new_stock,
                    ss.board
                FROM klines_daily k
                LEFT JOIN daily_basic db
                    ON k.code = db.code AND k.trade_date = db.trade_date
                LEFT JOIN symbols s
                    ON k.code = s.code
                LEFT JOIN latest_af laf
                    ON k.code = laf.code
                LEFT JOIN stock_status_daily ss
                    ON k.code = ss.code AND k.trade_date = ss.trade_date
                WHERE k.trade_date >= %(start)s
                  AND k.trade_date <= %(end)s
                  {universe_clause}
                ORDER BY k.trade_date, k.code
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
        feed._ensure_adj_close()
        return feed

    @classmethod
    def from_parquet(cls, path: str | Path) -> "DataFeed":
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
        if not df.empty and "trade_date" in df.columns and pd.api.types.is_datetime64_any_dtype(df["trade_date"]):
            df["trade_date"] = df["trade_date"].dt.date

        logger.info(
            "DataFeed.from_parquet: %d行, 文件=%s",
            len(df),
            path.name,
        )
        feed = cls(df)
        feed.validate()
        feed._ensure_adj_close()
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
        feed._ensure_adj_close()
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
            if col in self._data.columns and not pd.api.types.is_numeric_dtype(self._data[col]):
                raise DataFeedValidationError(
                    f"列 '{col}' 应为数值类型，实际为 {self._data[col].dtype}"
                )

    def _ensure_adj_close(self) -> None:
        """确保adj_close列存在。从adj_factor计算（Parquet/DataFrame来源需要）。

        from_database()已在SQL中计算adj_close，此方法处理其他来源。
        adj_close = close × adj_factor / latest_adj_factor_per_code
        """
        df = self._data
        if "adj_close" in df.columns or df.empty:
            return

        if "adj_factor" not in df.columns or "close" not in df.columns:
            return  # 无法计算

        # 每只股票最新的adj_factor作为基准
        latest_af = df.groupby("code")["adj_factor"].transform("last")
        # 避免除零
        safe_latest = latest_af.replace(0, 1.0).fillna(1.0)
        df["adj_close"] = df["close"] * df["adj_factor"].fillna(1.0) / safe_latest

        logger.info("DataFeed: adj_close computed from adj_factor (%d rows)", len(df))

    def standardize_units(self) -> None:
        """单位标准化（Step 3-A后DB已统一存元，此方法为空操作）。

        历史: 之前DB存Tushare原始单位(amount千元/total_mv万元)，需要启发式猜测转换。
        Step 3-A统一入库管道后，DataPipeline在入库时完成转换，DB已全部是元。
        保留方法签名保持API兼容。
        """
        pass

    def to_parquet(self, path: str | Path) -> None:
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
