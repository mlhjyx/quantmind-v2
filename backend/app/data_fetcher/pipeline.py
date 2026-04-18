"""统一数据入库管道 — 验证 + 单位转换 + Upsert。

所有外部数据入库必须经过DataPipeline.ingest()。
Contract定义在contracts.py中。

设计原则:
- 坏行被排除+记录原因，不阻塞整批
- 基础设施错误(连接失败/SQL错误)正常raise
- 单位转换在此完成(千元→元等)，DB存储标准单位
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import structlog
from psycopg2.extras import Json, execute_values, register_uuid

if TYPE_CHECKING:
    import psycopg2.extensions

    from backend.platform.data.lineage import Lineage

from app.data_fetcher.contracts import TableContract

# MVP 2.2: 模块级幂等注册, 让 psycopg2 自动转换 uuid.UUID ↔ PG UUID
# (置于所有 import 之后, 避免 ruff E402 "Module level import not at top of file")
register_uuid()

logger = structlog.get_logger(__name__)


def _is_null(v) -> bool:
    """安全 null 判定 (MVP 2.2).

    原 pipeline 用 `pd.isna(v)`, 对 dict/list 非 scalar 输入会 TypeError.
    本 helper 白名单短路: None → True, 容器/UUID/str → False, 其他 fallback pd.isna.
    """
    if v is None:
        return True
    if isinstance(v, (dict, list, str, _uuid.UUID)):
        return False
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _prepare_cell(v, dtype: str):
    """_upsert tuple 构造前的 type-aware null 处理 + JSON wrap (MVP 2.2).

    - jsonb: 用 psycopg2 `Json(...)` adapter 包装 dict/list → JSONB 字面量
    - uuid / text / 其他: 直通 (register_uuid 已注册 UUID 适配器)
    """
    if _is_null(v):
        return None
    if dtype == "jsonb":
        return Json(v)
    return v


def _to_jsonable_scalar(v):
    """PK 单值的 JSON safe 归一化 (MVP 2.2 Sub2 内部).

    UUID→str / date/datetime→isoformat / numpy scalar→python scalar / 其他直通.
    """
    if v is None:
        return None
    if isinstance(v, _uuid.UUID):
        return str(v)
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except TypeError:
            pass
    # numpy scalar 归一
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    return v


@dataclass
class IngestResult:
    """入库结果。

    MVP 2.2 Sub2: `lineage_id` 字段追加, 默认 None (不传 lineage 时保持向后兼容).
    传入 Lineage 时, DataPipeline.ingest 自动补 outputs + write_lineage + 回填本字段.
    """

    table: str
    total_rows: int
    valid_rows: int
    rejected_rows: int
    upserted_rows: int
    reject_reasons: dict[str, int] = field(default_factory=dict)
    lineage_id: _uuid.UUID | None = None

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

    def ingest(
        self,
        df: pd.DataFrame,
        contract: TableContract,
        lineage: Lineage | None = None,
    ) -> IngestResult:
        """验证 + 单位转换 + Upsert。

        Steps:
        1. rename_map (ts_code→code等)
        2. 列对齐 (保留contract列，补缺失nullable列)
        3. 单位转换 (千元→元等)
        4. 逐列验证 (PK非空, 值域, inf/NaN→None)
        5. FK过滤 (symbols.code)
        6. Upsert (ON CONFLICT DO UPDATE)
        7. (MVP 2.2 Sub2) lineage 传入 → 自动补 outputs 引用 + write_lineage + 回填 lineage_id

        Args:
            df: 输入数据
            contract: 表契约
            lineage: 可选血缘对象. None 保持向后兼容 (零改动其他调用方).
                     传入时自动从 upsert 后的 valid_df 提取 PK 列为 outputs LineageRef.
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

        # 3.5 P1-3: L1 sanity check (仅 L1 核心表, 不影响 L2/L3)
        sanity_rejects: dict[str, int] = {}
        if contract.table_name in ("klines_daily", "daily_basic", "moneyflow_daily", "minute_bars"):
            df, sanity_rejects = self._sanity_check_l1(df, contract.table_name)

        # 4. 验证
        df, reject_reasons = self._validate(df, contract)
        # merge sanity reasons
        for k, v in sanity_rejects.items():
            reject_reasons[k] = reject_reasons.get(k, 0) + v
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

        # 7. MVP 2.2 Sub2: lineage 埋点 (传入才执行, 不传保持向后兼容)
        lineage_id: _uuid.UUID | None = None
        if lineage is not None and upserted > 0:
            lineage_id = self._record_lineage(lineage, df, contract)

        return IngestResult(
            table=contract.table_name,
            total_rows=total,
            valid_rows=len(df),
            rejected_rows=rejected,
            upserted_rows=upserted,
            reject_reasons=reject_reasons,
            lineage_id=lineage_id,
        )

    # ─── 单位转换 ──────────────────────────────────────────

    def _convert_units(self, df: pd.DataFrame, contract: TableContract) -> pd.DataFrame:
        """按Contract定义转换单位。"""
        for col_name, spec in contract.columns.items():
            factor = spec.conversion_factor
            if factor is not None and col_name in df.columns:
                df[col_name] = pd.to_numeric(df[col_name], errors="coerce") * factor
        return df

    # ─── L1 Sanity Check (P1-3) ──────────────────────────────

    def _sanity_check_l1(
        self, df: pd.DataFrame, table_name: str
    ) -> tuple[pd.DataFrame, dict[str, int]]:
        """L1 入库 sanity check (DATA_SYSTEM_V1 P1-3).

        拒绝明显错误数据, 保留 good rows.

        规则:
          - 价格合理性: close>0, high>=max(open,close), low<=min(open,close), high>=low
          - 量合理性: volume>=0, amount>=0
          - 异常波动: |close/open - 1| < 0.5 (A股单日最大 ±20%, 超 50% 必 bug)

        Returns:
            (df_valid, {reason: count})
        """
        if df.empty:
            return df, {}

        reject_reasons: dict[str, int] = {}
        valid_mask = pd.Series(True, index=df.index)

        # 辅助: 安全 coerce 数值
        def _num(col: str) -> pd.Series | None:
            if col not in df.columns:
                return None
            return pd.to_numeric(df[col], errors="coerce")

        # ── 价格合理性 ──
        close = _num("close")
        open_ = _num("open")
        high = _num("high")
        low = _num("low")
        if close is not None:
            bad = (close <= 0).fillna(False)
            if bad.any():
                reject_reasons["sanity_close_le_zero"] = int(bad.sum())
                valid_mask &= ~bad
        if high is not None and low is not None:
            bad = (high < low).fillna(False)
            if bad.any():
                reject_reasons["sanity_high_lt_low"] = int(bad.sum())
                valid_mask &= ~bad
        if high is not None and open_ is not None and close is not None:
            bad = (high < pd.concat([open_, close], axis=1).max(axis=1)).fillna(False)
            if bad.any():
                reject_reasons["sanity_high_lt_open_close"] = int(bad.sum())
                valid_mask &= ~bad
        if low is not None and open_ is not None and close is not None:
            bad = (low > pd.concat([open_, close], axis=1).min(axis=1)).fillna(False)
            if bad.any():
                reject_reasons["sanity_low_gt_open_close"] = int(bad.sum())
                valid_mask &= ~bad

        # ── 量/金额合理性 ──
        volume = _num("volume")
        amount = _num("amount")
        if volume is not None:
            bad = (volume < 0).fillna(False)
            if bad.any():
                reject_reasons["sanity_volume_negative"] = int(bad.sum())
                valid_mask &= ~bad
        if amount is not None:
            bad = (amount < 0).fillna(False)
            if bad.any():
                reject_reasons["sanity_amount_negative"] = int(bad.sum())
                valid_mask &= ~bad

        # ── 异常波动 (日 K 才检查) ──
        if table_name == "klines_daily" and close is not None and open_ is not None:
            ret = (close / open_ - 1).abs()
            bad = (ret > 0.5).fillna(False)
            if bad.any():
                reject_reasons["sanity_abnormal_return_gt_50pct"] = int(bad.sum())
                valid_mask &= ~bad

        if not valid_mask.all():
            df = df[valid_mask].copy()
            logger.warning(
                "[sanity] %s 拒绝 %d 行 | %s",
                table_name,
                (~valid_mask).sum(),
                reject_reasons,
            )
        return df, reject_reasons

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

            # MVP 2.2: UUID 验证 (accept UUID | str, normalize → uuid.UUID; 非法 str → reject)
            elif spec.dtype == "uuid":

                def _try_uuid_strict(v):
                    """Return (valid, normalized_value)."""
                    if _is_null(v):
                        return True, None
                    if isinstance(v, _uuid.UUID):
                        return True, v
                    if isinstance(v, str):
                        try:
                            return True, _uuid.UUID(v)
                        except (ValueError, AttributeError):
                            return False, None
                    return False, None

                results = col.apply(_try_uuid_strict)
                invalid_mask = results.apply(lambda t: not t[0])
                df[col_name] = results.apply(lambda t: t[1])
                if invalid_mask.any():
                    reject_reasons[f"invalid_uuid_{col_name}"] = int(invalid_mask.sum())
                    valid_mask &= ~invalid_mask

            # MVP 2.2: JSONB 验证 (accept dict | list | None; 其他 reject)
            elif spec.dtype == "jsonb":

                def _try_jsonb_strict(v):
                    if _is_null(v):
                        return True, None
                    if isinstance(v, (dict, list)):
                        return True, v
                    return False, None

                results = col.apply(_try_jsonb_strict)
                invalid_mask = results.apply(lambda t: not t[0])
                df[col_name] = results.apply(lambda t: t[1])
                if invalid_mask.any():
                    reject_reasons[f"invalid_jsonb_{col_name}"] = int(invalid_mask.sum())
                    valid_mask &= ~invalid_mask

        # 应用mask
        valid_df = df[valid_mask].reset_index(drop=True)

        # MVP 2.2: NaN → None 收紧到仅 numeric 列
        # (原全 df where(pd.notna, None) 在 object 列含 dict/list 时崩 vectorize)
        numeric_cols = [
            c
            for c, s in contract.columns.items()
            if s.dtype in ("float", "int") and c in valid_df.columns
        ]
        if numeric_cols:
            valid_df[numeric_cols] = valid_df[numeric_cols].where(
                pd.notna(valid_df[numeric_cols]), other=None
            )

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

        # DataFrame → list of tuples, type-aware 处理 (MVP 2.2)
        # - numeric NaN → None (psycopg2 需 Python None 不是 numpy NaN, 铁律 29)
        # - jsonb dict/list → Json(...) wrap
        # - uuid UUID 实例 → 直通 (register_uuid 已注册 adapter)
        type_map = {c: contract.columns[c].dtype for c in columns}
        records = [
            tuple(_prepare_cell(v, type_map[c]) for c, v in zip(columns, row, strict=True))
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

    # ─── Lineage 埋点 (MVP 2.2 Sub2) ───────────────────────

    def _record_lineage(
        self,
        lineage: Lineage,
        valid_df: pd.DataFrame,
        contract: TableContract,
    ) -> _uuid.UUID | None:
        """从 valid_df 提取 PK 列, 补到 lineage.outputs, 落 data_lineage 表.

        策略:
          - 只取每批 valid_df 的 distinct PK 组合 (防同列重复记录)
          - 若 outputs 已有手动传入的 LineageRef, 不覆盖, 末尾 append 自动补的
          - write_lineage 走 Platform primitive, 独立事务内此函数已 post-upsert commit

        Returns:
            lineage_id on success, None on failure (fail-loud logged, 不 raise 破坏上游).
        """
        try:
            # Lineage dataclass frozen=True 不能直接改 outputs, 需重建
            # Import 延迟 (避免 Platform 初始化循环)
            from backend.platform.data.lineage import (
                Lineage as _LineageCls,
            )
            from backend.platform.data.lineage import (
                LineageRef,
                write_lineage,
            )

            pk_cols = [c for c in contract.pk_columns if c in valid_df.columns]
            if pk_cols:
                # 取 distinct PK 组合作为 outputs (防每行一条)
                pk_df = valid_df[pk_cols].drop_duplicates()
                auto_outputs = [
                    LineageRef(
                        table=contract.table_name,
                        pk_values={k: _to_jsonable_scalar(v) for k, v in row.items()},
                    )
                    for row in pk_df.to_dict(orient="records")
                ]
            else:
                auto_outputs = [
                    LineageRef(table=contract.table_name, pk_values={})
                ]

            merged_outputs = list(lineage.outputs) + auto_outputs
            enriched = _LineageCls(
                lineage_id=lineage.lineage_id,
                inputs=lineage.inputs,
                code=lineage.code,
                params=lineage.params,
                timestamp=lineage.timestamp,
                parent_lineage_ids=lineage.parent_lineage_ids,
                outputs=merged_outputs,
                schema_version=lineage.schema_version,
            )
            lid = write_lineage(enriched, self.conn)
            self.conn.commit()
            return lid
        except Exception as e:  # fail-loud, 不阻塞主路径 upsert 已 committed
            logger.error(
                "lineage 埋点失败 (main upsert 已落盘, 不回滚): %s", e, exc_info=True
            )
            return None
