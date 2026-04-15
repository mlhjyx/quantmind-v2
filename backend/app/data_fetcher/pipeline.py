"""统一数据入库管道 — 验证 + 单位转换 + Upsert。

所有外部数据入库必须经过DataPipeline.ingest()。
Contract定义在contracts.py中。

设计原则:
- 坏行被排除+记录原因，不阻塞整批
- 基础设施错误(连接失败/SQL错误)正常raise
- 单位转换在此完成(千元→元等)，DB存储标准单位
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import structlog
from psycopg2.extras import execute_values

if TYPE_CHECKING:
    import psycopg2.extensions

from app.data_fetcher.contracts import TableContract

logger = structlog.get_logger(__name__)


@dataclass
class IngestResult:
    """入库结果。"""

    table: str
    total_rows: int
    valid_rows: int
    rejected_rows: int
    upserted_rows: int
    reject_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.upserted_rows > 0


class DataPipeline:
    """统一数据入库管道。

    用法:
        pipeline = DataPipeline(conn)
        result = pipeline.ingest(df, KLINES_DAILY)
        if result.rejected_rows > 0:
            logger.warning("rejected: %s", result.reject_reasons)
    """

    def __init__(self, conn: psycopg2.extensions.connection | None = None):
        self._conn = conn
        self._own_conn = conn is None
        self._symbols_cache: set[str] | None = None

    @property
    def conn(self) -> psycopg2.extensions.connection:
        if self._conn is None:
            from app.data_fetcher.data_loader import get_sync_conn

            self._conn = get_sync_conn()
            self._own_conn = True
        return self._conn

    def close(self) -> None:
        """关闭自建的连接。"""
        if self._own_conn and self._conn is not None:
            self._conn.close()
            self._conn = None

    # ─── 主入口 ────────────────────────────────────────────

    def ingest(self, df: pd.DataFrame, contract: TableContract) -> IngestResult:
        """验证 + 单位转换 + Upsert。

        Steps:
        1. rename_map (ts_code→code等)
        2. 列对齐 (保留contract列，补缺失nullable列)
        3. 单位转换 (千元→元等)
        4. 逐列验证 (PK非空, 值域, inf/NaN→None)
        5. FK过滤 (symbols.code)
        6. Upsert (ON CONFLICT DO UPDATE)
        """
        if df.empty:
            return IngestResult(contract.table_name, 0, 0, 0, 0)

        total = len(df)
        df = df.copy()

        # 1. rename
        if contract.rename_map:
            df = df.rename(columns=contract.rename_map)

        # 2. 列对齐
        contract_cols = list(contract.columns.keys())
        # 只保留contract定义的列
        available = [c for c in contract_cols if c in df.columns]
        # 补缺失的nullable列
        for col in contract_cols:
            if col not in df.columns:
                spec = contract.columns[col]
                if spec.nullable:
                    df[col] = None
                    available.append(col)
                # 非nullable缺失列: 稍后在validate中处理

        df = df[available].copy()

        # 3. 单位转换
        if not contract.skip_unit_conversion:
            df = self._convert_units(df, contract)

        # 4. 验证
        df, reject_reasons = self._validate(df, contract)
        rejected = total - len(df)

        if df.empty:
            return IngestResult(contract.table_name, total, 0, rejected, 0, reject_reasons)

        # 5. FK过滤
        if contract.fk_filter_col and contract.fk_filter_col in df.columns:
            before_fk = len(df)
            df = self._fk_filter(df, contract.fk_filter_col)
            fk_dropped = before_fk - len(df)
            if fk_dropped > 0:
                reject_reasons["fk_not_in_symbols"] = fk_dropped
                rejected += fk_dropped

        if df.empty:
            return IngestResult(contract.table_name, total, 0, rejected, 0, reject_reasons)

        # 6. Upsert
        upserted = self._upsert(df, contract)

        return IngestResult(
            table=contract.table_name,
            total_rows=total,
            valid_rows=len(df),
            rejected_rows=rejected,
            upserted_rows=upserted,
            reject_reasons=reject_reasons,
        )

    # ─── 单位转换 ──────────────────────────────────────────

    def _convert_units(self, df: pd.DataFrame, contract: TableContract) -> pd.DataFrame:
        """按Contract定义转换单位。"""
        for col_name, spec in contract.columns.items():
            factor = spec.conversion_factor
            if factor is not None and col_name in df.columns:
                df[col_name] = pd.to_numeric(df[col_name], errors="coerce") * factor
        return df

    # ─── 验证 ──────────────────────────────────────────────

    def _validate(
        self, df: pd.DataFrame, contract: TableContract
    ) -> tuple[pd.DataFrame, dict[str, int]]:
        """向量化行级验证。返回(valid_df, reject_counts)。"""
        reject_reasons: dict[str, int] = {}
        valid_mask = pd.Series(True, index=df.index)

        for col_name, spec in contract.columns.items():
            if col_name not in df.columns:
                if not spec.nullable:
                    # 必须列完全缺失 → 全部拒绝
                    reject_reasons[f"missing_required_{col_name}"] = len(df)
                    return df.iloc[0:0], reject_reasons
                continue

            col = df[col_name]

            # PK非空检查
            if not spec.nullable:
                null_mask = col.isna()
                null_count = null_mask.sum()
                if null_count > 0:
                    reject_reasons[f"null_{col_name}"] = int(null_count)
                    valid_mask &= ~null_mask

            # 数值列: inf/NaN → None, 类型强转
            if spec.dtype in ("float", "int"):
                numeric = pd.to_numeric(col, errors="coerce")
                # inf → NaN → 后续变None
                numeric = numeric.replace([np.inf, -np.inf], np.nan)
                df[col_name] = numeric

                # 值域检查
                if spec.min_val is not None:
                    below = numeric < spec.min_val
                    # 忽略NaN(nullable列允许NaN)
                    below = below.fillna(False)
                    below_count = below.sum()
                    if below_count > 0:
                        reject_reasons[f"{col_name}_below_{spec.min_val}"] = int(below_count)
                        valid_mask &= ~below

                if spec.max_val is not None:
                    above = numeric > spec.max_val
                    above = above.fillna(False)
                    above_count = above.sum()
                    if above_count > 0:
                        reject_reasons[f"{col_name}_above_{spec.max_val}"] = int(above_count)
                        valid_mask &= ~above

        # 应用mask
        valid_df = df[valid_mask].reset_index(drop=True)

        # NaN → None (psycopg2需要Python None不是numpy NaN)
        valid_df = valid_df.where(pd.notna(valid_df), other=None)

        return valid_df, reject_reasons

    # ─── FK过滤 ─────────────────────────────────────────────

    def _fk_filter(self, df: pd.DataFrame, fk_col: str) -> pd.DataFrame:
        """过滤FK列不在symbols表中的行。"""
        if self._symbols_cache is None:
            with self.conn.cursor() as cur:
                cur.execute("SELECT code FROM symbols")
                self._symbols_cache = {r[0] for r in cur.fetchall()}
            logger.info("Loaded %d valid codes from symbols", len(self._symbols_cache))

        mask = df[fk_col].isin(self._symbols_cache)
        return df[mask].reset_index(drop=True)

    # ─── Upsert ─────────────────────────────────────────────

    def _build_upsert_sql(self, contract: TableContract, columns: list[str]) -> str:
        """从Contract自动生成INSERT ... ON CONFLICT DO UPDATE SQL。"""
        pk = list(contract.pk_columns)
        non_pk = [c for c in columns if c not in pk]

        cols_str = ", ".join(columns)
        conflict_str = ", ".join(pk)
        update_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in non_pk)

        sql = f"INSERT INTO {contract.table_name} ({cols_str}) VALUES %s"
        if update_str:
            sql += f" ON CONFLICT ({conflict_str}) DO UPDATE SET {update_str}"
        else:
            sql += f" ON CONFLICT ({conflict_str}) DO NOTHING"

        return sql

    def _upsert(self, df: pd.DataFrame, contract: TableContract) -> int:
        """执行upsert，返回行数。"""
        columns = [c for c in contract.columns if c in df.columns]
        sql = self._build_upsert_sql(contract, columns)

        # DataFrame → list of tuples, NaN→None for psycopg2 (铁律29)
        # float64列中pd.where(other=None)无法存储None(被转回NaN),
        # 因此在tuple化时显式转换
        records = [
            tuple(None if pd.isna(v) else v for v in row)
            for row in df[columns].itertuples(index=False, name=None)
        ]

        try:
            with self.conn.cursor() as cur:
                execute_values(cur, sql, records, page_size=10000)
            self.conn.commit()
            logger.info(
                "Upserted %d rows to %s",
                len(records),
                contract.table_name,
            )
            return len(records)
        except Exception:
            self.conn.rollback()
            raise
