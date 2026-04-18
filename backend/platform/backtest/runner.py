"""MVP 2.3 Sub1 PR B · PlatformBacktestRunner concrete — 包而不改 run_hybrid_backtest.

设计:
  - "包而不改": 内部仍调 `engines.backtest.runner.run_hybrid_backtest`, 仅 wrap 成 Platform OO 接口.
  - 降 blast radius: 不重写计算逻辑 (铁律 14/18), 仅负责编排 / hash / cache / 血缘 / 聚合.
  - Mode dispatch: QUICK_1Y / FULL_5Y / FULL_12Y / WF_5FOLD / LIVE_PT 决定 start/end 覆盖.
  - Cache: 同 config_hash 命中走 `registry.get_by_hash`, LIVE_PT 除外 (实盘每次强制 re-run).
  - Lineage (MVP 2.2 U3): 构造 `Lineage` 传给 `DataPipeline.ingest`, 自动回填 `lineage_id` 到 result.

关联铁律: 14 (engine 纯计算) / 15 (config_hash 复现) / 17 (DataPipeline 入库) / 31 (Platform 纯计算) / 38.
关联 ADR-007: 字段名映射 (config_hash → config_yaml_hash 等) 在 DBBacktestRegistry 层处理.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from backend.platform._types import BacktestMode

from .interface import BacktestConfig, BacktestRegistry, BacktestResult, BacktestRunner

if TYPE_CHECKING:
    from backend.platform.data.lineage import Lineage


# ─── Mode → 时间窗口映射 ────────────────────────────────────────

_MODE_TO_YEARS: dict[BacktestMode, int | None] = {
    BacktestMode.QUICK_1Y: 1,  # AI 闭环内循环淘汰
    BacktestMode.FULL_5Y: 5,  # 标准 5 年 (regression anchor)
    BacktestMode.FULL_12Y: 12,  # 多 regime 长周期
    BacktestMode.WF_5FOLD: None,  # WF 走 config.start/end 完整窗, 不 override
    BacktestMode.LIVE_PT: None,  # 实盘走 config.start/end, 不 cache
}


class PlatformBacktestRunner(BacktestRunner):
    """BacktestRunner concrete (MVP 2.3 PR B).

    Args:
      registry: BacktestRegistry 实例 (DBBacktestRegistry 或 mock).
      data_loader: 可选 callable(config, start, end) -> (factor_df, price_data, bench_df).
                   留 PR C 迁 scripts 时注入 DAL 或 parquet 加载; PR B 默认 None, 走 engine 调用方自备数据.
      conn: psycopg2 连接 (传给 engine size-neutral 需要 ln_mcap). 可 None (non-SN backtest).
    """

    def __init__(
        self,
        registry: BacktestRegistry,
        data_loader: Any | None = None,
        conn: Any | None = None,
    ) -> None:
        self._registry = registry
        self._data_loader = data_loader
        self._conn = conn

    # ─── 公共入口 (BacktestRunner.run abstract 实现) ──────────

    def run(self, mode: BacktestMode, config: BacktestConfig) -> BacktestResult:
        """执行一次回测 (铁律 15: config_hash + git_commit 必录入).

        流程:
          1. config_hash (sha256 of sorted JSON)
          2. Cache 查 (LIVE_PT 除外)
          3. Mode 应用 (start/end override)
          4. 数据加载 (via data_loader)
          5. Engine 运行 (run_hybrid_backtest 包而不改)
          6. 指标聚合 (engines/metrics PerformanceReport)
          7. Lineage 构造 (MVP 2.2 U3)
          8. Registry 写入 (log_run → DataPipeline.ingest)
          9. 返回 BacktestResult (lineage_id 回填)
        """
        config_hash = self._compute_config_hash(config)
        git_commit = self._get_git_commit()

        # Cache hit (LIVE_PT always re-run — 实盘每次新信号)
        if mode != BacktestMode.LIVE_PT:
            cached = self._registry.get_by_hash(config_hash)
            if cached is not None:
                return cached

        # Mode → start/end 应用
        start_date, end_date = self._apply_mode(config, mode)

        # 数据加载 (允许注入, PR C 迁 scripts 时接 DAL 或 parquet)
        if self._data_loader is None:
            raise NotImplementedError(
                "PlatformBacktestRunner requires data_loader callable (config, start, end) -> "
                "(factor_df, price_data, bench_df). PR C 迁 scripts 时注入 DAL 或 parquet loader."
            )
        factor_df, price_data, bench_df = self._data_loader(config, start_date, end_date)

        # Engine 运行 (包而不改 run_hybrid_backtest)
        directions = self._factor_directions(config.factor_pool)
        engine_config = self._build_engine_config(config)

        from engines.backtest.runner import run_hybrid_backtest

        started_at = datetime.now(UTC)
        engine_result = run_hybrid_backtest(
            factor_df=factor_df,
            directions=directions,
            price_data=price_data,
            config=engine_config,
            benchmark_data=bench_df,
            conn=self._conn,
        )
        elapsed_sec = int((datetime.now(UTC) - started_at).total_seconds())

        # 指标聚合 (reuse engines/metrics PerformanceReport)
        perf = engine_result.metrics()

        # Lineage 构造 (MVP 2.2 U3)
        lineage = self._build_lineage(config, git_commit, mode, config_hash, start_date, end_date)

        # 构造 Platform BacktestResult (lineage_id 待 registry 回填)
        run_id = uuid4()
        platform_result = BacktestResult(
            run_id=run_id,
            config_hash=config_hash,
            git_commit=git_commit or "",
            sharpe=float(perf.sharpe_ratio),
            annual_return=float(perf.annual_return),
            max_drawdown=float(perf.max_drawdown),
            total_return=float(perf.total_return),
            trades_count=int(perf.total_trades),
            metrics=perf.to_dict(),
            # lineage_id=None (registry.log_run 回填)
        )

        # Registry 写入 + lineage_id 回填
        lineage_id = self._registry.log_run(
            config=config,
            result=platform_result,
            artifact_paths={},  # PR B 不处理 artifact, 推 PR C/Sub2
            mode=mode,
            elapsed_sec=elapsed_sec,
            lineage=lineage,
            perf=perf,
            start_date=start_date,
            end_date=end_date,
        )
        return replace(platform_result, lineage_id=lineage_id)

    # ─── 内部 helpers ───────────────────────────────────────

    @staticmethod
    def _compute_config_hash(config: BacktestConfig) -> str:
        """sha256(sorted JSON of asdict(config)). 同 config 两次必同 hash (铁律 15)."""
        s = json.dumps(asdict(config), sort_keys=True, default=str)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    @staticmethod
    def _get_git_commit() -> str | None:
        """获取 HEAD short SHA. Dirty working tree 或非 git repo 返 None."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short=40", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return None

    @staticmethod
    def _apply_mode(config: BacktestConfig, mode: BacktestMode) -> tuple[date, date]:
        """Mode → start/end 窗口映射. QUICK/FULL 基于 config.end 倒推, WF/LIVE 原样."""
        years = _MODE_TO_YEARS.get(mode)
        if years is None:
            # WF_5FOLD / LIVE_PT: 原样沿用 config.start/end
            return config.start, config.end

        end_date = config.end
        start_date = date(end_date.year - years, end_date.month, min(end_date.day, 28))
        return start_date, end_date

    @staticmethod
    def _factor_directions(factor_pool: tuple[str, ...]) -> dict[str, int]:
        """Placeholder: 真实实现走 DAL.read_registry(status='active') 查 direction.

        PR B 占位返 +1 (等 PR C 迁 scripts 时走 DAL).
        """
        return dict.fromkeys(factor_pool, 1)

    @staticmethod
    def _build_engine_config(config: BacktestConfig) -> Any:
        """Platform BacktestConfig → Engine BacktestConfig 映射 (ADR-007 tech debt 之一).

        映射点:
          - capital (Decimal str) → initial_capital (float)
          - top_n → top_n (直传)
          - rebalance_freq → rebalance_freq (直传, daily/weekly/monthly)
          - benchmark ("csi300"/"none") → benchmark_code ("000300.SH"/"")
          - cost_model ("simplified"/"full") → slippage_config / historical_stamp_tax
        """
        from engines.backtest.config import BacktestConfig as EngineBacktestConfig

        bench_code = "000300.SH" if config.benchmark == "csi300" else ""
        historical_tax = config.cost_model == "full"

        return EngineBacktestConfig(
            initial_capital=float(config.capital),
            top_n=config.top_n,
            rebalance_freq=config.rebalance_freq,
            benchmark_code=bench_code,
            historical_stamp_tax=historical_tax,
        )

    def _build_lineage(
        self,
        config: BacktestConfig,
        git_commit: str | None,
        mode: BacktestMode,
        config_hash: str,
        start_date: date,
        end_date: date,
    ) -> Lineage:
        """构造 MVP 2.2 U3 血缘记录 (inputs + code + params).

        outputs 由 DataPipeline.ingest 自动补 (run_id PK).
        """
        from backend.platform.data.lineage import CodeRef, Lineage, LineageRef

        inputs: list[LineageRef] = [
            LineageRef(
                table="factor_values",
                pk_values={
                    "factor_pool": list(config.factor_pool),
                    "start": str(start_date),
                    "end": str(end_date),
                },
            ),
            LineageRef(
                table="klines_daily",
                pk_values={"start": str(start_date), "end": str(end_date)},
            ),
        ]
        if config.benchmark and config.benchmark != "none":
            inputs.append(
                LineageRef(
                    table="index_daily",
                    pk_values={
                        "benchmark": config.benchmark,
                        "start": str(start_date),
                        "end": str(end_date),
                    },
                )
            )

        return Lineage(
            inputs=inputs,
            code=CodeRef(
                git_commit=git_commit or "",
                module="backend.platform.backtest.runner",
                function="PlatformBacktestRunner.run",
            ),
            params={
                "mode": mode.value,
                "config_hash": config_hash,
                "universe": config.universe,
                "top_n": config.top_n,
                "rebalance_freq": config.rebalance_freq,
                "size_neutral_beta": config.size_neutral_beta,
                "industry_cap": config.industry_cap,
            },
        )


__all__ = ["PlatformBacktestRunner"]
