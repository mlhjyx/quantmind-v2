"""因子入库服务 — 将审批通过的GP候选因子写入生产环境。

[S2b Refactor 2026-04-15]
重构原则 (审计 S1-S4 沉淀的铁律对齐):
  - **铁律 17** 数据入库走 DataPipeline — factor_values / factor_ic_history 全部通过
    `DataPipeline.ingest(df, Contract)` 写入, 不直接 INSERT
  - **铁律 19** IC 口径统一 — 所有 IC 必须走 `engines/ic_calculator.py`
    (T+1 入场 / CSI300 超额 / Spearman Rank)
  - **铁律 29** NaN → None — DataPipeline 内置处理, 无需 _safe_float 手动包装
  - **铁律 31** Engine 层纯计算 — factor_onboarding 是 Service, 可以读写 DB,
    但 Engine 层模块 (FactorDSL / FactorNeutralizer) 仍保持纯计算
  - **铁律 32** Service 不 commit — conn.autocommit=True, 每条 SQL 自成事务,
    Service 函数零 `.commit()` 调用
  - **铁律 33** 禁止 silent failure — 所有 except 分支都有 logger.error/warning
    + exc_info=True

流程:
  1. 从 approval_queue 读取审批通过的因子元数据
  2. 写入 factor_registry (status='new')
  3. 用 FactorDSL 计算历史因子值 → DataPipeline → factor_values
  4. ic_calculator 计算多 horizon IC → DataPipeline → factor_ic_history
  5. 更新 factor_registry gate 统计字段 (gate_ic/gate_ir/gate_t)

设计文档:
  - docs/GP_CLOSED_LOOP_DESIGN.md §6.2: 人工审批后的因子入库逻辑
  - docs/DEV_FACTOR_MINING.md: 因子计算规则 (预处理顺序 + IC 定义)
  - docs/QUANTMIND_V2_DDL_FINAL.sql: factor_registry / factor_values /
    factor_ic_history 表结构
  - docs/audit/S2b_factor_onboarding_refactor.md: 本次重构的 finding 闭环记录

调用方:
  - `backend/app/tasks/onboarding_tasks.py` (Celery task, sync, 直接调用)
  - `backend/app/api/pipeline.py` (FastAPI router, 通过 celery send_task 间接调用)
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import structlog

from app.data_fetcher.contracts import FACTOR_IC_HISTORY, FACTOR_VALUES
from app.data_fetcher.pipeline import DataPipeline

logger = structlog.get_logger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

# IC 计算 horizon (与 factor_ic_history schema 对齐)
HORIZONS: list[int] = [1, 5, 10, 20]

# 截面有效样本最低要求 (IC 计算截面少于此数 → 跳过该日)
MIN_STOCKS: int = 30

# 历史计算起始窗口 (年) + 额外缓冲天数 (用于前瞻收益尾巴)
DEFAULT_LOOKBACK_YEARS: int = 2
LOOKBACK_BUFFER_DAYS: int = 60

# CSI300 指数代码 (用于 ic_calculator 计算超额收益, 铁律 19)
BENCHMARK_INDEX_CODE: str = "000300.SH"


# ---------------------------------------------------------------------------
# 主服务类
# ---------------------------------------------------------------------------


class FactorOnboardingService:
    """将审批通过的因子入库到生产环境。

    所有公共方法均为 sync, Celery task 直接调用 (不再走 asyncio.run).
    内部使用 psycopg2 + `conn.autocommit=True` (铁律 32), DataPipeline 处理所有入库。
    """

    def __init__(self, db_url: str | None = None) -> None:
        """初始化服务。

        Args:
            db_url: PostgreSQL 连接字符串。None 时从环境变量读取。

        Raises:
            RuntimeError: 当 db_url 未传且 DATABASE_URL 环境变量也未设置时
                (S2 F65 2026-04-15 禁止弱密码 fallback, 铁律 35)。
        """
        raw_url = db_url or os.environ.get("DATABASE_URL")
        if not raw_url:
            raise RuntimeError(
                "FactorOnboardingService: DATABASE_URL env var not set. "
                "Check backend/.env or pass db_url explicitly."
            )
        # DATABASE_URL 可能带 asyncpg driver 前缀 (历史遗留), psycopg2 需要纯 postgresql://
        if raw_url.startswith("postgresql+asyncpg://"):
            raw_url = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._db_url = raw_url

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def onboard_factor(self, approval_queue_id: int) -> dict[str, Any]:
        """入库审批通过的因子 (sync 主入口)。

        Args:
            approval_queue_id: approval_queue 表主键 id。

        Returns:
            入库结果摘要:
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
        conn = psycopg2.connect(self._db_url)
        # 铁律 32: Service 不显式 commit, autocommit 让每条 SQL 自成事务
        conn.autocommit = True
        try:
            return self._onboard_inner(conn, approval_queue_id)
        finally:
            conn.close()

    def _onboard_inner(
        self,
        conn: psycopg2.extensions.connection,
        approval_queue_id: int,
    ) -> dict[str, Any]:
        """入库核心逻辑 (单连接内顺序执行)。"""
        # ── Step 1: 读取 approval_queue 记录 ──────────────────────────
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, run_id, factor_name, factor_expr, ast_hash,
                       gate_result, sharpe_1y, sharpe_5y, backtest_report, status
                FROM approval_queue
                WHERE id = %s
                """,
                (approval_queue_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"approval_queue_id={approval_queue_id} 不存在")
            colnames = [desc[0] for desc in cur.description]
            aq_row = dict(zip(colnames, row, strict=False))

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
        registry_id = self._upsert_factor_registry(
            conn=conn,
            factor_name=factor_name,
            factor_expr=factor_expr,
            gate_result=gate_result,
            run_id=aq_row["run_id"],
            sharpe_1y=float(aq_row["sharpe_1y"]) if aq_row["sharpe_1y"] else None,
        )
        logger.info("factor_registry 写入完成: id=%s", registry_id)

        # ── Step 3: 加载行情数据, 计算因子值 ───────────────────────────
        end_date = date.today()
        start_date = end_date - timedelta(
            days=DEFAULT_LOOKBACK_YEARS * 365 + LOOKBACK_BUFFER_DAYS
        )

        market_data = self._load_market_data(conn, start_date, end_date)
        if market_data.empty:
            logger.warning("行情数据为空, 跳过因子值计算: factor_name=%s", factor_name)
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

        # 加载行业数据 (symbols.industry_sw1), 用于行业中性化
        all_codes = market_data["code"].unique().tolist()
        industry_map = self._load_industry_map(conn, all_codes)

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

        # ── Step 4: 写入 factor_values (走 DataPipeline, 铁律 17) ─────
        fv_written = self._upsert_factor_values(
            conn=conn,
            factor_name=factor_name,
            factor_values_df=factor_values_df,
        )
        logger.info("factor_values 写入完成: %d 行", fv_written)

        # ── Step 5: IC 计算 (ic_calculator, 铁律 19) + 写入 factor_ic_history ─
        benchmark_df = self._load_csi300(conn, start_date, end_date)
        price_df = self._compute_adj_returns(market_data)

        ic_df = self._compute_ic_multi_horizon(
            factor_values_df=factor_values_df,
            price_df=price_df,
            benchmark_df=benchmark_df,
            factor_name=factor_name,
        )
        ic_written = self._upsert_ic_history(conn, factor_name, ic_df)
        logger.info("factor_ic_history 写入完成: %d 行", ic_written)

        # ── Step 6: 更新 factor_registry gate 统计 ────────────────────
        gate_ic, gate_ir, gate_t = self._compute_gate_stats(ic_df)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE factor_registry
                SET gate_ic = %s, gate_ir = %s, gate_t = %s,
                    status = 'active', updated_at = NOW()
                WHERE id = %s
                """,
                (gate_ic, gate_ir, gate_t, registry_id),
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
    # Step 2: factor_registry upsert (MVP 1.3c: 走 Platform DBFactorRegistry.register)
    # ------------------------------------------------------------------

    def _upsert_factor_registry(
        self,
        conn: psycopg2.extensions.connection,
        factor_name: str,
        factor_expr: str,
        gate_result: dict[str, Any],
        run_id: str,
        sharpe_1y: float | None,
    ) -> str:
        """写入或幂等获取 factor_registry 的 registry_id.

        MVP 1.3c (2026-04-18) 改造: 不再裸 INSERT, 走 Platform DBFactorRegistry.register.
          - G10 hypothesis 强制非空 + 禁占位符 (铁律 13)
          - G9 AST Jaccard > 0.7 拒绝近似因子 (铁律 12)
          - 已注册因子 (DuplicateFactor) 幂等返回现有 id (不重复 INSERT/UPDATE)

        Raises:
            OnboardingBlocked: G9/G10 失败 (hypothesis 占位 / AST 太近似).
                调用方 (Celery onboarding_task) 负责记录到 approval_queue 审计.
        """
        from backend.platform.data.access_layer import PlatformDataAccessLayer
        from backend.platform.factor.interface import FactorSpec
        from backend.platform.factor.registry import (
            DBFactorRegistry,
            DuplicateFactor,
        )

        # Platform Registry 需要独立 conn_factory (每次新开短连接, 不复用 Service 的 conn)
        def _new_conn() -> psycopg2.extensions.connection:
            c = psycopg2.connect(self._db_url)
            c.autocommit = True
            return c

        dal = PlatformDataAccessLayer(_new_conn)
        registry = DBFactorRegistry(dal=dal, conn_factory=_new_conn)

        hypothesis = (gate_result.get("hypothesis") or "").strip()
        direction = int(gate_result.get("direction", 1))
        category = str(gate_result.get("category") or "alpha")
        author = str(gate_result.get("source") or "gp")

        spec = FactorSpec(
            name=factor_name,
            hypothesis=hypothesis,  # 空 / GP占位 会被 G10 拒 (铁律 13)
            expression=factor_expr,
            direction=direction,
            category=category,
            pool="CANDIDATE",  # 新因子进 CANDIDATE, L2 人工晋升到 ACTIVE
            author=author,
        )

        try:
            new_id = registry.register(spec)
            logger.info(
                "factor_registry INSERT via Platform register: "
                "factor_name=%s, id=%s, run_id=%s",
                factor_name, new_id, run_id,
            )
            return str(new_id)
        except DuplicateFactor:
            # 幂等: 已注册 → 返现有 id (保 onboarding 可重跑)
            existing = dal.read_registry()
            row = existing[existing["name"] == factor_name]
            if row.empty:
                raise
            existing_id = str(row.iloc[0]["id"])
            logger.info(
                "factor %s already in registry, returning existing id=%s (idempotent)",
                factor_name, existing_id,
            )
            del sharpe_1y  # sharpe_1y 已在调用方 gate_result 中; MVP 1.3c 不用于 register
            return existing_id

    # ------------------------------------------------------------------
    # Step 3: 行情数据加载
    # ------------------------------------------------------------------

    def _load_market_data(
        self,
        conn: psycopg2.extensions.connection,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """加载 klines_daily 行情宽表 (供 FactorDSL 使用)。

        过滤: volume>0, is_suspended=FALSE, close>0, adj_factor>0。
        """
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT code, trade_date,
                       open, high, low, close, volume, amount,
                       adj_factor, is_suspended
                FROM klines_daily
                WHERE trade_date BETWEEN %s AND %s
                  AND volume > 0
                  AND is_suspended = FALSE
                  AND close > 0
                  AND adj_factor > 0
                ORDER BY code, trade_date
                """,
                (start_date, end_date),
            )
            rows = cur.fetchall()

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

    def _load_industry_map(
        self,
        conn: psycopg2.extensions.connection,
        codes: list[str],
    ) -> dict[str, str]:
        """从 symbols 表加载申万一级行业标签。

        Returns:
            {code: industry_sw1} 字典。industry_sw1 为 NULL 的股票不包含在内。
            加载失败时返回空字典 + logger.warning (铁律 33: 读路径 fallback 有日志)。
        """
        if not codes:
            return {}
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT code, industry_sw1
                    FROM symbols
                    WHERE code = ANY(%s)
                      AND industry_sw1 IS NOT NULL
                    """,
                    (codes,),
                )
                rows = cur.fetchall()
            result = {code: ind for code, ind in rows}
            logger.info(
                "行业标签加载完成: %d/%d 只股票有行业标签",
                len(result),
                len(codes),
            )
            return result
        except Exception as exc:
            logger.warning(
                "行业标签加载失败, 中性化 fallback 截面 zscore: error=%s",
                exc,
                exc_info=True,
            )
            return {}

    def _load_csi300(
        self,
        conn: psycopg2.extensions.connection,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """加载 CSI300 基准行情 (用于 ic_calculator 计算超额收益, 铁律 19)。

        Returns:
            DataFrame [trade_date, close], 按日期升序。
        """
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, close
                FROM index_daily
                WHERE index_code = %s
                  AND trade_date BETWEEN %s AND %s
                ORDER BY trade_date
                """,
                (BENCHMARK_INDEX_CODE, start_date, end_date),
            )
            rows = cur.fetchall()

        if not rows:
            logger.warning(
                "CSI300 基准行情加载为空: %s ~ %s, IC 计算将退化 (铁律 19 可能不成立)",
                start_date,
                end_date,
            )
            return pd.DataFrame(columns=["trade_date", "close"])

        df = pd.DataFrame(rows, columns=["trade_date", "close"])
        df["close"] = df["close"].astype(float)
        logger.info("CSI300 基准行情加载: %d 行", len(df))
        return df

    # ------------------------------------------------------------------
    # Step 3: FactorDSL 因子值计算 (Engine 层调用, 铁律 31)
    # ------------------------------------------------------------------

    def _compute_factor_values(
        self,
        factor_expr: str,
        market_data: pd.DataFrame,
        industry_map: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """用 FactorDSL 按交易日逐截面计算因子值, 并应用行业中性化。

        预处理顺序 (不可变):
          MAD Winsorize → 行业/截面 zscore → clip ±3

        Args:
            factor_expr: FactorDSL 表达式字符串。
            market_data: klines_daily 行情 DataFrame。
            industry_map: {code: industry_sw1} 字典, 来自 symbols 表。

        Returns:
            DataFrame [code, trade_date, raw_value, neutral_value]。
        """
        from engines.mining.factor_dsl import FactorDSL  # type: ignore[import]
        from engines.neutralizer import FactorNeutralizer

        dsl = FactorDSL()
        expr_node = dsl.parse(factor_expr)
        neutralizer = FactorNeutralizer()

        # 构建 industry Series
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
                # 铁律 33: 不 silent, 但是 DSL 单日失败是可恢复的 (下一日继续)
                logger.warning(
                    "FactorDSL 计算异常 (跳过该日): date=%s, expr=%s, error=%s",
                    dt,
                    factor_expr[:50],
                    exc,
                )
                continue

            valid = factor_series.dropna()
            if len(valid) < MIN_STOCKS:
                continue

            # 行业+截面双重中性化
            neutral_series = neutralizer.neutralize(
                raw_values=factor_series,
                industry=industry_series,
            )

            for code in valid.index:
                # 铁律 29: 不写 float NaN (DataPipeline 会二次保护, 但我们这里主动转 None)
                raw_val = factor_series.get(code, np.nan)
                raw_val = None if (isinstance(raw_val, float) and np.isnan(raw_val)) else float(raw_val)

                neutral_val = neutral_series.get(code)
                if neutral_val is not None and pd.notna(neutral_val):
                    neutral_val = float(neutral_val)
                    if np.isnan(neutral_val):
                        neutral_val = None
                else:
                    neutral_val = None

                records.append(
                    {
                        "code": code,
                        "trade_date": dt,
                        "raw_value": raw_val,
                        "neutral_value": neutral_val,
                    }
                )

        return (
            pd.DataFrame(records)
            if records
            else pd.DataFrame(columns=["code", "trade_date", "raw_value", "neutral_value"])
        )

    # ------------------------------------------------------------------
    # Step 4: factor_values 入库 (走 DataPipeline, 铁律 17)
    # ------------------------------------------------------------------

    def _upsert_factor_values(
        self,
        conn: psycopg2.extensions.connection,
        factor_name: str,
        factor_values_df: pd.DataFrame,
    ) -> int:
        """走 DataPipeline 写入 factor_values (铁律 17)。

        DataPipeline 内置:
          - NaN → None (铁律 29)
          - 列对齐 / 值域验证 / ON CONFLICT DO UPDATE (幂等)

        Args:
            conn: psycopg2 连接 (autocommit=True)。
            factor_name: 因子名称。
            factor_values_df: [code, trade_date, raw_value, neutral_value]。

        Returns:
            实际 upsert 行数。
        """
        if factor_values_df.empty:
            return 0

        # 构造符合 FACTOR_VALUES Contract 的 DataFrame
        df = factor_values_df.copy()
        df["factor_name"] = factor_name
        # 列顺序对齐 Contract (非必须, DataPipeline 会重排, 但显式更清晰)
        df = df[["code", "trade_date", "factor_name", "raw_value", "neutral_value"]]

        pipeline = DataPipeline(conn)
        result = pipeline.ingest(df, FACTOR_VALUES)

        if result.rejected_rows > 0:
            logger.warning(
                "factor_values 部分行被拒: factor_name=%s, rejected=%d, reasons=%s",
                factor_name,
                result.rejected_rows,
                result.reject_reasons,
            )

        return result.upserted_rows

    # ------------------------------------------------------------------
    # Step 5a: 复权收盘价 (供 ic_calculator 使用)
    # ------------------------------------------------------------------

    def _compute_adj_returns(self, market_data: pd.DataFrame) -> pd.DataFrame:
        """从行情数据计算复权收盘价序列。

        Args:
            market_data: klines_daily 行情 DataFrame (含 close / adj_factor)。

        Returns:
            DataFrame [code, trade_date, adj_close]。
        """
        df = market_data[["code", "trade_date", "close", "adj_factor"]].copy()
        df["adj_close"] = df["close"] * df["adj_factor"]
        return df[["code", "trade_date", "adj_close"]]

    # ------------------------------------------------------------------
    # Step 5b: 多 horizon IC 计算 (ic_calculator 铁律 19)
    # ------------------------------------------------------------------

    def _compute_ic_multi_horizon(
        self,
        factor_values_df: pd.DataFrame,
        price_df: pd.DataFrame,
        benchmark_df: pd.DataFrame,
        factor_name: str,
    ) -> pd.DataFrame:
        """多 horizon IC 计算 — 走 ic_calculator (铁律 19)。

        对每个 horizon ∈ {1, 5, 10, 20}:
          1. compute_forward_excess_returns — T+1 入场到 T+horizon 卖出的 CSI300 超额
          2. compute_ic_series — 每日截面 Spearman Rank IC

        然后合并成宽表 + 派生 abs/ma/decay_level 列。

        Args:
            factor_values_df: [code, trade_date, neutral_value] 长表。
            price_df: [code, trade_date, adj_close] 长表。
            benchmark_df: [trade_date, close] 长表 (CSI300)。
            factor_name: 因子名 (日志用)。

        Returns:
            DataFrame [trade_date, ic_1d, ic_5d, ic_10d, ic_20d,
                       ic_abs_1d, ic_abs_5d, ic_ma20, ic_ma60, decay_level]。
        """
        from engines.ic_calculator import (
            compute_forward_excess_returns,
            compute_ic_series,
        )

        if factor_values_df.empty or price_df.empty:
            logger.warning(
                "IC 计算输入为空: factor_name=%s, factor_rows=%d, price_rows=%d",
                factor_name,
                len(factor_values_df),
                len(price_df),
            )
            return pd.DataFrame()

        if benchmark_df.empty:
            logger.error(
                "CSI300 基准为空, IC 计算无法进行 (铁律 19 超额收益不可计算): "
                "factor_name=%s",
                factor_name,
            )
            return pd.DataFrame()

        # pivot 因子到宽表 (trade_date × code), 用 neutral_value
        factor_wide = (
            factor_values_df[["trade_date", "code", "neutral_value"]]
            .pivot_table(
                index="trade_date",
                columns="code",
                values="neutral_value",
                aggfunc="first",
            )
            .sort_index()
        )

        # 为每个 horizon 构造 forward excess return + 计算 IC 序列
        ic_frames: dict[str, pd.Series] = {}
        for h in HORIZONS:
            fwd = compute_forward_excess_returns(
                price_df,
                benchmark_df,
                horizon=h,
                price_col="adj_close",
                benchmark_price_col="close",
            )
            ic_series = compute_ic_series(factor_wide, fwd)
            ic_frames[f"ic_{h}d"] = ic_series

        # 合并成 DataFrame, index=trade_date
        ic_df = pd.DataFrame(ic_frames).sort_index()
        if ic_df.empty:
            logger.warning(
                "IC 计算结果为空 (所有 horizon 都没有有效截面): factor_name=%s",
                factor_name,
            )
            return pd.DataFrame()

        ic_df.index.name = "trade_date"
        ic_df = ic_df.reset_index()

        # 派生指标 (与旧版 schema 一致, 保持 factor_ic_history 列兼容)
        ic_df["ic_abs_1d"] = ic_df["ic_1d"].abs()
        ic_df["ic_abs_5d"] = ic_df["ic_5d"].abs()
        ic_df["ic_ma20"] = ic_df["ic_20d"].rolling(window=20, min_periods=5).mean()
        ic_df["ic_ma60"] = ic_df["ic_20d"].rolling(window=60, min_periods=10).mean()
        ic_df["decay_level"] = _compute_decay_level(ic_df)

        logger.info(
            "IC 计算完成 (ic_calculator, 铁律19): factor_name=%s, %d 个交易日",
            factor_name,
            len(ic_df),
        )
        return ic_df

    # ------------------------------------------------------------------
    # Step 5c: factor_ic_history 入库 (走 DataPipeline, 铁律 17)
    # ------------------------------------------------------------------

    def _upsert_ic_history(
        self,
        conn: psycopg2.extensions.connection,
        factor_name: str,
        ic_df: pd.DataFrame,
    ) -> int:
        """走 DataPipeline 写入 factor_ic_history (铁律 17 + 11)。

        Args:
            conn: psycopg2 连接 (autocommit=True)。
            factor_name: 因子名称。
            ic_df: multi-horizon IC DataFrame。

        Returns:
            实际 upsert 行数。
        """
        if ic_df.empty:
            return 0

        # 构造符合 FACTOR_IC_HISTORY Contract 的 DataFrame
        df = ic_df.copy()
        df["factor_name"] = factor_name
        # 列顺序对齐 Contract
        df = df[
            [
                "factor_name",
                "trade_date",
                "ic_1d",
                "ic_5d",
                "ic_10d",
                "ic_20d",
                "ic_abs_1d",
                "ic_abs_5d",
                "ic_ma20",
                "ic_ma60",
                "decay_level",
            ]
        ]

        pipeline = DataPipeline(conn)
        result = pipeline.ingest(df, FACTOR_IC_HISTORY)

        if result.rejected_rows > 0:
            logger.warning(
                "factor_ic_history 部分行被拒: factor_name=%s, rejected=%d, reasons=%s",
                factor_name,
                result.rejected_rows,
                result.reject_reasons,
            )

        return result.upserted_rows

    # ------------------------------------------------------------------
    # Step 6: gate 统计 (纯计算)
    # ------------------------------------------------------------------

    def _compute_gate_stats(
        self, ic_df: pd.DataFrame
    ) -> tuple[float | None, float | None, float | None]:
        """计算 gate_ic / gate_ir / gate_t (基于 ic_20d 列)。

        Args:
            ic_df: multi-horizon IC DataFrame (含 ic_20d 列)。

        Returns:
            (gate_ic, gate_ir, gate_t), 数据不足时返回 (None, None, None)。
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
# 辅助函数 (module-level)
# ---------------------------------------------------------------------------


def _compute_decay_level(ic_df: pd.DataFrame) -> str:
    """计算 IC 衰减速度标签 (基于 ic_1d / ic_5d / ic_20d 的均值比)。

    Args:
        ic_df: multi-horizon IC DataFrame。

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
