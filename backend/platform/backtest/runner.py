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

import calendar
import hashlib
import json
import subprocess
import warnings
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from engines.backtest.config import BacktestConfig as EngineBacktestConfig
from engines.backtest.runner import run_hybrid_backtest

# app.data_fetcher.pipeline 提供 lineage gateway helpers (make_lineage / make_lineage_ref /
# make_code_ref) 避免 Platform backtest → Platform data 跨 framework 违规
# (test_platform_skeleton.test_frameworks_do_not_cross_import 硬门).
# app 层允许 import platform (方向正确), Platform 通过 app helpers 间接访问其他 Platform framework.
from app.data_fetcher.pipeline import make_code_ref, make_lineage, make_lineage_ref
from backend.platform._types import BacktestMode

from .interface import BacktestConfig, BacktestRegistry, BacktestResult, BacktestRunner

# ─── Mode → 时间窗口映射 ────────────────────────────────────────

_MODE_TO_YEARS: dict[BacktestMode, int | None] = {
    BacktestMode.QUICK_1Y: 1,  # AI 闭环内循环淘汰
    BacktestMode.FULL_5Y: 5,  # 标准 5 年 (regression anchor)
    BacktestMode.FULL_12Y: 12,  # 多 regime 长周期
    BacktestMode.WF_5FOLD: None,  # WF 走 config.start/end 完整窗, 不 override
    BacktestMode.LIVE_PT: None,  # 实盘走 config.start/end, 不 cache
}


class PlatformBacktestRunner(BacktestRunner):
    """BacktestRunner concrete (MVP 2.3 PR B + PR C1).

    Args:
      registry: BacktestRegistry 实例 (DBBacktestRegistry 或 mock).
      data_loader: 可选 callable(config, start, end) -> (factor_df, price_data, bench_df).
                   PR C1 提供参考实现 `loaders.ParquetBaselineLoader` /
                   `loaders.BacktestCacheLoader`. 调用方也可传任意符合签名的 callable.
      conn: psycopg2 连接 (传给 engine size-neutral 需要 ln_mcap). 可 None (non-SN backtest).
      direction_provider: 可选 callable(factor_pool) -> {name: direction}. PR C1 新增,
                   替代 PR B placeholder (all +1). 若 None, 保留 placeholder 行为但
                   emit UserWarning (铁律 27: 模糊结论不可接受, 显式 warn 让调用方知情).
                   生产路径必须注入 (e.g. DBFactorRegistry.get_direction 包装 lambda).
    """

    def __init__(
        self,
        registry: BacktestRegistry,
        data_loader: Any | None = None,
        conn: Any | None = None,
        direction_provider: Callable[[tuple[str, ...]], dict[str, int]] | None = None,
    ) -> None:
        self._registry = registry
        self._data_loader = data_loader
        self._conn = conn
        self._direction_provider = direction_provider

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
        directions = self._resolve_directions(config.factor_pool)
        engine_config = self._build_engine_config(config)

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
        """Mode → start/end 窗口映射. QUICK/FULL 基于 config.end 倒推, WF/LIVE 原样.

        PR B review P1 fix: 原 `min(day, 28)` 对 29/30/31 月全错 (只防 Feb leap year),
        用 `calendar.monthrange` 精准取目标月最后一天 (铁律 15 复现: 同 hash 必同窗口).
        """
        years = _MODE_TO_YEARS.get(mode)
        if years is None:
            # WF_5FOLD / LIVE_PT: 原样沿用 config.start/end
            return config.start, config.end

        end_date = config.end
        target_year = end_date.year - years
        target_month = end_date.month
        # 目标月最后一天 (闰年/31-day-month 等情况精准处理)
        last_day_of_target_month = calendar.monthrange(target_year, target_month)[1]
        start_date = date(target_year, target_month, min(end_date.day, last_day_of_target_month))
        return start_date, end_date

    def _resolve_directions(self, factor_pool: tuple[str, ...]) -> dict[str, int]:
        """解析 factor direction. PR C1: 优先走 `direction_provider`, 否则 placeholder + warn.

        生产路径 direction_provider 必传 (e.g. lambda pool: {n: dal_registry.get_direction(n) for n in pool}).
        若 None → UserWarning + 全 +1 placeholder (PR B 行为保留, 仅测试/快速迭代场景).
        """
        if self._direction_provider is not None:
            return dict(self._direction_provider(factor_pool))
        warnings.warn(
            "PlatformBacktestRunner.direction_provider=None — 所有因子 direction 退回 +1 "
            "placeholder. CORE 因子 (turnover_mean_20/volatility_20 = -1) 会信号反向 → "
            "负 alpha 静默产生. 生产路径必须注入 direction_provider (铁律 19/34).",
            UserWarning,
            stacklevel=3,
        )
        return self._factor_directions(factor_pool)

    @staticmethod
    def _factor_directions(factor_pool: tuple[str, ...]) -> dict[str, int]:
        """Placeholder: 全 +1 (不安全). 仅在 direction_provider=None 时走.

        **WARNING (PR B review P1)**: 本方法仅在 `data_loader` 被注入后才会被调用
        (run() L93 守护). 若未来修改 run() 跳过 data_loader 检查, 本 placeholder
        会返所有因子 +1, 导致 CORE 因子方向错误 (turnover_mean_20/volatility_20
        正确方向为 -1) → 信号反向 → 负 alpha 静默产生.
        PR C1 已加 direction_provider kwarg 让调用方注入正确 direction.
        """
        return dict.fromkeys(factor_pool, 1)

    @staticmethod
    def _build_engine_config(config: BacktestConfig) -> Any:
        """Platform BacktestConfig → Engine BacktestConfig 映射 (ADR-007 tech debt 之一).

        映射点:
          - capital (Decimal str) → initial_capital (float, 走 Decimal 中转保精度, 金融铁律)
          - top_n → top_n (直传)
          - rebalance_freq → rebalance_freq (直传, daily/weekly/monthly)
          - benchmark ("csi300"/"none") → benchmark_code ("000300.SH"/"")
          - cost_model ("simplified"/"full") → slippage_config / historical_stamp_tax

        PR B review P1 fix: `float(config.capital)` 对 "9999999.99" IEEE 754 精度丢失,
        走 `Decimal` 中转 (金融金额规则: CLAUDE.md 编码规则 "金融金额用 Decimal").
        """
        bench_code = "000300.SH" if config.benchmark == "csi300" else ""
        historical_tax = config.cost_model == "full"

        return EngineBacktestConfig(
            initial_capital=float(Decimal(config.capital)),
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
    ) -> Any:
        """构造 MVP 2.2 U3 血缘记录 (inputs + code + params).

        outputs 由 DBBacktestRegistry 在 log_run 时追加 (含 backtest_run.run_id).

        走 app.data_fetcher.pipeline 的 lineage gateway helpers 避免跨 framework import 违规
        (PR B review fix).
        """
        inputs = [
            make_lineage_ref(
                "factor_values",
                {
                    "factor_pool": list(config.factor_pool),
                    "start": str(start_date),
                    "end": str(end_date),
                },
            ),
            make_lineage_ref(
                "klines_daily",
                {"start": str(start_date), "end": str(end_date)},
            ),
        ]
        if config.benchmark and config.benchmark != "none":
            inputs.append(
                make_lineage_ref(
                    "index_daily",
                    {
                        "benchmark": config.benchmark,
                        "start": str(start_date),
                        "end": str(end_date),
                    },
                )
            )

        return make_lineage(
            inputs=inputs,
            code=make_code_ref(
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
