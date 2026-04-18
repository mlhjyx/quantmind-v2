"""MVP 2.3 Sub1 PR C1 · 内建 data_loader 参考实现.

`PlatformBacktestRunner.data_loader` 接受任何 `(config, start, end) -> (factor_df, price_data,
bench_df)` callable. PR B 未提供参考实现, PR C1 补 2 个开箱即用 loader 替 Platform runner
交付一整套 SDK:

  1. `ParquetBaselineLoader` — 从 `cache/baseline/*.parquet` 加载冻结基线 (regression / 研究用,
     铁律 15 可复现锚点).
  2. `BacktestCacheLoader` — 从 `cache/backtest/YEAR/*.parquet` 按年分区缓存加载 (生产 YAML 驱动
     回测, Step 5 Parquet 缓存系统).

关联铁律:
  - 14 (engine 不做数据清洗) / 15 (config_hash 复现) / 31 (Platform 纯计算 — loader 不触 DB/HTTP)

设计原则 (PR C1):
  - Loader 不跨 Platform framework import (无 `backend.platform.data.*`), 避免触发
    `test_frameworks_do_not_cross_import` 硬门.
  - Loader 只做数据装配 (Parquet → DataFrame), 不做 fallback, 不做单位转换
    (铁律 17 DataPipeline 统一管道). 文件缺失显式 FileNotFoundError raise.
  - DAL-backed / DB-backed loader 推 PR C2 (需走 app 层 gateway 避免跨 framework 违规).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from .interface import BacktestConfig

# Module-level import (PR C1 review P1-a fix): patch target "patch where used" 规则对齐.
# 之前 lazy import 导致 tests 必须 patch 源 module (`data.parquet_cache`), 一旦
# 未来 refactor 此处为 module-level 其他导入路径, tests 会 silently 继续 patch 旧位置
# 却不报错. 改 try/except 挂 module-level 可选依赖, ImportError 延到 __call__ raise
# 清晰错误 (test collection 仍不加载 — 仅类对象引用, 不实例化 BacktestDataCache).
try:
    from data.parquet_cache import BacktestDataCache as _BacktestDataCache
except ImportError:  # pragma: no cover — PYTHONPATH 异常才触
    _BacktestDataCache = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ParquetBaselineLoader:
    """从 `cache/baseline/` 冻结 Parquet 基线加载 (regression / 研究 / 铁律 15).

    文件命名 (PR A Phase B M2 已固化):
      cache/baseline/factor_data_{years}yr.parquet   (必选)
      cache/baseline/price_data_{years}yr.parquet    (必选)
      cache/baseline/benchmark_{years}yr.parquet     (可选, 不存在返 None)

    Args:
      baseline_dir: `cache/baseline/` 目录绝对路径 (调用方传, 不硬编码).
      years: 5 / 12 (决定后缀 `_5yr` / `_12yr`).

    Raises (__call__):
      FileNotFoundError: factor_data / price_data 文件不存在 (benchmark 可选).
    """

    baseline_dir: Path
    years: int

    def __call__(
        self,
        config: BacktestConfig,  # noqa: ARG002 — 冻结基线不按 config 过滤
        start: date,  # noqa: ARG002 — 冻结基线窗口由 years 决定, 非 start
        end: date,  # noqa: ARG002 — 同上
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
        """Loader callable 协议: `(config, start, end) -> (factor_df, price_data, bench_df)`.

        config / start / end 参数保留匹配 runner 注入签名; ParquetBaselineLoader 实际
        不使用 (冻结基线的时间窗由 years 决定, 非 config 动态). 调用方应确保 years
        对齐 config.start ~ config.end 的目标窗口 (e.g. FULL_5Y → years=5).

        PR C1 review P2-e fix: 参数 `noqa: ARG002` 显式标注 unused, 未来若新增窗口
        过滤逻辑应同时移除 noqa 注释 (防 silent 失配).
        """
        suffix = f"{self.years}yr"
        factor_path = self.baseline_dir / f"factor_data_{suffix}.parquet"
        price_path = self.baseline_dir / f"price_data_{suffix}.parquet"
        bench_path = self.baseline_dir / f"benchmark_{suffix}.parquet"

        if not factor_path.exists():
            raise FileNotFoundError(f"Baseline factor data missing: {factor_path}")
        if not price_path.exists():
            raise FileNotFoundError(f"Baseline price data missing: {price_path}")

        factor_df = pd.read_parquet(factor_path)
        price_data = pd.read_parquet(price_path)
        bench_df = pd.read_parquet(bench_path) if bench_path.exists() else None

        return factor_df, price_data, bench_df


@dataclass(frozen=True)
class BacktestCacheLoader:
    """从 `cache/backtest/YEAR/*.parquet` 按年分区缓存加载 (Step 5 Parquet 系统).

    委托 `data.parquet_cache.BacktestDataCache` 的 `is_valid` / `load` 接口.
    生产 YAML 驱动回测 (run_backtest.py / profile_backtest.py) 走此 loader.

    Args:
      cache_dir: 可选 `cache/backtest/` 目录 (默认走 `BacktestDataCache` 内置路径).
                 保留参数方便测试注入临时目录.

    Raises (__call__):
      ValueError: 缓存对 (start, end) 范围不可用 (需先跑 `scripts/build_backtest_cache.py`).
    """

    cache_dir: Path | None = None

    def __call__(
        self,
        config: BacktestConfig,  # noqa: ARG002 — BacktestDataCache 仅按 start/end 查
        start: date,
        end: date,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
        """Loader callable 协议同 ParquetBaselineLoader."""
        if _BacktestDataCache is None:  # pragma: no cover
            raise ImportError(
                "data.parquet_cache 不可用. 检查 PYTHONPATH / `backend/` 目录是否在 sys.path."
            )

        cache = (
            _BacktestDataCache(cache_dir=self.cache_dir) if self.cache_dir else _BacktestDataCache()
        )
        if not cache.is_valid(start, end):
            raise ValueError(
                f"BacktestDataCache invalid for {start}~{end}. "
                f"Run `python scripts/build_backtest_cache.py` first (Step 5)."
            )
        data = cache.load(start, end)
        factor_df = data["factor_data"]
        price_data = data["price_data"]
        bench_df = data.get("benchmark")
        return factor_df, price_data, bench_df


__all__ = ["BacktestCacheLoader", "ParquetBaselineLoader"]
