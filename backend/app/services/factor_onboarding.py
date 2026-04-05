"""因子入库服务 — 将审批通过的GP候选因子写入生产环境。

流程:
  1. 从 approval_queue 读取审批通过的因子元数据
  2. 写入 factor_registry（status='new'）
  3. 用 FactorDSL 计算历史因子值 → 写入 factor_values
  4. 计算 Rank IC → 写入 factor_ic_history
  5. 更新 factor_registry gate 统计字段（gate_ic/gate_ir/gate_t）

设计文档:
  - docs/GP_CLOSED_LOOP_DESIGN.md §6.2: 人工审批后的因子入库逻辑
  - docs/DEV_FACTOR_MINING.md: 因子计算规则（预处理顺序+IC定义）
  - docs/QUANTMIND_V2_DDL_FINAL.sql: factor_registry/factor_values/factor_ic_history 表结构

注意:
  - 此服务在 Celery worker 中通过 asyncio.run() 调用（mining_tasks 模式）
  - FactorDSL 计算可能耗时 30-120 秒，必须异步执行
  - PT 代码隔离：不修改 v1.1 信号链路（宪法 §16.2）
  - 因子名冲突时（factor_registry.name 已存在）使用 ON CONFLICT DO UPDATE
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

import asyncpg
import numpy as np
import pandas as pd
import structlog
from scipy import stats as scipy_stats

logger = structlog.get_logger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

# IC 计算周期（与 compute_factor_ic.py 保持一致）
HORIZONS: list[int] = [1, 5, 10, 20]

# 截面有效样本最低要求
MIN_STOCKS: int = 30

# 历史计算起始窗口（年）
DEFAULT_LOOKBACK_YEARS: int = 2


# ---------------------------------------------------------------------------
# 主服务类
# ---------------------------------------------------------------------------


class FactorOnboardingService:
    """将审批通过的因子入库到生产环境。

    所有公共方法均为 async，供 Celery worker 通过 asyncio.run() 调用。
    """

    def __init__(self, db_url: str | None = None) -> None:
        """初始化服务。

        Args:
            db_url: PostgreSQL 连接字符串。None 时从环境变量读取。
        """
        self._db_url = db_url or os.environ.get(
            "DATABASE_URL",
            "postgresql://quantmind:quantmind@localhost:5432/quantmind",
        )

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def onboard_factor(
        self,
        approval_queue_id: int,
    ) -> dict[str, Any]:
        """入库审批通过的因子。

        Args:
            approval_queue_id: approval_queue 表主键 id。

        Returns:
            入库结果摘要：
            {
                "success": bool,
                "factor_name": str,
                "registry_id": str,  # factor_registry UUID
                "factor_values_written": int,
                "ic_rows_written": int,
                "gate_ic": float,
                "gate_t": float,
                "error": str | None,
            }

        Raises:
            ValueError: approval_queue_id 不存在或 status != 'approved'。
        """
        conn = await asyncpg.connect(self._db_url)
        try:
            return await self._onboard_inner(conn, approval_queue_id)
        finally:
            await conn.close()

    async def _onboard_inner(
        self,
        conn: asyncpg.Connection,
        approval_queue_id: int,
    ) -> dict[str, Any]:
        """入库核心逻辑（单连接内顺序执行）。

        Args:
            conn: asyncpg 连接。
            approval_queue_id: approval_queue 主键。

        Returns:
            入库结果摘要。
        """
        # ── Step 1: 读取 approval_queue 记录 ──────────────────────────
        aq_row = await conn.fetchrow(
            """
            SELECT id, run_id, factor_name, factor_expr, ast_hash,
                   gate_result, sharpe_1y, sharpe_5y, backtest_report, status
            FROM approval_queue
            WHERE id = $1
            """,
            approval_queue_id,
        )
        if aq_row is None:
            raise ValueError(f"approval_queue_id={approval_queue_id} 不存在")

        if aq_row["status"] != "approved":
            raise ValueError(
                f"approval_queue_id={approval_queue_id} "
                f"status={aq_row['status']!r}，非 'approved'，无法入库"
            )

        factor_name: str = aq_row["factor_name"]
        factor_expr: str = aq_row["factor_expr"]
        gate_result: dict[str, Any] = (
            json.loads(aq_row["gate_result"]) if aq_row["gate_result"] else {}
        )

        logger.info(
            "因子入库开始: factor_name=%s, expr=%s",
            factor_name,
            factor_expr[:60],
        )

        # ── Step 2: 写入 factor_registry ──────────────────────────────
        registry_id = await self._upsert_factor_registry(
            conn=conn,
            factor_name=factor_name,
            factor_expr=factor_expr,
            gate_result=gate_result,
            run_id=aq_row["run_id"],
            sharpe_1y=float(aq_row["sharpe_1y"]) if aq_row["sharpe_1y"] else None,
        )
        logger.info("factor_registry 写入完成: id=%s", registry_id)

        # ── Step 3: 加载行情数据，计算因子值 ───────────────────────────
        end_date = date.today()
        start_date = end_date - timedelta(days=DEFAULT_LOOKBACK_YEARS * 365 + 60)

        market_data = await self._load_market_data(conn, start_date, end_date)
        if market_data.empty:
            logger.warning("行情数据为空，跳过因子值计算: factor_name=%s", factor_name)
            return {
                "success": False,
                "factor_name": factor_name,
                "registry_id": str(registry_id),
                "factor_values_written": 0,
                "ic_rows_written": 0,
                "gate_ic": None,
                "gate_t": None,
                "error": "行情数据为空",
            }

        # 加载行业数据（symbols.industry_sw1），用于行业中性化
        all_codes = market_data["code"].unique().tolist()
        industry_map = await self._load_industry_map(conn, all_codes)

        factor_values_df = self._compute_factor_values(
            factor_expr=factor_expr,
            market_data=market_data,
            industry_map=industry_map,
        )
        logger.info(
            "因子值计算完成: factor_name=%s, rows=%d",
            factor_name,
            len(factor_values_df),
        )

        # ── Step 4: 写入 factor_values ────────────────────────────────
        fv_written = await self._upsert_factor_values(
            conn=conn,
            factor_name=factor_name,
            factor_values_df=factor_values_df,
        )
        logger.info("factor_values 写入完成: %d 行", fv_written)

        # ── Step 5: 计算 IC，写入 factor_ic_history ───────────────────
        adj_returns_df = self._compute_adj_returns(market_data)
        trading_dates = sorted(market_data["trade_date"].unique().tolist())
        fwd_ret_df = self._compute_forward_returns(adj_returns_df, trading_dates)

        ic_df = self._compute_ic_series(factor_values_df, fwd_ret_df, factor_name)
        ic_written = await self._upsert_ic_history(conn, factor_name, ic_df)
        logger.info("factor_ic_history 写入完成: %d 行", ic_written)

        # ── Step 6: 更新 factor_registry gate 统计 ────────────────────
        gate_ic, gate_ir, gate_t = self._compute_gate_stats(ic_df)
        await conn.execute(
            """
            UPDATE factor_registry
            SET gate_ic = $1, gate_ir = $2, gate_t = $3,
                status = 'active', updated_at = NOW()
            WHERE id = $4
            """,
            gate_ic,
            gate_ir,
            gate_t,
            registry_id,
        )
        logger.info(
            "factor_registry gate 更新完成: factor_name=%s, gate_ic=%.4f, gate_t=%.4f",
            factor_name,
            gate_ic or 0.0,
            gate_t or 0.0,
        )

        return {
            "success": True,
            "factor_name": factor_name,
            "registry_id": str(registry_id),
            "factor_values_written": fv_written,
            "ic_rows_written": ic_written,
            "gate_ic": gate_ic,
            "gate_t": gate_t,
            "error": None,
        }

    # ------------------------------------------------------------------
    # Step 2: factor_registry upsert
    # ------------------------------------------------------------------

    async def _upsert_factor_registry(
        self,
        conn: asyncpg.Connection,
        factor_name: str,
        factor_expr: str,
        gate_result: dict[str, Any],
        run_id: str,
        sharpe_1y: float | None,
    ) -> str:
        """写入或更新 factor_registry。

        使用 ON CONFLICT (name) DO UPDATE 保证幂等性。

        Args:
            conn: asyncpg 连接。
            factor_name: 因子名称（唯一键）。
            factor_expr: FactorDSL 表达式字符串。
            gate_result: Gate G1-G8 检验结果字典。
            run_id: 来源 pipeline_runs.run_id。
            sharpe_1y: approval_queue 中的 sharpe_1y（可选）。

        Returns:
            factor_registry.id（UUID 字符串）。
        """
        hypothesis = gate_result.get("hypothesis") or f"GP自动挖掘: {factor_expr[:100]}"
        row = await conn.fetchrow(
            """
            INSERT INTO factor_registry
                (name, category, direction, expression, hypothesis,
                 source, status, created_at, updated_at)
            VALUES
                ($1, 'alpha', 'auto', $2, $3,
                 'gp', 'new', NOW(), NOW())
            ON CONFLICT (name) DO UPDATE
                SET expression = EXCLUDED.expression,
                    hypothesis  = EXCLUDED.hypothesis,
                    source      = EXCLUDED.source,
                    updated_at  = NOW()
            RETURNING id
            """,
            factor_name,
            factor_expr,
            hypothesis,
        )
        return str(row["id"])

    # ------------------------------------------------------------------
    # Step 3: 行情数据加载
    # ------------------------------------------------------------------

    async def _load_market_data(
        self,
        conn: asyncpg.Connection,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """加载 klines_daily 行情宽表（供 FactorDSL 使用）。

        列: code, trade_date, open, high, low, close, volume, amount,
            adj_factor, is_suspended

        Args:
            conn: asyncpg 连接。
            start_date: 起始日（含，多加 60 日缓冲）。
            end_date: 截止日（含）。

        Returns:
            DataFrame，行=交易记录，供 FactorDSL 按日期分组后使用。
        """
        rows = await conn.fetch(
            """
            SELECT code, trade_date,
                   open, high, low, close, volume, amount,
                   adj_factor, is_suspended
            FROM klines_daily
            WHERE trade_date BETWEEN $1 AND $2
              AND volume > 0
              AND is_suspended = FALSE
              AND close > 0
              AND adj_factor > 0
            ORDER BY code, trade_date
            """,
            start_date,
            end_date,
        )
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(
            rows,
            columns=[
                "code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "adj_factor",
                "is_suspended",
            ],
        )
        for col in ["open", "high", "low", "close", "volume", "amount", "adj_factor"]:
            df[col] = df[col].astype(float)
        logger.info(
            "行情数据加载完成: %d 行, %d 只股票, %s ~ %s",
            len(df),
            df["code"].nunique(),
            start_date,
            end_date,
        )
        return df

    # ------------------------------------------------------------------
    # Step 3: FactorDSL 因子值计算
    # ------------------------------------------------------------------

    def _compute_factor_values(
        self,
        factor_expr: str,
        market_data: pd.DataFrame,
        industry_map: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """用 FactorDSL 按交易日逐截面计算因子值，并应用行业中性化。

        使用 FactorNeutralizer 进行行业+截面双重中性化（铁律2）：
          1. MAD 法 Winsorize（3σ 截断）
          2. 行业内 zscore（申万一级，组内 < 5 时 fallback 截面 zscore）
          3. 全截面 zscore 再标准化

        Args:
            factor_expr: FactorDSL 表达式字符串（如 "ts_mean(close,20)"）。
            market_data: klines_daily 行情 DataFrame（含 code/trade_date 列）。
            industry_map: {code: industry_sw1} 字典，来自 symbols 表。
                          None 或为空时 fallback 到截面 zscore（兼容旧调用）。

        Returns:
            DataFrame with columns [code, trade_date, raw_value, neutral_value]。
        """
        from engines.mining.factor_dsl import FactorDSL  # type: ignore[import]
        from engines.neutralizer import FactorNeutralizer

        dsl = FactorDSL()
        expr_node = dsl.parse(factor_expr)
        neutralizer = FactorNeutralizer()

        # 构建 industry Series（全截面共享，不按日期变化）
        if industry_map:
            industry_series = pd.Series(industry_map, name="industry_sw1")
        else:
            industry_series = pd.Series(dtype=str)

        records: list[dict[str, Any]] = []
        trading_dates = sorted(market_data["trade_date"].unique().tolist())

        for dt in trading_dates:
            day_data = market_data[market_data["trade_date"] == dt].copy()
            if len(day_data) < MIN_STOCKS:
                continue

            day_data = day_data.set_index("code")
            try:
                factor_series = expr_node.evaluate(day_data)
            except Exception as exc:
                logger.debug("FactorDSL 计算异常（跳过该日）: date=%s, error=%s", dt, exc)
                continue

            valid = factor_series.dropna()
            if len(valid) < MIN_STOCKS:
                continue

            # 行业+截面双重中性化（FactorNeutralizer 内部 fallback 到截面 zscore）
            neutral_series = neutralizer.neutralize(
                raw_values=factor_series,
                industry=industry_series,
            )

            for code in valid.index:
                records.append(
                    {
                        "code": code,
                        "trade_date": dt,
                        "raw_value": float(factor_series.get(code, np.nan)),
                        "neutral_value": float(neutral_series.get(code, np.nan))
                        if pd.notna(neutral_series.get(code))
                        else np.nan,
                    }
                )

        return (
            pd.DataFrame(records)
            if records
            else pd.DataFrame(columns=["code", "trade_date", "raw_value", "neutral_value"])
        )

    # ------------------------------------------------------------------
    # Step 3 helper: 加载行业标签
    # ------------------------------------------------------------------

    async def _load_industry_map(
        self,
        conn: asyncpg.Connection,
        codes: list[str],
    ) -> dict[str, str]:
        """从 symbols 表加载申万一级行业标签。

        Args:
            conn: asyncpg 连接。
            codes: 股票代码列表。

        Returns:
            {code: industry_sw1} 字典。industry_sw1 为 NULL 的股票不包含在内。
            加载失败时返回空字典（中性化模块会 fallback 到截面 zscore）。
        """
        if not codes:
            return {}
        try:
            rows = await conn.fetch(
                """
                SELECT code, industry_sw1
                FROM symbols
                WHERE code = ANY($1::text[])
                  AND industry_sw1 IS NOT NULL
                """,
                codes,
            )
            result = {row["code"]: row["industry_sw1"] for row in rows}
            logger.info(
                "行业标签加载完成: %d/%d 只股票有行业标签",
                len(result),
                len(codes),
            )
            return result
        except Exception as exc:
            logger.warning("行业标签加载失败，中性化 fallback 截面 zscore: error=%s", exc)
            return {}

    # ------------------------------------------------------------------
    # Step 4: factor_values upsert
    # ------------------------------------------------------------------

    async def _upsert_factor_values(
        self,
        conn: asyncpg.Connection,
        factor_name: str,
        factor_values_df: pd.DataFrame,
    ) -> int:
        """批量写入 factor_values（幂等 upsert）。

        Args:
            conn: asyncpg 连接。
            factor_name: 因子名称。
            factor_values_df: [code, trade_date, raw_value, neutral_value]。

        Returns:
            写入行数。
        """
        if factor_values_df.empty:
            return 0

        rows = [
            (
                factor_name,
                row["code"],
                row["trade_date"],
                _safe_float(row["raw_value"]),
                _safe_float(row["neutral_value"]),
            )
            for _, row in factor_values_df.iterrows()
        ]

        # asyncpg executemany 批量写入（每批 500 行）
        written = 0
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            await conn.executemany(
                """
                INSERT INTO factor_values
                    (factor_name, code, trade_date, raw_value, neutral_value)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (factor_name, code, trade_date) DO UPDATE
                    SET raw_value     = EXCLUDED.raw_value,
                        neutral_value = EXCLUDED.neutral_value
                """,
                batch,
            )
            written += len(batch)

        return written

    # ------------------------------------------------------------------
    # Step 5a: 复权收益率 + forward return（复用 compute_factor_ic 逻辑）
    # ------------------------------------------------------------------

    def _compute_adj_returns(self, market_data: pd.DataFrame) -> pd.DataFrame:
        """从行情数据计算复权收盘价序列。

        Args:
            market_data: klines_daily 行情 DataFrame。

        Returns:
            DataFrame with columns [code, trade_date, adj_close]。
        """
        df = market_data[["code", "trade_date", "close", "adj_factor"]].copy()
        df["adj_close"] = df["close"] * df["adj_factor"]
        return df[["code", "trade_date", "adj_close"]]

    def _compute_forward_returns(
        self,
        adj_df: pd.DataFrame,
        trading_dates: list[date],
    ) -> pd.DataFrame:
        """计算多期 forward return。

        Args:
            adj_df: [code, trade_date, adj_close]。
            trading_dates: 有序交易日列表。

        Returns:
            DataFrame with columns [code, trade_date, fwd_1d, fwd_5d, fwd_10d, fwd_20d]。
        """
        pivot = adj_df.pivot(index="trade_date", columns="code", values="adj_close")
        pivot = pivot.sort_index()

        result_frames = []
        for h in HORIZONS:
            shifted = pivot.shift(-h)
            fwd_ret = (shifted / pivot) - 1.0
            fwd_ret = fwd_ret.stack().reset_index()
            fwd_ret.columns = pd.Index(["trade_date", "code", f"fwd_{h}d"])
            result_frames.append(fwd_ret)

        merged = result_frames[0]
        for df in result_frames[1:]:
            merged = merged.merge(df, on=["trade_date", "code"], how="outer")

        fwd_cols = [f"fwd_{h}d" for h in HORIZONS]
        return merged.dropna(subset=fwd_cols, how="all")

    # ------------------------------------------------------------------
    # Step 5b: Rank IC 计算
    # ------------------------------------------------------------------

    def _compute_ic_series(
        self,
        factor_values_df: pd.DataFrame,
        fwd_ret_df: pd.DataFrame,
        factor_name: str,
    ) -> pd.DataFrame:
        """按交易日计算 Rank IC（Spearman 相关系数）。

        Args:
            factor_values_df: [code, trade_date, neutral_value]。
            fwd_ret_df: [code, trade_date, fwd_1d, fwd_5d, fwd_10d, fwd_20d]。
            factor_name: 用于日志输出。

        Returns:
            DataFrame with columns [trade_date, ic_1d, ic_5d, ic_10d, ic_20d,
                                     ic_abs_1d, ic_abs_5d, ic_ma20, ic_ma60, decay_level]。
        """
        merged = factor_values_df[["code", "trade_date", "neutral_value"]].merge(
            fwd_ret_df, on=["code", "trade_date"], how="inner"
        )

        if merged.empty:
            logger.warning("IC计算：因子值与forward return无交集: factor_name=%s", factor_name)
            return pd.DataFrame()

        records = []
        for dt in sorted(merged["trade_date"].unique()):
            cross = merged[merged["trade_date"] == dt].dropna(subset=["neutral_value"])
            if len(cross) < MIN_STOCKS:
                continue

            row: dict[str, Any] = {"trade_date": dt}
            for h in HORIZONS:
                col = f"fwd_{h}d"
                valid = cross[["neutral_value", col]].dropna()
                if len(valid) < MIN_STOCKS:
                    row[f"ic_{h}d"] = None
                    continue
                ic_val, _ = scipy_stats.spearmanr(valid["neutral_value"], valid[col])
                row[f"ic_{h}d"] = float(ic_val) if not np.isnan(ic_val) else None

            records.append(row)

        if not records:
            return pd.DataFrame()

        ic_df = pd.DataFrame(records).sort_values("trade_date").reset_index(drop=True)

        # 衍生指标（与 compute_factor_ic.py 保持一致）
        ic_df["ic_abs_1d"] = ic_df["ic_1d"].abs()
        ic_df["ic_abs_5d"] = ic_df["ic_5d"].abs()
        ic_df["ic_ma20"] = ic_df["ic_20d"].rolling(window=20, min_periods=5).mean()
        ic_df["ic_ma60"] = ic_df["ic_20d"].rolling(window=60, min_periods=10).mean()
        ic_df["decay_level"] = _compute_decay_level(ic_df)

        logger.info(
            "IC 计算完成: factor_name=%s, %d 个交易日",
            factor_name,
            len(ic_df),
        )
        return ic_df

    # ------------------------------------------------------------------
    # Step 5c: factor_ic_history upsert
    # ------------------------------------------------------------------

    async def _upsert_ic_history(
        self,
        conn: asyncpg.Connection,
        factor_name: str,
        ic_df: pd.DataFrame,
    ) -> int:
        """批量写入 factor_ic_history（幂等 upsert）。

        Args:
            conn: asyncpg 连接。
            factor_name: 因子名称。
            ic_df: enriched IC DataFrame。

        Returns:
            写入行数。
        """
        if ic_df.empty:
            return 0

        rows = [
            (
                factor_name,
                row["trade_date"],
                _safe_float(row.get("ic_1d")),
                _safe_float(row.get("ic_5d")),
                _safe_float(row.get("ic_10d")),
                _safe_float(row.get("ic_20d")),
                _safe_float(row.get("ic_abs_1d")),
                _safe_float(row.get("ic_abs_5d")),
                _safe_float(row.get("ic_ma20")),
                _safe_float(row.get("ic_ma60")),
                str(row.get("decay_level", "unknown")),
            )
            for _, row in ic_df.iterrows()
        ]

        written = 0
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            await conn.executemany(
                """
                INSERT INTO factor_ic_history
                    (factor_name, trade_date, ic_1d, ic_5d, ic_10d, ic_20d,
                     ic_abs_1d, ic_abs_5d, ic_ma20, ic_ma60, decay_level)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (factor_name, trade_date) DO UPDATE SET
                    ic_1d      = EXCLUDED.ic_1d,
                    ic_5d      = EXCLUDED.ic_5d,
                    ic_10d     = EXCLUDED.ic_10d,
                    ic_20d     = EXCLUDED.ic_20d,
                    ic_abs_1d  = EXCLUDED.ic_abs_1d,
                    ic_abs_5d  = EXCLUDED.ic_abs_5d,
                    ic_ma20    = EXCLUDED.ic_ma20,
                    ic_ma60    = EXCLUDED.ic_ma60,
                    decay_level = EXCLUDED.decay_level
                """,
                batch,
            )
            written += len(batch)

        return written

    # ------------------------------------------------------------------
    # Step 6: gate 统计
    # ------------------------------------------------------------------

    def _compute_gate_stats(
        self, ic_df: pd.DataFrame
    ) -> tuple[float | None, float | None, float | None]:
        """计算 gate_ic / gate_ir / gate_t（与 compute_factor_ic.py 算法一致）。

        Args:
            ic_df: enriched IC DataFrame（含 ic_20d 列）。

        Returns:
            (gate_ic, gate_ir, gate_t)，数据不足时返回 (None, None, None)。
        """
        if ic_df.empty or "ic_20d" not in ic_df.columns:
            return None, None, None

        ic_vals = ic_df["ic_20d"].dropna()
        if len(ic_vals) < 2:
            return None, None, None

        ic_mean = float(ic_vals.mean())
        ic_std = float(ic_vals.std(ddof=1))
        n = len(ic_vals)

        if ic_std < 1e-9:
            return float(round(ic_mean, 6)), 0.0, 0.0

        gate_ic = float(round(ic_mean, 6))
        gate_ir = float(round(ic_mean / ic_std, 4))
        gate_t = float(round(ic_mean / (ic_std / np.sqrt(n)), 4))
        return gate_ic, gate_ir, gate_t


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> float | None:
    """将值安全转换为 float，NaN/None 返回 None。

    Args:
        val: 任意值。

    Returns:
        float 或 None。
    """
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _compute_decay_level(ic_df: pd.DataFrame) -> str:
    """计算 IC 衰减速度标签（与 compute_factor_ic.py 逻辑一致）。

    Args:
        ic_df: enriched IC DataFrame。

    Returns:
        'fast' | 'medium' | 'slow' | 'stable' | 'unknown'
    """
    ic_means: dict[int, float] = {}
    for h in HORIZONS:
        col = f"ic_{h}d"
        if col in ic_df.columns:
            vals = ic_df[col].dropna().abs()
            if len(vals) > 0:
                ic_means[h] = float(vals.mean())

    if len(ic_means) < 2 or ic_means.get(1, 0.0) < 1e-9:
        return "unknown"

    ic1 = ic_means.get(1, 0.0)
    ic5 = ic_means.get(5, 0.0)
    ic20 = ic_means.get(20, 0.0)

    decay_5 = (ic1 - ic5) / ic1
    decay_20 = (ic1 - ic20) / ic1

    if decay_5 > 0.5:
        return "fast"
    if decay_20 > 0.5:
        return "medium"
    if decay_20 > 0.1:
        return "slow"
    return "stable"
