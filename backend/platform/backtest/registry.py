"""MVP 2.3 Sub1 PR B · DBBacktestRegistry concrete — backtest_run DB 自动记录.

设计 (ADR-007 沿用老表):
  - 老表 `backtest_run` (7 行历史 + 4 FK 依赖表) 不动, PR A ALTER ADD 3 新列 (mode / lineage_id / extra_decimals).
  - `log_run` 通过 `DataPipeline.ingest(df, BACKTEST_RUN, lineage=lineage)` 写入 (铁律 17).
  - Lineage 自动回填 `lineage_id` 到 `IngestResult.lineage_id`, 返给 Runner.
  - 字段映射 (Platform concept → 老表列名):
      * config_hash → config_yaml_hash
      * factor_pool → factor_list (text_array)
      * config (asdict) → config_json (jsonb)
      * metrics (PerformanceReport) → 独立 DECIMAL 列 (sharpe/mdd/...)
  - `get_by_hash`: 按 `config_yaml_hash` 查最近一条, 重构 BacktestResult.
  - `list_recent`: 按 `created_at DESC` 排序, LIMIT N.

关联铁律: 15 / 17 / 22 / 25 / 38.
关联 ADR-007: 字段名映射 Follow-up 推 MVP 3.x Clean-up RENAME COLUMN.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pandas as pd

from backend.platform._types import BacktestMode

from .interface import BacktestConfig, BacktestRegistry, BacktestResult

if TYPE_CHECKING:
    from datetime import date

    from backend.platform.data.lineage import Lineage


# SELECT 字段顺序 (get_by_hash / list_recent 重构 BacktestResult 用)
_SELECT_COLS = [
    "run_id",
    "config_yaml_hash",
    "git_commit",
    "sharpe_ratio",
    "annual_return",
    "max_drawdown",
    "total_trades",
    "calmar_ratio",
    "sortino_ratio",
    "information_ratio",
    "beta",
    "win_rate",
    "profit_loss_ratio",
    "annual_turnover",
    "max_consecutive_loss_days",
    "sharpe_ci_lower",
    "sharpe_ci_upper",
    "avg_overnight_gap",
    "position_deviation",
    "excess_return",
    "lineage_id",
]
_SELECT_SQL = ", ".join(_SELECT_COLS)


class DBBacktestRegistry(BacktestRegistry):
    """BacktestRegistry concrete 走 PostgreSQL + DataPipeline.ingest (MVP 2.3 PR B).

    Args:
      pipeline: DataPipeline 实例 (含 psycopg2 conn). 可 None, 懒初始化.
      conn: psycopg2 连接 (给 pipeline 或 cursor 查询用).
    """

    def __init__(self, pipeline: Any | None = None, conn: Any | None = None) -> None:
        self._pipeline = pipeline
        self._conn = conn

    @property
    def pipeline(self) -> Any:
        """懒初始化 DataPipeline (若 __init__ 没传)."""
        if self._pipeline is None:
            from app.data_fetcher.pipeline import DataPipeline

            self._pipeline = DataPipeline(self._conn)
        return self._pipeline

    @property
    def conn(self) -> Any:
        """返回 conn (优先 self._conn, 否则 pipeline.conn)."""
        if self._conn is not None:
            return self._conn
        return self.pipeline.conn

    # ─── log_run (铁律 17 DataPipeline 入库) ────────────────────

    def log_run(  # type: ignore[override]
        self,
        config: BacktestConfig,
        result: BacktestResult,
        artifact_paths: dict[str, str],
        *,
        mode: BacktestMode | None = None,
        elapsed_sec: int | None = None,
        lineage: Lineage | None = None,
        perf: Any | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> UUID:
        """写一行到 backtest_run, 返回 lineage_id (MVP 2.2 U3 集成).

        扩展签名 (vs abstract L114-120):
          - 加 mode/elapsed_sec/lineage/perf/start_date/end_date kwargs
          - artifact_paths 保留以兼容 abstract, 当前 unused (留 PR C/Sub2 处理)
          - 走 Python duck typing, concrete 扩签名不破坏 LSP (调用方 Runner 按 concrete 调)

        映射 (ADR-007):
          - result.config_hash → row["config_yaml_hash"]
          - config.factor_pool → row["factor_list"] (text_array)
          - asdict(config) → row["config_json"] (jsonb)
          - perf.sharpe_ratio → row["sharpe_ratio"] (独立 DECIMAL)

        Returns:
          lineage_id (UUID from data_lineage), 由 DataPipeline.ingest 自动生成 + 回填.
        """
        del artifact_paths  # PR B 不处理, 推 PR C/Sub2

        import json

        from app.data_fetcher.contracts import BACKTEST_RUN

        # asdict(config) 含 date 字段, psycopg2.extras.Json 不支持原生 date,
        # 走 json.dumps(default=str) round-trip 转为 JSON-safe dict (date → ISO str).
        config_dict = json.loads(json.dumps(asdict(config), default=str))

        # lineage_id: 预置到 row (DataPipeline._record_lineage 在 _upsert 后跑, 不会 inject FK 列).
        # Lineage dataclass 已 default_factory=uuid4, 构造时就有 id, 直接 pre-set 即可让 FK 建立.
        row_lineage_id = lineage.lineage_id if lineage is not None else None

        row: dict[str, Any] = {
            # PK + metadata
            "run_id": result.run_id,
            "status": "success",
            # 配置 (字段名映射)
            "config_json": config_dict,
            "factor_list": list(config.factor_pool),
            # 复现锚
            "config_yaml_hash": result.config_hash,
            "git_commit": result.git_commit or None,
            # PR A 新列
            "mode": mode.value if mode is not None else None,
            "lineage_id": row_lineage_id,  # 预置 FK, 避免 NULL
            # 运行元
            "elapsed_sec": elapsed_sec,
            "start_date": start_date,
            "end_date": end_date,
        }

        # 指标 (PerformanceReport → 独立 DECIMAL 列)
        if perf is not None:
            row.update(self._perf_to_columns(perf))

        df = pd.DataFrame([row])

        # 预先 write_lineage: DataPipeline._record_lineage 在 _upsert 之后跑, 但 backtest_run.lineage_id
        # FK 在 INSERT 时立即检查 (非 DEFERRABLE). 若 data_lineage 行不先存在 → FK violation.
        # 同 txn 内先 write 再 ingest, FK 查命中, DataPipeline._record_lineage 会 ON CONFLICT DO NOTHING.
        if lineage is not None:
            from backend.platform.data.lineage import write_lineage as _write_lineage

            _write_lineage(lineage, self.conn)

        ingest_result = self.pipeline.ingest(df, BACKTEST_RUN, lineage=lineage)

        if ingest_result.upserted_rows == 0:
            raise RuntimeError(
                f"DBBacktestRegistry.log_run: 0 rows upserted "
                f"(rejected={ingest_result.rejected_rows}, reasons={ingest_result.reject_reasons})"
            )
        # lineage_id 由 DataPipeline.ingest 自动生成 + 回填 IngestResult.lineage_id
        return ingest_result.lineage_id

    @staticmethod
    def _perf_to_columns(perf: Any) -> dict[str, Any]:
        """PerformanceReport → backtest_run 独立 DECIMAL 列字典.

        映射 engines.metrics.PerformanceReport 字段 → 老表列名 (ADR-007).
        nullable 列允许 None (未算则 NULL).
        """
        ci = getattr(perf, "bootstrap_sharpe_ci", (0.0, 0.0, 0.0))
        return {
            "annual_return": float(perf.annual_return),
            "sharpe_ratio": float(perf.sharpe_ratio),
            "max_drawdown": float(perf.max_drawdown),
            "calmar_ratio": float(perf.calmar_ratio),
            "sortino_ratio": float(perf.sortino_ratio),
            "information_ratio": float(perf.information_ratio),
            "beta": float(perf.beta),
            "win_rate": float(perf.win_rate),
            "profit_loss_ratio": float(perf.profit_loss_ratio),
            "annual_turnover": float(perf.annual_turnover),
            "total_trades": int(perf.total_trades),
            "max_consecutive_loss_days": int(perf.max_consecutive_loss_days),
            "sharpe_ci_lower": float(ci[1]) if len(ci) > 1 else None,
            "sharpe_ci_upper": float(ci[2]) if len(ci) > 2 else None,
            "avg_overnight_gap": float(getattr(perf, "avg_open_gap", 0.0)),
            "position_deviation": float(getattr(perf, "mean_position_deviation", 0.0)),
            # excess_return 老表有, PerformanceReport 无直接字段 — 留 NULL (Sub2 补)
        }

    # ─── get_by_hash ──────────────────────────────────────────

    def get_by_hash(self, config_hash: str) -> BacktestResult | None:
        """按 config_yaml_hash 查最近一条 run (铁律 15 regression anchor)."""
        sql = (
            f"SELECT {_SELECT_SQL} FROM backtest_run "
            f"WHERE config_yaml_hash = %s ORDER BY created_at DESC LIMIT 1"
        )
        with self.conn.cursor() as cur:
            cur.execute(sql, (config_hash,))
            row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_result(row)

    # ─── list_recent ──────────────────────────────────────────

    def list_recent(self, limit: int = 20) -> list[BacktestResult]:
        """按 created_at DESC 排 LIMIT N 条."""
        sql = f"SELECT {_SELECT_SQL} FROM backtest_run ORDER BY created_at DESC LIMIT %s"
        with self.conn.cursor() as cur:
            cur.execute(sql, (int(limit),))
            rows = cur.fetchall()
        return [self._row_to_result(r) for r in rows]

    @staticmethod
    def _row_to_result(row: tuple) -> BacktestResult:
        """tuple (按 _SELECT_COLS 顺序) → BacktestResult.

        Note: total_return 老表无此列, PerformanceReport 算但表不存. 设 0.0 placeholder
              (Sub2 评估是否加列 or 算 from NAV parquet).
        """
        d = dict(zip(_SELECT_COLS, row, strict=True))

        # metrics 字典 (反聚合独立 DECIMAL 列)
        metrics = {
            "sharpe": float(d["sharpe_ratio"]) if d["sharpe_ratio"] is not None else 0.0,
            "annual_return": float(d["annual_return"]) if d["annual_return"] is not None else 0.0,
            "max_drawdown": float(d["max_drawdown"]) if d["max_drawdown"] is not None else 0.0,
            "calmar_ratio": _f(d["calmar_ratio"]),
            "sortino_ratio": _f(d["sortino_ratio"]),
            "information_ratio": _f(d["information_ratio"]),
            "beta": _f(d["beta"]),
            "win_rate": _f(d["win_rate"]),
            "profit_loss_ratio": _f(d["profit_loss_ratio"]),
            "annual_turnover": _f(d["annual_turnover"]),
            "max_consecutive_loss_days": _i(d["max_consecutive_loss_days"]),
            "sharpe_ci_lower": _f(d["sharpe_ci_lower"]),
            "sharpe_ci_upper": _f(d["sharpe_ci_upper"]),
            "avg_overnight_gap": _f(d["avg_overnight_gap"]),
            "position_deviation": _f(d["position_deviation"]),
            "excess_return": _f(d["excess_return"]),
        }

        return BacktestResult(
            run_id=d["run_id"],
            config_hash=d["config_yaml_hash"] or "",
            git_commit=d["git_commit"] or "",
            sharpe=metrics["sharpe"],
            annual_return=metrics["annual_return"],
            max_drawdown=metrics["max_drawdown"],
            total_return=0.0,  # 老表无直接列, placeholder
            trades_count=_i(d["total_trades"]),
            metrics=metrics,
            lineage_id=d["lineage_id"],
        )


def _f(v: Any) -> float:
    """None / Decimal / numeric → float, None 返 0.0."""
    return float(v) if v is not None else 0.0


def _i(v: Any) -> int:
    """None / numeric → int, None 返 0."""
    return int(v) if v is not None else 0


__all__ = ["DBBacktestRegistry"]
