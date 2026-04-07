"""Qlib StaticDataLoader适配器 — TimescaleDB factor_values → Qlib模型输入。

Phase 4: 连接QuantMind数据层与Qlib ML模型库(TRA/ALSTM/LightGBM)。
通过StaticDataLoader避免依赖Qlib自有数据目录(qlib.init不需要)。

用法:
    from engines.qlib_adapter import QuantMindQlibAdapter
    adapter = QuantMindQlibAdapter()
    loader = adapter.to_static_loader(factors, start, end, conn)
    # loader可直接传给Qlib DatasetH
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
import structlog

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class QuantMindQlibAdapter:
    """从TimescaleDB/Parquet加载因子数据，转换为Qlib StaticDataLoader格式。"""

    def load_factor_data(
        self,
        factors: list[str],
        start: date,
        end: date,
        conn,
    ) -> pd.DataFrame:
        """查询factor_values表，返回Qlib格式的宽表DataFrame。

        Args:
            factors: 因子名列表。
            start/end: 日期范围。
            conn: psycopg2连接。

        Returns:
            MultiIndex DataFrame: (datetime, instrument) × factor_columns
        """
        placeholders = ",".join(["%s"] * len(factors))
        df = pd.read_sql(
            f"""SELECT code AS instrument, trade_date AS datetime,
                       factor_name, zscore AS value
                FROM factor_values
                WHERE factor_name IN ({placeholders})
                  AND trade_date BETWEEN %s AND %s""",
            conn,
            params=(*factors, start, end),
        )

        if df.empty:
            logger.warning("factor_values查询为空: factors=%s, %s~%s", factors, start, end)
            return pd.DataFrame()

        # 长表 → 宽表: (datetime, instrument) × factors
        wide = df.pivot_table(
            index=["datetime", "instrument"],
            columns="factor_name",
            values="value",
        )
        wide.columns.name = None  # 清除列名层级
        logger.info(
            "加载因子数据: %d因子, %d行, %s~%s",
            len(factors),
            len(wide),
            start,
            end,
        )
        return wide

    def to_static_loader(
        self,
        factors: list[str],
        start: date,
        end: date,
        conn,
    ):
        """返回Qlib StaticDataLoader实例。

        StaticDataLoader接受预计算的DataFrame，不需要qlib.init()。
        可直接传给DatasetH用于模型训练/预测。

        Returns:
            qlib.data.dataset.loader.StaticDataLoader实例。
            如果qlib未安装返回None。
        """
        try:
            from qlib.data.dataset.loader import StaticDataLoader
        except ImportError:
            logger.error("pyqlib未安装, 无法创建StaticDataLoader")
            return None

        df = self.load_factor_data(factors, start, end, conn)
        if df.empty:
            return None

        return StaticDataLoader(config=df)
